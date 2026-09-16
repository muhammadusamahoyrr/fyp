"""Booking integrity: overlap, idempotency and abuse protection.

Phase 3. The guarantee under test is NOT the `has_conflict` pre-check — that
reads, then the service writes, and nothing holds the range in between, so two
callers can and do pass it together. The guarantee is two unique multikey
indexes over `occupied_slots`, and the point of this file is that the races are
run for real against local Mongo rather than reasoned about.

Why a transaction would not have done instead: MongoDB transactions give
snapshot isolation with NO PREDICATE LOCKING. Two transactions that each observe
"no conflicting appointment" and then insert DIFFERENT documents never touch the
same document and never conflict. That is write skew, and it is precisely the
shape of a double-booking — which is why the overlap question is converted into
an equality question that an index can answer atomically.

The slot rules are part of that guarantee, not formatting: 10:00/45min occupies
{10:00, 10:30} and 10:45/45min occupies {10:45, 11:15}, so two appointments that
overlap for a real quarter of an hour share no indexed instant and the unique
index silently stops catching them.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import AppointmentMode, AppointmentStatus
from app.core.exceptions import AppValidationError, ConflictError
from app.services import appointment_slots

pytestmark = pytest.mark.integration


@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import get_appointments_col, get_users_col

    tag = secrets.token_hex(4)
    lawyer_id, lawyer2_id = f"BI-L-{tag}", f"BI-L2-{tag}"
    client_id, client2_id = f"BI-C-{tag}", f"BI-C2-{tag}"
    now = datetime.now(timezone.utc)

    def _lawyer(_id, name):
        return {"_id": _id, "role": "lawyer", "is_active": True,
                "email": f"{_id}@test.invalid", "full_name": name,
                "province": "punjab", "created_at": now,
                "lawyer_profile": {"specializations": ["criminal"],
                                   "kyc_verified": True, "rating": 4.0,
                                   "total_reviews": 0, "availability": True,
                                   "experience_years": 5}}

    await get_users_col().insert_many([
        _lawyer(lawyer_id, "Adv One"), _lawyer(lawyer2_id, "Adv Two"),
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"{client_id}@test.invalid", "full_name": "Client One",
         "created_at": now},
        {"_id": client2_id, "role": "client", "is_active": True,
         "email": f"{client2_id}@test.invalid", "full_name": "Client Two",
         "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "lawyer2_id": lawyer2_id,
           "client_id": client_id, "client2_id": client2_id}
    await get_users_col().delete_many(
        {"_id": {"$in": [lawyer_id, lawyer2_id, client_id, client2_id]}})
    await get_appointments_col().delete_many(
        {"client_id": {"$in": [client_id, client2_id]}})


def _slot(hours_ahead: int = 48, minute: int = 0) -> datetime:
    """An aligned future instant."""
    base = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return base.replace(minute=minute, second=0, microsecond=0)


async def _book(parties, when=None, **over):
    from app.services import appointment_service
    kwargs = {"client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
              "case_id": None, "scheduled_at": when or _slot(),
              "duration_minutes": 60, "mode": AppointmentMode.VIDEO, "notes": None}
    kwargs.update(over)
    return await appointment_service.book_appointment(**kwargs)


def _one_winner(results, *, expect_conflict=True):
    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, Exception)]
    assert len(winners) == 1, f"both bookings were accepted: {results!r}"
    if expect_conflict:
        assert all(isinstance(e, (ConflictError, AppValidationError))
                   for e in losers), f"loser failed for the wrong reason: {losers!r}"
    return winners[0]


# ── 1. The slot model ────────────────────────────────────────────────────────

def test_overlapping_appointments_always_share_a_slot():
    """The property the whole guarantee rests on.

    Checked as a property over the grid rather than on one example, because a
    single passing case would not distinguish a correct generator from one that
    happens to agree at 10:00.
    """
    base = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
    grid = [base + timedelta(minutes=30 * i) for i in range(8)]
    durations = (30, 60, 90, 120)

    for start_a in grid:
        for dur_a in durations:
            end_a = start_a + timedelta(minutes=dur_a)
            slots_a = set(appointment_slots.occupied_slots(start_a, dur_a))
            for start_b in grid:
                for dur_b in durations:
                    end_b = start_b + timedelta(minutes=dur_b)
                    overlaps = start_a < end_b and start_b < end_a
                    shares = bool(slots_a & set(
                        appointment_slots.occupied_slots(start_b, dur_b)))
                    assert overlaps == shares, (
                        f"{start_a:%H:%M}/{dur_a} vs {start_b:%H:%M}/{dur_b}: "
                        f"overlaps={overlaps} but shares_slot={shares}")


def test_the_end_instant_belongs_to_the_next_appointment():
    """Half-open, or back-to-back bookings would collide."""
    start = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
    slots = appointment_slots.occupied_slots(start, 60)

    assert [s.strftime("%H:%M") for s in slots] == ["10:00", "10:30"]
    assert start + timedelta(minutes=60) not in slots


@pytest.mark.parametrize("minute,ok", [(0, True), (30, True), (15, False), (45, False)])
def test_only_half_hour_starts_are_aligned(minute, ok):
    value = datetime(2026, 9, 20, 10, minute, tzinfo=timezone.utc)
    assert (appointment_slots.alignment_error(value) is None) is ok


def test_sub_minute_precision_is_refused_not_truncated():
    """Truncating would move an appointment the client explicitly asked for."""
    value = datetime(2026, 9, 20, 10, 0, 30, tzinfo=timezone.utc)
    assert appointment_slots.alignment_error(value) is not None


@pytest.mark.parametrize("minutes,ok", [
    (30, True), (60, True), (90, True), (180, True),
    (45, False), (20, False), (0, False), (210, False),
])
def test_durations_must_be_whole_slots_within_range(minutes, ok):
    assert (appointment_slots.duration_error(minutes) is None) is ok


# ── 2. Controlled rejection at the API boundary ──────────────────────────────

def test_a_45_minute_booking_is_a_422_not_a_500():
    from pydantic import ValidationError

    from app.schemas.appointment import BookAppointmentRequest

    with pytest.raises(ValidationError, match="multiple of 30"):
        BookAppointmentRequest(
            lawyer_id="L", scheduled_at=_slot(), duration_minutes=45)


def test_a_misaligned_booking_is_a_422_not_a_500():
    from pydantic import ValidationError

    from app.schemas.appointment import BookAppointmentRequest

    with pytest.raises(ValidationError, match="30-minute boundary"):
        BookAppointmentRequest(
            lawyer_id="L", scheduled_at=_slot(minute=45), duration_minutes=60)


# ── 3. Slots are persisted ───────────────────────────────────────────────────

async def test_a_booking_stores_the_slots_it_claims(parties):
    from app.db.collections import get_appointments_col

    when = _slot()
    appt = await _book(parties, when, duration_minutes=90)

    stored = await get_appointments_col().find_one({"_id": appt["id"]})
    assert len(stored["occupied_slots"]) == 3
    assert sorted(s.replace(tzinfo=timezone.utc) for s in stored["occupied_slots"]) == \
        appointment_slots.occupied_slots(when, 90)


# ── 4. The races ─────────────────────────────────────────────────────────────

async def test_a_lawyer_cannot_be_double_booked_by_a_race(parties):
    """10:00/60 and 10:30/60 — the case `uniq_pending_slot` let through.

    Different start times, so the superseded exact-start index saw no duplicate
    at all. They share 10:30.
    """
    at_ten = _slot()
    results = await asyncio.gather(
        _book(parties, at_ten, duration_minutes=60),
        _book(parties, at_ten + timedelta(minutes=30), duration_minutes=60,
              client_id=parties["client2_id"]),
        return_exceptions=True,
    )
    _one_winner(results)


async def test_two_clients_cannot_take_the_same_exact_slot(parties):
    at_ten = _slot()
    results = await asyncio.gather(
        _book(parties, at_ten),
        _book(parties, at_ten, client_id=parties["client2_id"]),
        return_exceptions=True,
    )
    _one_winner(results)


async def test_a_client_cannot_double_book_themselves_across_lawyers(parties):
    """The half `has_conflict` never checked.

    It only ever asked about the LAWYER, so one client could commit two
    different lawyers' diaries to the same hour and attend one of them.
    """
    at_ten = _slot()
    results = await asyncio.gather(
        _book(parties, at_ten, lawyer_id=parties["lawyer_id"]),
        _book(parties, at_ten + timedelta(minutes=30),
              lawyer_id=parties["lawyer2_id"]),
        return_exceptions=True,
    )
    _one_winner(results)


async def test_a_client_booking_two_different_lawyers_at_different_times_is_fine(parties):
    """The guard must not be so wide that it blocks legitimate bookings."""
    at_ten = _slot()
    first = await _book(parties, at_ten, lawyer_id=parties["lawyer_id"])
    second = await _book(parties, at_ten + timedelta(hours=2),
                         lawyer_id=parties["lawyer2_id"])

    assert first["id"] != second["id"]


async def test_back_to_back_appointments_are_allowed(parties):
    """10:00–11:00 then 11:00–12:00. If the end instant were claimed, this
    legitimate pair would be refused as a double booking."""
    at_ten = _slot()
    first = await _book(parties, at_ten, duration_minutes=60)
    second = await _book(parties, at_ten + timedelta(minutes=60),
                         duration_minutes=60, client_id=parties["client2_id"])

    assert first["id"] != second["id"]


# ── 5. Claims held and released ──────────────────────────────────────────────

async def test_confirming_an_appointment_keeps_its_claim(parties):
    """`uniq_pending_slot` was scoped to PENDING alone, so confirming an
    appointment FREED the slot it had just been agreed for."""
    from app.services import appointment_service

    at_ten = _slot()
    appt = await _book(parties, at_ten)
    await appointment_service.confirm_appointment(appt["id"], parties["lawyer_id"])

    with pytest.raises((ConflictError, AppValidationError)):
        await _book(parties, at_ten, client_id=parties["client2_id"])


async def test_cancelling_an_appointment_releases_its_claim(parties):
    """The partial filter is what does this: a cancelled row leaves the index's
    scope, so its instants stop colliding with anyone else's."""
    from app.services import appointment_service

    at_ten = _slot()
    appt = await _book(parties, at_ten)
    await appointment_service.cancel_appointment(
        appt_id=appt["id"], user_id=parties["client_id"],
        user_role="client", reason=None)

    replacement = await _book(parties, at_ten, client_id=parties["client2_id"])
    assert replacement["status"] == AppointmentStatus.PENDING.value


