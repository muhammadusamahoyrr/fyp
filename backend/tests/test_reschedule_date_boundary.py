"""A hearing can be rescheduled to today or later, on the PAKISTAN calendar.

WHAT WAS WRONG. The check was `new_date.date() < today_utc - 1 day`: it
accepted yesterday (the message says "from today onwards"), and it compared
UTC dates, so between 00:00 and 05:00 PKT — when Pakistan is already on the
next day — "yesterday" in Pakistan was two days back by the server's count.

The clock is pinned (no test here reads the real time), and the date the page
sends follows the app's convention: midnight UTC of the chosen day.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

_RealDatetime = datetime


def _frozen(at: datetime):
    """A `datetime` whose now() is `at`. Instances of the real datetime still
    pass isinstance() checks against it, so the module behaves normally."""
    class _Meta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, _RealDatetime)

    class Frozen(_RealDatetime, metaclass=_Meta):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz else at.astimezone(timezone.utc).replace(tzinfo=None)

    return Frozen


# 20:00 UTC on 10 Nov = 01:00 PKT on 11 Nov: inside the window where the two
# calendars disagree.
NIGHT = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
# 08:00 UTC on 10 Nov = 13:00 PKT, the same day on both calendars.
DAY = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
async def case(app_indexes):
    from app.db.collections import get_cases_col, get_notifications_col

    tag = secrets.token_hex(4)
    ids = {"case": f"RD-C-{tag}", "lawyer": f"RD-L-{tag}", "client": f"RD-CL-{tag}"}
    await get_cases_col().insert_one({
        "_id": ids["case"], "case_number": f"RD-{tag}", "title": "Rent dispute",
        "client_id": ids["client"], "lawyer_id": ids["lawyer"], "status": "in_progress",
        "case_type": "civil", "province": "punjab", "description": "x", "created_at": NIGHT,
        "hearing_dates": [{"_id": "h1", "date": datetime(2026, 11, 20), "time": "10:00",
                           "court": "Civil Court Lahore", "purpose": "Evidence", "outcome": None}],
    })
    yield ids
    await get_cases_col().delete_one({"_id": ids["case"]})
    await get_notifications_col().delete_many({"user_id": ids["client"]})


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


async def _move(ids, monkeypatch, now, date_value, time_value="11:00"):
    from app.dependencies import get_current_user
    from app.main import app
    from app.services import case_service

    monkeypatch.setattr(case_service, "datetime", _frozen(now))
    app.dependency_overrides[get_current_user] = lambda: {"_id": ids["lawyer"], "role": "lawyer"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1") as c:
        return await c.patch(f"/cases/{ids['case']}/hearings/h1/reschedule",
                             json={"date": date_value, "time": time_value})


# ── 00:00–05:00 PKT: Pakistan is already on the 11th, UTC still on the 10th ──

async def test_at_night_yesterday_in_pakistan_is_refused(case, monkeypatch):
    r = await _move(case, monkeypatch, NIGHT, "2026-11-10T00:00:00Z")
    assert r.status_code == 422, r.text
    assert "today onwards" in r.text


async def test_at_night_today_in_pakistan_is_accepted(case, monkeypatch):
    r = await _move(case, monkeypatch, NIGHT, "2026-11-11T00:00:00Z")
    assert r.status_code == 200, r.text


async def test_at_night_tomorrow_is_accepted(case, monkeypatch):
    r = await _move(case, monkeypatch, NIGHT, "2026-11-12T00:00:00Z")
    assert r.status_code == 200, r.text


# ── an offset-aware value is read on the Pakistan calendar ──────────────────

async def test_an_offset_aware_late_evening_yesterday_is_refused(case, monkeypatch):
    # 23:30 PKT on the 10th (18:30 UTC on the 10th): yesterday in Pakistan.
    r = await _move(case, monkeypatch, NIGHT, "2026-11-10T23:30:00+05:00")
    assert r.status_code == 422, r.text


async def test_an_offset_aware_early_morning_today_is_accepted(case, monkeypatch):
    # 00:30 PKT on the 11th is 19:30 UTC on the 10th: TODAY in Pakistan.
    r = await _move(case, monkeypatch, NIGHT, "2026-11-11T00:30:00+05:00")
    assert r.status_code == 200, r.text
    # Stored the way every reader expects a hearing day: midnight UTC of the
    # Pakistan date (not 19:30 UTC on the 10th, which reads as the 10th).
    h = next(x for x in r.json()["hearing_dates"] if x["_id"] == "h1")
    assert h["date"].startswith("2026-11-11T00:00:00"), h["date"]


# ── during the day, when both calendars agree ───────────────────────────────

async def test_by_day_yesterday_is_refused(case, monkeypatch):
    r = await _move(case, monkeypatch, DAY, "2026-11-09T00:00:00Z")
    assert r.status_code == 422, r.text


async def test_by_day_today_is_accepted(case, monkeypatch):
    r = await _move(case, monkeypatch, DAY, "2026-11-10T00:00:00Z")
    assert r.status_code == 200, r.text


# ── unchanged: moving to the same date and time is refused ──────────────────

async def test_the_same_date_and_time_is_still_refused(case, monkeypatch):
    r = await _move(case, monkeypatch, DAY, "2026-11-20T00:00:00Z", "10:00")
    assert r.status_code == 422, r.text
    assert "already" in r.text


# ── the helpers, without the app ────────────────────────────────────────────

def test_pkt_helpers_read_the_pakistan_calendar():
    from datetime import date

    from app.core.pkt import pkt_date, pkt_today

    assert pkt_today(NIGHT) == date(2026, 11, 11)
    assert pkt_today(DAY) == date(2026, 11, 10)
    assert pkt_date(datetime(2026, 11, 10)) == date(2026, 11, 10), "naive values are UTC (as Mongo returns them)"
    assert pkt_date(datetime(2026, 11, 10, 19, 30, tzinfo=timezone.utc)) == date(2026, 11, 11)
    assert pkt_date(datetime.fromisoformat("2026-11-10T23:30:00+05:00")) == date(2026, 11, 10)
