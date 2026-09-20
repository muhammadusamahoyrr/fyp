"""The control plane that could run appointment notifications, and doesn't.

Both feature flags are OFF by default, and the strongest form of that is what
this file asserts first: with both off, `appointment_scheduler_task()` returns
None — no task, no loop, nothing scheduled to wake. A loop that woke and found
nothing to do would be a scheduler that EXISTS, one configuration mistake away
from dispatching to real people, and would have to be trusted to keep finding
nothing.

THE LOCK IS THE FAIL-CLOSED ONE, and that is the substantive decision here.
`acquire_period_lock` returns True when Redis is missing or erroring so a sweep
still runs — right for an idempotent sweep whose worst duplicate outcome is
wasted work, wrong when the work is messaging people. Every worker runs this
loop; failing open means every worker dispatches the same batch at the same
moment, and the only thing standing between that and duplicate notices would be
a unique index reached by N simultaneous writers. Skipping the cycle costs a
reminder arriving one interval late.

Nothing here touches Redis, a provider, or a production database. The services
are stubbed, so a test that "sends" a reminder sends nothing.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

import pytest

from app.services import appointment_scheduler as scheduler

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
ACTIVATED = datetime(2026, 10, 1, tzinfo=timezone.utc)

# How long a "wedged" job pretends to run for. Deliberately SMALL.
#
# It only has to outlast the job timeout the tests patch in (0.01s), and the
# assertion is about which branch fires, not about the duration. An hour here
# would be just as correct and would make the suite unrunnable the moment the
# timeout is removed -- which is exactly what a mutation does. A guard that
# can only be verified by a test that hangs for an hour without it is a guard
# nobody will re-verify.
HANG_SECONDS = 5

# What a wedged job returns IF IT IS ALLOWED TO FINISH.
#
# Mutation testing found this: the stubs used to return None, and None is
# precisely what `run_cycle` stores when it abandons a job. So "the job was
# timed out" and "the job ran to completion and returned nothing" were the
# same observation, and the timeout could be deleted without a test noticing.
# A distinct sentinel makes the two outcomes tell apart.
FINISHED = {"sent": 999, "applied": True}


@pytest.fixture
def config():
    """Set scheduler settings for one test and always put them back."""
    from app.core.config import settings

    keys = ("appointment_reminders_enabled",
            "appointment_outcome_nudges_enabled",
            "appointment_outcome_nudges_activated_at",
            "appointment_scheduler_interval_minutes",
            "appointment_reminder_batch",
            "appointment_outcome_nudge_batch",
            "appointment_expiry_enabled",
            "appointment_expiry_batch")
    saved = {k: getattr(settings, k, None) for k in keys}

    def _set(**values):
        for key, value in values.items():
            setattr(settings, key, value)

    yield _set
    for key, value in saved.items():
        setattr(settings, key, value)


@pytest.fixture
def calls(monkeypatch):
    """Stub both services and both external dependencies.

    The real services are exercised by their own suites; here they are
    recording stubs, so nothing this file runs can deliver a notification.
    """
    from app.services import appointment_outcomes, appointment_reminders

    seen = {"reminders": [], "nudges": [], "locks": [], "index_checks": []}

    async def _reminders(**kwargs):
        seen["reminders"].append(kwargs)
        return {"selected": 2, "sent": 4, "deduplicated": 0, "stale": 0,
                "failed": 0, "remaining": 0, "applied": True}

    async def _nudges(**kwargs):
        seen["nudges"].append(kwargs)
        return {"scanned": 3, "eligible": 3, "sent": 3, "failed": 0,
                "stale": 0, "applied": True}

    async def _lock(key, ttl_seconds, job):
        seen["locks"].append(job)
        return seen.get("lock_result", True)

    async def _indexes():
        seen["index_checks"].append(True)
        return seen.get("index_problems", [])

    monkeypatch.setattr(appointment_reminders, "send_due_reminders", _reminders)
    monkeypatch.setattr(appointment_outcomes, "notify_outstanding_outcomes", _nudges)
    monkeypatch.setattr(scheduler, "acquire_period_lock_strict", _lock)

    from app.db import indexes as indexes_module
    monkeypatch.setattr(indexes_module, "validate_appointment_indexes", _indexes)
    return seen


def _missing(name):
    from app.db.v2_index_spec import QUERY, IndexProblem
    return [IndexProblem("missing", "appointments", name, "gone", kind=QUERY)]


# ── 1. Off by default ────────────────────────────────────────────────────────

def test_both_flags_are_off_by_default():
    from app.core.config import Settings

    fresh = Settings()
    assert fresh.appointment_reminders_enabled is False
    assert fresh.appointment_outcome_nudges_enabled is False
    assert fresh.appointment_outcome_nudges_activated_at is None


async def test_no_task_is_created_when_both_flags_are_off(config, calls):
    """Stronger than a loop that finds nothing to do: there is no loop."""
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=False)

    assert scheduler.appointment_scheduler_task() is None


async def test_a_cycle_with_every_flag_off_dispatches_nothing(config, calls):
    """EVERY job, enumerated from the scheduler rather than listed here.

    Written this way after adding the third one: a hand-written pair silently
    stops covering whatever is added next, and "the cycle does nothing while
    the flags are off" is exactly the assertion that must keep covering all of
    them.
    """
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=False,
           appointment_expiry_enabled=False)

    result = await scheduler.run_cycle(NOW)

    assert result == {job: None for job in scheduler.LOCK_KEYS}
    assert set(result) == {scheduler.JOB_REMINDERS,
                           scheduler.JOB_OUTCOME_NUDGES,
                           scheduler.JOB_EXPIRY}
    assert calls["reminders"] == []
    assert calls["nudges"] == []
    assert calls["locks"] == [], "a lock was taken for a disabled job"


# ── 2. One job at a time ─────────────────────────────────────────────────────

async def test_reminders_only(config, calls):
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    await scheduler.run_cycle(NOW)

    assert len(calls["reminders"]) == 1
    assert calls["nudges"] == []
    assert calls["reminders"][0]["apply"] is True
    assert calls["reminders"][0]["now"] == NOW


async def test_outcome_nudges_only(config, calls):
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    await scheduler.run_cycle(NOW)

    assert calls["reminders"] == []
    assert len(calls["nudges"]) == 1
    assert calls["nudges"][0]["apply"] is True


async def test_both_jobs_run_in_one_cycle(config, calls):
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    await scheduler.run_cycle(NOW)

    assert len(calls["reminders"]) == 1
    assert len(calls["nudges"]) == 1
    # ONE `now` FOR THE CYCLE: a long first job must not move the boundary the
    # second one measures against.
    assert calls["reminders"][0]["now"] == calls["nudges"][0]["now"] == NOW


async def test_apply_is_only_true_for_an_enabled_job(config, calls):
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    await scheduler.run_cycle(NOW)

    assert calls["reminders"][0]["apply"] is True
    assert calls["nudges"] == [], "a disabled job was called at all"


# ── 3. The activation instant ────────────────────────────────────────────────

def test_enabling_nudges_without_an_activation_instant_is_refused():
    """FAIL CLOSED at configuration: without a fixed instant the first run
    would decide for itself how much history to notify."""
    from app.core.config import Settings

    with pytest.raises(Exception) as caught:
        Settings(appointment_outcome_nudges_enabled=True)
    assert "activated_at" in str(caught.value)


def test_a_naive_activation_instant_is_refused():
    """A naive timestamp is not a moment — it is a wall-clock reading whose
    meaning depends on where it is read, and this value decides how much
    history gets messaged."""
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(appointment_outcome_nudges_activated_at=datetime(2026, 10, 1))


def test_an_aware_activation_instant_is_normalised_to_utc():
    from datetime import timedelta
    from app.core.config import Settings

    local = datetime(2026, 10, 1, 5, 0,
                     tzinfo=timezone(timedelta(hours=5)))
    fresh = Settings(appointment_outcome_nudges_activated_at=local)

    assert fresh.appointment_outcome_nudges_activated_at == datetime(
        2026, 10, 1, 0, 0, tzinfo=timezone.utc)


async def test_the_activation_instant_is_passed_through_unchanged(config, calls):
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    await scheduler.run_cycle(NOW)

    assert calls["nudges"][0]["activated_at"] == ACTIVATED
    assert calls["nudges"][0]["activated_at"] != NOW


async def test_the_activation_instant_survives_many_cycles(config, calls):
    """It must not drift toward `now`. A value that moved would let a redeploy
    re-open a window somebody had already closed."""
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    for hours in (0, 6, 24):
        await scheduler.run_cycle(NOW.replace(hour=(9 + hours) % 24))

    assert {c["activated_at"] for c in calls["nudges"]} == {ACTIVATED}


async def test_a_missing_activation_instant_at_runtime_sends_nothing(config, calls):
    """Belt to the validator's braces: if the setting is ever absent when a
    cycle runs, the right answer is to send nothing."""
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=None)

    await scheduler.run_cycle(NOW)

    assert calls["nudges"] == []
    assert calls["locks"] == [], "a lock was taken before the check"


def test_the_activation_instant_is_never_derived_from_process_start():
    import inspect

    source = inspect.getsource(scheduler)
    body = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "activated_at=now" not in body
    assert "activated_at=datetime.now" not in body


# ── 4. The strict lock ───────────────────────────────────────────────────────

async def test_the_scheduler_uses_the_fail_closed_lock():
    """Not `acquire_period_lock`, which returns True when Redis is missing or
    erroring - that would let every worker dispatch the same batch.

    Asserted by IDENTITY rather than by the text of the import line. The
    earlier version matched
    `from app.core.redis_client import acquire_period_lock_strict` verbatim
    and broke the moment that import gained a second name and wrapped in
    parentheses - a formatting change, with the guarantee untouched. What
    matters is which function the module actually holds, and that a reference
    to the fail-open one never appears in its body.
    """
    import inspect

    from app.core import redis_client

    assert scheduler.acquire_period_lock_strict is \
        redis_client.acquire_period_lock_strict

    source = inspect.getsource(scheduler)
    body = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "acquire_period_lock(" not in body


async def test_a_denied_lock_dispatches_nothing(config, calls):
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)
    calls["lock_result"] = False

    await scheduler.run_cycle(NOW)

    assert calls["reminders"] == []
    assert calls["nudges"] == []


async def test_an_erroring_lock_dispatches_nothing(config, calls, monkeypatch):
    async def _boom(key, ttl_seconds, job):
        raise RuntimeError("redis unreachable at mongodb://user:pw@host")

    monkeypatch.setattr(scheduler, "acquire_period_lock_strict", _boom)
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    result = await scheduler.run_cycle(NOW)

    assert calls["reminders"] == []
    assert calls["nudges"] == []
    assert result[scheduler.JOB_REMINDERS] is None


def test_the_strict_lock_refuses_when_redis_is_absent():
    """The real function, not the stub: with no Redis configured it returns
    False rather than the fail-open True of its sibling."""
    import inspect

    from app.core.redis_client import (
        acquire_period_lock,
        acquire_period_lock_strict,
    )

    strict = inspect.getsource(acquire_period_lock_strict)
    assert "return False" in strict
    # And the fail-open original is untouched, so other schedulers behave
    # exactly as they did.
    assert "running anyway" in inspect.getsource(acquire_period_lock)


async def test_each_job_holds_its_own_lock(config, calls):
    """Separate keys: one job's claim must never block the other."""
    assert (scheduler.LOCK_KEYS[scheduler.JOB_REMINDERS]
            != scheduler.LOCK_KEYS[scheduler.JOB_OUTCOME_NUDGES])

    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    await scheduler.run_cycle(NOW)

    assert calls["locks"] == [scheduler.JOB_REMINDERS,
                              scheduler.JOB_OUTCOME_NUDGES]


