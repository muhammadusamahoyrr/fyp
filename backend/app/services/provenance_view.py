"""The lawyer-facing projection of a provenance record.

WHY THIS IS NOT `return record`
-------------------------------
`GET /provenance/{request_id}` already returns the stored document, and it is
owner-scoped, so nothing here is about hiding a record from the person who
created it. It is about what a UI is allowed to render, and the difference
matters for three reasons:

  * a stored document grows. `build_record` is edited whenever the pipeline
    learns to record something new, and a view built by subtraction ("return
    everything except these keys") silently publishes each new field the day it
    is added. This projection is a WHITELIST for the same reason
    `_CASE_CONTEXT_FIELDS` is one: a field reaches a screen only when someone
    decided it should.
  * a Mongo document is not JSON. `_id` is an ObjectId and `created_at` is a
    datetime; both need converting, and doing it here means the route cannot
    forget.
  * the record's field names are pipeline vocabulary. `arbitration_output`,
    `signal_variance` and `bm25_confidence` are meaningful to this codebase and
    to nobody else, so the view labels them.

WHAT IS DELIBERATELY EXCLUDED
-----------------------------
  prompts        No system prompt, template or rendered prompt is stored by
                 `build_record` in the first place, and none is reconstructed
                 here. The IRAC instructions in generation_node are product
                 surface, not audit data.
  case facts     `case_context_hash` proves WHICH context a turn used;
                 the facts stay in the case record where authorization applies.
                 The audit store is not a second copy of privileged material.
  secrets        No key, token or connection string is in the record. The view
                 additionally never echoes a raw config value.
  provider error `llm_calls` events are metadata-only by construction —
                 provider_health.record_failure records a fixed vocabulary and
                 explicitly never `str(exc)`, because Groq's 429 body carries an
                 organization id and OpenRouter's 402 carries a user id. This
                 view depends on that and narrows further: an attempt is
                 reported as provider/model/purpose/outcome plus a CLASSIFIED
                 reason, never a status body.

WHY A LAWYER AND NOT A CLIENT
-----------------------------
A client is shown citation status, claim support and repeal warnings — the
findings. This view is the machinery that produced them: which model answered,
which provider failed over, which thresholds and corpus versions were in force.
Shown to a client it would be noise attached to a legal answer; withheld from a
lawyer it makes "how far do I trust this" unanswerable.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

# Provider-failure kinds, mapped to language that says what happened without
# reproducing a provider's response body.
_FAILURE_TEXT = {
    "rate_limit":   "provider rate limit",
    "quota":        "provider quota exhausted",
    "auth":         "provider credentials rejected",
    "not_found":    "model unavailable on this provider",
    "timeout":      "provider timed out",
    "server_error": "provider error",
    "network":      "network failure reaching the provider",
}

# Every LLM-attempt field that may reach a screen. `status_code` is included
# (it is an HTTP integer, not a body) and nothing else is.
_CALL_FIELDS = ("provider", "model", "tier", "purpose", "outcome",
                "latency_ms", "is_fallback", "call_id")

# Fields of `answer_llm` — who wrote the answer. A separate, narrower list than
# _CALL_FIELDS: this one names an author, so it needs identity and nothing else.
_ANSWER_LLM_FIELDS = ("provider", "model", "tier", "purpose", "call_id")


def _plain(value: Any) -> Any:
    """A JSON-safe SCALAR. Mongo hands back ObjectId and datetime.

    A container is dropped rather than stringified. `str({...})` renders every
    key and value it holds, so stringifying is the one way an allowlist can be
    defeated without anyone editing the allowlist: a field that is a string
    today becomes a dict tomorrow, and its contents are printed into the view
    by a helper whose job was type conversion.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return None
    return str(value)


def _answered_by(value: object) -> dict | None:
    """The author of the answer, projected through an allowlist.

    `answer_llm` is built by provider_health and stored verbatim, so returning
    it directly would publish whatever that dict happens to hold — today and
    after the next change to it. This module's whole discipline is that a field
    reaches a screen because someone decided it should, and a nested dict is not
    an exception to that: it is where an exception would hide.
    """
    if not isinstance(value, dict):
        return None
    out = {k: _plain(value[k]) for k in _ANSWER_LLM_FIELDS if k in value}
    return out or None


def _call_view(event: dict) -> dict:
    """One LLM attempt, as metadata. Never a provider response body."""
    out = {k: _plain(event.get(k)) for k in _CALL_FIELDS if k in event}
    if event.get("outcome") == "failure":
        kind = str(event.get("kind") or "")
        out["reason"] = _FAILURE_TEXT.get(kind, "provider call failed")
        # The HTTP status is a number the lawyer can quote in a support ticket.
        # The response body it came from is not carried anywhere near this.
        out["status_code"] = _plain(event.get("status_code"))
    return out


def _evidence_view(record: dict) -> dict:
    """What the answer was built from — identifiers, never chunk text."""
    return {
        "statutes": [
            {
                "statute":  _plain(c.get("statute")),
                "section":  _plain(c.get("section_number")),
                "province": _plain(c.get("province")),
                "chunk_id": _plain(c.get("chunk_id")),
                "source":   _plain(c.get("source_file")),
            }
            for c in (record.get("statute_chunks") or [])
        ],
        "judgments": [
            {
                "citation": _plain(c.get("citation")),
                "title":    _plain(c.get("title")),
                "score":    _plain(c.get("score")),
            }
            for c in (record.get("case_law") or [])
        ],
        # Deterministic engine calls: which tool ran and whether it succeeded.
        # `result` is excluded — it is truncated free text and the citation and
        # claim panels already report what it concluded.
        "tools": [
            {"tool": _plain(c.get("tool")), "ok": bool(c.get("ok"))}
            for c in (record.get("tool_calls") or [])
        ],
        "web_search_used": bool(record.get("web_search_used")),
    }


