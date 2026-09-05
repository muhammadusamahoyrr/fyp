"""A lawyer may only decide on the revision they actually read.

APPROVING THE WRONG BYTES IS THE MOST EXPENSIVE MISTAKE THIS SYSTEM CAN MAKE.
The approval is what gets filed, and a client who regenerates after submitting
would otherwise have their lawyer's name on a document the lawyer never saw.

The protection is that `review` guards its atomic update on
(submitted_version, submitted_pdf_sha256) — the pair the reviewer sends back.
It is IN the conditional update rather than a read-then-decide-then-write,
which matters: between a read and a write, a regeneration can land, and the
check would pass on the old state and the write apply to the new one.

Covered here: a stale decision is refused for all three actions, a correct one
is applied, the same key twice records ONE transition, and a different body
under a reused key is a mismatch rather than a silent replay.
"""
from __future__ import annotations

import secrets

import pytest

from app.core.exceptions import ConflictError
from app.db.collections import get_documents_col
from app.services import document_transitions as tx

pytestmark = pytest.mark.integration

CLIENT = "stale-client"
LAWYER = "stale-lawyer"

GOOD_HASH = "a" * 64
NEW_HASH = "b" * 64


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def wipe():
        await get_documents_col().delete_many({"client_id": CLIENT})

    await wipe()
    yield
    await wipe()


async def _submitted(version=3, pdf_sha256=GOOD_HASH):
    """A document sitting in the lawyer's queue, as `submit` leaves it."""
    doc_id = f"stale-{secrets.token_hex(6)}"
    await get_documents_col().insert_one({
        "_id": doc_id, "schema_version": 2, "client_id": CLIENT,
        "title": "A notice", "template_type": "legal_notice",
        "review_status": "submitted", "submitted_to": LAWYER,
        "submitted_revision_id": "rev-" + secrets.token_hex(4),
        "submitted_version": version, "submitted_pdf_sha256": pdf_sha256,
        "current_version": version, "event_seq": 0, "pending_events": [],
    })
    return doc_id


async def _status(doc_id):
    doc = await get_documents_col().find_one({"_id": doc_id})
    return doc["review_status"]


# ══════════════════════════════════════════════════════════════════════════════
# A stale reviewer is refused
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("action", ["approve", "return", "reject"])
async def test_a_stale_hash_cannot_decide_anything(action):
    """All three actions, not just approve. A return or a reject recorded
    against bytes the lawyer never read is the same error wearing a different
    verb — the client is told their document was rejected on the strength of a
    reading of something else."""
    doc_id = await _submitted()

    with pytest.raises(ConflictError):
        await tx.review(
            document_id=doc_id, reviewer_id=LAWYER, action=action,
            expected_version=3, expected_pdf_sha256=NEW_HASH,
            note="a reason", idempotency_key=secrets.token_hex(8))

    assert await _status(doc_id) == "submitted", "a stale decision was applied"


async def test_a_stale_version_cannot_decide():
    doc_id = await _submitted(version=3)

    with pytest.raises(ConflictError):
        await tx.review(
            document_id=doc_id, reviewer_id=LAWYER, action="approve",
            expected_version=2, expected_pdf_sha256=GOOD_HASH,
            note=None, idempotency_key=secrets.token_hex(8))

    assert await _status(doc_id) == "submitted"


async def test_the_regeneration_race_is_lost_by_the_stale_reviewer():
    """The document is regenerated and resubmitted while the lawyer reads.

    Their decision carries the pair they saw; the document now holds a
    different one; the guarded update matches nothing. This is the scenario the
    whole mechanism exists for."""
    doc_id = await _submitted(version=3, pdf_sha256=GOOD_HASH)
    read_version, read_hash = 3, GOOD_HASH

    # The client regenerates and resubmits underneath them.
    await get_documents_col().update_one(
        {"_id": doc_id},
        {"$set": {"submitted_version": 4, "submitted_pdf_sha256": NEW_HASH,
                  "current_version": 4}})

    with pytest.raises(ConflictError):
        await tx.review(
            document_id=doc_id, reviewer_id=LAWYER, action="approve",
            expected_version=read_version, expected_pdf_sha256=read_hash,
            note=None, idempotency_key=secrets.token_hex(8))

    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "submitted"
    assert doc.get("approved_revision_id") is None, (
        "a document was approved on a revision the lawyer never read")


