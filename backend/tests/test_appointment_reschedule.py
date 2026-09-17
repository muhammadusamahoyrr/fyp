"""Client rescheduling of PENDING requests, and the races it opens.

Phase 4B. Rescheduling is the first operation that changes an appointment's
TIME rather than its status, which makes it the first one the existing CAS
cannot protect on its own: every guard so far compares `status`, and a
reschedule leaves the status exactly where it was.

Two things follow, and both are tested here rather than reasoned about.

  1. The slot claim and the time must move TOGETHER. `occupied_slots` is what
     the unique indexes compare, so a row whose slots disagree with its
     `scheduled_at` is a row the overlap guarantee no longer covers — it claims
     hours it is not booked for and leaves its real hours free.

  2. Status is not enough to detect a stale write. A client who reschedules
     A -> B -> A ends at the time they started, so a filter comparing the time
     would accept a write composed two moves earlier. A counter cannot be
     fooled that way, which is why `schedule_version` exists.

The lawyer-side race is the one with teeth: confirming is agreeing to a
specific time, and the status stays PENDING while the client moves it. Without
the version pin, a lawyer's Accept lands on a time they never saw.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import AppointmentMode, AppointmentStatus
from app.core.exceptions import AppValidationError, ConflictError, ForbiddenError
from app.services import appointment_slots

pytestmark = pytest.mark.integration


@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import get_appointments_col, get_users_col

    tag = secrets.token_hex(4)
    lawyer_id, lawyer2_id = f"RS-L-{tag}", f"RS-L2-{tag}"
    client_id, client2_id = f"RS-C-{tag}", f"RS-C2-{tag}"
    admin_id = f"RS-A-{tag}"
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
        {"_id": admin_id, "role": "admin", "is_active": True,
         "email": f"{admin_id}@test.invalid", "full_name": "The Admin",
         "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "lawyer2_id": lawyer2_id,
           "client_id": client_id, "client2_id": client2_id,
           "admin_id": admin_id}
    await get_users_col().delete_many(
        {"_id": {"$in": [lawyer_id, lawyer2_id, client_id, client2_id, admin_id]}})
    await get_appointments_col().delete_many(
        {"client_id": {"$in": [client_id, client2_id]}})


def _slot(hours_ahead: int = 48, minute: int = 0) -> datetime:
    base = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return base.replace(minute=minute, second=0, microsecond=0)


async def _book(parties, when=None, **over):
    from app.services import appointment_service
    kwargs = {"client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
              "case_id": None, "scheduled_at": when or _slot(),
              "duration_minutes": 60, "mode": AppointmentMode.VIDEO, "notes": None}
    kwargs.update(over)
    return await appointment_service.book_appointment(**kwargs)


_UNSET = object()


async def _move(parties, appt_id, when, version=_UNSET, client_id=None):
    """Move an appointment, pinning a version.

    When no version is given the CURRENT one is read first and pinned — in a
    test that is an explicit choice, not the silent substitution the service
    refuses to make. Pass `version=None` to exercise that refusal.
    """
    from app.services import appointment_service

    if version is _UNSET:
        row = await _row(appt_id)
        version = (row or {}).get("schedule_version", 0)
    return await appointment_service.reschedule_appointment(
        appt_id=appt_id,
        client_id=client_id or parties["client_id"],
        scheduled_at=when,
        expected_version=version,
    )


async def _row(appt_id: str) -> dict:
    from app.db.collections import get_appointments_col
    return await get_appointments_col().find_one({"_id": appt_id})


# ── 1. The contract ──────────────────────────────────────────────────────────

async def test_a_pending_request_moves_to_a_new_time(parties):
    appt = await _book(parties, _slot())
    later = _slot(72)

    out = await _move(parties, appt["id"], later)

    assert out["scheduled_at"].replace(tzinfo=timezone.utc) == later
    assert out["status"] == AppointmentStatus.PENDING.value


async def test_only_the_time_changes(parties):
    """A reschedule that could also change the lawyer, the case, the mode or
    the duration would be a different booking wearing the same id — and the
    lawyer agreed to none of it."""
    appt = await _book(parties, _slot(), duration_minutes=90,
                       mode=AppointmentMode.PHONE)
    before = await _row(appt["id"])

    await _move(parties, appt["id"], _slot(72))
    after = await _row(appt["id"])

    for field in ("lawyer_id", "client_id", "case_id", "mode",
                  "duration_minutes", "notes"):
        assert after[field] == before[field], f"{field} changed"


async def test_the_slot_claim_moves_with_the_time(parties):
    """`occupied_slots` is what the unique indexes compare. A row whose slots
    disagree with its own `scheduled_at` claims hours it is not booked for and
    leaves its real hours free — it is outside the guarantee in both
    directions."""
    appt = await _book(parties, _slot(), duration_minutes=60)
    later = _slot(72)

    await _move(parties, appt["id"], later)
    row = await _row(appt["id"])

    expected = appointment_slots.occupied_slots(later, 60)
    assert sorted(s.replace(tzinfo=timezone.utc) for s in row["occupied_slots"]) == expected
    assert row["end_at"].replace(tzinfo=timezone.utc) == later + timedelta(minutes=60)


async def test_the_old_slot_is_released(parties):
    """Another client can take the time this one has left."""
    original = _slot()
    appt = await _book(parties, original)
    await _move(parties, appt["id"], _slot(72))

    taken = await _book(parties, original, client_id=parties["client2_id"])
    assert taken["status"] == AppointmentStatus.PENDING.value


async def test_the_version_advances_on_every_move(parties):
    appt = await _book(parties, _slot())
    assert (await _row(appt["id"]))["schedule_version"] == 0

    await _move(parties, appt["id"], _slot(72))
    assert (await _row(appt["id"]))["schedule_version"] == 1

    await _move(parties, appt["id"], _slot(96))
    assert (await _row(appt["id"]))["schedule_version"] == 2


# ── 2. What may not be rescheduled ───────────────────────────────────────────

async def test_a_confirmed_appointment_cannot_be_moved_unilaterally(parties):
    """A confirmed appointment is an agreement between two people. Letting one
    of them move it is not rescheduling, it is telling the other where to be."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"],
        expected_version=(await _row(appt["id"]))["schedule_version"])

    with pytest.raises(ConflictError, match="pending"):
        await _move(parties, appt["id"], _slot(72))


@pytest.mark.parametrize("terminal", ["cancelled", "completed", "no_show"])
async def test_a_terminal_appointment_cannot_be_moved(parties, terminal):
    from app.db.collections import get_appointments_col

    appt = await _book(parties, _slot())
    await get_appointments_col().update_one(
        {"_id": appt["id"]}, {"$set": {"status": terminal}})

    with pytest.raises(ConflictError):
        await _move(parties, appt["id"], _slot(72))