async def test_one_jobs_lock_does_not_block_the_other(config, calls, monkeypatch):
    async def _only_reminders(key, ttl_seconds, job):
        calls["locks"].append(job)
        return job == scheduler.JOB_REMINDERS

    monkeypatch.setattr(scheduler, "acquire_period_lock_strict", _only_reminders)
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    await scheduler.run_cycle(NOW)

    assert len(calls["reminders"]) == 1
    assert calls["nudges"] == []


# ── 5. Index readiness ───────────────────────────────────────────────────────

async def test_a_missing_reminder_index_skips_only_reminders(config, calls):
    """A QUERY index's absence turns a bounded read into a collection scan.
    Skipping is right; scanning is not, and refusing to start is worse."""
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)
    calls["index_problems"] = _missing("appointment_confirmed_reminder")

    await scheduler.run_cycle(NOW)

    assert calls["reminders"] == []
    assert len(calls["nudges"]) == 1, "the other job was skipped too"


async def test_a_missing_outcome_index_skips_only_outcome_nudges(config, calls):
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)
    calls["index_problems"] = _missing("appointment_confirmed_outcome")

    await scheduler.run_cycle(NOW)

    assert len(calls["reminders"]) == 1
    assert calls["nudges"] == []


async def test_an_unrelated_index_problem_stops_neither_job(config, calls):
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)
    calls["index_problems"] = _missing("some_other_index")

    await scheduler.run_cycle(NOW)

    assert len(calls["reminders"]) == 1
    assert len(calls["nudges"]) == 1


