"""Provider eligibility, per-turn LLM attribution, and call telemetry.

Two problems, two mechanisms.

1. Eligibility is scoped, not global
-----------------------------------
Groq meters tokens per DAY *per model*. The graph spends that budget almost
entirely on the fast tier — query expansion, the retrieval grader and the
grounding judge all call get_fast_llm — so openai/gpt-oss-20b exhausted at
199,507/200,000 while openai/gpt-oss-120b on the same key still had headroom.
A provider-wide circuit would have disabled a healthy model to punish a
sibling's rate limit.

So failures are scoped by what they actually prove:

    rate_limit (429)        -> this account + this model
    model_unavailable (404) -> this account + this model
    auth (401/403)          -> the whole account (the key is bad, not the model)
    payment (402)           -> the whole account (the balance is empty)
    transient (5xx/conn)    -> nothing; fail over, retry next call

Accounts are independent: `groq` and `groq2` are separate keys with separate
budgets, so one going dark says nothing about the other.

2. Attribution is per-turn and explicitly scoped
------------------------------------------------
The previous design stored a single "last used" value in a ContextVar, set from
a callback. That was wrong three ways, and each way produced a plausible-looking
but false provenance record:

  * Callbacks frequently run inside asyncio.to_thread. That copies the context,
    so a ContextVar SET in the worker thread never reaches the parent — the
    value silently stayed empty for exactly the calls that matter.
  * "Last successful call" is normally the fast grounding judge, not the main
    model that wrote the answer. The record would name the wrong model.
  * A WebSocket connection serves many turns in one coroutine. Nothing reset the
    value, so a cache hit or a canned reply inherited the previous turn's model
    identity — attribution for an LLM call that never happened.

The fix is a MUTABLE collector held in a ContextVar. Context copying shares the
object reference, so a mutation made in a worker thread is visible to the parent;
each turn gets its own instance, so consecutive and concurrent turns cannot see
each other; and every append is under a lock, so thread-safety does not depend on
the GIL.

Never recorded anywhere in this module: prompts, completions, API keys,
organization ids, provider user ids, or raw exception bodies. Groq's 429 text
embeds an organization id and OpenRouter's 402 embeds a user id, so error text is
reduced to a fixed classification vocabulary before it is stored or logged.
"""
from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

# ── cooldown policy ──────────────────────────────────────────────────────────
# Every cooldown is bounded. Daily budgets roll over and balances get topped up;
# a permanent skip would need a restart to undo, which turns a transient outage
# into a mystery outage.
MAX_COOLDOWN_S = 900.0
DEFAULT_RATE_LIMIT_COOLDOWN_S = 60.0
PAYMENT_COOLDOWN_S = 900.0
CONFIG_COOLDOWN_S = 900.0

KIND_RATE_LIMIT = "rate_limit"
KIND_PAYMENT = "payment_required"
KIND_AUTH = "auth"
KIND_MODEL_UNAVAILABLE = "model_unavailable"
KIND_TRANSIENT = "transient"
KIND_OTHER = "other"

SCOPE_MODEL = "model"        # this account + this model only
SCOPE_ACCOUNT = "account"    # every model on this account
SCOPE_NONE = "none"          # fail over, but stay eligible

# What each failure actually proves about future calls.
_SCOPE_OF: dict[str, str] = {
    KIND_RATE_LIMIT:        SCOPE_MODEL,
    KIND_MODEL_UNAVAILABLE: SCOPE_MODEL,
    KIND_AUTH:              SCOPE_ACCOUNT,
    KIND_PAYMENT:           SCOPE_ACCOUNT,
    KIND_TRANSIENT:         SCOPE_NONE,
    KIND_OTHER:             SCOPE_NONE,
}

_FIXED_COOLDOWN: dict[str, Optional[float]] = {
    KIND_RATE_LIMIT:        None,               # provider states the duration
    KIND_MODEL_UNAVAILABLE: CONFIG_COOLDOWN_S,
    KIND_AUTH:              CONFIG_COOLDOWN_S,
    KIND_PAYMENT:           PAYMENT_COOLDOWN_S,
}

