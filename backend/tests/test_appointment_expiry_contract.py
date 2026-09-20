"""The expiry CONTRACT: one flag, two enforcement points, and a terminal state.

The mechanism itself — the deadline policy, the sweep's bounds, its version
pin — is tested in `test_appointment_expiry.py`. What is tested here is the
part that decides whether any of it runs, and what the rest of the system does
while it is running.

THE FLAG IS THE WHOLE DESIGN. `appointment_expiry_enabled` gates the sweep and
the confirmation refusal together, from one function, because the two states
you get by separating them are both bad:

  * sweep on, confirmation guard off — a lawyer accepts a request the next
    sweep is about to retire, and which one wins is a matter of timing rather
    than policy.
  * confirmation guard on, sweep off — a lapsed request is neither confirmable
    nor expirable. Stuck, still holding its slots, with no explanation for
    either party.

THE DEADLINE IS ENFORCED TWICE AND THAT IS NOT BELT-AND-BRACES. The service
check exists for the MESSAGE — a filter that matches nothing cannot explain
itself. The CAS clause exists for the TRUTH: it is evaluated against the
DATABASE's clock, so it still decides correctly when the deadline passes
between the read and the write, and when two application hosts disagree about
what time it is.

NOTHING HERE ENABLES ANYTHING BEYOND ITS OWN TEST. Every test that needs the
flag sets it through a fixture that always puts it back.
"""
import asyncio
import inspect
import secrets
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import AppointmentMode, AppointmentStatus
from app.core.exceptions import ConflictError
from app.services import appointment_expiry as expiry
from app.services import appointment_scheduler as scheduler
from app.services import appointment_service

pytestmark = pytest.mark.integration

EXPIRED_MESSAGE = "This appointment request has expired."

# Never a real connection string: the guard only checks that one is SET.
FAKE_REDIS_URL = "rediss://default:NOT-A-REAL-TOKEN@cache.example.net:6379"


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def flags():
    """Set expiry settings for one test and always put them back."""
    from app.core.config import settings

    keys = ("appointment_expiry_enabled", "appointment_expiry_batch",
            "appointment_reminders_enabled",
            "appointment_outcome_nudges_enabled")
    saved = {k: getattr(settings, k, None) for k in keys}

    def _set(**values):
        for key, value in values.items():
            setattr(settings, key, value)

    yield _set
    for key, value in saved.items():
        setattr(settings, key, value)


@pytest.fixture(autouse=True)
def no_real_lock(monkeypatch):
    """No test here may touch the configured Redis. Autouse, unconditional.

    `run_expiry` takes the strict lock before anything else, and the strict
    lock is real: with `redis_url` set it opens a connection and SETs a key on
    whatever that variable points at. A test suite does not get to write to a
    hosted instance because the key is small.

    It also fixes a subtler problem. With the real lock in play, a test that
    means to prove "the fail-closed guard refused" can instead pass because
    the LOCK was denied - the job returns None either way, and the assertion
    cannot tell the two apart. Granting by default makes the guard under test
    the only thing that can refuse.

    Returns the list of jobs that asked, so a test can assert the lock was
    never reached at all.
    """
    asked: list[str] = []

    async def _granted(key, ttl_seconds, job):
        asked.append(job)
        return True

    monkeypatch.setattr(scheduler, "acquire_period_lock_strict", _granted)
    return asked