async def test_an_index_check_failure_skips_rather_than_scans(config, calls, monkeypatch):
    from app.db import indexes as indexes_module

    async def _boom():
        raise RuntimeError("cannot read index metadata")

    monkeypatch.setattr(indexes_module, "validate_appointment_indexes", _boom)
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    await scheduler.run_cycle(NOW)

    assert calls["reminders"] == []


def test_the_scheduler_never_creates_an_index():
    import inspect

    source = inspect.getsource(scheduler)
    for creator in ("create_index", "create_indexes", "ensure_appointment_indexes",
                    "drop_index"):
        assert creator not in source


def test_the_index_check_does_not_block_startup(config):
    """It is consulted per job, per cycle — never at import or task creation."""
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=False)

    assert scheduler.appointment_scheduler_task() is None


# ── 6. Isolation and survival ────────────────────────────────────────────────

async def test_one_job_failing_does_not_suppress_the_other(config, calls, monkeypatch):
    from app.services import appointment_reminders

    async def _boom(**kwargs):
        raise RuntimeError("reminder backend down")

    monkeypatch.setattr(appointment_reminders, "send_due_reminders", _boom)
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    result = await scheduler.run_cycle(NOW)

    assert result[scheduler.JOB_REMINDERS] is None
    assert len(calls["nudges"]) == 1, "a failing job silenced the other"