async def test_another_client_cannot_move_it_and_learns_nothing(parties):
    """The generic denial, unchanged: a stranger cannot tell a real appointment
    from an imaginary one."""
    appt = await _book(parties, _slot())

    with pytest.raises(ForbiddenError) as real:
        await _move(parties, appt["id"], _slot(72), client_id=parties["client2_id"])
    with pytest.raises(ForbiddenError) as imaginary:
        await _move(parties, "no-such-id", _slot(72), client_id=parties["client2_id"])

    assert real.value.detail == imaginary.value.detail
    assert real.value.status_code == 403


async def test_a_lawyer_cannot_reschedule(parties):
    """Not a route they have: `require_client` guards it. The service is asked
    directly here, because a future caller might not go through the route."""
    appt = await _book(parties, _slot())

    with pytest.raises(ForbiddenError):
        await _move(parties, appt["id"], _slot(72), client_id=parties["lawyer_id"])


# ── 3. Time rules ────────────────────────────────────────────────────────────

async def test_the_cutoff_applies_to_the_old_time(parties):
    """The lawyer has already been told to hold the ORIGINAL slot, and that is
    the commitment the two-hour rule protects. Checking the new time instead
    would let a client move a 4pm appointment at 3:55 by picking next week."""
    soon = (datetime.now(timezone.utc) + timedelta(minutes=90)).replace(
        minute=0, second=0, microsecond=0)
    appt = await _book(parties, soon)

    with pytest.raises(AppValidationError, match="hours before"):
        await _move(parties, appt["id"], _slot(96))


@pytest.mark.parametrize("minute", [15, 45])
async def test_a_misaligned_new_time_is_refused(parties, minute):
    appt = await _book(parties, _slot())

    with pytest.raises(AppValidationError, match="30-minute boundary"):
        await _move(parties, appt["id"], _slot(72, minute=minute))


async def test_a_naive_new_time_is_refused(parties):
    appt = await _book(parties, _slot())

    with pytest.raises(AppValidationError, match="UTC offset"):
        await _move(parties, appt["id"], _slot(72).replace(tzinfo=None))


async def test_a_past_new_time_is_refused(parties):
    appt = await _book(parties, _slot())
    past = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(
        minute=0, second=0, microsecond=0)

    with pytest.raises(AppValidationError, match="future"):
        await _move(parties, appt["id"], past)


async def test_nothing_is_written_when_the_new_time_is_refused(parties):
    appt = await _book(parties, _slot())
    before = await _row(appt["id"])

    with pytest.raises(AppValidationError):
        await _move(parties, appt["id"], _slot(72, minute=45))

    after = await _row(appt["id"])
    assert after["scheduled_at"] == before["scheduled_at"]
    assert after["occupied_slots"] == before["occupied_slots"]
    assert after.get("schedule_version") == before.get("schedule_version")


# ── 4. Overlap, still enforced by the index ──────────────────────────────────

async def test_moving_onto_a_taken_slot_is_refused(parties):
    """The unique index, not `has_conflict` — which this path never calls."""
    taken = _slot(72)
    await _book(parties, taken, client_id=parties["client2_id"])
    appt = await _book(parties, _slot())

    with pytest.raises(ConflictError, match="just been taken"):
        await _move(parties, appt["id"], taken)


async def test_moving_onto_your_own_other_appointment_is_refused(parties):
    """The client's own diary — the half `has_conflict` never checked."""
    other = _slot(72)
    await _book(parties, other, lawyer_id=parties["lawyer2_id"])
    appt = await _book(parties, _slot())

    with pytest.raises(ConflictError, match="already have an appointment"):
        await _move(parties, appt["id"], other)


async def test_a_clash_leaks_no_index_name_or_driver_text(parties):
    taken = _slot(72)
    await _book(parties, taken, client_id=parties["client2_id"])
    appt = await _book(parties, _slot())

    with pytest.raises(ConflictError) as exc:
        await _move(parties, appt["id"], taken)

    detail = str(exc.value.detail)
    for leak in ("uniq_appointment", "occupied_slots", "E11000", "dup key",
                 parties["client2_id"], parties["lawyer_id"]):
        assert leak not in detail, f"{leak!r} leaked"


async def test_a_failed_move_leaves_the_original_claim_intact(parties):
    """The row must not be left holding neither slot, or half of each."""
    taken = _slot(72)
    await _book(parties, taken, client_id=parties["client2_id"])
    original = _slot()
    appt = await _book(parties, original)
    before = await _row(appt["id"])

    with pytest.raises(ConflictError):
        await _move(parties, appt["id"], taken)

    after = await _row(appt["id"])
    assert after["occupied_slots"] == before["occupied_slots"]
    assert after["scheduled_at"] == before["scheduled_at"]
    assert after["schedule_version"] == before["schedule_version"], (
        "a refused move still burned a version")


# ── 5. The races ─────────────────────────────────────────────────────────────

