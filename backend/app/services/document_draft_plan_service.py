"""Client prompt planning for DOCUMENTS_V2.

This module is deliberately an intake layer, not a second document engine.
Plans collect a template and reviewed fields; confirmed plans are handed to
``document_v2_service`` which remains authoritative for identity, immutable
revisions, hashes, checks and artifacts.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ReturnDocument

from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)
from app.db.collections import get_document_draft_plans_col, get_documents_col
from app.repositories import revision_repo
from app.repositories.case_repo import CaseRepository
from app.services import document_service
from app.services import document_v2_service as v2
from app.services import template_registry
from app.services.document_transitions import (
    canonical_body_hash,
    validate_idempotency_key,
)

MAX_PROMPT_CHARS = 8_000
MAX_ANSWER_CHARS = 4_000
MAX_QUESTIONS = 3
PLAN_LIFETIME = timedelta(days=7)
# How long one generation attempt owns a plan. A browser that reloads or loses
# its connection mid-generation loses its (client-held) retry key; after the
# lease lapses a NEW key may reclaim the plan instead of it staying stuck in
# ``generating`` forever. Longer than a normal render; short enough to recover.
GENERATION_LEASE = timedelta(minutes=3)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """Mongo returns naive UTC datetimes; compare them as UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return not value
    return False


def _humanise(field: str) -> str:
    special = {
        "cnic": "CNIC", "dob": "date of birth", "fir": "FIR",
        "poa": "power of attorney", "sp": "SP",
    }
    words = []
    for word in field.split("_"):
        words.append(special.get(word, word))
    return " ".join(words)


# These are drafting details, not assertions of statutory requiredness.  Legal
# completeness remains pleading_rules' job and is frozen on the V2 revision.
_ESSENTIAL_FIELDS: dict[str, tuple[str, ...]] = {
    "nda": ("party_a", "party_b", "purpose", "duration", "jurisdiction"),
    "rental_agreement": (
        "landlord_name", "tenant_name", "property_address", "monthly_rent",
        "tenancy_period", "start_date", "province",
    ),
    "legal_notice": (
        "sender_name", "recipient_name", "notice_body", "demand",
        "response_days",
    ),
    "plaint_civil": (
        "plaintiff_name", "defendant_name", "court_name", "facts",
        "cause_of_action", "relief_sought",
    ),
    "written_statement": (
        "plaintiff_name", "defendant_name", "court_name",
        "preliminary_objections", "reply_on_merits",
    ),
    "fir_application": (
        "police_station", "district", "incident_date", "incident_place",
        "incident_facts", "accused_details",
    ),
    "complaint_154_3": (
        "police_station", "district", "application_date", "incident_facts",
    ),
    "petition_22a": (
        "complainant_name", "police_station", "district", "incident_facts",
        "application_date",
    ),
    "fia_cybercrime": (
        "fia_office_city", "incident_date", "platform", "incident_facts",
        "accused_details", "evidence_list",
    ),
    "guardianship_petition": (
        "court_name", "petitioner_name", "petitioner_address", "minor_name",
        "minor_dob", "minor_residence", "application_scope", "causes",
    ),
    "wakalatnama_checklist": (
        "court_name", "case_title", "appointer_name", "pleader_name",
        "party_represented",
    ),
}


# Long/specific phrases are evaluated first.  This is a conservative router:
# an uncertain prompt asks the user for a type instead of inventing one.
_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "petition_22a": ("22-a", "22a", "justice of peace"),
    "complaint_154_3": ("154(3)", "154 3", "complaint to sp"),
    "fia_cybercrime": ("fia cybercrime", "cyber crime", "cybercrime"),
    "written_statement": ("written statement", "reply to plaint"),
    "guardianship_petition": ("guardianship", "guardian petition"),
    "wakalatnama_checklist": ("wakalatnama checklist", "pleader appointment checklist"),
    "rental_agreement": ("rental agreement", "rent agreement", "tenancy agreement", "lease agreement"),
    "legal_notice": ("legal notice", "demand notice"),
    "plaint_civil": ("civil plaint", "civil suit", "plaint"),
    "fir_application": ("fir application", "register fir", "first information report"),
    "nda": ("non-disclosure", "non disclosure", "nda", "confidentiality agreement"),
}


