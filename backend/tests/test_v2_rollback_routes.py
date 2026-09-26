"""DOCUMENTS_V2 rollback · the legacy HTTP routes still serve V2-native documents.

If the flag is switched back OFF, documents created while it was on have no
legacy `file_path`, `fields` or `status` of their own. The compatibility reader
existed and was unit-tested in isolation, which is how three route-level
failures survived:

  * download 404'd: the projected `file_path` was the store-RELATIVE key, and
    the route checks `Path(file_path).exists()` against the working directory;
  * the case list 500'd: it never ran the reader, and `DocumentOut` requires
    `status`, so one V2-native row broke the whole listing;
  * a created-but-never-rendered V2 document had no `status` even through the
    reader.

These go through the real app over ASGI, so the response models run exactly as
they do in production.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.collections import get_document_revisions_col, get_documents_col
from app.services import artifact_store as store

pytestmark = pytest.mark.integration

CLIENT = {"_id": "rb-client-" + uuid.uuid4().hex[:6], "role": "client", "is_active": True}
LAWYER = {"_id": "rb-lawyer-" + uuid.uuid4().hex[:6], "role": "lawyer", "is_active": True}
CASE_ID = "rb-case-" + uuid.uuid4().hex[:6]
PDF = b"%PDF-1.4 a v2-native document"


@pytest.fixture
def flag_off(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "documents_v2", False)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    store.ensure_dirs()
    return tmp_path


@pytest.fixture
async def docs(mongo, flag_off):
    """Three rows in one case: V2-native rendered, V2-native never rendered,
    and an ordinary legacy document."""
    native, empty, legacy = (f"rb-{k}-" + uuid.uuid4().hex[:6]
                             for k in ("native", "empty", "legacy"))
    rev_id = "rb-rev-" + uuid.uuid4().hex[:6]
    key = store.write_final(rev_id, 0, PDF)

    await get_document_revisions_col().insert_one({
        "_id": rev_id, "document_id": native, "version": 1, "status": "generated",
        "artifact_key": key, "pdf_sha256": store.sha256_bytes(PDF),
        "fields": {"notice_body": "Pay the sum owed."},
        "compliance": {"checked": False}, "verification": {"ran": True, "counts": {}}})
    await get_documents_col().insert_many([
        {"_id": native, "client_id": CLIENT["_id"], "case_id": CASE_ID,
         "template_type": "legal_notice", "title": "Native notice", "schema_version": 2,
         "current_revision_id": rev_id, "current_version": 1, "review_status": "submitted",
         "submitted_to": LAWYER["_id"]},
        {"_id": empty, "client_id": CLIENT["_id"], "case_id": CASE_ID,
         "template_type": "legal_notice", "title": "Never rendered", "schema_version": 2,
         "current_revision_id": None, "current_version": 0, "review_status": "none"},
        {"_id": legacy, "client_id": CLIENT["_id"], "case_id": CASE_ID,
         "template_type": "legal_notice", "title": "Legacy notice", "status": "generated",
         "file_path": None, "fields": {"notice_body": "x"}},
    ])
    yield {"native": native, "empty": empty, "legacy": legacy}
    await get_document_revisions_col().delete_many({"_id": rev_id})
    await get_documents_col().delete_many({"_id": {"$in": [native, empty, legacy]}})


@pytest.fixture
async def http():
    from app.dependencies import get_current_user, require_lawyer
    from app.main import app

    state = {"user": CLIENT}

    async def _current():
        return state["user"]

    async def _lawyer():
        if state["user"].get("role") != "lawyer":
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="forbidden")
        return state["user"]

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[require_lawyer] = _lawyer
    async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                 base_url="http://test/api/v1") as client:
        client.act_as = lambda user: state.__setitem__("user", user)
        yield client
    app.dependency_overrides.clear()


async def test_a_v2_native_document_downloads_through_the_legacy_route(docs, http):
    res = await http.get(f"/documents/{docs['native']}/download")
    assert res.status_code == 200, res.text
    assert res.content == PDF


async def test_its_detail_is_legacy_shaped_and_leaks_no_path(docs, http):
    res = await http.get(f"/documents/{docs['native']}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "generated"
    assert body["verification"] == {"ran": True, "counts": {}}
    assert "file_path" not in body


async def test_the_case_list_serves_every_kind_of_row(docs, http):
    res = await http.get(f"/documents/case/{CASE_ID}")
    assert res.status_code == 200, res.text
    rows = {r["_id"]: r for r in res.json()}
    assert set(rows) == {docs["native"], docs["empty"], docs["legacy"]}
    assert rows[docs["native"]]["status"] == "generated"
    assert rows[docs["empty"]]["status"] == "pending"   # no PDF yet, not a crash
    assert rows[docs["legacy"]]["status"] == "generated"
    assert all("file_path" not in r for r in rows.values())


async def test_a_never_rendered_document_has_nothing_to_download(docs, http):
    res = await http.get(f"/documents/{docs['empty']}/download")
    assert res.status_code == 404


async def test_the_lawyer_inbox_shows_the_revision_checks(docs, http):
    http.act_as(LAWYER)
    res = await http.get("/documents/review-queue")
    assert res.status_code == 200, res.text
    row = next(r for r in res.json() if r["id"] == docs["native"])
    assert row["verification"] == {"ran": True, "counts": {}}
    assert row["status"] == "generated"
