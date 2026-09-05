"""DOCUMENTS_V2 · the rollback manifest as an INPUT, not as a fact.

The CAS added earlier guards WHICH documents rollback may touch. It says nothing
about WHAT rollback does to them, and that came straight out of the manifest:

    unset = {f: "" for f in entry.get("added_fields", [])}

`added_fields` is data. It arrives from a JSON file an operator kept from an
earlier run, through whatever moved it between machines. Any name in that list
becomes a `$unset` on a production document — `client_id`, `fields`,
`review_cycles`, `_id` — and the CAS happily permits it, because the CAS is
checking that the document is the one the entry names, not that the entry is
sane.

So the guard covered the target and left the weapon unchecked. And the moment
this runs is the moment nobody is inspecting JSON by hand: something has gone
wrong, and rollback is the thing that is supposed to make it safe.

WHAT THIS ADDS

  * an ALLOWLIST of the fields migration actually owns — nothing else can be
    unset, whatever a manifest says;
  * a schema version, so a manifest from a different build is refused rather
    than half-understood;
  * a deterministic fingerprint over the WHOLE manifest, so a single altered
    byte is detectable;
  * validation of every entry BEFORE the first write, so a tampered manifest
    performs no writes at all rather than stopping half-way.

That last property is the one that matters. A rollback that validates as it goes
leaves an estate that is neither migrated nor rolled back, and no record of
where it stopped.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_migration as mig
from app.services import pleading_rules
from app.services.pdf_generator import generate_pdf

pytestmark = pytest.mark.integration

CLIENT = "rb-manifest-client"


@pytest.fixture
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture(autouse=True)
async def _clean(mongo):
    async def _wipe():
        await get_document_revisions_col().delete_many({})
        await get_documents_col().delete_many({})

    await _wipe()
    yield
    await _wipe()


def _fields():
    return {"sender_name": "A", "recipient_name": "B",
            "notice_body": "Breach under the contract.", "demand": "Pay",
            "date": "1 January 2026"}


async def _legacy_doc(*, review_status=None, reviewer=None):
    doc_id = "legacy-" + uuid.uuid4().hex[:10]
    fields = _fields()
    doc = {
        "_id": doc_id, "client_id": CLIENT, "case_id": None,
        "template_type": "legal_notice", "title": "Legal Notice", "fields": fields,
        "compliance": pleading_rules.check_pleading("legal_notice", fields),
        "verification": {"ran": False},
        "file_path": str(generate_pdf(doc_id, "legal_notice", fields)),
        "status": "generated", "created_at": datetime.now(timezone.utc),
    }
    if review_status is not None:
        doc["review_status"] = review_status
    if reviewer:
        doc["submitted_to"] = reviewer
    await get_documents_col().insert_one(doc)
    return doc_id


async def _migrate(n=1, **kw):
    ids = [await _legacy_doc(**kw) for _ in range(n)]
    manifest = await mig.dry_run()
    res = await mig.apply(mig.approve(manifest, "rb-test"))
    return ids, res["rollback_plan"]


async def _snapshot():
    return {d["_id"]: d async for d in get_documents_col().find({})}


async def _assert_no_writes(before):
    assert await _snapshot() == before, "a rejected manifest still wrote"


# ── the plan is a structure, not a bare list ─────────────────────────────────

async def test_apply_returns_a_versioned_fingerprinted_plan(mongo, _store):
    _, plan = await _migrate()
    assert plan["rollback_schema_version"] == mig.ROLLBACK_SCHEMA_VERSION
    assert plan["migration_id"]
    assert plan["fingerprint"] == mig.rollback_fingerprint(plan)
    assert len(plan["entries"]) == 1


async def test_the_fingerprint_is_deterministic(mongo, _store):
    _, plan = await _migrate(3)
    assert mig.rollback_fingerprint(plan) == mig.rollback_fingerprint(plan)

    # Key order is not a difference in meaning; a byte of content is.
    reordered = dict(plan)
    reordered["entries"] = [dict(reversed(list(e.items()))) for e in plan["entries"]]
    assert mig.rollback_fingerprint(reordered) == plan["fingerprint"]


# ── the allowlist ────────────────────────────────────────────────────────────

async def test_a_field_migration_does_not_own_is_refused(mongo, _store):
    """THE DEFECT. `added_fields` used to become `$unset` unchallenged."""
    _, plan = await _migrate()
    before = await _snapshot()

    plan["entries"][0]["added_fields"].append("client_id")
    plan["fingerprint"] = mig.rollback_fingerprint(plan)   # even a re-signed one

    with pytest.raises(mig.RollbackRejected) as exc:
        await mig.rollback(plan)
    assert "client_id" in str(exc.value)
    await _assert_no_writes(before)


@pytest.mark.parametrize("field", ["_id", "client_id", "fields", "template_type",
                                   "title", "created_at", "file_path", "status"])
async def test_no_legacy_field_can_be_unset_by_a_manifest(mongo, _store, field):
    """Each one individually. These are the document, not the migration's marks."""
    _, plan = await _migrate()
    before = await _snapshot()

    plan["entries"][0]["added_fields"] = [field]
    plan["fingerprint"] = mig.rollback_fingerprint(plan)

    with pytest.raises(mig.RollbackRejected):
        await mig.rollback(plan)
    await _assert_no_writes(before)