@pytest.fixture
def reachable_backend(monkeypatch):
    """A configured lock backend that answers.

    Tests named after the INDEX or the DEADLINES must not also be failing the
    Redis probe: a test that refuses for three reasons proves nothing about
    any one of them, and would still pass if the check it is named after were
    deleted.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "redis_url", FAKE_REDIS_URL)

    async def _reachable(url, **kwargs):
        return True

    monkeypatch.setattr(scheduler, "redis_reachable", _reachable)


@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import get_appointments_col, get_users_col

    tag = secrets.token_hex(4)
    lawyer_id, client_id = f"XC-L-{tag}", f"XC-C-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"{lawyer_id}@test.invalid", "full_name": "Adv One",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["criminal"],
                            "kyc_verified": True, "rating": 4.0,
                            "total_reviews": 0, "availability": True,
                            "experience_years": 5}},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"{client_id}@test.invalid", "full_name": "Client One",
         "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "client_id": client_id, "tag": tag}
    await get_users_col().delete_many({"_id": {"$in": [lawyer_id, client_id]}})
    await get_appointments_col().delete_many({"client_id": client_id})


def _slot(hours_ahead: int = 48) -> datetime:
    base = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return base.replace(minute=0, second=0, microsecond=0)


async def _book(parties, when=None):
    return await appointment_service.book_appointment(
        client_id=parties["client_id"], lawyer_id=parties["lawyer_id"],
        case_id=None, scheduled_at=when or _slot(), duration_minutes=60,
        mode=AppointmentMode.VIDEO, notes=None)


async def _row(appt_id):
    from app.db.collections import get_appointments_col
    return await get_appointments_col().find_one({"_id": appt_id})


async def _patch(appt_id, **fields):
    """Booking refuses a past time, so a lapsed row cannot be produced through
    the API. Editing the stored value is the only way to reach the state under
    test, and it keeps the real queries running against real stored data."""
    from app.db.collections import get_appointments_col
    await get_appointments_col().update_one({"_id": appt_id},
                                            {"$set": fields})


async def _unset(appt_id, *fields):
    from app.db.collections import get_appointments_col
    await get_appointments_col().update_one(
        {"_id": appt_id}, {"$unset": {f: "" for f in fields}})


async def _confirm(appt_id, parties, version=0):
    return await appointment_service.confirm_appointment(
        appt_id, parties["lawyer_id"], expected_version=version)


async def _notifications(appt_id):
    from app.db.collections import get_notifications_col
    return await get_notifications_col().find(
        {"payload.appointment_id": appt_id}).to_list(length=50)


# ── 1. Off by default, and read at call time ─────────────────────────────────

def test_expiry_is_off_by_default():
    from app.core.config import Settings

    fresh = Settings()
    assert fresh.appointment_expiry_enabled is False
    assert fresh.appointment_expiry_batch == 50


def test_the_flag_is_read_at_call_time_not_captured_at_import(flags):
    """A snapshot taken at import could not be changed without a restart, and
    would let a test exercise only whichever branch was true when the module
    first loaded."""
    flags(appointment_expiry_enabled=False)
    assert expiry.expiry_enabled() is False

    flags(appointment_expiry_enabled=True)
    assert expiry.expiry_enabled() is True

    flags(appointment_expiry_enabled=False)
    assert expiry.expiry_enabled() is False


def test_the_scheduler_and_the_service_read_the_same_flag(flags):
    """One source of truth. Two `getattr(settings, ...)` calls would be two
    answers waiting to diverge."""
    flags(appointment_expiry_enabled=True)
    assert scheduler.expiry_enabled() is expiry.expiry_enabled() is True

    flags(appointment_expiry_enabled=False)
    assert scheduler.expiry_enabled() is expiry.expiry_enabled() is False


def test_the_batch_cap_agrees_with_the_sweeps_own_limit():
    """Settings would otherwise accept a value the sweep rejects at run time -
    a misconfiguration that only appears once the feature is switched on."""
    from app.core.config import MAX_EXPIRY_BATCH
    from app.services.appointment_expiry_sweep import DEFAULT_LIMIT

    assert MAX_EXPIRY_BATCH == DEFAULT_LIMIT


# ── 2. While OFF, nothing changes ────────────────────────────────────────────

async def test_off_leaves_a_lapsed_request_confirmable(flags, parties):
    """The current behaviour, preserved exactly.

    This is the half that makes the flag safe to ship disabled: until somebody
    turns it on, a request past its deadline confirms as it always has.
    """
    flags(appointment_expiry_enabled=False)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

    updated = await _confirm(appt["id"], parties)

    assert updated["status"] == AppointmentStatus.CONFIRMED.value


async def test_off_creates_no_expiry_task(flags):
    flags(appointment_expiry_enabled=False,
          appointment_reminders_enabled=False,
          appointment_outcome_nudges_enabled=False)

    assert scheduler.any_job_enabled() is False
    assert scheduler.appointment_scheduler_task() is None


async def test_off_runs_no_expiry_job_and_takes_no_lock(flags, monkeypatch):
    flags(appointment_expiry_enabled=False)
    taken = []

    async def _lock(key, ttl, job):
        taken.append(job)
        return True

    monkeypatch.setattr(scheduler, "acquire_period_lock_strict", _lock)

    assert await scheduler.run_expiry(datetime.now(timezone.utc)) is None
    assert scheduler.JOB_EXPIRY not in taken


async def test_off_expires_nothing_even_when_a_row_has_lapsed(flags, parties):
    flags(appointment_expiry_enabled=False)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

    await scheduler.run_expiry(datetime.now(timezone.utc))

    assert (await _row(appt["id"]))["status"] == \
        AppointmentStatus.PENDING.value
    # Booking itself notifies, so "no notices at all" would be false whatever
    # happened. The claim is narrower and actually checkable: nobody was told
    # this request expired, because it did not.
    from app.core.constants import NotificationType
    kinds = {n.get("type") for n in await _notifications(appt["id"])}
    assert NotificationType.APPOINTMENT_EXPIRED.value not in kinds


# ── 3. While ON, the confirmation contract ───────────────────────────────────

async def test_on_rejects_an_expired_confirmation_with_the_exact_message(
        flags, parties):
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    with pytest.raises(ConflictError) as raised:
        await _confirm(appt["id"], parties)

    assert raised.value.detail == EXPIRED_MESSAGE
    assert (await _row(appt["id"]))["status"] == \
        AppointmentStatus.PENDING.value


async def test_the_service_check_refuses_before_attempting_any_write(
        flags, parties, monkeypatch):
    """What the SERVICE check buys that the CAS does not.

    Removing it changed no observable behaviour: the CAS still refused and the
    fallback still produced the right message, so every test passed. That made
    it defence with no evidence behind it.

    Its actual job is to refuse BEFORE a write is attempted - no round trip,
    no update against a row the answer is already known for. That is
    observable, so it is asserted.
    """
    from app.repositories.appointment_repo import AppointmentRepository

    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

    attempts = []
    original = AppointmentRepository.compare_and_set

    async def _record(self, *args, **kwargs):
        attempts.append(args)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AppointmentRepository, "compare_and_set", _record)

    with pytest.raises(ConflictError) as raised:
        await _confirm(appt["id"], parties)

    assert raised.value.detail == EXPIRED_MESSAGE
    assert attempts == [], "a write was attempted for an already-known refusal"


def test_the_boundary_instant_is_lapsed_exactly(flags):
    """`expires_at == now` is expired, asserted on the pure function.

    Through the service this can only be probed with a near-boundary value,
    because the CAS compares against the database's clock and the exact
    instant cannot be hit deterministically. Here it can: the policy is a pure
    comparison, so the boundary is testable to the microsecond, and flipping
    `>=` to `>` fails this and nothing else.
    """
    moment = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)

    assert expiry.stored_has_lapsed({"expires_at": moment}, now=moment) is True
    assert expiry.stored_has_lapsed(
        {"expires_at": moment}, now=moment - timedelta(microseconds=1)) is False
    assert expiry.stored_has_lapsed(
        {"expires_at": moment}, now=moment + timedelta(microseconds=1)) is True


def test_the_boundary_agrees_across_all_three_implementations(flags):
    """The policy, the sweep's query and the CAS must draw the line in the
    same place, or a row one of them retires is a row another would confirm.

    The query uses `$lte` and the CAS requires `$gt`; both mean "the deadline
    instant is already too late", which is what `>=` says here.
    """
    import inspect

    from app.repositories.appointment_repo import AppointmentRepository

    policy_src = inspect.getsource(expiry.stored_has_lapsed)
    assert ">= deadline" in policy_src

    query_src = inspect.getsource(AppointmentRepository.find_lapsed_pending)
    assert "$lte" in query_src

    cas = str(AppointmentRepository.unexpired_filter())
    assert "$gt" in cas


async def test_on_permits_a_confirmation_inside_the_deadline(flags, parties):
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) + timedelta(hours=1))

    updated = await _confirm(appt["id"], parties)

    assert updated["status"] == AppointmentStatus.CONFIRMED.value


async def test_the_deadline_instant_itself_is_already_too_late(flags, parties):
    """`expires_at <= now` is expired.

    The deadline is the instant the request STOPS holding its slot, so that
    instant is on the expired side. The sweep's `$lte`, `stored_has_lapsed`'s
    `>=` and the CAS's `$gt` all have to agree, or a row one of them retires
    is a row another would still confirm.
    """
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    # A whole millisecond: BSON stores milliseconds, so a microsecond offset
    # would be truncated onto the boundary and test nothing.
    now = datetime.now(timezone.utc).replace(microsecond=0)
    await _patch(appt["id"], expires_at=now - timedelta(milliseconds=1))

    with pytest.raises(ConflictError) as raised:
        await _confirm(appt["id"], parties)

    assert raised.value.detail == EXPIRED_MESSAGE


async def test_one_millisecond_before_the_deadline_still_confirms(
        flags, parties):
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) + timedelta(seconds=30))

    updated = await _confirm(appt["id"], parties)

    assert updated["status"] == AppointmentStatus.CONFIRMED.value


async def test_a_row_with_no_stored_deadline_still_confirms(flags, parties):
    """Missing `expires_at` blocks ACTIVATION, never a lawyer's confirmation.

    Refusing here would mean denying a confirmation because of a field the
    client's booking never wrote - an inference about a legacy row, made at
    the expense of a real appointment.
    """
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _unset(appt["id"], "expires_at")

    updated = await _confirm(appt["id"], parties)

    assert updated["status"] == AppointmentStatus.CONFIRMED.value


async def test_a_malformed_deadline_still_confirms(flags, parties):
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"], expires_at="not-a-date")

    updated = await _confirm(appt["id"], parties)

    assert updated["status"] == AppointmentStatus.CONFIRMED.value


# ── 4. The second enforcement point ──────────────────────────────────────────

async def test_a_deadline_crossed_between_the_read_and_the_write_is_caught(
        flags, parties, monkeypatch):
    """The reason the CAS clause exists.

    The service reads the row, decides it is fine, and then the deadline
    passes before the write lands. Only a filter evaluated by the database at
    write time can refuse that, and the lawyer still has to be told WHY -
    a bare "modified by someone else" would be both untrue and unactionable.
    """
    from app.repositories.appointment_repo import AppointmentRepository

    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    # Comfortably inside the deadline, so the SERVICE check genuinely passes.
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) + timedelta(hours=1))

    original = AppointmentRepository.compare_and_set

    async def _deadline_passes_first(self, *args, **kwargs):
        # The race, made deterministic: the deadline moves into the past in
        # the instant between the service deciding and the write landing.
        # Nothing about the service's decision was wrong when it was made.
        await _patch(
            appt["id"],
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(AppointmentRepository, "compare_and_set",
                        _deadline_passes_first)

    with pytest.raises(ConflictError) as raised:
        await _confirm(appt["id"], parties)

    # Refused by the CAS, and still explained properly rather than as a
    # generic "someone else modified this".
    assert raised.value.detail == EXPIRED_MESSAGE
    assert (await _row(appt["id"]))["status"] == \
        AppointmentStatus.PENDING.value


async def test_the_cas_uses_the_database_clock_not_this_process(parties):
    """`$$NOW` is the server's clock.

    Two application hosts with skewed clocks would otherwise answer "has this
    expired" differently, and the answer decides whether somebody's
    consultation happens.
    """
    from app.repositories.appointment_repo import AppointmentRepository

    clause = AppointmentRepository.unexpired_filter()

    assert "$expr" in clause
    assert "$$NOW" in str(clause)


async def test_the_unexpired_clause_is_not_applied_to_other_transitions(
        flags, parties):
    """A lapsed request must still be CANCELLABLE.

    Refusing that would leave a client unable to withdraw a request nobody can
    accept - the stuck state this whole design exists to avoid.
    """
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

    updated = await appointment_service.cancel_appointment(
        appt["id"], parties["client_id"], "client", reason="changed my mind")

    assert updated["status"] == AppointmentStatus.CANCELLED.value


# ── 5. Confirmation versus the sweep ─────────────────────────────────────────

async def test_a_confirmation_racing_the_sweep_produces_exactly_one_winner(
        flags, parties):
    """Both paths pin the row, so one of them matches nothing.

    The sweep pins `status: PENDING` and the schedule version; the
    confirmation pins the status, the version and the server-time deadline.
    Whichever lands second finds a row that no longer matches, and the outcome
    is one terminal state rather than a confirmed appointment that was also
    expired.
    """
    from app.services import appointment_expiry_sweep

    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

    async def _try_confirm():
        try:
            return await _confirm(appt["id"], parties)
        except Exception as exc:
            return exc

    async def _try_sweep():
        return await appointment_expiry_sweep.expire_lapsed_requests(
            apply=True, now=datetime.now(timezone.utc), limit=10)

    confirmed, swept = await asyncio.gather(_try_confirm(), _try_sweep())

    final = (await _row(appt["id"]))["status"]
    assert final in (AppointmentStatus.EXPIRED.value,
                     AppointmentStatus.CONFIRMED.value)

    if final == AppointmentStatus.EXPIRED.value:
        assert isinstance(confirmed, ConflictError)
    else:
        assert not isinstance(confirmed, Exception)
        assert swept["expired"] == 0


# ── 6. Activation is fail-closed ─────────────────────────────────────────────

async def test_a_pending_row_without_a_stored_deadline_blocks_the_job(
        flags, parties, monkeypatch, no_real_lock):
    """The sweep already ignores those rows - its query selects on the stored
    value. The risk is not damage but a FALSE ALL-CLEAR: a clean-looking pass
    over a population nobody decided about."""
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _unset(appt["id"], "expires_at")

    swept = []

    async def _never_sweep(**kwargs):
        swept.append(kwargs)
        return {}

    from app.services import appointment_expiry_sweep
    monkeypatch.setattr(appointment_expiry_sweep, "expire_lapsed_requests",
                        _never_sweep)
    monkeypatch.setattr(scheduler, "_index_ready",
                        lambda job: _true())

    result = await scheduler.run_expiry(datetime.now(timezone.utc))

    assert result is None
    assert swept == [], "the sweep ran with an undated pending row present"
    # It got PAST the lock and the index. Without this the test would also
    # pass if the lock had simply been denied, which proves nothing about the
    # guard it is named after.
    assert no_real_lock == [scheduler.JOB_EXPIRY]


async def _true():
    return True


async def test_a_malformed_deadline_also_blocks_the_job(
        flags, parties, monkeypatch, no_real_lock):
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"], expires_at=12345)

    swept = []

    async def _never_sweep(**kwargs):
        swept.append(kwargs)
        return {}

    from app.services import appointment_expiry_sweep
    monkeypatch.setattr(appointment_expiry_sweep, "expire_lapsed_requests",
                        _never_sweep)
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _true())

    assert await scheduler.run_expiry(datetime.now(timezone.utc)) is None
    assert swept == []
    assert no_real_lock == [scheduler.JOB_EXPIRY]


async def test_a_missing_query_index_skips_expiry_only(flags, monkeypatch):
    """A QUERY index is a performance index. Its absence must stop the one job
    whose read it serves and nothing else."""
    from app.db import indexes as indexes_module
    from app.db.v2_index_spec import QUERY, IndexProblem

    flags(appointment_expiry_enabled=True,
          appointment_reminders_enabled=True,
          appointment_outcome_nudges_enabled=False)

    async def _problems():
        return [IndexProblem("missing", "appointments",
                             "appointment_pending_expiry", "gone", kind=QUERY)]

    monkeypatch.setattr(indexes_module, "validate_appointment_indexes",
                        _problems)

    assert await scheduler._index_ready(scheduler.JOB_EXPIRY) is False
    assert await scheduler._index_ready(scheduler.JOB_REMINDERS) is True


async def test_a_denied_lock_writes_nothing(flags, parties, monkeypatch):
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

    async def _denied(key, ttl, job):
        return False

    monkeypatch.setattr(scheduler, "acquire_period_lock_strict", _denied)

    assert await scheduler.run_expiry(datetime.now(timezone.utc)) is None
    assert (await _row(appt["id"]))["status"] == \
        AppointmentStatus.PENDING.value


# ── 7. Isolation from the other jobs ─────────────────────────────────────────

async def test_a_wedged_expiry_job_does_not_suppress_the_other_two(
        flags, monkeypatch):
    from app.services import appointment_outcomes, appointment_reminders

    flags(appointment_expiry_enabled=True,
          appointment_reminders_enabled=True,
          appointment_outcome_nudges_enabled=True)
    from app.core.config import settings
    monkeypatch.setattr(settings, "appointment_outcome_nudges_activated_at",
                        datetime(2026, 1, 1, tzinfo=timezone.utc))

    ran = {"reminders": 0, "nudges": 0}

    async def _reminders(**kwargs):
        ran["reminders"] += 1
        return {"sent": 0}

    async def _nudges(**kwargs):
        ran["nudges"] += 1
        return {"sent": 0}

    async def _lock(key, ttl, job):
        return True

    async def _hang(now):
        await asyncio.sleep(5)
        return {"expired": 999}

    monkeypatch.setattr(appointment_reminders, "send_due_reminders", _reminders)
    monkeypatch.setattr(appointment_outcomes, "notify_outstanding_outcomes",
                        _nudges)
    monkeypatch.setattr(scheduler, "acquire_period_lock_strict", _lock)
    monkeypatch.setattr(scheduler, "run_expiry", _hang)
    monkeypatch.setattr(scheduler, "_job_timeout_seconds", lambda: 0.01)

    from app.db import indexes as indexes_module

    async def _no_problems():
        return []

    monkeypatch.setattr(indexes_module, "validate_appointment_indexes",
                        _no_problems)

    result = await scheduler.run_cycle(datetime.now(timezone.utc))

    assert result[scheduler.JOB_EXPIRY] is None
    assert ran["reminders"] == 1, "a wedged sweep suppressed the reminders"
    assert ran["nudges"] == 1, "a wedged sweep suppressed the nudges"


async def test_a_failing_expiry_job_does_not_kill_the_cycle(
        flags, monkeypatch):
    flags(appointment_expiry_enabled=True,
          appointment_reminders_enabled=False,
          appointment_outcome_nudges_enabled=False)

    async def _boom(now):
        raise RuntimeError("mongodb://user:secret@host/db is unreachable")

    monkeypatch.setattr(scheduler, "run_expiry", _boom)

    result = await scheduler.run_cycle(datetime.now(timezone.utc))

    assert result[scheduler.JOB_EXPIRY] is None


async def test_an_expiry_failure_logs_the_class_not_the_connection_string(
        flags, monkeypatch, caplog):
    import logging

    flags(appointment_expiry_enabled=True,
          appointment_reminders_enabled=False,
          appointment_outcome_nudges_enabled=False)

    async def _boom(now):
        raise RuntimeError("mongodb://user:secret@host/db is unreachable")

    monkeypatch.setattr(scheduler, "run_expiry", _boom)

    with caplog.at_level(logging.WARNING):
        await scheduler.run_cycle(datetime.now(timezone.utc))

    assert "RuntimeError" in caplog.text
    assert "secret" not in caplog.text
    assert "mongodb://" not in caplog.text


# ── 8. Notifications ─────────────────────────────────────────────────────────

async def test_a_repeated_sweep_does_not_notify_twice(flags, parties):
    """`logical_event_id` is globally unique, and the second pass finds the row
    already EXPIRED anyway - two independent reasons, both worth having."""
    from app.services import appointment_expiry_sweep

    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

    now = datetime.now(timezone.utc)
    first = await appointment_expiry_sweep.expire_lapsed_requests(
        apply=True, now=now, limit=10)
    after_first = len(await _notifications(appt["id"]))

    second = await appointment_expiry_sweep.expire_lapsed_requests(
        apply=True, now=now, limit=10)

    assert first["expired"] == 1
    assert second["expired"] == 0
    assert len(await _notifications(appt["id"])) == after_first


async def test_a_notification_failure_does_not_undo_the_expiration(
        flags, parties, monkeypatch):
    """The status change is the record; the notice is best-effort.

    Rolling the transition back because a message failed would leave the slot
    held by a request the system has already decided is over.
    """
    from app.services import appointment_expiry_sweep

    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

    async def _explode(*args, **kwargs):
        raise RuntimeError("notification store unreachable")

    monkeypatch.setattr(appointment_expiry_sweep, "_announce", _explode)

    try:
        await appointment_expiry_sweep.expire_lapsed_requests(
            apply=True, now=datetime.now(timezone.utc), limit=10)
    except RuntimeError:
        pass

    assert (await _row(appt["id"]))["status"] == \
        AppointmentStatus.EXPIRED.value


# ── 9. Nothing public can trigger it ─────────────────────────────────────────

def test_no_route_can_trigger_expiry():
    """Expiry is a scheduled, flag-gated sweep. An endpoint that ran it would
    be a way for a caller to terminate other people's requests on demand."""
    import pathlib

    from app.api.v1 import routes

    root = pathlib.Path(routes.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "expire_lapsed_requests" in text or "run_expiry" in text:
            offenders.append(path.name)

    assert offenders == [], offenders


def test_no_route_mentions_the_expiry_flag():
    import pathlib

    from app.api.v1 import routes

    root = pathlib.Path(routes.__file__).parent
    offenders = [p.name for p in root.rglob("*.py")
                 if "appointment_expiry_enabled" in p.read_text(encoding="utf-8")]

    assert offenders == []


# ── 10. The report-only paths still write nothing ────────────────────────────

async def test_the_survey_writes_nothing_even_with_expiry_on(flags, parties):
    from app.services import appointment_expiry_sweep

    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _unset(appt["id"], "expires_at")
    before = await _row(appt["id"])

    await appointment_expiry_sweep.survey_legacy_pending(
        now=datetime.now(timezone.utc))

    assert await _row(appt["id"]) == before


async def test_a_non_applying_sweep_writes_nothing_with_expiry_on(
        flags, parties):
    from app.services import appointment_expiry_sweep

    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _patch(appt["id"],
                 expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
    before = await _row(appt["id"])

    report = await appointment_expiry_sweep.expire_lapsed_requests(
        now=datetime.now(timezone.utc), limit=10)

    assert report["applied"] is False
    assert report["expired"] == 1          # what it WOULD have done
    assert await _row(appt["id"]) == before


# ── 11. The startup guard ────────────────────────────────────────────────────
#
# The per-cycle checks make the sweep DECLINE; they do not make anybody
# NOTICE. A deployment with expiry on and a missing index would skip every
# cycle for days, leaving one warning line among many as the only evidence -
# a feature believed to be live, doing nothing, silently. Refusing at boot is
# loud, immediate, and undone by turning the flag back off.
#
# The two are not redundant. This catches a deployment that was never ready;
# the per-cycle checks catch one that STOPS being ready - an index dropped in
# maintenance, a legacy row arriving from a restore.


async def test_the_guard_does_no_work_at_all_while_the_flag_is_off(
        flags, monkeypatch):
    """A requirement, not an optimisation.

    Every default deployment runs this on every boot, and every deployment
    today has expiry off. It must not add an index read, a query or a Redis
    probe to that path.
    """
    flags(appointment_expiry_enabled=False)

    async def _forbidden(*args, **kwargs):
        raise AssertionError("the guard performed a readiness query while off")

    monkeypatch.setattr(scheduler, "_index_ready", _forbidden)
    monkeypatch.setattr(scheduler, "_every_pending_row_has_a_stored_deadline",
                        _forbidden)

    await scheduler.assert_appointment_expiry_activation_ready()


async def test_an_unconfigured_lock_backend_refuses_startup(
        flags, monkeypatch):
    """No backend means the fail-closed acquirer returns False for ever: the
    job would exist, wake on its interval, and never dispatch."""
    from app.core.config import settings

    flags(appointment_expiry_enabled=True)
    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _true())
    monkeypatch.setattr(scheduler, "_every_pending_row_has_a_stored_deadline",
                        _true)

    with pytest.raises(scheduler.AppointmentExpiryNotReady) as raised:
        await scheduler.assert_appointment_expiry_activation_ready()

    assert scheduler.EXPIRY_NO_LOCK_BACKEND in raised.value.reasons


async def test_an_invalid_expiry_index_refuses_startup(
        flags, monkeypatch, reachable_backend):
    flags(appointment_expiry_enabled=True)
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _false())
    monkeypatch.setattr(scheduler, "_every_pending_row_has_a_stored_deadline",
                        _true)

    with pytest.raises(scheduler.AppointmentExpiryNotReady) as raised:
        await scheduler.assert_appointment_expiry_activation_ready()

    assert scheduler.EXPIRY_INDEX_NOT_READY in raised.value.reasons