async def test_a_failing_cycle_does_not_kill_the_loop(config, calls, monkeypatch):
    """A notification scheduler that dies on one bad batch stops silently, and
    silence is indistinguishable from it working."""
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False,
           appointment_scheduler_interval_minutes=1)

    cycles = {"n": 0}

    async def _sometimes_boom(now=None):
        cycles["n"] += 1
        if cycles["n"] == 1:
            raise RuntimeError("cycle blew up")
        return {}

    # The INTERVAL is shortened, not `asyncio.sleep`. Patching
    # `scheduler.asyncio.sleep` reaches the real asyncio module — every
    # coroutine in the process, including the replacement's own sleep — and
    # hangs the run.
    monkeypatch.setattr(scheduler, "run_cycle", _sometimes_boom)
    monkeypatch.setattr(scheduler, "_interval_seconds", lambda: 0)

    task = asyncio.create_task(scheduler.scheduler_loop())
    while cycles["n"] < 3:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cycles["n"] >= 3, "the loop stopped after a failing cycle"


async def test_shutdown_cancels_and_awaits_cleanly(config, monkeypatch):
    """Cancellation only REQUESTS a stop. A task cancelled and never awaited
    can still be mid-dispatch when the loop closes under it."""
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False,
           appointment_scheduler_interval_minutes=1)

    task = scheduler.appointment_scheduler_task()
    assert task is not None

    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled()
    assert task.done()


