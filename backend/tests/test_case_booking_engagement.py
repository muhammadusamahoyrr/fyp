"""First integration coverage for three core write paths.

`create_case`, `book_appointment` and `request_engagement` had NO tests — not at
the service level, not through their routes, not anywhere. Verified three ways:
no test file imports `appointment_service` at all, none calls these functions,
and no test references the `/cases`, `/appointments` or `/engagements` route
paths. `test_e2e_http.py` runs no lifespan and touches no database.

Each of the three carries a race guard that is a UNIQUE INDEX, and each sits
behind an ordinary application pre-check that handles the sequential case:

    create_case          cases.case_number            unique
    book_appointment     uniq_pending_slot            partial, status=pending
    request_engagement   uniq_pending_engagement      partial, status=requested

The pre-checks (`has_conflict`, `find_pending_for_case`) are what a normal user
hits. The index is what decides the concurrent case, where both requests read
"free" before either writes — a window no read-then-write check can close. So
the tests below deliberately do both: exercise the pre-check as a user meets it,
and then neutralise the pre-check to prove the index is really underneath.

Every test takes `app_indexes`, because none of these indexes exists on the test
database otherwise: `create_all_indexes()` runs at application startup, which no
test performs.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import (
    AppointmentMode, AppointmentStatus, CaseStatus, EngagementStatus,
)
from app.core.exceptions import AppValidationError, ConflictError, ForbiddenError

pytestmark = pytest.mark.integration


@pytest.fixture
async def parties(app_indexes):
    """A verified lawyer and a client, with the real application indexes."""
    from app.db.collections import (
        get_appointments_col, get_cases_col, get_engagements_col, get_users_col,
    )

    tag = secrets.token_hex(4)
    lawyer_id, client_id = f"CB-L-{tag}", f"CB-C-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"cb-l-{tag}@test.invalid", "full_name": "Adv Booking",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["criminal"],
                            "kyc_verified": True, "rating": 4.0,
                            "total_reviews": 0, "availability": True,
                            "experience_years": 7}},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"cb-c-{tag}@test.invalid", "full_name": "Client Booking",
         "created_at": now},
    ])

    yield {"lawyer_id": lawyer_id, "client_id": client_id, "tag": tag}

    await get_users_col().delete_many({"_id": {"$in": [lawyer_id, client_id]}})
    await get_cases_col().delete_many({"client_id": client_id})
    await get_appointments_col().delete_many({"client_id": client_id})
    await get_engagements_col().delete_many({"client_id": client_id})


def _case_data(**over) -> dict:
    data = {"case_type": "criminal", "province": "punjab",
            "title": "FIR quashment", "description": "Pre-arrest bail sought."}
    data.update(over)
    return data


# ── create_case ──────────────────────────────────────────────────────────────

async def test_a_case_is_created_with_a_case_number(parties):
    from app.services import case_service

    case = await case_service.create_case(parties["client_id"], _case_data())

    assert case["case_number"].startswith("ATT-")
    assert case["client_id"] == parties["client_id"]
    assert case["lawyer_id"] is None
    assert case["status"] == CaseStatus.OPEN.value


async def test_two_cases_get_distinct_case_numbers(parties):
    from app.services import case_service

    a = await case_service.create_case(parties["client_id"], _case_data())
    b = await case_service.create_case(parties["client_id"], _case_data())

    assert a["case_number"] != b["case_number"]


async def test_a_case_number_collision_is_retried(parties, monkeypatch):
    """The retry loop, which nothing had ever executed.

    Counts INSERT ATTEMPTS, not calls to the number generator. The generator is
    an unreliable witness here: `create_case` calls it twice on every happy
    path — once to populate the initial document, where the value is discarded
    unread, and once inside the loop. An earlier version of this test asserted
    "the generator was called twice" and so passed whether or not a collision
    had ever occurred, which is precisely the kind of test this file exists to
    stop existing.

    The insert is the thing that can actually fail, so the insert is what gets
    counted. And because only the unique index makes the first attempt fail,
    dropping that index makes this test fail — which is the point.
    """
    from app.repositories.case_repo import CaseRepository
    from app.services import case_service

    first = await case_service.create_case(parties["client_id"], _case_data())
    taken = first["case_number"]

    attempts: list[str] = []
    real_insert = CaseRepository.insert

    async def _counting_insert(self, document):
        attempts.append(document["case_number"])
        return await real_insert(self, document)

    monkeypatch.setattr(CaseRepository, "insert", _counting_insert)
    # Hand out the taken number until it has actually been ATTEMPTED once;
    # anything after that is unique. Written against attempts rather than a
    # call count so the discarded generator call above cannot consume it.
    monkeypatch.setattr(
        case_service, "_gen_case_number",
        lambda: taken if not attempts else f"ATT-2026-{secrets.token_hex(4).upper()}",
    )

    second = await case_service.create_case(parties["client_id"], _case_data())

    assert attempts[0] == taken, "the colliding number was never attempted"
    assert len(attempts) == 2, (
        f"expected one failed insert then one success, got {attempts} — "
        "without the unique index the first insert succeeds and no retry happens"
    )
    assert second["case_number"] != taken
    assert second["case_number"] == attempts[1]


async def test_a_case_number_that_never_resolves_is_refused(parties, monkeypatch):
    """Five collisions in a row must fail cleanly rather than loop or silently
    write a duplicate."""
    from app.services import case_service

    first = await case_service.create_case(parties["client_id"], _case_data())
    monkeypatch.setattr(case_service, "_gen_case_number",
                        lambda: first["case_number"])

    with pytest.raises(AppValidationError, match="unique case number"):
        await case_service.create_case(parties["client_id"], _case_data())


async def test_concurrent_case_creation_produces_distinct_numbers(parties):
    from app.services import case_service

    created = await asyncio.gather(*[
        case_service.create_case(parties["client_id"], _case_data())
        for _ in range(5)
    ])
    numbers = [c["case_number"] for c in created]
    assert len(set(numbers)) == 5, f"case numbers collided: {numbers}"


# ── book_appointment ─────────────────────────────────────────────────────────

def _slot(hours_ahead: int = 48) -> datetime:
    base = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return base.replace(minute=0, second=0, microsecond=0)


async def _book(parties, when, **over):
    from app.services import appointment_service
    kwargs = {"client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
              "case_id": None, "scheduled_at": when, "duration_minutes": 30,
              "mode": AppointmentMode.VIDEO, "notes": None}
    kwargs.update(over)
    return await appointment_service.book_appointment(**kwargs)


async def test_an_appointment_can_be_booked(parties):
    appt = await _book(parties, _slot())

    assert appt["status"] == AppointmentStatus.PENDING.value
    assert appt["lawyer_id"] == parties["lawyer_id"]


async def test_a_taken_slot_is_refused_by_the_availability_check(parties):
    """What an ordinary second client meets: the read-then-write pre-check."""
    when = _slot()
    await _book(parties, when)

    with pytest.raises(AppValidationError, match="already booked"):
        await _book(parties, when)


async def test_a_slot_race_is_refused_by_the_unique_index(parties, monkeypatch):
    """The window the pre-check cannot close.

    `has_conflict` is neutralised so the booking reaches the insert believing
    the slot is free — exactly the state two concurrent requests are both in
    before either has written. Only the unique index can decide it, and the
    message proves which guard fired.

    Now a ConflictError (409) rather than an AppValidationError (422), and the
    guard is `uniq_appointment_lawyer_slot` rather than the superseded
    `uniq_pending_slot`. A slot clash IS a conflict: nothing the caller sent is
    invalid, the world moved under them, and re-reading availability is the fix
    — the same distinction Phase 2 drew for stale transitions.
    """
    from app.core.exceptions import ConflictError
    from app.repositories.appointment_repo import AppointmentRepository

    when = _slot()
    await _book(parties, when)

    async def _no_conflict(self, *a, **k):
        return False

    monkeypatch.setattr(AppointmentRepository, "has_conflict", _no_conflict)

    with pytest.raises(ConflictError, match="was just booked"):
        await _book(parties, when)


async def test_a_cancelled_booking_frees_the_slot(parties, monkeypatch):
    """The guard is PARTIAL — scoped to pending. A cancelled appointment must
    not keep a slot reserved forever."""
    from app.db.collections import get_appointments_col
    from app.repositories.appointment_repo import AppointmentRepository

    when = _slot()
    first = await _book(parties, when)
    await get_appointments_col().update_one(
        {"_id": first["id"]},
        {"$set": {"status": AppointmentStatus.CANCELLED.value}})

    async def _no_conflict(self, *a, **k):
        return False

    monkeypatch.setattr(AppointmentRepository, "has_conflict", _no_conflict)

    again = await _book(parties, when)
    assert again["status"] == AppointmentStatus.PENDING.value


async def test_booking_an_unverified_lawyer_is_refused(parties):
    from app.db.collections import get_users_col

    await get_users_col().update_one(
        {"_id": parties["lawyer_id"]},
        {"$set": {"lawyer_profile.kyc_verified": False}})

    with pytest.raises(AppValidationError, match="KYC"):
        await _book(parties, _slot())


async def test_booking_against_someone_elses_case_is_refused(parties):
    from app.db.collections import get_cases_col

    other_case = f"CB-OTHER-{parties['tag']}"
    await get_cases_col().insert_one({
        "_id": other_case, "client_id": "somebody-else", "lawyer_id": None,
        "case_number": f"ATT-2026-{parties['tag'].upper()}",
        "case_type": "civil", "province": "punjab", "title": "Not yours",
        "description": "x", "status": CaseStatus.OPEN.value})

    with pytest.raises(ForbiddenError):
        await _book(parties, _slot(), case_id=other_case)


# ── request_engagement ───────────────────────────────────────────────────────

async def _a_case(parties) -> str:
    from app.services import case_service
    case = await case_service.create_case(parties["client_id"], _case_data())
    return case["_id"]


async def test_an_engagement_can_be_requested(parties):
    from app.services import engagement_service

    case_id = await _a_case(parties)
    eng = await engagement_service.request_engagement(
        parties["client_id"], {"case_id": case_id,
                               "lawyer_id": parties["lawyer_id"]})

    assert eng["status"] == EngagementStatus.REQUESTED.value
    assert eng["case_id"] == case_id


async def test_a_second_request_for_the_same_case_is_refused(parties):
    """The ordinary path: the pending-request pre-check."""
    from app.services import engagement_service

    case_id = await _a_case(parties)
    payload = {"case_id": case_id, "lawyer_id": parties["lawyer_id"]}
    await engagement_service.request_engagement(parties["client_id"], payload)

    with pytest.raises(ConflictError, match="pending request"):
        await engagement_service.request_engagement(parties["client_id"], payload)


async def test_an_engagement_race_is_refused_by_the_unique_index(
    parties, monkeypatch
):
    """Both requests read "no pending engagement" before either writes. Only
    `uniq_pending_engagement` decides it."""
    from app.repositories.engagement_repo import EngagementRepository
    from app.services import engagement_service

    case_id = await _a_case(parties)
    payload = {"case_id": case_id, "lawyer_id": parties["lawyer_id"]}
    await engagement_service.request_engagement(parties["client_id"], payload)

    async def _none_pending(self, _case_id):
        return None

    monkeypatch.setattr(EngagementRepository, "find_pending_for_case",
                        _none_pending)

    with pytest.raises(ConflictError, match="pending request"):
        await engagement_service.request_engagement(parties["client_id"], payload)


async def test_concurrent_requests_leave_exactly_one_open(parties, monkeypatch):
    """The real race, run concurrently: five requests, one engagement."""
    from app.db.collections import get_engagements_col
    from app.repositories.engagement_repo import EngagementRepository
    from app.services import engagement_service

    case_id = await _a_case(parties)
    payload = {"case_id": case_id, "lawyer_id": parties["lawyer_id"]}

    async def _none_pending(self, _case_id):
        return None

    monkeypatch.setattr(EngagementRepository, "find_pending_for_case",
                        _none_pending)

    results = await asyncio.gather(
        *[engagement_service.request_engagement(parties["client_id"], payload)
          for _ in range(5)],
        return_exceptions=True,
    )

    created = [r for r in results if isinstance(r, dict)]
    refused = [r for r in results if isinstance(r, ConflictError)]

    assert len(created) == 1, f"more than one engagement was opened: {results}"
    assert len(refused) == 4
    assert await get_engagements_col().count_documents(
        {"case_id": case_id,
         "status": EngagementStatus.REQUESTED.value}) == 1


async def test_a_cancelled_request_allows_another(parties, monkeypatch):
    """The guard is PARTIAL — scoped to `requested`. Cancelling must let the
    client approach a different lawyer."""
    from app.db.collections import get_engagements_col
    from app.services import engagement_service

    case_id = await _a_case(parties)
    payload = {"case_id": case_id, "lawyer_id": parties["lawyer_id"]}
    first = await engagement_service.request_engagement(
        parties["client_id"], payload)

    await get_engagements_col().update_one(
        {"_id": first["id"]},
        {"$set": {"status": EngagementStatus.CANCELLED.value}})

    again = await engagement_service.request_engagement(
        parties["client_id"], payload)
    assert again["status"] == EngagementStatus.REQUESTED.value


async def test_requesting_on_someone_elses_case_is_refused(parties):
    from app.db.collections import get_cases_col
    from app.services import engagement_service

    other = f"CB-ENG-OTHER-{parties['tag']}"
    await get_cases_col().insert_one({
        "_id": other, "client_id": "somebody-else", "lawyer_id": None,
        "case_number": f"ATT-2026-E{parties['tag'].upper()}",
        "case_type": "civil", "province": "punjab", "title": "Not yours",
        "description": "x", "status": CaseStatus.OPEN.value})

    with pytest.raises(ForbiddenError):
        await engagement_service.request_engagement(
            parties["client_id"],
            {"case_id": other, "lawyer_id": parties["lawyer_id"]})


async def test_requesting_on_an_assigned_case_is_refused(parties):
    from app.db.collections import get_cases_col
    from app.services import engagement_service

    case_id = await _a_case(parties)
    await get_cases_col().update_one(
        {"_id": case_id}, {"$set": {"lawyer_id": "someone"}})

    with pytest.raises(ConflictError, match="already has a lawyer"):
        await engagement_service.request_engagement(
            parties["client_id"],
            {"case_id": case_id, "lawyer_id": parties["lawyer_id"]})


# ── mark_no_show ─────────────────────────────────────────────────────────────
#
# Added alongside the lawyer-side UI for it. The endpoint, the service and the
# NO_SHOW status all existed and none of them had a test; the lawyer's page had
# no control to reach them and displayed `no_show` as "Cancelled". These pin the
# eligibility rule the UI now mirrors: CONFIRMED only, and only the appointment's
# own lawyer.
#
# A second rule joined them with the state machine: an appointment that has not
# STARTED cannot be a no-show, because the client has not yet failed to attend
# anything. Booking validates that the slot is in the future, so these tests
# reach a started appointment the only way the product can — by letting the
# clock pass it, which in a test means moving the row rather than waiting.


async def _observed_version(appt_id: str) -> int:
    """The schedule version a caller would have READ before acting.

    Exactly what the lawyer's page does: load the row, then accept the version
    it displayed. Read explicitly here because the service refuses to guess one
    — a default inside `confirm_appointment` would pin every write to whatever
    the row says on arrival, which is the unconditional write the version
    exists to prevent.
    """
    from app.db.collections import get_appointments_col

    row = await get_appointments_col().find_one({"_id": appt_id})
    return (row or {}).get("schedule_version", 0)


async def _confirm(appt_id: str, lawyer_id: str, version=None):
    """Confirm at the observed version, or at one the test names deliberately."""
    from app.services import appointment_service

    if version is None:
        version = await _observed_version(appt_id)
    return await appointment_service.confirm_appointment(
        appt_id, lawyer_id, expected_version=version)


async def _start_now(appt_id: str) -> None:
    """Move a booked appointment's window to one that has just begun.

    Written against the stored row on purpose. Every route into the service
    refuses a past `scheduled_at`, so there is no legitimate API call that
    produces this state — only elapsed time does, and a test cannot wait for it.
    """
    from app.db.collections import get_appointments_col

    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    await get_appointments_col().update_one(
        {"_id": appt_id},
        {"$set": {"scheduled_at": started, "end_at": started + timedelta(minutes=30)}},
    )


async def test_a_confirmed_appointment_that_has_started_can_be_marked_no_show(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _confirm(appt["id"], parties["lawyer_id"])
    await _start_now(appt["id"])

    out = await appointment_service.mark_no_show(appt["id"], parties["lawyer_id"])

    assert out["status"] == AppointmentStatus.NO_SHOW.value


async def test_an_appointment_that_has_not_started_is_not_a_no_show_yet(parties):
    """422, not 409: nothing is stale, the lawyer is just early.

    The distinction is the caller's next move. A conflict means re-read and
    look again; this means the appointment is fine and the answer will change
    on its own once the time arrives.
    """
    from app.services import appointment_service

    appt = await _book(parties, _slot())  # 48 hours away
    await _confirm(appt["id"], parties["lawyer_id"])

    with pytest.raises(AppValidationError, match="has not started"):
        await appointment_service.mark_no_show(appt["id"], parties["lawyer_id"])


async def test_only_a_confirmed_appointment_can_be_marked_no_show(parties):
    """The rule the UI mirrors by offering the action on Upcoming rows only.

    Now a 409 rather than a 422. A pending appointment being marked no-show is
    a caller acting on a stale view — the lawyer never confirmed it, or someone
    else moved it — and re-reading is what resolves it.
    """
    from app.core.exceptions import ConflictError
    from app.services import appointment_service

    appt = await _book(parties, _slot())  # still PENDING
    await _start_now(appt["id"])          # and the status rule still decides

    with pytest.raises(ConflictError, match="pending"):
        await appointment_service.mark_no_show(appt["id"], parties["lawyer_id"])


async def test_another_lawyer_cannot_mark_a_no_show(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _confirm(appt["id"], parties["lawyer_id"])

    with pytest.raises(ForbiddenError):
        await appointment_service.mark_no_show(appt["id"], "some-other-lawyer")


async def test_a_no_show_is_not_a_cancellation(parties):
    """They are different states, and the stored value must say which. The
    lawyer's page used to render both as "Cancelled", which told a lawyer their
    client had called off when in fact the client had not turned up."""
    from app.db.collections import get_appointments_col
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _confirm(appt["id"], parties["lawyer_id"])
    await _start_now(appt["id"])
    await appointment_service.mark_no_show(appt["id"], parties["lawyer_id"])

    stored = await get_appointments_col().find_one({"_id": appt["id"]})
    assert stored["status"] == AppointmentStatus.NO_SHOW.value
    assert stored["status"] != AppointmentStatus.CANCELLED.value
