"""Every standalone document producer goes through one seam.

Seven routes called `document_service.generate_standalone`, which always writes
a legacy row. So switching DOCUMENTS_V2 on did not make new documents V2: these
routes would have produced legacy rows — no revision, no hash, invisible to
`/documents/v2/mine` — the moment the flag flipped. See app/services/document_writer.py.

Held down here:
  * no module calls `generate_standalone` except the facade;
  * flag OFF, the facade is the legacy path unchanged;
  * flag ON, EVERY producer creates a `schema_version: 2` document with a
    revision, and its response carries the revision id needed to download it;
  * an Idempotency-Key makes a retry return the same document.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.collections import (
    get_document_revisions_col, get_documents_col, get_disputes_col,
)
from app.services import artifact_store as store
from app.services import document_v2_service as v2
from app.services import document_writer

APP = Path(__file__).resolve().parents[1] / "app"


# ══════════════════════════════════════════════════════════════════════════════
# The seam
# ══════════════════════════════════════════════════════════════════════════════

def test_nothing_but_the_facade_calls_generate_standalone():
    callers = set()
    for path in APP.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "generate_standalone(" in line and "def generate_standalone" not in line:
                callers.add(path.relative_to(APP).as_posix())
    assert callers == {"services/document_writer.py"}, (
        f"generate_standalone called outside the facade: {sorted(callers)}")


async def test_flag_off_is_the_legacy_path(monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", False)
    seen = {}

    async def fake_standalone(owner, template, fields):
        seen.update(owner=owner, template=template, fields=fields)
        return {"_id": "legacy-1", "title": "Legal Notice", "status": "generated"}

    from app.services import document_service
    monkeypatch.setattr(document_service, "generate_standalone", fake_standalone)

    async def never(**_):
        raise AssertionError("V2 used while the flag is off")
    monkeypatch.setattr(v2, "create_document", never)

    doc = await document_writer.generate_owned_document(
        "u1", "legal_notice", {"notice_body": "x"}, idempotency_key="k")
    assert seen == {"owner": "u1", "template": "legal_notice", "fields": {"notice_body": "x"}}
    assert doc["_id"] == "legacy-1"
    assert doc["revision_id"] is None and doc["pdf_sha256"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Flag ON: every producer, through the real app
# ══════════════════════════════════════════════════════════════════════════════

CLIENT = {"_id": "writer-client-" + secrets.token_hex(3), "role": "client",
          "is_active": True, "full_name": "Test Client"}
LAWYER = {"_id": "writer-lawyer-" + secrets.token_hex(3), "role": "lawyer",
          "is_active": True, "full_name": "Test Advocate"}
PDF = b"%PDF-1.4 rendered by the fake"

HEIRS = {"sons": 1}


@pytest.fixture
def v2_on(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "documents_v2", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()

    async def _render(*, revision_id, document_id, version, template_type,
                      fields, fence, worker_id):
        # The routing is under test, not the templates (they have their own).
        from app.repositories import revision_repo
        key = store.write_final(revision_id, fence, PDF)
        promoted = await revision_repo.promote(revision_id, worker_id, fence, {
            "artifact_key": key, "pdf_sha256": store.sha256_bytes(PDF),
            "text_sha256": "t" * 64, "body_text": "text", "extraction_status": "ok",
            "verification": {"ran": False}, "compliance": {"checked": False}})
        await revision_repo.repoint_document(document_id, revision_id, version)
        return promoted
    monkeypatch.setattr(v2, "_render_and_select", _render)


@pytest.fixture
async def clean(mongo):
    owners = [CLIENT["_id"], LAWYER["_id"]]

    async def wipe():
        async for doc in get_documents_col().find({"client_id": {"$in": owners}}):
            await get_document_revisions_col().delete_many({"document_id": doc["_id"]})
        await get_documents_col().delete_many({"client_id": {"$in": owners}})
        await get_disputes_col().delete_many({"client_id": CLIENT["_id"]})
    await wipe()
    yield
    await wipe()


@pytest.fixture
async def http():
    from app.dependencies import get_current_user, require_lawyer
    from app.main import app

    state = {"user": CLIENT}

    async def _current():
        return state["user"]

    async def _lawyer():
        return state["user"]

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[require_lawyer] = _lawyer
    async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                 base_url="http://test/api/v1") as client:
        client.act_as = lambda user: state.__setitem__("user", user)
        yield client
    app.dependency_overrides.clear()


# (route, user, body, response key holding the document id)
PRODUCERS = [
    ("/documents/quick-notice", CLIENT,
     {"text": "My landlord kept my deposit.", "template_type": "legal_notice",
      "fields": {"notice_body": "Return the deposit.", "sender_name": "A"}}, "doc_id"),
    ("/calculators/labour-demand-pdf", CLIENT,
     {"monthly_wage": 50000, "years_of_service": 3, "worker_name": "A",
      "employer_name": "B"}, "doc_id"),
    ("/inheritance/settlement-pdf", CLIENT,
     {"estate_value": 1000000, "heirs": HEIRS, "deceased_name": "C"}, "doc_id"),
    ("/inheritance/demand-letter", CLIENT,
     {"claimant_name": "A", "recipient_name": "B", "deceased_name": "C",
      "share_fraction": "1/2"}, "doc_id"),
    ("/inheritance/wasiyyat-pdf", CLIENT,
     {"gross_estate": 1000000, "heirs": HEIRS, "testator_name": "C"}, "doc_id"),
    ("/ai/pleading-urdu/pdf", LAWYER,
     {"urdu_text": "عدالت میں درخواست", "english_label": "Plaint"}, "doc_id"),
]


async def _assert_v2(doc_id, owner):
    row = await get_documents_col().find_one({"_id": doc_id})
    assert row is not None
    assert row["schema_version"] == 2, "a legacy row was written with V2 on"
    assert row["client_id"] == owner["_id"]
    assert row.get("file_path") is None
    assert row["current_revision_id"]
    assert await get_document_revisions_col().count_documents({"document_id": doc_id}) == 1


@pytest.mark.integration
@pytest.mark.parametrize("route,user,body,id_key", PRODUCERS,
                         ids=[p[0] for p in PRODUCERS])
async def test_every_producer_writes_a_v2_document(v2_on, clean, http,
                                                   route, user, body, id_key):
    http.act_as(user)
    res = await http.post(route, json=body)
    assert res.status_code == 200, f"{route}: {res.status_code} {res.text}"
    data = res.json()
    await _assert_v2(data[id_key], user)
    # The response is the old shape PLUS what a V2 download needs.
    assert data["revision_id"]
    assert data["pdf_sha256"] == store.sha256_bytes(PDF)


@pytest.mark.integration
async def test_the_dispute_petition_writes_a_v2_document(v2_on, clean, monkeypatch):
    from app.services import dispute_intake, petition_drafter

    async def _facts(intake, grievance, petitioner):
        return petition_drafter.PetitionFacts(
            facts=["The Petitioner owns the property."], cause_of_action="Dispossession.")
    monkeypatch.setattr(petition_drafter, "_draft_facts", _facts)

    dispute_id = "writer-dispute-" + secrets.token_hex(3)
    await get_disputes_col().insert_one({
        "_id": dispute_id, "client_id": CLIENT["_id"], "state": dispute_intake.STATE_READY,
        "intake": {"property_description": "House 1", "province": "Punjab",
                   "opposing_party": "D", "timeline": "2025", "relief_wanted": "other"},
        "grievance": {}, "jurisdiction": {"province": "Punjab"}})

    out = await petition_drafter.draft_petition(dispute_id, CLIENT["_id"])
    await _assert_v2(out["document_id"], CLIENT)
    assert out["revision_id"]
    dispute = await get_disputes_col().find_one({"_id": dispute_id})
    assert dispute["petition_document_id"] == out["document_id"]


@pytest.mark.integration
async def test_one_idempotency_key_is_one_document(v2_on, clean, http):
    route, user, body, id_key = PRODUCERS[0]
    http.act_as(user)
    headers = {"Idempotency-Key": secrets.token_urlsafe(12)}
    first = (await http.post(route, json=body, headers=headers)).json()
    again = (await http.post(route, json=body, headers=headers)).json()
    assert first[id_key] == again[id_key]
    assert first["revision_id"] == again["revision_id"]
    assert await get_documents_col().count_documents({"client_id": user["_id"]}) == 1