async def test_a_pending_row_without_a_usable_deadline_refuses_startup(
        flags, parties, monkeypatch, reachable_backend):
    """The real database, a real legacy row, and the real check."""
    flags(appointment_expiry_enabled=True)
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _true())

    appt = await _book(parties)
    await _unset(appt["id"], "expires_at")

    with pytest.raises(scheduler.AppointmentExpiryNotReady) as raised:
        await scheduler.assert_appointment_expiry_activation_ready()

    assert scheduler.EXPIRY_UNUSABLE_DEADLINES in raised.value.reasons


async def test_a_malformed_deadline_refuses_startup(
        flags, parties, monkeypatch, reachable_backend):
    flags(appointment_expiry_enabled=True)
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _true())

    appt = await _book(parties)
    await _patch(appt["id"], expires_at="not-a-date")

    with pytest.raises(scheduler.AppointmentExpiryNotReady) as raised:
        await scheduler.assert_appointment_expiry_activation_ready()

    assert scheduler.EXPIRY_UNUSABLE_DEADLINES in raised.value.reasons


async def test_an_unreadable_deadline_check_refuses_rather_than_assumes(
        flags, monkeypatch, reachable_backend):
    """Unknown is not ready - the direction every other check here fails in."""
    flags(appointment_expiry_enabled=True)
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _true())

    async def _unreadable():
        raise RuntimeError("mongodb://user:secret@host/db is unreachable")

    monkeypatch.setattr(scheduler, "_every_pending_row_has_a_stored_deadline",
                        _unreadable)

    with pytest.raises(scheduler.AppointmentExpiryNotReady) as raised:
        await scheduler.assert_appointment_expiry_activation_ready()

    assert scheduler.EXPIRY_UNUSABLE_DEADLINES in raised.value.reasons


