"""The read-only appointment activation audit.

WHAT IS WORTH TESTING HERE

Not the counts. The surveys that produce them are tested where they live, and
re-asserting their arithmetic here would only prove that this module calls
them. What this module adds is JUDGEMENT and RESTRAINT, and both fail quietly:

  * A verdict that says READY when something is missing. The dangerous shape is
    not a wrong number, it is a right number attached to the wrong conclusion -
    so every feature is tested by breaking exactly one thing and checking that
    ONE verdict moves and the others do not.

  * A tool that writes. It reuses production services whose repositories can
    write, so "it does not write" has to be enforced rather than intended, and
    the enforcement has to be tested against the write it would otherwise make.

  * A report that leaks. It reads collections holding consultation notes,
    client statements and support's private reasoning, and its output is
    pasted into tickets.

  * A manual gate that drifts into looking satisfied. The freeze and the
    restore cannot be checked by any query, and the failure mode is a report
    that stops saying so.

THE DATASET IS CLEARED, NOT TAGGED

Every other appointment test namespaces its rows and cleans up after itself.
This one cannot: the audit asks global questions - how many lawyers have no
schedule, how many requests are pending - and a stray row from another test
would change the answer. So the collections it reads are emptied first, and
the tests own the whole population while they run.
"""
import contextlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.core.constants import AppointmentStatus
from app.db import appointment_activation_audit as audit
from app.db.appointment_index_spec import (
    ALL_INDEX_REQUIREMENTS,
    APPOINTMENT_DISPUTES,
    APPOINTMENTS,
)
from app.db.v2_index_spec import CORRECTNESS
from app.services.appointment_slots import occupied_slots

pytestmark = pytest.mark.integration

ENDPOINT = "mongodb://127.0.0.1:27017"
URI = "mongodb://auditor:hunter2@127.0.0.1:27017/?retryWrites=true"
ENV = {audit.URI_ENV_VAR: URI}

READ_COLLECTIONS = ("appointments", "users", "appointment_disputes",
                    "lawyer_availability")


class Recorder:
    """Captures the lines an operator would see."""

    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, line=""):
        self.lines.append(str(line))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


async def _never_connect(uri, database):
    raise AssertionError(
        f"the audit connected to {database!r} when it should have refused "
        "before constructing a driver")


class _Borrowed:
    """The session's client, lent to the command without its lifetime.

    `run()` closes the client it was handed, which is right - it opened it. The
    tests hand it the session fixture's client instead, which they do not own,
    so the close is absorbed here rather than weakened in the command.
    """

    def __init__(self, inner):
        self._inner = inner

    def __getitem__(self, name):
        return self._inner[name]

    def close(self):
        pass


def _lend(db):
    """A `connect` callable that lends the already-open test client."""
    async def _connect(uri, database):
        from app.db.mongodb import get_client
        return _Borrowed(get_client()), db.name
    return _connect


# ── Helpers ──────────────────────────────────────────────────────────────────

def _aligned(moment: datetime) -> datetime:
    """The half-hour grid the slot contract requires of every booking."""
    return moment.replace(minute=0 if moment.minute < 30 else 30,
                          second=0, microsecond=0)


def _lawyer(_id: str, *, verified: bool = True, active: bool = True) -> dict:
    return {"_id": _id, "role": "lawyer", "is_active": active,
            "email": f"{_id}@test.invalid", "full_name": "Adv Test",
            "province": "punjab", "created_at": datetime.now(timezone.utc),
            "lawyer_profile": {"specializations": ["criminal"],
                               "kyc_verified": verified, "rating": 4.0,
                               "total_reviews": 0, "availability": True,
                               "experience_years": 5}}


def _client(_id: str) -> dict:
    return {"_id": _id, "role": "client", "is_active": True,
            "email": f"{_id}@test.invalid", "full_name": "Client Test",
            "created_at": datetime.now(timezone.utc)}


def _appt(_id: str, *, lawyer_id: str, client_id: str, start: datetime,
          status: str, duration: int = 60, **extra) -> dict:
    """One appointment that satisfies the slot contract.

    `occupied_slots` is computed by the production function rather than written
    out, so a fixture row is exactly what the booking path would have stored -
    and a test about missing slots has to remove them deliberately.
    """
    row = {
        "_id": _id, "lawyer_id": lawyer_id, "client_id": client_id,
        "scheduled_at": start, "end_at": start + timedelta(minutes=duration),
        "duration_minutes": duration, "status": status,
        "occupied_slots": occupied_slots(start, duration),
        "created_at": start - timedelta(days=1), "schedule_version": 1,
        "mode": "online", "timezone": "Asia/Karachi",
    }
    row.update(extra)
    return row


def _schedule_covering(lawyer_id: str, start: datetime, duration: int) -> dict:
    """A stored schedule whose interval contains exactly this appointment.

    Built from the appointment rather than from office hours somebody made up:
    the point of the working-hours section is that this system does not know
    when anybody works, and a fixture that invented a default would be testing
    the assumption the feature exists to avoid.
    """
    from app.services import lawyer_availability as policy

    local = start.astimezone(policy.SCHEDULE_TZ)
    finish = (start + timedelta(minutes=duration)).astimezone(policy.SCHEDULE_TZ)
    return {"_id": lawyer_id,
            "working_hours": [{"weekday": local.weekday(),
                               "start": f"{local.hour:02d}:{local.minute:02d}",
                               "end": f"{finish.hour:02d}:{finish.minute:02d}"}],
            "exceptions": []}


async def _clear(db) -> None:
    for name in READ_COLLECTIONS:
        await db[name].delete_many({})


async def _run(db, now=None) -> dict:
    """The audit, against the bound test database."""
    from app.db.mongodb import get_client

    with audit._Bound(get_client(), db.name) as bound:
        return await audit.audit(bound, [ENDPOINT], db.name, now=now)


def _verdict(report: dict, name: str) -> str:
    return report["verdicts"][name]["verdict"]


@contextlib.asynccontextmanager
async def _without_index(db, spec):
    """Drop one declared index for the duration, then rebuild it exactly.

    Rebuilt FROM THE SPECIFICATION, so the database the next test sees is the
    one `ensure_app_indexes` guaranteed. A test that left an index missing
    would silently disarm every later test that depends on it.
    """
    await db[spec.collection].drop_index(spec.name)
    try:
        yield
    finally:
        options: dict = {"name": spec.name}
        if spec.unique:
            options["unique"] = True
        if spec.sparse:
            options["sparse"] = True
        if spec.partial_filter:
            options["partialFilterExpression"] = dict(spec.partial_filter)
        await db[spec.collection].create_index(list(spec.keys), **options)


def _spec(name: str):
    return next(s for s in ALL_INDEX_REQUIREMENTS if s.name == name)


# ── Fixtures ─────────────────────────────────────────────────────────────────

FAKE_REDIS_URL = "rediss://default:SUPERSECRETTOKEN@cache.example.net:6379"