def supported_template_types() -> tuple[str, ...]:
    """Templates prompt extraction genuinely supports, never aspirational ones."""
    return tuple(sorted(
        item["template_type"]
        for item in template_registry.listing()
        if document_service.supports_field_extraction(item["template_type"])
        and not item["structured_fields"]
    ))


def template_choices() -> list[dict[str, str]]:
    return [
        {"value": template_type,
         "label": template_registry.label_for(template_type)}
        for template_type in supported_template_types()
    ]


def _alias_pattern(alias: str) -> re.Pattern:
    # Whole tokens only. A raw substring test matched "plaint" inside
    # "complaint" and "nda" inside "standard"/"agenda"/"mandate", silently
    # choosing a legal instrument the user never asked for.
    return re.compile(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])")


_ALIAS_PATTERNS: dict[str, tuple[tuple[str, re.Pattern], ...]] = {
    template_type: tuple((alias, _alias_pattern(alias)) for alias in aliases)
    for template_type, aliases in _TYPE_ALIASES.items()
}


def infer_template_type(prompt: str) -> str | None:
    text = " ".join((prompt or "").lower()
                    .replace("\u2013", "-").replace("\u2014", "-").split())
    matches: list[tuple[int, str]] = []
    for template_type, aliases in _ALIAS_PATTERNS.items():
        for alias, pattern in aliases:
            if pattern.search(text):
                matches.append((len(alias), template_type))
    if not matches:
        return None
    matches.sort(reverse=True)
    best_length = matches[0][0]
    best = {kind for length, kind in matches if length == best_length}
    return next(iter(best)) if len(best) == 1 else None


def _require_supported(template_type: str) -> str:
    if template_type not in supported_template_types():
        raise AppValidationError(
            "That template cannot be drafted from a prompt. Choose one of the "
            "prompt-supported document types.")
    return template_type


def _normalise_fields(template_type: str, values: dict | None) -> dict:
    allowed = template_registry.fields_for(template_type)
    clean: dict[str, Any] = {}
    for key, value in (values or {}).items():
        if key not in allowed:
            continue
        if isinstance(value, str):
            value = value.strip()
            if len(value) > MAX_ANSWER_CHARS:
                raise AppValidationError(
                    f"{_humanise(key).capitalize()} is too long.")
        elif value is not None and not isinstance(value, (bool, int, float)):
            # Prompt-supported builders consume scalar answers.  Nested
            # calculator payloads belong to dedicated flows, not this planner.
            raise AppValidationError(
                f"{_humanise(key).capitalize()} must be a text or number value.")
        clean[key] = value
    return clean


def _coerce_model_fields(template_type: str, values: dict | None) -> tuple[dict, list[dict]]:
    """Normalise LLM extraction output without failing the user's request.

    ``_normalise_fields`` validates what the USER typed and may refuse it. The
    model's output is different: a list, an object or an overlong value is the
    model's shape, not the user's mistake, and must never surface as a 422.
    Scalars are kept, lists of scalars are joined, overlong text is trimmed,
    anything else is dropped -- and every such change is reported so the plan
    review can say which details need checking.
    """
    allowed = template_registry.fields_for(template_type)
    clean: dict[str, Any] = {}
    notes: list[dict] = []
    if not isinstance(values, dict):
        return clean, notes
    for key, value in values.items():
        if key not in allowed or value is None:
            continue
        if isinstance(value, (list, tuple)):
            if all(isinstance(item, (str, int, float, bool)) for item in value):
                value = "; ".join(str(item).strip() for item in value if str(item).strip())
                notes.append({"field": key, "action": "joined"})
            else:
                notes.append({"field": key, "action": "dropped"})
                continue
        elif isinstance(value, dict):
            notes.append({"field": key, "action": "dropped"})
            continue
        elif not isinstance(value, (str, bool, int, float)):
            notes.append({"field": key, "action": "dropped"})
            continue
        if isinstance(value, str):
            value = value.strip()
            if len(value) > MAX_ANSWER_CHARS:
                value = value[:MAX_ANSWER_CHARS].rstrip()
                notes.append({"field": key, "action": "truncated"})
        clean[key] = value
    return clean, notes