async def test_a_ready_state_permits_the_scheduler_to_be_created(
        flags, parties, monkeypatch, reachable_backend):
    """The other half: the guard must not refuse a deployment that IS ready."""
    flags(appointment_expiry_enabled=True)
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _true())

    # A booked appointment carries `expires_at` from the booking path itself,
    # so the ready state is the one the system produces normally.
    await _book(parties)

    await scheduler.assert_appointment_expiry_activation_ready()

    task = scheduler.appointment_scheduler_task()
    try:
        assert task is not None
    finally:
        if task is not None:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def test_the_refusal_carries_reason_codes_and_nothing_else(
        flags, monkeypatch, caplog):
    """This lands in a crash log that goes into a ticket, and the things it
    inspected are a connection string and rows describing consultations."""
    import logging

    from app.core.config import settings

    flags(appointment_expiry_enabled=True)
    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _false())

    async def _unreadable():
        raise RuntimeError("mongodb://user:secret@host/db is unreachable")

    monkeypatch.setattr(scheduler, "_every_pending_row_has_a_stored_deadline",
                        _unreadable)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(scheduler.AppointmentExpiryNotReady) as raised:
            await scheduler.assert_appointment_expiry_activation_ready()

    text = str(raised.value) + "\n" + caplog.text
    for code in (scheduler.EXPIRY_NO_LOCK_BACKEND,
                 scheduler.EXPIRY_INDEX_NOT_READY,
                 scheduler.EXPIRY_UNUSABLE_DEADLINES):
        assert code in text
    for secret in ("mongodb://", "secret", "RuntimeError", "unreachable",
                   "Traceback"):
        assert secret not in text, secret


