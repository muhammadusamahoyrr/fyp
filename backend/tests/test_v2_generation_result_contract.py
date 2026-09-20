"""What `generate_revision` returns when it loses the select CAS.

THE DEFECT THIS CLOSES

`promote()` guards on five conditions at once -- id, pending status, lease
owner, fence, and a live lease -- and returns one `None` for all of them. The
service turned that single `None` into `find_by_id(revision_id)` and returned
whatever came back. Two things went wrong with that:

  * The row could be GONE, so the service returned `None`, and the route's
    projection did `rev["_id"]` -- a `TypeError`, surfacing as a 500 for an
    outcome the design had fully anticipated. Observed in a full-suite run:

        tests/test_v2_queue_and_ownership.py::test_the_tabs_partition_the_queue
        app/api/v1/routes/documents_v2.py:316
        TypeError: 'NoneType' object is not subscriptable
        log: v2 XWudz0MApnoE5lUteu9wqw: lost lease at select; another actor will finish

  * The row could be PENDING -- another worker mid-render -- and the caller
    received a revision id with a null `pdf_sha256` as though generation had
    succeeded. That is the same false-completion failure `_await_terminal`
    already exists to prevent on the idempotency-race path.

So the contract is now: a TERMINAL revision, or a typed error. Never `None`,
never a pending row.

These tests drive the conditions DETERMINISTICALLY by writing the revision row
into the exact state each represents, rather than by racing real workers and
hoping. No provider is called; storage is the per-test tmp root.
"""
from __future__ import annotations

import asyncio
import secrets
from datetime import timedelta

import pytest

from app.core.config import settings
from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import document_v2_service as v2
from app.services import artifact_store as store

pytestmark = pytest.mark.integration

CLIENT = {"_id": "grc-client", "role": "client"}


@pytest.fixture(autouse=True)
def enabled(monkeypatch, tmp_path):
    """V2 on, and every byte written under this test's own tmp directory."""
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def clean(mongo):
    async def wipe():
        async for doc in get_documents_col().find({"client_id": CLIENT["_id"]}):
            await get_document_revisions_col().delete_many(
                {"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": CLIENT["_id"]})
    await wipe()
    yield
    await wipe()


async def _document() -> str:
    doc = await v2.create_document(
        client_id=CLIENT["_id"], case_id=None, template_type="legal_notice",
        title="A notice", idempotency_key=secrets.token_urlsafe(8))
    return doc["_id"]


async def _pending_revision(document_id: str, *, owner: str, fence: int,
                            lease_seconds: int = 300) -> str:
    """A revision row in exactly the state a live render would hold."""
    revision_id = secrets.token_urlsafe(12)
    now = v2._now()
    await get_document_revisions_col().insert_one({
        "_id": revision_id,
        "document_id": document_id,
        "idempotency_key": secrets.token_urlsafe(8),
        "version": 1,
        "status": "pending",
        "lease_owner": owner,
        "lease_expires_at": now + timedelta(seconds=lease_seconds),
        "fence": fence,
        "template_type": "legal_notice",
        "fields": {},
        "created_at": now,
    })
    return revision_id


# ══════════════════════════════════════════════════════════════════════════════
# Classification -- five conditions, five answers
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_deleted_revision_is_classified_as_missing():
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().delete_one({"_id": revision_id})

    reason, row = await v2._classify_lost_promotion(revision_id, "w1", 0)

    assert reason == v2.LOST_REVISION_MISSING
    assert row is None


@pytest.mark.parametrize("status", ["generated", "failed"])
async def test_a_finished_takeover_is_classified_as_completed(status):
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().update_one(
        {"_id": revision_id}, {"$set": {"status": status}})

    reason, row = await v2._classify_lost_promotion(revision_id, "w1", 0)

    assert reason == v2.LOST_TAKEOVER_COMPLETED
    assert row["status"] == status


async def test_a_steal_that_changed_owner_and_fence_is_a_pending_takeover():
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().update_one(
        {"_id": revision_id},
        {"$set": {"lease_owner": "reconciler", "fence": 1}})

    reason, _ = await v2._classify_lost_promotion(revision_id, "w1", 0)

    assert reason == v2.LOST_TAKEOVER_PENDING


async def test_an_expired_lease_we_still_own_is_classified_as_expiry():
    """Distinct from a takeover: nobody has stolen it, our own lease lapsed.
    The reconciler has not arrived yet, and the answer is 'wait', not 'gone'."""
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().update_one(
        {"_id": revision_id},
        {"$set": {"lease_expires_at": v2._now() - timedelta(seconds=1)}})

    reason, _ = await v2._classify_lost_promotion(revision_id, "w1", 0)

    assert reason == v2.LOST_LEASE_EXPIRED


async def test_an_unmodelled_state_is_named_rather_than_guessed():
    """Everything the CAS checks still holds. That should not happen, and if it
    does the report says so instead of inventing a cause."""
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)

    reason, _ = await v2._classify_lost_promotion(revision_id, "w1", 0)

    assert reason == v2.LOST_UNCLASSIFIED


