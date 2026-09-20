"""Reminding both parties that a confirmed consultation is coming. DORMANT.

`APPOINTMENT_REMINDER` has existed in `constants.py` since long before this
module and was emitted NOWHERE — a declared notification type that nothing ever
sent. This fills it in, and nothing else: no scheduler runs this, no flag
enables it, and the public entry point sends nothing unless a caller writes
`apply=True` at the call site.

TWO WINDOWS, AND WHY THEY DO NOT OVERLAP

  T-24h   more than 23 hours and at most 24 hours before the start
  T-1h    more than 0 minutes and at most 1 hour before the start

The first is "tomorrow", far enough ahead to rearrange a day around. The second
is "now-ish", close enough to leave for. They are disjoint by construction —
one hour is nowhere near twenty-three — so no appointment is ever selected by
both in one run, and the two reminders say different things to a recipient who
receives both over the course of a day.

An appointment whose start has PASSED is in neither window: `> 0 minutes`
excludes it. A reminder about a consultation that has already begun is not a
reminder, it is a record of having been too late.

ONE `now` FOR THE WHOLE RUN. Every boundary in a run is measured against a
single pinned instant, so a row cannot fall inside a window for one comparison
and outside it for the next as the clock moves under a long batch.

IDEMPOTENCY SURVIVES A RESCHEDULE, WHICH IS THE WHOLE DIFFICULTY

`logical_event_id` is unique GLOBALLY — `uniq_notification_logical_event` covers
that field alone — so the id must name the appointment, the window, the
RECIPIENT and the SCHEDULE VERSION:

    appointment:{id}:reminder:{24h|1h}:v{schedule_version}:{recipient}

Without the recipient, whoever was notified first claims the id and the other
party's notice is silently swallowed as an already-delivered duplicate. Without
the version, a client who reschedules from Tuesday to Thursday would never be
reminded about Thursday: the Tuesday reminder already holds the id, and the
system would consider the job done. With the version in the id, a genuine
reschedule is a genuinely new event, while a retry of the SAME schedule is
still recognised as the same one.

WHAT THIS MODULE REFUSES TO DO

It never writes to an appointment. Not a status, not a marker, not a counter —
sending a reminder is not an event in the life of a consultation, and a module
that reminds people has no business editing the thing it reminds them about.
Everything it needs to avoid duplicates is already in the notification's own
unique id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.constants import AppointmentStatus, NotificationType
from app.core.exceptions import AppValidationError
from app.repositories.appointment_repo import AppointmentRepository
from app.repositories.notification_repo import NotificationRepository
from app.repositories.user_repo import UserRepository
from app.services.appointment_service import _slot_text

logger = logging.getLogger(__name__)

appt_repo = AppointmentRepository()
notification_repo = NotificationRepository()
user_repo = UserRepository()

# The windows, as (key, earliest-before-start, latest-before-start). A row is
# due when `earliest < scheduled_at - now <= latest`.
WINDOW_24H = "24h"
WINDOW_1H = "1h"
WINDOWS: tuple[tuple[str, timedelta, timedelta], ...] = (
    (WINDOW_24H, timedelta(hours=23), timedelta(hours=24)),
    (WINDOW_1H, timedelta(0), timedelta(hours=1)),
)

# How many APPOINTMENTS one run may remind about. Each produces up to two
# notifications, one per party. Bounded because the first real run against an
# existing deployment meets every confirmed appointment in both windows at
# once, and a batch job that messages everybody simultaneously is an incident
# whichever way the messages go.
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

# One database page while scanning for outstanding work, and the ceiling on how
# far a single run will look. Bounded because a window full of already-reminded
# appointments would otherwise be walked end to end on every run.
PAGE_SIZE = 200
MAX_SCAN = 2000


def window_bounds(window: str, now: datetime) -> tuple[datetime, datetime]:
    """The half-open `scheduled_at` range this window selects, as instants.

    `(now + earliest, now + latest]` — open at the near end so an appointment
    exactly 23 hours away belongs to neither window rather than both, and
    closed at the far end so one exactly 24 hours away is reminded about.
    """
    for key, earliest, latest in WINDOWS:
        if key == window:
            return now + earliest, now + latest
    raise AppValidationError(f"unknown reminder window {window!r}")


def reminder_event_id(
    appt_id: str, window: str, schedule_version: int, recipient_id: str,
) -> str:
    """The identity of one reminder, to one person, about one schedule.

    Four parts, and every one of them earns its place — see the module
    docstring. Dropping the recipient loses the second party's notice to the
    global uniqueness of the field; dropping the version means a rescheduled
    appointment is never reminded about again.
    """
    return (f"appointment:{appt_id}:reminder:{window}"
            f":v{schedule_version}:{recipient_id}")


def _as_utc(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            ).astimezone(timezone.utc)


def _version_of(appt: dict) -> int:
    """The stored schedule version, defaulted at the read boundary.

    Rows booked before the field existed carry none and are version 0 — the
    same default `schedule_version_of` applies elsewhere, so a legacy row gets
    a stable reminder identity rather than one that changes shape.
    """
    value = appt.get("schedule_version")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def is_due(appt: dict, window: str, now: datetime) -> bool:
    """Is this appointment in `window` at `now`?

    Re-asserted in code after the query has already selected on it. The two
    must agree, and checking here is what guarantees they do: if they ever
    diverge, a row is skipped rather than reminded about on the strength of a
    filter nobody re-read.
    """
    if appt.get("status") != AppointmentStatus.CONFIRMED.value:
        return False
    start = appt.get("scheduled_at")
    if not isinstance(start, datetime):
        return False
    earliest, latest = window_bounds(window, now)
    return earliest < _as_utc(start) <= latest


# ── Selecting what is due ─────────────────────────────────────────────────────

async def _collect(window: str, now: datetime, limit: int) -> tuple[list, int]:
    """Up to `limit` appointments that still NEED at least one reminder.

    THE BUDGET COUNTS OUTSTANDING WORK, NOT ROWS READ, and that is the
    difference between a cap and a stall. Selecting the first `limit` due rows
    and only then discarding the ones already reminded about means a run whose
    whole page has been handled sends nothing and advances nowhere — every
    subsequent run reads the same handled rows and the tail of the window is
    never reached. That is the same starvation the outcome nudge had to be
    rescued from.

    Keyset-paginated inside the window, so a scan larger than one page cannot
    repeat or skip a row at the boundary: `scheduled_at` alone is not unique,
    since two consultations with different lawyers can begin at the same
    instant.

    Returns the appointments paired with the recipients still owed a reminder,
    and how many recipient-reminders were skipped as already delivered.
    """
    earliest, latest = window_bounds(window, now)
    collected: list = []
    deduplicated = 0
    after_at = after_id = None
    scanned = 0

    while len(collected) < limit and scanned < MAX_SCAN:
        page = await appt_repo.find_due_reminders(
            earliest=earliest, latest=latest, limit=PAGE_SIZE,
            after_scheduled_at=after_at, after_id=after_id)
        if not page:
            break
        scanned += len(page)
        after_at, after_id = page[-1].get("scheduled_at"), page[-1]["_id"]

        # One query for the whole page, so "already delivered" is reported as
        # such rather than counted as a fresh send.
        ids_by_row = []
        every_id = []
        for appt in page:
            version = _version_of(appt)
            pairs = [
                (r, reminder_event_id(appt["_id"], window, version, r))
                for r in (appt.get("client_id"), appt.get("lawyer_id")) if r
            ]
            ids_by_row.append((appt, pairs))
            every_id.extend(event_id for _r, event_id in pairs)
        delivered = await _already_sent(every_id)

        for appt, pairs in ids_by_row:
            outstanding = [(r, i) for r, i in pairs if i not in delivered]
            deduplicated += len(pairs) - len(outstanding)
            if not outstanding:
                continue
            collected.append((appt, outstanding))
            if len(collected) >= limit:
                break

    return collected, deduplicated


async def _already_sent(event_ids: list[str]) -> set[str]:
    """Which of these reminders have already been delivered.

    Read in ONE query rather than discovered one duplicate-key at a time, so
    the report can distinguish "deduplicated" from "sent" honestly instead of
    counting every attempt as a delivery.

    This is an optimisation and a reporting aid, NOT the guarantee. Two runs
    racing can both read "not sent" and both attempt; the unique index on
    `logical_event_id` is what makes the second one a no-op.
    """
    if not event_ids:
        return set()
    rows = await notification_repo.find_many(
        {"logical_event_id": {"$in": event_ids}})
    return {row["logical_event_id"] for row in rows
            if row.get("logical_event_id")}


# ── The messages ──────────────────────────────────────────────────────────────

def _body(window: str, when: str, other_party: str, for_client: bool) -> str:
    """What each party reads.

    CARRIES NOTHING PRIVATE. No `lawyer_notes`, no cancellation reason, no
    reason written against a day off, no internal marker, no meeting link
    invented for the occasion. A reminder needs the time and who it is with;
    everything else stored on the appointment is somebody's business and not
    the reminder's.
    """
    lead = ("Tomorrow" if window == WINDOW_24H else "Starting soon")
    if for_client:
        return (f"{lead}: your consultation with {other_party} is at {when}. "
                "Open the appointment for the details.")
    return (f"{lead}: your consultation with {other_party} is at {when}. "
            "Open the appointment for the details.")


async def _name(user_id: str, cache: dict, fallback: str) -> str:
    if user_id not in cache:
        try:
            user = await user_repo.find_by_id(user_id)
            name = user.get("full_name") if isinstance(user, dict) else None
            cache[user_id] = name if isinstance(name, str) and name.strip() else fallback
        except Exception as exc:
            # Optional context must never turn a reminder into an error. The
            # class only: driver messages carry URIs, and this runs unattended.
            logger.warning("appointment_reminder_name_failed error=%s",
                           type(exc).__name__)
            cache[user_id] = fallback
    return cache[user_id]


# ── The run ───────────────────────────────────────────────────────────────────

async def send_due_reminders(
    *,
    apply: bool = False,
    now: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Remind both parties about consultations due in either window.

    DEFAULTS TO SENDING NOTHING. Without `apply=True` this reports exactly what
    an applying run would send and writes nothing at all — no notifications, no
    appointment fields, nothing.

    `now` is pinned once for the whole run and every boundary is measured
    against it, so a row cannot fall inside a window for one comparison and
    outside it for the next as the clock moves under a long batch.

    THE RACE THIS CLOSES, AND THE ONE IT DOES NOT. Immediately before notifying
    about an appointment, the row is re-read and required to be still CONFIRMED
    with the same `scheduled_at` and the same `schedule_version` as the row
    selected. A cancellation or reschedule that lands between the selection and
    the send is therefore caught, and the row is skipped.

    A NARROW WINDOW REMAINS, and it is not eliminated: between that re-read and
    the notification insert, the appointment can still change. Nothing here is
    transactional, and claiming otherwise would be worse than the gap. What
    bounds the damage is that the worst outcome is a reminder about a
    consultation cancelled seconds earlier — recoverable, visible to both
    parties, and preferable to the alternative design of claiming the row
    first, which would silence reminders for ever if a run died mid-flight.

    The counts distinguish what matters:

      selected       appointments the queries returned
      sent           notifications delivered (or, without `apply`, that would be)
      deduplicated   reminders already delivered for this exact schedule
      stale          rows that changed between selection and sending
      failed         sends that raised — nothing is written, so they retry
      remaining      due appointments this run did not reach
      applied        whether anything was actually sent
    """
    if type(apply) is not bool:
        raise AppValidationError("apply must be a boolean")
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise AppValidationError(
            f"limit must be an integer from 1 to {MAX_LIMIT}")

    now = _as_utc(now or datetime.now(timezone.utc))
    report = {"selected": 0, "sent": 0, "deduplicated": 0, "stale": 0,
              "failed": 0, "remaining": 0, "applied": bool(apply),
              "now": now, "by_window": {}}

    names: dict = {}
    budget = limit

    for window, _earliest, _latest in WINDOWS:
        picked, deduplicated = (await _collect(window, now, budget)
                                if budget > 0 else ([], 0))
        due_total = await _count_window(window, now)
        report["by_window"][window] = {"due": due_total, "selected": len(picked)}
        report["selected"] += len(picked)
        report["deduplicated"] += deduplicated
        report["remaining"] += max(due_total - len(picked) - deduplicated // 2, 0)
        budget -= len(picked)

        for appt, outstanding in picked:
            if not apply:
                report["sent"] += len(outstanding)
                continue

            # RE-READ, immediately before sending. See the docstring.
            fresh = await appt_repo.find_by_id(appt["_id"])
            if not _unchanged(fresh, appt, window, now):
                report["stale"] += len(outstanding)
                continue

            when = _slot_text(fresh["scheduled_at"])
            client_name = await _name(fresh.get("client_id"), names, "your client")
            lawyer_name = await _name(fresh.get("lawyer_id"), names, "your lawyer")

            for recipient, event_id in outstanding:
                for_client = recipient == fresh.get("client_id")
                ok = await _deliver(
                    appt_id=fresh["_id"],
                    user_id=recipient,
                    title=("Appointment tomorrow" if window == WINDOW_24H
                           else "Appointment starting soon"),
                    body=_body(window, when,
                               lawyer_name if for_client else client_name,
                               for_client),
                    event_id=event_id,
                )
                report["sent" if ok else "failed"] += 1

    logger.info(
        "appointment_reminders selected=%s sent=%s deduplicated=%s stale=%s "
        "failed=%s remaining=%s applied=%s",
        report["selected"], report["sent"], report["deduplicated"],
        report["stale"], report["failed"], report["remaining"], report["applied"])
    return report


def _unchanged(fresh: dict | None, selected: dict, window: str,
               now: datetime) -> bool:
    """Is the re-read row still the one that was selected, and still due?

    All three must hold: still CONFIRMED, the same start, the same schedule
    version. A reschedule changes two of them and a cancellation the third, and
    either means the reminder in hand describes an appointment that no longer
    exists in that form.
    """
    if fresh is None:
        return False
    if not is_due(fresh, window, now):
        return False
    if _version_of(fresh) != _version_of(selected):
        return False
    start_now, start_then = fresh.get("scheduled_at"), selected.get("scheduled_at")
    if not isinstance(start_now, datetime) or not isinstance(start_then, datetime):
        return False
    return _as_utc(start_now) == _as_utc(start_then)


async def _deliver(*, appt_id: str, user_id: str, title: str, body: str,
                   event_id: str) -> bool:
    """One reminder. Returns whether it was delivered.

    A failure writes NOTHING — no appointment field, no marker — so the row is
    simply selected again on the next run. There is no state to get wrong,
    because the notification's own unique id is the entire record of whether
    this reminder exists.

    Only the exception CLASS is logged. Driver messages carry URIs and
    credentials, and this path runs unattended.
    """
    from app.services.notification_service import create_notification

    try:
        await create_notification(
            user_id=user_id,
            type=NotificationType.APPOINTMENT_REMINDER,
            title=title,
            body=body,
            payload={"appointment_id": appt_id},
            logical_event_id=event_id,
        )
        return True
    except Exception as exc:
        logger.warning(
            "appointment_reminder_failed appointment_id=%s error=%s",
            appt_id, type(exc).__name__)
        return False


async def _count_window(window: str, now: datetime) -> int:
    earliest, latest = window_bounds(window, now)
    return await appt_repo.count_due_reminders(earliest, latest)


async def survey_due_reminders(now: datetime | None = None) -> dict:
    """How many reminders are due in each window. COUNTS ONLY, writes nothing.

    No appointment ids, no party names, no times of individual consultations —
    the question is "how many, and in which window", and answering it does not
    require naming anybody's consultation.

    There is no `apply` here and there is not meant to be one: this exists so
    the decision to switch reminders on can be taken against real numbers.
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    counts = {window: await _count_window(window, now)
              for window, _e, _l in WINDOWS}
    logger.info("appointment_reminder_survey %s", counts)
    return {"measured_at": now, "due": counts,
            "total": sum(counts.values())}