async def test_a_clash_does_not_leak_the_index_or_the_driver_message(parties):
    """The duplicate-key message names the index AND the duplicated values —
    another client's id and the exact hours a lawyer is booked."""
    at_ten = _slot()
    await _book(parties, at_ten)

    with pytest.raises((ConflictError, AppValidationError)) as exc:
        await _book(parties, at_ten, client_id=parties["client2_id"])

    detail = str(exc.value.detail)
    for leak in ("uniq_appointment", "occupied_slots", "E11000",
                 "dup key", parties["client_id"], parties["lawyer_id"]):
        assert leak not in detail, f"{leak!r} leaked into the response"


# ── 6. Idempotency ───────────────────────────────────────────────────────────

async def test_the_same_key_and_payload_replays_the_original(parties):
    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()

    first = await _book(parties, when, idempotency_key=key)
    second = await _book(parties, when, idempotency_key=key)

    assert first["id"] == second["id"]


async def test_a_replay_is_not_reported_as_a_slot_clash(parties):
    """The ordering requirement, stated as a test.

    With the lookup AFTER the conflict check, a retry finds the appointment its
    own first attempt created and is told the slot is taken — reporting failure
    for a booking that succeeded, which is the exact failure idempotency exists
    to prevent.
    """
    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()
    first = await _book(parties, when, idempotency_key=key)

    replay = await _book(parties, when, idempotency_key=key)

    assert replay["id"] == first["id"]
    assert replay["status"] == AppointmentStatus.PENDING.value


async def test_the_same_key_with_a_different_payload_is_a_409(parties):
    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()
    await _book(parties, when, idempotency_key=key)

    with pytest.raises(ConflictError, match="idempotency_mismatch"):
        await _book(parties, when + timedelta(hours=1), idempotency_key=key)


async def test_a_changed_note_is_a_different_booking(parties):
    """`notes` is stored and shown to the lawyer, so a retry that silently
    dropped a changed note would return a receipt for an appointment that does
    not say what the client last sent."""
    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()
    await _book(parties, when, idempotency_key=key, notes="Bail matter")

    with pytest.raises(ConflictError, match="idempotency_mismatch"):
        await _book(parties, when, idempotency_key=key, notes="Property matter")


async def test_whitespace_alone_does_not_make_a_new_booking(parties):
    """Normalisation is conservative but real: the same intent re-sent through a
    client that reformats its payload still matches."""
    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()
    first = await _book(parties, when, idempotency_key=key, notes="Bail  matter")
    second = await _book(parties, when, idempotency_key=key, notes=" Bail matter ")

    assert first["id"] == second["id"]


async def test_concurrent_identical_retries_create_exactly_one_appointment(parties):
    """Both attempts read "no such key", both insert, and the unique index
    decides. The loser must replay the winner, not report a clash."""
    from app.db.collections import get_appointments_col

    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()

    results = await asyncio.gather(
        _book(parties, when, idempotency_key=key),
        _book(parties, when, idempotency_key=key),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, Exception)]
    assert not failures, f"an identical retry failed: {failures!r}"
    assert results[0]["id"] == results[1]["id"], "two different appointments"

    stored = await get_appointments_col().count_documents(
        {"client_id": parties["client_id"], "idempotency_key": key})
    assert stored == 1


async def test_a_replay_does_not_notify_twice(parties):
    """Two notifications for one request would tell the lawyer they had been
    booked twice."""
    from app.db.collections import get_notifications_col

    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()
    appt = await _book(parties, when, idempotency_key=key)
    await _book(parties, when, idempotency_key=key)

    told = await get_notifications_col().count_documents(
        {"payload.appointment_id": appt["id"]})
    assert told == 2, f"expected one notification per party, got {told}"


async def test_concurrent_retries_notify_exactly_one_pair(parties):
    from app.db.collections import get_notifications_col

    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()
    results = await asyncio.gather(
        _book(parties, when, idempotency_key=key),
        _book(parties, when, idempotency_key=key),
    )

    told = await get_notifications_col().count_documents(
        {"payload.appointment_id": results[0]["id"]})
    assert told == 2


def test_the_fingerprint_is_computed_here_and_never_supplied(parties):
    """A client-supplied fingerprint would let a retry declare itself identical
    to a booking it does not match."""
    from app.schemas.appointment import BookAppointmentRequest

    assert "payload_fingerprint" not in BookAppointmentRequest.model_fields