class _PingOnlyRedis:
    """A Redis client that permits a PING and a close, and nothing else.

    The audit's whole claim about this backend is that it probes without
    touching it. `set`, `get`, `eval`, `delete` - and above all the `set(...,
    nx=True)` that IS the lock - reach `__getattr__` and fail the test loudly,
    so "it only pings" is enforced rather than reviewed.
    """

    def __init__(self, *, fail: bool = False):
        self.pinged = 0
        self.closed = 0
        self._fail = fail

    async def ping(self):
        self.pinged += 1
        if self._fail:
            raise ConnectionError(
                f"Error connecting to {FAKE_REDIS_URL}: auth token rejected")
        return True

    async def aclose(self):
        self.closed += 1

    def __getattr__(self, item):
        raise AssertionError(
            f"the audit called Redis.{item} - it may only PING and close")


@pytest.fixture(autouse=True)
def no_real_redis(monkeypatch):
    """No test in this file may open a socket to a real Redis.

    Autouse and unconditional. `audit()` probes the strict-lock backend on
    every run, and this repository's configured `redis_url` points at a hosted
    production instance - so without this the suite would ping it once per
    test. The probe is read-only, which is not the point: a test suite does not
    get to decide it may talk to production because the call is harmless.
    """
    clients: list[_PingOnlyRedis] = []

    async def _open(url):
        client = _PingOnlyRedis()
        clients.append(client)
        return client

    monkeypatch.setattr(audit, "_open_redis", _open)
    monkeypatch.setattr(settings, "redis_url", FAKE_REDIS_URL)
    return clients


@pytest.fixture
async def healthy(app_indexes):
    """A dataset with nothing wrong with it.

    One verified lawyer who has said when they work, one client, one confirmed
    consultation inside those hours, and one pending request that carries the
    `expires_at` the current booking path writes. Every machine-verifiable
    check should pass against this, and each later test breaks exactly one
    thing about it.
    """
    db = app_indexes
    await _clear(db)

    tag = secrets.token_hex(4)
    lawyer_id, client_id = f"AU-L-{tag}", f"AU-C-{tag}"
    now = datetime.now(timezone.utc)
    start = _aligned(now) + timedelta(days=2)
    pending_start = start + timedelta(days=1)

    await db["users"].insert_many([_lawyer(lawyer_id), _client(client_id)])

    schedule = _schedule_covering(lawyer_id, start, 60)
    # One interval per weekday touched, so the pending request is inside the
    # schedule too - otherwise the dataset would fail the section it is meant
    # to be the clean baseline for.
    schedule["working_hours"] += _schedule_covering(
        lawyer_id, pending_start, 60)["working_hours"]
    schedule["working_hours"].sort(key=lambda i: (i["weekday"], i["start"]))
    await db["lawyer_availability"].insert_one(schedule)

    await db[APPOINTMENTS].insert_many([
        _appt(f"AU-A1-{tag}", lawyer_id=lawyer_id, client_id=client_id,
              start=start, status=AppointmentStatus.CONFIRMED.value),
        _appt(f"AU-A2-{tag}", lawyer_id=lawyer_id, client_id=client_id,
              start=pending_start, status=AppointmentStatus.PENDING.value,
              expires_at=now + timedelta(hours=6)),
    ])

    yield {"db": db, "lawyer_id": lawyer_id, "client_id": client_id,
           "tag": tag, "now": now, "start": start,
           "pending_start": pending_start}

    await _clear(db)


# ── 1. The clean baseline ────────────────────────────────────────────────────

async def test_a_healthy_dataset_passes_every_machine_check(healthy):
    report = await _run(healthy["db"], now=healthy["now"])

    assert _verdict(report, "booking_rollout") == audit.READY
    assert _verdict(report, "expiry_activation") == audit.READY
    assert _verdict(report, "reminders_activation") == audit.READY
    assert _verdict(report, "working_hours_enforcement") == audit.READY
    assert _verdict(report, "dispute_workflow") == audit.READY
    assert audit.exit_code_for(report) == audit.EXIT_OK


async def test_a_healthy_dataset_is_still_not_a_production_go(healthy):
    """Requirement 15, which is the whole point of the tool.

    Every database check passing is not permission. The freeze and the restore
    are invisible to every query this could run - an idle database and a frozen
    one are indistinguishable - so the best available answer is that nothing
    checkable says no.
    """
    report = await _run(healthy["db"], now=healthy["now"])

    assert _verdict(report, "overall_production_go") == audit.UNVERIFIED_EXTERNAL
    assert _verdict(report, "overall_production_go") != audit.READY
    text = audit.render(report)
    assert "THIS IS NOT A GO." in text


async def test_exit_zero_never_means_go(healthy):
    """Requirement 16's last line, as an assertion rather than a convention."""
    report = await _run(healthy["db"], now=healthy["now"])

    assert audit.exit_code_for(report) == audit.EXIT_OK
    assert _verdict(report, "overall_production_go") != audit.READY
    assert "NOT A GO" in audit.render(report)


# ── 2. Correctness indexes ───────────────────────────────────────────────────

@pytest.mark.parametrize("index_name", [
    "uniq_appointment_lawyer_slot",
    "uniq_appointment_client_slot",
    "uniq_appointment_idempotency",
])
async def test_each_missing_correctness_index_blocks_booking(
        healthy, index_name):
    """One at a time, so a verdict cannot pass by accident of another failing."""
    db = healthy["db"]

    async with _without_index(db, _spec(index_name)):
        report = await _run(db, now=healthy["now"])

    assert _verdict(report, "booking_rollout") == audit.NOT_READY
    assert "failed_gate:indexes_valid" in \
        report["verdicts"]["booking_rollout"]["reasons"]
    assert not report["sections"]["booking_correctness"][
        "correctness_indexes_valid"]
    assert audit.exit_code_for(report) == audit.EXIT_NO_GO


async def test_a_missing_dispute_correctness_index_also_blocks_booking(
        healthy):
    """The coupling is real, and the report has to say so rather than hide it.

    The one-live-complaint constraint lives on another collection and stops a
    different wrong thing, so the tempting verdict is "disputes only". It would
    be false. `assert_appointment_booking_ready` refuses to START THE SERVICE
    whenever any CORRECTNESS index is missing, across both collections - so
    while this index is absent the application will not boot, and booking
    cannot roll out no matter how clean the appointments collection is.

    Reporting READY here would mean telling an operator to proceed with a
    deployment that will refuse to start. So the verdict follows the gate the
    application actually uses, and names the index that tripped it.
    """
    db = healthy["db"]

    async with _without_index(db, _spec("uniq_active_appointment_dispute")):
        report = await _run(db, now=healthy["now"])

    assert _verdict(report, "dispute_workflow") == audit.NOT_READY
    assert "missing_correctness_index:uniq_active_appointment_dispute" in \
        report["verdicts"]["dispute_workflow"]["reasons"]

    assert _verdict(report, "booking_rollout") == audit.NOT_READY
    assert "missing_correctness_index:uniq_active_appointment_dispute" in \
        report["verdicts"]["booking_rollout"]["reasons"], (
            "booking went red without saying which index did it")

    # The QUERY indexes are untouched, so the features they serve are too:
    # a correctness failure elsewhere must not cascade into every verdict.
    assert _verdict(report, "reminders_activation") == audit.READY
    assert _verdict(report, "expiry_activation") == audit.READY


