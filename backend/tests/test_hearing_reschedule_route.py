"""PATCH /cases/{id}/hearings/{hid}/reschedule, over HTTP.

Courts move dates (judge on leave, strike, a cause-list change). The only way
to change a hearing date was to record a fake outcome, which told the client
something happened that did not. Rescheduling moves an UPCOMING hearing, keeps
the old date on the hearing's history, and tells the client.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

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
    ids = {"case": f"RS-C-{tag}", "lawyer": f"RS-L-{tag}", "other": f"RS-O-{tag}", "client": f"RS-CL-{tag}"}
    await get_cases_col().insert_one({
        "_id": ids["case"], "title": "Rent dispute", "client_id": ids["client"], "lawyer_id": ids["lawyer"],
        "status": "in_progress", "case_type": "civil", "province": "punjab", "description": "x",
        "created_at": datetime.now(timezone.utc),
        "hearing_dates": [
            {"_id": "h-up", "date": _day(10), "time": "10:00", "court": "Civil Court Lahore", "purpose": "Framing of issues", "outcome": None},
            {"_id": "h-done", "date": _day(-5), "time": "10:00", "court": "Civil Court Lahore", "purpose": "Issues", "outcome": "adjourned"},
        ],
    })
    yield ids
    await get_cases_col().delete_one({"_id": ids["case"]})
    await get_notifications_col().delete_many({"user_id": ids["client"]})


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


def _as_lawyer(user_id: str) -> AsyncClient:
    from app.dependencies import get_current_user, require_lawyer
    from app.main import app

    who = {"_id": user_id, "role": "lawyer"}
    app.dependency_overrides[get_current_user] = lambda: who
    app.dependency_overrides[require_lawyer] = lambda: who
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1")


def _url(case):
    return f"/cases/{case['case']}/hearings/h-up/reschedule"


async def test_the_assigned_lawyer_moves_a_hearing_and_the_old_date_is_kept(case):
    from app.db.collections import get_cases_col, get_notifications_col

    new = _day(17).isoformat()
    async with _as_lawyer(case["lawyer"]) as c:
        resp = await c.patch(_url(case), json={"date": new, "time": "11:30", "reason": "Judge on leave"})
    assert resp.status_code == 200, resp.text
    moved = next(h for h in resp.json()["hearing_dates"] if h["_id"] == "h-up")
    assert moved["date"].startswith(_day(17).date().isoformat())
    assert moved["time"] == "11:30"
    assert moved["purpose"] == "Framing of issues"         # not an outcome: purpose kept

    stored = await get_cases_col().find_one({"_id": case["case"]})
    h = next(x for x in stored["hearing_dates"] if x["_id"] == "h-up")
    assert len(h["reschedules"]) == 1
    entry = h["reschedules"][0]
    assert entry["from_time"] == "10:00" and entry["to_time"] == "11:30"
    assert entry["reason"] == "Judge on leave"
    assert len(stored["hearing_dates"]) == 2, "a reschedule must not add a hearing"

    note = await get_notifications_col().find_one({"user_id": case["client"]})
    assert note is not None, "the client was not told"
    assert "moved from" in note["body"] and "Judge on leave" in note["body"]


async def test_the_time_is_kept_when_only_the_date_moves(case):
    async with _as_lawyer(case["lawyer"]) as c:
        resp = await c.patch(_url(case), json={"date": _day(12).isoformat()})
    assert resp.status_code == 200, resp.text
    moved = next(h for h in resp.json()["hearing_dates"] if h["_id"] == "h-up")
    assert moved["time"] == "10:00"


async def test_another_lawyer_cannot_reschedule(case):
    async with _as_lawyer(case["other"]) as c:
        resp = await c.patch(_url(case), json={"date": _day(12).isoformat()})
    assert resp.status_code == 403


async def test_a_hearing_with_an_outcome_cannot_move(case):
    async with _as_lawyer(case["lawyer"]) as c:
        resp = await c.patch(f"/cases/{case['case']}/hearings/h-done/reschedule", json={"date": _day(12).isoformat()})
    # 409, not 422: a state conflict, the same code the concurrent case gives.
    assert resp.status_code == 409
    assert "outcome" in resp.text


async def test_unknown_hearing_is_404(case):
    async with _as_lawyer(case["lawyer"]) as c:
        resp = await c.patch(f"/cases/{case['case']}/hearings/nope/reschedule", json={"date": _day(12).isoformat()})
    assert resp.status_code == 404


@pytest.mark.parametrize("body", [
    {"date": _day(-10).isoformat()},                     # in the past
    {"date": _day(10).isoformat(), "time": "10:00"},     # same date and time
    {"date": _day(12).isoformat(), "time": "25:00"},     # not a time
    {"date": _day(12).isoformat(), "lawyer_id": "x"},    # unknown field
])
async def test_invalid_moves_are_refused(case, body):
    async with _as_lawyer(case["lawyer"]) as c:
        resp = await c.patch(_url(case), json=body)
    assert resp.status_code == 422, resp.text


async def test_a_failed_client_notice_is_logged_not_swallowed(case, monkeypatch, caplog):
    """The move stands when the notice fails, but the failure is recorded:
    a bare `except: pass` hid that a client was never told their date moved."""
    import logging

    from app.services import notification_service

    async def boom(*a, **k):
        raise RuntimeError("notifications down")

    monkeypatch.setattr(notification_service, "create_notification", boom)
    caplog.set_level(logging.ERROR, logger="app.services.case_service")
    async with _as_lawyer(case["lawyer"]) as c:
        resp = await c.patch(_url(case), json={"date": _day(18).isoformat(), "time": "10:00"})
    assert resp.status_code == 200, resp.text
    assert any("hearing-rescheduled notification failed" in r.getMessage() for r in caplog.records)