async def test_two_reschedules_onto_the_same_slot_leave_one_winner(parties):
    """Two different clients, both moving onto the same free time."""
    target = _slot(72)
    mine = await _book(parties, _slot())
    theirs = await _book(parties, _slot(76), client_id=parties["client2_id"])

    results = await asyncio.gather(
        _move(parties, mine["id"], target),
        _move(parties, theirs["id"], target, client_id=parties["client2_id"]),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1, f"both moves landed on one slot: {results!r}"
    assert all(isinstance(e, (ConflictError, AppValidationError))
               for e in results if isinstance(e, Exception))


async def test_two_moves_of_the_same_appointment_leave_one_winner(parties):
    """Both composed against version 0; only one may apply."""
    appt = await _book(parties, _slot())

    results = await asyncio.gather(
        _move(parties, appt["id"], _slot(72), version=0),
        _move(parties, appt["id"], _slot(96), version=0),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1, f"both stale-pinned moves applied: {results!r}"
    row = await _row(appt["id"])
    assert row["schedule_version"] == 1, "two moves advanced the version twice"
    assert row["scheduled_at"].replace(tzinfo=timezone.utc) == \
        winners[0]["scheduled_at"].replace(tzinfo=timezone.utc)


async def test_a_reschedule_and_a_confirm_have_exactly_one_winner(parties):
    """The race with teeth.

    Confirming is agreeing to a TIME. The status stays PENDING while the client
    moves it, so the status filter alone would let the lawyer's Accept land on
    a time they never saw.
    """
    from app.services import appointment_service

    appt = await _book(parties, _slot())

    results = await asyncio.gather(
        _move(parties, appt["id"], _slot(96), version=0),
        appointment_service.confirm_appointment(
            appt["id"], parties["lawyer_id"], expected_version=0),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1, f"both the move and the confirm applied: {results!r}"

    row = await _row(appt["id"])
    if row["status"] == AppointmentStatus.CONFIRMED.value:
        # The lawyer won: the time they agreed to is the one they saw.
        assert row["scheduled_at"].replace(tzinfo=timezone.utc) == _slot()
    else:
        # The client won: still pending, at the new time, version advanced.
        assert row["status"] == AppointmentStatus.PENDING.value
        assert row["schedule_version"] == 1


async def test_a_confirm_pinned_to_an_old_schedule_is_refused_and_says_why(parties):
    """Sequential, so the message is deterministic. "A pending appointment
    cannot be confirmed" would be both false and baffling."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _move(parties, appt["id"], _slot(96), version=0)

    with pytest.raises(ConflictError, match="changed the time"):
        await appointment_service.confirm_appointment(
            appt["id"], parties["lawyer_id"], expected_version=0)

    assert (await _row(appt["id"]))["status"] == AppointmentStatus.PENDING.value


async def test_a_confirm_at_the_current_schedule_still_works(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _move(parties, appt["id"], _slot(96), version=0)

    out = await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"], expected_version=1)

    assert out["status"] == AppointmentStatus.CONFIRMED.value


async def test_a_stale_version_is_refused_even_when_the_time_matches(parties):
    """A -> B -> A.

    The appointment ends where it started, so a guard comparing `scheduled_at`
    would accept a write composed two moves ago. Only a counter can tell that
    anything happened in between.
    """
    a = _slot()
    b = _slot(96)
    appt = await _book(parties, a)

    await _move(parties, appt["id"], b, version=0)     # A -> B, version 1
    await _move(parties, appt["id"], a, version=1)     # B -> A, version 2

    row = await _row(appt["id"])
    assert row["scheduled_at"].replace(tzinfo=timezone.utc) == a
    assert row["schedule_version"] == 2

    # A write composed when the appointment was at A, version 0. The time it
    # would write is the time already stored.
    with pytest.raises(ConflictError, match="changed a moment ago"):
        await _move(parties, appt["id"], b, version=0)

    assert (await _row(appt["id"]))["schedule_version"] == 2


async def test_a_cancellation_racing_a_reschedule_leaves_one_winner(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot())

    results = await asyncio.gather(
        _move(parties, appt["id"], _slot(96), version=0),
        appointment_service.cancel_appointment(
            appt_id=appt["id"], user_id=parties["lawyer_id"],
            user_role="lawyer", reason="unavailable"),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) >= 1
    row = await _row(appt["id"])
    if row["status"] == AppointmentStatus.CANCELLED.value:
        # A cancelled row must not still be holding a slot claim from a move
        # that was refused.
        assert row["schedule_version"] in (0, 1)
    else:
        assert row["status"] == AppointmentStatus.PENDING.value


async def test_a_reschedule_after_cancellation_is_refused(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await appointment_service.cancel_appointment(
        appt_id=appt["id"], user_id=parties["client_id"],
        user_role="client", reason=None)

    with pytest.raises(ConflictError):
        await _move(parties, appt["id"], _slot(96))


# ── 6. Legacy rows and notifications ─────────────────────────────────────────

async def test_a_row_with_no_version_is_treated_as_version_zero(parties):
    """Rows booked before the field existed carry none. Read at the boundary
    rather than migrated — no backfill is needed to move an old appointment."""
    from app.db.collections import get_appointments_col

    appt = await _book(parties, _slot())
    await get_appointments_col().update_one(
        {"_id": appt["id"]}, {"$unset": {"schedule_version": ""}})

    out = await _move(parties, appt["id"], _slot(96))

    assert out["schedule_version"] == 1


async def test_the_lawyer_is_told_only_after_a_successful_move(parties):
    from app.db.collections import get_notifications_col

    appt = await _book(parties, _slot())
    await get_notifications_col().delete_many({"payload.appointment_id": appt["id"]})

    await _move(parties, appt["id"], _slot(96))

    told = await get_notifications_col().find(
        {"payload.appointment_id": appt["id"]}).to_list(length=10)
    assert [n["user_id"] for n in told] == [parties["lawyer_id"]]
    assert "moved their pending request" in told[0]["body"]


async def test_a_refused_move_notifies_nobody(parties):
    """A notification on a conflict tells a lawyer to rearrange their day for a
    change that did not happen."""
    from app.db.collections import get_notifications_col

    taken = _slot(72)
    await _book(parties, taken, client_id=parties["client2_id"])
    appt = await _book(parties, _slot())
    await get_notifications_col().delete_many({"payload.appointment_id": appt["id"]})

    with pytest.raises(ConflictError):
        await _move(parties, appt["id"], taken)

    assert await get_notifications_col().count_documents(
        {"payload.appointment_id": appt["id"]}) == 0


async def test_the_response_hides_the_internal_fields(parties):
    appt = await _book(parties, _slot())

    out = await _move(parties, appt["id"], _slot(96))

    for field in ("occupied_slots", "idempotency_key", "payload_fingerprint"):
        assert field not in out
    assert out["schedule_version"] == 1, "the client needs this to compose the next move"


def test_the_reschedule_route_is_rate_limited():
    from app.api.v1.routes import appointments as routes  # noqa: F401
    from app.core.rate_limit import limiter

    limits = getattr(limiter, "_route_limits", {})
    key = "app.api.v1.routes.appointments.reschedule_appointment"
    assert key in limits and limits[key]
    assert int(routes._LIMIT_RESCHEDULE.split("/")[0]) <= 15


# ── 7. The version contract, end to end ──────────────────────────────────────
#
# The pieces were each correct and the contract between them was not: the
# service pinned a version, the read boundary could return null for a legacy
# row, the request schema let the field be omitted, and the lawyer's page
# dropped it in its row mapping. Any one of those turns the pin back into an
# unconditional write.

async def test_a_legacy_row_is_exposed_as_version_zero(parties):
    """A caller that receives `null` has nothing to send back, so every legacy
    appointment would become unmovable the moment the version was required."""
    from app.db.collections import get_appointments_col
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await get_appointments_col().update_one(
        {"_id": appt["id"]}, {"$unset": {"schedule_version": ""}})

    fetched = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["client_id"], user_role="client")
    assert fetched["schedule_version"] == 0

    page = await appointment_service.list_appointments(
        user_id=parties["client_id"], user_role="client",
        status=None, page=1, page_size=10)
    assert all(i["schedule_version"] == 0 for i in page["items"])

    # And the stored row is untouched — defaulted at the boundary, not migrated.
    assert "schedule_version" not in await _row(appt["id"])


async def test_a_reschedule_without_a_version_is_refused(parties):
    """Substituting the current version would pin every write to whatever the
    row says when it arrives, which is no pin at all."""
    appt = await _book(parties, _slot())

    with pytest.raises(AppValidationError, match="schedule_version is required"):
        await _move(parties, appt["id"], _slot(96), version=None)

    assert (await _row(appt["id"]))["schedule_version"] == 0


def test_the_request_schemas_require_a_non_negative_version():
    from pydantic import ValidationError

    from app.schemas.appointment import (
        ConfirmAppointmentRequest,
        RescheduleAppointmentRequest,
    )

    with pytest.raises(ValidationError):
        RescheduleAppointmentRequest(scheduled_at=_slot(96))      # omitted
    with pytest.raises(ValidationError):
        RescheduleAppointmentRequest(scheduled_at=_slot(96), schedule_version=-1)
    with pytest.raises(ValidationError):
        ConfirmAppointmentRequest()                               # omitted
    with pytest.raises(ValidationError):
        ConfirmAppointmentRequest(schedule_version=-1)

    assert RescheduleAppointmentRequest(
        scheduled_at=_slot(96), schedule_version=0).schedule_version == 0
    assert ConfirmAppointmentRequest(schedule_version=0).schedule_version == 0


# ── 8. Over HTTP ─────────────────────────────────────────────────────────────
#
# The service-level races are covered above. This exercises the same contract
# through the routes, because the schema, the dependency and the status code
# are what a real client meets — and three of the four gaps this section pins
# lived in that layer rather than in the service.

@pytest.fixture
async def http(parties):
    """A client bound to the real app, with auth resolved to our two users."""
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import get_current_user, require_client, require_lawyer
    from app.main import app

    state = {"user": None}

    def _as(user_id, role):
        return {"_id": user_id, "role": role, "is_active": True}

    async def _current():
        return state["user"]

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[require_client] = _current
    app.dependency_overrides[require_lawyer] = _current

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
        yield {
            "client": c,
            "be_client": lambda: state.__setitem__(
                "user", _as(parties["client_id"], "client")),
            "be_lawyer": lambda: state.__setitem__(
                "user", _as(parties["lawyer_id"], "lawyer")),
        }
    app.dependency_overrides.clear()


async def test_http_a_stale_accept_is_refused_and_the_fresh_one_succeeds(http, parties):
    """The sequence the lawyer's page has to survive.

    The lawyer loads a pending request at version 0. The client moves it to
    version 1 while the page is open. Accept pinned to 0 must fail WITHOUT
    confirming, and the same Accept after a reload must succeed.
    """
    appt = await _book(parties, _slot())
    c = http["client"]

    # What the lawyer's page was showing.
    http["be_lawyer"]()
    listed = await c.get("/appointments")
    assert listed.status_code == 200
    shown = next(i for i in listed.json()["items"] if i["id"] == appt["id"])
    assert shown["schedule_version"] == 0
    assert shown["status"] == AppointmentStatus.PENDING.value

    # The client moves it underneath them.
    http["be_client"]()
    moved = await c.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"scheduled_at": _slot(96).isoformat(), "schedule_version": 0})
    assert moved.status_code == 200, moved.text
    assert moved.json()["schedule_version"] == 1

    # The stale Accept.
    http["be_lawyer"]()
    stale = await c.patch(f"/appointments/{appt['id']}/confirm",
                          json={"schedule_version": shown["schedule_version"]})
    assert stale.status_code == 409, stale.text
    assert "changed the time" in stale.json()["error"]
    assert (await _row(appt["id"]))["status"] == AppointmentStatus.PENDING.value, (
        "a stale Accept confirmed the appointment anyway")

    # Reload, then accept what is actually there.
    reloaded = await c.get(f"/appointments/{appt['id']}")
    assert reloaded.json()["schedule_version"] == 1
    fresh = await c.patch(f"/appointments/{appt['id']}/confirm",
                          json={"schedule_version": 1})
    assert fresh.status_code == 200, fresh.text
    assert (await _row(appt["id"]))["status"] == AppointmentStatus.CONFIRMED.value


async def test_http_an_omitted_version_is_a_422(http, parties):
    appt = await _book(parties, _slot())
    c = http["client"]

    http["be_lawyer"]()
    assert (await c.patch(f"/appointments/{appt['id']}/confirm",
                          json={})).status_code == 422

    http["be_client"]()
    assert (await c.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"scheduled_at": _slot(96).isoformat()})).status_code == 422

    # Neither refusal touched the row.
    row = await _row(appt["id"])
    assert row["status"] == AppointmentStatus.PENDING.value
    assert row["schedule_version"] == 0


async def test_http_a_negative_version_is_a_422(http, parties):
    appt = await _book(parties, _slot())
    c = http["client"]
    http["be_lawyer"]()

    resp = await c.patch(f"/appointments/{appt['id']}/confirm",
                         json={"schedule_version": -1})

    assert resp.status_code == 422


async def test_http_a_legacy_row_is_movable_without_a_migration(http, parties):
    """Version 0 at the read boundary and `version_filter(0)` in the CAS have to
    agree, or a legacy appointment is readable and unchangeable."""
    from app.db.collections import get_appointments_col

    appt = await _book(parties, _slot())
    await get_appointments_col().update_one(
        {"_id": appt["id"]}, {"$unset": {"schedule_version": ""}})

    c = http["client"]
    http["be_client"]()
    shown = await c.get(f"/appointments/{appt['id']}")
    assert shown.json()["schedule_version"] == 0

    moved = await c.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"scheduled_at": _slot(96).isoformat(),
              "schedule_version": shown.json()["schedule_version"]})

    assert moved.status_code == 200, moved.text
    assert moved.json()["schedule_version"] == 1


# ── 9. The internal bypass, closed ───────────────────────────────────────────
#
# `expected_version` was optional so existing callers kept working, which left
# the guarantee resting on ONE route remembering to pass it. Any internal
# caller — a script, an admin tool, a scheduler — could confirm unversioned and
# silently get the pre-4B behaviour back. The default was the bypass, not a
# convenience.

def test_the_service_will_not_confirm_without_an_observed_version():
    """A missing version is a programming error, caught at the call.

    Asserted on the SIGNATURE as well as the call, because a default that came
    back would make the call succeed again and this test would still pass if it
    only checked for an exception.
    """
    import inspect

    from app.services.appointment_service import confirm_appointment

    parameter = inspect.signature(confirm_appointment).parameters["expected_version"]
    assert parameter.default is inspect.Parameter.empty, (
        "a default makes unversioned confirmation reachable again")
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (
        "a positional integer after two ids is the kind that gets passed in "
        "the wrong order and still type-checks")


async def test_omitting_the_version_raises_rather_than_confirming(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot())

    with pytest.raises(TypeError, match="expected_version"):
        await appointment_service.confirm_appointment(
            appt["id"], parties["lawyer_id"])

    assert (await _row(appt["id"]))["status"] == AppointmentStatus.PENDING.value


async def test_a_stale_direct_service_confirm_cannot_slip_past_the_route(parties):
    """THE REGRESSION.

    The public route is versioned, so this is the path that mattered: an
    internal caller holding a version it read before the client moved the
    appointment. It must lose exactly as the route does — the protection has to
    live in the service, not in the layer above it.
    """
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    observed = (await _row(appt["id"]))["schedule_version"]
    assert observed == 0

    # The client moves it while the internal caller holds `observed`.
    await _move(parties, appt["id"], _slot(96), version=observed)

    with pytest.raises(ConflictError, match="changed the time"):
        await appointment_service.confirm_appointment(
            appt["id"], parties["lawyer_id"], expected_version=observed)

    row = await _row(appt["id"])
    assert row["status"] == AppointmentStatus.PENDING.value, (
        "a stale direct service call confirmed the appointment")
    assert row["schedule_version"] == 1


async def test_the_same_caller_succeeds_once_it_re_reads(parties):
    """The other half: the guard refuses staleness, not the caller."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _move(parties, appt["id"], _slot(96), version=0)

    fresh = (await _row(appt["id"]))["schedule_version"]
    out = await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"], expected_version=fresh)

    assert out["status"] == AppointmentStatus.CONFIRMED.value


def test_no_production_caller_omits_the_version():
    """Greps the application package, not the tests.

    A signature can be relaxed again in one line, and the failure is silent:
    everything keeps working and the guarantee quietly stops applying. This
    fails if any `app/` caller ever confirms without naming a version.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"confirm_appointment\s*\(", text):
            # The call's argument list, up to the matching close paren.
            tail = text[match.end():match.end() + 400]
            if "def confirm_appointment" in text[max(0, match.start() - 10):match.start() + 1]:
                continue
            head = tail.split(")")[0]
            if "expected_version" not in head and "await" in text[max(0, match.start() - 40):match.start()]:
                offenders.append(f"{path.name}: ...{head.strip()[:80]}")

    assert not offenders, (
        "these application callers confirm without a version: " + "; ".join(offenders))


# ── 11. The joining link ─────────────────────────────────────────────────────
#
# The link was accepted only at COMPLETION — after the consultation. A join
# link that arrives once the call is over is not a join link. It now belongs at
# confirmation, with a separate route for a lawyer who did not have the room
# yet, and completion no longer erases it.

LINK = "https://meet.example.com/room/abc-def"
OTHER_LINK = "https://meet.example.com/room/second"


async def _confirm_with_link(parties, appt_id, link=None):
    from app.services import appointment_service

    row = await _row(appt_id)
    return await appointment_service.confirm_appointment(
        appt_id, parties["lawyer_id"],
        expected_version=row["schedule_version"],
        meeting_link=link)


async def test_a_lawyer_supplies_the_link_when_confirming(parties):
    appt = await _book(parties, _slot())

    out = await _confirm_with_link(parties, appt["id"], LINK)

    assert out["status"] == AppointmentStatus.CONFIRMED.value
    assert out["meeting_link"] == LINK
    assert (await _row(appt["id"]))["meeting_link"] == LINK


async def test_confirming_without_a_link_leaves_it_unset(parties):
    """A lawyer may not have the room yet. That is not an error."""
    appt = await _book(parties, _slot())

    out = await _confirm_with_link(parties, appt["id"], None)

    assert out["status"] == AppointmentStatus.CONFIRMED.value
    assert out.get("meeting_link") is None


@pytest.mark.parametrize("bad", [
    "javascript:alert(document.cookie)",
    "JavaScript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "http://meet.example.com/room",
    "https:no-host",
    "not a url",
])
def test_an_unsafe_link_is_refused_at_every_entry_point(bad):
    """The client renders this into an `href`, so it is clicked, not read. All
    three requests share one validator — separate ones are how a link refused
    at confirmation is accepted at completion."""
    from pydantic import ValidationError

    from app.schemas.appointment import (
        CompleteAppointmentRequest,
        ConfirmAppointmentRequest,
        SetMeetingLinkRequest,
    )

    with pytest.raises(ValidationError):
        ConfirmAppointmentRequest(schedule_version=0, meeting_link=bad)
    with pytest.raises(ValidationError):
        CompleteAppointmentRequest(meeting_link=bad)
    with pytest.raises(ValidationError):
        SetMeetingLinkRequest(meeting_link=bad)


# ── the separate way to supply one ───────────────────────────────────────────

async def test_a_lawyer_can_add_a_link_after_confirming(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _confirm_with_link(parties, appt["id"], None)

    out = await appointment_service.set_meeting_link(
        appt["id"], parties["lawyer_id"], LINK)

    assert out["meeting_link"] == LINK
    assert out["status"] == AppointmentStatus.CONFIRMED.value


async def test_a_link_can_be_added_before_confirmation(parties):
    """A lawyer who has the room before they accept should not have to wait."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())

    out = await appointment_service.set_meeting_link(
        appt["id"], parties["lawyer_id"], LINK)

    assert out["meeting_link"] == LINK
    assert out["status"] == AppointmentStatus.PENDING.value


async def test_a_link_can_be_replaced(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _confirm_with_link(parties, appt["id"], LINK)

    out = await appointment_service.set_meeting_link(
        appt["id"], parties["lawyer_id"], OTHER_LINK)

    assert out["meeting_link"] == OTHER_LINK


async def test_only_the_appointments_own_lawyer_may_set_the_link(parties):
    """The existing access rule, unchanged — and it must not leak whether the
    appointment exists."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())

    with pytest.raises(ForbiddenError) as real:
        await appointment_service.set_meeting_link(
            appt["id"], "some-other-lawyer", LINK)
    with pytest.raises(ForbiddenError) as imaginary:
        await appointment_service.set_meeting_link(
            "no-such-appointment", "some-other-lawyer", LINK)

    assert real.value.detail == imaginary.value.detail
    assert (await _row(appt["id"])).get("meeting_link") is None


async def test_a_client_cannot_set_the_link(parties):
    """`require_lawyer` guards the route; the service is asked directly here
    because a future caller might not go through it."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())

    with pytest.raises(ForbiddenError):
        await appointment_service.set_meeting_link(
            appt["id"], parties["client_id"], LINK)


@pytest.mark.parametrize("terminal", ["cancelled", "completed", "no_show"])
async def test_a_terminal_appointment_will_not_take_a_new_link(parties, terminal):
    """A completed consultation's link is a record of where it happened, and a
    cancelled one has nowhere to join."""
    from app.db.collections import get_appointments_col
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await get_appointments_col().update_one(
        {"_id": appt["id"]}, {"$set": {"status": terminal}})

    with pytest.raises(ConflictError, match="cannot be set"):
        await appointment_service.set_meeting_link(
            appt["id"], parties["lawyer_id"], LINK)


# ── completion must not erase it ─────────────────────────────────────────────

async def test_completing_without_a_link_preserves_the_stored_one(parties):
    """THE ERASURE BUG. Completion wrote `meeting_link` whatever it was given,
    so finishing a consultation without resending the link set it to None —
    destroying the record of where the consultation happened, at the moment
    that record became historical."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _confirm_with_link(parties, appt["id"], LINK)
    await _elapse_for_completion(appt["id"])

    out = await appointment_service.complete_appointment(
        appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
        lawyer_notes="Advised on filing", meeting_link=None)

    assert out["meeting_link"] == LINK, "completion erased the joining link"
    assert (await _row(appt["id"]))["meeting_link"] == LINK


async def test_completing_with_a_link_still_replaces_it(parties):
    """Preserving an absent value must not have made the field read-only."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _confirm_with_link(parties, appt["id"], LINK)
    await _elapse_for_completion(appt["id"])

    out = await appointment_service.complete_appointment(
        appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
        lawyer_notes=None, meeting_link=OTHER_LINK)

    assert out["meeting_link"] == OTHER_LINK


async def _elapse_for_completion(appt_id: str) -> None:
    from app.db.collections import get_appointments_col

    start = datetime.now(timezone.utc) - timedelta(minutes=120)
    await get_appointments_col().update_one(
        {"_id": appt_id},
        {"$set": {"scheduled_at": start, "end_at": start + timedelta(minutes=60)}})


# ── the link travels only through the normal access rules ────────────────────

async def test_the_client_on_the_appointment_sees_the_link(parties):
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _confirm_with_link(parties, appt["id"], LINK)

    seen = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["client_id"], user_role="client")

    assert seen["meeting_link"] == LINK


async def test_an_unrelated_client_cannot_read_the_link(parties):
    """The link IS the admission to the consultation, so it is protected by
    exactly the rule that protects the appointment."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    await _confirm_with_link(parties, appt["id"], LINK)

    with pytest.raises(ForbiddenError):
        await appointment_service.get_appointment(
            appt_id=appt["id"], user_id=parties["client2_id"], user_role="client")


async def test_phone_and_in_person_appointments_are_unchanged(parties):
    """Nothing here should have altered the other two modes."""
    from app.core.constants import AppointmentMode
    from app.services import appointment_service

    for mode, hours in ((AppointmentMode.PHONE, 60), (AppointmentMode.IN_PERSON, 64)):
        appt = await _book(parties, _slot(hours_ahead=hours), mode=mode)
        row = await _row(appt["id"])
        assert row["mode"] == mode.value
        assert row.get("meeting_link") is None

        out = await appointment_service.confirm_appointment(
            appt["id"], parties["lawyer_id"],
            expected_version=row["schedule_version"])
        assert out["status"] == AppointmentStatus.CONFIRMED.value
        assert out.get("meeting_link") is None


# ── 12. The three validation gaps ────────────────────────────────────────────

# --- blank input must not become a stored None ------------------------------

@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n  "])
def test_a_blank_link_is_refused_where_a_link_is_the_point(blank):
    """An "after" validator's return is NOT re-checked against the field type,
    so a whitespace-only body sailed through `meeting_link: str` and arrived at
    the service as None — which then stored nothing and told the client a
    joining link had been added."""
    from pydantic import ValidationError

    from app.schemas.appointment import SetMeetingLinkRequest

    with pytest.raises(ValidationError):
        SetMeetingLinkRequest(meeting_link=blank)


def test_the_set_link_request_never_yields_none():
    from app.schemas.appointment import SetMeetingLinkRequest

    assert SetMeetingLinkRequest(
        meeting_link="  https://meet.example.com/a  ").meeting_link == \
        "https://meet.example.com/a"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_still_means_no_link_where_that_is_allowed(blank):
    """Confirmation and completion may legitimately carry no link. Tightening
    the dedicated request must not have removed that."""
    from app.schemas.appointment import (
        CompleteAppointmentRequest,
        ConfirmAppointmentRequest,
    )

    assert ConfirmAppointmentRequest(
        schedule_version=0, meeting_link=blank).meeting_link is None
    assert CompleteAppointmentRequest(meeting_link=blank).meeting_link is None


async def test_the_service_never_stores_a_none_link(parties):
    """Belt and braces at the service: even called directly, an empty link must
    not overwrite the field or notify the client."""
    from app.db.collections import get_notifications_col
    from app.services import appointment_service

    appt = await _book(parties, _slot(), mode=AppointmentMode.VIDEO)
    await _confirm_with_link(parties, appt["id"], LINK)
    await get_notifications_col().delete_many({"payload.appointment_id": appt["id"]})

    with pytest.raises((AppValidationError, ConflictError, ValueError)):
        await appointment_service.set_meeting_link(
            appt["id"], parties["lawyer_id"], "   ")

    assert (await _row(appt["id"]))["meeting_link"] == LINK, "the link was cleared"
    assert await get_notifications_col().count_documents(
        {"payload.appointment_id": appt["id"]}) == 0, (
        "the client was told a link was added when none was saved")


# --- a real hostname, not merely a non-empty netloc -------------------------

def test_a_url_with_credentials_and_no_host_is_refused():
    """`urlparse("https://user@")` yields netloc "user@" and hostname None —
    all credentials and no host. The netloc test passed it, so a link leading
    nowhere was storable and would render as a dead anchor the client is told
    to click."""
    from pydantic import ValidationError

    from app.schemas.appointment import (
        ConfirmAppointmentRequest,
        SetMeetingLinkRequest,
    )

    for bad in ("https://user@", "https://user:pw@", "https://@"):
        with pytest.raises(ValidationError):
            SetMeetingLinkRequest(meeting_link=bad)
        with pytest.raises(ValidationError):
            ConfirmAppointmentRequest(schedule_version=0, meeting_link=bad)


def test_a_valid_https_url_with_credentials_still_works():
    """The control: a host IS present here, so it is a real destination."""
    from app.schemas.appointment import SetMeetingLinkRequest

    ok = "https://user@meet.example.com/room/abc"
    assert SetMeetingLinkRequest(meeting_link=ok).meeting_link == ok


def test_the_plain_valid_control_is_unaffected():
    from app.schemas.appointment import SetMeetingLinkRequest

    assert SetMeetingLinkRequest(
        meeting_link="https://meet.example.com/room/abc").meeting_link == \
        "https://meet.example.com/room/abc"


# --- a new link belongs to a video consultation only ------------------------

@pytest.mark.parametrize("mode", [AppointmentMode.PHONE, AppointmentMode.IN_PERSON])
async def test_a_non_video_appointment_refuses_a_new_link_at_confirmation(parties, mode):
    """A phone appointment's joining information is a number and an in-person
    one's is an address. Neither is a URL."""
    from app.services import appointment_service

    appt = await _book(parties, _slot(), mode=mode)
    row = await _row(appt["id"])

    with pytest.raises(AppValidationError, match="video consultation"):
        await appointment_service.confirm_appointment(
            appt["id"], parties["lawyer_id"],
            expected_version=row["schedule_version"], meeting_link=LINK)

    after = await _row(appt["id"])
    assert after["status"] == AppointmentStatus.PENDING.value, (
        "the confirmation applied despite the refused link")
    assert after.get("meeting_link") is None


@pytest.mark.parametrize("mode", [AppointmentMode.PHONE, AppointmentMode.IN_PERSON])
async def test_a_non_video_appointment_refuses_the_set_link_endpoint(parties, mode):
    from app.services import appointment_service

    appt = await _book(parties, _slot(), mode=mode)

    with pytest.raises(AppValidationError, match="video consultation"):
        await appointment_service.set_meeting_link(
            appt["id"], parties["lawyer_id"], LINK)

    assert (await _row(appt["id"])).get("meeting_link") is None


@pytest.mark.parametrize("mode", [AppointmentMode.PHONE, AppointmentMode.IN_PERSON])
async def test_a_non_video_appointment_refuses_a_link_at_completion(parties, mode):
    from app.services import appointment_service

    appt = await _book(parties, _slot(), mode=mode)
    row = await _row(appt["id"])
    await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"],
        expected_version=row["schedule_version"])
    await _elapse_for_completion(appt["id"])

    with pytest.raises(AppValidationError, match="video consultation"):
        await appointment_service.complete_appointment(
            appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
            lawyer_notes=None, meeting_link=LINK)

    after = await _row(appt["id"])
    assert after["status"] == AppointmentStatus.CONFIRMED.value, (
        "the completion applied despite the refused link")


@pytest.mark.parametrize("mode", [AppointmentMode.PHONE, AppointmentMode.IN_PERSON])
async def test_a_non_video_appointment_completes_normally_without_a_link(parties, mode):
    """The rule gates WRITING a link, not the other two modes themselves."""
    from app.services import appointment_service

    appt = await _book(parties, _slot(), mode=mode)
    row = await _row(appt["id"])
    await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"],
        expected_version=row["schedule_version"])
    await _elapse_for_completion(appt["id"])

    out = await appointment_service.complete_appointment(
        appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
        lawyer_notes="Spoke by phone", meeting_link=None)

    assert out["status"] == AppointmentStatus.COMPLETED.value


async def test_a_video_appointment_accepts_a_link_at_every_stage(parties):
    """The control, so the refusals above are not passing because everything
    is refused."""
    from app.services import appointment_service

    appt = await _book(parties, _slot(), mode=AppointmentMode.VIDEO)

    # set-link before confirmation
    pre = await appointment_service.set_meeting_link(
        appt["id"], parties["lawyer_id"], LINK)
    assert pre["meeting_link"] == LINK

    # and at confirmation
    row = await _row(appt["id"])
    confirmed = await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"],
        expected_version=row["schedule_version"], meeting_link=OTHER_LINK)
    assert confirmed["meeting_link"] == OTHER_LINK

    # and at completion
    await _elapse_for_completion(appt["id"])
    done = await appointment_service.complete_appointment(
        appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
        lawyer_notes=None, meeting_link=LINK)
    assert done["meeting_link"] == LINK


