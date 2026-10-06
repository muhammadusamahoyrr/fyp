"""GET /cases?status=... : an optional, validated filter inside the caller's scope.

The lawyer dashboard needs exact active totals (open + in_progress). Without a
filter it could only count the first 50 cases it downloaded. The filter must:
  * leave the unfiltered listing exactly as it was (backward compatible);
  * reject an unknown status with a 422 rather than returning nothing;
  * narrow WITHIN the caller's own cases, never widen past them.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def world(mongo):
    from app.db.collections import get_cases_col

    tag = secrets.token_hex(4)
    lawyer, other_lawyer, client = f"CSF-L-{tag}", f"CSF-O-{tag}", f"CSF-C-{tag}"
    now = datetime.now(timezone.utc)

    def case(n, status, lawyer_id=lawyer, client_id=client):
        return {"_id": f"CSF-{tag}-{n}", "case_number": f"CSF-{tag}-{n}", "title": f"Matter {n}",
                "client_id": client_id, "lawyer_id": lawyer_id, "status": status,
                "milestones": [], "hearing_dates": [], "created_at": now, "updated_at": now}

    docs = [
        case(1, "open"), case(2, "in_progress"), case(3, "in_progress"),
        case(4, "pending_lawyer"), case(5, "closed"),
        # Another lawyer's open case, for the same client: must never leak into
        # the first lawyer's counts.
        case(6, "open", lawyer_id=other_lawyer),
    ]
    await get_cases_col().insert_many(docs)
    yield {"lawyer": lawyer, "other": other_lawyer, "client": client}
    await get_cases_col().delete_many({"_id": {"$in": [d["_id"] for d in docs]}})


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


async def _total(user_id: str, role: str, query: str = "") -> int:
    async with _as(user_id, role) as c:
        resp = await c.get(f"/cases?page_size=1{query}")
    assert resp.status_code == 200, resp.text
    return resp.json()["total"]


async def test_without_status_the_listing_is_unchanged(world):
    assert await _total(world["lawyer"], "lawyer") == 5


async def test_status_narrows_to_that_status(world):
    async with _as(world["lawyer"], "lawyer") as c:
        resp = await c.get("/cases?page_size=50&status=in_progress")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert {item["status"] for item in body["items"]} == {"in_progress"}


async def test_active_total_is_open_plus_in_progress(world):
    open_ = await _total(world["lawyer"], "lawyer", "&status=open")
    in_progress = await _total(world["lawyer"], "lawyer", "&status=in_progress")
    assert (open_, in_progress) == (1, 2)


async def test_the_filter_stays_inside_the_callers_scope(world):
    # The other lawyer's open case is not counted for this lawyer...
    assert await _total(world["lawyer"], "lawyer", "&status=open") == 1
    # ...and that lawyer sees only their own.
    assert await _total(world["other"], "lawyer", "&status=open") == 1
    # The client sees both open cases that are theirs, and nothing more.
    assert await _total(world["client"], "client", "&status=open") == 2


async def test_an_unknown_status_is_rejected(world):
    async with _as(world["lawyer"], "lawyer") as c:
        resp = await c.get("/cases?status=active")
    assert resp.status_code == 422