def test_the_allowlist_is_exactly_what_migration_writes():
    """The two lists cannot drift apart.

    A field the migration starts writing but the allowlist does not know about
    would survive a rollback — leaving V2 marks on a document that is otherwise
    legacy again, which is the state nothing else in this module can interpret.
    """
    from app.services.document_migration import (
        ROLLBACK_OWNED_FIELDS, _document_fields, Outcome)

    written: set[str] = set()
    for outcome in mig._OUTCOME_BY_CODE.values():
        fields = _document_fields(
            {"_id": "d", "review_status": "submitted", "submitted_to": "l"},
            outcome, "rev-1",
            mig.SourceSnapshot(True, b"x", "a" * 64, 1),
            "mig-1", datetime.now(timezone.utc))
        written |= set(fields)

    assert written <= ROLLBACK_OWNED_FIELDS, (
        f"migration writes fields rollback cannot remove: "
        f"{sorted(written - ROLLBACK_OWNED_FIELDS)}")


# ── tampering with the entries ───────────────────────────────────────────────

async def test_a_fingerprint_mismatch_is_refused(mongo, _store):
    _, plan = await _migrate()
    before = await _snapshot()

    plan["entries"][0]["prev_review_status"] = "approved"   # not re-signed

    with pytest.raises(mig.RollbackRejected) as exc:
        await mig.rollback(plan)
    assert "fingerprint" in str(exc.value).lower()
    await _assert_no_writes(before)


async def test_a_duplicate_document_entry_is_refused(mongo, _store):
    """Two entries for one document cannot both be right.

    The second would run against a document the first already changed, so its
    CAS fails and it is reported as skipped — a silent, confusing half-result.
    """
    _, plan = await _migrate()
    before = await _snapshot()

    plan["entries"].append(dict(plan["entries"][0]))
    plan["fingerprint"] = mig.rollback_fingerprint(plan)

    with pytest.raises(mig.RollbackRejected) as exc:
        await mig.rollback(plan)
    assert "duplicate" in str(exc.value).lower()
    await _assert_no_writes(before)


async def test_an_altered_pointer_is_refused(mongo, _store):
    """Redirecting the CAS at another document's revision."""
    _, plan = await _migrate()
    before = await _snapshot()

    plan["entries"][0]["post_current_revision_id"] = "somebody-elses-revision"
    plan["fingerprint"] = mig.rollback_fingerprint(plan)

    with pytest.raises(mig.RollbackRejected):
        await mig.rollback(plan)
    await _assert_no_writes(before)