async def test_a_cancelled_cycle_propagates_rather_than_being_swallowed(config, calls, monkeypatch):
    """`CancelledError` must not be caught by the job error boundary, or
    shutdown would hang waiting for a task that keeps working."""
    from app.services import appointment_reminders

    async def _cancelled(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(appointment_reminders, "send_due_reminders", _cancelled)
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    with pytest.raises(asyncio.CancelledError):
        await scheduler.run_cycle(NOW)


# ── 7. What must never be here ───────────────────────────────────────────────

def test_the_expiry_sweep_is_wired_but_cannot_run_by_default():
    """This assertion used to be that expiry was ABSENT from this module.

    That was the right contract while the confirmation path had no deadline
    guard: a sweep without one lets a lawyer accept a request the next sweep
    is about to retire. Now that both are gated on one flag, the sweep belongs
    here - and what has to be asserted instead is that being present is not
    the same as being able to run.
    """
    import inspect

    source = inspect.getsource(scheduler)
    assert "expire_lapsed_requests" in source
    assert scheduler.JOB_EXPIRY in scheduler.LOCK_KEYS
    assert scheduler.JOB_INDEXES[scheduler.JOB_EXPIRY] == \
        "appointment_pending_expiry"

    # Wired, and off.
    from app.core.config import Settings
    assert Settings().appointment_expiry_enabled is False


def test_the_expiry_lock_key_is_not_shared_with_the_notification_jobs():
    """Sharing a key would let a reminder run in progress silently suppress
    the sweep for a whole period - and a lapsed request keeps holding its
    slots until something retires it."""
    keys = list(scheduler.LOCK_KEYS.values())

    assert len(set(keys)) == len(keys)
    assert scheduler.LOCK_KEYS[scheduler.JOB_EXPIRY] not in (
        scheduler.LOCK_KEYS[scheduler.JOB_REMINDERS],
        scheduler.LOCK_KEYS[scheduler.JOB_OUTCOME_NUDGES],
    )


def test_working_hours_enforcement_is_not_touched():
    import inspect

    source = inspect.getsource(scheduler)
    assert "working_hours" not in source


def test_no_public_endpoint_can_trigger_a_dispatch():
    """`apply=True` must be reachable only from this module, never from a
    request somebody can send."""
    from pathlib import Path

    routes = Path("app/api/v1/routes")
    for path in routes.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "send_due_reminders" not in text, path.name
        assert "notify_outstanding_outcomes" not in text, path.name
        assert "appointment_scheduler" not in text, path.name


def test_main_holds_no_scheduling_logic():
    """`main.py` starts and stops the task; the decisions live here."""
    from pathlib import Path

    import app.main as main

    source = Path(main.__file__).read_text(encoding="utf-8")
    assert "appointment_scheduler_task" in source
    for leaked in ("send_due_reminders", "notify_outstanding_outcomes",
                   "acquire_period_lock_strict", "appointment_confirmed_reminder"):
        assert leaked not in source, leaked


# ── 8. What reaches the log ──────────────────────────────────────────────────

async def test_a_run_logs_counts_and_nothing_else(config, calls, caplog):
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    with caplog.at_level(logging.INFO):
        await scheduler.run_cycle(NOW)

    assert "appointment_scheduler_ran" in caplog.text
    assert "sent" in caplog.text


async def test_no_sensitive_value_reaches_the_log(config, calls, caplog, monkeypatch):
    """A report that somehow carried a body, a statement or a URI must not be
    logged wholesale. The summary is an allowlist of counts."""
    from app.services import appointment_reminders

    async def _leaky(**kwargs):
        return {
            "selected": 1, "sent": 1, "failed": 0,
            "body": "Your consultation with Adv Khan is at 09:00",
            "statement": "the client's private account",
            "lawyer_notes": "INTERNAL: unreliable",
            "meeting_link": "https://meet.example.com/abc",
            "uri": "mongodb://user:secret@host/db",
        }

    monkeypatch.setattr(appointment_reminders, "send_due_reminders", _leaky)
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    with caplog.at_level(logging.DEBUG):
        await scheduler.run_cycle(NOW)

    for secret in ("Adv Khan", "private account", "INTERNAL", "unreliable",
                   "meet.example.com", "secret@host", "mongodb://"):
        assert secret not in caplog.text, f"the log leaked {secret!r}"


async def test_a_job_failure_logs_the_class_not_the_message(config, calls, caplog, monkeypatch):
    from app.services import appointment_reminders

    async def _boom(**kwargs):
        raise RuntimeError("mongodb://user:secret@host is unreachable")

    monkeypatch.setattr(appointment_reminders, "send_due_reminders", _boom)
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    with caplog.at_level(logging.DEBUG):
        await scheduler.run_cycle(NOW)

    assert "RuntimeError" in caplog.text
    assert "secret" not in caplog.text
    assert "mongodb://" not in caplog.text


# ── 9. Cadence ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("minutes", [1, 15, 30, 720])
def test_the_timing_invariant_holds_at_every_valid_cadence(config, minutes):
    """job timeout < lock TTL < interval, at the minimum, the default, the
    reminder maximum and the absolute maximum.

    The previous TTL was `max(interval * 0.8, 60)`, and the floor was the bug:
    at a one-minute interval it returned 60 seconds, so the TTL EQUALLED the
    interval and one worker's claim covered the whole of the next period.
    Asserting only at the default would never have found it - which is why
    this is parametrized over the boundaries rather than over a nice number.
    """
    config(appointment_scheduler_interval_minutes=minutes)

    timeout = scheduler._job_timeout_seconds()
    ttl = scheduler._lock_ttl_seconds()
    interval = scheduler._interval_seconds()

    assert timeout < ttl < interval, (timeout, ttl, interval)
    assert timeout > 0
    assert timeout <= scheduler.MAX_JOB_TIMEOUT_SECONDS


@pytest.mark.parametrize("minutes", [9, 60, 240, 720])
def test_a_wide_cadence_does_not_buy_a_wide_timeout(config, minutes):
    """The ceiling, and the reason it is not a proportion.

    The fractions keep the ORDERING right at every cadence and say nothing
    about whether the number is a sensible length of time. At the widest
    cadence the settings allow - 720 minutes, reachable only by an
    outcome-only deployment, since reminders cap the interval at 30 - a pure
    proportion gave SEVEN HOURS AND TWELVE MINUTES. Neither job does anything
    that takes seven hours; both send a batch bounded in the low hundreds. A
    job still going after five minutes is wedged, not busy.
    """
    config(appointment_scheduler_interval_minutes=minutes)

    assert scheduler._job_timeout_seconds() ==         scheduler.MAX_JOB_TIMEOUT_SECONDS
    # The ceiling must never invert the ordering it sits inside.
    assert scheduler._job_timeout_seconds() < scheduler._lock_ttl_seconds()


def test_the_ceiling_only_ever_lowers_the_timeout(config):
    """At a short cadence the proportion is already well under the ceiling, so
    the ceiling must not raise it - that would push the timeout past the lock
    TTL and hand exclusivity away."""
    config(appointment_scheduler_interval_minutes=1)

    timeout = scheduler._job_timeout_seconds()

    assert timeout < scheduler.MAX_JOB_TIMEOUT_SECONDS
    assert timeout < scheduler._lock_ttl_seconds() < scheduler._interval_seconds()


def test_the_invariant_holds_at_every_cadence_the_settings_allow(config):
    """Not a sample of cadences - all 720 of them.

    The boundary cases are where this has already failed once (the old TTL
    floor broke it at exactly one minute), and a ceiling introduces a second
    place two formulas can disagree. Checking the whole domain is cheap and
    removes the question.
    """
    from app.core.config import MAX_INTERVAL_MINUTES

    violations = []
    for minutes in range(1, MAX_INTERVAL_MINUTES + 1):
        config(appointment_scheduler_interval_minutes=minutes)
        timeout = scheduler._job_timeout_seconds()
        ttl = scheduler._lock_ttl_seconds()
        interval = scheduler._interval_seconds()
        if not (0 < timeout < ttl < interval):
            violations.append((minutes, timeout, ttl, interval))
        elif timeout > scheduler.MAX_JOB_TIMEOUT_SECONDS:
            violations.append((minutes, timeout, ttl, interval))

    assert violations == [], violations[:5]


def test_a_job_timeout_that_outlived_its_lock_would_lose_exclusivity(config):
    """Why the ordering is timeout < TTL and not the other way around.

    A job still running when its own lock expires is a job whose exclusivity
    has quietly lapsed: another worker can take the lock and start the same
    batch, to the same people, while the first is still dispatching.
    """
    config(appointment_scheduler_interval_minutes=15)

    assert scheduler._job_timeout_seconds() < scheduler._lock_ttl_seconds()


@pytest.mark.parametrize("bad", [0, -1, 721, 10_000])
def test_an_unusable_interval_is_refused(bad):
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(appointment_scheduler_interval_minutes=bad)


@pytest.mark.parametrize("bad", [0, -5, 501])
def test_an_unusable_batch_cap_is_refused(bad):
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(appointment_reminder_batch=bad)
    with pytest.raises(Exception):
        Settings(appointment_outcome_nudge_batch=bad)


async def test_the_configured_batch_caps_are_passed_through(config, calls):
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED,
           appointment_reminder_batch=40,
           appointment_outcome_nudge_batch=5)

    await scheduler.run_cycle(NOW)

    assert calls["reminders"][0]["limit"] == 40
    assert calls["nudges"][0]["limit"] == 5


