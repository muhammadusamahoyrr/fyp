"""GET /appointments?starts_from=&starts_before= — a start-time window.

The lawyer list is sorted oldest first, so the dashboard's "today" (the first
50 rows) never reached today for a lawyer with any history. A window lets it
ask for one day. Omitted, the listing is unchanged.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def rows(app_indexes):
    from app.db.collections import get_appointments_col

    tag = secrets.token_hex(4)
    lawyer, client = f"WIN-L-{tag}", f"WIN-C-{tag}"
    base = datetime(2026, 11, 10, 5, 0, tzinfo=timezone.utc)     # 10:00 PKT
    docs = []
    for i, offset in enumerate([-30, 0, 0, 1, 25]):
        at = base + timedelta(days=offset, hours=i)
        docs.append({
            "_id": f"WIN-{tag}-{i}", "lawyer_id": lawyer, "client_id": client,
            "scheduled_at": at, "end_at": at + timedelta(minutes=30), "duration_minutes": 30,
            "status": "confirmed", "mode": "video", "created_at": base, "updated_at": base,
            "occupied_slots": [f"WIN-{tag}-{i}"], "schedule_version": 1,
        })
    await get_appointments_col().insert_many(docs)
    yield {"lawyer": lawyer, "client": client, "ids": [d["_id"] for d in docs]}
    await get_appointments_col().delete_many({"lawyer_id": lawyer})


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


def _as(user_id: str, role: str) -> AsyncClient:
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {"_id": user_id, "role": role}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1")


DAY = {"starts_from": "2026-11-10T00:00:00+05:00", "starts_before": "2026-11-11T00:00:00+05:00"}


async def test_a_one_day_window_returns_only_that_days_appointments(rows):
    async with _as(rows["lawyer"], "lawyer") as c:
        resp = await c.get("/appointments", params={**DAY, "page_size": 50})
    assert resp.status_code == 200, resp.text
    assert [a["id"] for a in resp.json()["items"]] == rows["ids"][1:3]
    assert resp.json()["total"] == 2


async def test_the_client_listing_honours_the_window_too(rows):
    async with _as(rows["client"], "client") as c:
        resp = await c.get("/appointments", params={**DAY, "page_size": 50})
    assert sorted(a["id"] for a in resp.json()["items"]) == sorted(rows["ids"][1:3])


async def test_without_a_window_the_listing_is_unchanged(rows):
    async with _as(rows["lawyer"], "lawyer") as c:
        resp = await c.get("/appointments", params={"page_size": 50})
    assert resp.json()["total"] == 5


async def test_a_window_without_an_offset_is_refused(rows):
    async with _as(rows["lawyer"], "lawyer") as c:
        resp = await c.get("/appointments", params={"starts_from": "2026-11-10T00:00:00"})
    assert resp.status_code == 422