async def test_an_existing_link_on_a_non_video_row_is_left_alone(parties):
    """The rule gates writing a NEW link. Retroactively clearing one would
    destroy the record of where a consultation happened in order to enforce a
    rule that did not exist when it was written."""
    from app.db.collections import get_appointments_col
    from app.services import appointment_service

    appt = await _book(parties, _slot(), mode=AppointmentMode.PHONE)
    # A legacy row that acquired a link before the rule existed.
    await get_appointments_col().update_one(
        {"_id": appt["id"]}, {"$set": {"meeting_link": LINK}})
    row = await _row(appt["id"])

    await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"],
        expected_version=row["schedule_version"])

    assert (await _row(appt["id"]))["meeting_link"] == LINK
    seen = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["client_id"], user_role="client")
    assert seen["meeting_link"] == LINK


# ── 13. lawyer_notes is the lawyer's record, and nobody else's ───────────────
#
# It is documented as private and was returned to everyone. Every response goes
# through `_sanitize`, which stripped three internal fields and passed this one
# straight through — so a note written for the lawyer's file was readable by
# its subject through `GET /appointments/{id}` and through the list.
#
# `AppointmentOut` cannot be the filter: it DECLARES `lawyer_notes` and is
# `extra="allow"`. That is why these tests assert at the HTTP boundary as well
# as on the projection — the route is where a regression would actually surface.

