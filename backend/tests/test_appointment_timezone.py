"""The appointment flow's timezone contract.

Three defects are pinned here, and every one of them was live in production
while the appointment suite was green — because the paths that carry them had
no test at all.

  1. Motor decoded BSON dates NAIVE, so `scheduled_at` read back from Mongo
     could not be compared to an aware `now`. Client cancellation raised
     TypeError and answered 500 on every call; the two-hour cutoff it was
     enforcing had never once been evaluated.

  2. A `scheduled_at` with no UTC offset raised TypeError INSIDE a Pydantic
     validator. Pydantic v2 wraps ValueError into a 422 but lets TypeError
     escape, so an offsetless booking got a 500 rather than a validation error.

  3. Availability was computed over a UTC calendar day while the client picked a
     PAKISTAN one. In PKT that window is 05:00 to 05:00, so an appointment in
     the first five hours of the local day was reported as a free slot.

The reload tests deliberately go through Mongo rather than asserting on the
returned document. The bug only exists on the way BACK from the driver, so a
test that never reloads cannot see it.
"""
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.constants import AppointmentMode, AppointmentStatus
from app.core.exceptions import AppValidationError

pytestmark = pytest.mark.integration

PKT = ZoneInfo("Asia/Karachi")


@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import get_appointments_col, get_users_col

    tag = secrets.token_hex(4)
    lawyer_id, client_id = f"TZ-L-{tag}", f"TZ-C-{tag}"
    now = datetime.now(timezone.utc)
    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"tz-l-{tag}@test.invalid", "full_name": "Adv Timezone",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["criminal"], "kyc_verified": True,
                            "rating": 4.0, "total_reviews": 0,
                            "availability": True, "experience_years": 5}},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"tz-c-{tag}@test.invalid", "full_name": "Client Timezone",
         "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "client_id": client_id}
    await get_users_col().delete_many({"_id": {"$in": [lawyer_id, client_id]}})
    await get_appointments_col().delete_many({"client_id": client_id})


async def _book(parties, when, **over):
    from app.services import appointment_service
    kwargs = {"client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
              "case_id": None, "scheduled_at": when, "duration_minutes": 30,
              "mode": AppointmentMode.VIDEO, "notes": None}
    kwargs.update(over)
    return await appointment_service.book_appointment(**kwargs)


# ── 1. Mongo decoding ────────────────────────────────────────────────────────

async def test_a_stored_appointment_reads_back_timezone_aware(parties):
    """The root fix. Everything else in this file depends on it."""
    from app.db.collections import get_appointments_col

    when = (datetime.now(timezone.utc) + timedelta(days=2)).replace(
        minute=0, second=0, microsecond=0)
    appt = await _book(parties, when)

    stored = await get_appointments_col().find_one({"_id": appt["id"]})

    assert stored["scheduled_at"].tzinfo is not None, (
        "a naive read is the bug: it cannot be compared to an aware now()")
    assert stored["scheduled_at"].utcoffset() == timedelta(0)


async def test_a_reloaded_appointment_keeps_the_same_pakistan_clock_face(parties):
    """create → Mongo reload → identical PKT date and time.

    The lifecycle assertion. A client books 3 pm in Karachi; after a round trip
    through the driver it must still be 3 pm in Karachi, not 10 am and not a
    different day.
    """
    from app.db.collections import get_appointments_col

    chosen_local = (datetime.now(PKT) + timedelta(days=3)).replace(
        hour=15, minute=0, second=0, microsecond=0)
    appt = await _book(parties, chosen_local.astimezone(timezone.utc))

    stored = await get_appointments_col().find_one({"_id": appt["id"]})
    reloaded_local = stored["scheduled_at"].astimezone(PKT)

    assert reloaded_local.strftime("%Y-%m-%d %H:%M") == \
        chosen_local.strftime("%Y-%m-%d %H:%M")


# ── 2. The API boundary ──────────────────────────────────────────────────────