async def test_a_booking_without_a_key_still_works(parties):
    """Every existing caller sends none. The idempotency index is partial on
    `$type: "string"`, so keyless rows are not indexed and cannot collide."""
    first = await _book(parties, _slot())
    second = await _book(parties, _slot(hours_ahead=50),
                         client_id=parties["client2_id"])

    assert first["id"] != second["id"]


# ── 7. The index specification ───────────────────────────────────────────────

async def test_the_declared_indexes_are_actually_in_force(app_indexes):
    from app.db.indexes import validate_appointment_indexes

    assert await validate_appointment_indexes() == []


async def test_a_missing_index_is_detected(app_indexes):
    """The validator has to fail when the guarantee is absent, or the fixture
    that runs it proves nothing."""
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.collections import get_appointments_col
    from app.db.indexes import create_appointment_correctness_indexes, validate_appointment_indexes

    spec = APPOINTMENT_INDEX_REQUIREMENTS[0]
    await get_appointments_col().drop_index(spec.name)
    try:
        problems = await validate_appointment_indexes()
        assert any(p.name == spec.name and p.code == "missing" for p in problems)
    finally:
        await create_appointment_correctness_indexes()

    assert await validate_appointment_indexes() == []


async def test_a_malformed_index_is_detected(app_indexes):
    """An index with the right keys and the wrong options is a DIFFERENT
    guarantee. Mongo keeps the old one in place when a redefinition is refused,
    so this is the realistic failure, not the missing one."""
    from pymongo import ASCENDING, IndexModel

    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.collections import get_appointments_col
    from app.db.indexes import create_appointment_correctness_indexes, validate_appointment_indexes

    spec = next(s for s in APPOINTMENT_INDEX_REQUIREMENTS
                if s.name == "uniq_appointment_lawyer_slot")
    col = get_appointments_col()
    await col.drop_index(spec.name)
    # Same keys, NOT unique — it enforces nothing at all.
    await col.create_indexes([IndexModel(
        [("lawyer_id", ASCENDING), ("occupied_slots", ASCENDING)],
        name=spec.name)])
    try:
        problems = await validate_appointment_indexes()
        assert any(p.name == spec.name and p.code == "not_unique"
                   for p in problems), problems
    finally:
        await col.drop_index(spec.name)
        await create_appointment_correctness_indexes()

    assert await validate_appointment_indexes() == []


async def test_the_enforcer_raises_rather_than_warning(app_indexes):
    """Appointments are live and have no flag, so "missing but nothing depends
    on it" is not a state this collection can be in."""
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.collections import get_appointments_col
    from app.db.indexes import (
        MissingAppointmentIndexes,
        create_appointment_correctness_indexes,
        enforce_appointment_correctness_indexes,
    )

    spec = APPOINTMENT_INDEX_REQUIREMENTS[0]
    await get_appointments_col().drop_index(spec.name)
    try:
        with pytest.raises(MissingAppointmentIndexes) as exc:
            await enforce_appointment_correctness_indexes()
        assert "NOT enforced" in str(exc.value)
    finally:
        await create_appointment_correctness_indexes()

    assert await enforce_appointment_correctness_indexes() == []


async def test_the_superseded_index_is_not_recreated(app_indexes):
    """`uniq_pending_slot` was exact-start-only and scoped to PENDING.

    It is retired in code and reported by the preflight, NOT dropped by the
    application — dropping an index at startup is an operator's decision. The
    check that matters is that running index creation does not bring it back,
    because a deployment that recreated it would keep rejecting idempotent
    retries: two retries of one booking are the same lawyer at the same start.
    """
    from app.db.appointment_index_spec import OBSOLETE_INDEXES
    from app.db.collections import get_appointments_col
    from app.db.indexes import _appointments_indexes

    await _appointments_indexes()

    info = await get_appointments_col().index_information()
    assert "uniq_pending_slot" not in info, (
        "the superseded exact-start index was recreated")
    assert any(name == "uniq_pending_slot" for _, name, _ in OBSOLETE_INDEXES), (
        "it must still be declared obsolete so the preflight reports it")


# ── 8. The preflight writes nothing ──────────────────────────────────────────

async def test_the_preflight_performs_zero_writes(app_indexes, parties):
    """Asserted by COUNTING writes at the driver, not by reading the code.

    A preflight that fixed things itself would destroy the evidence used to
    approve the fix, so "it writes nothing" is a property worth pinning rather
    than trusting.
    """
    from app.db.appointment_slot_preflight import preflight
    from app.db.mongodb import get_database

    await _book(parties, _slot())

    db = get_database()
    calls: list[str] = []

    class _Guard:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            attr = getattr(self._inner, name)
            if name in ("insert_one", "insert_many", "update_one", "update_many",
                        "replace_one", "delete_one", "delete_many",
                        "find_one_and_update", "find_one_and_replace",
                        "find_one_and_delete", "bulk_write", "create_index",
                        "create_indexes", "drop_index", "drop_indexes", "drop"):
                def _refuse(*a, **kw):
                    calls.append(name)
                    raise AssertionError(f"preflight called {name}")
                return _refuse
            return attr

    real_getitem = type(db).__getitem__

    def _wrapped(self, key):
        return _Guard(real_getitem(self, key))

    type(db).__getitem__ = _wrapped
    try:
        result = await preflight()
    finally:
        type(db).__getitem__ = real_getitem

    assert calls == [], f"the preflight wrote: {calls}"
    assert "findings" in result


async def test_the_preflight_reports_an_overlap_without_naming_anyone(app_indexes, parties):
    """Output goes into tickets and chat logs, and an appointment's notes are
    privileged. Counts and appointment ids only."""
    from app.db.appointment_slot_preflight import find_overlaps, render
    from app.db.collections import get_appointments_col
    from app.db.mongodb import get_database

    when = _slot()
    appt = await _book(parties, when, notes="Confidential bail instructions")

    # The overlapping pair is created with the slot indexes ABSENT, which is
    # not a contrivance: the preflight exists to be run BEFORE those indexes
    # are built, on a collection whose history predates them. With the indexes
    # in place this row cannot exist — that is the whole point of them.
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.indexes import create_appointment_correctness_indexes

    slot_indexes = [s.name for s in APPOINTMENT_INDEX_REQUIREMENTS
                    if "slot" in s.name]
    for name in slot_indexes:
        await get_appointments_col().drop_index(name)

    await get_appointments_col().insert_one({
        "_id": f"legacy-{secrets.token_hex(4)}",
        "client_id": parties["client2_id"], "lawyer_id": parties["lawyer_id"],
        "status": AppointmentStatus.PENDING.value,
        "scheduled_at": when, "end_at": when + timedelta(minutes=60),
        "duration_minutes": 60,
        "occupied_slots": appointment_slots.occupied_slots(when, 60),
        "notes": "Another confidential note",
        "meeting_link": "https://secret.example.com/room",
    })

    try:
        findings = await find_overlaps(get_database())
    finally:
        await get_appointments_col().delete_many({"_id": {"$regex": "^legacy-"}})
        await create_appointment_correctness_indexes()

    lawyer_finding = next(f for f in findings
                          if f["code"] == "overlapping_active_lawyer_id")

    assert lawyer_finding["count"] >= 2
    text = render({"database": "x", "indexes_ready": True, "problems": [],
                   "findings": findings, "build_blocking_rows": 2,
                   "rows_needing_backfill": 0, "obsolete_present": [],
                   "recommended_create": [], "recommended_drop": []})
    for leak in ("Confidential bail", "Another confidential",
                 "secret.example.com", "Client One", "Adv One"):
        assert leak not in text, f"{leak!r} leaked into preflight output"
    assert appt["id"] in text, "an operator must be able to find the rows"


