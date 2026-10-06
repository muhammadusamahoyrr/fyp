"""Document Analyzer, P2B: reviewer qualifications and audited approvals.

Approval is bound to a qualification for the pack's jurisdiction and
practice area, not merely to "a verified lawyer". Every change writes an
audit row in the same transaction. Replica set (`mongo_transactional`).
The legal pack is a TEST fixture in a temporary directory.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.services.analyzer import approvals, playbook_engine as engine, readiness
from app.services.analyzer.errors import AnalyzerConflict, AnalyzerNotFound, UploadRejected
from app.services.analyzer.playbook_dsl import PlaybookError
from tests._analyzer_support import KEY
from tests.test_analyzer_playbook_engine import LEASE, LEGAL, TENANCY, sentences_of


@pytest.fixture
async def env(mongo_transactional, app_indexes, tmp_path, monkeypatch):
    db = mongo_transactional
    (tmp_path / "general.yaml").write_text(
        (engine.PLAYBOOK_DIR / "general.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_legal.yaml").write_text(LEGAL, encoding="utf-8")
    monkeypatch.setattr(engine, "PLAYBOOK_DIR", tmp_path)
    for name in ("analysis_playbook_approvals", "analysis_reviewer_qualifications",
                 "analysis_approval_audit"):
        await db[name].delete_many({})
    yield db, tmp_path
    for name in ("analysis_playbook_approvals", "analysis_reviewer_qualifications",
                 "analysis_approval_audit"):
        await db[name].delete_many({})


async def user(db, *, role="lawyer", kyc="approved"):
    uid = f"user-{uuid.uuid4().hex[:8]}"
    await db["users"].insert_one({"_id": uid, "email": f"{uid}@example.test", "role": role,
                                  "lawyer_profile": {"kyc_status": kyc}})
    return {"_id": uid, "role": role}


def legal_pack():
    return next(p for p in engine.load_packs() if p.id == "test_legal")


async def statuses():
    _, summary = await engine.analyse(TENANCY, LEASE, sentences_of(LEASE))
    return {p["pack_id"]: p["status"] for p in summary}


# ── the pack declares what qualification it needs ───────────────────────────

def test_a_legal_pack_must_name_a_well_formed_qualification():
    with pytest.raises(PlaybookError, match="required_qualification"):
        engine.parse_pack(LEGAL.replace("required_qualification: pk.punjab.tenancy\n", ""))
    with pytest.raises(PlaybookError, match="required_qualification"):
        engine.parse_pack(LEGAL.replace("pk.punjab.tenancy", "Punjab Tenancy"))
    general = (engine.PLAYBOOK_DIR / "general.yaml").read_text(encoding="utf-8")
    with pytest.raises(PlaybookError, match="no reviewer qualification"):
        engine.parse_pack(general.replace("requires_approval: false\n",
                                          "requires_approval: false\nrequired_qualification: pk.any.thing\n"))
    assert engine.parse_pack(LEGAL).required_qualification == "pk.punjab.tenancy"


# ── qualifications ───────────────────────────────────────────────────────────

async def test_only_a_verified_lawyer_can_be_qualified_and_the_grant_is_audited(env):
    db, _ = env
    admin, lawyer = await user(db, role="admin"), await user(db)
    for target in (await user(db, role="client"), await user(db, kyc="pending")):
        with pytest.raises(UploadRejected, match="verified lawyer"):
            await approvals.grant_qualification(admin=admin, user_id=target["_id"],
                                                qualification="pk.punjab.tenancy", basis="x")
    with pytest.raises(UploadRejected, match="pk.punjab.tenancy"):
        await approvals.grant_qualification(admin=admin, user_id=lawyer["_id"],
                                            qualification="tenancy", basis="x")
    grant = await approvals.grant_qualification(admin=admin, user_id=lawyer["_id"],
                                                qualification="pk.punjab.tenancy",
                                                basis="Advocate, Lahore High Court Bar")
    with pytest.raises(AnalyzerConflict):
        await approvals.grant_qualification(admin=admin, user_id=lawyer["_id"],
                                            qualification="pk.punjab.tenancy", basis="again")
    [entry] = await approvals.audit_trail()
    assert entry["action"] == "grant_qualification" and entry["grant_id"] == grant["_id"]
    assert entry["actor_user_id"] == admin["_id"] and entry["basis"].startswith("Advocate")


# ── approvals ────────────────────────────────────────────────────────────────

async def test_approval_needs_the_packs_exact_qualification(env):
    db, _ = env
    admin = await user(db, role="admin")
    unqualified, nda_only, tenancy = await user(db), await user(db), await user(db)
    await approvals.grant_qualification(admin=admin, user_id=nda_only["_id"],
                                        qualification="pk.contract.nda", basis="NDA practice")
    await approvals.grant_qualification(admin=admin, user_id=tenancy["_id"],
                                        qualification="pk.punjab.tenancy", basis="Tenancy practice")
    pack = legal_pack()
    for who in (unqualified, nda_only):
        with pytest.raises(UploadRejected, match="needs the qualification pk.punjab.tenancy"):
            await approvals.record_approval(reviewer=who, pack_id=pack.id,
                                            content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")
    assert (await statuses())["test_legal"] == "awaiting_approval"

    record = await approvals.record_approval(reviewer=tenancy, pack_id=pack.id,
                                             content_hash=pack.content_hash, authorities_hash=pack.authorities_hash,
                                             reviewer_role="Advocate, Punjab")
    assert record["qualification"] == "pk.punjab.tenancy" and record["active"] is True
    assert (await statuses())["test_legal"] == "applied"
    audit = await approvals.audit_trail()
    assert audit[0]["action"] == "approve_playbook" and audit[0]["content_hash"] == pack.content_hash


async def test_refusals_hash_general_and_duplicates(env):
    db, _ = env
    admin, lawyer = await user(db, role="admin"), await user(db)
    await approvals.grant_qualification(admin=admin, user_id=lawyer["_id"],
                                        qualification="pk.punjab.tenancy", basis="b")
    pack = legal_pack()
    with pytest.raises(AnalyzerConflict, match="changed since it was reviewed"):
        await approvals.record_approval(reviewer=lawyer, pack_id=pack.id,
                                        content_hash="0" * 64, authorities_hash=pack.authorities_hash, reviewer_role="r")
    with pytest.raises(UploadRejected, match="no legal claim"):
        await approvals.record_approval(reviewer=lawyer, pack_id="general",
                                        content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")
    with pytest.raises(AnalyzerNotFound):
        await approvals.record_approval(reviewer=lawyer, pack_id="nope",
                                        content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")
    await approvals.record_approval(reviewer=lawyer, pack_id=pack.id,
                                    content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")
    with pytest.raises(AnalyzerConflict, match="already approved"):
        await approvals.record_approval(reviewer=lawyer, pack_id=pack.id,
                                        content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")


async def test_an_audit_failure_rolls_the_approval_back(env, monkeypatch):
    db, _ = env
    admin, lawyer = await user(db, role="admin"), await user(db)
    await approvals.grant_qualification(admin=admin, user_id=lawyer["_id"],
                                        qualification="pk.punjab.tenancy", basis="b")
    pack = legal_pack()

    async def boom(*a, **k):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(approvals, "_audit", boom)
    with pytest.raises(RuntimeError):
        await approvals.record_approval(reviewer=lawyer, pack_id=pack.id,
                                        content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")
    monkeypatch.undo()
    assert await db["analysis_playbook_approvals"].count_documents({}) == 0, \
        "an approval committed without its audit row"


async def test_revoking_an_approval_and_approving_again(env):
    db, _ = env
    admin, lawyer, other = await user(db, role="admin"), await user(db), await user(db)
    for who in (lawyer, other):
        await approvals.grant_qualification(admin=admin, user_id=who["_id"],
                                            qualification="pk.punjab.tenancy", basis="b")
    pack = legal_pack()
    record = await approvals.record_approval(reviewer=lawyer, pack_id=pack.id,
                                             content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")
    with pytest.raises(AnalyzerNotFound):            # someone else's approval
        await approvals.revoke_approval(actor=other, approval_id=record["_id"], reason="no")
    await approvals.revoke_approval(actor=lawyer, approval_id=record["_id"], reason="re-reviewing")
    assert (await statuses())["test_legal"] == "awaiting_approval"
    # The same text can be approved again; the revoked record stays as history.
    again = await approvals.record_approval(reviewer=other, pack_id=pack.id,
                                            content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")
    await approvals.revoke_approval(actor=admin, approval_id=again["_id"], reason="admin")
    assert await db["analysis_playbook_approvals"].count_documents({"active": False}) == 2


async def test_revoking_a_qualification_withdraws_its_approvals(env):
    db, _ = env
    admin, lawyer = await user(db, role="admin"), await user(db)
    grant = await approvals.grant_qualification(admin=admin, user_id=lawyer["_id"],
                                                qualification="pk.punjab.tenancy", basis="b")
    pack = legal_pack()
    record = await approvals.record_approval(reviewer=lawyer, pack_id=pack.id,
                                             content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")
    assert (await statuses())["test_legal"] == "applied"
    outcome = await approvals.revoke_qualification(admin=admin, grant_id=grant["_id"],
                                                   reason="enrolment lapsed")
    assert outcome["approvals_deactivated"] == [record["_id"]]
    assert (await statuses())["test_legal"] == "awaiting_approval"
    audit = await approvals.audit_trail()
    assert audit[0]["action"] == "revoke_qualification"
    assert audit[0]["approvals_deactivated"] == [record["_id"]]
    with pytest.raises(UploadRejected, match="needs the qualification"):
        await approvals.record_approval(reviewer=lawyer, pack_id=pack.id,
                                        content_hash=pack.content_hash, authorities_hash=pack.authorities_hash, reviewer_role="r")


# ── the HTTP surface and its roles ───────────────────────────────────────────

@pytest.fixture
async def api(env, monkeypatch):
    from app.dependencies import get_current_user
    from app.main import app

    db, _ = env
    actor = {}
    monkeypatch.setattr(settings, "doc_analyzer", True)
    monkeypatch.setattr(settings, "analyzer_keks", KEY)
    monkeypatch.setattr(settings, "analyzer_kek_active", "k1")
    readiness._reset_for_tests()
    readiness._STATE.checked = True

    async def current():
        return {"is_active": True, **actor}

    app.dependency_overrides[get_current_user] = current
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://test/api/v1/documents/analyses") as client:
            yield client, actor, db
    finally:
        app.dependency_overrides.clear()
        readiness._reset_for_tests()


async def test_the_review_endpoints_enforce_roles_end_to_end(api):
    client, actor, db = api
    admin, lawyer = await user(db, role="admin"), await user(db)

    actor.update(_id="client-1", role="client")
    for method, path in (("GET", "/playbooks"), ("GET", "/playbooks/test_legal"),
                         ("GET", "/approval-audit"), ("POST", "/reviewer-qualifications")):
        assert (await client.request(method, path, json={})).status_code == 403, path

    actor.update(admin)
    granted = await client.post("/reviewer-qualifications", json={
        "user_id": lawyer["_id"], "qualification": "pk.punjab.tenancy", "basis": "Advocate"})
    assert granted.status_code == 201

    actor.clear(); actor.update(lawyer)
    assert (await client.get("/approval-audit")).status_code == 403
    listing = (await client.get("/playbooks")).json()
    legal = next(p for p in listing if p["id"] == "test_legal")
    assert legal["required_qualification"] == "pk.punjab.tenancy" and legal["approvals"] == []
    text = (await client.get("/playbooks/test_legal")).json()
    assert text["content_hash"] == legal["content_hash"] and "Rent Registrar" in text["text"]
    approved = await client.post("/playbooks/test_legal/approvals", json={
        "content_hash": text["content_hash"], "authorities_hash": text["authorities_hash"],
        "reviewer_role": "Advocate, Punjab"})
    assert approved.status_code == 201, approved.text
    listing = (await client.get("/playbooks")).json()
    assert len(next(p for p in listing if p["id"] == "test_legal")["approvals"]) == 1

    actor.clear(); actor.update(admin)
    audit = (await client.get("/approval-audit")).json()
    assert [a["action"] for a in audit] == ["approve_playbook", "grant_qualification"]


async def test_an_obsolete_full_unique_approval_index_is_removed(env):
    db, _ = env
    from app.db.indexes import _analyzer_indexes, validate_analyzer_indexes
    col = db["analysis_playbook_approvals"]
    await col.create_index([("pack_id", 1), ("content_hash", 1)],
                           name="uniq_analysis_playbook_approval", unique=True)
    await _analyzer_indexes()
    assert "uniq_analysis_playbook_approval" not in await col.index_information()
    assert await validate_analyzer_indexes() == []
