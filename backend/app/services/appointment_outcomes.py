"""Consultations that happened and were never reported on. READ-ONLY.

THE GAP THIS ADDRESSES

A CONFIRMED appointment goes nowhere on its own. Only the lawyer can move it to
COMPLETED or NO_SHOW, and if they never do, it stays `confirmed` for ever — a
meeting in the past that the record still describes as upcoming.

That is not merely untidy. `exists_completed` gates the client's right to
review the lawyer, so a lawyer who never records an outcome silently withholds
that right from the client. The absence of an action removes something from
somebody, and nothing currently surfaces it.

WHAT THIS MODULE DOES, AND WHAT IT REFUSES TO DO

It answers two questions and takes no action on either:

  * `outstanding_outcomes()` — which of ONE lawyer's consultations are waiting
    on them, as a paginated queue they could work through.

  * `survey_outstanding_outcomes()` — how large the backlog is across the whole
    system, in counts alone, so the size of the problem is known before
    anything is built on top of it.

It does NOT complete appointments. Completion is a claim that a consultation
took place, and only a person who was there can make it; inferring it from a
clock would write a fact nobody asserted into the record of a legal engagement,
and would hand out review rights on the strength of a guess. It does not notify
anyone, and it is not wired to a scheduler. Those are separate decisions, and
they need the numbers this module produces before they can sensibly be taken.

THE GRACE PERIOD

`DEFAULT_GRACE` is two hours after `end_at`. A consultation that ran late, or a
lawyer who closes their laptop before filing anything, should not appear in a
queue of neglected work minutes after the scheduled end. The cutoff is always
passed explicitly into the repository, so the rule lives here where it can be
read and varied rather than inside a query.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.constants import AppointmentStatus, NotificationType
from app.core.exceptions import AppValidationError
from app.repositories.appointment_repo import AppointmentRepository

logger = logging.getLogger(__name__)

appt_repo = AppointmentRepository()

# How long after the scheduled end a consultation waits before it counts as
# needing an outcome.
DEFAULT_GRACE = timedelta(hours=2)

# The horizons the survey reports. NESTED, NOT DISJOINT: everything overdue by
# seven days is also overdue by two hours, so the counts are cumulative and the
# keys say so. Reporting them as buckets would invite adding them up.
SURVEY_HORIZONS: tuple[tuple[str, timedelta], ...] = (
    ("over_2h", timedelta(hours=2)),
    ("over_24h", timedelta(hours=24)),
    ("over_7d", timedelta(days=7)),
)

# A page of the queue. Bounded because the first lawyer to open this after a
# year of unreported consultations should not receive all of them at once.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# How many NEW notices one run may actually send. Small on purpose: the first
# real run is the one that could put a notice in front of every lawyer at once,
# and a cap is the difference between a nudge and an incident. Failures do not
# count against it — nothing was sent.
NOTICE_CAP = 25

# And how that cap is DIVIDED. Fresh work and retry work get their own budgets
# because a single shared one is not a fair share of anything: whichever
# population is read first spends it. Ordering fresh rows ahead of retries
# stops old failures starving new consultations, and by itself it creates the
# mirror failure — a steady trickle of new consultations means the retry pass
# is never reached, and a lawyer whose notice failed once is never told at all.
#
# A reservation is the only arrangement that bounds both directions. Unused
# retry budget is NOT lent back to fresh work: the reserve exists precisely for
# the runs where there is plenty of fresh work to do.
FRESH_CAP = 20
RETRY_CAP = 5

# How long a failed notice waits before the next attempt, by attempt count.
#
# Without backoff a permanently unreachable recipient is attempted on every
# run, for ever: the row never leaves the queue, and each run spends part of
# its reserve on an address that will not accept mail. The delay grows, so a
# transient failure is retried within minutes while a persistent one falls back
# to daily — and NOTHING here ever abandons the row. A consultation whose
# lawyer could not be reached is still a consultation nobody has reported an
# outcome for.
RETRY_BACKOFF = (
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(days=1),
)

# How many rows one run will look at while trying to fill that cap. Bounded
# because a scan is not free, and because an unbounded one is how a batch job
# that finds nothing to do still costs something every time it runs.
MAX_SCAN = 500


def cutoff_for(now: datetime | None = None,
               grace: timedelta = DEFAULT_GRACE) -> datetime:
    """The instant before which a finished consultation is overdue an outcome."""
    return (now or datetime.now(timezone.utc)) - grace


async def outstanding_outcomes(
    *,
    lawyer_id: str,
    now: datetime | None = None,
    grace: timedelta = DEFAULT_GRACE,
    page_size: int = DEFAULT_PAGE_SIZE,
    after_end_at: datetime | None = None,
    after_id: str | None = None,
    cutoff: datetime | None = None,
) -> dict:
    """One page of this lawyer's consultations awaiting an outcome.

    Returns the rows, plus the cursor for the next page or None at the end.
    Nothing is written and nobody is notified.

    The cursor is `(end_at, _id)` — the sort key, in full. Handing back an
    offset instead would break precisely when this queue is working: rows leave
    it as outcomes are recorded, every departure shifts the offsets behind it,
    and the next page steps over a row that nobody has seen.

    `cutoff` pins the scan. It is returned in every cursor, so passing the
    whole cursor back is all a caller has to do; supplying a continuation
    without it is refused rather than silently rebased onto a later instant.
    """
    if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise AppValidationError(
            f"page_size must be an integer from 1 to {MAX_PAGE_SIZE}")

    # HALF A CURSOR IS AN ERROR, NOT A FRESH START.
    #
    # An earlier version quietly returned page one for a cursor missing either
    # half. That is the worst of the options: the caller believes it is
    # continuing a scan, and instead re-reads rows it has already handled while
    # never reaching the ones it was walking towards. A caller that has lost
    # half its cursor has lost its position, and it needs to be told so rather
    # than handed a page that looks like progress.
    if (after_end_at is None) != (after_id is None):
        raise AppValidationError(
            "a cursor needs both after_end_at and after_id — one alone cannot "
            "address a position in the (end_at, _id) ordering")

    continuing = after_end_at is not None

    # THE CUTOFF IS PINNED FOR THE WHOLE SCAN, and the cursor carries it.
    #
    # Recomputing it per page would move the queue's edge forward between
    # pages: consultations become due while the scan is in flight, and a moving
    # edge means a walk cannot be said to have covered anything in particular.
    # Pinning it makes one scan a statement about one instant.
    if continuing and cutoff is None:
        raise AppValidationError(
            "continuing a scan requires the cutoff the scan started with — "
            "pass back the whole cursor")
    if cutoff is None:
        cutoff = cutoff_for(now, grace)

    # One more than the page, to learn whether a next page exists without
    # running a second query or a count.
    rows = await appt_repo.find_outstanding_outcomes(
        lawyer_id=lawyer_id,
        cutoff=cutoff,
        limit=page_size + 1,
        after_end_at=after_end_at,
        after_id=after_id,
    )
    has_more = len(rows) > page_size
    page = rows[:page_size]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = {"after_end_at": last["end_at"], "after_id": last["_id"],
                       "cutoff": cutoff}

    return {
        "items": page,
        "next_cursor": next_cursor,
        "cutoff": cutoff,
    }


async def outstanding_outcomes_for_response(
    *,
    lawyer_id: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    after_end_at: datetime | None = None,
    after_id: str | None = None,
    cutoff: datetime | None = None,
) -> dict:
    """The queue as an API response: sanitised rows, named parties, a cursor.

    The raw rows carry `occupied_slots`, the notice markers and anything else
    the collection happens to hold, so they go through the SAME projection
    every other appointment response uses rather than a second one written
    here — a private field added later must not reach a client because this
    path forgot to strip it.

    `for_lawyer=True` is correct and is not a widening: the queue is scoped to
    one lawyer in the query, so every row in it is already theirs, and
    `lawyer_notes` is their own record of their own consultation.

    Names come from one batched read, not two per row.
    """
    from app.services.appointment_service import (
        _enrich, _names_for, _names_from, _sanitize,
    )

    page = await outstanding_outcomes(
        lawyer_id=lawyer_id, page_size=page_size,
        after_end_at=after_end_at, after_id=after_id, cutoff=cutoff)

    rows = page["items"]
    by_id = await _names_for(rows)
    items = [_enrich(_sanitize(row, for_lawyer=True), _names_from(row, by_id))
             for row in rows]

    return {"items": items, "next_cursor": page["next_cursor"],
            "cutoff": page["cutoff"]}


async def survey_outstanding_outcomes(now: datetime | None = None) -> dict:
    """How large the unreported-outcome backlog is. COUNTS ONLY.

    No appointment ids, no party names, no notes, no times of individual
    consultations — three integers and the instant they were measured at. The
    question this answers is "how big is this, and how old", and answering it
    does not require naming anybody's consultation or which lawyer let it sit.

    That restraint is deliberate rather than incidental. This exists so the
    decision about notifying people can be taken against real numbers, and a
    survey that listed who was at fault would be doing part of that job before
    the decision was made.

    Reads only: three counts, executed by the database, returning integers.

    The counts are CUMULATIVE. `over_7d` is a subset of `over_24h`, which is a
    subset of `over_2h`; they are not buckets and must not be summed.
    """
    now = now or datetime.now(timezone.utc)
    report: dict = {"measured_at": now, "cumulative": True}

    for key, horizon in SURVEY_HORIZONS:
        report[key] = await appt_repo.count_outstanding_outcomes(now - horizon)

    logger.info(
        "appointment_outcome_survey over_2h=%s over_24h=%s over_7d=%s",
        report["over_2h"], report["over_24h"], report["over_7d"])
    return report


# ── Step 4: the nudge ─────────────────────────────────────────────────────────
#
# REPORT-ONLY BY DEFAULT. `notify_outstanding_outcomes()` without `apply=True`
# sends nothing, writes nothing, and reports what it would have done.
# Notifying requires that argument at the call site, for the same reason the
# expiry sweep does: this puts messages in front of real people.
#
# It is also NOT WIRED TO ANYTHING. No scheduler runs it and no flag enables
# it. Switching it on is a later, separate decision that needs the survey's
# numbers and an answer to what happens when a lawyer never responds.


def _split_budget(limit: int) -> dict:
    """How one run's cap is divided between fresh work and retries.

    At the default cap the split is the declared one, 20 and 5. A caller that
    asks for a smaller cap — a first cautious run, or a test — gets the same
    PROPORTIONS rather than a reserve that rounds away to nothing, and the
    retry share is never allowed to reach zero while there is more than one
    notice to give: a reserve of zero is not a reserve.
    """
    if limit <= 1:
        # One notice cannot be shared. Fresh work takes it, because a
        # consultation nobody has been told about at all is the worse silence.
        return {"fresh": limit, "retry": 0}
    retry = max(1, round(limit * RETRY_CAP / NOTICE_CAP))
    return {"fresh": limit - retry, "retry": retry}


def _retry_after(attempts: int, now: datetime) -> datetime:
    """When a row that has failed `attempts` times may be tried again.

    The last step repeats for ever rather than escalating without bound: the
    row is never abandoned, merely asked about once a day instead of once a
    run. Nothing in this module drops a consultation because its notice was
    hard to deliver.
    """
    index = min(max(attempts, 1), len(RETRY_BACKOFF)) - 1
    return now + RETRY_BACKOFF[index]


def _notice_event_id(appt_id: str, recipient_id: str) -> str:
    """One logical event per appointment AND recipient.

    `logical_event_id` is unique GLOBALLY — `uniq_notification_logical_event`
    covers that field alone — so an id naming only the appointment would let
    the first recipient claim it and silently swallow anyone else's notice.

    That global uniqueness is also what makes this safe to run twice, or from
    two workers at once: `create_notification` treats the duplicate key as
    SUCCESS and returns the existing row without pushing again. The dedup
    belongs to the database, not to this process, so it survives a crash
    between the send and the progress marker.
    """
    return f"appointment:{appt_id}:outcome_due:{recipient_id}"


def _is_eligible(appt: dict, cutoff: datetime, floor: datetime) -> bool:
    """Re-asserted in code, after the query already selected on it.

    The query and this check must agree, and asserting it here is what
    guarantees they do: if they ever diverge, a row is skipped rather than
    notified on the strength of a filter nobody re-read.
    """
    if appt.get("status") != AppointmentStatus.CONFIRMED.value:
        return False
    end_at = appt.get("end_at")
    if not isinstance(end_at, datetime):
        return False
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    return floor <= end_at < cutoff


async def notify_outstanding_outcomes(
    *,
    activated_at: datetime,
    apply: bool = False,
    now: datetime | None = None,
    grace: timedelta = DEFAULT_GRACE,
    limit: int = NOTICE_CAP,
    max_scan: int = MAX_SCAN,
) -> dict:
    """Nudge lawyers about consultations they have not reported an outcome for.

    DEFAULTS TO SENDING NOTHING. Without `apply=True` this reports exactly what
    an applying run would send and writes nothing — no notices, no progress
    markers, no attempt counters.

    `activated_at` is REQUIRED and has no default. A consultation is eligible
    only if it became due (`end_at` + grace) at or after that instant, so the
    historical backlog — every unreported consultation since the product
    started — is excluded until somebody deliberately moves the boundary. A
    default here would make the first run's blast radius a matter of whatever
    the clock happened to say.

    THE LAWYER ONLY. The client is not told, and that is a deliberate omission
    rather than an oversight: telling a client their lawyer has filed nothing
    invites them to act on a process they have no part in, and the dispute
    route that would give them somewhere to go does not exist yet.

    NOTHING IS COMPLETED. The status is never written. Completion is a claim
    that a consultation took place, and it grants the client's right to review
    the lawyer through `exists_completed` — a right that must come from a
    person saying what happened, not from a clock.

    The counts distinguish what matters:

      scanned   rows the queries returned
      eligible  rows that passed the policy check in code
      sent      notices delivered (or, without `apply`, that would be)
      failed    sends that raised — left unmarked, so they are retried
      stale     rows the lawyer dealt with between the read and the send
      fresh_sent / retry_sent
                how much of each reserved budget the run spent
      applied   whether anything was actually sent
    """
    if type(apply) is not bool:
        raise AppValidationError("apply must be a boolean")
    if type(limit) is not int or not 1 <= limit <= NOTICE_CAP:
        raise AppValidationError(
            f"limit must be an integer from 1 to {NOTICE_CAP}")
    if not isinstance(activated_at, datetime):
        raise AppValidationError(
            "activated_at is required: without it a first run would notify "
            "about every unreported consultation in the system's history")

    now = now or datetime.now(timezone.utc)
    cutoff = cutoff_for(now, grace)
    # A row becomes due at `end_at + grace`, so "became due at or after
    # activation" is `end_at >= activated_at - grace`.
    floor = activated_at - grace

    report = {"scanned": 0, "eligible": 0, "sent": 0, "failed": 0, "stale": 0,
              "fresh_sent": 0, "retry_sent": 0,
              "applied": bool(apply), "activated_at": activated_at,
              "cutoff": cutoff}

    # Rows already handled in THIS run. Without it the retry pass picks up the
    # row the fresh pass just failed on — the failure writes an attempt
    # counter, which is exactly what the retry query selects — and one run
    # would hammer a failing recipient twice in a row while reporting two
    # failures for one consultation. A retry belongs in the NEXT run, when
    # whatever was broken has had a chance to stop being broken.
    handled: set[str] = set()

    # EACH POPULATION SPENDS ITS OWN BUDGET. Fresh work first, so a new
    # consultation is never queued behind an old failure — and a reserve for
    # retries, so a steady stream of new consultations cannot mean a failed
    # notice is never sent at all.
    budgets = _split_budget(limit)
    for retries, budget in ((False, budgets["fresh"]), (True, budgets["retry"])):
        if budget <= 0 or report["scanned"] >= max_scan:
            continue
        spent = 0
        room = min(max_scan - report["scanned"], max(budget * 4, budget))
        candidates = await appt_repo.find_outcome_notice_candidates(
            cutoff=cutoff, floor=floor, limit=room, retries=retries,
            retry_due_by=now if retries else None)

        for appt in candidates:
            if spent >= budget:
                break
            if appt["_id"] in handled:
                continue
            handled.add(appt["_id"])
            report["scanned"] += 1
            if not _is_eligible(appt, cutoff, floor):
                continue
            report["eligible"] += 1
            if not apply:
                spent += 1
                report["sent"] += 1
                continue
            outcome = await _send_notice(appt, now, cutoff, floor)
            report[outcome] += 1
            if outcome in ("sent", "failed"):
                # A failure consumed an attempt on this budget just as surely
                # as a delivery did; not counting it would let one run retry a
                # broken recipient until the scan ran out.
                spent += 1
        report["fresh_sent" if not retries else "retry_sent"] = spent

    logger.info(
        "appointment_outcome_notices scanned=%s eligible=%s sent=%s failed=%s "
        "stale=%s applied=%s", report["scanned"], report["eligible"],
        report["sent"], report["failed"], report["stale"], report["applied"])
    return report


async def _send_notice(
    appt: dict, now: datetime, cutoff: datetime, floor: datetime,
) -> str:
    """One nudge, and the progress marker that follows a successful one.

    Returns "sent", "failed" or "stale".

    "sent" INCLUDES a notice already delivered by an earlier run or another
    worker, which `create_notification` reports as success through the unique
    logical id.

    RE-READ IMMEDIATELY BEFORE SENDING, and this is the completion race rather
    than belt-and-braces. The row in hand was read when the batch started; the
    check in `_is_eligible` examines THAT dict, so a lawyer who records the
    outcome while the run is in flight would still be chased for work they had
    just finished — the check would be inspecting a snapshot of a world that no
    longer exists. Re-reading narrows the window to the moment between this
    read and the send, and costs one query per notice at a cap of 25.

    It cannot be closed completely without claiming the row before sending, and
    a claim that outlived a crash would permanently silence a consultation
    nobody was ever told about. A duplicate nudge is recoverable; a silent one
    is not.

    The marker is written AFTER the send and only after it. A marker written
    first would, if the process died in between, permanently silence a
    consultation nobody was ever told about; this way a crash costs at most a
    duplicate attempt, and the duplicate is absorbed by the unique index.

    A failure is recorded as an ATTEMPT, never as a completed notice: the row
    stays eligible and is retried, merely behind the rows nobody has tried yet.
    """
    from app.services.notification_service import create_notification

    appt_id = appt["_id"]
    lawyer_id = appt["lawyer_id"]

    fresh = await appt_repo.find_by_id(appt_id)
    if fresh is None or not _is_eligible(fresh, cutoff, floor):
        return "stale"

    try:
        await create_notification(
            user_id=lawyer_id,
            type=NotificationType.APPOINTMENT_OUTCOME_NUDGE,
            title="Consultation needs an outcome",
            body=("A consultation you confirmed has finished and no outcome "
                  "has been recorded. Mark it completed, or as a no-show, so "
                  "the record of the consultation is accurate."),
            payload={"appointment_id": appt_id},
            logical_event_id=_notice_event_id(appt_id, lawyer_id),
        )
    except Exception as exc:
        # The class only: driver messages carry URIs, and this runs unattended.
        logger.warning(
            "appointment_outcome_notice_failed appointment_id=%s error=%s",
            appt_id, type(exc).__name__)
        attempts = int(appt.get("outcome_notice_attempts") or 0) + 1
        await appt_repo.record_outcome_notice_attempt(
            appt_id, now, _retry_after(attempts, now))
        return "failed"

    await appt_repo.mark_outcome_notice_sent(appt_id, now)
    return "sent"