async def test_the_preflight_finds_rows_that_would_defeat_the_index(app_indexes, parties):
    """A legacy row with no `occupied_slots` passes the index build and protects
    nothing — a different problem from an overlap, and reported separately."""
    from app.db.appointment_slot_preflight import inspect_rows
    from app.db.collections import get_appointments_col
    from app.db.mongodb import get_database

    when = _slot()
    await get_appointments_col().insert_one({
        "_id": f"legacy-{secrets.token_hex(4)}",
        "client_id": parties["client_id"], "lawyer_id": parties["lawyer2_id"],
        "status": AppointmentStatus.PENDING.value,
        "scheduled_at": when, "end_at": when + timedelta(minutes=60),
        "duration_minutes": 60,
    })

    findings = {f["code"]: f for f in await inspect_rows(get_database())}
    assert findings["missing_occupied_slots"]["count"] >= 1


async def test_the_backfill_defaults_to_dry_run_and_writes_nothing(app_indexes, parties):
    """Dormant by design. Nothing in the application calls it, and the default
    call must not change data."""
    from app.db.appointment_slot_preflight import backfill_occupied_slots
    from app.db.collections import get_appointments_col
    from app.db.mongodb import get_database

    when = _slot()
    legacy_id = f"legacy-{secrets.token_hex(4)}"
    await get_appointments_col().insert_one({
        "_id": legacy_id,
        "client_id": parties["client_id"], "lawyer_id": parties["lawyer2_id"],
        "status": AppointmentStatus.PENDING.value,
        "scheduled_at": when, "end_at": when + timedelta(minutes=60),
        "duration_minutes": 60,
    })

    result = await backfill_occupied_slots(get_database())

    assert result["dry_run"] is True
    assert result["planned"] >= 1
    assert result["written"] == 0
    still = await get_appointments_col().find_one({"_id": legacy_id})
    assert "occupied_slots" not in still, "the dry run wrote to the database"


# ── 9. Rate limiting ─────────────────────────────────────────────────────────

def test_the_booking_route_is_registered_with_the_limiter():
    """Asked of the limiter itself. Looking for a marker attribute on the
    handler finds `__wrapped__`, which any decorator sets."""
    from app.api.v1.routes import appointments as routes  # noqa: F401
    from app.core.rate_limit import limiter

    limits = getattr(limiter, "_route_limits", {})
    key = "app.api.v1.routes.appointments.book_appointment"
    assert key in limits, "POST /appointments is not rate limited"
    assert limits[key]


def test_the_booking_limit_is_tight_enough_to_protect_a_diary():
    """A limit generous enough to be harmless is not a limit. Nothing expires
    stale PENDING requests until Phase 4, so an unlimited POST lets one client
    fill a lawyer's diary permanently."""
    from app.api.v1.routes import appointments as routes

    per_minute = int(routes._LIMIT_BOOK.split("/")[0])
    assert per_minute <= 15, f"_LIMIT_BOOK is {routes._LIMIT_BOOK}, too loose"


def test_the_limit_allows_normal_use_and_refuses_a_flood():
    """The declared limit VALUE, exercised end to end.

    A standalone app with a fresh in-memory limiter, so this neither contacts
    the configured Redis nor turns network reachability into a test result —
    the pattern `test_rate_limit_fails_open` already establishes.
    """
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.util import get_remote_address

    from app.api.v1.routes import appointments as routes

    allowed = int(routes._LIMIT_BOOK.split("/")[0])

    limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.post("/appointments")
    @limiter.limit(routes._LIMIT_BOOK)
    async def _book(request: Request):
        return {"ok": True}

    client = TestClient(app)
    codes = [client.post("/appointments").status_code for _ in range(allowed + 2)]

    assert codes[:allowed] == [200] * allowed, f"a normal session was refused: {codes}"
    assert codes[allowed:] == [429, 429], f"the flood was not refused: {codes}"


# ── 10. Internal fields never reach a response ───────────────────────────────
#
# `AppointmentOut` is `extra="allow"` on purpose — CaseContext caches the whole
# appointments list and components read arbitrary fields off it — so the
# response model filters NOTHING. Whatever `_sanitize` returns is what the
# client gets, which makes these four paths the entire boundary.

_INTERNAL = ("occupied_slots", "idempotency_key", "payload_fingerprint")

# The fields the UI actually reads. Asserted alongside the leak check so a
# future "sanitise everything" cannot pass this file by emptying the payload.
_UI_FIELDS = ("id", "status", "scheduled_at", "end_at", "duration_minutes",
              "mode", "timezone", "lawyer_id", "client_id")


def _assert_clean(payload: dict, where: str) -> None:
    for field in _INTERNAL:
        assert field not in payload, f"{field} leaked from {where}"
    for field in _UI_FIELDS:
        assert field in payload, f"{where} dropped {field}, which the UI reads"


async def test_booking_response_carries_no_internal_fields(parties):
    key = f"bk_{secrets.token_hex(8)}"
    appt = await _book(parties, _slot(), idempotency_key=key)
    _assert_clean(appt, "book_appointment")


async def test_replay_response_carries_no_internal_fields(parties):
    """The replay path returns a row read straight back out of Mongo, so it is
    the one most likely to hand over the stored document verbatim."""
    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()
    await _book(parties, when, idempotency_key=key)

    replay = await _book(parties, when, idempotency_key=key)

    _assert_clean(replay, "the idempotent replay")


async def test_get_response_carries_no_internal_fields(parties):
    from app.services import appointment_service

    key = f"bk_{secrets.token_hex(8)}"
    appt = await _book(parties, _slot(), idempotency_key=key)

    fetched = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["client_id"], user_role="client")

    _assert_clean(fetched, "get_appointment")


async def test_list_response_carries_no_internal_fields(parties):
    from app.services import appointment_service

    key = f"bk_{secrets.token_hex(8)}"
    await _book(parties, _slot(), idempotency_key=key)

    page = await appointment_service.list_appointments(
        user_id=parties["client_id"], user_role="client",
        status=None, page=1, page_size=10)

    assert page["items"]
    for item in page["items"]:
        _assert_clean(item, "list_appointments")


async def test_a_lawyer_never_sees_the_clients_idempotency_key(parties):
    """The key belongs to the client. The lawyer reads the same object."""
    from app.services import appointment_service

    key = f"bk_{secrets.token_hex(8)}"
    appt = await _book(parties, _slot(), idempotency_key=key)

    seen = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["lawyer_id"], user_role="lawyer")

    assert key not in str(seen)


async def test_the_internal_fields_are_still_stored(parties):
    """Hidden from the response, NOT dropped from the database — they are what
    the guarantees are made of."""
    from app.db.collections import get_appointments_col

    key = f"bk_{secrets.token_hex(8)}"
    appt = await _book(parties, _slot(), idempotency_key=key)

    stored = await get_appointments_col().find_one({"_id": appt["id"]})
    assert stored["occupied_slots"]
    assert stored["idempotency_key"] == key
    assert stored["payload_fingerprint"]


# ── 11. The service validates without the schema ─────────────────────────────
#
# `BookAppointmentRequest` guards the HTTP route only. Tests, fixtures, seed
# scripts and any internal caller reach the service directly, and a part-slot
# row written that way is invisible to the overlap guard rather than merely
# untidy.

