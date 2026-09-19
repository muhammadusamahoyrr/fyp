"""The control plane for appointment notifications. OFF BY DEFAULT.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT

The reminder and outcome-nudge mechanisms are built and tested. Neither has
ever run. This is the part that could run them — and it does nothing at all
unless somebody turns a flag on, per environment, deliberately.

With both flags off, `appointment_scheduler_task()` returns None: no task is
created, no loop exists, and nothing is scheduled to wake up. That is stronger
than a loop that wakes and finds nothing to do, because there is no cycle to
mis-configure into activity.

THE EXPIRY SWEEP IS NOT HERE, on purpose. It is the one mechanism whose effect
is irreversible from a client's point of view — it terminates pending requests
— and its own prerequisites (the Phase 3 indexes, a deadline-guarded
confirmation path, approval for existing rows) are unmet. Wiring it "while we
are here" would be exactly the accident this module is arranged to prevent, so
there is no import of it and a test asserts the absence.

WHY THE LOCK IS THE STRICT ONE

Every worker runs this loop. The existing `acquire_period_lock` fails OPEN —
when Redis is missing or erroring it returns True so the sweep runs anyway,
which is right for an idempotent sweep whose worst duplicate outcome is wasted
work. It is wrong here: failing open means every worker dispatches the same
batch of messages to the same people at the same moment. The unique
`logical_event_id` would still collapse those into one delivered notice, but
the guarantee would be resting on a database constraint reached by N
simultaneous writers. Skipping a cycle costs a reminder arriving one interval
later. That is the cheaper mistake, so this uses `acquire_period_lock_strict`.

ONE JOB'S FAILURE IS NOT THE OTHER'S

The two jobs hold SEPARATE locks and run in sequence inside their own error
boundaries. A reminder run that throws must not stop the outcome nudges, a
cycle that throws must not kill the loop, and neither may take down the
application. The alternative — one lock, one try block — means a single bad
batch silences everything until somebody notices, which for a notification
system is indistinguishable from it working.

INDEX READINESS IS CHECKED BEFORE DISPATCH, NOT AT STARTUP

Each job's query index is a QUERY-kind index: nothing is incorrect without it,
but its absence turns a bounded read into a collection scan on a table that
only grows. So a missing index SKIPS that job and says so, rather than either
scanning or refusing to start the application — a performance index must never
be a reason the service will not boot.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.redis_client import acquire_period_lock_strict

logger = logging.getLogger(__name__)

JOB_REMINDERS = "appointment_reminders"
JOB_OUTCOME_NUDGES = "appointment_outcome_nudges"

# Separate keys, so one job holding its claim never blocks the other.
LOCK_KEYS = {
    JOB_REMINDERS: "lock:scheduler:appointment_reminders",
    JOB_OUTCOME_NUDGES: "lock:scheduler:appointment_outcome_nudges",
}

# The QUERY index each job's read depends on.
JOB_INDEXES = {
    JOB_REMINDERS: "appointment_confirmed_reminder",
    JOB_OUTCOME_NUDGES: "appointment_confirmed_outcome",
}

# The counts a run may report. An allowlist, so a service that starts returning
# something new does not quietly widen what this logs — the reports next to
# these numbers are about real people's consultations.
_SUMMARY_FIELDS = ("selected", "sent", "deduplicated", "stale", "failed",
                   "remaining", "scanned", "eligible", "applied")


def reminders_enabled() -> bool:
    """Read at call time, never captured at import — a snapshot could not be
    turned on without a restart, and tests could exercise only one branch."""
    return bool(getattr(settings, "appointment_reminders_enabled", False))


def outcome_nudges_enabled() -> bool:
    return bool(getattr(settings, "appointment_outcome_nudges_enabled", False))


def any_job_enabled() -> bool:
    return reminders_enabled() or outcome_nudges_enabled()


def _interval_seconds() -> int:
    return int(getattr(settings, "appointment_scheduler_interval_minutes", 15)) * 60


# THE ONE ORDERING EVERYTHING ELSE HERE DEPENDS ON:
#
#     job timeout  <  lock TTL  <  interval
#
# Read right to left, each gap pays for a different failure.
#
# TTL < interval: a claim that outlived its period would suppress the NEXT
# one as well, so a single slow cycle silently halves the cadence.
#
# timeout < TTL: a job still running when its own lock expires is a job whose
# exclusivity has quietly lapsed - a second worker can take the lock and start
# the same batch while the first is still dispatching to the same people. The
# timeout has to fire while the claim is still held.
#
# These are FRACTIONS of the interval rather than constants, so the ordering
# holds at every cadence the settings allow instead of only at the default.
_TTL_FRACTION = 0.8
_TIMEOUT_FRACTION = 0.75        # of the TTL, so 0.6 of the interval

# AN ABSOLUTE CEILING, because a proportion of a long cadence is not a budget.
#
# The fractions above keep the ordering correct at every cadence, and that is
# all they do. They say nothing about whether the resulting number is a
# sensible length of time to let a job run, and at the widest cadence the
# settings allow - 720 minutes, which only an outcome-only deployment can use,
# since reminders cap the interval at 30 - 0.6 of the interval is SEVEN HOURS
# AND TWELVE MINUTES. Nothing either job does takes seven hours: a reminder
# run sends at most `appointment_reminder_batch` notices and a nudge run at
# most `appointment_outcome_nudge_batch`, both bounded in the low hundreds. A
# job still going after five minutes is wedged, not busy, and the only thing a
# seven-hour budget buys is seven hours of not finding out.
#
# It is a floor-free `min`, so it can only ever LOWER the timeout: the
# `timeout < TTL < interval` ordering is preserved by construction rather than
# by another calculation that could disagree with the first one.
MAX_JOB_TIMEOUT_SECONDS = 300


def _lock_ttl_seconds() -> int:
    """Shorter than the interval at every valid cadence.

    An earlier version was `max(interval * 0.8, 60)`, and the floor was the
    bug: at a one-minute interval it returned 60 seconds, so TTL EQUALLED the
    interval and the ordering above collapsed - one worker's claim covered the
    whole of the next period. The floor is gone rather than lowered, because a
    fraction of a validated interval never needs one: the smallest cadence the
    settings permit is a minute, which leaves 48 seconds.
    """
    return int(_interval_seconds() * _TTL_FRACTION)


def _job_timeout_seconds() -> int:
    """How long one job may run before it is abandoned for this cycle.

    Deterministic, derived, strictly inside the lock's lifetime, and never
    longer than `MAX_JOB_TIMEOUT_SECONDS` however wide the cadence. Not
    retried inside the same cycle: a job that just failed to finish in its
    whole budget will not finish in the remainder, and the next cycle is
    already the retry.
    """
    return min(int(_lock_ttl_seconds() * _TIMEOUT_FRACTION),
               MAX_JOB_TIMEOUT_SECONDS)


async def _index_ready(job: str) -> bool:
    """Is this job's QUERY index present and valid?

    Read-only, and it never creates anything: an index appearing as a side
    effect of a scheduler tick is how a production index build starts without
    anybody deciding to run one.
    """
    from app.db.indexes import validate_appointment_indexes

    wanted = JOB_INDEXES[job]
    try:
        problems = await validate_appointment_indexes()
    except Exception as exc:
        # Cannot establish readiness: skip rather than scan. Class only.
        logger.warning("appointment_scheduler_index_check_failed job=%s error=%s",
                       job, type(exc).__name__)
        return False
    return not any(p.name == wanted for p in problems)


def _summarise(job: str, report: dict) -> dict:
    """The numbers, and nothing else.

    Reports from these services carry only counts already, but this filters
    rather than trusts: what sits beside them in memory is a client's
    consultation, and a log line is the easiest place for it to end up.
    """
    return {key: report[key] for key in _SUMMARY_FIELDS
            if key in report and isinstance(report[key], (int, bool))}


async def run_reminders(now: datetime) -> dict | None:
    """One reminder cycle, or None if it was skipped."""
    if not reminders_enabled():
        return None
    if not await acquire_period_lock_strict(
            LOCK_KEYS[JOB_REMINDERS], _lock_ttl_seconds(), JOB_REMINDERS):
        logger.info("appointment_scheduler_skipped job=%s reason=lock",
                    JOB_REMINDERS)
        return None
    if not await _index_ready(JOB_REMINDERS):
        logger.warning("appointment_scheduler_skipped job=%s reason=index",
                       JOB_REMINDERS)
        return None

    from app.services import appointment_reminders

    report = await appointment_reminders.send_due_reminders(
        apply=True, now=now,
        limit=int(getattr(settings, "appointment_reminder_batch", 100)))
    logger.info("appointment_scheduler_ran job=%s %s",
                JOB_REMINDERS, _summarise(JOB_REMINDERS, report))
    return report


async def run_outcome_nudges(now: datetime) -> dict | None:
    """One outcome-nudge cycle, or None if it was skipped."""
    if not outcome_nudges_enabled():
        return None

    activated_at = getattr(
        settings, "appointment_outcome_nudges_activated_at", None)
    if not isinstance(activated_at, datetime):
        # Belt to the config validator's braces. If this is ever reachable, the
        # right answer is to send nothing: without a fixed instant the run
        # would choose for itself how much history to notify.
        logger.error("appointment_scheduler_skipped job=%s reason=no_activation",
                     JOB_OUTCOME_NUDGES)
        return None

    if not await acquire_period_lock_strict(
            LOCK_KEYS[JOB_OUTCOME_NUDGES], _lock_ttl_seconds(),
            JOB_OUTCOME_NUDGES):
        logger.info("appointment_scheduler_skipped job=%s reason=lock",
                    JOB_OUTCOME_NUDGES)
        return None
    if not await _index_ready(JOB_OUTCOME_NUDGES):
        logger.warning("appointment_scheduler_skipped job=%s reason=index",
                       JOB_OUTCOME_NUDGES)
        return None

    from app.services import appointment_outcomes

    report = await appointment_outcomes.notify_outstanding_outcomes(
        apply=True, now=now,
        # PASSED THROUGH UNCHANGED, from configuration. Never `now`, never the
        # process start time: a value that moved on restart would let a
        # redeploy re-open a window somebody had already closed.
        activated_at=activated_at,
        limit=int(getattr(settings, "appointment_outcome_nudge_batch", 25)))
    logger.info("appointment_scheduler_ran job=%s %s",
                JOB_OUTCOME_NUDGES, _summarise(JOB_OUTCOME_NUDGES, report))
    return report


async def run_cycle(now: datetime | None = None) -> dict:
    """One pass over both jobs. Each is isolated from the other's failure.

    `now` is pinned once and handed to both, so the two jobs reason about the
    same instant — and so a long first job cannot move the boundary the second
    one measures against.
    """
    now = now or datetime.now(timezone.utc)
    timeout = _job_timeout_seconds()
    outcomes: dict = {}
    for job, runner in ((JOB_REMINDERS, run_reminders),
                        (JOB_OUTCOME_NUDGES, run_outcome_nudges)):
        try:
            # BOUNDED, and bounded around the WHOLE job rather than around the
            # dispatch inside it: acquiring the lock and checking the index are
            # network calls too, and a job wedged on either of those is just as
            # stuck as one wedged on a send.
            outcomes[job] = await asyncio.wait_for(runner(now), timeout)
        except asyncio.CancelledError:
            # BEFORE the timeout clause, and it has to be: shutdown cancels
            # this task, and a cancellation reported as a timeout would look
            # like a hung job in the logs every time the application stops.
            # CancelledError is a BaseException, so `except Exception` below
            # would not catch it either - this clause is explicit so the
            # ordering is deliberate rather than incidental.
            raise
        except TimeoutError:
            # Its own clause so the log says what actually happened, and so
            # the NEXT job still runs: a reminder batch that wedges must not
            # take the outcome nudges down with it.
            logger.warning("appointment_scheduler_job_timeout job=%s error=%s",
                           job, TimeoutError.__name__)
            outcomes[job] = None
        except Exception as exc:
            # One job's failure is not the other's. Class only — a driver
            # message carries the URI it failed to reach.
            logger.warning("appointment_scheduler_job_failed job=%s error=%s",
                           job, type(exc).__name__)
            outcomes[job] = None
    return outcomes


async def scheduler_loop() -> None:
    """Run a cycle, THEN sleep. Survives a failing cycle.

    THE FIRST CYCLE IS IMMEDIATE, and the previous order - sleep, then run -
    was a real gap rather than a style choice. A deploy, a restart or a crash
    recovery inside the T-1h window meant the first opportunity to send did
    not arrive until a whole cadence later, by which time the appointment the
    reminder was for may already have started. Rolling restarts made it worse:
    every worker starts its own blind interval at once, so the entire fleet is
    silent for the same first period.

    Nothing is dispatched that would not have been dispatched anyway. The
    windows, the lock and the `logical_event_id` decide that; this only
    decides when the first look happens, and looking immediately is what a
    restart should do.

    The sleep sits OUTSIDE the cycle's error handling and is never skipped. A
    failing cycle that looped straight back would become a hot loop hammering
    the database and filling the log with the same line - which is how a
    scheduler turns one bad batch into an outage.
    """
    interval = _interval_seconds()
    logger.info(
        "appointment_scheduler_started interval_minutes=%s reminders=%s "
        "nudges=%s job_timeout_seconds=%s lock_ttl_seconds=%s",
        interval // 60, reminders_enabled(), outcome_nudges_enabled(),
        _job_timeout_seconds(), _lock_ttl_seconds())
    try:
        while True:
            try:
                await run_cycle()
            except Exception as exc:
                # CancelledError is a BaseException and passes straight through
                # to the handler below, so shutdown is never mistaken for a
                # failing cycle.
                logger.warning("appointment_scheduler_cycle_failed error=%s",
                               type(exc).__name__)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("appointment_scheduler_stopped")
        raise


def appointment_scheduler_task() -> asyncio.Task | None:
    """The task, or None when nothing is enabled.

    NO TASK AT ALL is the default. A loop that wakes and finds both flags off
    would be a scheduler that exists — one configuration mistake away from
    dispatching — and would have to be trusted to keep finding nothing. Not
    creating it is the stronger statement, and the one the tests assert.
    """
    if not any_job_enabled():
        return None
    return asyncio.create_task(scheduler_loop())
