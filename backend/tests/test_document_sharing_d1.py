"""Decision D1 (2026-10-03) on the LEGACY submit path.

The legacy `submit_for_review` used the case's lawyer if there was one, and
otherwise ANY lawyer the client named who was flagged KYC-verified -- no
relationship needed. Both submit paths now share one rule
(`document_sharing.require_accepted_engagement`): only through an ACCEPTED
engagement with that lawyer, on the document's case when it has one.
(The DOCUMENTS_V2 path is covered in test_v2_authorization.py.)
"""
from __future__ import annotations

import secrets

import pytest

from app.core.exceptions import ForbiddenError
from app.db.collections import get_documents_col, get_users_col
from app.services import document_service
from tests._engagement_support import disengage, engage

TAG = secrets.token_hex(3)
CLIENT = f"d1-client-{TAG}"
LAWYER = f"d1-lawyer-{TAG}"
OTHER = f"d1-other-{TAG}"


@pytest.fixture(autouse=True)
async def _people(mongo):
    for lawyer in (LAWYER, OTHER):
        await get_users_col().update_one(
            {"_id": lawyer}, {"$set": {"_id": lawyer, "role": "lawyer", "email": f"{lawyer}@test.invalid",
                                       "full_name": "L", "lawyer_profile": {"kyc_verified": True}}},
            upsert=True)
    yield
    await disengage(CLIENT, LAWYER, OTHER)
    await get_documents_col().delete_many({"client_id": CLIENT})
    await get_users_col().delete_many({"_id": {"$in": [LAWYER, OTHER]}})


async def legacy_doc(case_id=None) -> str:
    doc_id = f"d1-doc-{secrets.token_hex(4)}"
    await get_documents_col().insert_one({"_id": doc_id, "client_id": CLIENT, "case_id": case_id,
                                          "status": "generated", "title": "A notice",
                                          "template_type": "legal_notice"})
    return doc_id


async def test_a_caseless_legacy_document_needs_an_accepted_engagement():
    doc_id = await legacy_doc()
    with pytest.raises(ForbiddenError, match="accepted engagement"):
        await document_service.submit_for_review(doc_id, CLIENT, OTHER, None, "normal")
    assert (await get_documents_col().find_one({"_id": doc_id})).get("review_status") != "submitted"

    await engage(CLIENT, LAWYER)
    out = await document_service.submit_for_review(doc_id, CLIENT, LAWYER, None, "normal")
    assert out["review_status"] == "submitted"


@pytest.mark.parametrize("status", ["requested", "terms_proposed", "completed", "terminated",
                                    "declined", "cancelled"])
async def test_a_non_accepted_engagement_authorises_nothing_on_the_legacy_path(status):
    await engage(CLIENT, OTHER, status=status)
    doc_id = await legacy_doc()
    with pytest.raises(ForbiddenError, match="accepted engagement"):
        await document_service.submit_for_review(doc_id, CLIENT, OTHER, None, "normal")


async def test_a_legacy_case_document_needs_the_engagement_on_its_case():
    await engage(CLIENT, LAWYER, case_id="another-matter")
    doc_id = await legacy_doc(case_id=None)
    # (no case: the engagement on another matter is enough)
    assert (await document_service.submit_for_review(doc_id, CLIENT, LAWYER, None, "normal"))["review_status"] \
        == "submitted"
    case_doc = await legacy_doc(case_id="this-matter")
    with pytest.raises(ForbiddenError, match="on that case"):
        await document_service.submit_for_review(case_doc, CLIENT, LAWYER, None, "normal")
