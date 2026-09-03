"""Server-side case context: identity, hearings, and the retrieval supplement.

Everything here operates on a case record the caller has ALREADY been authorised
to see. Nothing in this module performs authorization, and nothing accepts case
facts from a client — that is the whole point of the module existing: case facts
used to arrive as free text the browser placed in `history`, so the client
decided what the model believed about a matter it might not have access to.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Optional

# Thread identity ------------------------------------------------------------
# Bounded so an identifier can never grow with user input, and hashed so no
# separator can be smuggled through. Concatenation was the previous scheme and
# is ambiguous: "research:{user}:{session}:case:{case}" collides whenever a
# session_id itself contains ":case:", which a client controls entirely.
_THREAD_PREFIX = "research"
_THREAD_DIGEST_LEN = 32          # 128 bits of a sha256 — collision-safe here
MAX_THREAD_ID_LEN = len(_THREAD_PREFIX) + 1 + _THREAD_DIGEST_LEN


def thread_id(user_id: str, session_id: str, case_id: Optional[str]) -> str:
    """A collision-safe conversation identity for (user, session, case).

    The tuple is serialised canonically — JSON with a fixed separator set and no
    ambiguity between fields — then hashed. Two different tuples cannot produce
    one id, and a client-supplied session_id cannot impersonate another case by
    embedding delimiters in itself.

    Length is fixed regardless of input, so a very long session_id cannot
    produce an unbounded key in the checkpoint store.
    """
    canonical = json.dumps(
        [str(user_id or ""), str(session_id or ""), str(case_id or "")],
        separators=(",", ":"), ensure_ascii=True, sort_keys=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_THREAD_DIGEST_LEN]
    return f"{_THREAD_PREFIX}:{digest}"


# Hearings -------------------------------------------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y")


def _parse_date(value: Any) -> Optional[date]:
    """A calendar date from a hearing entry, or None. Never raises.

    Hearing rows are user-entered and arrive as strings, datetimes, or rubbish.
    A malformed entry must be skipped, not crash the turn and not silently
    become "today".
    """
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # ISO first, including trailing Z and offsets.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).date() if parsed.tzinfo else parsed.date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def next_hearing(hearings: Any, today: Optional[date] = None) -> Optional[str]:
    """The earliest UPCOMING hearing that has not already happened.

    Three things the naive `sorted(dates)[0]` got wrong:
      * it returned the earliest hearing in the record, which for an ongoing
        matter is a date in the past — presented to the model as "next hearing";
      * it ignored `outcome`, so a hearing that had already been heard and
        recorded still counted as upcoming;
      * it assumed every entry parsed, so one malformed row raised inside a
        request that was otherwise fine.

    "Today" is evaluated in UTC. A hearing dated today is still upcoming.
    """
    today = today or datetime.now(timezone.utc).date()
    upcoming: list[date] = []
    for row in hearings or []:
        if not isinstance(row, dict):
            continue
        # A recorded outcome means the hearing happened, whatever its date says.
        if row.get("outcome"):
            continue
        parsed = _parse_date(row.get("date"))
        if parsed is None or parsed < today:
            continue
        upcoming.append(parsed)
    return min(upcoming).isoformat() if upcoming else None


# Retrieval supplement -------------------------------------------------------

_STOPWORDS = frozenset("""
a an and are as at be by for from has have in is it its of on or that the to
was were will with what should i my me we our you your how do does can
""".split())

# Bounded hard: this text is appended to a retrieval query, and an unbounded
# supplement would swamp the user's actual words in BM25 scoring.
_MAX_SUPPLEMENT_TERMS = 24
_MAX_SUPPLEMENT_CHARS = 320

# A question that carries almost no retrievable subject of its own. These are
# exactly the prompts the case-workspace assistant suggests ("What should I
# prepare?"), and on their own they retrieve nothing useful.
_VAGUE_RE = re.compile(
    r"^\s*(what|how|any|anything|which|when)\b.{0,80}\b"
    r"(prepare|next|do|advice|advise|suggest|recommend|strategy|steps?|help)\b",
    re.IGNORECASE,
)
_MIN_SUBSTANTIVE_TERMS = 3


def _terms(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z؀-ۿ]{3,}", text or "")
    out, seen = [], set()
    for w in words:
        low = w.lower()
        if low in _STOPWORDS or low in seen:
            continue
        seen.add(low)
        out.append(w)
    return out


def is_vague(question: str) -> bool:
    """True when the question alone gives retrieval almost nothing to match."""
    if _VAGUE_RE.match(question or ""):
        return True
    return len(_terms(question)) < _MIN_SUBSTANTIVE_TERMS


def retrieval_supplement(context: Optional[dict]) -> str:
    """Bounded search terms derived from APPROVED case fields.

    Built from case_type, title and description — the fields already whitelisted
    and PII-scrubbed upstream. Returns terms only, never sentences, because this
    is concatenated onto a retrieval query and not shown to anyone.
    """
    if not context:
        return ""
    parts = [
        str(context.get("case_type") or ""),
        str(context.get("title") or ""),
        str(context.get("description") or ""),
    ]
    terms = _terms(" ".join(p for p in parts if p))[:_MAX_SUPPLEMENT_TERMS]
    return " ".join(terms)[:_MAX_SUPPLEMENT_CHARS]


def augment_query(question: str, context: Optional[dict]) -> str:
    """The user's question, plus case terms when the question needs them.

    NEVER replaces the question. The user's own words stay first and intact —
    named-statute affinity reads the raw query, and generation answers the
    question that was asked, so overwriting it would silently change both.
    The supplement is added only when the question is too vague to retrieve on.
    """
    question = question or ""
    if not context or not is_vague(question):
        return question
    supplement = retrieval_supplement(context)
    return f"{question} {supplement}".strip() if supplement else question


# Provenance -----------------------------------------------------------------

def context_fingerprint(context: Optional[dict]) -> Optional[str]:
    """Stable hash of the context that was used. Never the facts themselves.

    Lets an auditor prove two turns used the SAME case context, or that a turn's
    context differed from the case record as it stands now, without the audit
    store becoming a second copy of privileged case material.
    """
    if not context:
        return None
    canonical = json.dumps(context, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def record_version(case: Optional[dict]) -> Optional[str]:
    """The case record's own version marker — updated_at, as an ISO string."""
    if not case:
        return None
    value = case.get("updated_at") or case.get("created_at")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None
