"""DOCUMENTS_V2 · migration — every consumed value from ONE guarded snapshot.

`_META_FIELDS` grew from the fields the revision needs — client_id, case_id,
template_type, title, fields, created_at — and the meta-hash and the CAS were
both built from it. But `apply` reads more of the document than that:

    compliance    → copied onto the revision when present
    submitted_at  → the review cycle's `submitted_at`
    reviewed_at   → the review cycle's `decided_at`
    lawyer_note   → the review cycle's `note`
    review_note   → the same, as a fallback

None of those five were in the hash and none were in the CAS. So a change to any
of them, at any point across the whole width of a record — read the document,
extract text, run citation verification, write the artifact, insert the revision
— was invisible. The migration would then write a review cycle whose timestamps
and note came from one version of the document and whose everything-else came
from another.

WHY THAT IS WORSE THAN IT SOUNDS. A mixed review cycle is not a corrupt row that
something later rejects. It is a plausible, well-formed history: a decision
attributed to a lawyer, with a date, and a note that was written about a
different state of the document. Nothing downstream can detect it, and it is an
audit record about a legal document.

The rule this file pins: every value consumed comes from the one guarded
snapshot, or is deterministically recomputed from guarded inputs. A record
either migrates one internally consistent snapshot, or it skips.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store
from app.services import document_migration as mig
from app.services import pleading_rules
from app.services.pdf_generator import generate_pdf

pytestmark = pytest.mark.integration

CLIENT = "mig-snapshot-client"
BASE = datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc)


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


async def _legacy_doc(*, review_status="approved", reviewer="lawyer-1", **extra):
    doc_id = "legacy-" + uuid.uuid4().hex[:10]
    fields = _fields()
    doc = {
        "_id": doc_id, "client_id": CLIENT, "case_id": None,
        "template_type": "legal_notice", "title": "Legal Notice", "fields": fields,
        "compliance": pleading_rules.check_pleading("legal_notice", fields),
        "verification": {"ran": False},
        "file_path": str(generate_pdf(doc_id, "legal_notice", fields)),
        "status": "generated", "created_at": BASE,
        "submitted_at": BASE + timedelta(hours=1),
        "reviewed_at": BASE + timedelta(hours=2),
        "lawyer_note": "The original note.",
        "review_note": "The original review note.",
    }
    if review_status is not None:
        doc["review_status"] = review_status
    if reviewer:
        doc["submitted_to"] = reviewer
    doc.update(extra)
    await get_documents_col().insert_one(doc)
    return doc_id


async def _apply_approved(manifest=None):
    if manifest is None:
        manifest = await mig.dry_run()
    return await mig.apply(mig.approve(manifest, "snapshot-test"))


# ── the contract, stated once ────────────────────────────────────────────────

def test_every_consumed_legacy_field_is_guarded():
    """The audit itself, as an assertion.

    `_CONSUMED_LEGACY_FIELDS` names every field `apply` reads off the legacy
    document to build a revision, a cycle or an attribution. All of them must be
    in the guarded set — otherwise the value reaches the output without anything
    checking it did not change on the way.
    """
    assert mig._CONSUMED_LEGACY_FIELDS <= set(mig._META_FIELDS), (
        "consumed but unguarded: "
        f"{sorted(mig._CONSUMED_LEGACY_FIELDS - set(mig._META_FIELDS))}")


async def test_the_cas_guards_every_consumed_field(mongo, _store):
    doc_id = await _legacy_doc()
    doc = await get_documents_col().find_one({"_id": doc_id})
    guarded = set(mig._cas_filter(doc))
    for field in mig._CONSUMED_LEGACY_FIELDS:
        assert field in guarded, f"{field} is consumed but not CAS-guarded"


async def test_the_manifest_hash_covers_every_consumed_field(mongo, _store):
    """A change to any of them must change the record's fingerprint."""
    doc_id = await _legacy_doc()
    doc = await get_documents_col().find_one({"_id": doc_id})
    baseline = mig._meta_hash(doc)

    for field in mig._CONSUMED_LEGACY_FIELDS:
        altered = dict(doc)
        altered[field] = "something else entirely"
        assert mig._meta_hash(altered) != baseline, \
            f"{field} does not affect the manifest hash"


# ── the races ────────────────────────────────────────────────────────────────

RACES = [
    ("compliance", {"ok": False, "problems": ["changed mid-migration"]}),
    ("submitted_at", BASE + timedelta(days=30)),
    ("reviewed_at", BASE + timedelta(days=31)),
    ("lawyer_note", "A note written during the migration."),
    ("review_note", "A different review note."),
]