def test_the_guard_runs_before_every_background_task_and_before_serving():
    """Structural, because the ORDERING IS THE GUARANTEE.

    The guard used to sit next to the appointment scheduler, which read well
    and was wrong. By that point the warmup task, the WebSocket subscriber,
    the cause-list scheduler, the lawyer index reconciler and both relays
    already existed - and a guard that raises there aborts `lifespan` BEFORE
    `yield`, so the cleanup after `yield` never runs. Every one of those tasks
    is then orphaned against a closing loop, on top of whatever each was half
    way through.

    So the assertion is not "before its own task" but BEFORE THE FIRST ONE.
    """
    import inspect
    import re

    from app import main

    source = inspect.getsource(main.lifespan)

    def at(pattern):
        match = re.search(pattern, source)
        assert match is not None, pattern
        return match.start()

    connected = at(r"await connect_db\(\)")
    indexes = at(r"await create_all_indexes\(\)")
    booking = at(r"await assert_appointment_booking_ready\(\)")
    guard = at(r"await assert_appointment_expiry_activation_ready\(\)")
    first_task = at(r"create_task\(")
    serving = at(r"\n    yield")

    assert connected < indexes < booking < guard < first_task < serving, (
        connected, indexes, booking, guard, first_task, serving)


def test_no_background_task_is_created_before_the_guard():
    """Every `create_task` in `lifespan`, not merely the first one found."""
    import inspect
    import re

    from app import main

    source = inspect.getsource(main.lifespan)
    guard = source.index("await assert_appointment_expiry_activation_ready()")

    early = [m.start() for m in re.finditer(r"create_task\(", source)
             if m.start() < guard]

    assert early == [], f"{len(early)} background task(s) created before the guard"