# ── call purposes ────────────────────────────────────────────────────────────
# Explicit, never inferred from tier or call order. "Which model wrote the
# answer" is not "which model was called last" — the last call in a turn is
# almost always the fast grounding judge.
PURPOSE_GATEKEEPER = "gatekeeper"
PURPOSE_INTENT = "intent_classification"
PURPOSE_TRIAGE = "triage"
PURPOSE_FACT_GAP = "fact_gap"
PURPOSE_QUERY_EXPANSION = "query_expansion"
PURPOSE_RETRIEVAL_GRADER = "retrieval_grader"
PURPOSE_ANSWER_GENERATION = "answer_generation"
PURPOSE_GROUNDING_JUDGE = "grounding_judge"
PURPOSE_ANSWER_REFORMAT = "answer_reformat"
PURPOSE_TOOL_SELECTION = "tool_selection"
# Beyond the chat graph: the drafting, intake and dispute subsystems also call
# the factories, and an untagged call is indistinguishable from an unattributed
# one in the audit. Named after what the call is FOR, never after its tier.
PURPOSE_CLARIFICATION = "clarification"
PURPOSE_INTAKE_EXTRACTION = "intake_extraction"
PURPOSE_INTAKE_GROUNDING = "intake_grounding"
PURPOSE_DISPUTE_CLASSIFICATION = "dispute_classification"
PURPOSE_DOCUMENT_DRAFTING = "document_drafting"
PURPOSE_PETITION_DRAFTING = "petition_drafting"
PURPOSE_DIRECT_CHAT = "direct_chat"
PURPOSE_DRAFT_STREAM = "draft_stream"
PURPOSE_PLEADING_URDU = "pleading_urdu"
PURPOSE_MODEL_COMPARE = "model_compare"
PURPOSE_UNKNOWN = "unknown"

ALL_PURPOSES = frozenset({
    PURPOSE_GATEKEEPER, PURPOSE_INTENT, PURPOSE_TRIAGE, PURPOSE_FACT_GAP,
    PURPOSE_QUERY_EXPANSION, PURPOSE_RETRIEVAL_GRADER, PURPOSE_ANSWER_GENERATION,
    PURPOSE_GROUNDING_JUDGE, PURPOSE_ANSWER_REFORMAT, PURPOSE_TOOL_SELECTION,
    PURPOSE_CLARIFICATION, PURPOSE_INTAKE_EXTRACTION, PURPOSE_INTAKE_GROUNDING,
    PURPOSE_DISPUTE_CLASSIFICATION, PURPOSE_DOCUMENT_DRAFTING,
    PURPOSE_PETITION_DRAFTING, PURPOSE_DIRECT_CHAT, PURPOSE_DRAFT_STREAM,
    PURPOSE_PLEADING_URDU, PURPOSE_MODEL_COMPARE,
    PURPOSE_UNKNOWN,
})

# Purposes whose successful call can be the answer's author, most specific first.
# A reformat rewrites a previous answer and IS the text the user sees, so it wins
# when present; otherwise the generation call is the author.
_AUTHOR_PURPOSES = (PURPOSE_ANSWER_REFORMAT, PURPOSE_ANSWER_GENERATION)

ORIGIN_CURRENT_TURN = "current_turn"
ORIGIN_CACHED = "cached_source"
ORIGIN_NONE = "none"

