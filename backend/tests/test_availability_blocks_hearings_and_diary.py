"""A client is not offered, and cannot book, an hour the lawyer is busy.

WHAT WAS WRONG. Bookable slots subtracted only other appointments. A lawyer
with a court hearing at 10:00, or a meeting they had put in their own diary,
was still offered to clients at that hour, and the booking went through.

Now: an upcoming hearing on one of the lawyer's open cases holds three hours
from its listed time (the whole day when no time is listed); a diary entry
holds exactly its own length. A hearing with an outcome, one on a closed case,
or one on another lawyer's case holds nothing.
"""
import secrets
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.constants import AppointmentMode
from app.core.exceptions import AppValidationError
from app.services import lawyer_availability as policy
from app.services import lawyer_availability_service as svc

pytestmark = pytest.mark.integration


@pytest.fixture
async def world(app_indexes):
    from app.core.config import settings
    from app.db.collections import (
        get_appointments_col,
        get_cases_col,
        get_lawyer_availability_col,
        get_lawyer_events_col,
        get_users_col,
    )

    tag = secrets.token_hex(4)
    lawyer, other, client = f"BH-L-{tag}", f"BH-L2-{tag}", f"BH-C-{tag}"
    now = datetime.now(timezone.utc)
    profile = {"specializations": ["civil"], "kyc_verified": True, "rating": 4.0,
               "total_reviews": 0, "availability": True, "experience_years": 5}
    await get_users_col().insert_many([
        {"_id": lawyer, "role": "lawyer", "is_active": True, "email": f"{lawyer}@test.invalid",
         "full_name": "Adv Busy", "created_at": now, "lawyer_profile": profile},
        {"_id": other, "role": "lawyer", "is_active": True, "email": f"{other}@test.invalid",
         "full_name": "Adv Other", "created_at": now, "lawyer_profile": profile},
        {"_id": client, "role": "client", "is_active": True, "email": f"{client}@test.invalid",
         "full_name": "Client", "created_at": now},
    ])
    await svc.replace_own(actor_id=lawyer, actor_role="lawyer", lawyer_id=lawyer,
                          working_hours=[{"weekday": 1, "start": "09:00", "end": "17:00"}],
                          exceptions=[])
    original = settings.appointment_working_hours_enforced
    yield {"lawyer": lawyer, "other": other, "client": client, "tag": tag}
    settings.appointment_working_hours_enforced = original
    await get_users_col().delete_many({"_id": {"$in": [lawyer, other, client]}})
    await get_lawyer_availability_col().delete_many({"_id": {"$in": [lawyer, other]}})
    await get_appointments_col().delete_many({"lawyer_id": lawyer})
    await get_cases_col().delete_many({"_id": {"$regex": f"^BH-{tag}"}})
    await get_lawyer_events_col().delete_many({"lawyer_id": lawyer})


def _tuesday() -> date:
    day = (datetime.now(policy.SCHEDULE_TZ) + timedelta(days=14)).date()
    return day + timedelta(days=(1 - day.weekday()) % 7)


def _pkt(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=policy.SCHEDULE_TZ).astimezone(timezone.utc)


async def _case(world, suffix, *, lawyer=None, status="in_progress", hearings=()):
    from app.db.collections import get_cases_col

    await get_cases_col().insert_one({
        "_id": f"BH-{world['tag']}-{suffix}", "lawyer_id": lawyer or world["lawyer"],
        "client_id": world["client"], "title": "Case", "status": status,
        "hearing_dates": list(hearings), "created_at": datetime.now(timezone.utc),
    })


def _hearing(day: date, time: str | None, outcome=None):
    # Stored the way add_hearing stores it: the UTC midnight of the day.
    return {"_id": secrets.token_hex(4), "date": datetime(day.year, day.month, day.day, tzinfo=timezone.utc),
            "time": time, "court": "Civil Court", "outcome": outcome}


async def _times(world, day):
    result = await svc.bookable_slots(world["lawyer"], from_date=day)
    return [s["local_time"] for s in result["days"][0]["slots"]]


async def test_a_hearing_holds_three_hours_from_its_time(world):
    day = _tuesday()
    await _case(world, "a", hearings=[_hearing(day, "10:00")])
    times = await _times(world, day)
    assert "09:30" not in times, "an hour-long meeting at 09:30 runs into the hearing"
    for held in ("10:00", "11:00", "12:30"):
        assert held not in times
    assert "09:00" in times and "13:00" in times


async def test_a_hearing_without_a_time_holds_the_whole_day(world):
    day = _tuesday()
    await _case(world, "a", hearings=[_hearing(day, None)])
    assert await _times(world, day) == []


@pytest.mark.parametrize("variant", ["decided", "closed", "other_lawyer"])
async def test_hearings_that_do_not_bind_the_lawyer_hold_nothing(world, variant):
    day = _tuesday()
    if variant == "decided":
        await _case(world, "a", hearings=[_hearing(day, "10:00", outcome="adjourned")])
    elif variant == "closed":
        await _case(world, "a", status="closed", hearings=[_hearing(day, "10:00")])
    else:
        await _case(world, "a", lawyer=world["other"], hearings=[_hearing(day, "10:00")])
    assert "10:00" in await _times(world, day)


async def test_a_diary_entry_holds_exactly_its_length(world):
    from app.db.collections import get_lawyer_events_col

    day = _tuesday()
    await get_lawyer_events_col().insert_one({
        "_id": f"BH-EV-{world['tag']}", "lawyer_id": world["lawyer"], "kind": "meeting",
        "title": "Partner meeting", "starts_at": _pkt(day, 14, 0), "duration_minutes": 60,
    })
    times = await _times(world, day)
    assert "14:00" not in times and "14:30" not in times and "13:30" not in times
    assert "13:00" in times and "15:00" in times


async def test_with_enforcement_on_a_booking_over_a_hearing_is_refused(world):
    from app.core.config import settings
    from app.services import appointment_service

    settings.appointment_working_hours_enforced = True
    day = _tuesday()
    await _case(world, "a", hearings=[_hearing(day, "10:00")])
    with pytest.raises(AppValidationError, match="not available at that time"):
        await appointment_service.book_appointment(
            client_id=world["client"], lawyer_id=world["lawyer"], case_id=None,
            scheduled_at=_pkt(day, 11, 0), duration_minutes=60,
            mode=AppointmentMode.VIDEO, notes=None)
    made = await appointment_service.book_appointment(
        client_id=world["client"], lawyer_id=world["lawyer"], case_id=None,
        scheduled_at=_pkt(day, 15, 0), duration_minutes=60,
        mode=AppointmentMode.VIDEO, notes=None)
    assert made["id"]