def test_a_timestamp_without_an_offset_is_refused_as_a_validation_error():
    """It must be a 422, and the distinction is not cosmetic.

    This raised TypeError, which Pydantic does NOT convert — so the caller got a
    500. A 500 says the server broke; a 422 says the request was not specific
    enough, which is the truth and is something a client can act on.
    """
    from pydantic import ValidationError
    from app.schemas.appointment import BookAppointmentRequest

    for offsetless in ("2027-01-01T10:00:00", "2027-01-01 10:00:00"):
        with pytest.raises(ValidationError) as caught:
            BookAppointmentRequest(lawyer_id="L", scheduled_at=offsetless)
        assert "offset" in str(caught.value).lower()


def test_an_offset_timestamp_is_accepted_and_normalised_to_utc():
    """+05:00 and its UTC equivalent are the same instant and must both work."""
    from app.schemas.appointment import BookAppointmentRequest

    local = BookAppointmentRequest(
        lawyer_id="L", scheduled_at="2027-01-01T15:00:00+05:00")
    utc = BookAppointmentRequest(
        lawyer_id="L", scheduled_at="2027-01-01T10:00:00Z")

    assert local.scheduled_at == utc.scheduled_at
    assert local.scheduled_at.utcoffset() == timedelta(0)


def test_a_past_timestamp_is_still_refused():
    """The rule that already existed must survive the new one in front of it."""
    from pydantic import ValidationError
    from app.schemas.appointment import BookAppointmentRequest

    with pytest.raises(ValidationError, match="future"):
        BookAppointmentRequest(lawyer_id="L", scheduled_at="2020-01-01T10:00:00Z")


# ── 3. Client cancellation ───────────────────────────────────────────────────

async def test_a_client_can_cancel_outside_the_cutoff(parties):
    """This is the call that answered 500 for every client, every time."""
    from app.services import appointment_service

    when = datetime.now(timezone.utc) + timedelta(days=2)
    appt = await _book(parties, when.replace(minute=0, second=0, microsecond=0))

    out = await appointment_service.cancel_appointment(
        appt_id=appt["id"], user_id=parties["client_id"],
        user_role="client", reason="Conflict at work")

    assert out["status"] == AppointmentStatus.CANCELLED.value
    assert out["cancelled_by"] == "client"


async def test_a_client_cannot_cancel_inside_the_cutoff(parties):
    """The cutoff is now actually evaluated rather than raising before it."""
    from app.services import appointment_service

    soon = datetime.now(timezone.utc) + timedelta(minutes=30)
    appt = await _book(parties, soon)

    with pytest.raises(AppValidationError, match="2 hours"):
        await appointment_service.cancel_appointment(
            appt_id=appt["id"], user_id=parties["client_id"],
            user_role="client", reason=None)


async def test_a_lawyer_may_still_cancel_inside_the_cutoff(parties):
    """The cutoff binds the client only — a lawyer with an emergency is not
    trapped into attending."""
    from app.services import appointment_service

    soon = datetime.now(timezone.utc) + timedelta(minutes=30)
    appt = await _book(parties, soon)

    out = await appointment_service.cancel_appointment(
        appt_id=appt["id"], user_id=parties["lawyer_id"],
        user_role="lawyer", reason="Court ran over")

    assert out["status"] == AppointmentStatus.CANCELLED.value


# ── 4. Availability is a Pakistan day ────────────────────────────────────────

async def test_an_early_morning_pkt_booking_shows_on_its_own_local_day(parties):
    """The window bug, stated as the client meets it.

    02:00 PKT is 21:00 UTC the PREVIOUS day. Under a UTC window the slot was
    absent from its own local date and the grid offered it as free; the booking
    check then refused it, which reads as a broken product.
    """
    from app.services import appointment_service

    local = (datetime.now(PKT) + timedelta(days=4)).replace(
        hour=2, minute=0, second=0, microsecond=0)
    await _book(parties, local.astimezone(timezone.utc))

    result = await appointment_service.get_availability(
        parties["lawyer_id"], local.strftime("%Y-%m-%d"))

    assert len(result["booked_slots"]) == 1, (
        "the 00:00-05:00 PKT band fell outside a UTC-shaped day")
    assert result["booked_slots"][0]["start"].endswith("Z")