# ══════════════════════════════════════════════════════════════════════════════
# Resolution -- a documented result or a typed error, never None
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_missing_revision_raises_not_found_and_is_not_recreated(monkeypatch):
    """And answers quickly rather than holding the request open.

    The wait exists for work still in flight. A revision that no longer exists is
    not in flight, so the dedicated branch answers without entering it.

    HONEST LIMIT OF THIS ASSERTION: removing that branch does NOT fail this test,
    and mutation testing confirmed it. `_await_terminal_revision` polls every
    `_AWAIT_POLL_SECONDS` and raises `NotFoundError` on its first look, so the
    fallback reaches the same answer ~50ms later. The branch is a clarity and
    latency choice, not a correctness boundary, and this guards only against a
    regression that made the missing case wait out the full deadline.
    """
    monkeypatch.setattr(v2, "_AWAIT_TERMINAL_SECONDS", 30.0)
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().delete_one({"_id": revision_id})

    started = asyncio.get_running_loop().time()
    with pytest.raises(NotFoundError):
        await v2._resolve_lost_promotion(revision_id, "w1", 0)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 1.0, f"waited {elapsed:.2f}s for a revision that is gone"
    assert await get_document_revisions_col().find_one({"_id": revision_id}) is None, \
        "a deleted revision must never be resurrected by the loser of the race"


async def test_a_completed_takeover_returns_the_winners_result():
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().update_one(
        {"_id": revision_id},
        {"$set": {"status": "generated", "lease_owner": "w2", "fence": 1,
                  "pdf_sha256": "deadbeef"}})

    result = await v2._resolve_lost_promotion(revision_id, "w1", 0)

    assert result["status"] == "generated"
    assert result["pdf_sha256"] == "deadbeef"


async def test_a_terminal_failure_is_returned_rather_than_retried_silently():
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().update_one(
        {"_id": revision_id}, {"$set": {"status": "failed"}})

    result = await v2._resolve_lost_promotion(revision_id, "w1", 0)

    assert result["status"] == "failed"


async def test_a_pending_takeover_waits_and_then_reports_unavailable(monkeypatch):
    """Bounded wait, then 503 -- 'unknown, retry with the same key'. Never a
    pending row returned as a finished one."""
    monkeypatch.setattr(v2, "_AWAIT_TERMINAL_SECONDS", 0.2)
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().update_one(
        {"_id": revision_id},
        {"$set": {"lease_owner": "reconciler", "fence": 1}})

    with pytest.raises(ServiceUnavailableError):
        await v2._resolve_lost_promotion(revision_id, "w1", 0)


async def test_a_takeover_that_finishes_during_the_wait_returns_its_result(monkeypatch):
    """The wait is not a formality: a winner that lands mid-wait is returned."""
    monkeypatch.setattr(v2, "_AWAIT_TERMINAL_SECONDS", 2.0)
    monkeypatch.setattr(v2, "_AWAIT_POLL_SECONDS", 0.01)
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().update_one(
        {"_id": revision_id},
        {"$set": {"lease_owner": "reconciler", "fence": 1}})

    calls = {"n": 0}
    real_find = v2.revision_repo.find_by_id

    async def finish_on_second_poll(rid):
        calls["n"] += 1
        if calls["n"] == 2:
            await get_document_revisions_col().update_one(
                {"_id": rid}, {"$set": {"status": "generated",
                                        "pdf_sha256": "cafebabe"}})
        return await real_find(rid)

    monkeypatch.setattr(v2.revision_repo, "find_by_id", finish_on_second_poll)

    result = await v2._resolve_lost_promotion(revision_id, "w1", 0)

    assert result["status"] == "generated"
    assert result["pdf_sha256"] == "cafebabe"


async def test_a_revision_deleted_during_the_wait_raises_not_found(monkeypatch):
    monkeypatch.setattr(v2, "_AWAIT_TERMINAL_SECONDS", 2.0)
    monkeypatch.setattr(v2, "_AWAIT_POLL_SECONDS", 0.01)
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().update_one(
        {"_id": revision_id},
        {"$set": {"lease_owner": "reconciler", "fence": 1}})

    real_find = v2.revision_repo.find_by_id

    async def delete_then_find(rid):
        await get_document_revisions_col().delete_one({"_id": rid})
        return await real_find(rid)

    monkeypatch.setattr(v2.revision_repo, "find_by_id", delete_then_find)

    with pytest.raises(NotFoundError):
        await v2._resolve_lost_promotion(revision_id, "w1", 0)


async def test_resolution_never_writes_to_the_revision():
    """FENCING. The loser of a race must not promote, fail, re-lease or repoint.
    Asserted over the stored row rather than by reading the code."""
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_document_revisions_col().update_one(
        {"_id": revision_id},
        {"$set": {"status": "generated", "lease_owner": "w2", "fence": 3}})
    before = await get_document_revisions_col().find_one({"_id": revision_id})

    await v2._resolve_lost_promotion(revision_id, "w1", 0)

    after = await get_document_revisions_col().find_one({"_id": revision_id})
    assert after == before, "the losing worker modified a revision it does not own"