def build_view(record: dict | None) -> dict | None:
    """The lawyer-facing view of one provenance record, or None.

    Pure. Every value passes through `_plain`, so the result is JSON-safe
    whatever Mongo returned.
    """
    if not record:
        return None

    arbitration = record.get("arbitration") or {}
    signals     = record.get("signals") or {}
    attempts    = record.get("attempts") or {}
    execution   = dict(record.get("execution") or {})
    versions    = record.get("versions") or {}
    grounding   = record.get("citation_grounding") or {}

    return {
        # ── Identity ─────────────────────────────────────────────────────────
        "request_id": _plain(record.get("request_id")),
        "session_id": _plain(record.get("session_id")),
        "created_at": _plain(record.get("created_at")),
        "turn_type":  _plain(record.get("turn_type")),
        # A turn produced under a repaired contract must be readable as such:
        # the answer reached the user, but the pipeline had already caught
        # itself breaking its own invariant getting there.
        "invariant_violation": _plain(record.get("invariant_violation")),

        # ── What was asked, and of which jurisdiction ─────────────────────────
        "question":  _plain(record.get("query")),
        "language":  _plain(record.get("language")),
        "case_type": _plain(record.get("case_type")),
        "province":  _plain(record.get("province")),

        # ── Which case, and whether its context did anything ──────────────────
        # The hash identifies the context; the facts are not duplicated here.
        "case": {
            "case_id":        _plain(record.get("case_id")),
            "context_supplied": bool(record.get("case_context_supplied")),
            "context_hash":   _plain(record.get("case_context_hash")),
            "record_version": _plain(record.get("case_record_version")),
            "used_by":        list(record.get("case_context_used_by") or []),
        },

        # ── Which answer this describes ───────────────────────────────────────
        # The digest lets a lawyer prove the text they are holding is the text
        # this record describes, without the audit storing a second copy.
        "answer": {
            "sha256":  _plain(record.get("answer_sha256")),
            "preview": _plain(record.get("answer_preview")),
        },

        # ── Who actually answered ─────────────────────────────────────────────
        # `answer_llm` is the call that wrote the user-facing text, not the last
        # successful call — the last one is usually the fast grounding judge.
        "model": {
            "answered_by": _answered_by(record.get("answer_llm")),
            "origin":      _plain(record.get("answer_llm_origin")),
            "attempts":    [_call_view(e) for e in (record.get("llm_calls") or [])
                            if isinstance(e, dict)],
        },

        # ── How the evidence was weighed ──────────────────────────────────────
        "decision": {
            "verdict":    _plain(arbitration.get("output")),
            "source":     _plain(arbitration.get("source")),
            "confidence": _plain(arbitration.get("confidence")),
            "grounded":   bool(record.get("is_grounded")),
            "cache_hit":  bool(record.get("cache_hit")),
            "convergence": _plain(record.get("convergence_status")),
        },
        "signals": {
            "relevance":       _plain(signals.get("relevance_score")),
            "bm25":            _plain(signals.get("bm25_confidence")),
            "variance":        _plain(signals.get("signal_variance")),
            "self_reported":   _plain(signals.get("confidence")),
        },
        # How much of what the answer cited was in the evidence it was given.
        # A measurement, never an error rate: CrPC s.154 is exactly the FIR
        # provision, and an answer citing it from parametric memory is correct
        # while being ungrounded. `measurable: false` means the answer carried
        # no parseable citation — nothing to ground, which is not a finding of
        # groundedness either way.
        "citation_grounding": {
            "measurable":     bool(grounding.get("measurable")),
            "grounded_ratio": _plain(grounding.get("grounded_ratio")),
            "cited_count":    len(grounding.get("cited") or []),
            "grounded_count": len(grounding.get("grounded") or []),
            # Named, because "which of my citations could you not place" is the
            # question a lawyer actually has.
            "ungrounded":     [_plain(x) for x in (grounding.get("ungrounded") or [])],
            "reason":         _plain(grounding.get("reason")),
        },
        "attempts": {
            "retrieval":           _plain(attempts.get("retrieval")),
            "generation":          _plain(attempts.get("generation")),
            "clarification_depth": _plain(attempts.get("clarification_depth")),
        },

        # ── Timing ────────────────────────────────────────────────────────────
        # `errors` is a list of "kind:name" span labels — which node or tool
        # failed, never what a provider said about it.
        "execution": {
            "total_ms":   _plain(execution.get("total_ms")),
            "llm_ms":     _plain(execution.get("llm_ms")),
            "llm_calls":  _plain(execution.get("llm_calls")),
            "tool_calls": [_plain(x) for x in (execution.get("tool_calls") or [])],
            "models":     [_plain(x) for x in (execution.get("models") or [])],
            "errors":     [_plain(x) for x in (execution.get("errors") or [])],
        },

        # ── Reproducibility ───────────────────────────────────────────────────
        # Without these a re-run months later uses a different embedding model
        # or chunking strategy and cannot reproduce the evidence above.
        "versions": {
            "schema":          _plain(record.get("schema_version")),
            "embedding_model": _plain(versions.get("embedding_model")),
            "chunking":        _plain(versions.get("chunking")),
        },

        "evidence": _evidence_view(record),
    }
