"""Retire booking requests nobody answered. SCHEDULED, FLAGGED OFF, FAIL-CLOSED.

WIRED, AND DISABLED BY DEFAULT.

`services/appointment_scheduler.py` runs this as its third job, and `main.py`
creates that scheduler — but only when a flag is on. With
`appointment_expiry_enabled` false, which is the default and every deployment
today, no task exists at all and this module is never reached.

Switching the flag on is gated four ways, and each refuses before anything is
written: the startup guard (`assert_appointment_expiry_activation_ready`)
refuses to boot unless the lock backend answers, the
`appointment_pending_expiry` index is valid, and no PENDING row lacks a usable
stored deadline; and every cycle re-checks the last two, because an index can
be dropped during maintenance and a legacy row can arrive from a restore long
after a boot that passed.

What remains unmet is operational, not code: E1 (the correctness indexes built
and validated in production), E3 (explicit approval for rows that predate
`expires_at`) and E4 (cadence and burst size). See
APPOINTMENT_ROLLOUT_CHECKLIST.md — until E1 holds, a lapsed row is still the
only thing holding its slots, and retiring it under the old, weak
`uniq_pending_slot` would free hours the current guarantee is not yet in place
to re-protect.

FAILING CLOSED IS THE POINT OF THE SIGNATURE

`expire_lapsed_requests()` — a bare call, the one a future scheduler or a
console session would most plausibly make — WRITES NOTHING AND NOTIFIES NOBODY.
Expiring requires `apply=True`, spelled out at the call site. A default that
mutated would mean the difference between inspecting and acting was a keyword
somebody remembered to pass, and this module terminates other people's
appointments.

The report a bare call returns is the same report an applying call returns,
with `applied: False` and nothing written. That is what makes "how many would
this touch?" answerable without a rehearsal that is itself a mutation.

TWO POPULATIONS, AND ONLY ONE OF THEM IS TOUCHED

  1. Rows with a stored `expires_at` — everything booked since the field
     existed. An indexed range read, and the only rows `expire_lapsed_requests`
     will ever write to.

  2. Rows without one, booked before it existed. `survey_legacy_pending` counts
     them and NOTHING ELSE. It is read-only by construction: there is no
     argument that makes it write, because changing the status of rows that
     predate this mechanism is a separate decision that needs its own approval,
     taken against real numbers rather than in the middle of a sweep.

     An earlier version of this module expired those rows in the same pass, off
     a read that always returned the FIRST page. Rows that could not be acted
     on — unassessable, or not yet due — stay at the front of that page for
     ever, so the read never advanced past them and the overdue rows behind
     them were never reached. The survey pages on `_id` for exactly that
     reason.

EVERY WRITE IS VERSION-PINNED. The read and the write are separate statements
and a client may reschedule in between — which moves the deadline and bumps the
version, so the stale expiry matches nothing. A sweep must never be the reason
a request the client just moved into next week disappears.

AND IT IS NO LONGER THE ONLY ENFORCEMENT POINT. `confirm` now refuses a lapsed
request too — checked once in the service for a usable message, and once more
in the CAS against the DATABASE's clock via `$$NOW`, which is what still
decides correctly when the deadline passes between the read and the write.

BOTH ARE GATED ON THE SAME FLAG, `appointment_expiry.expiry_enabled`, and that
is the whole design. Either one alone is a broken state: a sweep without the
confirmation guard leaves a window in which a lawyer accepts a request the
next sweep was about to retire, with the winner decided by timing rather than
policy; a confirmation guard without the sweep leaves a lapsed request neither
confirmable nor expirable — stuck, slots still held, unexplained to both
parties. One flag makes both of those unreachable.

When the two do race, both writes pin `status: pending` and the schedule
version, and the confirmation additionally pins the server-time deadline, so
whichever lands second matches nothing. Exactly one winner, by construction.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.constants import AppointmentStatus, NotificationType
from app.repositories.appointment_repo import AppointmentRepository
from app.services import appointment_expiry as expiry
from app.services.appointment_service import (
    _as_utc,
    _name_for_notice,
    _notify,
    _slot_text,
    schedule_version_of,
)

logger = logging.getLogger(__name__)

appt_repo = AppointmentRepository()

# How many rows one run may retire. A limit rather than "all of them" because
# the first run against an existing deployment meets the entire history of
# unanswered requests at once, and a sweep that notifies thousands of people in
# one burst is an incident whichever way the notifications go.
DEFAULT_LIMIT = 200

# The legacy survey reads more per run than the sweep writes, because counting
# is cheap and the answer is only useful if it covers the population. Bounded
# all the same: an unbounded scan of a growing collection is how a read-only
# tool becomes an outage.
SURVEY_PAGE_SIZE = 500
SURVEY_MAX_PAGES = 40


def _event_id(appt_id: str, recipient_id: str) -> str:
    """One logical event PER RECIPIENT.

    `logical_event_id` is unique GLOBALLY — `uniq_notification_logical_event`
    covers that field alone — so `appointment:{id}:expired` would let whichever
    party was notified first claim the id, and the second notification would be
    silently swallowed as an already-delivered duplicate. The recipient is part
    of the identity because the notification is.
    """
    return f"appointment:{appt_id}:expired:{recipient_id}"


async def _name(user_id: str, cache: dict[str, str], appt_id: str) -> str:
    if user_id not in cache:
        cache[user_id] = await _name_for_notice(
            user_id, "", appt_id=appt_id, transition="expired")
    return cache[user_id]


async def _announce(appt: dict, names: dict[str, str], now: datetime) -> None:
    """Tell BOTH parties, separately and in their own terms.

    The client is told because the request they are waiting on is over, and a
    silent disappearance from their list is indistinguishable from a bug. The
    lawyer is told because a request left their inbox without them acting on
    it, and finding out by noticing an absence is not finding out.

    Neither message blames anyone. Nobody did anything wrong: one person did
    not answer in time, which the wording states as a fact about the request.

    AND NEITHER MESSAGE OFFERS A SLOT THAT NO LONGER EXISTS. A request can lapse
    at its own start time — that is the third term of the deadline — so "the
    time is free again, book it" would, for those, invite the client to book an
    hour that is already in the past. What is true in every case is that the
    request is closed and a new one can be made.
    """
    appt_id = appt["_id"]
    start = _as_utc(appt["scheduled_at"])
    when = _slot_text(appt["scheduled_at"])
    still_bookable = start > now
    lawyer_name = await _name(appt["lawyer_id"], names, appt_id) or "your lawyer"
    client_name = await _name(appt["client_id"], names, appt_id) or "A client"

    to_client = (
        "That time is free again — you can request it, or another one."
        if still_bookable
        else "That time has now passed. You can send a new request for a "
             "later time."
    )
    to_lawyer = (
        "The time has been released."
        if still_bookable
        else "That time has now passed."
    )

    await _notify(
        appt_id, "expired",
        user_id=appt["client_id"],
        type=NotificationType.APPOINTMENT_EXPIRED,
        title="Booking Request Expired",
        body=(f"Your request for {when} with {lawyer_name} was not confirmed "
              f"in time and has been closed. {to_client}"),
        payload={"appointment_id": appt_id},
        logical_event_id=_event_id(appt_id, appt["client_id"]),
    )
    await _notify(
        appt_id, "expired",
        user_id=appt["lawyer_id"],
        type=NotificationType.APPOINTMENT_EXPIRED,
        title="Unanswered Request Closed",
        body=(f"{client_name}'s request for {when} expired before it was "
              f"answered. {to_lawyer}"),
        payload={"appointment_id": appt_id},
        logical_event_id=_event_id(appt_id, appt["lawyer_id"]),
    )


async def expire_lapsed_requests(
    *,
    apply: bool = False,
    now: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """One bounded pass over lapsed PENDING requests that carry a deadline.

    DEFAULTS TO WRITING NOTHING. Without `apply=True` this reports exactly what
    an applying run would retire and touches no row and no recipient.

    Only rows with a STORED `expires_at` are considered. Appointments booked
    before that field existed are not expired here at all — see
    `survey_legacy_pending`, which only counts them.

    The returned counts distinguish the outcomes that matter:

      examined      rows the query returned
      expired       rows moved to EXPIRED (or, without `apply`, that would be)
      not_lapsed    rows whose stored deadline has not passed after all
      unassessable  rows with no usable deadline — left alone
      moved         rows whose version changed under us; somebody else acted
      applied       whether anything was actually written
    """
    # Type annotations do not validate runtime calls. In particular,
    # `apply="false"` is truthy and would otherwise take the write path.
    # Likewise a caller-supplied huge limit must not bypass the batch cap.
    if type(apply) is not bool:
        raise ValueError("apply must be a boolean")
    if type(limit) is not int or not 1 <= limit <= DEFAULT_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {DEFAULT_LIMIT}")

    now = now or datetime.now(timezone.utc)
    report = {"examined": 0, "expired": 0, "not_lapsed": 0,
              "unassessable": 0, "moved": 0, "applied": bool(apply)}

    candidates = await appt_repo.find_lapsed_pending(now, limit)

    names: dict[str, str] = {}
    for appt in candidates:
        report["examined"] += 1

        # Re-asserted in code even though the query already selected on the
        # stored value. The two must agree, and asserting the policy here is
        # what guarantees they do: if they ever diverge, this refuses rather
        # than expiring a row the policy would not have.
        if expiry.deadline_of(appt) is None:
            report["unassessable"] += 1
            continue
        if not expiry.has_lapsed(appt, now):
            report["not_lapsed"] += 1
            continue

        if not apply:
            report["expired"] += 1
            continue

        updated = await appt_repo.expire_pending(
            appt["_id"], schedule_version_of(appt))
        if updated is None:
            # Confirmed, cancelled, or rescheduled between the read and the
            # write. All three mean somebody is dealing with this request, and
            # the sweep's job is precisely to not be that somebody.
            report["moved"] += 1
            continue

        report["expired"] += 1
        await _announce(updated, names, now)

    logger.info(
        "appointment_expiry_sweep examined=%s expired=%s not_lapsed=%s "
        "unassessable=%s moved=%s applied=%s",
        report["examined"], report["expired"], report["not_lapsed"],
        report["unassessable"], report["moved"], report["applied"])
    return report


async def survey_legacy_pending(
    *,
    now: datetime | None = None,
    page_size: int = SURVEY_PAGE_SIZE,
    max_pages: int = SURVEY_MAX_PAGES,
) -> dict:
    """COUNT the pending requests that predate `expires_at`. Writes nothing.

    There is no `apply` here and there is not meant to be one. Changing the
    status of rows that already exist is a separate decision requiring its own
    approval; this exists so that decision can be taken against real numbers
    instead of an estimate.

    It returns COUNTS ONLY — no appointment ids, no parties. The question it
    answers is "how large is this population, and how much of it is overdue",
    and answering it does not require naming anybody's consultation.

    Pages on `_id`, so a page that is entirely unassessable or entirely not-due
    does not stop the scan: the rows that cannot be acted on are exactly the
    ones that would otherwise sit at the front of every read for ever.

      scanned       rows read
      lapsed        rows whose derived deadline has passed
      not_lapsed    rows still inside their derived deadline
      unassessable  rows with no usable created_at/scheduled_at
      pages         pages read
      complete      whether the scan reached the end of the population
    """
    now = now or datetime.now(timezone.utc)
    report = {"scanned": 0, "lapsed": 0, "not_lapsed": 0, "unassessable": 0,
              "pages": 0, "complete": False}

    after_id: str | None = None
    for _ in range(max_pages):
        page = await appt_repo.find_undated_pending_page(page_size, after_id)
        if not page:
            report["complete"] = True
            break

        report["pages"] += 1
        for appt in page:
            report["scanned"] += 1
            if expiry.deadline_of(appt) is None:
                report["unassessable"] += 1
            elif expiry.has_lapsed(appt, now):
                report["lapsed"] += 1
            else:
                report["not_lapsed"] += 1

        # ADVANCE PAST EVERYTHING JUST READ, including the rows this survey
        # could do nothing with. That is the whole difference between a scan
        # and a stuck read.
        after_id = page[-1]["_id"]
        if len(page) < page_size:
            report["complete"] = True
            break

    logger.info(
        "appointment_legacy_survey scanned=%s lapsed=%s not_lapsed=%s "
        "unassessable=%s pages=%s complete=%s",
        report["scanned"], report["lapsed"], report["not_lapsed"],
        report["unassessable"], report["pages"], report["complete"])
    return report


# A guard against the thing this module is most likely to get wrong later.
assert AppointmentStatus.EXPIRED.value == "expired"
