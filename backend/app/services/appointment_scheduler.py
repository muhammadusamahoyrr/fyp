"""The control plane for appointment notifications. OFF BY DEFAULT.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT

The reminder and outcome-nudge mechanisms are built and tested. Neither has
ever run. This is the part that could run them — and it does nothing at all
unless somebody turns a flag on, per environment, deliberately.

With ALL THREE flags off — reminders, outcome nudges and expiry —
`appointment_scheduler_task()` returns None: no task is created, no loop
exists, and nothing is scheduled to wake up. That is stronger than a loop that
wakes and finds nothing to do, because there is no cycle to mis-configure into
activity.

THE EXPIRY SWEEP IS NOW HERE, and it is the one job that changes appointment
state rather than sending a message about it. EXPIRED is terminal — the
transition table has no edge out of it — so it carries guards the other two do
not need, and each refuses BEFORE anything is written:

    flag off                      no job, and no task at all if it is the
                                  only thing enabled
    lock not granted              another worker holds the period
    `appointment_pending_expiry`  missing or invalid: skip, never scan
    any PENDING row with no       skip. Those rows predate the field, the
    stored `expires_at`           sweep cannot see them, and running anyway
                                  would report a clean pass over a population
                                  nobody had decided about

That last guard is the one worth keeping. The sweep is already safe around
those rows — its query selects on the stored value, so it simply never
returns them — and the risk is not damage but a FALSE ALL-CLEAR: an operator
who switched expiry on would reasonably believe every unanswered request was
being handled. Deciding what happens to the old ones is a separate decision
about real people's requests, and it has to be taken rather than inherited.

THE SAME FLAG GATES THE CONFIRMATION PATH. `appointment_expiry.expiry_enabled`
is the single source of truth for both, because they have to move together: a
sweep with no confirmation guard lets a lawyer accept a request the next sweep
is about to retire, and a confirmation guard with no sweep leaves a lapsed
request neither confirmable nor expired — stuck, still holding its slots, with
no explanation for either party.

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

The THREE jobs hold SEPARATE locks and run in sequence inside their own error
boundaries, each bounded by a timeout. A reminder run that throws or wedges
must not stop the outcome nudges or the expiry sweep, a cycle that throws must
not kill the loop, and none of them may take down the application. The
alternative — one lock, one try block — means a single bad batch silences
everything until somebody notices, which for a notification system is
indistinguishable from it working.

Expiry runs LAST, because it is the only job that changes appointment state
rather than sending a message about it.

INDEX READINESS: TWO DIFFERENT DEPENDENCIES, DELIBERATELY TREATED DIFFERENTLY

All three indexes are QUERY-kind — nothing about a stored appointment is
incorrect without them — but what their absence COSTS is not the same, so the
response is not the same either.

    appointment_confirmed_reminder   ordinary QUERY dependency.
    appointment_confirmed_outcome    A missing one turns a bounded read into a
                                     collection scan on a table that only
                                     grows, so the job SKIPS and says so. It
                                     must never stop the application booting:
                                     refusing to serve over a performance index
                                     is an outage for a reason that is not the
                                     reason, and the other jobs are unaffected.

    appointment_pending_expiry       The same at run time, PLUS a startup
                                     ACTIVATION PREREQUISITE while expiry is
                                     enabled. `assert_appointment_expiry_activation_ready`
                                     refuses to boot without it.

Why the difference. A skipped reminder is late; the next cycle sends it and
nothing is lost. A skipped expiry sweep is a mechanism an operator has just
switched on that then does nothing at all, silently, while lapsed requests go
on holding slots — and the only evidence is a warning line among many. That is
worth refusing to start for, ONLY when somebody has deliberately enabled it.
With the flag off, this index is not consulted at startup at all.

The per-cycle check stays regardless, and is not made redundant by the startup
one: an index can be dropped during maintenance hours after a boot that
passed.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.redis_client import (
    STRICT_LOCK_NOT_CONFIGURED,
    STRICT_LOCK_UNREACHABLE,
    acquire_period_lock_strict,
    redis_reachable,
)

logger = logging.getLogger(__name__)

JOB_REMINDERS = "appointment_reminders"
JOB_OUTCOME_NUDGES = "appointment_outcome_nudges"
JOB_EXPIRY = "appointment_expiry"

# Separate keys, so one job holding its claim never blocks the other.
#
# Expiry gets its OWN key rather than sharing the notification one. Sharing
# would mean a reminder run in progress silently suppressed the expiry sweep
# for a whole period, and the sweep is the job whose delay actually costs
# something: a lapsed request keeps holding its slots until somebody retires
# it, so every skipped cycle is a lawyer's diary staying blocked.
LOCK_KEYS = {
    JOB_REMINDERS: "lock:scheduler:appointment_reminders",
    JOB_OUTCOME_NUDGES: "lock:scheduler:appointment_outcome_nudges",
    JOB_EXPIRY: "lock:scheduler:appointment_expiry",
}

# The QUERY index each job's read depends on.
JOB_INDEXES = {
    JOB_REMINDERS: "appointment_confirmed_reminder",
    JOB_OUTCOME_NUDGES: "appointment_confirmed_outcome",
    JOB_EXPIRY: "appointment_pending_expiry",
}

# The counts a run may report. An allowlist, so a service that starts returning
# something new does not quietly widen what this logs — the reports next to
# these numbers are about real people's consultations.
_SUMMARY_FIELDS = ("selected", "sent", "deduplicated", "stale", "failed",
                   "remaining", "scanned", "eligible", "applied",
                   # The expiry sweep's own counts.
                   "examined", "expired", "not_lapsed", "unassessable",
                   "moved")


def reminders_enabled() -> bool:
    """Read at call time, never captured at import — a snapshot could not be
    turned on without a restart, and tests could exercise only one branch."""
    return bool(getattr(settings, "appointment_reminders_enabled", False))


def outcome_nudges_enabled() -> bool:
    return bool(getattr(settings, "appointment_outcome_nudges_enabled", False))


def expiry_enabled() -> bool:
    """Delegated, never re-read from settings here.

    The confirmation path and this scheduler must agree about whether expiry
    is on, and the way to guarantee that is for both to call the same
    function. A second `getattr(settings, ...)` in this module would be a
    second answer waiting to diverge from the first.
    """
    from app.services import appointment_expiry

    return appointment_expiry.expiry_enabled()


def any_job_enabled() -> bool:
    return reminders_enabled() or outcome_nudges_enabled() or expiry_enabled()


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


async def _every_pending_row_has_a_stored_deadline() -> bool:
    """FAIL-CLOSED PRECONDITION. Read-only, and bounded to one document.

    A PENDING row with no stored `expires_at` predates the field. The sweep
    ignores those rows by construction -- its query selects on the stored
    value -- so running with them present is not dangerous so much as
    DISHONEST: the mechanism would report a clean pass while a population it
    cannot see sits behind it, and the operator who switched it on would
    reasonably believe those requests were being handled.

    Deciding what happens to them is a separate decision about real people's
    requests, and it must be taken deliberately rather than inherited from
    whoever set the flag. So the job refuses while any of them exist.

    `find_one`, not a count: the answer is "are there any", and a count over a
    growing collection every cycle buys nothing the existence check does not.
    """
    from app.core.constants import AppointmentStatus
    from app.db.collections import get_appointments_col

    stray = await get_appointments_col().find_one(
        {"status": AppointmentStatus.PENDING.value,
         "expires_at": {"$not": {"$type": "date"}}},
        {"_id": 1},
    )
    return stray is None


async def run_expiry(now: datetime) -> dict | None:
    """One bounded expiry sweep, or None if it was skipped.

    THE ONLY JOB HERE WHOSE EFFECT A CLIENT CANNOT UNDO. EXPIRED is terminal --
    the transition table has no edge out of it -- so every guard in front of
    this one is load-bearing, and they are checked in the order that makes the
    cheapest refusal happen first.
    """
    if not expiry_enabled():
        return None

    if not await acquire_period_lock_strict(
            LOCK_KEYS[JOB_EXPIRY], _lock_ttl_seconds(), JOB_EXPIRY):
        logger.info("appointment_scheduler_skipped job=%s reason=lock",
                    JOB_EXPIRY)
        return None
    if not await _index_ready(JOB_EXPIRY):
        logger.warning("appointment_scheduler_skipped job=%s reason=index",
                       JOB_EXPIRY)
        return None

    try:
        legacy_clear = await _every_pending_row_has_a_stored_deadline()
    except Exception as exc:
        # Cannot establish the precondition: refuse. Class only.
        logger.warning("appointment_scheduler_skipped job=%s reason=%s error=%s",
                       JOB_EXPIRY, "legacy_check_failed", type(exc).__name__)
        return None
    if not legacy_clear:
        logger.warning("appointment_scheduler_skipped job=%s reason=%s",
                       JOB_EXPIRY, "pending_rows_without_a_stored_deadline")
        return None

    from app.services import appointment_expiry_sweep

    report = await appointment_expiry_sweep.expire_lapsed_requests(
        apply=True, now=now,
        limit=int(getattr(settings, "appointment_expiry_batch", 50)))
    logger.info("appointment_scheduler_ran job=%s %s",
                JOB_EXPIRY, _summarise(JOB_EXPIRY, report))
    return report


async def run_cycle(now: datetime | None = None) -> dict:
    """One pass over all THREE jobs. Each is isolated from the others' failure.

    `now` is pinned once and handed to all three, so the jobs reason about the
    same instant — and so a long first job cannot move the boundary a later one
    measures against. That matters most for expiry, whose boundary decides
    whether somebody's request is terminated.
    """
    now = now or datetime.now(timezone.utc)
    timeout = _job_timeout_seconds()
    outcomes: dict = {}
    # Expiry runs LAST. It is the only job that changes appointment state, and
    # putting it after the notification jobs means a cycle that dies partway
    # has sent messages about appointments rather than retired appointments
    # nobody was told about. Each job is isolated regardless -- a wedged or
    # failing expiry sweep cannot suppress either notification job, and a
    # failing notification job cannot suppress the sweep.
    for job, runner in ((JOB_REMINDERS, run_reminders),
                        (JOB_OUTCOME_NUDGES, run_outcome_nudges),
                        (JOB_EXPIRY, run_expiry)):
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
        "nudges=%s expiry=%s job_timeout_seconds=%s lock_ttl_seconds=%s",
        interval // 60, reminders_enabled(), outcome_nudges_enabled(),
        expiry_enabled(), _job_timeout_seconds(), _lock_ttl_seconds())
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


class AppointmentExpiryNotReady(RuntimeError):
    """Expiry is switched on and its preconditions do not hold.

    Carries REASON CODES and nothing else. This is raised during startup, so
    it lands in a crash log that goes into a ticket - and the things it
    inspected are a connection string, an index, and rows describing real
    people's consultations. A code says what to fix; a message would say what
    the data is.
    """

    def __init__(self, reasons: list[str]):
        self.reasons = sorted(set(reasons))
        super().__init__(
            "appointment expiry is enabled but not ready: "
            + ", ".join(self.reasons))


# The reason codes. The two lock-backend ones are IMPORTED rather than
# restated: the activation audit reports the same two conditions, and a report
# saying `strict_lock_backend_unreachable` while startup refused with a
# differently-spelled code would send an operator looking for two problems.
EXPIRY_NO_LOCK_BACKEND = STRICT_LOCK_NOT_CONFIGURED
EXPIRY_LOCK_BACKEND_UNREACHABLE = STRICT_LOCK_UNREACHABLE
EXPIRY_INDEX_NOT_READY = "expiry_query_index_not_ready"
EXPIRY_UNUSABLE_DEADLINES = "pending_rows_without_a_usable_stored_deadline"


async def assert_appointment_expiry_activation_ready() -> None:
    """Refuse to start when expiry is enabled and cannot be run safely.

    WHY A STARTUP GUARD WHEN THE CYCLE ALREADY CHECKS

    The per-cycle checks make the sweep decline; they do not make anybody
    notice. A deployment with expiry switched on and a missing index would run
    for days skipping every cycle, and the only evidence would be a warning
    line among many that nobody is reading - a feature believed to be live,
    doing nothing, silently. Refusing at boot is loud, immediate, and
    reversible by turning the flag back off.

    So the two are not redundant and neither replaces the other: this one
    catches a deployment that was never ready, and the per-cycle checks catch
    an environment that STOPS being ready afterwards - an index dropped during
    maintenance, or a legacy row arriving from a restore.

    WHEN THE FLAG IS OFF THIS COSTS NOTHING, and that is a requirement rather
    than an optimisation. Every default deployment runs this on every boot, so
    it must not add a database round trip, an index read or a Redis probe to a
    process that has expiry switched off - which is all of them today.

    IT REPAIRS NOTHING and it is not the activation audit. The audit is an
    operator tool that reads seven sections and prints a report; running it
    here would put a full collection survey in the boot path and make a
    restart a way to produce an activation verdict nobody asked for. This
    checks exactly the three preconditions the sweep itself depends on.
    """
    if not expiry_enabled():
        # RETURNS BEFORE ANY I/O. No settings read beyond the flag, no index
        # validation, no query, no Redis.
        return

    reasons: list[str] = []

    # 1. The strict lock needs a backend that is configured AND ANSWERING.
    #
    #    Checking only that the URL is non-empty was not enough, and the gap
    #    was a real one: a wrong or dead Redis URL passed startup, and then
    #    every cycle failed its lock and did nothing. The deployment reported
    #    healthy, the feature was believed live, and the only evidence was a
    #    skip line in a log. "Configured" and "reachable" fail identically at
    #    run time, so they are both checked here and reported apart.
    #
    #    The probe is a bounded PING on a one-off client that is closed either
    #    way. Never a lock acquisition: taking the real lock would prove
    #    reachability by suppressing the next real cycle for its whole TTL.
    url = getattr(settings, "redis_url", "") or ""
    if not url:
        reasons.append(EXPIRY_NO_LOCK_BACKEND)
    elif not await redis_reachable(url):
        reasons.append(EXPIRY_LOCK_BACKEND_UNREACHABLE)

    # 2. The sweep's read degrades into a collection scan without its index,
    #    on a table that only grows.
    if not await _index_ready(JOB_EXPIRY):
        reasons.append(EXPIRY_INDEX_NOT_READY)

    # 3. A PENDING row with no usable stored deadline is invisible to the
    #    sweep's query, so the mechanism would report a clean pass over a
    #    population nobody has decided about.
    try:
        if not await _every_pending_row_has_a_stored_deadline():
            reasons.append(EXPIRY_UNUSABLE_DEADLINES)
    except Exception:
        # Could not establish it. Unknown is not ready - the same direction
        # every other check here fails in. The exception is not attached: a
        # driver error carries the URI it failed to reach.
        reasons.append(EXPIRY_UNUSABLE_DEADLINES)

    if reasons:
        logger.error("appointment_expiry_activation_refused reasons=%s",
                     ",".join(sorted(set(reasons))))
        raise AppointmentExpiryNotReady(reasons)

    logger.info("appointment_expiry_activation_ready")


def appointment_scheduler_task() -> asyncio.Task | None:
    """The task, or None when nothing is enabled.

    NO TASK AT ALL is the default. A loop that wakes and finds all three flags
    off would be a scheduler that EXISTS — one configuration mistake away from
    dispatching, or from expiring — and would have to be trusted to keep
    finding nothing. Not creating it is the stronger statement, and the one the
    tests assert.
    """
    if not any_job_enabled():
        return None
    return asyncio.create_task(scheduler_loop())