async def test_an_altered_previous_value_is_refused(mongo, _store):
    """`prev_review_status` is what gets WRITTEN back.

    An entry claiming a document was previously "approved" would restore an
    approval that never existed — a legal claim manufactured by editing a JSON
    file.
    """
    ids, plan = await _migrate(review_status="returned", reviewer="lawyer-1")
    before = await _snapshot()

    plan["entries"][0]["prev_review_status"] = "approved"
    plan["fingerprint"] = mig.rollback_fingerprint(plan)

    with pytest.raises(mig.RollbackRejected):
        await mig.rollback(plan)
    await _assert_no_writes(before)


async def test_a_wrong_schema_version_is_refused(mongo, _store):
    _, plan = await _migrate()
    before = await _snapshot()

    plan["rollback_schema_version"] = 99
    plan["fingerprint"] = mig.rollback_fingerprint(plan)

    with pytest.raises(mig.RollbackRejected):
        await mig.rollback(plan)
    await _assert_no_writes(before)


async def test_a_missing_required_key_is_refused(mongo, _store):
    _, plan = await _migrate()
    before = await _snapshot()

    del plan["entries"][0]["migration_id"]
    plan["fingerprint"] = mig.rollback_fingerprint(plan)

    with pytest.raises(mig.RollbackRejected):
        await mig.rollback(plan)
    await _assert_no_writes(before)


async def test_validation_happens_before_the_first_write(mongo, _store):
    """A bad entry LAST in the list must still stop the good ones ahead of it.

    Validating as it goes would leave an estate that is neither migrated nor
    rolled back, with nothing recording where it stopped.
    """
    ids, plan = await _migrate(4)
    before = await _snapshot()

    plan["entries"][-1]["added_fields"] = ["client_id"]
    plan["fingerprint"] = mig.rollback_fingerprint(plan)

    with pytest.raises(mig.RollbackRejected):
        await mig.rollback(plan)

    await _assert_no_writes(before)
    for doc_id in ids:
        d = await get_documents_col().find_one({"_id": doc_id})
        assert d["schema_version"] == 2, "a document was rolled back anyway"


# ── the happy path and the CAS both survive ──────────────────────────────────

async def test_a_valid_plan_still_rolls_back(mongo, _store):
    ids, plan = await _migrate(2)
    out = await mig.rollback(plan)
    assert out["restored"] == 2 and out["skipped"] == 0
    for doc_id in ids:
        d = await get_documents_col().find_one({"_id": doc_id})
        assert d.get("schema_version") != 2
        assert d.get("migration_id") is None


async def test_the_cas_protections_are_still_in_force(mongo, _store):
    """Validation is added to the guard, not substituted for it."""
    ids, plan = await _migrate()
    await get_documents_col().update_one(
        {"_id": ids[0]}, {"$set": {"event_seq": 1}})

    out = await mig.rollback(plan)
    assert out["restored"] == 0 and out["skipped"] == 1
    assert out["skipped_documents"][0]["reason"] == "reviewed_since_migration"
    d = await get_documents_col().find_one({"_id": ids[0]})
    assert d["schema_version"] == 2


async def test_the_token_is_written_atomically_with_the_migration(mongo, _store):
    """One write, not two.

    The token was briefly stamped by a second `update_one` after the CAS. A
    process dying between the two leaves a document that is migrated and carries
    no token — and the verifier reads a missing token as a tampered plan, so the
    undo would be refused. A crash would have made the migration permanent.
    """
    ids, plan = await _migrate(2)
    for doc_id in ids:
        d = await get_documents_col().find_one({"_id": doc_id})
        assert d["schema_version"] == 2
        assert d["rollback_token"], "migrated without a rollback token"

    entries = {e["document_id"]: e for e in plan["entries"]}
    for doc_id in ids:
        d = await get_documents_col().find_one({"_id": doc_id})
        assert d["rollback_token"] == entries[doc_id]["rollback_token"]
        assert d["rollback_token"] == mig.rollback_entry_token(entries[doc_id])


async def test_the_token_is_removed_by_a_rollback(mongo, _store):
    """It is a migration mark, so it goes when the migration does."""
    ids, plan = await _migrate()
    await mig.rollback(plan)
    d = await get_documents_col().find_one({"_id": ids[0]})
    assert d.get("rollback_token") is None