# ── 3. Query indexes, per feature ────────────────────────────────────────────

@pytest.mark.parametrize("index_name,feature,verdict_name", [
    ("appointment_pending_expiry", "pending_expiry", "expiry_activation"),
    ("appointment_confirmed_outcome", "outcome_queue",
     "outcome_nudges_activation"),
    ("appointment_confirmed_reminder", "reminder_scheduling",
     "reminders_activation"),
    ("appointment_dispute_queue", "disputes", "dispute_workflow"),
])
async def test_a_missing_query_index_affects_only_its_own_feature(
        healthy, index_name, feature, verdict_name):
    """Requirement 2's real content.

    A QUERY index is a performance index. Its absence must block the ONE
    feature whose read it serves and nothing else - above all not booking,
    because refusing to serve bookings over a missing performance index is an
    outage for a reason that is not the reason.
    """
    db = healthy["db"]
    others = [name for _i, _f, name in [
        ("appointment_pending_expiry", "pending_expiry", "expiry_activation"),
        ("appointment_confirmed_outcome", "outcome_queue",
         "outcome_nudges_activation"),
        ("appointment_confirmed_reminder", "reminder_scheduling",
         "reminders_activation"),
        ("appointment_dispute_queue", "disputes", "dispute_workflow"),
    ] if name != verdict_name]

    async with _without_index(db, _spec(index_name)):
        report = await _run(db, now=healthy["now"])

    by_feature = report["sections"]["query_indexes"]["by_feature"]
    assert by_feature[feature]["present"] is False
    assert _verdict(report, verdict_name) == audit.NOT_READY
    assert f"missing_query_index:{index_name}" in \
        report["verdicts"][verdict_name]["reasons"]

    # Booking is untouched, and so is every other feature.
    assert _verdict(report, "booking_rollout") == audit.READY
    assert report["sections"]["booking_correctness"][
        "correctness_indexes_valid"] is True
    assert report["sections"]["query_indexes"]["blocks_booking"] is False
    for other in others:
        assert _verdict(report, other) in (
            audit.READY, audit.UNVERIFIED_EXTERNAL), other


async def test_the_working_hours_lookup_is_not_reported_as_a_missing_index(
        healthy):
    """It is served by the primary key, and inventing a spec so this report had
    something to tick would create an index the system does not need."""
    report = await _run(healthy["db"], now=healthy["now"])

    state = report["sections"]["query_indexes"]["by_feature"][
        "working_hours_lookup"]
    assert state["present"] is True
    assert state["index"] == audit.WORKING_HOURS_LOOKUP
    assert report["sections"]["query_indexes"]["missing"] == []


# ── 4. Row-level booking problems ────────────────────────────────────────────

async def test_an_active_row_without_slots_is_reported_and_blocks_booking(
        healthy):
    db = healthy["db"]
    await db[APPOINTMENTS].update_one(
        {"_id": f"AU-A1-{healthy['tag']}"}, {"$unset": {"occupied_slots": ""}})

    report = await _run(db, now=healthy["now"])
    booking = report["sections"]["booking_correctness"]

    assert booking["active_rows_slotted"] is False
    assert booking["rows_needing_backfill"] >= 1
    assert booking["problem_counts"].get("missing_occupied_slots") == 1
    assert _verdict(report, "booking_rollout") == audit.NOT_READY


async def test_a_misaligned_start_is_reported_as_unusable(healthy):
    db = healthy["db"]
    bad = healthy["start"] + timedelta(minutes=7)
    await db[APPOINTMENTS].update_one(
        {"_id": f"AU-A1-{healthy['tag']}"},
        {"$set": {"scheduled_at": bad,
                  "end_at": bad + timedelta(minutes=60)}})

    report = await _run(db, now=healthy["now"])
    booking = report["sections"]["booking_correctness"]

    assert booking["active_rows_usable"] is False
    assert booking["problem_counts"].get("misaligned_start") == 1
    assert _verdict(report, "booking_rollout") == audit.NOT_READY


async def test_an_overlap_is_found_when_the_index_is_not_there_to_prevent_it(
        healthy):
    """The overlap the unique index exists to make impossible.

    It has to be inserted with that index dropped, which is the point: the
    audit's job is to find the rows that would stop the index being BUILT, and
    those rows can only exist where it is absent.
    """
    db = healthy["db"]
    tag = healthy["tag"]

    async with _without_index(db, _spec("uniq_appointment_lawyer_slot")):
        await db[APPOINTMENTS].insert_one(
            _appt(f"AU-DUP-{tag}", lawyer_id=healthy["lawyer_id"],
                  client_id=f"AU-OTHER-{tag}", start=healthy["start"],
                  status=AppointmentStatus.CONFIRMED.value))
        report = await _run(db, now=healthy["now"])
        await db[APPOINTMENTS].delete_one({"_id": f"AU-DUP-{tag}"})

    booking = report["sections"]["booking_correctness"]
    assert booking["no_lawyer_or_client_overlap"] is False
    assert booking["build_blocking_rows"] >= 1
    assert _verdict(report, "booking_rollout") == audit.NOT_READY


async def test_an_idempotency_collision_is_found_and_the_key_is_not_printed(
        healthy):
    """The key is client-generated and may carry anything the client put in it."""
    db = healthy["db"]
    tag = healthy["tag"]
    secret_key = f"SECRET-KEY-{tag}"

    async with _without_index(db, _spec("uniq_appointment_idempotency")):
        await db[APPOINTMENTS].insert_many([
            _appt(f"AU-K1-{tag}", lawyer_id=healthy["lawyer_id"],
                  client_id=healthy["client_id"],
                  start=healthy["start"] + timedelta(days=5),
                  status=AppointmentStatus.CANCELLED.value,
                  idempotency_key=secret_key),
            _appt(f"AU-K2-{tag}", lawyer_id=healthy["lawyer_id"],
                  client_id=healthy["client_id"],
                  start=healthy["start"] + timedelta(days=6),
                  status=AppointmentStatus.CANCELLED.value,
                  idempotency_key=secret_key),
        ])
        report = await _run(db, now=healthy["now"])
        await db[APPOINTMENTS].delete_many(
            {"_id": {"$in": [f"AU-K1-{tag}", f"AU-K2-{tag}"]}})

    booking = report["sections"]["booking_correctness"]
    assert booking["no_idempotency_collision"] is False
    assert booking["problem_counts"].get("idempotency_key_collisions") == 2
    assert _verdict(report, "booking_rollout") == audit.NOT_READY
    assert secret_key not in audit.render(report)


