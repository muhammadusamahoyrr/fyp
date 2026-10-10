"""POST /cases/walk-in: a lawyer opens a case for a client not on the platform.

Before this, a lawyer had no way to create a case: POST /cases treats the
caller as the CLIENT, so a lawyer calling it became the client of their own
case, and the case never appeared in their list.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

BODY = {"title": "Rent recovery — Mr. Aslam", "case_type": "civil", "province": "punjab",
        "client_name": "Muhammad Aslam", "client_phone": "+92 300 1234567",
        "court": "Civil Court Lahore", "court_case_number": "1234/2026"}


@pytest.fixture
async def lawyer(app_indexes):
    from app.db.collections import get_cases_col, get_notifications_col

    lid = f"WI-L-{secrets.token_hex(4)}"
    yield lid
    await get_cases_col().delete_many({"lawyer_id": lid})
    await get_notifications_col().delete_many({"user_id": None})


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


def _as(user_id: str, role: str) -> AsyncClient:
    from app.dependencies import get_current_user, require_lawyer
    from app.main import app

    who = {"_id": user_id, "role": role, "full_name": "Adv Test"}
    app.dependency_overrides[get_current_user] = lambda: who
    if role == "lawyer":
        app.dependency_overrides[require_lawyer] = lambda: who
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1")


async def test_a_lawyer_creates_a_case_that_is_theirs_and_listed(lawyer):
    async with _as(lawyer, "lawyer") as c:
        made = await c.post("/cases/walk-in", json=BODY)
        assert made.status_code == 201, made.text
        case = made.json()
        assert case["lawyer_id"] == lawyer
        assert case["client_id"] is None
        assert case["walk_in"] is True
        assert case["status"] == "in_progress"
        assert case["client_name"] == "Muhammad Aslam"
        assert case["case_number"].startswith("ATT-")
        listed = await c.get("/cases", params={"page_size": 50})
    items = listed.json()["items"]
    assert [x["_id"] for x in items] == [case["_id"]]
    assert items[0]["client_name"] == "Muhammad Aslam", "the stored client name is shown"


async def test_a_client_cannot_use_it(lawyer):
    """The REAL lawyer guard (only the signed-in user is substituted)."""
    from app.db.collections import get_cases_col

    async with _as("WI-CLIENT", "client") as c:
        resp = await c.post("/cases/walk-in", json=BODY)
    assert resp.status_code == 403
    assert await get_cases_col().count_documents({"client_name": BODY["client_name"], "lawyer_id": "WI-CLIENT"}) == 0


@pytest.mark.parametrize("bad", [
    {"title": "ab"},
    {"client_name": ""},
    {"client_phone": "call me"},
    {"case_type": "tax"},
    {"province": "mars"},
    {"lawyer_id": "someone-else"},          # extra fields are refused, not ignored
])
async def test_invalid_input_is_refused(lawyer, bad):
    async with _as(lawyer, "lawyer") as c:
        resp = await c.post("/cases/walk-in", json={**BODY, **bad})
    assert resp.status_code == 422, resp.text


async def test_hearings_work_and_no_notification_goes_to_a_missing_client(lawyer):
    from app.db.collections import get_notifications_col

    async with _as(lawyer, "lawyer") as c:
        case = (await c.post("/cases/walk-in", json=BODY)).json()
        day = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
        added = await c.post(f"/cases/{case['_id']}/hearings",
                             json={"date": day, "court": "Civil Court Lahore", "time": "10:00"})
        assert added.status_code == 200, added.text
        hid = added.json()["hearing_dates"][0]["_id"]
        moved = await c.patch(f"/cases/{case['_id']}/hearings/{hid}/reschedule",
                              json={"date": (datetime.now(timezone.utc) + timedelta(days=12)).date().isoformat(), "time": "11:00"})
        assert moved.status_code == 200, moved.text
    assert await get_notifications_col().count_documents({"user_id": None}) == 0


async def test_messages_are_refused_because_nobody_would_receive_them(lawyer):
    async with _as(lawyer, "lawyer") as c:
        case = (await c.post("/cases/walk-in", json=BODY)).json()
        resp = await c.post(f"/cases/{case['_id']}/messages", json={"text": "Hello"})
    assert resp.status_code == 409
    assert "not on Attorney.AI" in resp.json().get("detail", resp.text) or "not on Attorney.AI" in resp.text


async def test_another_lawyer_cannot_open_it(lawyer):
    async with _as(lawyer, "lawyer") as c:
        case = (await c.post("/cases/walk-in", json=BODY)).json()
    async with _as("WI-OTHER", "lawyer") as c:
        resp = await c.get(f"/cases/{case['_id']}")
    assert resp.status_code in (403, 404)