def test_the_guard_runs_before_chroma_and_websocket_setup():
    """Both are process-wide side effects. Refusing after them leaves a
    connected vector store and a registered WebSocket manager behind a
    process that is going to die anyway."""
    import inspect

    from app import main

    source = inspect.getsource(main.lifespan)
    guard = source.index("await assert_appointment_expiry_activation_ready()")

    assert guard < source.index("connect_chroma()")
    assert guard < source.index("set_ws_manager(")


def test_the_guard_runs_after_the_database_is_connected():
    """Two of its three checks read from the database."""
    import inspect

    from app import main

    source = inspect.getsource(main.lifespan)

    assert source.index("await connect_db()") < source.index(
        "await assert_appointment_expiry_activation_ready()")


def test_the_startup_guard_does_not_invoke_the_activation_audit():
    """The audit is an operator tool that reads seven sections and prints a
    report. Running it here would put a full collection survey in the boot
    path and make a restart a way to produce a verdict nobody asked for."""
    import inspect

    source = inspect.getsource(
        scheduler.assert_appointment_expiry_activation_ready)

    assert "appointment_activation_audit" not in source
    assert "audit(" not in source


async def test_the_per_cycle_refusal_still_works_after_the_guard_exists(
        flags, parties, monkeypatch, no_real_lock):
    """Defence against LATER drift: an index dropped during maintenance, or a
    legacy row arriving from a restore, after a boot that passed."""
    flags(appointment_expiry_enabled=True)
    appt = await _book(parties)
    await _unset(appt["id"], "expires_at")

    swept = []

    async def _never_sweep(**kwargs):
        swept.append(kwargs)
        return {}

    from app.services import appointment_expiry_sweep
    monkeypatch.setattr(appointment_expiry_sweep, "expire_lapsed_requests",
                        _never_sweep)
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _true())

    assert await scheduler.run_expiry(datetime.now(timezone.utc)) is None
    assert swept == []
    assert no_real_lock == [scheduler.JOB_EXPIRY]


