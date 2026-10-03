"""Document review requests, slice 4: what the flag decides about transactions.

DOCUMENT_REVIEW_REQUESTS off: the lifecycle hooks are no-ops and an engagement
completes on its old, non-transactional path -- a standalone Mongo keeps
working. On: transactions are mandatory, and startup refuses a standalone
server instead of letting the first completion fail at runtime.

These tests run on whatever database the suite points at; the standalone
cases are the point of the file, so they do not need a replica set.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.db.collections import (
    get_document_review_request_events_col,
    get_document_review_requests_col,
    get_notifications_col,
    get_users_col,
)
from app.services import agreement_service, engagement_service
from app.services import review_request_lifecycle as life
from tests._engagement_support import disengage, engage

pytestmark = pytest.mark.integration

TAG = uuid.uuid4().hex[:8]
CLIENT = f"fgc-{TAG}"
LAWYER = f"fgl-{TAG}"


@pytest.fixture
async def people(mongo):
    await get_users_col().insert_many([
        {"_id": CLIENT, "role": "client", "full_name": "Ayesha Khan", "email": f"{CLIENT}@test.invalid"},
        {"_id": LAWYER, "role": "lawyer", "full_name": "Adv. Bilal", "email": f"{LAWYER}@test.invalid"}])
    yield mongo
    await get_document_review_requests_col().delete_many({"client_id": CLIENT})
    await get_document_review_request_events_col().delete_many({"request_id": {"$regex": f"^{TAG}"}})
    await get_notifications_col().delete_many({"user_id": {"$in": [CLIENT, LAWYER]}})
    await get_users_col().delete_many({"_id": {"$in": [CLIENT, LAWYER]}})
    await disengage(CLIENT, LAWYER)


def _open_request(engagement_id: str) -> dict:
    now = datetime.now(timezone.utc)
    return {"_id": f"{TAG}-{uuid.uuid4().hex[:8]}", "state_version": 2, "event_seq": 2,
            "status": "submitted", "is_open": True, "client_id": CLIENT, "lawyer_id": LAWYER,
            "engagement_id": engagement_id, "case_id": None, "document_id": f"{TAG}-doc",
            "revision_id": f"{TAG}-rev", "version": 1, "pdf_sha256": "a" * 64,
            "created_at": now, "updated_at": now, "submitted_at": now,
            "create_idempotency_key_hash": uuid.uuid4().hex + uuid.uuid4().hex,
            "receipts": {}, "pending_events": []}


async def test_flag_off_completion_takes_the_old_path_with_no_transaction(people, monkeypatch):
    monkeypatch.setattr(settings, "document_review_requests", False)

    async def no_transactions(_operation):
        raise AssertionError("a transaction was started with DOCUMENT_REVIEW_REQUESTS off")

    monkeypatch.setattr(agreement_service, "_run_in_transaction", no_transactions)
    engagement = await engage(CLIENT, LAWYER)
    request = _open_request(engagement)
    await get_document_review_requests_col().insert_one(request)

    done = await engagement_service.complete_engagement(engagement, LAWYER, note="Done.", one_sided=True)
    assert done["status"] == "completed" and done["completion_kind"] == "one_sided"
    # The hook is a no-op while off: the row is left for the sweep.
    row = await get_document_review_requests_col().find_one({"_id": request["_id"]})
    assert (row["status"], row["state_version"]) == ("submitted", 2)


async def test_flag_off_the_hooks_and_the_sweep_do_nothing(people, monkeypatch):
    monkeypatch.setattr(settings, "document_review_requests", False)
    engagement = await engage(CLIENT, LAWYER, status="completed")
    await get_document_review_requests_col().insert_one(_open_request(engagement))
    assert await life.end_for_engagement(None, engagement_id=engagement) == {"cancelled": 0,
                                                                          "retention_started": 0}
    assert (await life.sweep())["batches"] == 0


class _FakeAdmin:
    def __init__(self, hello):
        self._hello = hello

    async def command(self, name):
        assert name == "hello"
        return self._hello


class _FakeDb:
    def __init__(self, hello):
        self.client = type("C", (), {"admin": _FakeAdmin(hello)})()


@pytest.mark.parametrize("hello, ready", [
    ({"isWritablePrimary": True}, False),                     # standalone
    ({"isWritablePrimary": True, "setName": "rs0"}, True),    # replica set
    ({"isWritablePrimary": True, "msg": "isdbgrid"}, True),   # mongos
])
async def test_readiness_with_the_flag_on_refuses_only_a_standalone(monkeypatch, hello, ready):
    monkeypatch.setattr(settings, "document_review_requests", True)
    if ready:
        await life.assert_ready(_FakeDb(hello))
    else:
        with pytest.raises(life.ReviewRequestsNotReady, match="standalone.*replica set"):
            await life.assert_ready(_FakeDb(hello))


async def test_readiness_with_the_flag_off_checks_nothing(monkeypatch):
    monkeypatch.setattr(settings, "document_review_requests", False)
    await life.assert_ready(_FakeDb({"isWritablePrimary": True}))      # a standalone, and fine


async def test_readiness_against_the_real_test_database(mongo, monkeypatch):
    """On a standalone (the default local run) the flag-on check must fail
    clearly; on a replica set it must pass."""
    monkeypatch.setattr(settings, "document_review_requests", True)
    hello = await mongo.client.admin.command("hello")
    if hello.get("setName") or hello.get("msg") == "isdbgrid":
        await life.assert_ready(mongo)
    else:
        with pytest.raises(life.ReviewRequestsNotReady, match="DOCUMENT_REVIEW_REQUESTS"):
            await life.assert_ready(mongo)
