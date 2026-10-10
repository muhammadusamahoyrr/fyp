"""/lawyer-events: a lawyer's own meetings and events, over HTTP.

A lawyer could not put anything in their own diary: the only thing on the
calendar was client-booked appointments, and `POST /appointments` is
client-only by design. A diary entry is the lawyer's private note of a meeting
or event. It must stay private to its owner and never be addressable by
another lawyer or by a client.
"""
from __future__ import annotations

import secrets

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def lawyers(app_indexes):
    from app.db.collections import get_lawyer_events_col

    tag = secrets.token_hex(4)
    ids = {"a": f"LE-A-{tag}", "b": f"LE-B-{tag}"}
    yield ids
    await get_lawyer_events_col().delete_many({"lawyer_id": {"$in": list(ids.values())}})


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


def _as(user_id: str, role: str = "lawyer") -> AsyncClient:
    from fastapi import HTTPException

    from app.dependencies import get_current_user, require_lawyer
    from app.main import app

    who = {"_id": user_id, "role": role}
    app.dependency_overrides[get_current_user] = lambda: who

    def _lawyer_only():
        if role != "lawyer":
            raise HTTPException(status_code=403, detail="Lawyers only")
        return who
    app.dependency_overrides[require_lawyer] = _lawyer_only
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1")


MEETING = {
    "kind": "meeting", "title": "  Chambers meeting with Mr. Khan  ",
    "starts_at": "2026-10-08T16:30:00+05:00", "duration_minutes": 90,
    "client_name": "Imran Khan", "location": "Chambers, Mall Road",
    "priority": "high", "notes": "Bring the sale deed.",
}
OCTOBER = {"start": "2026-10-01T00:00:00+05:00", "end": "2026-11-01T00:00:00+05:00"}


async def test_a_lawyer_creates_an_entry_and_sees_it_in_the_month(lawyers):
    async with _as(lawyers["a"]) as c:
        made = await c.post("/lawyer-events", json=MEETING)
        assert made.status_code == 201, made.text
        body = made.json()
        assert body["title"] == "Chambers meeting with Mr. Khan"      # trimmed
        assert body["starts_at"].startswith("2026-10-08T11:30:00")    # stored as UTC
        assert body["ends_at"].startswith("2026-10-08T13:00:00")
        assert body["priority"] == "high" and body["kind"] == "meeting"

        listed = await c.get("/lawyer-events", params=OCTOBER)
        assert listed.status_code == 200, listed.text
        assert [e["id"] for e in listed.json()] == [body["id"]]
        # The offset survives the round trip through Mongo.
        assert listed.json()[0]["starts_at"].endswith(("Z", "+00:00"))


async def test_the_window_bounds_the_listing(lawyers):
    async with _as(lawyers["a"]) as c:
        await c.post("/lawyer-events", json=MEETING)
        nov = await c.get("/lawyer-events", params={
            "start": "2026-11-01T00:00:00+05:00", "end": "2026-12-01T00:00:00+05:00"})
        assert nov.json() == []
        too_wide = await c.get("/lawyer-events", params={
            "start": "2026-01-01T00:00:00+05:00", "end": "2026-12-01T00:00:00+05:00"})
        assert too_wide.status_code == 422
        backwards = await c.get("/lawyer-events", params={
            "start": OCTOBER["end"], "end": OCTOBER["start"]})
        assert backwards.status_code == 422


async def test_another_lawyers_entries_are_invisible_and_undeletable(lawyers):
    async with _as(lawyers["a"]) as c:
        made = (await c.post("/lawyer-events", json=MEETING)).json()
    async with _as(lawyers["b"]) as c:
        assert (await c.get("/lawyer-events", params=OCTOBER)).json() == []
        gone = await c.delete(f"/lawyer-events/{made['id']}")
        assert gone.status_code == 404
    async with _as(lawyers["a"]) as c:
        assert len((await c.get("/lawyer-events", params=OCTOBER)).json()) == 1


async def test_the_owner_deletes_an_entry(lawyers):
    async with _as(lawyers["a"]) as c:
        made = (await c.post("/lawyer-events", json=MEETING)).json()
        resp = await c.delete(f"/lawyer-events/{made['id']}")
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "message": "Diary entry deleted"}
        assert (await c.get("/lawyer-events", params=OCTOBER)).json() == []
        assert (await c.delete(f"/lawyer-events/{made['id']}")).status_code == 404


async def test_a_client_cannot_use_the_diary(lawyers):
    async with _as("LE-CLIENT", role="client") as c:
        assert (await c.post("/lawyer-events", json=MEETING)).status_code == 403
        assert (await c.get("/lawyer-events", params=OCTOBER)).status_code == 403


@pytest.mark.parametrize("bad", [
    {"title": "   "},                                   # blank after trimming
    {"starts_at": "2026-10-08T16:30:00"},               # no offset
    {"duration_minutes": 5},
    {"kind": "hearing"},
    {"priority": "urgent"},
    {"lawyer_id": "someone-else"},                      # cannot pick the owner
])
async def test_invalid_entries_are_refused(lawyers, bad):
    async with _as(lawyers["a"]) as c:
        resp = await c.post("/lawyer-events", json={**MEETING, **bad})
        assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("when", ["9999-12-31T23:30:00+00:00", "0001-01-01T00:30:00+05:00",
                                  "1999-12-31T23:00:00+00:00", "2100-01-01T00:00:00+00:00"])
async def test_dates_outside_the_diary_range_are_a_422_not_a_500(lawyers, when):
    # year 9999 + 60 min overflowed AFTER the insert: a 500 and a stored row.
    from app.db.collections import get_lawyer_events_col
    async with _as(lawyers["a"]) as c:
        resp = await c.post("/lawyer-events", json={**MEETING, "starts_at": when})
        assert resp.status_code == 422, resp.text
    assert await get_lawyer_events_col().count_documents({"lawyer_id": lawyers["a"]}) == 0


async def test_listing_outside_the_range_is_a_422(lawyers):
    async with _as(lawyers["a"]) as c:
        resp = await c.get("/lawyer-events", params={
            "start": "0001-01-01T00:00:00+05:00", "end": "0001-02-01T00:00:00+05:00"})
        assert resp.status_code == 422, resp.text