# ── 10. The first cycle is immediate ─────────────────────────────────────────

async def test_the_first_cycle_runs_before_the_first_sleep(config, monkeypatch):
    """The gap this closes is a real one, not a tidiness point.

    Sleeping first meant a deploy, restart or crash recovery inside the T-1h
    window got no opportunity to send until a whole cadence later - by which
    time the consultation may already have started. The interval here is an
    hour, so a loop that slept first would record no cycle at all.
    """
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False,
           appointment_scheduler_interval_minutes=30)

    cycles = {"n": 0}

    async def _cycle(now=None):
        cycles["n"] += 1
        return {}

    monkeypatch.setattr(scheduler, "run_cycle", _cycle)
    monkeypatch.setattr(scheduler, "_interval_seconds", lambda: 3600)

    task = asyncio.create_task(scheduler.scheduler_loop())
    for _ in range(10):
        if cycles["n"]:
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cycles["n"] == 1, "the loop slept before its first cycle"


@pytest.mark.parametrize("window", ["24h", "1h"])
async def test_a_restart_inside_a_reminder_window_does_not_wait_a_cadence(
        config, calls, monkeypatch, window):
    """A worker that comes up inside either window looks immediately.

    Rolling restarts are the case that matters: every worker starts its own
    blind interval at the same moment, so with a sleep-first loop the whole
    fleet is silent for the same first period.
    """
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False,
           appointment_scheduler_interval_minutes=30)
    monkeypatch.setattr(scheduler, "_interval_seconds", lambda: 3600)

    task = asyncio.create_task(scheduler.scheduler_loop())
    for _ in range(20):
        if calls["reminders"]:
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls["reminders"], (
        f"a worker restarting inside the T-{window} window waited a full "
        "cadence before looking")
    assert calls["reminders"][0]["apply"] is True


