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
from datetime import datetime, timezone

import pytest

from app.services import appointment_scheduler as scheduler

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
ACTIVATED = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
def config():
    """Set scheduler settings for one test and always put them back."""
    from app.core.config import settings

    keys = ("appointment_reminders_enabled",
            "appointment_outcome_nudges_enabled",
            "appointment_outcome_nudges_activated_at",
            "appointment_scheduler_interval_minutes",
            "appointment_reminder_batch",
            "appointment_outcome_nudge_batch")
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


async def test_a_cycle_with_both_flags_off_dispatches_nothing(config, calls):
    config(appointment_reminders_enabled=False,
           appointment_outcome_nudges_enabled=False)

    result = await scheduler.run_cycle(NOW)

    assert result == {scheduler.JOB_REMINDERS: None,
                      scheduler.JOB_OUTCOME_NUDGES: None}
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
    erroring — that would let every worker dispatch the same batch."""
    import inspect

    source = inspect.getsource(scheduler)
    assert "acquire_period_lock_strict" in source
    assert "from app.core.redis_client import acquire_period_lock_strict" in source
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

def test_the_expiry_sweep_is_not_wired():
    """The one mechanism whose effect a client cannot undo — it terminates
    pending requests — and whose own prerequisites are unmet."""
    import inspect

    source = inspect.getsource(scheduler)
    assert "appointment_expiry" not in source
    assert "expire_lapsed_requests" not in source


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

def test_the_lock_ttl_sits_inside_the_interval(config):
    """A TTL past the interval would let one worker's claim suppress the NEXT
    period; one shorter than a run would let a second worker start the same
    batch mid-dispatch."""
    config(appointment_scheduler_interval_minutes=15)

    assert scheduler._lock_ttl_seconds() < scheduler._interval_seconds()
    assert scheduler._lock_ttl_seconds() >= 60


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