async def _count(parties) -> int:
    from app.db.collections import get_appointments_col
    return await get_appointments_col().count_documents(
        {"client_id": {"$in": [parties["client_id"], parties["client2_id"]]}})


@pytest.mark.parametrize("minute,duration,expected", [
    (45, 60, "30-minute boundary"),
    (15, 60, "30-minute boundary"),
    (0, 45, "multiple of 30"),
    (0, 100, "multiple of 30"),
    (0, 10, "between 30 and 180"),
    (0, 240, "between 30 and 180"),
])
async def test_a_direct_service_call_refuses_invalid_slots(
        parties, minute, duration, expected):
    before = await _count(parties)

    with pytest.raises(AppValidationError, match=expected):
        await _book(parties, _slot(minute=minute), duration_minutes=duration)

    assert await _count(parties) == before, "an invalid booking was written"


async def test_a_direct_service_call_refuses_a_naive_timestamp(parties):
    """Naive means the caller never said which instant they meant."""
    before = await _count(parties)
    naive = _slot().replace(tzinfo=None)

    with pytest.raises(AppValidationError, match="UTC offset"):
        await _book(parties, naive)

    assert await _count(parties) == before


async def test_a_direct_service_call_refuses_sub_minute_precision(parties):
    before = await _count(parties)

    with pytest.raises(AppValidationError, match="exact to the minute"):
        await _book(parties, _slot().replace(second=30))

    assert await _count(parties) == before


async def test_a_bad_duration_type_is_a_controlled_error_not_a_500(parties):
    before = await _count(parties)

    with pytest.raises(AppValidationError, match="whole number of minutes"):
        await _book(parties, _slot(), duration_minutes="60")

    assert await _count(parties) == before


async def test_invalid_input_is_rejected_before_any_lookup_or_write(parties, monkeypatch):
    """Validation comes first, so a bad booking touches nothing — not the
    idempotency lookup, not the lawyer read, not the collection."""
    from app.repositories.appointment_repo import AppointmentRepository
    from app.repositories.user_repo import UserRepository

    touched: list[str] = []

    async def _watch_find_one(self, *a, **k):
        touched.append("appointment_lookup")
        return None

    async def _watch_user(self, *a, **k):
        touched.append("lawyer_lookup")
        return None

    monkeypatch.setattr(AppointmentRepository, "find_one", _watch_find_one)
    monkeypatch.setattr(UserRepository, "find_by_id", _watch_user)

    with pytest.raises(AppValidationError):
        await _book(parties, _slot(minute=45),
                    idempotency_key=f"bk_{secrets.token_hex(8)}")

    assert touched == [], f"an invalid booking still queried: {touched}"


async def test_the_service_refuses_rather_than_rounding(parties):
    """Rounding would move an appointment the caller explicitly asked for, and
    would do it to exactly the rows already wrong about when they are."""
    from app.db.collections import get_appointments_col

    with pytest.raises(AppValidationError):
        await _book(parties, _slot(minute=45))

    # Nothing was quietly created at the neighbouring aligned instant either.
    assert await get_appointments_col().count_documents(
        {"client_id": parties["client_id"]}) == 0


# ── 12. The preflight is honest ──────────────────────────────────────────────

async def _clear(parties=None) -> None:
    """Empty the appointments collection on the TEST database.

    Deliberately not scoped to this fixture's rows. The preflight and the
    backfill are WHOLE-COLLECTION audits — that is their job — so a gate
    asserting "clean" cannot be evaluated while another module's leftovers are
    still present. Scoping the delete made these tests report the state of the
    whole suite rather than the state under test.

    Safe because pytest runs sequentially and every appointment fixture in this
    suite creates the rows it needs.
    """
    from app.db.collections import get_appointments_col
    await get_appointments_col().delete_many({})


async def test_one_row_with_a_repeated_slot_is_not_reported_as_an_overlap(parties):
    """The false positive. `$sum: 1` counted UNWOUND entries, so a single row
    whose occupied_slots contained one instant twice was announced as an
    overlap between an appointment and itself — blocking work invented during a
    maintenance window."""
    from app.db.appointment_slot_preflight import find_overlaps
    from app.db.collections import get_appointments_col
    from app.db.mongodb import get_database

    await _clear(parties)
    when = _slot()
    occupied = appointment_slots.occupied_slots(when, 60)
    await get_appointments_col().insert_one({
        "_id": f"legacy-{secrets.token_hex(4)}",
        "client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
        "status": AppointmentStatus.PENDING.value,
        "scheduled_at": when, "end_at": when + timedelta(minutes=60),
        "duration_minutes": 60,
        # The same instant twice, in ONE row.
        "occupied_slots": [occupied[0], occupied[0], occupied[1]],
    })
    try:
        findings = await find_overlaps(get_database())
    finally:
        await _clear(parties)

    for finding in findings:
        assert finding["count"] == 0, (
            f"{finding['code']} reported an overlap between one row and itself")


async def test_a_malformed_slot_entry_is_reported_not_filtered_away(parties):
    """Filtering non-datetimes out before comparing made a row carrying one
    compare EQUAL to the correct pair and pass as healthy."""
    from app.db.appointment_slot_preflight import inspect_rows
    from app.db.collections import get_appointments_col
    from app.db.mongodb import get_database

    await _clear(parties)
    when = _slot()
    good = appointment_slots.occupied_slots(when, 60)
    await get_appointments_col().insert_one({
        "_id": f"legacy-{secrets.token_hex(4)}",
        "client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
        "status": AppointmentStatus.PENDING.value,
        "scheduled_at": when, "end_at": when + timedelta(minutes=60),
        "duration_minutes": 60,
        "occupied_slots": [*good, "not-a-datetime"],
    })
    try:
        findings = {f["code"]: f for f in await inspect_rows(get_database())}
    finally:
        await _clear(parties)

    assert findings["malformed_occupied_slots"]["count"] == 1
    assert findings["incorrect_occupied_slots"]["count"] == 0, (
        "a malformed row must be reported as malformed, not merely as wrong")


async def test_a_clean_database_is_safe_to_activate(app_indexes, parties):
    from app.db.appointment_slot_preflight import preflight

    await _clear(parties)
    await _book(parties, _slot())
    await _book(parties, _slot(hours_ahead=52), client_id=parties["client2_id"])

    result = await preflight()

    assert result["safe_to_activate"] is True, result["failed_gates"]
    assert result["failed_gates"] == []


async def test_activation_is_refused_when_an_index_is_missing(app_indexes, parties):
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.appointment_slot_preflight import preflight
    from app.db.collections import get_appointments_col
    from app.db.indexes import create_appointment_correctness_indexes

    await _clear(parties)
    spec = APPOINTMENT_INDEX_REQUIREMENTS[0]
    await get_appointments_col().drop_index(spec.name)
    try:
        result = await preflight()
    finally:
        await create_appointment_correctness_indexes()

    assert result["safe_to_activate"] is False
    assert "indexes_valid" in result["failed_gates"]