# ── 5. Pending expiry ────────────────────────────────────────────────────────

async def test_legacy_pending_rows_are_counted_and_left_alone(healthy):
    """Rows booked before `expires_at` existed. NOTHING is expired."""
    db = healthy["db"]
    tag = healthy["tag"]
    now = healthy["now"]
    # Created eight days ago for a start next week: past every derived deadline.
    old = _appt(f"AU-OLD-{tag}", lawyer_id=healthy["lawyer_id"],
                client_id=healthy["client_id"],
                start=_aligned(now) + timedelta(days=9),
                status=AppointmentStatus.PENDING.value)
    old["created_at"] = now - timedelta(days=8)
    await db[APPOINTMENTS].insert_one(old)

    report = await _run(db, now=now)
    expiry = report["sections"]["pending_expiry"]

    assert expiry["pending_total"] == 2          # the baseline row and this one
    assert expiry["missing_expires_at"] == 1
    assert expiry["currently_expired_legacy"] == 1
    assert expiry["legacy_treatment_undecided"] is True

    # Nothing moved. This is the assertion the section exists for.
    after = await db[APPOINTMENTS].find_one({"_id": f"AU-OLD-{tag}"})
    assert after["status"] == AppointmentStatus.PENDING.value
    assert "expires_at" not in after

    # A ROW WITH NO STORED DEADLINE IS A MACHINE NO, not a decision pending.
    #
    # The scheduler refuses to run the sweep while any exists, so calling this
    # UNVERIFIED_EXTERNAL would describe the feature as "awaiting approval"
    # when switching it on actually produces a job that declines every cycle.
    # The decision about those rows is still owed - and still reported - but
    # it is no longer the only thing standing in the way.
    assert _verdict(report, "expiry_activation") == audit.NOT_READY
    reasons = report["verdicts"]["expiry_activation"]["reasons"]
    assert "pending_rows_without_a_stored_deadline" in reasons
    assert "legacy_rows_awaiting_policy" in reasons

    assert expiry["deadlines_missing"] == 1
    assert expiry["deadlines_malformed"] == 0
    # The baseline pending row still carries its own deadline.
    assert expiry["deadlines_valid"] == 1


async def test_pending_rows_past_their_start_and_deadline_are_counted(healthy):
    db = healthy["db"]
    tag = healthy["tag"]
    now = healthy["now"]
    lapsed = _appt(f"AU-LAPSED-{tag}", lawyer_id=healthy["lawyer_id"],
                   client_id=healthy["client_id"],
                   start=_aligned(now) - timedelta(days=1),
                   status=AppointmentStatus.PENDING.value,
                   expires_at=now - timedelta(days=2))
    await db[APPOINTMENTS].insert_one(lapsed)

    report = await _run(db, now=now)
    expiry = report["sections"]["pending_expiry"]

    assert expiry["currently_expired_dated"] == 1
    assert expiry["already_past_scheduled_start"] == 1
    # The two populations are reported apart, never summed.
    assert expiry["currently_expired_legacy"] == 0


async def test_expiry_age_buckets_are_disjoint_and_say_so(healthy):
    db = healthy["db"]
    now = healthy["now"]
    buckets = (await _run(db, now=now))["sections"]["pending_expiry"]

    assert buckets["age_buckets_cumulative"] is False
    assert sum(buckets["age_buckets"].values()) == buckets["age_scanned"]


# ── 6. Outcome nudges ────────────────────────────────────────────────────────

async def test_the_outcome_backlog_is_counted_without_notifying_anybody(
        healthy):
    db = healthy["db"]
    tag = healthy["tag"]
    now = healthy["now"]
    await db[APPOINTMENTS].insert_one(
        _appt(f"AU-OUT-{tag}", lawyer_id=healthy["lawyer_id"],
              client_id=healthy["client_id"],
              start=_aligned(now) - timedelta(days=3),
              status=AppointmentStatus.CONFIRMED.value))

    before = await db["notifications"].count_documents({})
    report = await _run(db, now=now)
    nudges = report["sections"]["outcome_nudges"]

    assert nudges["outstanding"]["over_2h"] == 1
    assert nudges["outstanding"]["over_24h"] == 1
    assert nudges["cumulative"] is True
    assert nudges["enabled"] is False
    assert await db["notifications"].count_documents({}) == before


async def test_a_missing_activation_instant_needs_a_person_not_a_default(
        healthy):
    """Requirement 4's honest answer.

    The instant decides how much history gets notified. Absent, the correct
    report is that a decision is outstanding - never a value this tool picked.
    """
    report = await _run(healthy["db"], now=healthy["now"])
    nudges = report["sections"]["outcome_nudges"]

    assert nudges["activation_instant_configured"] is False
    assert _verdict(report, "outcome_nudges_activation") == \
        audit.UNVERIFIED_EXTERNAL
    assert "activation_instant_not_configured" in \
        report["verdicts"]["outcome_nudges_activation"]["reasons"]


async def test_a_configured_activation_instant_is_reported_without_its_value(
        healthy, monkeypatch):
    """WHETHER, not what. The instant is a decision about real consultations."""
    from app.core.config import settings

    instant = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        settings, "appointment_outcome_nudges_activated_at", instant)

    report = await _run(healthy["db"], now=healthy["now"])

    assert report["sections"]["outcome_nudges"][
        "activation_instant_configured"] is True
    assert _verdict(report, "outcome_nudges_activation") == audit.READY
    assert instant.isoformat() not in audit.render(report)
    assert "2026-03-01" not in audit.render(report)


# ── 7. Reminders ─────────────────────────────────────────────────────────────

async def test_appointments_in_each_reminder_window_are_counted_not_sent(
        healthy):
    db = healthy["db"]
    tag = healthy["tag"]
    now = healthy["now"]
    base = _aligned(now)
    await db[APPOINTMENTS].insert_many([
        _appt(f"AU-R24-{tag}", lawyer_id=healthy["lawyer_id"],
              client_id=healthy["client_id"],
              start=base + timedelta(hours=23, minutes=30),
              status=AppointmentStatus.CONFIRMED.value),
        _appt(f"AU-R1-{tag}", lawyer_id=healthy["lawyer_id"],
              client_id=healthy["client_id"],
              start=base + timedelta(minutes=30),
              status=AppointmentStatus.CONFIRMED.value),
    ])

    before = await db["notifications"].count_documents({})
    report = await _run(db, now=now)
    reminders = report["sections"]["reminders"]

    assert reminders["due"]["24h"] == 1
    assert reminders["due"]["1h"] == 1
    assert reminders["due_total"] == 2
    assert reminders["enabled"] is False
    assert await db["notifications"].count_documents({}) == before


async def test_the_report_names_the_fail_closed_lock(healthy):
    """A fail-open lock means every worker dispatches the same batch at once."""
    report = await _run(healthy["db"], now=healthy["now"])
    locking = report["sections"]["strict_lock"]

    assert locking["strict_lock_available"] is True
    assert locking["strict_lock_wired"] is True