_RETRY_PHRASE = re.compile(
    r"try again in\s+(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.IGNORECASE)


# ── health state ─────────────────────────────────────────────────────────────

@dataclass
class _Entry:
    cooldown_until: float = 0.0
    reason: str = ""
    kind: str = ""
    status_code: Optional[int] = None
    consecutive_failures: int = 0
    last_success: float = 0.0


_lock = threading.Lock()
_account: dict[str, _Entry] = {}
_model: dict[tuple[str, str], _Entry] = {}


def reset() -> None:
    """Clear all health state. Tests, and an explicit operator reset."""
    with _lock:
        _account.clear()
        _model.clear()


def _entry(store: dict, key) -> _Entry:
    e = store.get(key)
    if e is None:
        e = _Entry()
        store[key] = e
    return e


# ── classification ───────────────────────────────────────────────────────────

def _status_of(exc: BaseException) -> Optional[int]:
    for attr in ("status_code", "http_status", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(exc, "response", None)
    v = getattr(resp, "status_code", None)
    return v if isinstance(v, int) else None


def _parse_duration(text: str) -> Optional[float]:
    text = text.strip()
    if re.fullmatch(r"[\d.]+", text):
        try:
            return float(text)
        except ValueError:
            return None
    m = re.fullmatch(r"([\d.]+)ms", text, re.IGNORECASE)
    if m:
        return float(m.group(1)) / 1000.0
    m = _RETRY_PHRASE.search(text)
    if not m or not any(m.groups()):
        m2 = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", text, re.IGNORECASE)
        if not m2 or not any(m2.groups()):
            return None
        m = m2
    h, mn, sec = m.groups()
    return (int(h or 0) * 3600) + (int(mn or 0) * 60) + float(sec or 0)


def _retry_after_from(exc: BaseException) -> Optional[float]:
    """Seconds to wait. Header first; the message is read ONLY for a duration."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) or getattr(exc, "headers", None)
    if headers:
        for key in ("retry-after", "Retry-After",
                    "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
            try:
                raw = headers.get(key)
            except Exception:
                raw = None
            if raw:
                parsed = _parse_duration(str(raw))
                if parsed is not None:
                    return parsed
    return _parse_duration(str(exc))


def classify(exc: BaseException) -> tuple[str, Optional[int]]:
    """(kind, status). Reads status and type name only — never the body."""
    status = _status_of(exc)
    name = type(exc).__name__
    if status == 429 or name == "RateLimitError":
        return KIND_RATE_LIMIT, status or 429
    if status == 402:
        return KIND_PAYMENT, 402
    if status in (401, 403) or name == "AuthenticationError":
        return KIND_AUTH, status or 401
    if status == 404 or name == "NotFoundError":
        return KIND_MODEL_UNAVAILABLE, status or 404
    if status is not None and 500 <= status < 600:
        return KIND_TRANSIENT, status
    if name in ("APIConnectionError", "APITimeoutError", "InternalServerError",
                "ServiceUnavailable", "DeadlineExceeded"):
        return KIND_TRANSIENT, status
    return KIND_OTHER, status


# ── eligibility ──────────────────────────────────────────────────────────────

def is_eligible(provider: str, model: Optional[str] = None,
                now: Optional[float] = None) -> bool:
    """Is `provider` usable for `model` right now?

    Account-level cooldown disables every model; model-level disables one. A
    configured key is never on its own proof of usability — that assumption is
    what let an exhausted account be re-tried on every node of every turn.
    """
    now = time.time() if now is None else now
    with _lock:
        acct = _account.get(provider)
        if acct is not None and now < acct.cooldown_until:
            return False
        if model is None:
            return True
        mod = _model.get((provider, model))
        return mod is None or now >= mod.cooldown_until


def cooldown_remaining(provider: str, model: Optional[str] = None,
                       now: Optional[float] = None) -> float:
    now = time.time() if now is None else now
    with _lock:
        best = 0.0
        acct = _account.get(provider)
        if acct:
            best = max(best, acct.cooldown_until - now)
        if model is not None:
            mod = _model.get((provider, model))
            if mod:
                best = max(best, mod.cooldown_until - now)
        return max(0.0, best)


def cooldown_reason(provider: str, model: Optional[str] = None) -> str:
    now = time.time()
    with _lock:
        acct = _account.get(provider)
        if acct and now < acct.cooldown_until:
            return acct.reason
        if model is not None:
            mod = _model.get((provider, model))
            if mod and now < mod.cooldown_until:
                return mod.reason
    return ""


def snapshot() -> dict[str, Any]:
    """Diagnostics. No keys, no bodies, no ids."""
    now = time.time()
    with _lock:
        return {
            "accounts": {
                p: {"eligible": now >= e.cooldown_until,
                    "cooldown_remaining_s": round(max(0.0, e.cooldown_until - now), 1),
                    "kind": e.kind, "status_code": e.status_code, "reason": e.reason,
                    "consecutive_failures": e.consecutive_failures}
                for p, e in _account.items()},
            "models": {
                f"{p}/{m}": {"eligible": now >= e.cooldown_until,
                             "cooldown_remaining_s": round(max(0.0, e.cooldown_until - now), 1),
                             "kind": e.kind, "status_code": e.status_code,
                             "reason": e.reason,
                             "consecutive_failures": e.consecutive_failures}
                for (p, m), e in _model.items()},
        }


# ── per-turn usage collector ─────────────────────────────────────────────────

@dataclass
class TurnUsage:
    """Every LLM attempt made during ONE turn.

    Mutable on purpose. asyncio.to_thread copies the context, which shares this
    object rather than copying it, so an append made on a worker thread is
    visible to the parent request. A scalar ContextVar set inside the thread is
    invisible to the parent — that is the bug this replaces.
    """
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    events: list[dict] = field(default_factory=list)
    _guard: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, event: dict) -> None:
        with self._guard:
            self.events.append(event)

    def all_events(self) -> list[dict]:
        with self._guard:
            return list(self.events)

    def successes(self, purpose: str) -> list[dict]:
        with self._guard:
            return [e for e in self.events
                    if e.get("purpose") == purpose and e.get("outcome") == "success"]

    def answer_llm(self) -> Optional[dict]:
        """The call that produced the user-facing answer.

        A reformat rewrites a prior answer and IS what the user reads, so it
        outranks generation. Within a purpose the LAST success wins, so a
        generation retry names the attempt that actually succeeded. Judge and
        retrieval calls can never be the author, however recently they ran.
        """
        for purpose in _AUTHOR_PURPOSES:
            hits = self.successes(purpose)
            if hits:
                return _public(hits[-1])
        return None


_TURN: contextvars.ContextVar[Optional[TurnUsage]] = contextvars.ContextVar(
    "llm_turn_usage", default=None)


def current_turn() -> Optional[TurnUsage]:
    return _TURN.get()


@contextmanager
def turn_scope(turn_id: Optional[str] = None) -> Iterator[TurnUsage]:
    """Scope one turn's attribution. Reset in `finally`, always.

    Must wrap the whole turn — opened before the first LLM call and closed only
    after provenance has been written. Without the reset, consecutive turns on
    one WebSocket coroutine inherit the previous turn's model identity, which is
    how a cache hit came to be attributed to an LLM call that never happened.
    """
    usage = TurnUsage(turn_id=turn_id or uuid.uuid4().hex[:12])
    token = _TURN.set(usage)
    try:
        yield usage
    finally:
        _TURN.reset(token)


def _public(event: dict) -> dict:
    """Attribution view of an event — metadata only."""
    return {k: event[k] for k in ("provider", "model", "tier", "purpose",
                                  "latency_ms", "call_id")
            if k in event}


# ── recording ────────────────────────────────────────────────────────────────

def _emit(event: dict) -> None:
    """One structured telemetry line. Metadata only, by construction."""
    logger.info(
        "llm_call provider=%s model=%s tier=%s purpose=%s outcome=%s "
        "latency_ms=%.0f status=%s kind=%s fallback=%s call_id=%s cooldown_s=%.0f "
        "scope=%s",
        event["provider"], event["model"], event["tier"], event["purpose"],
        event["outcome"], event["latency_ms"],
        event["status_code"] if event["status_code"] is not None else "-",
        event["kind"] or "-", event["is_fallback"], event["call_id"],
        event["cooldown_s"], event["scope"],
    )


def _base_event(provider, model, tier, purpose, outcome, latency_ms,
                is_fallback, call_id) -> dict:
    return {
        "provider": provider, "model": model, "tier": tier,
        "purpose": purpose if purpose in ALL_PURPOSES else PURPOSE_UNKNOWN,
        "outcome": outcome, "latency_ms": round(float(latency_ms), 1),
        "status_code": None, "kind": "", "cooldown_s": 0.0,
        "scope": SCOPE_NONE, "is_fallback": bool(is_fallback),
        "call_id": call_id or uuid.uuid4().hex[:12],
    }


def record_success(provider: str, model: str, tier: str, latency_ms: float,
                   purpose: str = PURPOSE_UNKNOWN, is_fallback: bool = False,
                   call_id: Optional[str] = None) -> dict:
    """Clear cooldowns for this account+model and append the event."""
    with _lock:
        for store, key in ((_account, provider), (_model, (provider, model))):
            e = _entry(store, key)
            e.cooldown_until = 0.0
            e.consecutive_failures = 0
            e.reason = ""
            e.kind = ""
            e.status_code = None
            e.last_success = time.time()

    ev = _base_event(provider, model, tier, purpose, "success", latency_ms,
                     is_fallback, call_id)
    turn = _TURN.get()
    if turn is not None:
        turn.record(ev)
    _emit(ev)
    return ev


def record_failure(provider: str, model: str, tier: str, exc: BaseException,
                   latency_ms: float = 0.0, purpose: str = PURPOSE_UNKNOWN,
                   is_fallback: bool = False, call_id: Optional[str] = None,
                   now: Optional[float] = None) -> dict:
    """Classify, apply a scoped cooldown, append the event."""
    now = time.time() if now is None else now
    kind, status = classify(exc)
    scope = _SCOPE_OF.get(kind, SCOPE_NONE)

    cooldown = 0.0
    if scope != SCOPE_NONE:
        fixed = _FIXED_COOLDOWN.get(kind)
        cooldown = (_retry_after_from(exc) or DEFAULT_RATE_LIMIT_COOLDOWN_S) \
            if fixed is None else fixed
        cooldown = max(0.0, min(cooldown, MAX_COOLDOWN_S))

    # A fixed vocabulary, never str(exc): Groq's 429 body carries an
    # organization id and OpenRouter's 402 carries a user id.
    reason = f"{kind} ({status})" if status else kind

    if cooldown > 0:
        with _lock:
            store, key = ((_account, provider) if scope == SCOPE_ACCOUNT
                          else (_model, (provider, model)))
            e = _entry(store, key)
            e.consecutive_failures += 1
            e.kind, e.status_code, e.reason = kind, status, reason
            e.cooldown_until = max(e.cooldown_until, now + cooldown)
    else:
        with _lock:
            e = _entry(_model, (provider, model))
            e.consecutive_failures += 1
            e.kind, e.status_code, e.reason = kind, status, reason

    ev = _base_event(provider, model, tier, purpose, "failure", latency_ms,
                     is_fallback, call_id)
    ev.update({"status_code": status, "kind": kind,
               "cooldown_s": round(cooldown, 1), "scope": scope})
    turn = _TURN.get()
    if turn is not None:
        turn.record(ev)
    _emit(ev)
    return ev