PRIVATE_NOTE = "PRIVATE-NOTE-7f3a: client unreliable, consider declining future work"


async def _with_private_note(parties, mode=AppointmentMode.VIDEO):
    """A stored appointment carrying a distinctive private note."""
    from app.db.collections import get_appointments_col

    appt = await _book(parties, _slot(), mode=mode)
    await get_appointments_col().update_one(
        {"_id": appt["id"]}, {"$set": {"lawyer_notes": PRIVATE_NOTE}})
    return appt


def _assert_hidden(payload, where: str) -> None:
    assert PRIVATE_NOTE not in str(payload), f"the private note leaked via {where}"
    assert not payload.get("lawyer_notes"), (
        f"{where} returned a lawyer_notes value")


# --- the service projection -------------------------------------------------

async def test_the_client_never_receives_the_private_note_from_get(parties):
    from app.services import appointment_service

    appt = await _with_private_note(parties)

    seen = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["client_id"], user_role="client")

    _assert_hidden(seen, "get_appointment as client")


async def test_the_client_never_receives_it_from_the_list(parties):
    from app.services import appointment_service

    await _with_private_note(parties)

    page = await appointment_service.list_appointments(
        user_id=parties["client_id"], user_role="client",
        status=None, page=1, page_size=10)

    assert page["items"]
    for item in page["items"]:
        _assert_hidden(item, "list_appointments as client")