async def test_a_scheduler_on_the_fail_open_lock_is_a_machine_no(
        healthy, monkeypatch):
    from app.core import redis_client
    from app.services import appointment_scheduler

    monkeypatch.setattr(appointment_scheduler, "acquire_period_lock_strict",
                        redis_client.acquire_period_lock)

    report = await _run(healthy["db"], now=healthy["now"])

    assert report["sections"]["strict_lock"]["strict_lock_wired"] is False
    assert _verdict(report, "reminders_activation") == audit.NOT_READY
    assert "scheduler_not_using_fail_closed_lock" in \
        report["verdicts"]["reminders_activation"]["reasons"]
    # The same lock, so the same block.
    assert _verdict(report, "outcome_nudges_activation") == audit.NOT_READY


# ── 7b. The strict-lock backend ──────────────────────────────────────────────

async def test_an_absent_redis_blocks_both_dispatching_features(
        healthy, monkeypatch):
    """No backend means the fail-closed lock returns False for ever.

    The scheduler would wake on its interval, decline every job, and report
    nothing wrong - a notification system that is silent and looks healthy.
    Reporting the features as READY because the code is present would be
    describing a deployment that cannot send anything.
    """
    monkeypatch.setattr(settings, "redis_url", "")

    report = await _run(healthy["db"], now=healthy["now"])
    locking = report["sections"]["strict_lock"]

    assert locking["backend_configured"] is False
    # None, not False: "we did not ask" is not "it did not answer".
    assert locking["backend_reachable"] is None

    for feature in ("reminders_activation", "outcome_nudges_activation"):
        assert _verdict(report, feature) == audit.NOT_READY, feature
        assert "strict_lock_backend_not_configured" in \
            report["verdicts"][feature]["reasons"], feature


async def test_an_unreachable_redis_blocks_both_dispatching_features(
        healthy, monkeypatch):
    """Configured-but-down produces exactly the outcome of not configured.

    An audit that checked only configuration would call this ready, which is
    the whole reason the two are separate questions.
    """
    async def _open(url):
        return _PingOnlyRedis(fail=True)

    monkeypatch.setattr(audit, "_open_redis", _open)

    report = await _run(healthy["db"], now=healthy["now"])
    locking = report["sections"]["strict_lock"]

    assert locking["backend_configured"] is True
    assert locking["backend_reachable"] is False

    for feature in ("reminders_activation", "outcome_nudges_activation"):
        assert _verdict(report, feature) == audit.NOT_READY, feature
        assert "strict_lock_backend_unreachable" in \
            report["verdicts"][feature]["reasons"], feature
        assert "strict_lock_backend_not_configured" not in \
            report["verdicts"][feature]["reasons"], feature


async def test_a_reachable_redis_lets_both_features_through(healthy):
    report = await _run(healthy["db"], now=healthy["now"])
    locking = report["sections"]["strict_lock"]

    assert locking["backend_configured"] is True
    assert locking["backend_reachable"] is True
    assert _verdict(report, "reminders_activation") == audit.READY


async def test_the_probe_is_a_ping_and_nothing_else(healthy, no_real_redis):
    """Never a lock, never a write.

    Taking the real lock would prove reachability and SUPPRESS A REAL CYCLE for
    its whole TTL - an audit that silences the next batch of reminders in order
    to report that reminders could be sent. The fake raises on every other
    attribute, so `set`, `eval` or `delete` fail this loudly.
    """
    await _run(healthy["db"], now=healthy["now"])

    assert len(no_real_redis) == 1
    assert no_real_redis[0].pinged == 1


async def test_the_audits_redis_client_is_closed(healthy, no_real_redis):
    """It opens its own client rather than the application's shared one, so it
    is the only thing that may close it - and it must."""
    await _run(healthy["db"], now=healthy["now"])

    assert no_real_redis[0].closed == 1


async def test_a_redis_client_that_fails_is_still_closed(healthy, monkeypatch):
    opened: list[_PingOnlyRedis] = []

    async def _open(url):
        client = _PingOnlyRedis(fail=True)
        opened.append(client)
        return client

    monkeypatch.setattr(audit, "_open_redis", _open)

    await _run(healthy["db"], now=healthy["now"])

    assert opened[0].closed == 1


async def test_the_redis_token_never_reaches_the_output(healthy, monkeypatch):
    """The driver's error carries the URL, and for `rediss://` that URL carries
    the token. The report says unreachable; it never says why."""
    async def _open(url):
        return _PingOnlyRedis(fail=True)

    monkeypatch.setattr(audit, "_open_redis", _open)

    report = await _run(healthy["db"], now=healthy["now"])
    rendered = audit.render(report)

    for secret in ("SUPERSECRETTOKEN", "cache.example.net", FAKE_REDIS_URL,
                   "auth token rejected", "ConnectionError"):
        assert secret not in rendered, secret
        assert secret not in str(report), secret


async def test_a_redis_failure_is_not_logged_with_its_message(
        healthy, monkeypatch, caplog):
    async def _open(url):
        return _PingOnlyRedis(fail=True)

    monkeypatch.setattr(audit, "_open_redis", _open)

    with caplog.at_level("DEBUG"):
        await _run(healthy["db"], now=healthy["now"])

    text = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("SUPERSECRETTOKEN", "cache.example.net",
                   "auth token rejected"):
        assert secret not in text, secret


# ── 8. Working hours ─────────────────────────────────────────────────────────

async def test_configured_and_unconfigured_lawyers_are_counted_separately(
        healthy):
    db = healthy["db"]
    await db["users"].insert_one(_lawyer(f"AU-L2-{healthy['tag']}"))

    report = await _run(db, now=healthy["now"])
    hours = report["sections"]["working_hours"]

    assert hours["eligible_lawyers"] == 2
    assert hours["configured"] == 1
    assert hours["unconfigured"] == 1
    assert hours["enforced"] is False
    # Enforcement would make the second lawyer unbookable, so it is a NO.
    assert _verdict(report, "working_hours_enforcement") == audit.NOT_READY
    assert "lawyers_without_a_schedule" in \
        report["verdicts"]["working_hours_enforcement"]["reasons"]


async def test_a_saved_but_empty_schedule_is_not_a_configuration(healthy):
    """`is_configured` treats it as unanswered, and so must this.

    A document with no intervals says the lawyer works no hours, which is
    indistinguishable in effect from never having answered.
    """
    db = healthy["db"]
    tag = healthy["tag"]
    await db["users"].insert_one(_lawyer(f"AU-L3-{tag}"))
    await db["lawyer_availability"].insert_one(
        {"_id": f"AU-L3-{tag}", "working_hours": [], "exceptions": []})

    hours = (await _run(db, now=healthy["now"]))["sections"]["working_hours"]

    assert hours["configured"] == 1
    assert hours["unconfigured"] == 1


