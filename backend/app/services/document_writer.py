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

A caller may pass the request's `Idempotency-Key`. With one, a retry of the same
intent returns the same document and revision instead of a second pair — the V2
guarantee. Without one, a fresh key is minted, which is exactly today's
behaviour (every call a new document) and no worse. The legacy path has no
idempotency to offer and ignores it.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException

from app.core.config import settings
from app.core.constants import DocumentTemplate
from app.core.exceptions import AppValidationError

logger = logging.getLogger(__name__)


def _title_for(template_type: str) -> str:
    # The legacy path's own title table, so a document is named the same
    # whichever backend produced it.
    from app.services.document_service import TEMPLATE_TITLES
    try:
        return TEMPLATE_TITLES.get(DocumentTemplate(template_type), template_type)
    except ValueError:
        return template_type


async def generate_owned_document(
    owner_id: str, template_type: str, fields: dict, *,
    idempotency_key: str | None = None,
) -> dict:
    """Produce a standalone document owned by `owner_id`, on whichever backend
    is live. Returns the legacy-shaped dict plus `revision_id`/`pdf_sha256`."""
    if not settings.documents_v2:
        from app.services import document_service
        doc = await document_service.generate_standalone(owner_id, template_type, fields)
        return {**doc, "revision_id": None, "pdf_sha256": None}

    from app.services import document_v2_service as v2

    key = idempotency_key or secrets.token_urlsafe(16)
    title = _title_for(template_type)
    doc = await v2.create_document(
        client_id=owner_id, case_id=None, template_type=template_type,
        title=title, idempotency_key=key)
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

    if rev.get("status") != "generated":
        raise AppValidationError("PDF generation failed.")

    return {
        "_id": doc["_id"],
        "case_id": None,
        "client_id": owner_id,
        "template_type": template_type,
        "title": doc.get("title") or title,
        "compliance": rev.get("compliance"),
        "verification": rev.get("verification"),
        "status": "generated",
        "schema_version": 2,
        "revision_id": rev["_id"],
        "pdf_sha256": rev.get("pdf_sha256"),
    }
