"""The /intake route contracts, exercised over HTTP.

The service layer is well covered and the routes were not: nothing asserted what
a client actually receives, which is how `GET /intake/{token}` came to return the
session token, a step number and nothing the client had typed — a response that
made a refresh unable to rebuild the form it belonged to.

These go through the real FastAPI app and the real dependency graph, so an
auth rule, a response model that filters a field out, or a status code are all
in scope. The database is the throwaway test one; no model is called.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def seeded(mongo):
    """A client and an intake part-way through. Returns ids only."""
    from app.db.collections import get_intakes_col, get_users_col

    tag = secrets.token_hex(4)
    client_id = f"HT-C-{tag}"
    token = f"HT-T-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_one({
        "_id": client_id, "role": "client", "is_active": True,
        "email": f"ht-{tag}@test.invalid", "full_name": "HTTP Client",
        "province": "punjab", "created_at": now,
    })
    await get_intakes_col().insert_one({
        "_id": f"HT-I-{tag}", "session_token": token, "client_id": client_id,
        "current_step": 4, "completed": False, "case_id": None,
        "step1": {"province": "punjab", "party_role": "defendant"},
        "step2": {"case_type": "family", "urgency": "high"},
        "step3": {"incident_description": "My husband stopped paying maintenance."},
        "step4": {"has_evidence": True, "evidence_description": "Bank statements."},
        "clarification_qa": [
            {"q": "For how many months?", "a": "Eight months."},
            {"q": "Is the marriage registered?", "a": None},
        ],
        "evidence_files": [
            {"file_id": "f-1", "filename": "statement.pdf",
             "content_type": "application/pdf", "size": 2048,
             "path": "C:/secret/upload/root/evidence/f-1.pdf"},
        ],
        "created_at": now, "updated_at": now,
    })

    yield {"token": token, "client_id": client_id}

    await get_users_col().delete_many({"_id": client_id})
    await get_intakes_col().delete_many({"session_token": token})


def _as(user_id: str):
    """Sign requests in as `user_id`, the way the rest of the suite does.

    Dependency overrides rather than a minted JWT: access tokens now carry a
    session id that `get_current_user` checks against a live session, so a
    hand-made token would be testing the session store rather than the route.
    The authorization boundary that matters for intake is the `client_id` check
    inside the service, and that is exercised by signing in as the WRONG user.
    """
    from app.dependencies import get_current_user, require_client
    from app.main import app

    who = {"_id": user_id, "role": "client"}
    app.dependency_overrides[require_client] = lambda: who
    app.dependency_overrides[get_current_user] = lambda: who
    return AsyncClient(transport=ASGITransport(app=app),
                       base_url="http://test/api/v1")


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


# ── GET /intake/{token}: everything a refresh needs ─────────────────────────

async def test_the_detail_response_returns_the_saved_steps(seeded):
    async with _as(seeded["client_id"]) as http:
        r = await http.get(f"/intake/{seeded['token']}")
    assert r.status_code == 200
    steps = r.json()["steps"]
    assert steps["1"]["province"] == "punjab"
    assert steps["2"]["case_type"] == "family"
    assert steps["3"]["incident_description"].startswith("My husband")


async def test_the_detail_response_returns_the_clarification_qa(seeded):
    async with _as(seeded["client_id"]) as http:
        r = await http.get(f"/intake/{seeded['token']}")
    qa = r.json()["clarification_qa"]
    assert len(qa) == 2
    assert qa[0]["a"] == "Eight months."
    assert qa[1]["a"] is None      # the question to resume on


async def test_the_detail_response_returns_the_uploaded_evidence(seeded):
    async with _as(seeded["client_id"]) as http:
        r = await http.get(f"/intake/{seeded['token']}")
    files = r.json()["evidence_files"]
    assert [f["filename"] for f in files] == ["statement.pdf"]


async def test_the_server_disk_path_is_never_returned(seeded):
    """`evidence_files` entries carry `path` — the absolute location on disk.

    Useless to a browser, and it hands out the upload root and the naming
    scheme to anyone who asks for their own intake.
    """
    async with _as(seeded["client_id"]) as http:
        r = await http.get(f"/intake/{seeded['token']}")
    body = r.text
    assert "path" not in r.json()["evidence_files"][0]
    assert "secret/upload/root" not in body


async def test_a_different_client_cannot_read_it(seeded):
    """The authorization boundary: the service checks `client_id` on the session.

    A stranger gets 404, not 403 — an intake they do not own should not be
    distinguishable from one that does not exist.
    """
    async with _as("HT-STRANGER") as http:
        r = await http.get(f"/intake/{seeded['token']}")
    assert r.status_code == 404


async def test_a_different_client_cannot_write_to_it(seeded):
    async with _as("HT-STRANGER") as http:
        r = await http.patch(f"/intake/{seeded['token']}/step/1",
                             json={"data": {"province": "sindh"}})
    assert r.status_code == 404


# ── PATCH /intake/{token}/step/{n}: the validation contract ────────────────

async def test_an_invalid_province_is_rejected_over_http(seeded):
    async with _as(seeded["client_id"]) as http:
        r = await http.patch(f"/intake/{seeded['token']}/step/1",
                             json={"data": {"province": "Atlantis"}})
    assert r.status_code == 422
    assert "province" in r.text


async def test_an_unknown_field_is_rejected_over_http(seeded):
    async with _as(seeded["client_id"]) as http:
        r = await http.patch(f"/intake/{seeded['token']}/step/1",
                             json={"data": {"province": "punjab", "smuggled": "x"}})
    assert r.status_code == 422


async def test_a_valid_step_save_round_trips(seeded):
    async with _as(seeded["client_id"]) as http:
        save = await http.patch(f"/intake/{seeded['token']}/step/5",
                                json={"data": {"desired_outcome": "A maintenance order"}})
        assert save.status_code == 200
        read = await http.get(f"/intake/{seeded['token']}")
    assert read.json()["steps"]["5"]["desired_outcome"] == "A maintenance order"


async def test_the_party_role_is_normalised_over_http(seeded):
    """The UI sends its card labels as shown: "Plaintiff", not "plaintiff"."""
    async with _as(seeded["client_id"]) as http:
        await http.patch(f"/intake/{seeded['token']}/step/1",
                         json={"data": {"province": "punjab",
                                        "party_role": "Plaintiff"}})
        read = await http.get(f"/intake/{seeded['token']}")
    assert read.json()["steps"]["1"]["party_role"] == "plaintiff"


async def test_a_step_out_of_range_is_refused(seeded):
    async with _as(seeded["client_id"]) as http:
        r = await http.patch(f"/intake/{seeded['token']}/step/9", json={"data": {}})
    assert r.status_code == 422


# ── the draft confirmation contract ────────────────────────────────────────

async def test_the_detail_response_reports_the_case_status(seeded, mongo):
    """A refresh has to tell a draft from a live case.

    The intake records that a case was produced; only the CASE records whether
    the client confirmed it. Without this the UI would offer to confirm an
    already-open case, or present a draft as ready.
    """
    from app.db.collections import get_cases_col, get_intakes_col

    case_id = f"HT-CASE-{seeded['client_id']}"
    await get_cases_col().insert_one({
        "_id": case_id, "case_number": "ATT-2026-HTTP", "client_id": seeded["client_id"],
        "lawyer_id": None, "case_type": "family", "province": "punjab",
        "status": "draft", "title": "t", "description": "d",
        "milestones": [], "hearing_dates": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    await get_intakes_col().update_one(
        {"session_token": seeded["token"]}, {"$set": {"case_id": case_id}})

    async with _as(seeded["client_id"]) as http:
        r = await http.get(f"/intake/{seeded['token']}")
        assert r.json()["case_status"] == "draft"

        confirmed = await http.patch(f"/cases/{case_id}/confirm")
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "open"

        after = await http.get(f"/intake/{seeded['token']}")
        assert after.json()["case_status"] == "open"

    await get_cases_col().delete_many({"_id": case_id})


async def test_confirming_twice_over_http_is_not_an_error(seeded, mongo):
    from app.db.collections import get_cases_col

    case_id = f"HT-IDEM-{seeded['client_id']}"
    await get_cases_col().insert_one({
        "_id": case_id, "case_number": "ATT-2026-IDEM", "client_id": seeded["client_id"],
        "lawyer_id": None, "case_type": "family", "province": "punjab",
        "status": "draft", "title": "t", "description": "d",
        "milestones": [], "hearing_dates": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

    async with _as(seeded["client_id"]) as http:
        first = await http.patch(f"/cases/{case_id}/confirm")
        second = await http.patch(f"/cases/{case_id}/confirm")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "open"
    await get_cases_col().delete_many({"_id": case_id})


async def test_a_stranger_cannot_confirm_over_http(seeded, mongo):
    from app.db.collections import get_cases_col

    case_id = f"HT-FORB-{seeded['client_id']}"
    await get_cases_col().insert_one({
        "_id": case_id, "case_number": "ATT-2026-FORB", "client_id": seeded["client_id"],
        "lawyer_id": None, "case_type": "family", "province": "punjab",
        "status": "draft", "title": "t", "description": "d",
        "milestones": [], "hearing_dates": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

    async with _as("HT-STRANGER") as http:
        r = await http.patch(f"/cases/{case_id}/confirm")

    assert r.status_code == 403
    stored = await get_cases_col().find_one({"_id": case_id})
    assert stored["status"] == "draft"
    await get_cases_col().delete_many({"_id": case_id})