async def test_a_document_deleted_during_generation_is_not_repointed():
    """The document row is gone; nothing may recreate it or point it anywhere."""
    document_id = await _document()
    revision_id = await _pending_revision(document_id, owner="w1", fence=0)
    await get_documents_col().delete_one({"_id": document_id})
    await get_document_revisions_col().delete_one({"_id": revision_id})

    with pytest.raises(NotFoundError):
        await v2._resolve_lost_promotion(revision_id, "w1", 0)

    assert await get_documents_col().find_one({"_id": document_id}) is None


# ══════════════════════════════════════════════════════════════════════════════
# generate_revision itself -- the wiring, not just the helpers
# ══════════════════════════════════════════════════════════════════════════════
#
# The tests above exercise `_classify_lost_promotion` and
# `_resolve_lost_promotion` directly. Mutation testing showed that leaves the
# BRANCH IN `generate_revision` that calls them completely uncovered: disabling
# it entirely still passed every test in this file. These close that.


async def _generate(document_id: str):
    return await v2.generate_revision(
        document_id=document_id, template_type="legal_notice",
        fields={"sender_name": "A", "recipient_name": "B", "demand": "pay"},
        idempotency_key=secrets.token_urlsafe(8))


async def test_generate_revision_never_returns_none_when_the_cas_is_lost(monkeypatch):
    """The observed production failure, reproduced at its source.

    `_render_and_select` returning None used to travel straight out of
    `generate_revision` to the route's projection.
    """
    async def lost(**kwargs):
        return None

    monkeypatch.setattr(v2, "_render_and_select", lost)
    document_id = await _document()

    with pytest.raises((NotFoundError, ServiceUnavailableError)) as raised:
        await _generate(document_id)

    assert raised.value.status_code in (404, 503)


async def test_generate_revision_never_returns_a_pending_row(monkeypatch):
    """The quieter half of the defect: a pending row presented as finished.

    A caller receiving this would store a null `pdf_sha256`, then submit with it
    and be told the document had changed since they loaded it. It had not; it had
    not been written yet.
    """
    captured = {}

    async def lost_but_pending(**kwargs):
        captured["revision_id"] = kwargs["revision_id"]
        return await v2.revision_repo.find_by_id(kwargs["revision_id"])

    monkeypatch.setattr(v2, "_render_and_select", lost_but_pending)
    monkeypatch.setattr(v2, "_AWAIT_TERMINAL_SECONDS", 0.2)
    document_id = await _document()

    with pytest.raises(ServiceUnavailableError):
        await _generate(document_id)

    stored = await get_document_revisions_col().find_one(
        {"_id": captured["revision_id"]})
    assert stored["status"] == "pending", "the row really was mid-flight"


async def test_a_genuinely_generated_result_passes_straight_through(monkeypatch):
    """The counterweight: the resolver must not intercept a real success."""
    async def promoted(**kwargs):
        return {"_id": kwargs["revision_id"], "status": "generated",
                "pdf_sha256": "abc123"}

    monkeypatch.setattr(v2, "_render_and_select", promoted)
    document_id = await _document()

    result = await _generate(document_id)

    assert result["status"] == "generated"
    assert result["pdf_sha256"] == "abc123"


# ══════════════════════════════════════════════════════════════════════════════
# The HTTP error contract
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_typed_errors_carry_the_documented_status_codes():
    """404 for gone, 503 for in-flight. Both are `HTTPException` subclasses, so
    FastAPI renders them; neither is the 500 this defect used to produce."""
    assert NotFoundError("Document revision").status_code == 404
    assert ServiceUnavailableError("x").status_code == 503


@pytest.mark.parametrize("raised_by_service, status, code", [
    (lambda: ServiceUnavailableError(
        "This document is still being generated — try again in a moment."),
     503, "backlog_unavailable"),
    (lambda: NotFoundError("Document revision"), 404, "not_found"),
])
async def test_the_route_answers_a_lost_race_with_its_documented_error(
        monkeypatch, raised_by_service, status, code):
    """The exact failing call from the observed trace, asserted end to end.

    `generate_revision_v2` -> `_revision_public(rev)`. Before the fix a lost CAS
    reached that projection as None and died with a TypeError -- a 500. Now the
    service raises a typed error first, and the route translates it into the
    documented envelope rather than letting anything reach the projection.
    """
    from fastapi import HTTPException

    from app.api.v1.routes import documents_v2 as route

    async def lost_cas(*args, **kwargs):
        raise raised_by_service()

    monkeypatch.setattr(v2, "generate_revision", lost_cas)

    document_id = await _document()
    with pytest.raises(HTTPException) as raised:
        await route.generate_revision_v2(
            document_id,
            route.GenerateBody(template_type="legal_notice",
                               fields={"sender_name": "A", "recipient_name": "B",
                                       "demand": "pay"}),
            idempotency_key=secrets.token_urlsafe(8), current_user=CLIENT)

    assert raised.value.status_code == status
    assert raised.value.detail["code"] == code
    assert not isinstance(raised.value, TypeError)
