"""Non-mutating AI suggestions for the DOCUMENTS_V2 editor."""
from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel, Field

from app.ai.provider_health import PURPOSE_DOCUMENT_DRAFTING
from app.core.exceptions import AppValidationError, ConflictError, ServiceUnavailableError
from app.db.collections import get_documents_col
from app.services.document_service import _clean_draft_html, visible_text
from app.services import template_registry


class WorkspaceSuggestion(BaseModel):
    body_html: str = Field(description="Complete revised document body as simple HTML")
    summary: str = Field(description="Short factual summary of the proposed changes")


class WorkspaceFieldSuggestion(BaseModel):
    fields: dict = Field(description="Complete revised template fields")
    summary: str = Field(description="Short factual summary of the proposed changes")


SYSTEM = """You assist with editing a Pakistani legal draft.
Return a proposal, never a final legal opinion. Follow the user's instruction while:
- preserving names, dates, amounts, citations and facts unless explicitly asked to change them;
- never inventing a missing fact, authority, case number or statutory citation;
- keeping unresolved facts as clear [PLACEHOLDER] text;
- returning the COMPLETE revised body, not a patch;
- using only simple document HTML (paragraphs, headings, emphasis, lists and blockquotes).
The user will review the proposal before it can become a new revision."""


async def propose(*, document_id: str, owner_id: str, body_html: str,
                  instruction: str, expected_revision_id: str,
                  expected_version: int, expected_content_epoch: int) -> dict:
    instruction = (instruction or "").strip()
    if not instruction:
        raise AppValidationError("Tell the assistant what to change.")

    guard = {
        "_id": document_id,
        "client_id": owner_id,
        "schema_version": 2,
        "current_revision_id": expected_revision_id,
        "current_version": expected_version,
    }
    if expected_content_epoch == 0:
        guard["$or"] = [
            {"content_epoch": 0}, {"content_epoch": {"$exists": False}},
        ]
    else:
        guard["content_epoch"] = expected_content_epoch
    if not await get_documents_col().find_one(guard, {"_id": 1}):
        raise ConflictError(
            "This document changed since you opened the editor. Reload before using AI Assist.")

    clean_input = _clean_draft_html(body_html or "")
    if not visible_text(clean_input):
        raise AppValidationError("The editor is empty.")

    try:
        from app.ai.llm import get_structured_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = get_structured_llm(
            WorkspaceSuggestion, purpose=PURPOSE_DOCUMENT_DRAFTING)
        proposal: WorkspaceSuggestion = await asyncio.to_thread(llm.invoke, [
            SystemMessage(content=SYSTEM),
            HumanMessage(content=(
                f"EDIT INSTRUCTION:\n{instruction}\n\n"
                f"CURRENT DOCUMENT HTML:\n{clean_input}"
            )),
        ])
    except (AppValidationError, ConflictError):
        raise
    except Exception as exc:
        raise ServiceUnavailableError(
            "AI Assist is temporarily unavailable. Your draft was not changed.") from exc

    # The model is untrusted input to the browser just like pasted HTML.
    proposed_html = _clean_draft_html(proposal.body_html or "")
    if not visible_text(proposed_html):
        raise ServiceUnavailableError(
            "AI Assist returned an empty proposal. Your draft was not changed.")

    # A slow model call must not hand back a proposal labelled for an obsolete
    # revision.  Nothing was mutated, so the user can safely retry after reload.
    if not await get_documents_col().find_one(guard, {"_id": 1}):
        raise ConflictError(
            "This document changed while AI Assist was working. Reload before applying changes.")

    return {
        "body_html": proposed_html,
        "summary": (proposal.summary or "Proposed edit").strip()[:1000],
        "base_revision_id": expected_revision_id,
        "base_version": expected_version,
        "content_epoch": expected_content_epoch,
        "applied": False,
    }


async def propose_fields(*, document_id: str, owner_id: str,
                         template_type: str, fields: dict,
                         instruction: str, expected_revision_id: str,
                         expected_version: int,
                         expected_content_epoch: int) -> dict:
    """Suggest field changes without converting a named template to prose."""
    instruction = (instruction or "").strip()
    if not instruction:
        raise AppValidationError("Tell the assistant what to change.")
    allowed = template_registry.fields_for(template_type)
    if not allowed:
        raise AppValidationError("This template has no editable fields.")
    current = {key: value for key, value in (fields or {}).items()
               if key in allowed}
    guard = {
        "_id": document_id, "client_id": owner_id, "schema_version": 2,
        "current_revision_id": expected_revision_id,
        "current_version": expected_version,
    }
    if expected_content_epoch == 0:
        guard["$or"] = [
            {"content_epoch": 0}, {"content_epoch": {"$exists": False}},
        ]
    else:
        guard["content_epoch"] = expected_content_epoch
    if not await get_documents_col().find_one(guard, {"_id": 1}):
        raise ConflictError(
            "This document changed since you opened the editor. Reload before using AI Assist.")

    try:
        from app.ai.llm import get_structured_llm
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = get_structured_llm(
            WorkspaceFieldSuggestion, purpose=PURPOSE_DOCUMENT_DRAFTING)
        proposal: WorkspaceFieldSuggestion = await asyncio.to_thread(llm.invoke, [
            SystemMessage(content=(SYSTEM + "\nReturn template fields, not document HTML. "
                                   "Keep every existing value unless the instruction changes it.")),
            HumanMessage(content=(
                f"TEMPLATE: {template_type}\n"
                f"ALLOWED FIELDS: {', '.join(sorted(allowed))}\n"
                f"EDIT INSTRUCTION:\n{instruction}\n\n"
                f"CURRENT FIELDS:\n{json.dumps(current, ensure_ascii=False)}"
            )),
        ])
    except (AppValidationError, ConflictError):
        raise
    except Exception as exc:
        raise ServiceUnavailableError(
            "AI Assist is temporarily unavailable. Your draft was not changed.") from exc

    proposed = {key: value for key, value in (proposal.fields or {}).items()
                if key in allowed and isinstance(value, (str, int, float, bool))}
    # Missing model keys retain their reviewed values.  The assistant proposes
    # a patch semantically, while the response remains a complete form.
    merged = {**current, **proposed}
    if not any(str(value).strip() for value in merged.values()):
        raise ServiceUnavailableError(
            "AI Assist returned an empty proposal. Your draft was not changed.")
    if not await get_documents_col().find_one(guard, {"_id": 1}):
        raise ConflictError(
            "This document changed while AI Assist was working. Reload before applying changes.")
    return {
        "fields": merged,
        "summary": (proposal.summary or "Proposed edit").strip()[:1000],
        "mode": "structured_fields",
        "base_revision_id": expected_revision_id,
        "base_version": expected_version,
        "content_epoch": expected_content_epoch,
        "applied": False,
    }
