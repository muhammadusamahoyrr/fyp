"""DOCUMENTS_V2 · the go/no-go signal for flipping the flag.

There was no single answer to "may we turn this on?", only three partial ones
that each looked like a whole one.

`queue_visibility_gap()` returned `safe_to_enable`. It inspects one thing — the
documents that would vanish from a lawyer's queue — and says nothing about
whether the indexes exist or whether the migration has run at all. The index
preflight had the same name and was renamed to `indexes_ready` for exactly this
reason; the comment there names the other two gates it deliberately does not
cover, and nothing ever composed them.

A key called `safe_to_enable` is not a naming quibble. It is the line an
operator reads at the moment of the decision, and a green one grants permission
it has not checked for. The failure it invites is silent and total: flip with
the migration half-done and every unmigrated document disappears from the
surfaces that serve it, while the check that said "safe" was right about the
only thing it looked at.

`activation_readiness()` is the composed signal. It is READ-ONLY, it names every
gate it checked — including the ones that passed, so a reader can see the shape
of the question — and it is false if any of them fails.
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

CLIENT = "activation-client"

GATES = ("indexes", "migration_complete", "queue_visibility",
         "migrated_documents_valid")


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


async def _migrate_everything():
    manifest = await mig.dry_run()
    return await mig.apply(mig.approve(manifest, "activation-test"))


# ── the honest name ──────────────────────────────────────────────────────────

async def test_queue_visibility_gap_no_longer_claims_overall_safety(
        mongo, _store):
    """It inspects one gate. Its result must not read as permission.

    Renamed rather than kept as an alias: an alias is exactly what somebody
    greps for and reads at the moment of the decision.
    """
    gap = await mig.queue_visibility_gap()
    assert "safe_to_enable" not in gap
    assert gap["queue_gap_empty"] is True


# ── the composed signal ──────────────────────────────────────────────────────

async def test_a_fully_migrated_estate_is_ready(mongo, _store):
    await _legacy_doc()
    await _legacy_doc(review_status="submitted", reviewer="lawyer-1")
    await _migrate_everything()

    out = await mig.activation_readiness()
    assert out["ready"] is True, out["blockers"]
    assert out["blockers"] == []


async def test_every_gate_is_named_even_when_it_passes(mongo, _store):
    """A reader must be able to see the SHAPE of the question, not just a verdict.

    A signal that lists only failures cannot be distinguished from one that
    forgot to check anything.
    """
    await _legacy_doc()
    await _migrate_everything()

    out = await mig.activation_readiness()
    for gate in GATES:
        assert gate in out["gates"], gate
        assert "passed" in out["gates"][gate]


async def test_it_writes_nothing(mongo, _store):
    """Read-only, because it is run against production at the decision point."""
    doc_id = await _legacy_doc()
    before = await get_documents_col().find_one({"_id": doc_id})
    revs_before = await get_document_revisions_col().count_documents({})

    await mig.activation_readiness()

    assert await get_documents_col().find_one({"_id": doc_id}) == before
    assert await get_document_revisions_col().count_documents({}) == revs_before


# ── each gate can fail the whole thing ───────────────────────────────────────

async def test_an_unmigrated_document_blocks_activation(mongo, _store):
    """The failure the old name invited: flip with the migration half-done."""
    await _legacy_doc()
    await _migrate_everything()
    await _legacy_doc()               # arrives after the migration

    out = await mig.activation_readiness()
    assert out["ready"] is False
    assert out["gates"]["migration_complete"]["passed"] is False
    assert out["gates"]["migration_complete"]["legacy_remaining"] == 1
    assert any("migrat" in b.lower() for b in out["blockers"])


async def test_a_queue_visibility_gap_blocks_activation(mongo, _store):
    """A legacy document in a lawyer's queue disappears the moment we flip."""
    await _legacy_doc(review_status="submitted", reviewer="lawyer-1")

    out = await mig.activation_readiness()
    assert out["ready"] is False
    assert out["gates"]["queue_visibility"]["passed"] is False
    assert out["gates"]["queue_visibility"]["at_risk"] >= 1


