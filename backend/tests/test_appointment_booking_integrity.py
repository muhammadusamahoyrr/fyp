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
    from app.db.indexes import _appointments_indexes, validate_appointment_indexes

    spec = APPOINTMENT_INDEX_REQUIREMENTS[0]
    await get_appointments_col().drop_index(spec.name)
    try:
        problems = await validate_appointment_indexes()
        assert any(p.name == spec.name and p.code == "missing" for p in problems)
    finally:
        await _appointments_indexes()

    assert await validate_appointment_indexes() == []


async def test_a_malformed_index_is_detected(app_indexes):
    """An index with the right keys and the wrong options is a DIFFERENT
    guarantee. Mongo keeps the old one in place when a redefinition is refused,
    so this is the realistic failure, not the missing one."""
    from pymongo import ASCENDING, IndexModel

    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.collections import get_appointments_col
    from app.db.indexes import _appointments_indexes, validate_appointment_indexes

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
        await _appointments_indexes()

    assert await validate_appointment_indexes() == []


async def test_the_enforcer_raises_rather_than_warning(app_indexes):
    """Appointments are live and have no flag, so "missing but nothing depends
    on it" is not a state this collection can be in."""
    from app.db.appointment_index_spec import APPOINTMENT_INDEX_REQUIREMENTS
    from app.db.collections import get_appointments_col
    from app.db.indexes import (
        MissingAppointmentIndexes,
        _appointments_indexes,
        enforce_appointment_correctness_indexes,
    )

    spec = APPOINTMENT_INDEX_REQUIREMENTS[0]
    await get_appointments_col().drop_index(spec.name)
    try:
        with pytest.raises(MissingAppointmentIndexes) as exc:
            await enforce_appointment_correctness_indexes()
        assert "NOT enforced" in str(exc.value)
    finally:
        await _appointments_indexes()

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
    from app.db.indexes import _appointments_indexes

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
        await _appointments_indexes()

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