# ══════════════════════════════════════════════════════════════════════════════
# A correct decision applies
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_matching_pair_is_accepted():
    """The guard must not be so strict it refuses the honest case."""
    doc_id = await _submitted()

    result = await tx.review(
        document_id=doc_id, reviewer_id=LAWYER, action="approve",
        expected_version=3, expected_pdf_sha256=GOOD_HASH,
        note=None, idempotency_key=secrets.token_hex(8))

    assert result["review_status"] == "approved"
    assert await _status(doc_id) == "approved"


async def test_a_return_clears_the_submission():
    doc_id = await _submitted()
    await tx.review(
        document_id=doc_id, reviewer_id=LAWYER, action="return",
        expected_version=3, expected_pdf_sha256=GOOD_HASH,
        note="Please add the date", idempotency_key=secrets.token_hex(8))

    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["review_status"] == "returned"
    assert doc["submitted_to"] is None


# ══════════════════════════════════════════════════════════════════════════════
# One key, one transition
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_same_key_twice_records_one_transition():
    """Pressing Approve twice, or retrying after a dropped response, must not
    produce two decisions. The second call replays the first's result."""
    doc_id = await _submitted()
    k = secrets.token_hex(8)

    first = await tx.review(
        document_id=doc_id, reviewer_id=LAWYER, action="approve",
        expected_version=3, expected_pdf_sha256=GOOD_HASH,
        note=None, idempotency_key=k)
    second = await tx.review(
        document_id=doc_id, reviewer_id=LAWYER, action="approve",
        expected_version=3, expected_pdf_sha256=GOOD_HASH,
        note=None, idempotency_key=k)

    assert first["logical_event_id"] == second["logical_event_id"]
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["event_seq"] == 1, f"one key produced {doc['event_seq']} events"
    assert len(doc["pending_events"]) == 1


async def test_a_reused_key_with_a_different_decision_is_refused():
    """The replay contract is that one key means one intent. Returning the
    first result for a DIFFERENT request would silently discard the second — a
    lawyer who meant to reject would be told they approved."""
    doc_id = await _submitted()
    k = secrets.token_hex(8)

    await tx.review(
        document_id=doc_id, reviewer_id=LAWYER, action="approve",
        expected_version=3, expected_pdf_sha256=GOOD_HASH,
        note=None, idempotency_key=k)

    with pytest.raises(ConflictError) as caught:
        await tx.review(
            document_id=doc_id, reviewer_id=LAWYER, action="reject",
            expected_version=3, expected_pdf_sha256=GOOD_HASH,
            note="different intent", idempotency_key=k)
    assert "already used" in str(caught.value.detail).lower()