async def test_activation_is_refused_while_the_superseded_index_is_present(
        app_indexes, parties):
    """Not a note: it is narrower than its replacement and still refuses writes
    the new rules allow — a second PENDING booking at the same lawyer and
    instant, which a KEYLESS retry is.

    It does not break a retry that carries a key: that is replayed before the
    duplicate-key error is interpreted, so it succeeds whichever index raised
    it. The gate exists because leaving it in place means production enforces
    two overlapping rules, one of which nothing in the code agrees with."""
    from pymongo import ASCENDING, IndexModel

    from app.db.appointment_slot_preflight import preflight
    from app.db.collections import get_appointments_col

    await _clear(parties)
    col = get_appointments_col()
    await col.create_indexes([IndexModel(
        [("lawyer_id", ASCENDING), ("scheduled_at", ASCENDING)],
        name="uniq_pending_slot", unique=True,
        partialFilterExpression={"status": AppointmentStatus.PENDING.value})])
    try:
        result = await preflight()
    finally:
        await col.drop_index("uniq_pending_slot")

    assert result["safe_to_activate"] is False
    assert "obsolete_indexes_absent" in result["failed_gates"]


async def test_activation_is_refused_while_rows_are_unslotted(app_indexes, parties):
    from app.db.appointment_slot_preflight import preflight
    from app.db.collections import get_appointments_col

    await _clear(parties)
    when = _slot()
    await get_appointments_col().insert_one({
        "_id": f"legacy-{secrets.token_hex(4)}",
        "client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
        "status": AppointmentStatus.PENDING.value,
        "scheduled_at": when, "end_at": when + timedelta(minutes=60),
        "duration_minutes": 60,
    })
    try:
        result = await preflight()
    finally:
        await _clear(parties)

    assert result["safe_to_activate"] is False
    assert "all_active_rows_slotted" in result["failed_gates"]


async def test_activation_is_refused_while_a_row_is_unusable(app_indexes, parties):
    from app.db.appointment_slot_preflight import preflight
    from app.db.collections import get_appointments_col

    await _clear(parties)
    when = _slot()
    await get_appointments_col().insert_one({
        "_id": f"legacy-{secrets.token_hex(4)}",
        "client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
        "status": AppointmentStatus.PENDING.value,
        # Misaligned, so no correct slot set exists for it.
        "scheduled_at": when + timedelta(minutes=15),
        "end_at": when + timedelta(minutes=75),
        "duration_minutes": 60,
    })
    try:
        result = await preflight()
    finally:
        await _clear(parties)

    assert result["safe_to_activate"] is False
    assert "all_active_rows_usable" in result["failed_gates"]


async def test_activation_is_refused_while_a_true_overlap_exists(app_indexes, parties):
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.appointment_slot_preflight import preflight
    from app.db.collections import get_appointments_col
    from app.db.indexes import create_appointment_correctness_indexes

    await _clear(parties)
    when = _slot()
    slots = appointment_slots.occupied_slots(when, 60)
    col = get_appointments_col()
    slot_indexes = [s.name for s in APPOINTMENT_INDEX_REQUIREMENTS if "slot" in s.name]
    for name in slot_indexes:
        await col.drop_index(name)
    try:
        for tag in ("a", "b"):
            await col.insert_one({
                "_id": f"legacy-{tag}-{secrets.token_hex(4)}",
                "client_id": (parties["client_id"] if tag == "a"
                              else parties["client2_id"]),
                "lawyer_id": parties["lawyer_id"],
                "status": AppointmentStatus.PENDING.value,
                "scheduled_at": when, "end_at": when + timedelta(minutes=60),
                "duration_minutes": 60, "occupied_slots": slots,
            })
        result = await preflight()
    finally:
        await _clear(parties)
        await create_appointment_correctness_indexes()

    assert result["safe_to_activate"] is False
    assert "no_overlapping_active_rows" in result["failed_gates"]


async def test_activation_is_refused_while_idempotency_keys_collide(app_indexes, parties):
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.appointment_slot_preflight import preflight
    from app.db.collections import get_appointments_col
    from app.db.indexes import create_appointment_correctness_indexes

    await _clear(parties)
    col = get_appointments_col()
    idx = next(s.name for s in APPOINTMENT_INDEX_REQUIREMENTS
               if s.name == "uniq_appointment_idempotency")
    await col.drop_index(idx)
    try:
        for i, hours in enumerate((60, 64)):
            when = _slot(hours_ahead=hours)
            await col.insert_one({
                "_id": f"legacy-{i}-{secrets.token_hex(4)}",
                "client_id": parties["client_id"],
                "lawyer_id": parties["lawyer_id"],
                "status": AppointmentStatus.PENDING.value,
                "scheduled_at": when, "end_at": when + timedelta(minutes=60),
                "duration_minutes": 60,
                "occupied_slots": appointment_slots.occupied_slots(when, 60),
                "idempotency_key": "bk_shared_key_value",
            })
        result = await preflight()
    finally:
        await _clear(parties)
        await create_appointment_correctness_indexes()

    assert result["safe_to_activate"] is False
    assert "no_idempotency_collisions" in result["failed_gates"]


async def test_the_verdict_is_rendered_not_only_returned(app_indexes, parties):
    """An operator reads the report, not the dict."""
    from app.db.appointment_slot_preflight import preflight, render

    await _clear(parties)
    await _book(parties, _slot())
    text = render(await preflight())

    assert "SAFE TO ACTIVATE" in text
    assert "NOT SAFE TO ACTIVATE" not in text


async def test_the_gates_are_still_read_only(app_indexes, parties):
    """Adding a verdict must not have added a write."""
    from app.db.appointment_slot_preflight import preflight
    from app.db.mongodb import get_database

    await _clear(parties)
    await _book(parties, _slot())

    db = get_database()
    calls: list[str] = []

    class _Guard:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            attr = getattr(self._inner, name)
            if name in ("insert_one", "insert_many", "update_one", "update_many",
                        "replace_one", "delete_one", "delete_many",
                        "find_one_and_update", "find_one_and_replace",
                        "find_one_and_delete", "bulk_write", "create_index",
                        "create_indexes", "drop_index", "drop_indexes", "drop"):
                def _refuse(*a, **kw):
                    calls.append(name)
                    raise AssertionError(f"preflight called {name}")
                return _refuse
            return attr

    real_getitem = type(db).__getitem__
    type(db).__getitem__ = lambda self, key: _Guard(real_getitem(self, key))
    try:
        await preflight()
    finally:
        type(db).__getitem__ = real_getitem

    assert calls == []


async def test_the_backfill_repairs_a_malformed_row_rather_than_skipping_it(parties):
    """Filtering unreadable entries out before comparing would make such a row
    compare EQUAL and be skipped — leaving in place exactly what the backfill
    exists to fix. Still a dry run: planned, not written."""
    from app.db.appointment_slot_preflight import backfill_occupied_slots
    from app.db.collections import get_appointments_col
    from app.db.mongodb import get_database

    await _clear(parties)
    when = _slot()
    good = appointment_slots.occupied_slots(when, 60)
    legacy_id = f"legacy-{secrets.token_hex(4)}"
    await get_appointments_col().insert_one({
        "_id": legacy_id,
        "client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
        "status": AppointmentStatus.PENDING.value,
        "scheduled_at": when, "end_at": when + timedelta(minutes=60),
        "duration_minutes": 60,
        "occupied_slots": [*good, "not-a-datetime"],
    })
    try:
        result = await backfill_occupied_slots(get_database())
    finally:
        await _clear(parties)

    assert result["planned"] == 1, "the malformed row was skipped as healthy"
    assert result["written"] == 0


# ── 13. end_at must agree with the row's own start and duration ──────────────
#
# `end_at` is STORED, not derived on read, and it is what the completion rule
# compares against. A row whose end disagrees with start + duration is telling
# two stories about when it finishes: the slots it claims come from the
# duration, whether it may be completed comes from end_at.

