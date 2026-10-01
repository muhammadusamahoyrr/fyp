"""Shared fixture and helpers for the Document Analyzer API tests.

Not a test module (leading underscore, like _conversation_fakes). Imported by
test_analyzer_upload_api.py
and test_analyzer_deletion.py so both drive the real app the same way.
"""
from __future__ import annotations

import base64
import io
import uuid

import httpx
import pytest
from httpx import ASGITransport

from app.ai import extraction as X
from app.ai.ocr import OcrPageResult
from app.core.config import settings
from app.db.collections import (
    get_analysis_blobs_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)
from app.services.analyzer import blob_store, readiness

PDF = b"%PDF-1.4\nTENANCY AGREEMENT (synthetic)\n1. The Landlord lets the shop.\n%%EOF\n"
KEY = "k1:" + base64.b64encode(b"\x33" * 32).decode()
# Headers, not form fields: they are checked before the body is parsed.
ATTESTED = {"X-Synthetic-Data-Attested": "true", "X-Synthetic-Attestation-Version": "synthetic-v1"}


@pytest.fixture
async def http(mongo, app_indexes, monkeypatch, tmp_path):
    from app.dependencies import get_current_user
    from app.main import app

    owner = f"client-{uuid.uuid4().hex[:10]}"
    actor = {"_id": owner, "role": "client", "is_active": True}
    monkeypatch.setattr(settings, "doc_analyzer", True)
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    monkeypatch.setattr(settings, "analyzer_keks", KEY)
    monkeypatch.setattr(settings, "analyzer_kek_active", "k1")
    readiness._reset_for_tests()
    readiness._STATE.checked = True          # as if the startup check passed

    async def current():
        return actor

    app.dependency_overrides[get_current_user] = current
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://test/api/v1") as client:
            yield client, actor
    finally:
        app.dependency_overrides.clear()
        readiness._reset_for_tests()
        # Everything this owner produced, in every source-scoped collection, so
        # the persistent test database never carries one test's rows into
        # another. (Stage outputs used to be left behind; once more than a
        # sweep's batch of them had aged, the output-sweep tests could no
        # longer reach their own rows.)
        ids = [x["_id"] async for x in get_analysis_sources_col().find({"owner_id": owner}, {"_id": 1})]
        for col in SOURCE_SCOPED():
            await col.delete_many({"source_id": {"$in": ids}})
        for col in (get_analysis_sources_col(), get_analysis_runs_col()):
            await col.delete_many({"owner_id": owner})


def SOURCE_SCOPED():
    """Every analyzer collection whose rows belong to a source (all keyed source_id)."""
    from app.db import collections as C
    return (C.get_analysis_deletion_outbox_col(), C.get_analysis_blobs_col(),
            C.get_analysis_text_pages_col(), C.get_analysis_text_blocks_col(),
            C.get_analysis_text_versions_col(), C.get_analysis_clauses_col(),
            C.get_analysis_sentences_col(), C.get_analysis_context_versions_col(),
            C.get_analysis_findings_col())


def files_on_disk() -> list:
    root = blob_store._root()
    return list(root.iterdir()) if root.exists() else []


async def stored_for(owner: str) -> tuple[int, int, int]:
    sources = await get_analysis_sources_col().count_documents({"owner_id": owner})
    runs = await get_analysis_runs_col().count_documents({"owner_id": owner})
    ids = [s["_id"] async for s in get_analysis_sources_col().find({"owner_id": owner}, {"_id": 1})]
    blobs = await get_analysis_blobs_col().count_documents({"source_id": {"$in": ids}})
    return sources, runs, blobs


async def upload(client, *, content=PDF, name="lease.pdf", attest=None, key="auto", **fields):
    """POST an upload. `attest` replaces the attestation headers; `fields` are form fields."""
    headers = dict(ATTESTED if attest is None else attest)
    if key is not None:
        headers["Idempotency-Key"] = uuid.uuid4().hex if key == "auto" else key
    return await client.post("/documents/analyses", data=fields, headers=headers,
                             files={"file": (name, content, "application/octet-stream")})


@pytest.fixture
def form_calls(monkeypatch):
    """Count `Request.form()` calls, to prove a refusal never parsed the body."""
    from starlette.requests import Request

    calls = []
    real = Request.form

    def spy(self, *args, **kwargs):
        calls.append(self.url.path)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Request, "form", spy)
    return calls


async def assert_nothing_stored(owner: str):
    assert await stored_for(owner) == (0, 0, 0)
    assert files_on_disk() == [], "a refused upload left a file on disk"


# ── extraction fixtures (shared by the stage and confirmation tests) ──────────

def result_of(pages: list[tuple[int, str, str]], *, outcome=X.OUTCOME_SUCCEEDED,
              pages_total=None, ocr: dict | None = None, error_code=None):
    """pages: (number, state, text). Builds text exactly as extract_pdf does."""
    chunks = [t for _, state, t in pages if state in (X.PAGE_TEXT_FOUND, X.PAGE_TEXT_SUSPECT)]
    r = X.ExtractionResult(outcome=outcome, completeness="complete", error_code=error_code,
                           pages_total=pages_total or len(pages))
    r.page_reports = [X.PageReport(n, state, chars=len(t) if t else 0) for n, state, t in pages]
    r.pages_with_text = len(chunks)
    r.ocr_pages = [OcrPageResult(page_number=n, status="ocr_completed_unconfirmed", text=t)
                   for n, t in (ocr or {}).items()]
    return r, "\n".join(chunks)


def pdf_with(pages: list[str]) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for line in pages:
        c.drawString(72, 720, line)
        c.showPage()
    c.save()
    return buf.getvalue()


def _fake_extraction(monkeypatch, *, before_return=None, ocr=None, pages=None):
    from app.ai import extraction_runner

    async def fake(path, **kwargs):
        if before_return:
            await before_return()
        return result_of(pages or [(1, X.PAGE_TEXT_FOUND, "Clause 1.")], ocr=ocr)

    monkeypatch.setattr(extraction_runner, "extract_isolated", fake)