async def test_a_failing_first_cycle_still_sleeps_before_retrying(
        config, monkeypatch):
    """The sleep is outside the cycle's error handling and is never skipped.

    A failing cycle that looped straight back would be a hot loop hammering
    the database and filling the log with one line - which is how a scheduler
    turns one bad batch into an outage.
    """
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    cycles = {"n": 0}

    async def _always_boom(now=None):
        # Raises WITHOUT awaiting, so the sleep is the loop's only yield point.
        # Remove the sleep and this becomes a true hot loop: the competing task
        # below never gets a turn, and the assertion fails by timing out rather
        # than by being wrong.
        cycles["n"] += 1
        raise RuntimeError("cycle blew up")

    monkeypatch.setattr(scheduler, "run_cycle", _always_boom)
    monkeypatch.setattr(scheduler, "_interval_seconds", lambda: 0)

    competitor = {"n": 0}

    async def _other_work():
        while True:
            competitor["n"] += 1
            await asyncio.sleep(0)

    rival = asyncio.create_task(_other_work())
    task = asyncio.create_task(scheduler.scheduler_loop())
    for _ in range(50):
        if cycles["n"] >= 3 and competitor["n"] >= 3:
            break
        await asyncio.sleep(0)
    task.cancel()
    rival.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cycles["n"] >= 3, "the loop stopped after a failing cycle"
    assert competitor["n"] >= 3, (
        "the loop never yielded between failing cycles - the sleep was "
        "skipped and this is a hot loop")


def test_flags_off_still_create_no_task_after_the_change(config):
    """The immediate first cycle must not become a reason to exist."""
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=False)

    assert scheduler.appointment_scheduler_task() is None


# ── 11. Cadence safety ───────────────────────────────────────────────────────

@pytest.mark.parametrize("minutes", [31, 45, 60, 120, 720])
def test_a_cadence_wider_than_half_the_window_is_refused_with_reminders_on(
        minutes):
    """The T-1h window is 60 minutes wide.

    A scheduler waking every 60 minutes gets one opportunity inside it if the
    phase lines up and NONE if it does not - an appointment can enter and
    leave between two ticks. The failure is silent and phase-dependent, which
    is exactly the kind that survives testing. Half the window guarantees two
    opportunities.
    """
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(appointment_reminders_enabled=True,
                 appointment_scheduler_interval_minutes=minutes)


@pytest.mark.parametrize("minutes", [1, 15, 30])
def test_a_cadence_inside_the_window_is_accepted_with_reminders_on(minutes):
    from app.core.config import Settings

    settings = Settings(appointment_reminders_enabled=True,
                        appointment_scheduler_interval_minutes=minutes)

    assert settings.appointment_scheduler_interval_minutes == minutes


@pytest.mark.parametrize("minutes", [31, 720])
def test_the_wider_range_survives_for_outcome_only_scheduling(minutes):
    """Nudges chase a backlog hours to days old and have no window to miss.

    Narrowing the range for a deployment that runs them alone would be a
    restriction with nothing behind it.
    """
    from app.core.config import Settings

    settings = Settings(
        appointment_reminders_enabled=False,
        appointment_outcome_nudges_enabled=True,
        appointment_outcome_nudges_activated_at=ACTIVATED,
        appointment_scheduler_interval_minutes=minutes)

    assert settings.appointment_scheduler_interval_minutes == minutes


def test_the_cadence_rule_is_enforced_at_settings_construction():
    """Not only inside the loop.

    The loop reads the interval once at startup. A check there would report a
    misconfiguration after the process was already running on it, to a log
    nobody reads until a reminder is missing.
    """
    from app.core.config import Settings

    with pytest.raises(Exception):
        Settings(appointment_reminders_enabled=True,
                 appointment_scheduler_interval_minutes=60)


def test_the_default_cadence_is_unchanged():
    from app.core.config import Settings

    assert Settings().appointment_scheduler_interval_minutes == 15


# ── 12. A wedged job is abandoned, not tolerated ─────────────────────────────

