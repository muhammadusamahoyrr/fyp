"""Durable, answer-linked provenance records.

Why this exists
---------------
`tracing.py` already records what the agent *did* — nodes, LLM calls with
provider attribution, tool calls, timings. But those spans live in memory for the
duration of one request and are then discarded. Once an answer was stored in the
chat history, nothing connected it to the evidence and decisions that produced
it: which statute chunks were retrieved, which deterministic engine ran, what the
Decision Engine's verdict was, or which model actually served the text.

For a legal assistant that is the difference between "the system logged
something" and "this specific answer can be audited". A user challenging advice
six months later needs the record for *their* answer, not a log line.

What is stored
--------------
Evidence (statute chunk ids, case-law citations, engine calls), the arbitration
verdict and its inputs, convergence counters, an execution rollup, and the
version tags needed to reproduce the retrieval. The answer itself is NOT
duplicated in full — it already lives in the chat history — only a SHA-256 digest
and a short preview, so a record can prove *which* answer it describes without
becoming a second copy of the user's legal correspondence.

Privacy
-------
Query and preview are PII-scrubbed with the same helper the user-facing answer
uses. Tool arguments are stored as key names with truncated values, since intake
engines take names, amounts and dates.

Failure policy
--------------
Never raises. An audit write that failed the user's legal query would be a worse
outcome than a missing audit row; failures are logged loudly instead.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from app.ai.cache import CHUNKING_STRATEGY_VERSION, EMBEDDING_MODEL_VERSION
from app.db.collections import get_answer_provenance_col
from app.utils.pii import scrub_pii

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "prov-v2"   # v2 adds is_synthetic

# ── Synthetic traffic ─────────────────────────────────────────────────────────
#
# Threshold warmup counts QUERIES and needs ~1000 of them; the labelling pool is
# built from the SAME records. So traffic generated to warm the threshold lands
# in the pool an annotator later draws from, and unmarked, a load generator's
# questions become "evaluation questions" indistinguishable from a user's.
#
# That is the exact threat the paper already concedes — evaluation questions
# that are developer-authored or LLM-generated — so it must be recorded at write
# time, not guessed at afterwards. A record cannot be reclassified later: once
# real and synthetic turns are mixed with nothing to tell them apart, the whole
# pool inherits the doubt.
#
# Read from the environment rather than threaded through the graph. NOTE the
# environment that counts is the one belonging to the process that WRITES the
# record — the API server — not the client driving the queries. Setting it on a
# seeding script does nothing, because the script only sends WebSocket frames;
# the server builds the record. Run a warmup session as a dedicated server:
#
#   GROQ_API_KEY="" PROVENANCE_SYNTHETIC=1 ./venv/Scripts/uvicorn.exe app.main:app ...
#
# Everything that server records is then marked, which is the intent: a warmup
# session is not serving real users. The default for anything that does not
# think about it is FALSE (treated as real), because the opposite default would
# silently discard genuine traffic. state["is_synthetic"] overrides, for a
# driver that runs mixed traffic in one process.
SYNTHETIC_ENV_VAR = "PROVENANCE_SYNTHETIC"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_synthetic_env() -> bool:
    return os.getenv(SYNTHETIC_ENV_VAR, "").strip().lower() in _TRUTHY


def _is_synthetic(state: dict) -> bool:
    if "is_synthetic" in state:
        return bool(state.get("is_synthetic"))
    return is_synthetic_env()

# What kind of turn a record describes. All three are audited; only "answer"
# turns are offered for answer-correctness labeling, because asking a human
# "was this answer right?" about a clarifying QUESTION is meaningless.
TURN_ANSWER        = "answer"        # the system produced (or refused) an answer
TURN_CLARIFICATION = "clarification" # the system asked the user for more facts
TURN_BLOCKED       = "blocked"       # the gatekeeper stopped the message
TURN_SHORTCUT      = "shortcut"      # answered by intent shortcut, graph not run
TURN_ERROR         = "error"         # the turn failed and the user saw a fault

# Every turn type a user-visible output can carry. The socket layer asserts the
# turn type it is about to write is in this set, so adding an output path
# without deciding how it is audited fails loudly rather than silently leaving
# a hole in the trail.
TURN_TYPES = frozenset({
    TURN_ANSWER, TURN_CLARIFICATION, TURN_BLOCKED, TURN_SHORTCUT, TURN_ERROR,
})

_QUERY_MAX   = 1000
_PREVIEW_MAX = 500
_ARG_MAX     = 120
_RESULT_MAX  = 300
_MAX_CHUNKS  = 20
_MAX_TOOLS   = 10


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _truncate(value: Any, limit: int) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _statute_evidence(state: dict) -> list[dict]:
    """Identify retrieved statute chunks by id — enough to re-fetch and verify."""
    out: list[dict] = []
    for chunk in (state.get("reranked_chunks") or [])[:_MAX_CHUNKS]:
        if chunk.get("law_type") == "judgment":
            continue   # case law is recorded separately
        out.append({
            "chunk_id":       chunk.get("chunk_id", ""),
            "statute":        chunk.get("statute", ""),
            "section_number": chunk.get("section_number", ""),
            "source_file":    chunk.get("source_file", ""),
            "province":       chunk.get("province", ""),
            "law_type":       chunk.get("law_type", ""),
        })
    return out


def _case_law_evidence(state: dict) -> list[dict]:
    return [
        {
            "judgment_id": c.get("judgment_id", ""),
            "citation":    c.get("citation", ""),
            "title":       _truncate(c.get("title", ""), _ARG_MAX),
            "score":       round(float(c.get("score", 0.0)), 4),
        }
        for c in (state.get("case_law_chunks") or [])[:_MAX_CHUNKS]
    ]


def _tool_evidence(state: dict) -> list[dict]:
    """
    Deterministic engine calls. These are the *computed* evidence the grounding
    verifier treats as ground truth, so an audit that omitted them could not
    explain why an answer was accepted as grounded.
    """
    out: list[dict] = []
    for call in (state.get("tool_results") or [])[:_MAX_TOOLS]:
        result = call.get("result")
        ok = True
        if isinstance(result, dict):
            ok = not result.get("error")
        elif isinstance(result, list):
            ok = any(isinstance(r, dict) and not r.get("error") for r in result)

        out.append({
            "tool": call.get("tool", ""),
            "args": {
                k: _truncate(v, _ARG_MAX)
                for k, v in (call.get("args") or {}).items()
            },
            "ok":     ok,
            "result": _truncate(result, _RESULT_MAX),
        })
    return out


def _execution_rollup(trace_summary: Optional[dict], spans: Optional[list]) -> dict:
    """Timing/provider rollup. `models` answers 'which provider actually served this'."""
    rollup = dict(trace_summary or {})
    rollup.pop("session_id", None)   # already a top-level field
    rollup.pop("request_id", None)

    models = sorted({
        s.get("name", "")
        for s in (spans or [])
        if s.get("kind") == "llm" and s.get("name")
    })
    if models:
        rollup["models"] = models
    return rollup


def build_record(
    state:         dict,
    session_id:    str,
    user_id:       str,
    request_id:    str,
    trace_summary: Optional[dict] = None,
    spans:         Optional[list] = None,
    turn_type:     str            = TURN_ANSWER,
) -> dict:
    """Assemble the provenance document for one turn. Pure — no I/O.

    For a clarification turn the caller passes the question it asked as
    state["answer"]: the record describes what the system EMITTED, and a
    clarifying question is as much an output as an answer is.
    """
    answer = state.get("answer") or ""

    return {
        "schema_version": SCHEMA_VERSION,
        "turn_type":      turn_type,
        # Whether a real person asked this. Recorded at write time because it
        # cannot be recovered later; see SYNTHETIC_ENV_VAR above.
        "is_synthetic":   _is_synthetic(state),
        "request_id":     request_id,
        "session_id":     session_id,
        "user_id":        user_id,
        "created_at":     datetime.now(timezone.utc),

        # ── What was asked ────────────────────────────────────────────────────
        "query":            scrub_pii(_truncate(state.get("query", ""), _QUERY_MAX)),
        "normalized_query": scrub_pii(
            _truncate(state.get("normalized_query", ""), _QUERY_MAX)
        ),
        "language":  state.get("language", ""),
        "case_type": state.get("case_type", ""),
        "province":  state.get("province", ""),

        # ── Which answer this record describes ────────────────────────────────
        # Digest of the FULL answer, preview scrubbed and truncated. The digest
        # detects tampering or divergence without duplicating the text.
        "answer_sha256":  _sha256(answer),
        "answer_preview": scrub_pii(_truncate(answer, _PREVIEW_MAX)),

        # ── Evidence ──────────────────────────────────────────────────────────
        "statute_chunks": _statute_evidence(state),
        "case_law":       _case_law_evidence(state),
        "tool_calls":     _tool_evidence(state),
        "web_search_used": bool(state.get("web_search_enabled")),

        # ── Decisions ─────────────────────────────────────────────────────────
        "arbitration": {
            "output":     state.get("arbitration_output", ""),
            "source":     state.get("arbitration_source", ""),
            "confidence": state.get("arbitration_confidence", 0.0),
        },
        "signals": {
            "relevance_score": state.get("relevance_score", 0.0),
            "signal_variance": state.get("signal_variance", 0.0),
            "bm25_confidence": state.get("bm25_confidence", 0.0),
            "confidence":      state.get("confidence", 0.0),
        },
        "is_grounded":        bool(state.get("is_grounded")),
        "cache_hit":          bool(state.get("cache_hit")),
        "convergence_status": state.get("convergence_status", ""),
        "attempts": {
            "retrieval":          state.get("retrieval_attempts", 0),
            "generation":         state.get("generation_attempts", 0),
            "clarification_depth": state.get("clarification_depth", 0),
        },

        # ── Execution ─────────────────────────────────────────────────────────
        "execution": _execution_rollup(trace_summary, spans),

        # ── Reproducibility ───────────────────────────────────────────────────
        # Without these, a re-run months later silently uses a different
        # embedding model or chunking strategy and cannot reproduce the evidence.
        "versions": {
            "embedding_model": EMBEDDING_MODEL_VERSION,
            "chunking":        CHUNKING_STRATEGY_VERSION,
        },
    }


async def record_answer(
    state:         dict,
    session_id:    str,
    user_id:       str,
    request_id:    str,
    trace_summary: Optional[dict] = None,
    spans:         Optional[list] = None,
    turn_type:     str            = TURN_ANSWER,
) -> Optional[str]:
    """
    Persist a provenance record. Returns the request_id on success, else None.

    Never raises — an audit write must not fail the query it describes.
    """
    try:
        record = build_record(
            state, session_id, user_id, request_id, trace_summary, spans, turn_type
        )
        await get_answer_provenance_col().insert_one(record)
        return request_id
    except Exception:
        logger.exception(
            "provenance: failed to record answer (session=%s request=%s)",
            session_id, request_id,
        )
        return None


async def get_by_request(request_id: str, user_id: str) -> Optional[dict]:
    """
    Fetch one record, scoped to its owner.

    user_id is a REQUIRED filter, not a post-hoc check: an audit trail that let
    one user read another's provenance would leak the legal questions they asked.
    """
    return await get_answer_provenance_col().find_one(
        {"request_id": request_id, "user_id": user_id}, {"_id": 0}
    )


async def list_for_session(session_id: str, user_id: str, limit: int = 50) -> list[dict]:
    """Records for one chat session, newest first. Owner-scoped for the same reason."""
    cursor = (
        get_answer_provenance_col()
        .find({"session_id": session_id, "user_id": user_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(max(1, min(limit, 200)))
    )
    return await cursor.to_list(length=None)