async def test_the_client_never_receives_it_from_a_cancellation(parties):
    """Not only get and list. Cancellation returns the row too."""
    from app.services import appointment_service

    appt = await _with_private_note(parties)

    out = await appointment_service.cancel_appointment(
        appt_id=appt["id"], user_id=parties["client_id"],
        user_role="client", reason=None)

    _assert_hidden(out, "cancel_appointment as client")


async def test_the_client_never_receives_it_from_a_reschedule(parties):
    from app.services import appointment_service

    appt = await _with_private_note(parties)
    row = await _row(appt["id"])

    out = await appointment_service.reschedule_appointment(
        appt_id=appt["id"], client_id=parties["client_id"],
        scheduled_at=_slot(96), expected_version=row["schedule_version"])

    _assert_hidden(out, "reschedule_appointment")


async def test_the_client_never_receives_it_from_an_idempotent_replay(parties):
    """The replay returns a row read straight back out of Mongo, so it is the
    path most likely to hand over the stored document verbatim."""
    from app.db.collections import get_appointments_col

    key = f"bk_{secrets.token_hex(8)}"
    when = _slot()
    first = await _book(parties, when, idempotency_key=key)
    await get_appointments_col().update_one(
        {"_id": first["id"]}, {"$set": {"lawyer_notes": PRIVATE_NOTE}})

    replay = await _book(parties, when, idempotency_key=key)

    assert replay["id"] == first["id"]
    _assert_hidden(replay, "the idempotent replay")