def _essential_fields(template_type: str) -> tuple[str, ...]:
    declared = template_registry.fields_for(template_type)
    configured = _ESSENTIAL_FIELDS.get(template_type, tuple(sorted(declared)))
    return tuple(field for field in configured if field in declared)


def questions_for(template_type: str | None, fields: dict | None) -> tuple[list[dict], int]:
    if not template_type:
        return ([{
            "id": "template_type",
            "field": "template_type",
            "label": "Document type",
            "question": "What type of document do you want to draft?",
            "options": template_choices(),
            "legal_requirement": False,
        }], 1)

    missing = [
        field for field in _essential_fields(template_type)
        if _blank((fields or {}).get(field))
    ]
    questions = [{
        "id": field,
        "field": field,
        "label": _humanise(field).capitalize(),
        "question": f"Please provide the {_humanise(field)}.",
        "options": [],
        "legal_requirement": False,
    } for field in missing[:MAX_QUESTIONS]]
    return questions, len(missing)


def _status(template_type: str | None, fields: dict | None) -> str:
    if not template_type:
        return "needs_template"
    questions, _ = questions_for(template_type, fields)
    return "needs_details" if questions else "ready"


def _public(plan: dict) -> dict:
    questions, remaining = questions_for(plan.get("template_type"), plan.get("fields"))
    if plan.get("status") in {
            "confirmed", "generating", "generated", "generation_failed"}:
        questions = []
    result = {
        "id": plan["_id"],
        "version": plan.get("version", 0),
        "status": plan.get("status"),
        "title": plan.get("title"),
        "template_type": plan.get("template_type"),
        "case_id": plan.get("case_id"),
        "prompt": plan.get("prompt"),
        "fields": plan.get("fields") or {},
        "extraction_status": plan.get("extraction_status", "not_run"),
        "extraction_notes": plan.get("extraction_notes") or [],
        "questions": questions,
        "remaining_detail_count": remaining,
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
        "confirmed_at": plan.get("confirmed_at"),
        "expires_at": plan.get("expires_at"),
    }
    if plan.get("generation"):
        result["generation"] = plan["generation"]
    return result


async def _require_case(owner_id: str, case_id: str | None) -> None:
    if not case_id:
        return
    case = await CaseRepository().find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if str(case.get("client_id") or "") != owner_id:
        raise ForbiddenError("That case does not belong to you")
    from app.services.case_service import assert_not_draft
    assert_not_draft(case, "be used for document drafting")


async def _extract(prompt: str, template_type: str) -> tuple[dict, str, list[dict]]:
    extracted = await document_service.extract_fields_from_text(prompt, template_type)
    clean, notes = _coerce_model_fields(template_type, extracted)
    if not extracted:
        return clean, "failed", notes
    if any(not _blank(value) for value in clean.values()):
        return clean, "ok", notes
    return clean, "empty", notes