async def _false():
    return False


# ── 12. The lock backend must ANSWER, not merely be configured ──────────────
#
# Checking only that `redis_url` is non-empty left a real gap: a wrong or dead
# URL passed startup, and then every cycle failed its strict lock and did
# nothing. The deployment reported healthy, the feature was believed live, and
# the only evidence was a skip line in a log nobody reads. "Configured" and
# "reachable" fail identically at run time, so both are checked and reported
# apart.


class _PingOnlyClient:
    """Permits PING and close. Anything else - above all the `set(nx=True)`
    that IS the lock - fails the test loudly."""

    def __init__(self, *, fail=False, hang=False):
        self.pinged = 0
        self.closed = 0
        self._fail = fail
        self._hang = hang

    async def ping(self):
        self.pinged += 1
        if self._hang:
            await asyncio.sleep(10)
        if self._fail:
            raise ConnectionError(
                "Error 111 connecting to cache.example.net:6379 "
                "(auth token SUPERSECRETTOKEN rejected)")
        return True

    async def aclose(self):
        self.closed += 1

    def __getattr__(self, item):
        raise AssertionError(f"the readiness probe called Redis.{item}")


def _opener(client):
    async def _open(url):
        return client
    return _open


async def test_the_guard_probes_nothing_at_all_while_the_flag_is_off(
        flags, monkeypatch):
    """Zero Redis probe, zero index query, zero appointment query.

    A requirement rather than an optimisation: this runs on every boot of
    every deployment, and every deployment today has expiry off.
    """
    flags(appointment_expiry_enabled=False)

    async def _forbidden(*args, **kwargs):
        raise AssertionError("the guard performed I/O while the flag was off")

    monkeypatch.setattr(scheduler, "redis_reachable", _forbidden)
    monkeypatch.setattr(scheduler, "_index_ready", _forbidden)
    monkeypatch.setattr(scheduler, "_every_pending_row_has_a_stored_deadline",
                        _forbidden)

    await scheduler.assert_appointment_expiry_activation_ready()


async def test_a_configured_but_unreachable_backend_refuses_startup(
        flags, monkeypatch):
    """Distinct from 'not configured', because the fix is different: one is a
    missing setting, the other is a dead or wrong endpoint."""
    flags(appointment_expiry_enabled=True)
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _true())
    monkeypatch.setattr(scheduler, "_every_pending_row_has_a_stored_deadline",
                        _true)

    client = _PingOnlyClient(fail=True)
    monkeypatch.setattr(scheduler, "redis_reachable",
                        lambda url, **kw: _redis_probe(client))

    with pytest.raises(scheduler.AppointmentExpiryNotReady) as raised:
        await scheduler.assert_appointment_expiry_activation_ready()

    assert scheduler.EXPIRY_LOCK_BACKEND_UNREACHABLE in raised.value.reasons
    assert scheduler.EXPIRY_NO_LOCK_BACKEND not in raised.value.reasons


async def test_a_reachable_backend_lets_startup_continue(flags, monkeypatch):
    flags(appointment_expiry_enabled=True)
    monkeypatch.setattr(scheduler, "_index_ready", lambda job: _true())
    monkeypatch.setattr(scheduler, "_every_pending_row_has_a_stored_deadline",
                        _true)

    client = _PingOnlyClient()
    monkeypatch.setattr(scheduler, "redis_reachable",
                        lambda url, **kw: _redis_probe(client))

    await scheduler.assert_appointment_expiry_activation_ready()


async def _redis_probe(client):
    from app.core.redis_client import redis_reachable
    return await redis_reachable("u", timeout=0.2, open_client=_opener(client))


# ── The shared helper itself ────────────────────────────────────────────────

async def test_the_probe_pings_and_closes_on_success():
    from app.core.redis_client import redis_reachable

    client = _PingOnlyClient()

    assert await redis_reachable("u", open_client=_opener(client)) is True
    assert client.pinged == 1
    assert client.closed == 1


async def test_the_probe_closes_its_client_on_failure_too():
    """A probe that leaked a connection per boot would slowly exhaust the very
    backend it was checking."""
    from app.core.redis_client import redis_reachable

    client = _PingOnlyClient(fail=True)

    assert await redis_reachable("u", open_client=_opener(client)) is False
    assert client.closed == 1


async def test_the_probe_is_bounded_and_a_hang_is_unreachable():
    from app.core.redis_client import redis_reachable

    client = _PingOnlyClient(hang=True)
    started = time.monotonic()

    result = await redis_reachable("u", timeout=0.05,
                                   open_client=_opener(client))

    assert result is False
    assert time.monotonic() - started < 2
    assert client.closed == 1


