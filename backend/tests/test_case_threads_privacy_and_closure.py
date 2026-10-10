"""Case messages and tasks belong to one engagement; closed cases are read-only.

THE DEFECTS
-----------
* Ending an engagement only cleared `lawyer_id`. The case's `messages[]` and
  `tasks[]` stayed, so the NEXT lawyer engaged read the client's whole private
  conversation with the previous lawyer, and that lawyer's to-do list.
* `GET /cases/{id}/tasks` let the client in, and every case response carried
  `tasks` and `messages` inline (`CaseOut` is extra="allow"), so the client
  could read the lawyer's private working notes.
* A closed or dismissed case accepted new hearings, outcomes, reschedules,
  tasks and messages, notifying the client about a matter that had ended.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.constants import CaseStatus

pytestmark = pytest.mark.integration


def _day(n: int) -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=n)


@pytest.fixture
async def ids(app_indexes):
    from app.db.collections import get_cases_col, get_notifications_col

    tag = secrets.token_hex(4)
    out = {"case": f"TP-C-{tag}", "old": f"TP-L1-{tag}", "new": f"TP-L2-{tag}", "client": f"TP-CL-{tag}"}
    yield out
    await get_cases_col().delete_one({"_id": out["case"]})
    await get_notifications_col().delete_many({"user_id": {"$in": [out["client"], out["old"], out["new"]]}})


async def _insert_case(ids, *, lawyer, status=CaseStatus.IN_PROGRESS.value, **extra):
    from app.db.collections import get_cases_col
    await get_cases_col().insert_one({
        "_id": ids["case"], "title": "Rent dispute", "client_id": ids["client"], "lawyer_id": lawyer,
        "status": status, "case_type": "civil", "province": "punjab", "description": "x",
        "created_at": datetime.now(timezone.utc), "milestones": [],
        "hearing_dates": [{"_id": "h1", "date": _day(10), "time": "10:00", "court": "Civil Court", "purpose": "Issues", "outcome": None}],
        **extra,
    })


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


def _as(user_id: str, role: str) -> AsyncClient:
    from fastapi import HTTPException

    from app.dependencies import get_current_user, require_client, require_lawyer
    from app.main import app

    who = {"_id": user_id, "role": role, "full_name": f"{role} {user_id}"}
    app.dependency_overrides[get_current_user] = lambda: who

    def _only(r):
        def dep():
            if role != r:
                raise HTTPException(status_code=403, detail="forbidden")
            return who
        return dep
    app.dependency_overrides[require_lawyer] = _only("lawyer")
    app.dependency_overrides[require_client] = _only("client")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1")


# ── 1. a departing lawyer's thread stays theirs ───────────────────────────────

async def test_after_release_the_next_lawyer_sees_none_of_the_old_thread(ids):
    from app.db.collections import get_cases_col
    from app.services.case_service import seal_threads_for

    await _insert_case(ids, lawyer=ids["old"])
    async with _as(ids["old"], "lawyer") as c:
        assert (await c.post(f"/cases/{ids['case']}/messages", json={"text": "Bring the deed"})).status_code == 200
        assert (await c.post(f"/cases/{ids['case']}/tasks", json={"title": "Old strategy"})).status_code == 200
    # A legacy row written before messages were tagged.
    await get_cases_col().update_one({"_id": ids["case"]}, {"$push": {"messages": {
        "_id": "legacy", "sender_role": "client", "text": "Legacy hello", "created_at": datetime.now(timezone.utc)}}})

    # The engagement ends (what terminate_engagement does), then a new lawyer.
    await get_cases_col().update_one({"_id": ids["case"]}, {"$set": {"lawyer_id": None, "status": CaseStatus.OPEN.value}})
    await seal_threads_for(ids["case"], ids["old"])
    await get_cases_col().update_one({"_id": ids["case"]}, {"$set": {"lawyer_id": ids["new"], "status": CaseStatus.IN_PROGRESS.value}})

    async with _as(ids["new"], "lawyer") as c:
        msgs = (await c.get(f"/cases/{ids['case']}/messages")).json()
        tasks = (await c.get(f"/cases/{ids['case']}/tasks")).json()
        assert msgs == [], f"the new lawyer read the old thread: {msgs}"
        assert tasks == [], f"the new lawyer read the old tasks: {tasks}"
        # Their own thread starts clean and is theirs.
        assert (await c.post(f"/cases/{ids['case']}/messages", json={"text": "Hello, I am your new lawyer"})).status_code == 200
        assert [m["text"] for m in (await c.get(f"/cases/{ids['case']}/messages")).json()] == ["Hello, I am your new lawyer"]

    # The client keeps their whole history.
    async with _as(ids["client"], "client") as c:
        texts = [m["text"] for m in (await c.get(f"/cases/{ids['case']}/messages")).json()]
    assert texts == ["Bring the deed", "Legacy hello", "Hello, I am your new lawyer"]


async def test_sealing_a_case_with_no_threads_is_harmless(ids):
    from app.services.case_service import seal_threads_for
    await _insert_case(ids, lawyer=None, status=CaseStatus.OPEN.value)
    await seal_threads_for(ids["case"], ids["old"])     # no messages/tasks arrays: no error


@pytest.mark.parametrize("_", [None])
async def test_termination_seals_the_thread(ids, _, mongo_transactional):
    """End to end through terminate_engagement (skips without a replica set)."""
    from app.core.constants import EngagementStatus
    from app.db.collections import get_cases_col, get_engagements_col
    from app.services import engagement_service

    await _insert_case(ids, lawyer=ids["old"], messages=[{"_id": "m1", "text": "old", "sender_role": "lawyer"}],
                       tasks=[{"_id": "t1", "title": "old task", "done": False}])
    eng_id = f"TP-E-{secrets.token_hex(4)}"
    now = datetime.now(timezone.utc)
    await get_engagements_col().insert_one({
        "_id": eng_id, "case_id": ids["case"], "client_id": ids["client"], "lawyer_id": ids["old"],
        "status": EngagementStatus.ACCEPTED.value, "agreement_id": None, "created_at": now, "updated_at": now,
    })
    try:
        await engagement_service.terminate_engagement(eng_id, ids["client"], "Moving on")
        case = await get_cases_col().find_one({"_id": ids["case"]})
        assert case["messages"][0]["lawyer_id"] == ids["old"]
        assert case["tasks"][0]["lawyer_id"] == ids["old"]
    finally:
        await get_engagements_col().delete_one({"_id": eng_id})


# ── 2. tasks are the lawyer's ─────────────────────────────────────────────────

async def test_the_client_cannot_read_tasks_and_cases_carry_no_threads(ids):
    await _insert_case(ids, lawyer=ids["old"])
    async with _as(ids["old"], "lawyer") as c:
        await c.post(f"/cases/{ids['case']}/tasks", json={"title": "Settle at 180k max"})
        await c.post(f"/cases/{ids['case']}/messages", json={"text": "Hi"})
        lawyer_case = (await c.get(f"/cases/{ids['case']}")).json()
    assert "tasks" not in lawyer_case and "messages" not in lawyer_case

    async with _as(ids["client"], "client") as c:
        assert (await c.get(f"/cases/{ids['case']}/tasks")).status_code == 403
        one = (await c.get(f"/cases/{ids['case']}")).json()
        listed = (await c.get("/cases")).json()["items"]
    assert "tasks" not in one and "messages" not in one
    mine = next(x for x in listed if x["_id"] == ids["case"])
    assert "tasks" not in mine and "messages" not in mine


# ── 3. closed cases are read-only ─────────────────────────────────────────────

@pytest.mark.parametrize("status", [CaseStatus.CLOSED.value, CaseStatus.DISMISSED.value])
async def test_a_closed_case_refuses_every_change(ids, status):
    from app.db.collections import get_notifications_col

    await _insert_case(ids, lawyer=ids["old"], status=status, tasks=[{"_id": "t1", "title": "x", "done": False, "lawyer_id": ids["old"]}])
    base = f"/cases/{ids['case']}"
    async with _as(ids["old"], "lawyer") as c:
        calls = [
            await c.post(f"{base}/hearings", json={"date": _day(20).isoformat(), "court": "Civil Court"}),
            await c.patch(f"{base}/hearings/h1", json={"outcome": "adjourned"}),
            await c.patch(f"{base}/hearings/h1/reschedule", json={"date": _day(25).isoformat()}),
            await c.post(f"{base}/tasks", json={"title": "late"}),
            await c.patch(f"{base}/tasks/t1", json={"done": True}),
            await c.post(f"{base}/messages", json={"text": "late"}),
            await c.post(f"{base}/milestones", json={"title": "late", "date": _day(1).isoformat()}),
        ]
        # Reading is still allowed.
        assert (await c.get(base)).status_code == 200
        assert (await c.get(f"{base}/messages")).status_code == 200
    assert [r.status_code for r in calls] == [409] * len(calls), [r.text for r in calls]
    async with _as(ids["client"], "client") as c:
        assert (await c.post(f"{base}/messages", json={"text": "late"})).status_code == 409
    assert await get_notifications_col().count_documents({"user_id": ids["client"]}) == 0