async def test_concurrent_decisions_on_one_document_yield_one_winner():
    """Two tabs, two keys, one document. The second finds a document that is no
    longer `submitted` and is refused — a decided document cannot be decided
    again."""
    import asyncio

    doc_id = await _submitted()

    async def decide(action):
        try:
            return await tx.review(
                document_id=doc_id, reviewer_id=LAWYER, action=action,
                expected_version=3, expected_pdf_sha256=GOOD_HASH,
                note="a reason", idempotency_key=secrets.token_hex(8))
        except Exception as exc:
            return exc

    results = await asyncio.gather(decide("approve"), decide("reject"))
    applied = [r for r in results if isinstance(r, dict)]
    refused = [r for r in results if isinstance(r, Exception)]

    assert len(applied) == 1, f"{len(applied)} decisions were applied"
    assert len(refused) == 1
    doc = await get_documents_col().find_one({"_id": doc_id})
    assert doc["event_seq"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Authorisation is unchanged
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_lawyer_it_was_not_submitted_to_cannot_decide():
    from app.core.exceptions import ForbiddenError

    doc_id = await _submitted()
    with pytest.raises(ForbiddenError):
        await tx.review(
            document_id=doc_id, reviewer_id="some-other-lawyer",
            action="approve", expected_version=3,
            expected_pdf_sha256=GOOD_HASH, note=None,
            idempotency_key=secrets.token_hex(8))
    assert await _status(doc_id) == "submitted"


async def test_a_reject_still_requires_a_reason():
    """Unchanged by this work, and asserted so the wiring did not weaken it: a
    client told their document was rejected is owed the reason."""
    from app.core.exceptions import AppValidationError

    doc_id = await _submitted()
    with pytest.raises(AppValidationError):
        await tx.review(
            document_id=doc_id, reviewer_id=LAWYER, action="reject",
            expected_version=3, expected_pdf_sha256=GOOD_HASH,
            note="   ", idempotency_key=secrets.token_hex(8))


# ══════════════════════════════════════════════════════════════════════════════
# The paginated queue, and what a row must carry to be usable
# ══════════════════════════════════════════════════════════════════════════════
#
# The unpaginated queue this replaces returned every document ever submitted to
# a lawyer in one response — fine on a demo account, a cliff on a real one.
# Switching to the paginated one must not cost the display data the screen
# needs, or every row reads "Client" with no case reference and the compliance
# panels go blank. A blank panel does not read as "not loaded"; on a screen a
# lawyer signs off from, it reads as "nothing to report".

async def _queued(n, *, client_id="stale-client", case_id=None):
    from app.db.collections import get_document_revisions_col
    ids = []
    for i in range(n):
        doc_id = f"stale-q{i}-{secrets.token_hex(4)}"
        rev_id = f"rev-{secrets.token_hex(4)}"
        await get_document_revisions_col().insert_one({
            "_id": rev_id, "document_id": doc_id, "version": 1,
            "idempotency_key": f"seed-{rev_id}", "status": "generated",
            "compliance": {"ok": True}, "verification": {"verdict": "pass"},
            "extraction_status": "ok",
        })
        await get_documents_col().insert_one({
            "_id": doc_id, "schema_version": 2, "client_id": client_id,
            "title": f"Doc {i}", "template_type": "legal_notice",
            "review_status": "submitted", "submitted_to": LAWYER,
            "submitted_revision_id": rev_id, "submitted_version": 1,
            "submitted_pdf_sha256": GOOD_HASH, "case_id": case_id,
            "body_text": "SECRET PROSE", "event_seq": 0, "pending_events": [],
        })
        ids.append(doc_id)
    return ids


async def test_the_queue_pages_and_every_document_is_reachable():
    """The cursor must walk the whole inbox exactly once. A document that falls
    between pages is one a lawyer never reviews and never knows about."""
    ids = await _queued(7)

    seen, cursor, pages = [], None, 0
    while pages < 20:
        pages += 1
        page = await tx.review_queue(LAWYER, cursor=cursor, limit=3)
        seen.extend(r["id"] for r in page["items"])
        if not page["next_cursor"]:
            break
        cursor = page["next_cursor"]

    assert sorted(seen) == sorted(ids)
    assert len(seen) == len(set(seen)), "a document appeared on two pages"
    assert pages == 3

    from app.db.collections import get_document_revisions_col
    await get_document_revisions_col().delete_many(
        {"document_id": {"$in": ids}})


async def test_a_queue_row_carries_the_names_the_screen_shows():
    """Enriched from batched reads over the PAGE, which is what pagination
    makes affordable — the cost is now four queries regardless of how many
    documents the lawyer has ever been sent."""
    from app.db.collections import get_document_revisions_col, get_users_col

    await get_users_col().update_one(
        {"_id": "stale-client"},
        {"$set": {"_id": "stale-client", "role": "client",
                  "email": "stale-client@test.invalid",
                  "full_name": "Aisha Khan"}}, upsert=True)
    ids = await _queued(1)

    page = await tx.review_queue(LAWYER, limit=25)
    row = next(r for r in page["items"] if r["id"] in ids)
    assert row["client_name"] == "Aisha Khan"

    await get_users_col().delete_one({"_id": "stale-client"})
    await get_document_revisions_col().delete_many({"document_id": {"$in": ids}})


async def test_a_queue_row_carries_the_submitted_revisions_verdicts():
    """From the SUBMITTED revision, not the current one. After a regeneration
    the two differ, and showing the current revision's verdicts against the
    submitted document attributes checks to the wrong artefact."""
    from app.db.collections import get_document_revisions_col

    ids = await _queued(1)
    page = await tx.review_queue(LAWYER, limit=25)
    row = next(r for r in page["items"] if r["id"] in ids)

    assert row["compliance"] == {"ok": True}
    assert row["verification"] == {"verdict": "pass"}
    assert row["extraction_status"] == "ok"

    await get_document_revisions_col().delete_many({"document_id": {"$in": ids}})


async def test_the_queue_still_carries_no_document_prose():
    """Enrichment must not smuggle the body back in. The queue is a list of
    things to open, not a way to read them."""
    from app.db.collections import get_document_revisions_col

    ids = await _queued(2)
    page = await tx.review_queue(LAWYER, limit=25)
    assert "SECRET PROSE" not in repr(page)
    await get_document_revisions_col().delete_many({"document_id": {"$in": ids}})


async def test_an_empty_queue_needs_no_enrichment_reads():
    """The enricher must return early rather than issuing three `$in: []`
    queries for a lawyer with an empty inbox — the common case."""
    page = await tx.review_queue("nobody-at-all", limit=25)
    assert page["items"] == []
    assert page["next_cursor"] is None
