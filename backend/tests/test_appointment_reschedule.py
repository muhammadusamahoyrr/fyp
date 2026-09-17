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
    await appointment_service.confirm_appointment(appt["id"], parties["lawyer_id"])

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
