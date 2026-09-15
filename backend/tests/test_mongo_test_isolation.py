"""The suite must never reach for the application's own database.

The `mongo` fixture used to fall back to `settings.mongodb_url` when a local
instance was unreachable. That URI points at the hosted cluster, and the
consequences were not limited to speed:

  * a green run stopped meaning the guarantees held, because a DNS blip turned
    real assertions into skips;
  * the hosted cluster does not carry the V2 unique indexes, and those indexes
    ARE the guarantee that concurrent generation is idempotent — so a correct
    implementation failed there, and could have passed there while broken.

These tests cover the guard rather than trusting it, because a safety check
nobody exercises is a safety check that quietly stops working.
"""
from __future__ import annotations

import secrets

import pytest
from pymongo.errors import DuplicateKeyError

from tests.conftest import (
    TEST_DB_SUFFIX,
    _looks_like_the_configured_uri,
    ensure_ocr_indexes,
)


# ── the host comparison ──────────────────────────────────────────────────────

@pytest.mark.parametrize("candidate", [
    "mongodb+srv://cluster0.abcd.mongodb.net",
    "mongodb+srv://someone:secret@cluster0.abcd.mongodb.net",
    "mongodb+srv://other:pw@cluster0.abcd.mongodb.net/?retryWrites=true",
    "mongodb://cluster0.abcd.mongodb.net/appdb",
])
def test_the_configured_host_is_refused_however_it_is_dressed_up(candidate):
    """Compared on HOST, not on the whole string.

    The configured URI carries credentials and options a hand-written test URI
    would not repeat, so an exact-string check would wave through a candidate
    naming the same server with different credentials. The host is the part that
    decides which database gets written to.
    """
    configured = "mongodb+srv://appuser:realpassword@cluster0.abcd.mongodb.net/?w=majority"
    assert _looks_like_the_configured_uri(candidate, configured) is True


@pytest.mark.parametrize("candidate", [
    "mongodb://localhost:27017",
    "mongodb://127.0.0.1:27017",
    "mongodb://mongo:27017",
    "mongodb+srv://user:pw@throwaway.efgh.mongodb.net",
])
def test_a_genuinely_different_host_is_allowed(candidate):
    configured = "mongodb+srv://appuser:pw@cluster0.abcd.mongodb.net"
    assert _looks_like_the_configured_uri(candidate, configured) is False


def test_a_local_configured_uri_does_not_lock_the_developer_out():
    """A developer whose app already points at localhost is not aiming at
    production, and refusing that would make the suite unrunnable for them."""
    assert _looks_like_the_configured_uri(
        "mongodb://localhost:27017", "mongodb://localhost:27017") is False


def test_nothing_is_refused_when_there_is_nothing_to_compare():
    assert _looks_like_the_configured_uri(None, "mongodb://x") is False
    assert _looks_like_the_configured_uri("mongodb://x", "") is False


# ── the fixture's own shape ──────────────────────────────────────────────────

def test_the_fixture_offers_no_configured_fallback():
    """Read from the source, because the behaviour under test is what the
    fixture does when a local Mongo is ABSENT — which cannot be provoked from
    inside a test that needs Mongo to run."""
    from pathlib import Path
    source = (Path(__file__).resolve().parent / "conftest.py").read_text(
        encoding="utf-8")
    # The helper is defined ABOVE the fixture, so slice forward to the index
    # block instead — slicing to it produced an empty string and an assertion
    # that passed against nothing.
    # Bounded by what now follows the fixture. The previous bound was
    # `_V2_UNIQUE_INDEXES`, a list the fixture no longer keeps — it reads the
    # production manifest instead — so the slice raised rather than silently
    # shrinking to nothing.
    body = source[source.index("async def mongo()"):
                  source.index("async def ensure_v2_indexes")]
    assert len(body) > 500, "the fixture body was not located"

    # The candidate list is the explicit override or localhost. Never the
    # configured URI — that was the fallback, and it is gone.
    assert 'candidates = [explicit] if explicit else ["mongodb://localhost:27017"]' in body
    assert "original_url," not in body, (
        "the configured URI is back in the candidate list")
    assert "_looks_like_the_configured_uri" in body
    assert "await ensure_ocr_indexes(db)" in body, (
        "integration tests no longer install the OCR correctness index")


@pytest.mark.integration
async def test_an_integration_test_only_ever_sees_a_test_database(mongo):
    # The tripwire, exercised. If the db-name override is removed or shadowed,
    # this fails rather than the suite discovering it by writing to the real one.
    assert mongo.name.endswith(TEST_DB_SUFFIX)


@pytest.mark.integration
async def test_the_correctness_indexes_are_present_for_every_integration_test(mongo):
    """Not an optimisation: `(document_id, idempotency_key)` unique is what
    makes concurrent generation idempotent, and nothing in the application
    creates it at test time."""
    info = await mongo["document_revisions"].index_information()
    assert "uniq_revision_document_idempotency" in info
    assert info["uniq_revision_document_idempotency"].get("unique") is True
    assert "uniq_revision_document_version" in info


@pytest.mark.integration
async def test_the_real_ocr_idempotency_index_is_present_and_enforced(mongo):
    """Prove the constraint against Mongo, not only a recording fake."""
    col = mongo["ocr_revisions"]
    # Do not inherit a green result from an earlier application startup. Remove
    # the exact test-only index and prove the fixture helper reconstructs it
    # from the production repository declaration.
    info = await col.index_information()
    if "uniq_ocr_revision_identity" in info:
        await col.drop_index("uniq_ocr_revision_identity")
    await ensure_ocr_indexes(mongo)

    info = await col.index_information()
    index = info.get("uniq_ocr_revision_identity")
    assert index is not None
    assert index.get("key") == [("owner_id", 1), ("idempotency_key", 1)]
    assert index.get("unique") is True

    marker = secrets.token_urlsafe(18)
    await col.delete_many({"owner_id": marker})
    try:
        await col.insert_one({
            "_id": f"{marker}-one",
            "owner_id": marker,
            "idempotency_key": "same-reading",
        })
        with pytest.raises(DuplicateKeyError):
            await col.insert_one({
                "_id": f"{marker}-two",
                "owner_id": marker,
                "idempotency_key": "same-reading",
            })
    finally:
        await col.delete_many({"owner_id": marker})
