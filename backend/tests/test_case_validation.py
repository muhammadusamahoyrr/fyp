"""Cases module input validation (Phase B4).

WHAT WAS WRONG
  * A hearing time was any string ("10am", "25:00"); the availability service
    then failed to parse it and blocked the lawyer's WHOLE day for bookings.
  * A hearing could be CREATED already carrying an outcome ("decided"),
    skipping the outcome workflow, its client notice and its next date.
  * Messages, task titles and descriptions, hearing purposes and notes, and
    outcome notes had no length limit (an empty message was accepted), and a
    task priority could be any string.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


def _day(n: int) -> datetime:
    d = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return d + timedelta(days=n)


@pytest.fixture
async def case(app_indexes):
    from app.db.collections import get_cases_col, get_notifications_col

    tag = secrets.token_hex(4)
    ids = {"case": f"CV-C-{tag}", "lawyer": f"CV-L-{tag}", "client": f"CV-CL-{tag}"}
    await get_cases_col().insert_one({
        "_id": ids["case"], "case_number": f"ATT-2026-V{tag.upper()}", "title": "Rent dispute",
        "client_id": ids["client"], "lawyer_id": ids["lawyer"], "status": "in_progress",
        "case_type": "civil", "province": "punjab", "description": "x", "created_at": datetime.now(timezone.utc),
        "hearing_dates": [{"_id": "h-past", "date": _day(-2), "time": "10:00", "court": "Civil Court Lahore",
                           "purpose": "Arguments", "outcome": None}],
    })
    yield ids
    await get_cases_col().delete_one({"_id": ids["case"]})
    await get_notifications_col().delete_many({"user_id": ids["client"]})


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


def _as(user_id: str, role: str) -> AsyncClient:
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {"_id": user_id, "role": role, "full_name": "Tester"}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1")


def _hearing(**over):
    return {"date": _day(20).isoformat(), "court": "Civil Court Lahore", "purpose": "Evidence", "time": "11:00", **over}


# ── hearing time ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["00:00", "09:30", "12:00", "23:59"])
async def test_valid_24_hour_times_are_accepted(case, value):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.post(f"/cases/{case['case']}/hearings", json=_hearing(time=value))
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("value", ["24:00", "9:30", "10am", "12:60", "10:00:00", "noon"])
async def test_malformed_times_are_refused_readably(case, value):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.post(f"/cases/{case['case']}/hearings", json=_hearing(time=value))
        o = await c.patch(f"/cases/{case['case']}/hearings/h-past",
                          json={"outcome": "adjourned", "next_date": _day(30).isoformat(), "next_time": value})
    assert r.status_code == 422, r.text
    assert "24-hour" in r.text, "the refusal does not say what a valid time looks like"
    assert o.status_code == 422, o.text


async def test_no_time_is_still_allowed(case):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.post(f"/cases/{case['case']}/hearings", json=_hearing(time=None))
    assert r.status_code == 200, r.text


# ── outcomes only through the outcome route ──────────────────────────────────

@pytest.mark.parametrize("outcome", ["decided", "adjourned"])
async def test_a_hearing_cannot_be_created_with_an_outcome(case, outcome):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.post(f"/cases/{case['case']}/hearings", json=_hearing(outcome=outcome))
    assert r.status_code == 422, r.text
    assert "Record outcome" in r.text


# ── lengths ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field,limit", [("purpose", 300), ("notes", 2000), ("court", 200), ("judge", 120)])
async def test_hearing_text_limits(case, field, limit):
    async with _as(case["lawyer"], "lawyer") as c:
        ok = await c.post(f"/cases/{case['case']}/hearings", json=_hearing(**{field: "x" * limit}))
        over = await c.post(f"/cases/{case['case']}/hearings", json=_hearing(**{field: "x" * (limit + 1)}))
    assert ok.status_code == 200, ok.text
    assert over.status_code == 422, over.text


async def test_a_hearing_needs_a_court(case):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.post(f"/cases/{case['case']}/hearings", json=_hearing(court="   "))
    assert r.status_code == 422


@pytest.mark.parametrize("field,limit", [("note", 2000), ("next_purpose", 300)])
async def test_outcome_text_limits(case, field, limit):
    async with _as(case["lawyer"], "lawyer") as c:
        over = await c.patch(f"/cases/{case['case']}/hearings/h-past", json={"outcome": "adjourned", field: "x" * (limit + 1)})
        ok = await c.patch(f"/cases/{case['case']}/hearings/h-past", json={"outcome": "adjourned", field: "x" * limit})
    assert over.status_code == 422, over.text
    assert ok.status_code == 200, ok.text


@pytest.mark.parametrize("text,status", [("", 422), ("   ", 422), ("x" * 4000, 200), ("x" * 4001, 422)],
                         ids=["empty", "blank", "max", "max+1"])
async def test_message_text_limits(case, text, status):
    async with _as(case["client"], "client") as c:
        r = await c.post(f"/cases/{case['case']}/messages", json={"text": text})
    assert r.status_code == status, r.text


@pytest.mark.parametrize("body,status", [
    ({"title": "x" * 200}, 200), ({"title": "x" * 201}, 422), ({"title": "  "}, 422),
    ({"title": "File reply", "description": "x" * 2000}, 200), ({"title": "File reply", "description": "x" * 2001}, 422),
    ({"title": "File reply", "priority": "high"}, 200), ({"title": "File reply", "priority": "urgent"}, 422),
])
async def test_task_limits(case, body, status):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.post(f"/cases/{case['case']}/tasks", json=body)
    assert r.status_code == status, r.text


# ── a legacy malformed time never blocks a whole day ─────────────────────────

async def test_a_stored_malformed_time_blocks_the_morning_not_the_whole_day(app_indexes):
    from app.db.collections import get_cases_col, get_users_col
    from app.services import lawyer_availability as policy
    from app.services import lawyer_availability_service as svc

    tag = secrets.token_hex(4)
    lawyer = f"CV-AV-{tag}"
    await get_users_col().insert_one({"_id": lawyer, "role": "lawyer", "is_active": True, "email": f"{lawyer}@x.invalid",
                                      "lawyer_profile": {"kyc_verified": True}})
    day = (datetime.now(policy.SCHEDULE_TZ) + timedelta(days=14)).date()
    day = day + timedelta(days=(1 - day.weekday()) % 7)
    await svc.replace_own(actor_id=lawyer, actor_role="lawyer", lawyer_id=lawyer,
                          working_hours=[{"weekday": 1, "start": "09:00", "end": "17:00"}], exceptions=[])
    await get_cases_col().insert_one({"_id": f"CV-AVC-{tag}", "lawyer_id": lawyer, "client_id": "x", "status": "in_progress",
                                      "case_number": f"AV-{tag}", "title": "T",
                                      "hearing_dates": [{"_id": "h", "date": datetime(day.year, day.month, day.day),
                                                         "time": "10am", "outcome": None}]})
    try:
        result = await svc.bookable_slots(lawyer, from_date=day)
        times = [s["local_time"] for s in result["days"][0]["slots"]]
        assert times, "an unreadable stored time blocked the whole day"
        assert "14:00" in times
        assert "09:00" not in times and "11:00" not in times, "the court morning should still be held"
    finally:
        from app.db.collections import get_lawyer_availability_col
        await get_cases_col().delete_many({"_id": f"CV-AVC-{tag}"})
        await get_users_col().delete_many({"_id": lawyer})
        await get_lawyer_availability_col().delete_many({"_id": lawyer})