async def test_a_late_evening_pkt_booking_is_not_pulled_into_the_next_day(parties):
    """The other edge. 23:00 PKT is 18:00 UTC the same day, so a UTC window
    happened to get this one right — it must stay right."""
    from app.services import appointment_service

    local = (datetime.now(PKT) + timedelta(days=5)).replace(
        hour=23, minute=0, second=0, microsecond=0)
    await _book(parties, local.astimezone(timezone.utc))

    same_day = await appointment_service.get_availability(
        parties["lawyer_id"], local.strftime("%Y-%m-%d"))
    next_day = await appointment_service.get_availability(
        parties["lawyer_id"], (local + timedelta(days=1)).strftime("%Y-%m-%d"))

    assert len(same_day["booked_slots"]) == 1
    assert next_day["booked_slots"] == []


# ── 5. What a human is told ──────────────────────────────────────────────────

async def test_a_notification_names_the_time_in_pakistan_time(parties):
    """A Pakistani client typing 3 pm was told 10:00 UTC — a correct instant,
    named in a zone nobody in this product thinks in."""
    from app.db.collections import get_notifications_col

    local = (datetime.now(PKT) + timedelta(days=6)).replace(
        hour=15, minute=0, second=0, microsecond=0)
    await _book(parties, local.astimezone(timezone.utc))

    note = await get_notifications_col().find_one({"user_id": parties["client_id"]})

    assert "15:00 PKT" in note["body"]
    assert "UTC" not in note["body"]
    await get_notifications_col().delete_many({"user_id": parties["client_id"]})


# ── 6. The timezone data contract ────────────────────────────────────────────

async def test_a_new_appointment_records_the_zone_it_was_booked_in(parties):
    """`scheduled_at` is an instant and says nothing about the clock face the
    client read. Without the zone stored beside it, rendering an old
    appointment after the booking zone ever changes would silently reinterpret
    it in the new one."""
    from app.db.collections import get_appointments_col

    appt = await _book(parties, datetime.now(timezone.utc) + timedelta(days=2))

    assert appt["timezone"] == "Asia/Karachi"
    stored = await get_appointments_col().find_one({"_id": appt["id"]})
    assert stored["timezone"] == "Asia/Karachi", "it must be PERSISTED, not just returned"


async def test_a_legacy_row_reads_as_karachi_without_being_rewritten(parties):
    """Rows booked before the field existed carry no zone. They are defaulted at
    the READ boundary, so no production backfill is needed merely to read them —
    and the stored document is left exactly as it was, so a later backfill can
    still find the true set of rows that never had it."""
    from app.db.collections import get_appointments_col
    from app.services import appointment_service

    appt = await _book(parties, datetime.now(timezone.utc) + timedelta(days=2))
    await get_appointments_col().update_one(
        {"_id": appt["id"]}, {"$unset": {"timezone": ""}})

    out = await appointment_service.get_appointment(
        appt_id=appt["id"], user_id=parties["client_id"], user_role="client")

    assert out["timezone"] == "Asia/Karachi"

    still_legacy = await get_appointments_col().find_one({"_id": appt["id"]})
    assert "timezone" not in still_legacy, (
        "the read boundary must not write back — that would destroy the "
        "evidence of which rows predate the field")


async def test_the_zone_survives_listing_too(parties):
    """The list path sanitises separately from the single-fetch path, so it gets
    its own assertion rather than inheriting one."""
    from app.services import appointment_service

    await _book(parties, datetime.now(timezone.utc) + timedelta(days=2))

    page = await appointment_service.list_appointments(
        user_id=parties["client_id"], user_role="client",
        status=None, page=1, page_size=10)

    assert page["items"], "the booking should be listed"
    assert all(i["timezone"] == "Asia/Karachi" for i in page["items"])