async def test_an_unverified_lawyer_is_not_counted_as_eligible(healthy):
    """The predicate is the directory's own, so it cannot drift from it."""
    db = healthy["db"]
    tag = healthy["tag"]
    await db["users"].insert_many([
        _lawyer(f"AU-L4-{tag}", verified=False),
        _lawyer(f"AU-L5-{tag}", active=False),
    ])

    hours = (await _run(db, now=healthy["now"]))["sections"]["working_hours"]

    assert hours["eligible_lawyers"] == 1
    assert hours["unconfigured"] == 0


async def test_an_upcoming_booking_outside_the_stored_schedule_is_reported(
        healthy):
    """Measured with `covers`, the same question booking enforcement asks."""
    db = healthy["db"]
    tag = healthy["tag"]
    # Inside the lawyer's working day by the clock, but on a weekday they have
    # not listed - so enforcement would refuse it.
    outside = healthy["start"] + timedelta(days=3)
    await db[APPOINTMENTS].insert_one(
        _appt(f"AU-OUTSIDE-{tag}", lawyer_id=healthy["lawyer_id"],
              client_id=healthy["client_id"], start=outside,
              status=AppointmentStatus.CONFIRMED.value))

    report = await _run(db, now=healthy["now"])
    hours = report["sections"]["working_hours"]

    assert hours["upcoming_outside_schedule"] == 1
    assert hours["upcoming_for_unconfigured_lawyer"] == 0
    assert _verdict(report, "working_hours_enforcement") == audit.NOT_READY
    assert "upcoming_bookings_outside_stored_schedule" in \
        report["verdicts"]["working_hours_enforcement"]["reasons"]


async def test_a_booking_for_an_unconfigured_lawyer_is_its_own_count(healthy):
    """Not folded into "outside a schedule": there is no schedule to be outside
    of, and merging them would report a lawyer who never answered as one being
    booked against their own stated hours."""
    db = healthy["db"]
    tag = healthy["tag"]
    other = f"AU-L6-{tag}"
    await db["users"].insert_one(_lawyer(other))
    await db[APPOINTMENTS].insert_one(
        _appt(f"AU-UNC-{tag}", lawyer_id=other, client_id=f"AU-C2-{tag}",
              start=healthy["start"] + timedelta(days=4),
              status=AppointmentStatus.PENDING.value,
              expires_at=healthy["now"] + timedelta(hours=3)))

    hours = (await _run(db, now=healthy["now"]))["sections"]["working_hours"]

    assert hours["upcoming_for_unconfigured_lawyer"] == 1
    assert hours["upcoming_outside_schedule"] == 0


async def test_no_default_working_hours_are_ever_assumed(healthy):
    """The audit must not fill the gap it exists to measure.

    A lawyer with no schedule has none. If this module ever grew a fallback,
    `unconfigured` would drop to zero and the enforcement verdict would turn
    green while nothing about the lawyers had changed.
    """
    db = healthy["db"]
    await db["lawyer_availability"].delete_many({})

    report = await _run(db, now=healthy["now"])
    hours = report["sections"]["working_hours"]

    assert hours["configured"] == 0
    assert hours["unconfigured"] == 1
    assert hours["upcoming_outside_schedule"] == 0
    assert hours["upcoming_for_unconfigured_lawyer"] == 2
    assert _verdict(report, "working_hours_enforcement") == audit.NOT_READY


# ── 9. Disputes ──────────────────────────────────────────────────────────────

async def test_open_disputes_are_counted_without_reading_what_they_say(
        healthy):
    db = healthy["db"]
    tag = healthy["tag"]
    now = healthy["now"]
    statement = f"PRIVATE-CLIENT-STATEMENT-{tag}"
    note = f"PRIVATE-SUPPORT-NOTE-{tag}"
    await db[APPOINTMENT_DISPUTES].insert_many([
        {"_id": f"AU-D1-{tag}", "appointment_id": f"AU-A1-{tag}",
         "active_key": f"AU-A1-{tag}", "client_id": healthy["client_id"],
         "status": "open", "category": "incorrect_no_show",
         "client_statement": statement, "support_note": note,
         "created_at": now - timedelta(days=2), "version": 1},
        {"_id": f"AU-D2-{tag}", "appointment_id": f"AU-A2-{tag}",
         "active_key": f"AU-A2-{tag}", "client_id": healthy["client_id"],
         "status": "open", "category": "outcome_not_recorded",
         "client_statement": statement, "support_note": note,
         "created_at": now - timedelta(days=40), "version": 1},
    ])

    report = await _run(db, now=now)
    disputes = report["sections"]["disputes"]

    assert disputes["open_total"] == 2
    assert disputes["age_buckets"]["under_7d"] == 1
    assert disputes["age_buckets"]["over_30d"] == 1
    assert disputes["count_agrees_with_queue"] is True
    assert _verdict(report, "dispute_workflow") == audit.READY

    rendered = audit.render(report)
    for secret in (statement, note, f"AU-D1-{tag}", f"AU-A1-{tag}"):
        assert secret not in rendered


async def test_a_resolved_dispute_is_not_open(healthy):
    """`active_key` is what the unique index enforces, so it is what "open"
    means - a resolved row has none at all."""
    db = healthy["db"]
    tag = healthy["tag"]
    await db[APPOINTMENT_DISPUTES].insert_one(
        {"_id": f"AU-D3-{tag}", "appointment_id": f"AU-A1-{tag}",
         "client_id": healthy["client_id"], "status": "resolved",
         "created_at": healthy["now"], "version": 2})

    disputes = (await _run(db, now=healthy["now"]))["sections"]["disputes"]

    assert disputes["open_total"] == 0


# ── 10. The target ───────────────────────────────────────────────────────────

async def test_the_uri_is_never_an_argument():
    """Arguments reach shell history and process listings."""
    options = {s for action in audit._parser()._actions
               for s in action.option_strings}

    assert "--uri" not in options
    assert "--mongo-url" not in options


async def test_a_missing_uri_variable_refuses_before_connecting():
    out = Recorder()

    code = await audit.run(
        ["--database", "attorney_ai", "--confirm-database", "attorney_ai",
         "--confirm-endpoint", ENDPOINT],
        {}, connect=_never_connect, out=out)

    assert code == audit.EXIT_FAILURE
    assert audit.URI_ENV_VAR in out.text


async def test_the_database_must_be_named_and_confirmed():
    for argv in (["--confirm-database", "attorney_ai",
                  "--confirm-endpoint", ENDPOINT],
                 ["--database", "attorney_ai",
                  "--confirm-endpoint", ENDPOINT]):
        out = Recorder()
        code = await audit.run(argv, ENV, connect=_never_connect, out=out)
        assert code == audit.EXIT_FAILURE


async def test_a_mismatched_database_confirmation_refuses_before_connecting():
    out = Recorder()

    code = await audit.run(
        ["--database", "attorney_ai", "--confirm-database", "attorney_ai_test",
         "--confirm-endpoint", ENDPOINT],
        ENV, connect=_never_connect, out=out)

    assert code == audit.EXIT_FAILURE
    assert "REFUSED" in out.text