@pytest.mark.parametrize("field,new_value", RACES, ids=[f for f, _ in RACES])
async def test_a_concurrent_change_never_produces_mixed_history(
        mongo, _store, monkeypatch, field, new_value):
    """One field at a time, changed at the real async seam.

    `_upsert_revision` is awaited after the metadata check and before the
    document CAS — the widest part of the window, and the point at which the
    revision has already been built from the values read earlier.

    The requirement is not that the write succeeds or fails. It is that the
    document ends up carrying ONE snapshot: either everything from before the
    change, or nothing at all. A cycle whose note came from after the edit and
    whose timestamps came from before is a plausible, unfalsifiable, wrong
    audit record.
    """
    doc_id = await _legacy_doc()
    manifest = await mig.dry_run()

    real_upsert = mig._upsert_revision
    fired: list[str] = []

    async def _edit_then_upsert(revision, **kw):
        if not fired:
            fired.append(field)
            await get_documents_col().update_one(
                {"_id": doc_id}, {"$set": {field: new_value}})
        return await real_upsert(revision, **kw)

    monkeypatch.setattr(mig, "_upsert_revision", _edit_then_upsert)

    res = await _apply_approved(manifest)
    assert fired, "the seam was never reached"

    assert res["summary"]["applied"] == 0, \
        f"a concurrent change to {field} was migrated over"
    assert res["summary"]["drifted"] >= 1
    assert res["summary"]["reconciles"] is True

    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2
    assert not d.get("review_cycles")
    assert d.get("migration_id") is None


@pytest.mark.parametrize("field,new_value", RACES, ids=[f for f, _ in RACES])
async def test_a_change_before_planning_is_migrated_consistently(
        mongo, _store, field, new_value):
    """The other half: a settled change migrates, whole.

    Guarding must not mean refusing. A document edited BEFORE the dry run is
    simply a different document, and its cycle must carry the new values
    throughout — not a mixture, and not a skip.
    """
    doc_id = await _legacy_doc()
    await get_documents_col().update_one({"_id": doc_id},
                                         {"$set": {field: new_value}})

    res = await _apply_approved()
    assert res["summary"]["applied"] == 1

    d = await get_documents_col().find_one({"_id": doc_id})
    cycle = d["review_cycles"][0]
    # Compared UTC-naive: this Motor client is `tz_aware=False`, so a datetime
    # read back from Mongo has no tzinfo even though it went in with one. The
    # instant is what is being asserted, not the representation.
    def _naive(value):
        return value.replace(tzinfo=None) if hasattr(value, "tzinfo") else value

    if field == "submitted_at":
        assert _naive(cycle["submitted_at"]) == _naive(new_value)
    elif field == "reviewed_at":
        assert _naive(cycle["decided_at"]) == _naive(new_value)
    elif field == "lawyer_note":
        assert cycle["note"] == new_value
    elif field == "review_note":
        # `lawyer_note` still wins; the fallback only applies when it is absent.
        assert cycle["note"] == "The original note."
    else:
        rev = await get_document_revisions_col().find_one(
            {"_id": mig.planned_revision_id(doc_id)})
        assert rev["compliance"] == new_value


async def test_the_review_note_fallback_is_still_guarded(mongo, _store,
                                                         monkeypatch):
    """`review_note` matters only when `lawyer_note` is absent — and then it matters."""
    doc_id = await _legacy_doc(lawyer_note=None)
    manifest = await mig.dry_run()

    real_upsert = mig._upsert_revision
    fired: list[str] = []

    async def _edit_then_upsert(revision, **kw):
        if not fired:
            fired.append("review_note")
            await get_documents_col().update_one(
                {"_id": doc_id}, {"$set": {"review_note": "changed"}})
        return await real_upsert(revision, **kw)

    monkeypatch.setattr(mig, "_upsert_revision", _edit_then_upsert)

    res = await _apply_approved(manifest)
    assert res["summary"]["applied"] == 0
    d = await get_documents_col().find_one({"_id": doc_id})
    assert d.get("schema_version") != 2


# ── recomputation is deterministic where it happens ──────────────────────────

async def test_recomputed_compliance_is_deterministic_from_guarded_inputs(
        mongo, _store):
    """A document with no stored compliance has it recomputed from `fields`.

    That is allowed precisely because `fields` IS guarded: the same guarded
    input gives the same output, so nothing unguarded reaches the revision.
    """
    doc_id = await _legacy_doc(compliance=None)
    await _apply_approved()

    rev = await get_document_revisions_col().find_one(
        {"_id": mig.planned_revision_id(doc_id)})
    expected = pleading_rules.check_pleading("legal_notice", _fields())
    assert rev["compliance"] == expected


async def test_an_unguarded_field_change_does_not_block_migration(
        mongo, _store, monkeypatch):
    """The guard must be tight as well as complete.

    A field the migration never reads changing mid-run is not drift. Treating it
    as drift would make any background write — a view counter, a notification
    flag — skip records for no reason, and a migration that skips half its
    estate arbitrarily gets its safety checks removed by whoever has to run it.
    """
    doc_id = await _legacy_doc()
    manifest = await mig.dry_run()

    real_upsert = mig._upsert_revision

    async def _touch_then_upsert(revision, **kw):
        await get_documents_col().update_one(
            {"_id": doc_id},
            {"$set": {"last_viewed_at": datetime.now(timezone.utc)}})
        return await real_upsert(revision, **kw)

    monkeypatch.setattr(mig, "_upsert_revision", _touch_then_upsert)

    res = await _apply_approved(manifest)
    assert res["summary"]["applied"] == 1