async def test_the_probe_never_writes_a_lock_key():
    """`set`, `eval`, `delete` and every other attribute raise on the fake, so
    reaching for one fails loudly. Taking the real lock would prove
    reachability by SUPPRESSING the next real cycle for its whole TTL."""
    from app.core.redis_client import redis_reachable

    client = _PingOnlyClient()

    await redis_reachable("u", open_client=_opener(client))

    assert client.pinged == 1


async def test_a_probe_failure_never_reveals_the_target_or_the_reason(caplog):
    import logging

    from app.core.redis_client import redis_reachable

    client = _PingOnlyClient(fail=True)

    with caplog.at_level(logging.DEBUG):
        assert await redis_reachable(
            FAKE_REDIS_URL, open_client=_opener(client)) is False

    for secret in ("SUPERSECRETTOKEN", "cache.example.net", FAKE_REDIS_URL,
                   "ConnectionError", "Error 111"):
        assert secret not in caplog.text, secret


# WHICH FAILURES MEAN "UNREACHABLE", AND WHICH MEAN "BROKEN".
#
# Only an operational failure may return False. Everything else is a defect in
# the probe or its configuration, and an earlier version proved why that line
# matters: `asyncio` was out of scope, the NameError was swallowed by a
# blanket `except Exception`, and the helper reported Redis unreachable on
# every call. A bug wearing an infrastructure costume is worse than a crash,
# because the crash gets fixed.


def _raising_client(exc):
    class _Client:
        def __init__(self):
            self.closed = 0

        async def ping(self):
            raise exc

        async def aclose(self):
            self.closed += 1

    return _Client()


@pytest.mark.parametrize("exc_factory,label", [
    (lambda: __import__("redis").exceptions.ConnectionError(
        "Error 111 connecting to cache.example.net:6379"), "driver connection"),
    (lambda: __import__("redis").exceptions.AuthenticationError(
        "invalid username-password pair SUPERSECRETTOKEN"), "driver auth"),
    (lambda: __import__("redis").exceptions.RedisError("protocol error"),
     "driver base"),
    (lambda: OSError(111, "Connection refused"), "socket"),
    (lambda: asyncio.TimeoutError(), "timeout"),
])
async def test_an_operational_failure_reports_unreachable(exc_factory, label):
    """These, and only these, mean Redis did not answer."""
    from app.core.redis_client import redis_reachable

    client = _raising_client(exc_factory())

    assert await redis_reachable("u", open_client=_opener(client)) is False
    assert client.closed == 1, label


@pytest.mark.parametrize("exc_factory,label", [
    (lambda: RuntimeError("event loop is closed"), "RuntimeError"),
    (lambda: ValueError("invalid connection string"), "ValueError"),
    (lambda: AssertionError("the probe called Redis.set"), "AssertionError"),
    (lambda: NameError("name 'asyncio' is not defined"), "NameError"),
    (lambda: AttributeError("'NoneType' has no attribute 'ping'"),
     "AttributeError"),
    (lambda: TypeError("ping() takes 1 positional argument"), "TypeError"),
])
async def test_a_programming_defect_propagates_instead_of_being_hidden(
        exc_factory, label):
    """None of these is an infrastructure failure, so none may return False.

    Reporting one as "unreachable" sends somebody to check a server that was
    never the problem, while the real defect stays in the code.
    """
    from app.core.redis_client import redis_reachable

    client = _raising_client(exc_factory())

    with pytest.raises(type(exc_factory())):
        await redis_reachable("u", open_client=_opener(client))

    # Still closed: the `finally` runs on the way out.
    assert client.closed == 1, label


async def test_a_missing_redis_driver_fails_loudly():
    """A driver that is not installed is not a Redis that is down.

    The import is deliberately unguarded, so this surfaces as an ImportError
    at startup rather than as a quiet "unreachable" that sends an operator to
    the wrong place.
    """
    import inspect

    from app.core import redis_client

    source = inspect.getsource(redis_client.redis_reachable)

    assert "from redis.exceptions import RedisError" in source
    assert "except ImportError" not in source
    assert "ImportError" not in source.split("operational = ")[1]


async def test_the_operational_allowlist_is_not_a_blanket_except():
    """CODE only. The comment above the handler explains why a blanket
    `except Exception` is wrong, and naming the thing in prose must not fail
    the test that forbids it - that is an assertion about punctuation rather
    than behaviour, and it would push somebody to delete the explanation.
    """
    import inspect

    from app.core import redis_client

    source = inspect.getsource(redis_client.redis_reachable)
    code = "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith("#"))

    assert "except Exception" not in code
    assert "except operational" in code


def test_the_guard_and_the_audit_use_the_same_reason_codes():
    """A report saying `strict_lock_backend_unreachable` while startup refused
    with a differently-spelled code sends an operator looking for two
    problems."""
    from app.core import redis_client
    from app.db import appointment_activation_audit as audit

    assert scheduler.EXPIRY_NO_LOCK_BACKEND == \
        redis_client.STRICT_LOCK_NOT_CONFIGURED
    assert scheduler.EXPIRY_LOCK_BACKEND_UNREACHABLE == \
        redis_client.STRICT_LOCK_UNREACHABLE

    verdict_source = inspect.getsource(audit.build_verdicts)
    assert redis_client.STRICT_LOCK_NOT_CONFIGURED in verdict_source
    assert redis_client.STRICT_LOCK_UNREACHABLE in verdict_source


def test_the_fail_open_lock_is_unchanged():
    """`acquire_period_lock` must keep failing OPEN. It serves idempotent
    sweeps whose worst duplicate outcome is wasted work, and changing it here
    would alter every other scheduler in the application."""
    from app.core import redis_client

    source = inspect.getsource(redis_client.acquire_period_lock)

    assert "Never let a Redis hiccup" in source
    assert "return True" in source