async def test_a_mismatched_endpoint_refuses_and_does_not_echo_the_real_one():
    """Naming the real endpoint in the refusal would turn a wrong guess into a
    way to read the target out of the error message."""
    out = Recorder()

    code = await audit.run(
        ["--database", "attorney_ai", "--confirm-database", "attorney_ai",
         "--confirm-endpoint", "mongodb://elsewhere.example.net:27017"],
        ENV, connect=_never_connect, out=out)

    assert code == audit.EXIT_FAILURE
    assert "127.0.0.1" not in out.text


async def test_the_port_is_part_of_the_endpoint():
    """Two instances on one host differing only by port is how staging and
    production end up side by side."""
    out = Recorder()

    code = await audit.run(
        ["--database", "attorney_ai", "--confirm-database", "attorney_ai",
         "--confirm-endpoint", "mongodb://127.0.0.1:27018"],
        ENV, connect=_never_connect, out=out)

    assert code == audit.EXIT_FAILURE


async def test_a_malformed_endpoint_confirmation_refuses_before_connecting():
    out = Recorder()

    code = await audit.run(
        ["--database", "attorney_ai", "--confirm-database", "attorney_ai",
         "--confirm-endpoint", "not-a-uri"],
        ENV, connect=_never_connect, out=out)

    assert code == audit.EXIT_FAILURE
    assert "REFUSED" in out.text


async def test_an_unparseable_connection_string_refuses_before_connecting():
    out = Recorder()

    code = await audit.run(
        ["--database", "attorney_ai", "--confirm-database", "attorney_ai",
         "--confirm-endpoint", ENDPOINT],
        {audit.URI_ENV_VAR: "this-is-not-a-uri"},
        connect=_never_connect, out=out)

    assert code == audit.EXIT_FAILURE


async def test_the_password_never_reaches_the_output(healthy):
    """The whole refusal path and the whole success path, checked for the one
    string that must never appear in a ticket."""
    db = healthy["db"]
    out = Recorder()

    code = await audit.run(
        ["--database", db.name, "--confirm-database", db.name,
         "--confirm-endpoint", ENDPOINT],
        {audit.URI_ENV_VAR: f"mongodb://auditor:hunter2@127.0.0.1:27017/{db.name}"},
        connect=_lend(db), out=out)

    assert code == audit.EXIT_OK
    assert "hunter2" not in out.text
    assert "auditor" not in out.text
    assert "127.0.0.1:27017" in out.text       # identity, without credentials


async def test_a_failed_connection_reports_a_class_not_a_message():
    """A driver error's message carries the URI and sometimes the credentials."""
    out = Recorder()

    async def _explode(uri, database):
        raise RuntimeError(f"connection refused to {uri}")

    code = await audit.run(
        ["--database", "attorney_ai", "--confirm-database", "attorney_ai",
         "--confirm-endpoint", ENDPOINT],
        ENV, connect=_explode, out=out)

    assert code == audit.EXIT_FAILURE
    assert "RuntimeError" in out.text
    assert "hunter2" not in out.text
    assert "connection refused" not in out.text


# ── 11. It cannot write ──────────────────────────────────────────────────────

class _FakeCollection:
    """Fails if anything reaches it that a read would not."""

    def __getattr__(self, item):
        raise AssertionError(f"the guard forwarded {item!r} to the driver")


class _FakeDatabase:
    name = "fake"

    def __getitem__(self, name):
        return _FakeCollection()

    def __getattr__(self, item):
        raise AssertionError(f"the guard forwarded {item!r} to the driver")


WRITE_OPERATIONS = (
    "insert_one", "insert_many", "update_one", "update_many", "replace_one",
    "delete_one", "delete_many", "find_one_and_update",
    "find_one_and_replace", "find_one_and_delete", "bulk_write", "drop",
    "rename", "create_index", "create_indexes", "drop_index", "drop_indexes",
)


@pytest.mark.parametrize("collection", READ_COLLECTIONS + ("notifications",))
@pytest.mark.parametrize("operation", WRITE_OPERATIONS)
def test_no_write_reaches_any_collection(collection, operation):
    """Interception, on every collection this tool touches and one it does not.

    Checked at the guard rather than by watching the database, because the
    guarantee has to hold for the collection nobody thought of.
    """
    guarded = audit._ReadOnlyDatabase(_FakeDatabase())[collection]

    with pytest.raises(audit.AuditWriteAttempted):
        getattr(guarded, operation)


@pytest.mark.parametrize("stage", ["$out", "$merge"])
def test_an_aggregation_cannot_write_through_a_read_api(stage):
    """`$out` and `$merge` are writes reached through `aggregate`."""
    guarded = audit._ReadOnlyDatabase(_FakeDatabase())["appointments"]

    with pytest.raises(audit.AuditWriteAttempted):
        guarded.aggregate([{"$match": {}}, {stage: "somewhere_else"}])


def test_the_database_handle_refuses_unknown_operations():
    """An unknown is a write until somebody says otherwise."""
    guarded = audit._ReadOnlyDatabase(_FakeDatabase())

    for item in ("command", "drop_collection", "create_collection"):
        with pytest.raises(audit.AuditWriteAttempted):
            getattr(guarded, item)


def test_the_reads_the_audit_actually_needs_are_forwarded():
    """The allowlist has to be complete, or the audit fails instead of writing.

    This is the other half of the trade: refusing everything unknown is only
    safe if what the reused services genuinely call is on the list.
    """
    class _Reads:
        def __getattr__(self, item):
            return f"forwarded:{item}"

    class _Db:
        def __getitem__(self, name):
            return _Reads()

    guarded = audit._ReadOnlyDatabase(_Db())["appointments"]
    for read in ("find", "find_one", "count_documents", "index_information",
                 "distinct", "list_indexes"):
        assert getattr(guarded, read) == f"forwarded:{read}"


async def test_a_full_audit_changes_nothing_in_any_collection(healthy):
    """The end-to-end version: every document, before and after."""
    db = healthy["db"]

    async def _snapshot():
        return {name: sorted(
            [str(doc) for doc in await db[name].find({}).to_list(length=1000)])
            for name in READ_COLLECTIONS}

    before = await _snapshot()
    await _run(db, now=healthy["now"])
    assert await _snapshot() == before


async def test_a_service_reaching_for_a_write_fails_the_audit_loudly(healthy):
    """The interception must not be silently swallowed into a partial report.

    A guarded handle that raised and was caught somewhere would produce a
    report with a plausible number in it and no indication that a section had
    failed - which is the one outcome worse than crashing.
    """
    db = healthy["db"]
    out = Recorder()

    def _explode(self, item):
        raise audit.AuditWriteAttempted("the audit is read-only: boom")

    original = audit._ReadOnlyCollection.__getattr__
    audit._ReadOnlyCollection.__getattr__ = _explode
    try:
        code = await audit.run(
            ["--database", db.name, "--confirm-database", db.name,
             "--confirm-endpoint", ENDPOINT],
            ENV, connect=_lend(db), out=out)
    finally:
        audit._ReadOnlyCollection.__getattr__ = original

    assert code == audit.EXIT_FAILURE
    assert "non-read operation" in out.text
    assert "VERDICTS" not in out.text