async def test_an_admin_does_not_receive_it(parties):
    """Hidden by default. `_actor_filter` grants an admin row ACCESS, not field
    access, and reading one into the other is how a privacy rule widens."""
    from app.services import appointment_service

    appt = await _with_private_note(parties)

    seen = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["admin_id"], user_role="admin")

    _assert_hidden(seen, "get_appointment as admin")


# --- the lawyer still has their own record ----------------------------------

async def test_the_assigned_lawyer_still_reads_the_note(parties):
    from app.services import appointment_service

    appt = await _with_private_note(parties)

    seen = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["lawyer_id"], user_role="lawyer")

    assert seen["lawyer_notes"] == PRIVATE_NOTE


async def test_the_lawyer_list_still_carries_the_note(parties):
    from app.services import appointment_service

    await _with_private_note(parties)

    page = await appointment_service.list_appointments(
        user_id=parties["lawyer_id"], user_role="lawyer",
        status=None, page=1, page_size=10)

    assert any(i.get("lawyer_notes") == PRIVATE_NOTE for i in page["items"])


async def test_the_lawyer_reads_it_back_after_writing_it(parties):
    """The note a lawyer just wrote at completion comes back to them."""
    from app.services import appointment_service

    appt = await _book(parties, _slot())
    row = await _row(appt["id"])
    await appointment_service.confirm_appointment(
        appt["id"], parties["lawyer_id"],
        expected_version=row["schedule_version"])
    await _elapse_for_completion(appt["id"])

    out = await appointment_service.complete_appointment(
        appt_id=appt["id"], lawyer_id=parties["lawyer_id"],
        lawyer_notes=PRIVATE_NOTE, meeting_link=None)

    assert out["lawyer_notes"] == PRIVATE_NOTE