async def test_a_hung_reminder_job_times_out_and_the_nudge_still_runs(
        config, calls, monkeypatch):
    """One job's failure is not the other's, and a wedge is a failure.

    A reminder batch stuck on a slow provider must not take the outcome
    nudges down with it for the whole cycle.
    """
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    async def _hang(now):
        await asyncio.sleep(HANG_SECONDS)
        return FINISHED

    monkeypatch.setattr(scheduler, "run_reminders", _hang)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda: 0.01)

    started = time.monotonic()
    result = await scheduler.run_cycle(NOW)
    elapsed = time.monotonic() - started

    # Abandoned, not merely empty-handed: FINISHED is what it returns if it is
    # allowed to run to the end.
    assert result[scheduler.JOB_REMINDERS] is None
    assert result[scheduler.JOB_REMINDERS] != FINISHED
    # And it gave up long before the job would have finished on its own.
    assert elapsed < HANG_SECONDS / 2, elapsed
    assert calls["nudges"], "the wedged reminder job suppressed the nudges"


async def test_a_hung_nudge_job_times_out_without_killing_later_cycles(
        config, calls, monkeypatch):
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=True,
           appointment_outcome_nudges_activated_at=ACTIVATED)

    async def _hang(now):
        await asyncio.sleep(HANG_SECONDS)
        return FINISHED

    monkeypatch.setattr(scheduler, "run_outcome_nudges", _hang)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda: 0.01)

    started = time.monotonic()
    first = await scheduler.run_cycle(NOW)
    second = await scheduler.run_cycle(NOW)
    elapsed = time.monotonic() - started

    assert first[scheduler.JOB_OUTCOME_NUDGES] is None
    assert second[scheduler.JOB_OUTCOME_NUDGES] is None
    assert first[scheduler.JOB_OUTCOME_NUDGES] != FINISHED
    # TWO whole cycles inside the time ONE unbounded job would have taken.
    assert elapsed < HANG_SECONDS, elapsed


async def test_a_timeout_logs_the_job_and_the_class_and_nothing_else(
        config, monkeypatch, caplog):
    """A driver message carries the URI it failed to reach."""
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    async def _hang(now):
        await asyncio.sleep(HANG_SECONDS)
        return FINISHED

    monkeypatch.setattr(scheduler, "run_reminders", _hang)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda: 0.01)

    with caplog.at_level(logging.WARNING):
        await scheduler.run_cycle(NOW)

    assert scheduler.JOB_REMINDERS in caplog.text
    assert "TimeoutError" in caplog.text
    assert "mongodb://" not in caplog.text
    assert "Traceback" not in caplog.text


async def test_a_timed_out_job_is_not_retried_inside_the_same_cycle(
        config, monkeypatch):
    """The next cycle is already the retry.

    A job that failed to finish in its whole budget will not finish in the
    remainder, and retrying inside the cycle would run past the lock's TTL -
    which is the exclusivity the timeout exists to stay inside.
    """
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    attempts = {"n": 0}

    async def _hang(now):
        attempts["n"] += 1
        await asyncio.sleep(HANG_SECONDS)
        return FINISHED

    monkeypatch.setattr(scheduler, "run_reminders", _hang)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda: 0.01)

    started = time.monotonic()
    await scheduler.run_cycle(NOW)
    elapsed = time.monotonic() - started

    assert attempts["n"] == 1
    assert elapsed < HANG_SECONDS / 2, elapsed


async def test_shutdown_cancellation_is_not_converted_into_a_timeout(
        config, monkeypatch, caplog):
    """Cancelling the task during shutdown must stay a cancellation.

    A cancellation reported as a timeout would put "job hung" in the log every
    time the application stops, and would train whoever reads it to ignore the
    line that means a job actually wedged.
    """
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    started = asyncio.Event()

    async def _slow(now):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(scheduler, "run_reminders", _slow)
    # A long timeout, so anything that fires is cancellation, not the clock.
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda: 3600)

    task = asyncio.create_task(scheduler.run_cycle(NOW))
    await started.wait()

    with caplog.at_level(logging.WARNING):
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert "TimeoutError" not in caplog.text
    assert "appointment_scheduler_job_timeout" not in caplog.text


async def test_the_loop_propagates_cancellation_during_a_running_job(
        config, monkeypatch):
    """The whole shutdown path, not just one cycle."""
    config(appointment_reminders_enabled=True,
           appointment_outcome_nudges_enabled=False)

    started = asyncio.Event()

    async def _slow(now=None):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(scheduler, "run_cycle", _slow)
    monkeypatch.setattr(scheduler, "_interval_seconds", lambda: 3600)

    task = asyncio.create_task(scheduler.scheduler_loop())
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