async def _insert_legacy(parties, **over) -> str:
    """A row written straight to Mongo, the way a legacy row exists."""
    from app.db.collections import get_appointments_col

    when = over.pop("scheduled_at", None) or _slot()
    duration = over.pop("duration_minutes", 60)
    doc = {
        "_id": f"legacy-{secrets.token_hex(4)}",
        "client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
        "status": AppointmentStatus.PENDING.value,
        "scheduled_at": when,
        "end_at": when + timedelta(minutes=duration),
        "duration_minutes": duration,
        "occupied_slots": appointment_slots.occupied_slots(when, duration),
    }
    doc.update(over)
    # `occupied_slots=None` means the field was never written, which is what a
    # pre-backfill row looks like. Setting it to null instead would be a
    # different row — one that HAS the field — and a test asserting "startup
    # did not backfill" would then pass whatever startup did.
    if doc.get("occupied_slots") is None:
        doc.pop("occupied_slots", None)
    await get_appointments_col().insert_one(doc)
    return doc["_id"]


async def test_an_end_time_that_is_too_early_is_reported(parties):
    from app.db.appointment_slot_preflight import inspect_rows
    from app.db.mongodb import get_database

    await _clear(parties)
    when = _slot()
    appt_id = await _insert_legacy(
        parties, scheduled_at=when, duration_minutes=60,
        end_at=when + timedelta(minutes=30))
    try:
        findings = {f["code"]: f for f in await inspect_rows(get_database())}
    finally:
        await _clear(parties)

    assert findings["end_at_mismatch"]["count"] == 1
    assert appt_id in findings["end_at_mismatch"]["appointment_ids"]


async def test_an_end_time_that_is_too_late_is_reported(parties):
    from app.db.appointment_slot_preflight import inspect_rows
    from app.db.mongodb import get_database

    await _clear(parties)
    when = _slot()
    appt_id = await _insert_legacy(
        parties, scheduled_at=when, duration_minutes=60,
        end_at=when + timedelta(minutes=120))
    try:
        findings = {f["code"]: f for f in await inspect_rows(get_database())}
    finally:
        await _clear(parties)

    assert findings["end_at_mismatch"]["count"] == 1
    assert appt_id in findings["end_at_mismatch"]["appointment_ids"]


async def test_a_consistent_end_time_is_not_reported(parties):
    from app.db.appointment_slot_preflight import inspect_rows
    from app.db.mongodb import get_database

    await _clear(parties)
    await _insert_legacy(parties)
    try:
        findings = {f["code"]: f for f in await inspect_rows(get_database())}
    finally:
        await _clear(parties)

    assert findings["end_at_mismatch"]["count"] == 0


@pytest.mark.parametrize("skew", [-30, 30])
async def test_an_end_at_mismatch_blocks_activation(app_indexes, parties, skew):
    from app.db.appointment_slot_preflight import preflight

    await _clear(parties)
    when = _slot()
    await _insert_legacy(parties, scheduled_at=when, duration_minutes=60,
                         end_at=when + timedelta(minutes=60 + skew))
    try:
        result = await preflight()
    finally:
        await _clear(parties)

    assert result["safe_to_activate"] is False
    assert "all_active_rows_usable" in result["failed_gates"]


# ── 14. Activation is enforced, not merely documented ────────────────────────
#
# The booking path has no feature flag: it writes slots and relies on the
# indexes from the first request after deploy. So there is no state in which
# "not ready yet" is survivable, and startup is fail-closed.

async def test_a_prepared_database_permits_startup(app_indexes, parties):
    from app.db.appointment_slot_preflight import assert_appointment_booking_ready

    await _clear(parties)
    await _book(parties, _slot())

    await assert_appointment_booking_ready()   # must not raise


async def test_startup_refuses_while_an_index_is_missing(app_indexes, parties):
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.appointment_slot_preflight import (
        AppointmentBookingNotReady,
        assert_appointment_booking_ready,
    )
    from app.db.collections import get_appointments_col
    from app.db.indexes import create_appointment_correctness_indexes

    await _clear(parties)
    spec = APPOINTMENT_INDEX_REQUIREMENTS[0]
    await get_appointments_col().drop_index(spec.name)
    try:
        with pytest.raises(AppointmentBookingNotReady) as exc:
            await assert_appointment_booking_ready()
        assert "indexes_valid" in str(exc.value)
    finally:
        await create_appointment_correctness_indexes()


async def test_startup_refuses_while_an_index_is_malformed(app_indexes, parties):
    """The realistic failure. Mongo keeps the old index when a redefinition is
    refused, so "present" and "correct" are different questions."""
    from pymongo import ASCENDING, IndexModel

    from app.db.appointment_slot_preflight import (
        AppointmentBookingNotReady,
        assert_appointment_booking_ready,
    )
    from app.db.collections import get_appointments_col
    from app.db.indexes import create_appointment_correctness_indexes

    await _clear(parties)
    col = get_appointments_col()
    await col.drop_index("uniq_appointment_lawyer_slot")
    # Same keys, NOT unique — it enforces nothing.
    await col.create_indexes([IndexModel(
        [("lawyer_id", ASCENDING), ("occupied_slots", ASCENDING)],
        name="uniq_appointment_lawyer_slot")])
    try:
        with pytest.raises(AppointmentBookingNotReady):
            await assert_appointment_booking_ready()
    finally:
        await col.drop_index("uniq_appointment_lawyer_slot")
        await create_appointment_correctness_indexes()


async def test_startup_refuses_while_unsafe_legacy_rows_exist(app_indexes, parties):
    """The case an index-only check cannot see.

    Every index is present and valid; the row simply carries no slots, so it is
    absent from them. The guarantee reads as enforced and this appointment can
    be double-booked freely.
    """
    from app.db.appointment_slot_preflight import (
        AppointmentBookingNotReady,
        assert_appointment_booking_ready,
    )
    from app.db.indexes import validate_appointment_indexes

    await _clear(parties)
    await _insert_legacy(parties, occupied_slots=None)
    try:
        assert await validate_appointment_indexes() == [], (
            "precondition: the indexes themselves are fine")
        with pytest.raises(AppointmentBookingNotReady) as exc:
            await assert_appointment_booking_ready()
        assert "all_active_rows_slotted" in str(exc.value)
    finally:
        await _clear(parties)


async def test_startup_refuses_while_the_obsolete_index_is_present(app_indexes, parties):
    from pymongo import ASCENDING, IndexModel

    from app.db.appointment_slot_preflight import (
        AppointmentBookingNotReady,
        assert_appointment_booking_ready,
    )
    from app.db.collections import get_appointments_col

    await _clear(parties)
    col = get_appointments_col()
    await col.create_indexes([IndexModel(
        [("lawyer_id", ASCENDING), ("scheduled_at", ASCENDING)],
        name="uniq_pending_slot", unique=True,
        partialFilterExpression={"status": AppointmentStatus.PENDING.value})])
    try:
        with pytest.raises(AppointmentBookingNotReady) as exc:
            await assert_appointment_booking_ready()
        assert "obsolete_indexes_absent" in str(exc.value)
    finally:
        await col.drop_index("uniq_pending_slot")


async def test_the_refusal_names_the_remedy_and_says_nothing_changed(app_indexes, parties):
    """An operator reads this in a crash log at deploy time."""
    from app.db.appointment_slot_preflight import (
        AppointmentBookingNotReady,
        assert_appointment_booking_ready,
    )

    await _clear(parties)
    await _insert_legacy(parties, occupied_slots=None)
    try:
        with pytest.raises(AppointmentBookingNotReady) as exc:
            await assert_appointment_booking_ready()
    finally:
        await _clear(parties)

    message = str(exc.value)
    assert "NOTHING HAS BEEN CHANGED" in message
    assert "appointment_slot_preflight" in message
    assert "not restart" in message.lower()