async def test_the_stored_value_is_untouched(parties):
    """Hidden from a response, NOT deleted. It is the lawyer's file."""
    from app.services import appointment_service

    appt = await _with_private_note(parties)

    await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["client_id"], user_role="client")

    assert (await _row(appt["id"]))["lawyer_notes"] == PRIVATE_NOTE


def test_the_projection_fails_closed():
    """A new response path that forgets to think about the viewer must hide the
    field rather than expose it."""
    import inspect

    from app.services.appointment_service import _sanitize

    assert inspect.signature(_sanitize).parameters["for_lawyer"].default is False

    hidden = _sanitize({"_id": "a", "lawyer_notes": PRIVATE_NOTE})
    assert "lawyer_notes" not in hidden
    shown = _sanitize({"_id": "a", "lawyer_notes": PRIVATE_NOTE}, for_lawyer=True)
    assert shown["lawyer_notes"] == PRIVATE_NOTE


# --- and at the HTTP boundary ----------------------------------------------
#
# `AppointmentOut` declares `lawyer_notes` and allows extras, so the schema
# strips nothing. If the projection ever regresses, this is where it shows.

async def test_http_the_client_sees_no_private_note(http, parties):
    appt = await _with_private_note(parties)
    c = http["client"]

    http["be_client"]()
    single = await c.get(f"/appointments/{appt['id']}")
    listed = await c.get("/appointments")

    assert single.status_code == 200
    assert PRIVATE_NOTE not in single.text, "the note leaked through GET /{id}"
    assert not single.json().get("lawyer_notes")
    assert PRIVATE_NOTE not in listed.text, "the note leaked through the list"


async def test_http_the_lawyer_sees_their_own_note(http, parties):
    appt = await _with_private_note(parties)
    c = http["client"]

    http["be_lawyer"]()
    single = await c.get(f"/appointments/{appt['id']}")

    assert single.status_code == 200
    assert single.json()["lawyer_notes"] == PRIVATE_NOTE


async def test_http_a_client_cancellation_returns_no_note(http, parties):
    appt = await _with_private_note(parties)
    c = http["client"]

    http["be_client"]()
    resp = await c.patch(f"/appointments/{appt['id']}/cancel", json={})

    assert resp.status_code == 200
    assert PRIVATE_NOTE not in resp.text


async def test_http_a_client_reschedule_returns_no_note(http, parties):
    appt = await _with_private_note(parties)
    row = await _row(appt["id"])
    c = http["client"]

    http["be_client"]()
    resp = await c.patch(
        f"/appointments/{appt['id']}/reschedule",
        json={"scheduled_at": _slot(96).isoformat(),
              "schedule_version": row["schedule_version"]})

    assert resp.status_code == 200, resp.text
    assert PRIVATE_NOTE not in resp.text
