"""The analyzer AI layer's provider contract, read from app.core.config.

One provider, one pinned model, no fallback. The settings live with the rest
of the analyzer's in `app/core/config.py` (ANALYZER_AI_*); this module only
VALIDATES them -- for readiness, at startup -- and states the resolved
contract that every AI output records.

  provider   "groq", the only one supported. Nothing else is ever called.
  model      pinned, and in the allowlist. Never chosen at runtime.
  policy id  the data-protection checklist the deployment was reviewed
             against, e.g. AAI-AI-DP-001.
  ZDR        "unverified" unless a person verified zero data retention, and
             then the date (not in the future) and where the evidence is
             kept. Unverified -> synthetic documents only, and the contract
             never says ZDR applies.

Problems are fixed vocabulary: no key, model id or evidence text is echoed.
"""
from __future__ import annotations

import re
from datetime import date

PROVIDER_GROQ = "groq"
ZDR_UNVERIFIED = "unverified"
ZDR_VERIFIED = "verified"

AI_PROVIDER_UNSUPPORTED = "ai_provider_unsupported: ANALYZER_AI_PROVIDER must be groq"
AI_MODEL_NOT_PINNED = "ai_model_not_pinned: ANALYZER_AI_MODEL is empty"
AI_ALLOWLIST_EMPTY = "ai_model_allowlist_empty: ANALYZER_AI_MODEL_ALLOWLIST names no model"
AI_MODEL_NOT_ALLOWLISTED = "ai_model_not_allowlisted: ANALYZER_AI_MODEL is not in the allowlist"
AI_KEY_MISSING = "ai_key_missing: GROQ_API_KEY is empty"
AI_POLICY_ID_MISSING = "ai_policy_id_missing: ANALYZER_AI_POLICY_ID is empty or malformed"
AI_ZDR_STATUS_INVALID = "ai_zdr_status_invalid: ANALYZER_AI_ZDR_STATUS must be unverified or verified"
AI_ZDR_CLAIM_UNSUPPORTED = ("ai_zdr_claim_unsupported: a verified ZDR status needs "
                            "ANALYZER_AI_ZDR_VERIFIED_ON (a past date) and ANALYZER_AI_ZDR_EVIDENCE")
AI_REAL_DOCUMENTS_NEED_ZDR = ("ai_real_documents_need_verified_zdr: ANALYZER_AI_SYNTHETIC_ONLY "
                              "may be false only with a verified ZDR record")

_POLICY_ID = re.compile(r"^[A-Z0-9][A-Z0-9._-]{2,63}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def allowlist(raw: str) -> tuple[str, ...]:
    return tuple(m for m in (part.strip() for part in raw.split(",")) if m)


def _zdr_date_ok(value: str, today: date) -> bool:
    if not _DATE.match(value or ""):
        return False
    try:
        return date.fromisoformat(value) <= today
    except ValueError:
        return False


def zdr_verified(settings, today: date | None = None) -> bool:
    """True only for a complete, plausible verification record."""
    today = today or date.today()
    return (settings.analyzer_ai_zdr_status == ZDR_VERIFIED
            and _zdr_date_ok(settings.analyzer_ai_zdr_verified_on, today)
            and bool(settings.analyzer_ai_zdr_evidence.strip()))


def problems(settings=None, today: date | None = None) -> list[str]:
    """Every reason the AI layer's configuration must not run. [] = consistent."""
    if settings is None:
        from app.core.config import settings
    today = today or date.today()
    out: list[str] = []
    if settings.analyzer_ai_provider != PROVIDER_GROQ:
        out.append(AI_PROVIDER_UNSUPPORTED)
    models = allowlist(settings.analyzer_ai_model_allowlist)
    if not models:
        out.append(AI_ALLOWLIST_EMPTY)
    if not settings.analyzer_ai_model.strip():
        out.append(AI_MODEL_NOT_PINNED)
    elif models and settings.analyzer_ai_model not in models:
        out.append(AI_MODEL_NOT_ALLOWLISTED)
    if not settings.groq_api_key.strip():
        out.append(AI_KEY_MISSING)
    if not _POLICY_ID.match(settings.analyzer_ai_policy_id or ""):
        out.append(AI_POLICY_ID_MISSING)
    status = settings.analyzer_ai_zdr_status
    if status not in (ZDR_UNVERIFIED, ZDR_VERIFIED):
        out.append(AI_ZDR_STATUS_INVALID)
    elif status == ZDR_VERIFIED and not zdr_verified(settings, today):
        out.append(AI_ZDR_CLAIM_UNSUPPORTED)
    if not settings.analyzer_ai_synthetic_only and not zdr_verified(settings, today):
        out.append(AI_REAL_DOCUMENTS_NEED_ZDR)
    return out


def contract(settings=None, today: date | None = None) -> dict:
    """What every AI output records about how it was produced. Call only when
    problems() is empty; ZDR is stated as verified only when it was."""
    if settings is None:
        from app.core.config import settings
    verified = zdr_verified(settings, today)
    return {"provider": settings.analyzer_ai_provider, "model": settings.analyzer_ai_model,
            "fallback": None, "policy_id": settings.analyzer_ai_policy_id,
            "zdr": {"status": ZDR_VERIFIED if verified else ZDR_UNVERIFIED,
                    "verified_on": settings.analyzer_ai_zdr_verified_on if verified else None},
            "synthetic_only": bool(settings.analyzer_ai_synthetic_only)}