async def test_missing_indexes_block_activation(mongo, _store, monkeypatch):
    """Composed from the preflight, not re-implemented.

    Stubbed rather than achieved by dropping a real index: this runs against a
    shared database and dropping one to observe the consequence is the kind of
    test that breaks the suite it lives in.
    """
    from app.db import v2_index_preflight

    async def _not_ready(*a, **k):
        return {"indexes_ready": False, "problems": [{"code": "missing"}],
                "database": "stub", "correctness_problems": 1,
                "query_problems": 0, "obsolete_present": [],
                "recommended_create": [], "recommended_drop": []}

    monkeypatch.setattr(v2_index_preflight, "preflight", _not_ready)

    out = await mig.activation_readiness()
    assert out["ready"] is False
    assert out["gates"]["indexes"]["passed"] is False
    assert any("index" in b.lower() for b in out["blockers"])


async def test_a_damaged_migrated_document_blocks_activation(mongo, _store):
    """`inspect_migrated` already knows what a broken document looks like.

    Nothing consulted it before a flip, so a migration that produced unusable
    documents would still show green on every other gate.
    """
    doc_id = await _legacy_doc()
    await _migrate_everything()

    rev = await get_document_revisions_col().find_one(
        {"_id": mig.planned_revision_id(doc_id)})
    store.delete_final(rev["artifact_key"])       # the bytes are gone

    out = await mig.activation_readiness()
    assert out["ready"] is False
    assert out["gates"]["migrated_documents_valid"]["passed"] is False
    sample = out["gates"]["migrated_documents_valid"]
    assert sample["unusable"] >= 1
    assert doc_id in [p["document_id"] for p in sample["problems"]]


async def test_the_inspection_gate_is_bounded(mongo, _store):
    """It must not read the whole estate to answer a yes/no question.

    An unbounded scan at the decision point is how a safety check becomes the
    thing somebody skips.
    """
    for _ in range(5):
        await _legacy_doc()
    await _migrate_everything()

    out = await mig.activation_readiness(sample=2)
    # The DETAIL is bounded, not the scan: every migrated document is still
    # inspected, and only the listing is capped.
    gate = out["gates"]["migrated_documents_valid"]
    assert gate["examined"] == 5
    assert gate["problems_listed"] <= 2


# ── the report an operator reads ─────────────────────────────────────────────

async def test_it_renders_a_report_naming_the_blockers(mongo, _store):
    await _legacy_doc(review_status="submitted", reviewer="lawyer-1")
    out = await mig.activation_readiness()
    text = mig.render_activation_readiness(out)

    assert "NOT READY" in text
    for gate in GATES:
        assert gate in text
    assert "queue" in text.lower()


async def test_the_report_says_ready_when_it_is(mongo, _store):
    await _legacy_doc()
    await _migrate_everything()
    text = mig.render_activation_readiness(await mig.activation_readiness())
    assert "READY" in text


# ── the verdict must cover the whole estate ──────────────────────────────────

async def _many_migrated(n):
    for _ in range(n):
        await _legacy_doc()
    await _migrate_everything()
    return [d["_id"] async for d in get_documents_col().find(
        {"schema_version": 2}, {"_id": 1}).sort("_id", 1)]


async def test_corruption_beyond_the_sample_still_blocks_activation(
        mongo, _store):
    """THE DEFECT. A bounded sample cannot answer a global question.

    `activation_readiness()` inspected 200 documents and returned a global
    `ready`. On an estate of any real size that is a verdict about the first
    200 rows presented as a verdict about all of them — and the flip it
    authorises affects every one.

    Here the damage is deliberately placed AFTER the sample boundary, which is
    exactly where a real migration failure would be least likely to be noticed.
    """
    ids = await _many_migrated(12)
    victim = ids[-1]

    rev = await get_document_revisions_col().find_one(
        {"_id": mig.planned_revision_id(victim)})
    store.delete_final(rev["artifact_key"])

    out = await mig.activation_readiness(sample=3)
    assert out["ready"] is False, "a sample-sized look declared the estate ready"

    gate = out["gates"]["migrated_documents_valid"]
    assert gate["passed"] is False
    assert gate["examined"] == len(ids), "the verdict did not examine everything"
    assert gate["total"] == len(ids)
    assert victim in [p["document_id"] for p in gate["problems"]]


async def test_the_diagnostic_sample_does_not_decide_readiness(mongo, _store):
    """A sample may remain, but only as a report — never as the verdict."""
    ids = await _many_migrated(8)
    out = await mig.activation_readiness(sample=2)
    gate = out["gates"]["migrated_documents_valid"]

    # Nothing is "sampled" for the purpose of deciding. The cap applies to the
    # problem LISTING only, and the verdict saw every document.
    assert gate["problems_listed"] <= 2
    assert gate["examined"] == len(ids)


