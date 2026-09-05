"""DOCUMENTS_V2 · Stage 5 — drafting modes, scrubbed context, jurisdiction.

  * scrub minimises obvious PII (best-effort);
  * build_case_context is a tight whitelist — no client PII leaks;
  * resolve_general validates case_type (422) and never coerces an unknown
    province to 'federal' (→ UNSPECIFIED);
  * case-bound drafting authorises the case server-side (403 for a non-owner);
  * the server type guard: generate has no template default (invalid → 422).
"""
from __future__ import annotations

import uuid

import httpx
import pytest

from app.core.exceptions import AppValidationError, ForbiddenError
from app.ai.jurisdiction import UNSPECIFIED
from app.services import case_context as cc


# ── unit: scrubbing + whitelist + jurisdiction ────────────────────────────────

def test_scrub_redacts_pii():
    s = cc.scrub("Reach me at ali@example.com or 0300-1234567, CNIC 35201-1234567-1.")
    assert "ali@example.com" not in s
    assert "0300-1234567" not in s
    assert "35201-1234567-1" not in s
    assert "[redacted]" in s


def test_build_case_context_is_a_tight_whitelist():
    case = {
        "case_type": "civil", "province": "Punjab", "case_number": "CS-2026-1",
        "ai_summary": "Tenant dispute. Contact 0300-1234567.",
        # none of the below must appear in the context
        "client_name": "Jane Client", "client_email": "jane@x.com",
        "client_phone": "0311-9999999", "lawyer_id": "lw-1", "balance": 50000,
    }
    ctx = cc.build_case_context(case)
    assert set(ctx.keys()) == {"case_type", "province", "case_number", "summary"}
    assert ctx["province"] == "punjab"                 # normalised
    blob = str(ctx)
    assert "Jane" not in blob and "jane@x.com" not in blob and "lw-1" not in blob
    assert "0300-1234567" not in ctx["summary"]        # scrubbed


def test_context_block_marks_untrusted():
    block = cc.context_block(cc.build_case_context({"case_type": "civil", "province": "sindh"}))
    assert "untrusted data" in block.lower()
    assert "not instructions" in block.lower()


def test_resolve_general_validates_case_type():
    ct, prov = cc.resolve_general("civil", "punjab")
    assert ct == "civil" and prov == "punjab"
    with pytest.raises(AppValidationError):
        cc.resolve_general("banana", "punjab")
    with pytest.raises(AppValidationError):
        cc.resolve_general(None, "punjab")


def test_resolve_general_unknown_province_is_unspecified_not_federal():
    _ct, prov = cc.resolve_general("civil", "atlantis")
    assert prov == UNSPECIFIED
    assert prov != "federal"
    _ct, prov2 = cc.resolve_general("civil", None)
    assert prov2 == UNSPECIFIED


# ── integration: case-bound authorization + general 422 via HTTP ──────────────

pytestmark_int = pytest.mark.integration


@pytest.mark.integration
async def test_case_bound_drafting_authorizes_case(mongo):
    """A lawyer not on the case cannot draft against it — get_case raises before
    any streaming or model call."""
    from app.api.v1.routes.ai import DraftRequest, ai_draft_stream
    from app.db.collections import get_cases_col

    case_id = "s5-case-" + uuid.uuid4().hex[:8]
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": "s5-client", "lawyer_id": "owner-lawyer",
        "case_type": "civil", "province": "punjab", "case_number": "CS-1",
        "description": "A civil matter.", "status": "open"})
    try:
        body = DraftRequest(instruction="draft a plaint", case_id=case_id)
        with pytest.raises(ForbiddenError):
            await ai_draft_stream(body, current_user={"_id": "intruder-lawyer",
                                                      "role": "lawyer"})
    finally:
        await get_cases_col().delete_one({"_id": case_id})


@pytest.mark.integration
async def test_general_drafting_invalid_case_type_422(mongo):
    """General drafting with an invalid case_type returns 422 before streaming."""
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {
        "_id": "lw", "role": "lawyer", "is_active": True}
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/api/v1/ai/draft/stream",
                             json={"instruction": "draft", "case_type": "banana"})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
async def test_generate_route_has_no_template_default(mongo):
    """The server type guard: an invalid/missing template_type is a 422 — there
    is no silent 'plaint_civil' default on the server (that fallback was frontend
    only)."""
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {
        "_id": "cl", "role": "client", "is_active": True}
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/api/v1/documents/generate",
                             json={"case_id": "x", "template_type": "not_a_template"})
        assert r.status_code == 422       # enum validation, no coercion
    finally:
        app.dependency_overrides.clear()