async def test_startup_never_silently_repairs_correctness_state(app_indexes, parties):
    """The property that makes the refusal meaningful.

    If a failed startup could create the index, drop the obsolete one or
    backfill the rows, then restarting would establish correctness quietly and
    nobody could tell from the outside whether the guarantee ever held.
    """
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.appointment_slot_preflight import (
        AppointmentBookingNotReady,
        assert_appointment_booking_ready,
    )
    from app.db.collections import get_appointments_col
    from app.db.indexes import create_appointment_correctness_indexes

    await _clear(parties)
    legacy_id = await _insert_legacy(parties, occupied_slots=None)
    spec = APPOINTMENT_INDEX_REQUIREMENTS[0]
    col = get_appointments_col()
    await col.drop_index(spec.name)
    try:
        for _ in range(3):          # restarting changes nothing
            with pytest.raises(AppointmentBookingNotReady):
                await assert_appointment_booking_ready()

        info = await col.index_information()
        assert spec.name not in info, "startup created a correctness index"

        row = await col.find_one({"_id": legacy_id})
        assert "occupied_slots" not in row, "startup backfilled a row"
    finally:
        await _clear(parties)
        await create_appointment_correctness_indexes()


async def test_normal_index_creation_does_not_build_the_correctness_indexes(app_indexes):
    """`create_all_indexes` is what startup runs. If it built these, a deploy
    would repair correctness state as a side effect of restarting."""
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.collections import get_appointments_col
    from app.db.indexes import _appointments_indexes, create_appointment_correctness_indexes

    col = get_appointments_col()
    for spec in APPOINTMENT_INDEX_REQUIREMENTS:
        await col.drop_index(spec.name)
    try:
        await _appointments_indexes()
        info = await col.index_information()
        for spec in APPOINTMENT_INDEX_REQUIREMENTS:
            assert spec.name not in info, (
                f"{spec.name} was created by ordinary startup index creation")
    finally:
        await create_appointment_correctness_indexes()

    assert await _validate() == []


async def _validate():
    from app.db.indexes import validate_appointment_indexes
    return await validate_appointment_indexes()


async def test_the_explicit_creation_function_builds_exactly_the_spec(app_indexes):
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.collections import get_appointments_col
    from app.db.indexes import create_appointment_correctness_indexes

    col = get_appointments_col()
    for spec in APPOINTMENT_INDEX_REQUIREMENTS:
        await col.drop_index(spec.name)

    await create_appointment_correctness_indexes()

    assert await _validate() == []


async def test_the_readiness_check_is_read_only(app_indexes, parties):
    """It is the thing standing between a deploy and the database, so it gets
    its own write-interception proof rather than inheriting the preflight's."""
    from app.db.appointment_slot_preflight import assert_appointment_booking_ready
    from app.db.mongodb import get_database

    await _clear(parties)
    await _book(parties, _slot())

    db = get_database()
    calls: list[str] = []

    class _Guard:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            attr = getattr(self._inner, name)
            if name in ("insert_one", "insert_many", "update_one", "update_many",
                        "replace_one", "delete_one", "delete_many",
                        "find_one_and_update", "find_one_and_replace",
                        "find_one_and_delete", "bulk_write", "create_index",
                        "create_indexes", "drop_index", "drop_indexes", "drop"):
                def _refuse(*a, **kw):
                    calls.append(name)
                    raise AssertionError(f"readiness check called {name}")
                return _refuse
            return attr

    real_getitem = type(db).__getitem__
    type(db).__getitem__ = lambda self, key: _Guard(real_getitem(self, key))
    try:
        await assert_appointment_booking_ready()
    finally:
        type(db).__getitem__ = real_getitem

    assert calls == []


def test_startup_calls_the_full_readiness_check_not_just_the_index_one():
    """An index-only gate at startup would pass over a collection whose active
    rows carry no slots — every guarantee reading as enforced while the rows
    that predate the backfill claim nothing."""
    import inspect

    from app import main

    source = inspect.getsource(main.lifespan)
    assert "assert_appointment_booking_ready" in source
    assert "enforce_appointment_correctness_indexes" not in source, (
        "the index-only enforcer is not sufficient at startup")


# ── 15. The obsolete index, described accurately ─────────────────────────────

async def test_a_keyed_retry_survives_the_obsolete_index(app_indexes, parties):
    """The correction.

    An earlier claim here was that `uniq_pending_slot` breaks every idempotent
    retry. It does not: a retry carrying a key is replayed BEFORE the
    duplicate-key error is interpreted, so it succeeds whichever index raised
    it. That claim was measured against a revision of the service in which the
    replay was gated behind the constraint name, and was not re-checked after
    the ordering was fixed.
    """
    from pymongo import ASCENDING, IndexModel

    from app.db.collections import get_appointments_col

    await _clear(parties)
    col = get_appointments_col()
    await col.create_indexes([IndexModel(
        [("lawyer_id", ASCENDING), ("scheduled_at", ASCENDING)],
        name="uniq_pending_slot", unique=True,
        partialFilterExpression={"status": AppointmentStatus.PENDING.value})])
    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()
    try:
        first = await _book(parties, when, idempotency_key=key)
        replay = await _book(parties, when, idempotency_key=key)

        assert replay["id"] == first["id"], (
            "a keyed retry must still replay with the obsolete index present")
    finally:
        await col.drop_index("uniq_pending_slot")
        await _clear(parties)


async def test_the_obsolete_index_still_refuses_writes_the_new_rules_allow(
        app_indexes, parties):
    """Why it is still a blocking gate. It is narrower than its replacement and
    scoped to PENDING, so it rejects a second PENDING booking at the same
    lawyer and instant — which a KEYLESS retry is."""
    from pymongo import ASCENDING, IndexModel

    from app.db.collections import get_appointments_col

    await _clear(parties)
    col = get_appointments_col()
    await col.create_indexes([IndexModel(
        [("lawyer_id", ASCENDING), ("scheduled_at", ASCENDING)],
        name="uniq_pending_slot", unique=True,
        partialFilterExpression={"status": AppointmentStatus.PENDING.value})])
    when = _slot()
    try:
        await _book(parties, when)
        with pytest.raises((ConflictError, AppValidationError)):
            await _book(parties, when, client_id=parties["client2_id"])
    finally:
        await col.drop_index("uniq_pending_slot")
        await _clear(parties)


def test_the_documented_order_drops_the_obsolete_index_after_validation():
    """Dropping it before the replacements exist leaves a window with NO
    overlap protection, inside a window that exists to add some."""
    from app.db import appointment_slot_preflight as pf

    doc = pf.__doc__
    drop_at = doc.index("drop the obsolete uniq_pending_slot")
    create_at = doc.index("create_appointment_correctness_indexes()")
    validate_at = doc.index("validate_appointment_indexes()")

    assert create_at < drop_at, "the drop must come after the indexes are built"
    assert validate_at < drop_at, "and after they are validated"


def test_the_obsolete_entry_does_not_overstate_its_effect():
    from app.db.appointment_index_spec import OBSOLETE_INDEXES

    why = next(w for _, name, w in OBSOLETE_INDEXES if name == "uniq_pending_slot")
    assert "ONLY AFTER" in why
    assert "every retr" not in why.lower(), (
        "the overstated claim must not come back")