async def test_sample_zero_still_gives_a_real_verdict(mongo, _store):
    """`sample=0` turns the diagnostic off. It must not turn the CHECK off.

    A caller passing 0 to skip the detail listing would otherwise get an
    unconditional green — the most dangerous possible reading of "no problems
    found".
    """
    ids = await _many_migrated(5)
    victim = ids[0]
    rev = await get_document_revisions_col().find_one(
        {"_id": mig.planned_revision_id(victim)})
    store.delete_final(rev["artifact_key"])

    out = await mig.activation_readiness(sample=0)
    assert out["ready"] is False
    gate = out["gates"]["migrated_documents_valid"]
    # Nothing listed, everything examined, and the count is still truthful.
    assert gate["problems_listed"] == 0
    assert gate["problems"] == []
    assert gate["examined"] == len(ids)
    assert gate["unusable"] >= 1


async def test_sample_zero_on_a_clean_estate_is_ready(mongo, _store):
    await _many_migrated(5)
    out = await mig.activation_readiness(sample=0)
    assert out["ready"] is True, out["blockers"]


async def test_the_problem_list_is_bounded_but_the_count_is_not(mongo, _store):
    """A report nobody can read is not a report; a count that lies is worse."""
    ids = await _many_migrated(30)
    for doc_id in ids:
        rev = await get_document_revisions_col().find_one(
            {"_id": mig.planned_revision_id(doc_id)})
        store.delete_final(rev["artifact_key"])

    out = await mig.activation_readiness(sample=2)
    gate = out["gates"]["migrated_documents_valid"]
    assert gate["unusable"] == len(ids)
    assert len(gate["problems"]) <= mig.READINESS_PROBLEM_CAP


async def test_the_scan_is_batched_not_one_big_read(mongo, _store):
    """Bounded memory: an estate is scanned in pages, not loaded whole."""
    await _many_migrated(9)
    sizes: list[int] = []
    real_to_list = None

    out = await mig.activation_readiness(sample=0, batch=4)
    gate = out["gates"]["migrated_documents_valid"]
    assert gate["examined"] == 9
    assert gate["batches"] >= 3


# ── fail closed ──────────────────────────────────────────────────────────────

async def test_a_scan_failure_fails_closed(mongo, _store, monkeypatch):
    """A database error must never read as permission.

    An exception escaping this function would reach an operator as a traceback,
    and a `ready` that defaulted to True would be worse still. Either way the
    honest answer is "we could not establish that this is safe".
    """
    await _many_migrated(3)

    async def _boom(document_id):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(mig, "inspect_migrated", _boom)

    out = await mig.activation_readiness(sample=0)
    assert out["ready"] is False
    assert out["gates"]["migrated_documents_valid"]["passed"] is False
    assert any("could not" in b.lower() or "error" in b.lower()
               for b in out["blockers"]), out["blockers"]


async def test_a_counting_failure_fails_closed(mongo, _store, monkeypatch):
    from app.db import collections as cols

    await _many_migrated(2)
    real = mig.get_documents_col

    class _Broken:
        def __getattr__(self, name):
            async def _boom(*a, **k):
                raise RuntimeError("the database went away")
            return _boom

    monkeypatch.setattr(mig, "get_documents_col", lambda: _Broken())
    out = await mig.activation_readiness(sample=0)
    monkeypatch.setattr(mig, "get_documents_col", real)

    assert out["ready"] is False
    assert out["blockers"]


async def test_the_exhaustive_scan_still_writes_nothing(mongo, _store):
    ids = await _many_migrated(6)
    before = {d["_id"]: d async for d in get_documents_col().find({})}
    revs_before = await get_document_revisions_col().count_documents({})

    await mig.activation_readiness(sample=2)

    after = {d["_id"]: d async for d in get_documents_col().find({})}
    assert after == before
    assert await get_document_revisions_col().count_documents({}) == revs_before


# ── argument validation and reconciliation ───────────────────────────────────