def test_the_module_contains_no_write_or_index_operation():
    """Requirement 12, read off the source.

    The allowlist design is what makes this assertion possible: a module that
    listed the banned operations in order to ban them would contain every one
    of these strings.
    """
    import inspect

    source = inspect.getsource(audit)
    for operation in WRITE_OPERATIONS:
        assert f".{operation}(" not in source, operation
    for forbidden in ("create_all_indexes", "expire_lapsed_requests",
                      "notify_outstanding_outcomes", "send_due_reminders",
                      "apply=True", "--apply"):
        assert forbidden not in source, forbidden


def test_the_module_is_not_wired_to_anything_that_runs():
    """No route, no scheduler hook, no startup call."""
    import inspect

    source = inspect.getsource(audit)
    for hook in ("APIRouter", "@router", "add_event_handler", "lifespan",
                 "create_task", "BackgroundTasks"):
        assert hook not in source, hook


def test_nothing_in_the_application_imports_the_audit():
    """It is an operator command. If startup could reach it, it would run."""
    import pathlib

    root = pathlib.Path(audit.__file__).resolve().parents[1]   # app/
    importers = [
        path for path in root.rglob("*.py")
        if path.name != "appointment_activation_audit.py"
        and "appointment_activation_audit" in path.read_text(encoding="utf-8")
    ]
    assert importers == []


# ── 12. The manual gates ─────────────────────────────────────────────────────

def test_every_manual_gate_is_unverified_and_stays_that_way():
    gates = audit.manual_gates()

    assert len(gates) == len(audit.MANUAL_GATES)
    for name, gate in gates.items():
        assert gate["verdict"] == audit.UNVERIFIED_EXTERNAL, name
        assert gate["why"]


def test_no_argument_can_mark_a_manual_gate_satisfied():
    """Requirement 8's last line.

    The backfill command takes an acknowledgement flag and is right to: it is
    attached to the operator writing, in the same command. This produces a
    REPORT that outlives its shell, so a flag would turn "I typed it" into
    "the gate passed" at exactly the moment the evidence is gone.
    """
    options = {s for action in audit._parser()._actions
               for s in action.option_strings}

    assert "--apply" not in options
    for name, _why in audit.MANUAL_GATES:
        flag = "--" + name.replace("_", "-")
        assert flag not in options, flag
        assert f"--{name}" not in options
    # Nothing that reads like an acknowledgement, under any spelling.
    for word in ("frozen", "freeze", "rehearsed", "approved", "authorised",
                 "acknowledge", "confirm-freeze"):
        assert not [o for o in options if word in o], word


async def test_a_clean_database_does_not_make_the_gates_pass(healthy):
    """The failure this is written against: a report where everything is zero
    and the gates quietly turn green because nothing contradicted them."""
    report = await _run(healthy["db"], now=healthy["now"])

    assert audit.exit_code_for(report) == audit.EXIT_OK
    for name, gate in report["manual_gates"].items():
        assert gate["verdict"] == audit.UNVERIFIED_EXTERNAL, name
    assert _verdict(report, "overall_production_go") == audit.UNVERIFIED_EXTERNAL


async def test_the_overall_verdict_is_never_ready(healthy, monkeypatch):
    """Even with every machine check passing and the nudge instant configured."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "appointment_outcome_nudges_activated_at",
                        datetime(2026, 1, 1, tzinfo=timezone.utc))

    report = await _run(healthy["db"], now=healthy["now"])

    assert all(_verdict(report, name) == audit.READY
               for name in audit._FEATURE_VERDICTS)
    assert _verdict(report, "overall_production_go") == audit.UNVERIFIED_EXTERNAL


# ── 13. The report's shape ───────────────────────────────────────────────────

async def test_the_json_report_has_a_stable_shape(healthy):
    """Something reads this. A silently renamed key is a silently broken gate."""
    report = await _run(healthy["db"], now=healthy["now"])

    assert set(report) == {"schema_version", "endpoints", "database",
                           "measured_at", "sections", "verdicts",
                           "manual_gates"}
    assert report["schema_version"] == audit.SCHEMA_VERSION
    assert set(report["sections"]) == {
        "booking_correctness", "query_indexes", "pending_expiry",
        "outcome_nudges", "reminders", "strict_lock", "working_hours",
        "disputes"}
    assert set(report["verdicts"]) == set(
        audit._FEATURE_VERDICTS) | {"overall_production_go"}
    assert set(report["manual_gates"]) == {n for n, _ in audit.MANUAL_GATES}
    for value in report["verdicts"].values():
        assert value["verdict"] in {audit.READY, audit.NOT_READY,
                                    audit.UNVERIFIED_EXTERNAL,
                                    audit.NOT_EVALUATED}


async def test_the_json_output_is_serialisable_and_carries_no_documents(
        healthy):
    import json

    db = healthy["db"]
    out = Recorder()

    code = await audit.run(
        ["--database", db.name, "--confirm-database", db.name,
         "--confirm-endpoint", ENDPOINT, "--json"],
        ENV, connect=_lend(db), out=out)

    assert code == audit.EXIT_OK
    parsed = json.loads(out.text)
    assert parsed["database"] == db.name
    assert parsed["endpoints"] == [ENDPOINT]
    # No appointment, lawyer or client id anywhere in the document.
    for identifier in (healthy["lawyer_id"], healthy["client_id"],
                       f"AU-A1-{healthy['tag']}"):
        assert identifier not in out.text


async def test_the_measured_instant_is_pinned_across_every_section(healthy):
    """One instant, so the sections describe the same system.

    A reminder window measured three seconds after the expiry deadlines were
    counted is a slightly different system, and the reader cannot see that it
    is.
    """
    now = healthy["now"]
    report = await _run(healthy["db"], now=now)

    assert report["measured_at"] == now.isoformat()


async def test_a_truncated_scan_is_never_reported_as_ready(healthy,
                                                           monkeypatch):
    """A partial count containing no problems is not evidence that there are
    none, and this is the only place that distinction can be lost."""
    db = healthy["db"]
    await db["users"].insert_many(
        [_lawyer(f"AU-T{i}-{healthy['tag']}") for i in range(3)])
    monkeypatch.setattr(audit, "PAGE_SIZE", 1)
    monkeypatch.setattr(audit, "MAX_PAGES", 1)

    report = await _run(db, now=healthy["now"])

    assert report["sections"]["working_hours"]["bookings_complete"] is False
    assert _verdict(report, "working_hours_enforcement") == audit.NOT_EVALUATED
    assert "scan_incomplete" in \
        report["verdicts"]["working_hours_enforcement"]["reasons"]
    # NOT_EVALUATED is not a pass.
    assert audit.exit_code_for(report) == audit.EXIT_NO_GO