async def create_plan(*, owner_id: str, prompt: str,
                      template_type: str | None, title: str | None,
                      case_id: str | None, idempotency_key: str) -> dict:
    validate_idempotency_key(idempotency_key)
    prompt = (prompt or "").strip()
    if not prompt:
        raise AppValidationError("Describe the document you want to draft.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise AppValidationError("The drafting description is too long.")
    await _require_case(owner_id, case_id)

    chosen = _require_supported(template_type) if template_type else infer_template_type(prompt)
    fingerprint = canonical_body_hash({
        "prompt": prompt, "template_type": chosen, "title": title,
        "case_id": case_id,
    })
    col = get_document_draft_plans_col()
    existing = await col.find_one({
        "owner_id": owner_id, "create_idempotency_key": idempotency_key,
    })
    if existing:
        if existing.get("create_fingerprint") != fingerprint:
            raise ConflictError(
                "This request key was already used for a different request.")
        return _public(existing)

    fields: dict = {}
    extraction_status = "not_run"
    extraction_notes: list[dict] = []
    if chosen:
        fields, extraction_status, extraction_notes = await _extract(prompt, chosen)

    now = _now()
    plan = {
        "_id": secrets.token_urlsafe(16),
        "owner_id": owner_id,
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "template_type": chosen,
        "title": (title or "").strip() or (
            f"{template_registry.label_for(chosen)} draft" if chosen
            else "Untitled legal draft"),
        "case_id": case_id,
        "fields": fields,
        "extraction_status": extraction_status,
        "extraction_notes": extraction_notes,
        "status": _status(chosen, fields),
        "version": 0,
        "create_idempotency_key": idempotency_key,
        "create_fingerprint": fingerprint,
        "created_at": now,
        "updated_at": now,
        "expires_at": now + PLAN_LIFETIME,
    }
    try:
        await col.insert_one(plan)
    except Exception:
        winner = await col.find_one({
            "owner_id": owner_id, "create_idempotency_key": idempotency_key,
        })
        if winner:
            if winner.get("create_fingerprint") != fingerprint:
                raise ConflictError(
                    "This request key was already used for a different request.")
            return _public(winner)
        raise
    return _public(plan)


async def get_plan(*, owner_id: str, plan_id: str) -> dict:
    plan = await get_document_draft_plans_col().find_one({
        "_id": plan_id, "owner_id": owner_id,
    })
    if not plan:
        raise NotFoundError("Draft plan")
    return _public(plan)


async def answer_plan(*, owner_id: str, plan_id: str, expected_version: int,
                      answers: dict[str, Any]) -> dict:
    if not answers:
        raise AppValidationError("Provide at least one answer.")
    col = get_document_draft_plans_col()
    plan = await col.find_one({"_id": plan_id, "owner_id": owner_id})
    if not plan:
        raise NotFoundError("Draft plan")
    if plan.get("status") in {"confirmed", "generating", "generated"}:
        raise ConflictError("This draft plan is already confirmed.")
    if plan.get("version", 0) != expected_version:
        raise ConflictError("The draft plan changed. Reload it and try again.")

    chosen = plan.get("template_type")
    supplied_type = answers.get("template_type")
    if supplied_type is not None:
        if not isinstance(supplied_type, str):
            raise AppValidationError("Document type must be text.")
        chosen = _require_supported(supplied_type.strip())

    if not chosen:
        raise AppValidationError("Choose a document type first.")

    fields = dict(plan.get("fields") or {})
    extraction_status = plan.get("extraction_status", "not_run")
    extraction_notes = plan.get("extraction_notes") or []
    if chosen != plan.get("template_type"):
        fields, extraction_status, extraction_notes = await _extract(
            plan.get("prompt") or "", chosen)

    submitted_fields = {k: v for k, v in answers.items() if k != "template_type"}
    unknown = set(submitted_fields) - template_registry.fields_for(chosen)
    if unknown:
        raise AppValidationError(
            "Unknown drafting field(s): " + ", ".join(sorted(unknown)) + ".")
    fields.update(_normalise_fields(chosen, submitted_fields))
    now = _now()
    updated = await col.find_one_and_update(
        {"_id": plan_id, "owner_id": owner_id,
         "version": expected_version,
         "status": {"$in": ["needs_template", "needs_details", "ready"]}},
        {"$set": {
            "template_type": chosen,
            "title": (plan.get("title") if plan.get("template_type") == chosen
                      else f"{template_registry.label_for(chosen)} draft"),
            "fields": fields,
            "extraction_status": extraction_status,
            "extraction_notes": extraction_notes,
            "status": _status(chosen, fields),
            "updated_at": now,
            "expires_at": now + PLAN_LIFETIME,
        }, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise ConflictError("The draft plan changed. Reload it and try again.")
    return _public(updated)


async def confirm_plan(*, owner_id: str, plan_id: str,
                       expected_version: int, skip_missing: bool) -> dict:
    col = get_document_draft_plans_col()
    plan = await col.find_one({"_id": plan_id, "owner_id": owner_id})
    if not plan:
        raise NotFoundError("Draft plan")
    if plan.get("status") in {"confirmed", "generating", "generated"}:
        return _public(plan)
    if plan.get("version", 0) != expected_version:
        raise ConflictError("The draft plan changed. Reload it and try again.")
    template_type = plan.get("template_type")
    if not template_type:
        raise AppValidationError("Choose a document type before confirming.")
    questions, _remaining = questions_for(template_type, plan.get("fields"))
    if questions and not skip_missing:
        raise AppValidationError(
            "Answer the displayed questions, or explicitly skip missing details.")
    if not any(not _blank(v) for v in (plan.get("fields") or {}).values()):
        raise AppValidationError(
            "The plan has no document details. Add at least one answer before confirming.")

    now = _now()
    updated = await col.find_one_and_update(
        {"_id": plan_id, "owner_id": owner_id,
         "version": expected_version,
         "status": {"$in": ["needs_details", "ready"]}},
        {"$set": {"status": "confirmed", "confirmed_at": now,
                  "updated_at": now}, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise ConflictError("The draft plan changed. Reload it and try again.")
    return _public(updated)


async def _reclaim_generation(plan: dict, owner_id: str, idempotency_key: str) -> dict:
    """Hand a stalled ``generating`` plan to a new attempt, only once its lease lapses.

    The caller's key is client-held and is lost on reload; without this the
    plan stayed in ``generating`` forever. While the lease is live the old
    attempt may still be rendering, so a new key is refused. After it lapses
    the plan is claimed atomically -- conditioned on the SAME stale key and an
    expired lease, so two reclaimers cannot both win. A document the old
    attempt created but never recorded is looked up by its create key and kept,
    so a reclaim never makes a second document.
    """
    now = _now()
    lease = _aware(plan.get("generation_lease_expires_at"))
    if lease is not None and lease > now:
        raise ConflictError(
            "This draft plan is already being generated. Try again in a few minutes.")
    old_key = plan.get("generation_idempotency_key")
    update: dict = {
        "generation_idempotency_key": idempotency_key,
        "generation_lease_expires_at": now + GENERATION_LEASE,
        "updated_at": now,
    }
    if not (plan.get("generation") or {}).get("document_id") and old_key:
        orphan = await get_documents_col().find_one(
            {"client_id": owner_id, "create_idempotency_key": old_key,
             "schema_version": 2}, {"_id": 1})
        if orphan:
            update["generation.document_id"] = orphan["_id"]
    reclaimed = await get_document_draft_plans_col().find_one_and_update(
        {"_id": plan["_id"], "owner_id": owner_id, "status": "generating",
         "generation_idempotency_key": old_key,
         "$or": [{"generation_lease_expires_at": {"$lte": now}},
                 {"generation_lease_expires_at": {"$exists": False}}]},
        {"$set": update, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if not reclaimed:
        raise ConflictError(
            "This draft plan is already being generated. Try again in a few minutes.")
    return reclaimed


async def generate_plan(*, owner_id: str, plan_id: str,
                        expected_version: int,
                        idempotency_key: str) -> dict:
    """Claim once, then hand off to V2 using the caller's retry key.

    A crash after the claim leaves ``generating`` with the key.  Repeating the
    same request resumes the two idempotent V2 calls; a different key cannot
    create a second document from the same confirmed plan.
    """
    validate_idempotency_key(idempotency_key)
    col = get_document_draft_plans_col()
    plan = await col.find_one({"_id": plan_id, "owner_id": owner_id})
    if not plan:
        raise NotFoundError("Draft plan")
    if plan.get("status") == "generated":
        if plan.get("generation_idempotency_key") != idempotency_key:
            raise ConflictError("This draft plan has already generated a document.")
        return _public(plan)
    if plan.get("status") == "generating":
        if plan.get("generation_idempotency_key") != idempotency_key:
            plan = await _reclaim_generation(plan, owner_id, idempotency_key)
    elif plan.get("status") in {"confirmed", "generation_failed"}:
        if plan.get("version", 0) != expected_version:
            raise ConflictError("The draft plan changed. Reload it and try again.")
        if (plan.get("status") == "generation_failed"
                and plan.get("failed_generation_key") == idempotency_key):
            raise ConflictError(
                "That generation attempt failed. Retry with a new request key.")
        now = _now()
        claimed = await col.find_one_and_update(
            {"_id": plan_id, "owner_id": owner_id,
             "version": expected_version,
             "status": {"$in": ["confirmed", "generation_failed"]}},
            {"$set": {"status": "generating",
                      "generation_idempotency_key": idempotency_key,
                      "generation_lease_expires_at": now + GENERATION_LEASE,
                      "updated_at": now},
             "$unset": {"generation_error": ""},
             "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if not claimed:
            raise ConflictError("The draft plan changed. Reload it and try again.")
        plan = claimed
    else:
        raise ConflictError("Confirm the draft plan before generating it.")

    template_type = plan["template_type"]
    document_id = (plan.get("generation") or {}).get("document_id")
    if document_id:
        document = await get_documents_col().find_one({
            "_id": document_id, "client_id": owner_id, "schema_version": 2,
        })
        if not document:
            raise ConflictError(
                "The document created for this plan is unavailable.")
    else:
        document = await v2.create_document(
            client_id=owner_id,
            case_id=plan.get("case_id"),
            template_type=template_type,
            title=plan["title"],
            idempotency_key=idempotency_key,
            request_fingerprint=canonical_body_hash({
                "plan_id": plan_id, "plan_version": plan.get("version"),
            }),
        )
        # Persist the identity before rendering.  If rendering fails, a retry
        # creates a new revision on this document rather than a duplicate
        # document identity.
        saved = await col.find_one_and_update(
            {"_id": plan_id, "owner_id": owner_id, "status": "generating",
             "generation_idempotency_key": idempotency_key},
            {"$set": {"generation.document_id": document["_id"],
                      "updated_at": _now()}},
            return_document=ReturnDocument.AFTER,
        )
        if not saved:
            raise ServiceUnavailableError(
                "The draft document was created but its plan could not be updated. "
                "Retry with the same key.")
        plan = saved

    try:
        revision = await v2.generate_revision(
            document_id=document["_id"],
            template_type=template_type,
            fields=plan.get("fields") or {},
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        failed = await revision_repo.find_by_idempotency(
            document["_id"], idempotency_key)
        if failed and failed.get("status") == "failed":
            await col.find_one_and_update(
                {"_id": plan_id, "owner_id": owner_id,
                 "status": "generating",
                 "generation_idempotency_key": idempotency_key},
                {"$set": {
                    "status": "generation_failed",
                    "failed_generation_key": idempotency_key,
                    "generation_error": "render_failed",
                    "updated_at": _now(),
                }, "$unset": {"generation_idempotency_key": ""},
                 "$inc": {"version": 1}},
            )
            raise ServiceUnavailableError(
                "Document generation failed. Reload the plan and retry.") from exc
        raise
    if revision.get("status") != "generated":
        if revision.get("status") == "failed":
            await col.find_one_and_update(
                {"_id": plan_id, "owner_id": owner_id,
                 "status": "generating",
                 "generation_idempotency_key": idempotency_key},
                {"$set": {
                    "status": "generation_failed",
                    "failed_generation_key": idempotency_key,
                    "generation_error": "render_failed",
                    "updated_at": _now(),
                }, "$unset": {"generation_idempotency_key": ""},
                 "$inc": {"version": 1}},
            )
            raise ServiceUnavailableError(
                "Document generation failed. Reload the plan and retry.")
        raise ServiceUnavailableError(
            "The document revision did not finish generating. Retry with the same key.")

    generation = {
        "document_id": document["_id"],
        "revision_id": revision["_id"],
        "version": revision.get("version"),
        "pdf_sha256": revision.get("pdf_sha256"),
        "status": revision.get("status"),
    }
    now = _now()
    updated = await col.find_one_and_update(
        {"_id": plan_id, "owner_id": owner_id,
         "status": "generating",
         "generation_idempotency_key": idempotency_key},
        {"$set": {"status": "generated", "generation": generation,
                  "updated_at": now},
         "$unset": {"prompt": ""},
         "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        # The legal artifact exists and is safe.  Report an explicitly
        # retryable workflow-state failure; the same key recovers it.
        raise ServiceUnavailableError(
            "The document was generated but its plan status could not be saved. "
            "Retry with the same key.")
    return _public(updated)