@pytest.mark.parametrize("sample", [-1, -50])
async def test_a_negative_sample_is_refused(mongo, _store, sample):
    """`problems[:min(-1, CAP)]` is `problems[:-1]` — it silently drops one.

    A negative argument did not error; it quietly hid the last failure in the
    report an operator reads before flipping the flag.
    """
    with pytest.raises(ValueError):
        await mig.activation_readiness(sample=sample)


@pytest.mark.parametrize("batch", [0, -1])
async def test_a_non_positive_batch_is_refused(mongo, _store, batch):
    """Mongo treats `limit(0)` as NO limit.

    The argument that exists to bound memory would have removed the bound —
    loading the whole estate in one read on exactly the collection this is
    meant to scan safely.
    """
    with pytest.raises(ValueError):
        await mig.activation_readiness(batch=batch)


async def test_the_problem_list_is_capped_during_the_scan(mongo, _store):
    """Bounded memory, not just a bounded report.

    Every failure was appended and only truncated on the way out, so an estate
    where everything is broken held one record per document in memory — the
    case where the machine is least able to spare it.
    """
    ids = await _many_migrated(8)
    for doc_id in ids:
        rev = await get_document_revisions_col().find_one(
            {"_id": mig.planned_revision_id(doc_id)})
        store.delete_final(rev["artifact_key"])

    out = await mig.activation_readiness(sample=2, batch=3)
    gate = out["gates"]["migrated_documents_valid"]
    # The COUNT stays truthful even though the detail is capped.
    assert gate["unusable"] == len(ids)
    assert gate["problems_listed"] <= 2
    assert len(gate["problems"]) <= mig.READINESS_PROBLEM_CAP


async def test_a_short_scan_fails_closed(mongo, _store, monkeypatch):
    """Examined and total were computed and never compared.

    A cursor cut short by a stepdown or a timeout returns fewer documents than
    the collection holds, and every one it managed to read is fine — so the
    gate passed on a partial scan and reported it as a clean estate.
    """
    await _many_migrated(6)

    real_count = mig.get_documents_col

    class _Inflated:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            if name == "count_documents":
                async def _more(*a, **k):
                    return await self._inner.count_documents(*a, **k) + 3
                return _more
            return getattr(self._inner, name)

    monkeypatch.setattr(mig, "get_documents_col",
                        lambda: _Inflated(real_count()))
    out = await mig.activation_readiness(sample=0)
    monkeypatch.setattr(mig, "get_documents_col", real_count)

    gate = out["gates"]["migrated_documents_valid"]
    assert gate["passed"] is False, "a partial scan passed as a clean estate"
    assert out["ready"] is False
    assert any("examin" in b.lower() or "incomplete" in b.lower()
               for b in out["blockers"]), out["blockers"]


def test_the_docstring_does_not_claim_the_scan_is_sampled():
    """It said SAMPLED long after the scan became exhaustive.

    A reader would distrust a verdict that is actually sound — and the whole
    value of this gate is that somebody believes it at the moment of the flip.
    """
    import inspect
    text = inspect.getdoc(mig.activation_readiness) or ""
    assert "SAMPLED, not exhaustive" not in text
    assert "every" in text.lower() or "exhaustive" in text.lower()


async def test_a_failed_scan_reports_the_full_unusable_count(
        mongo, _store, monkeypatch):
    """The error path reported the CAPPED list length as the count.

    Capping the detail during the scan was right; reusing `len(problems)` as
    the count afterwards was not. A scan that found forty broken documents and
    then died would report twenty — understating the damage in the one report
    that exists to describe it.
    """
    ids = await _many_migrated(25)
    for doc_id in ids:
        rev = await get_document_revisions_col().find_one(
            {"_id": mig.planned_revision_id(doc_id)})
        store.delete_final(rev["artifact_key"])

    real_inspect = mig.inspect_migrated
    seen = {"n": 0}

    async def _die_after_a_while(document_id):
        seen["n"] += 1
        if seen["n"] > 24:
            raise RuntimeError("the database went away")
        return await real_inspect(document_id)

    monkeypatch.setattr(mig, "inspect_migrated", _die_after_a_while)

    out = await mig.activation_readiness(sample=2, batch=50)
    gate = out["gates"]["migrated_documents_valid"]

    assert gate["passed"] is False
    assert gate["unusable"] == 24, (
        f"reported {gate['unusable']} unusable; the scan found 24 before dying")
    assert gate["problems_listed"] <= 2
