"""Document review requests, slice 1: the indexes that carry its guarantees.

The race guards are indexes, so they are tested against the database, not
assumed: at most one OPEN request per (document, engagement), one request per
retried create, one total order of audit events per request. Startup refuses
to run with a missing index only when DOCUMENT_REVIEW_REQUESTS is on.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.db import indexes
from app.db.collections import get_document_review_request_events_col, get_document_review_requests_col
from app.db.review_request_index_spec import REVIEW_REQUEST_INDEX_REQUIREMENTS
from app.db.v2_index_spec import CORRECTNESS

TAG = uuid.uuid4().hex[:8]
NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)


def req(document_id, engagement_id, status="draft", client="c-" + TAG, key=None):
    return {"_id": uuid.uuid4().hex, "document_id": document_id, "engagement_id": engagement_id,
            "client_id": client, "status": status,
            "is_open": status in ("draft", "submitted", "viewed"),
            "create_idempotency_key_hash": key or uuid.uuid4().hex + uuid.uuid4().hex, "created_at": NOW}


@pytest.fixture
async def cols(app_indexes):
    requests, events = get_document_review_requests_col(), get_document_review_request_events_col()
    yield requests, events
    await requests.delete_many({"client_id": {"$regex": f"{TAG}$"}})
    await events.delete_many({"request_id": {"$regex": f"^{TAG}"}})


def test_the_manifest_declares_the_plans_guarantees():
    by_name = {s.name: s for s in REVIEW_REQUEST_INDEX_REQUIREMENTS}
    assert by_name["uniq_open_review_request"].kind == CORRECTNESS
    assert by_name["uniq_open_review_request"].unique
    assert by_name["uniq_open_review_request"].partial_filter == {"is_open": True}
    assert by_name["uniq_review_request_event_seq"].unique
    assert by_name["uniq_review_request_create_key"].unique
    assert {"review_requests_lawyer_inbox", "review_requests_client_recent", "review_requests_engagement",
            "review_requests_revision_hold", "review_requests_document"} <= set(by_name)


async def test_startup_creates_every_index_and_validation_finds_nothing_missing(cols):
    assert await indexes.validate_review_request_indexes() == []


async def test_at_most_one_open_request_per_document_and_engagement(cols):
    requests, _ = cols
    doc, eng = f"d-{TAG}", f"e-{TAG}"
    await requests.insert_one(req(doc, eng, "draft"))
    for status in ("draft", "submitted", "viewed"):
        with pytest.raises(DuplicateKeyError):
            await requests.insert_one(req(doc, eng, status))
    # Finished requests for the same pair are any number, beside the open one.
    for status in ("accepted", "declined", "cancelled", "cancelled"):
        await requests.insert_one(req(doc, eng, status))
    # The same document to ANOTHER engagement is a different pair.
    await requests.insert_one(req(doc, f"e2-{TAG}", "submitted"))
    assert await requests.count_documents({"document_id": doc}) == 6


async def test_closing_the_open_request_frees_the_pair(cols):
    requests, _ = cols
    doc, eng = f"d3-{TAG}", f"e3-{TAG}"
    first = req(doc, eng, "submitted")
    await requests.insert_one(first)
    await requests.update_one({"_id": first["_id"]}, {"$set": {"status": "cancelled", "is_open": False}})
    await requests.insert_one(req(doc, eng, "draft"))


async def test_a_retried_create_makes_one_request(cols):
    requests, _ = cols
    key = "k" * 64
    await requests.insert_one(req(f"d4-{TAG}", f"e4-{TAG}", key=key))
    with pytest.raises(DuplicateKeyError):
        await requests.insert_one(req(f"d5-{TAG}", f"e5-{TAG}", key=key))
    # The same key from ANOTHER client is another client's request.
    await requests.insert_one(req(f"d6-{TAG}", f"e6-{TAG}", key=key, client="c2-" + TAG))


async def test_audit_events_have_one_total_order_per_request(cols):
    _, events = cols
    rid = f"{TAG}-req"
    await events.insert_one({"_id": uuid.uuid4().hex, "request_id": rid, "seq": 1})
    with pytest.raises(DuplicateKeyError):
        await events.insert_one({"_id": uuid.uuid4().hex, "request_id": rid, "seq": 1})
    await events.insert_one({"_id": uuid.uuid4().hex, "request_id": rid, "seq": 2})


async def test_startup_warns_while_off_and_refuses_once_on(cols, monkeypatch):
    requests, _ = cols
    await requests.drop_index("review_requests_lawyer_inbox")
    try:
        monkeypatch.setattr(settings, "document_review_requests", False)
        problems = await indexes.enforce_review_request_indexes()
        assert [p.name for p in problems] == ["review_requests_lawyer_inbox"]

        monkeypatch.setattr(settings, "document_review_requests", True)
        with pytest.raises(indexes.MissingReviewRequestIndexes, match="review_requests_lawyer_inbox"):
            await indexes.enforce_review_request_indexes()
    finally:
        await indexes._review_request_indexes()
    assert await indexes.validate_review_request_indexes() == []
