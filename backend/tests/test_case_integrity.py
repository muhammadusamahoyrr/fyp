"""Cases module integrity (Phase 1): writes that must not repeat or be lost.

WHAT WAS WRONG
  * POST /hearings had no idempotency: a double click or a retry after a lost
    reply created a second hearing and a second client notice.
  * PATCH /hearings/{id} (outcome) never refused a hearing that already had an
    outcome: a repeat overwrote it, added another next hearing and notified
    again. Two concurrent requests did the same.
  * PATCH /reschedule rebuilt the history from a stale read and wrote the whole
    array back, and its "no outcome" check ran on that stale read: concurrent
    moves lost history, a move could overwrite a freshly recorded outcome's
    hearing, and the client was told of a move that did not happen.
  * PATCH /cases/{id} skipped the closed-case guard, let a client change the
    case type under an engaged lawyer, and recorded a lawyer's change as the
    client's.
"""
from __future__ import annotations

import asyncio
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
    ids = {"case": f"CI-C-{tag}", "lawyer": f"CI-L-{tag}", "other": f"CI-O-{tag}",
           "client": f"CI-CL-{tag}", "stranger": f"CI-S-{tag}"}
    await get_cases_col().insert_one({
        "_id": ids["case"], "case_number": f"ATT-2026-{tag.upper()}", "title": "Rent dispute",
        "client_id": ids["client"], "lawyer_id": ids["lawyer"], "status": "in_progress",
        "case_type": "civil", "province": "punjab", "description": "x",
        "created_at": datetime.now(timezone.utc),
        "hearing_dates": [
            {"_id": "h-up", "date": _day(10), "time": "10:00", "court": "Civil Court Lahore",
             "purpose": "Framing of issues", "outcome": None},
            {"_id": "h-past", "date": _day(-2), "time": "10:00", "court": "Civil Court Lahore",
             "purpose": "Arguments", "outcome": None},
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


def _as(user_id: str, role: str) -> AsyncClient:
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {"_id": user_id, "role": role, "full_name": "Tester"}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1")


async def _case(ids):
    from app.db.collections import get_cases_col
    return await get_cases_col().find_one({"_id": ids["case"]})


async def _notes(ids, **match):
    from app.db.collections import get_notifications_col
    return await get_notifications_col().count_documents({"user_id": ids["client"], **match})


def _hearing_body(**over):
    return {"date": _day(20).isoformat(), "court": "Civil Court Lahore", "purpose": "Evidence",
            "time": "11:00", **over}


# ── 2. hearing creation is idempotent per request id ─────────────────────────

async def test_the_same_request_twice_creates_one_hearing_and_one_notice(case):
    rid = secrets.token_hex(16)
    async with _as(case["lawyer"], "lawyer") as c:
        first = await c.post(f"/cases/{case['case']}/hearings", json=_hearing_body(request_id=rid))
        again = await c.post(f"/cases/{case['case']}/hearings", json=_hearing_body(request_id=rid))
    assert first.status_code == 200, first.text
    assert again.status_code == 200, again.text
    stored = await _case(case)
    made = [h for h in stored["hearing_dates"] if h.get("request_id") == rid]
    assert len(made) == 1
    assert len(stored["hearing_dates"]) == 3
    assert await _notes(case, type="hearing_scheduled") == 1


async def test_two_concurrent_identical_requests_create_one_hearing(case):
    rid = secrets.token_hex(16)
    async with _as(case["lawyer"], "lawyer") as c:
        a, b = await asyncio.gather(
            c.post(f"/cases/{case['case']}/hearings", json=_hearing_body(request_id=rid)),
            c.post(f"/cases/{case['case']}/hearings", json=_hearing_body(request_id=rid)),
        )
    assert {a.status_code, b.status_code} == {200}, (a.text, b.text)
    stored = await _case(case)
    assert len([h for h in stored["hearing_dates"] if h.get("request_id") == rid]) == 1
    assert await _notes(case, type="hearing_scheduled") == 1


async def test_two_distinct_requests_with_identical_values_are_both_kept(case):
    async with _as(case["lawyer"], "lawyer") as c:
        for _ in range(2):
            r = await c.post(f"/cases/{case['case']}/hearings", json=_hearing_body(request_id=secrets.token_hex(16)))
            assert r.status_code == 200, r.text
    assert len((await _case(case))["hearing_dates"]) == 4
    assert await _notes(case, type="hearing_scheduled") == 2


async def test_the_same_id_with_different_details_is_refused(case):
    """A request id names ONE hearing. Reused for other details it is a
    client bug, not a retry: refuse it rather than silently return the old one."""
    rid = secrets.token_hex(16)
    async with _as(case["lawyer"], "lawyer") as c:
        first = await c.post(f"/cases/{case['case']}/hearings", json=_hearing_body(request_id=rid))
        other = await c.post(f"/cases/{case['case']}/hearings",
                             json=_hearing_body(request_id=rid, court="Sessions Court Lahore"))
    assert first.status_code == 200, first.text
    assert other.status_code == 409, other.text
    stored = await _case(case)
    assert len(stored["hearing_dates"]) == 3
    assert next(h for h in stored["hearing_dates"] if h.get("request_id") == rid)["court"] == "Civil Court Lahore"
    assert await _notes(case, type="hearing_scheduled") == 1


async def test_a_replay_restores_a_notice_lost_after_the_hearing_was_written(case, monkeypatch):
    """The hearing write succeeded but the process failed before the client
    notice. A retry of the same request must not create a second hearing, and
    must ensure the notice exists (once)."""
    from app.services import notification_service

    rid = secrets.token_hex(16)
    real = notification_service.create_notification

    async def down(*a, **k):
        raise RuntimeError("notifications down")
    monkeypatch.setattr(notification_service, "create_notification", down)
    async with _as(case["lawyer"], "lawyer") as c:
        assert (await c.post(f"/cases/{case['case']}/hearings", json=_hearing_body(request_id=rid))).status_code == 200
    assert await _notes(case, type="hearing_scheduled") == 0
    monkeypatch.setattr(notification_service, "create_notification", real)
    async with _as(case["lawyer"], "lawyer") as c:
        for _ in range(2):
            assert (await c.post(f"/cases/{case['case']}/hearings", json=_hearing_body(request_id=rid))).status_code == 200
    assert len((await _case(case))["hearing_dates"]) == 3
    assert await _notes(case, type="hearing_scheduled") == 1


async def test_a_request_without_an_id_still_works(case):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.post(f"/cases/{case['case']}/hearings", json=_hearing_body())
    assert r.status_code == 200, r.text
    assert len((await _case(case))["hearing_dates"]) == 3


@pytest.mark.parametrize("bad", ["short", "has spaces in it 1234567890", "x" * 65, "bad/slash/1234567890abc"])
async def test_a_malformed_request_id_is_refused(case, bad):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.post(f"/cases/{case['case']}/hearings", json=_hearing_body(request_id=bad))
    assert r.status_code == 422, r.text


# ── 3. one outcome per hearing ───────────────────────────────────────────────

async def test_a_second_outcome_is_refused_and_the_first_is_kept(case):
    url = f"/cases/{case['case']}/hearings/h-past"
    async with _as(case["lawyer"], "lawyer") as c:
        first = await c.patch(url, json={"outcome": "adjourned", "note": "first",
                                         "next_date": _day(30).isoformat(), "next_time": "10:00"})
        second = await c.patch(url, json={"outcome": "decided", "note": "second",
                                          "next_date": _day(31).isoformat(), "next_time": "10:00"})
    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text
    assert "already" in second.text.lower()
    stored = await _case(case)
    h = next(x for x in stored["hearing_dates"] if x["_id"] == "h-past")
    assert h["outcome"] == "adjourned" and h["outcome_note"] == "first", "the recorded outcome was overwritten"
    assert len(stored["hearing_dates"]) == 3, "a second next hearing was added"
    assert await _notes(case, type="case_update") == 1


async def test_concurrent_outcomes_record_one_outcome_one_next_hearing_one_notice(case):
    url = f"/cases/{case['case']}/hearings/h-past"
    body = {"outcome": "adjourned", "note": "n", "next_date": _day(30).isoformat(), "next_time": "10:00"}
    async with _as(case["lawyer"], "lawyer") as c:
        results = await asyncio.gather(*(c.patch(url, json=body) for _ in range(3)))
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409, 409], [r.text for r in results]
    stored = await _case(case)
    assert len(stored["hearing_dates"]) == 3, "more than one next hearing was created"
    assert await _notes(case, type="case_update") == 1


async def test_the_outcome_and_its_next_hearing_are_one_write(case, monkeypatch):
    """The old code wrote the outcome, then pushed the next hearing in a second
    write: a failure in between left an outcome whose next date was lost. Both
    must land together, or neither."""
    from app.services import case_service

    async def broken(*a, **k):
        raise RuntimeError("process stopped here")
    monkeypatch.setattr(case_service.case_repo, "add_hearing", broken)
    if hasattr(case_service.case_repo, "add_hearing_once"):
        monkeypatch.setattr(case_service.case_repo, "add_hearing_once", broken)
    status = None
    try:
        async with _as(case["lawyer"], "lawyer") as c:
            r = await c.patch(f"/cases/{case['case']}/hearings/h-past",
                              json={"outcome": "adjourned", "next_date": _day(30).isoformat(), "next_time": "10:00"})
            status = r.status_code
    except RuntimeError:
        status = "raised"            # the old two-write path stops here
    stored = await _case(case)
    h = next(x for x in stored["hearing_dates"] if x["_id"] == "h-past")
    nexts = [x for x in stored["hearing_dates"] if x["_id"] not in ("h-up", "h-past")]
    assert (h.get("outcome") is None and not nexts) or (h.get("outcome") == "adjourned" and len(nexts) == 1), \
        f"partial transition: outcome={h.get('outcome')!r} next hearings={len(nexts)} status={status}"
    assert status == 200 and h.get("outcome") == "adjourned", f"status={status}"


async def test_an_outcome_on_a_missing_hearing_is_404(case):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.patch(f"/cases/{case['case']}/hearings/nope", json={"outcome": "adjourned"})
    assert r.status_code == 404


# ── 5. reschedule is atomic and notifies only on success ─────────────────────

async def test_concurrent_reschedules_keep_every_history_entry_that_happened(case):
    url = f"/cases/{case['case']}/hearings/h-up/reschedule"
    async with _as(case["lawyer"], "lawyer") as c:
        a, b = await asyncio.gather(
            c.patch(url, json={"date": _day(15).isoformat(), "time": "11:00", "reason": "A"}),
            c.patch(url, json={"date": _day(16).isoformat(), "time": "12:00", "reason": "B"}),
        )
    codes = sorted([a.status_code, b.status_code])
    stored = await _case(case)
    h = next(x for x in stored["hearing_dates"] if x["_id"] == "h-up")
    moves = h.get("reschedules") or []
    # Each SUCCESSFUL move is in the history, exactly once; a refused one is not.
    assert len(moves) == codes.count(200)
    assert codes in ([200, 409], [200, 200]), (a.text, b.text)
    assert await _notes(case, title="Hearing rescheduled") == codes.count(200)
    if codes == [200, 200]:
        # Serialized: the second moved from where the first left it.
        assert moves[1]["from_date"] == moves[0]["to_date"]


def _serve_stale(monkeypatch, ids, snapshot, reads=(1, 3)):
    """Reads number `reads` of this case return `snapshot`.

    Each request reads the case once before writing and once after (to build
    its response, or to explain a refusal). Serving the snapshot to reads 1
    and 3 is "both requests read before either wrote", deterministically.
    """
    import copy
    from app.services import case_service

    real = case_service.case_repo.find_by_id
    seen = {"n": 0}

    async def read(cid):
        if cid == ids["case"]:
            seen["n"] += 1
            if seen["n"] in reads:
                return copy.deepcopy(snapshot)
        return await real(cid)
    monkeypatch.setattr(case_service.case_repo, "find_by_id", read)


async def test_two_reschedules_from_the_same_read_cannot_both_win(case, monkeypatch):
    _serve_stale(monkeypatch, case, await _case(case))
    url = f"/cases/{case['case']}/hearings/h-up/reschedule"
    async with _as(case["lawyer"], "lawyer") as c:
        a = await c.patch(url, json={"date": _day(15).isoformat(), "time": "11:00", "reason": "A"})
        b = await c.patch(url, json={"date": _day(16).isoformat(), "time": "12:00", "reason": "B"})
    assert (a.status_code, b.status_code) == (200, 409), (a.text, b.text)
    h = next(x for x in (await _case(case))["hearing_dates"] if x["_id"] == "h-up")
    assert [m["reason"] for m in h["reschedules"]] == ["A"], "history was rebuilt from a stale read"
    assert h["date"].date() == _day(15).date()
    assert await _notes(case, title="Hearing rescheduled") == 1


async def test_outcomes_from_the_same_read_record_once(case, monkeypatch):
    _serve_stale(monkeypatch, case, await _case(case))
    url = f"/cases/{case['case']}/hearings/h-past"
    async with _as(case["lawyer"], "lawyer") as c:
        a = await c.patch(url, json={"outcome": "adjourned", "note": "A", "next_date": _day(30).isoformat(), "next_time": "10:00"})
        b = await c.patch(url, json={"outcome": "decided", "note": "B", "next_date": _day(31).isoformat(), "next_time": "10:00"})
    assert (a.status_code, b.status_code) == (200, 409), (a.text, b.text)
    stored = await _case(case)
    h = next(x for x in stored["hearing_dates"] if x["_id"] == "h-past")
    assert h["outcome_note"] == "A"
    assert len(stored["hearing_dates"]) == 3, "a second next hearing was added"
    assert await _notes(case, type="case_update") == 1


async def test_an_outcome_recorded_meanwhile_is_not_overwritten_by_a_reschedule(case, monkeypatch):
    """The reschedule read the hearing before the outcome landed."""
    from app.db.collections import get_cases_col
    from app.services import case_service

    stale = await _case(case)                                  # no outcome yet
    await get_cases_col().update_one(
        {"_id": case["case"]}, {"$set": {"hearing_dates.$[h].outcome": "decided"}},
        array_filters=[{"h._id": "h-up"}])
    real = case_service.case_repo.find_by_id

    async def stale_read(cid):
        return stale if cid == case["case"] else await real(cid)
    monkeypatch.setattr(case_service.case_repo, "find_by_id", stale_read)

    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.patch(f"/cases/{case['case']}/hearings/h-up/reschedule",
                          json={"date": _day(15).isoformat(), "time": "11:00"})
    assert r.status_code == 409, r.text
    monkeypatch.setattr(case_service.case_repo, "find_by_id", real)
    h = next(x for x in (await _case(case))["hearing_dates"] if x["_id"] == "h-up")
    assert h["outcome"] == "decided"
    assert h["date"].date() == _day(10).date(), "the decided hearing was moved"
    assert not h.get("reschedules")
    assert await _notes(case, title="Hearing rescheduled") == 0


async def test_a_hearing_removed_meanwhile_is_not_notified(case, monkeypatch):
    from app.db.collections import get_cases_col
    from app.services import case_service

    stale = await _case(case)
    await get_cases_col().update_one({"_id": case["case"]}, {"$pull": {"hearing_dates": {"_id": "h-up"}}})
    real = case_service.case_repo.find_by_id

    async def stale_read(cid):
        return stale if cid == case["case"] else await real(cid)
    monkeypatch.setattr(case_service.case_repo, "find_by_id", stale_read)
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.patch(f"/cases/{case['case']}/hearings/h-up/reschedule",
                          json={"date": _day(15).isoformat(), "time": "11:00"})
    assert r.status_code == 409, r.text
    assert await _notes(case, title="Hearing rescheduled") == 0


# ── 4. who may edit the case record ──────────────────────────────────────────

async def _set(ids, **fields):
    from app.db.collections import get_cases_col
    await get_cases_col().update_one({"_id": ids["case"]}, {"$set": fields})


async def test_a_client_may_edit_before_a_lawyer_is_engaged(case):
    await _set(case, lawyer_id=None, status="open")
    async with _as(case["client"], "client") as c:
        r = await c.patch(f"/cases/{case['case']}", json={"title": "Rent recovery", "case_type": "family"})
    assert r.status_code == 200, r.text
    stored = await _case(case)
    assert stored["title"] == "Rent recovery" and stored["case_type"] == "family"
    assert stored["case_type_source"] == "client"


async def test_a_client_cannot_change_the_type_under_an_engaged_lawyer(case):
    async with _as(case["client"], "client") as c:
        r = await c.patch(f"/cases/{case['case']}", json={"case_type": "criminal"})
        ok = await c.patch(f"/cases/{case['case']}", json={"title": "Still editable"})
    assert r.status_code == 409, r.text
    assert (await _case(case))["case_type"] == "civil"
    assert ok.status_code == 200, "the client's title edit was refused"


async def test_the_assigned_lawyers_change_is_attributed_to_the_lawyer(case):
    async with _as(case["lawyer"], "lawyer") as c:
        r = await c.patch(f"/cases/{case['case']}", json={"case_type": "family"})
    assert r.status_code == 200, r.text
    stored = await _case(case)
    assert stored["case_type"] == "family"
    assert stored["case_type_source"] == "lawyer"
    assert stored["case_type_changed_by"] == case["lawyer"]


@pytest.mark.parametrize("status", ["closed", "dismissed"])
async def test_a_closed_case_cannot_be_edited(case, status):
    await _set(case, status=status)
    for who, role in ((case["client"], "client"), (case["lawyer"], "lawyer")):
        async with _as(who, role) as c:
            r = await c.patch(f"/cases/{case['case']}", json={"title": "Rewritten"})
        assert r.status_code == 409, (role, r.text)
    assert (await _case(case))["title"] == "Rent dispute"


@pytest.mark.parametrize("who,role", [("other", "lawyer"), ("stranger", "client")])
async def test_an_unrelated_user_cannot_edit(case, who, role):
    async with _as(case[who], role) as c:
        r = await c.patch(f"/cases/{case['case']}", json={"title": "Hijack"})
    assert r.status_code == 403
    assert (await _case(case))["title"] == "Rent dispute"


# ── 6. account closure and reminders ─────────────────────────────────────────

async def test_an_active_walk_in_case_blocks_closure_a_closed_one_does_not(case):
    from app.db.collections import get_cases_col
    from app.services import user_service

    lawyer = f"CI-WL-{secrets.token_hex(4)}"
    await get_cases_col().insert_one({"_id": f"{lawyer}-1", "lawyer_id": lawyer, "client_id": None, "walk_in": True,
                                      "status": "in_progress", "title": "Walk-in", "case_number": f"W-{lawyer}",
                                      "hearing_dates": []})
    try:
        reasons = await user_service._open_obligations(lawyer, "lawyer")
        assert any("walk-in" in r for r in reasons), reasons
        await get_cases_col().update_one({"_id": f"{lawyer}-1"}, {"$set": {"status": "closed"}})
        assert await user_service._open_obligations(lawyer, "lawyer") == []
    finally:
        await get_cases_col().delete_many({"lawyer_id": lawyer})


# ── a case closed between the read and the write ─────────────────────────────

@pytest.mark.parametrize("kind", ["add", "outcome", "reschedule"])
async def test_a_case_closed_meanwhile_takes_no_hearing_write_and_no_notice(case, monkeypatch, kind):
    stale = await _case(case)
    await _set(case, status="closed")
    _serve_stale(monkeypatch, case, stale, reads=(1,))      # read open, then closed
    base = f"/cases/{case['case']}/hearings"
    async with _as(case["lawyer"], "lawyer") as c:
        if kind == "add":
            r = await c.post(base, json=_hearing_body(request_id="closed-race-request-0001"))
        elif kind == "outcome":
            r = await c.patch(f"{base}/h-past", json={"outcome": "adjourned", "next_date": _day(30).isoformat()})
        else:
            r = await c.patch(f"{base}/h-up/reschedule", json={"date": _day(15).isoformat(), "time": "11:00"})
    assert r.status_code == 409, r.text
    assert "closed" in r.text
    stored = await _case(case)
    assert [h["_id"] for h in stored["hearing_dates"]] == ["h-up", "h-past"], "a hearing was added to a closed case"
    assert all(not h.get("outcome") for h in stored["hearing_dates"]), "an outcome was recorded on a closed case"
    assert not any(h.get("reschedules") for h in stored["hearing_dates"]), "a hearing on a closed case was moved"
    assert await _notes(case) == 0


@pytest.mark.parametrize("kind", ["message", "task", "toggle"])
async def test_a_case_closed_meanwhile_takes_no_message_or_task(case, monkeypatch, kind):
    from app.db.collections import get_notifications_col

    await _set(case, tasks=[{"_id": "t1", "lawyer_id": case["lawyer"], "title": "File reply", "done": False}])
    stale = await _case(case)
    await _set(case, status="closed")
    _serve_stale(monkeypatch, case, stale, reads=(1,))      # read open, then closed
    base = f"/cases/{case['case']}"
    async with _as(case["lawyer"], "lawyer") as c:
        if kind == "message":
            r = await c.post(f"{base}/messages", json={"text": "Please send the fard"})
        elif kind == "task":
            r = await c.post(f"{base}/tasks", json={"title": "Draft reply"})
        else:
            r = await c.patch(f"{base}/tasks/t1", json={"done": True})
    assert r.status_code == 409, r.text
    assert "closed" in r.text
    stored = await _case(case)
    assert not stored.get("messages"), "a message was added to a closed case"
    assert [(t["_id"], t["done"]) for t in stored["tasks"]] == [("t1", False)], "tasks changed on a closed case"
    assert await get_notifications_col().count_documents({"payload.case_id": case["case"]}) == 0


@pytest.fixture
async def reminder_case(app_indexes):
    from app.db.collections import get_cases_col, get_notifications_col, get_users_col

    tag = secrets.token_hex(4)
    ids = {"lawyer": f"CI-RL-{tag}", "client": f"CI-RC-{tag}", "case": f"CI-RCASE-{tag}"}
    await get_cases_col().insert_one({"_id": ids["case"], "lawyer_id": ids["lawyer"], "client_id": ids["client"],
                                      "status": "in_progress", "title": "T", "case_number": f"R-{tag}",
                                      "hearing_dates": [{"_id": "h1", "date": datetime(2026, 11, 11), "outcome": None}]})
    yield ids
    await get_cases_col().delete_many({"_id": ids["case"]})
    await get_users_col().delete_many({"_id": {"$in": [ids["lawyer"], ids["client"]]}})
    await get_notifications_col().delete_many({"user_id": {"$in": [ids["lawyer"], ids["client"]]}})


REMIND_AT = datetime(2026, 11, 10, 13, 0, tzinfo=timezone.utc)      # 18:00 PKT, the day before


async def _reminded(ids):
    from app.db.collections import get_notifications_col
    return {n["user_id"] async for n in get_notifications_col().find(
        {"user_id": {"$in": [ids["lawyer"], ids["client"]]}, "type": "hearing_reminder"})}


@pytest.mark.parametrize("lawyer_state,reminded", [
    ({"is_active": True}, True),
    ({"is_active": False}, False),
    ({"is_active": True, "is_closed": True}, False),
    (None, False),                                    # no user record at all
])
async def test_reminder_recipient_rules(reminder_case, lawyer_state, reminded):
    """One rule per case: only a live account is reminded. The client here is
    always live, so the lawyer's state alone decides the lawyer's reminder."""
    from app.db.collections import get_users_col
    from app.services import hearing_reminders as hr

    ids = reminder_case
    await get_users_col().insert_one({"_id": ids["client"], "role": "client", "is_active": True,
                                      "email": f"{ids['client']}@x.invalid"})
    if lawyer_state is not None:
        await get_users_col().insert_one({"_id": ids["lawyer"], "role": "lawyer",
                                          "email": f"{ids['lawyer']}@x.invalid", **lawyer_state})
    await hr.send_due_hearing_reminders(now=REMIND_AT)
    got = await _reminded(ids)
    assert ids["client"] in got, "the live client was not reminded"
    assert (ids["lawyer"] in got) is reminded, f"lawyer state {lawyer_state}: reminded={ids['lawyer'] in got}"


# ── 6b. close_account itself ─────────────────────────────────────────────────

@pytest.fixture
async def closing_lawyer(app_indexes):
    from app.core.security import hash_password
    from app.db.collections import get_cases_col, get_users_col

    lid = f"CI-CLOSE-{secrets.token_hex(4)}"
    await get_users_col().insert_one({"_id": lid, "role": "lawyer", "is_active": True,
                                      "email": f"{lid}@real.invalid", "full_name": "Adv Real",
                                      "password_hash": hash_password("correct-horse-1")})
    await get_cases_col().insert_one({"_id": f"{lid}-case", "lawyer_id": lid, "client_id": None, "walk_in": True,
                                      "status": "in_progress", "title": "Walk-in", "case_number": f"W-{lid}",
                                      "client_name": "Muhammad Aslam", "hearing_dates": []})
    yield lid
    await get_cases_col().delete_many({"lawyer_id": lid})
    await get_users_col().delete_many({"_id": lid})


async def test_close_account_is_refused_while_a_walk_in_case_is_open(closing_lawyer):
    from app.core.exceptions import AppValidationError
    from app.db.collections import get_cases_col, get_users_col
    from app.services import user_service

    with pytest.raises(AppValidationError, match="walk-in"):
        await user_service.close_account(closing_lawyer, "correct-horse-1")
    user = await get_users_col().find_one({"_id": closing_lawyer})
    assert user["is_active"] is True and not user.get("is_closed")
    assert user["email"] == f"{closing_lawyer}@real.invalid", "the refused closure still anonymised the account"
    case = await get_cases_col().find_one({"_id": f"{closing_lawyer}-case"})
    assert case["status"] == "in_progress" and case["lawyer_id"] == closing_lawyer, "the matter was changed"


@pytest.mark.parametrize("status", ["closed", "dismissed"])
async def test_close_account_is_allowed_once_walk_in_cases_are_finished(closing_lawyer, status):
    from app.db.collections import get_cases_col, get_users_col
    from app.services import user_service

    await get_cases_col().update_one({"_id": f"{closing_lawyer}-case"}, {"$set": {"status": status}})
    result = await user_service.close_account(closing_lawyer, "correct-horse-1")
    assert result["closed"] is True
    assert (await get_users_col().find_one({"_id": closing_lawyer}))["is_closed"] is True
