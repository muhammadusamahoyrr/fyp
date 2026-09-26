"""The one way a route produces a standalone document.

WHY THIS EXISTS

Seven routes produced documents by calling `document_service.generate_standalone`
directly: the quick notice, the labour demand notice, three inheritance
documents, the dispute petition and the court-Urdu pleading. That function
always writes a LEGACY row — a `file_path`, no revision, no `schema_version: 2`.

So switching DOCUMENTS_V2 on did not make new documents V2. The moment it was
on, these routes would start producing mixed records again: documents with no
revision to name, no hash, invisible to `/documents/v2/mine` (which lists only
`schema_version: 2`), and served only by the legacy download.

This facade is the single seam. With the flag OFF it is `generate_standalone`,
byte for byte. With it ON it creates a V2 document and renders its first
revision, and hands the caller a dict shaped like the legacy one — `_id`,
`title`, `compliance`, `verification`, `status` — so no route's response changes
shape. What it adds is `revision_id` and `pdf_sha256`, which a V2 document
cannot be downloaded without (the legacy download serves only legacy rows while
the flag is on) and which a legacy document has as None.

`tests/test_document_writer.py` asserts no route calls `generate_standalone`
directly, so the next writer cannot quietly reintroduce the split.

IDEMPOTENCY

A caller should pass the request's `Idempotency-Key` — the frontend mints one
per user intent and reuses it on a retry. With V2 on, what is keyed is the
REQUEST, not the rendered fields:

  * `request_fingerprint(route, body)` hashes the raw request. It is stored on
    the document when it is created and compared on every later use of the key.
    Same key, same request → the finished document is REPLAYED. Same key,
    different request → 409 (`_KEY_REUSED`), never the earlier PDF.
  * Routes that derive their fields from free text or an LLM (the quick notice,
    the petition) call `replay_owned_document` BEFORE deriving anything. Their
    fields can differ between two runs of the same request, so a retry must be
    answered from what was already produced, not re-derived and re-compared.

Without a key a fresh one is minted: every call a new document, which is the
behaviour these routes always had. A supplied key is validated in the same
format the V2 routes require, on either path; the legacy path has no
idempotency to offer and otherwise ignores it.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException

from app.core.config import settings
from app.core.constants import DocumentTemplate
from app.core.exceptions import AppValidationError, ConflictError

logger = logging.getLogger(__name__)


def _title_for(template_type: str) -> str:
    # The legacy path's own title table, so a document is named the same
    # whichever backend produced it.
    from app.services.document_service import TEMPLATE_TITLES
    try:
        return TEMPLATE_TITLES.get(DocumentTemplate(template_type), template_type)
    except ValueError:
        return template_type


def request_fingerprint(route: str, body: dict | None) -> str:
    """The identity of one request, for comparing a reused key."""
    from app.services.document_transitions import canonical_body_hash
    return canonical_body_hash({"route": route, "body": body or {}})


def _validate(key: str | None) -> None:
    if key is not None:
        from app.services.document_transitions import validate_idempotency_key
        validate_idempotency_key(key)


def _result(doc: dict, rev: dict, owner_id: str, template_type: str) -> dict:
    if rev.get("status") != "generated":
        raise AppValidationError("PDF generation failed.")
    return {
        "_id": doc["_id"],
        "case_id": None,
        "client_id": owner_id,
        "template_type": template_type,
        "title": doc.get("title") or _title_for(template_type),
        # What was rendered — a replayed response is built from THIS, not from
        # a fresh derivation that may differ.
        "fields": rev.get("fields") or {},
        "compliance": rev.get("compliance"),
        "verification": rev.get("verification"),
        "status": "generated",
        "schema_version": 2,
        "revision_id": rev["_id"],
        "pdf_sha256": rev.get("pdf_sha256"),
    }


async def replay_owned_document(
    owner_id: str, idempotency_key: str | None, fingerprint: str,
) -> dict | None:
    """The document this exact request already produced, or None.

    None when there is nothing to replay: V2 off, no key, no document for the
    key yet, or a document whose render never started (the caller then carries
    on, and `create_document` returns that same identity). Raises 409 when the
    key was used for a DIFFERENT request.
    """
    _validate(idempotency_key)
    if not settings.documents_v2 or not idempotency_key:
        return None

    from app.db.collections import get_documents_col
    from app.repositories import revision_repo
    from app.services import document_v2_service as v2

    doc = await get_documents_col().find_one(
        {"client_id": owner_id, "create_idempotency_key": idempotency_key})
    if not doc:
        return None
    expected = v2.create_fingerprint(
        template_type=doc.get("template_type"), title=doc.get("title"),
        case_id=doc.get("case_id"), request_fingerprint=fingerprint)
    if doc.get("create_fingerprint") not in (None, expected):
        raise ConflictError(v2._KEY_REUSED)

    rev = await revision_repo.find_by_idempotency(doc["_id"], idempotency_key)
    if not rev:
        return None
    # The revision's OWN template and fields: this is a replay of what that
    # request rendered, and re-deriving them could only disagree. Waits for a
    # render still in flight rather than starting a second one.
    rev = await v2.generate_revision(
        document_id=doc["_id"], template_type=rev["template_type"],
        fields=rev.get("fields") or {}, idempotency_key=idempotency_key)
    return _result(doc, rev, owner_id, rev.get("template_type") or doc["template_type"])


async def generate_owned_document(
    owner_id: str, template_type: str, fields: dict, *,
    idempotency_key: str | None = None,
    request_fingerprint: str | None = None,
) -> dict:
    """Produce a standalone document owned by `owner_id`, on whichever backend
    is live. Returns the legacy-shaped dict plus `revision_id`/`pdf_sha256`."""
    _validate(idempotency_key)
    if not settings.documents_v2:
        from app.services import document_service
        doc = await document_service.generate_standalone(owner_id, template_type, fields)
        return {**doc, "revision_id": None, "pdf_sha256": None}

    from app.services import document_v2_service as v2

    if idempotency_key and request_fingerprint:
        replayed = await replay_owned_document(owner_id, idempotency_key, request_fingerprint)
        if replayed:
            return replayed

    key = idempotency_key or secrets.token_urlsafe(16)
    doc = await v2.create_document(
        client_id=owner_id, case_id=None, template_type=template_type,
        title=_title_for(template_type), idempotency_key=key,
        request_fingerprint=request_fingerprint)
    try:
        rev = await v2.generate_revision(
            document_id=doc["_id"], template_type=template_type,
            fields=fields, idempotency_key=key)
    except HTTPException:
        raise                      # a typed refusal (422/409/503) passes through
    except Exception as exc:       # noqa: BLE001 — same contract as the legacy path
        logger.error("V2 standalone generation failed for %s: %s",
                     doc["_id"], type(exc).__name__)
        raise AppValidationError(f"PDF generation failed: {exc}")
    return _result(doc, rev, owner_id, template_type)
