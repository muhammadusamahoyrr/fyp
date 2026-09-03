"""How large one stored turn is allowed to be, and why each bound exists.

WHAT GOES WRONG WITHOUT THESE
-----------------------------
A Mongo document is capped at 16MB, and the cap is enforced at WRITE time. So
an unbounded message does not degrade — it throws, after the graph has already
run, after a provider has already been paid, and at the exact moment the answer
was about to be filed. The user sees a failure for work that succeeded.

Bounding at the boundary instead means an oversized turn is refused BEFORE any
of that: no graph run, no provider call, no partial write. The refusal is a
validation error the user can act on, not a storage error they cannot.

WHY EACH FIELD IS BOUNDED SEPARATELY
------------------------------------
A single total would let one field starve the others — 400 citations with no
text, or one enormous answer with no evidence — and both shapes break a
different part of the UI before they break the document limit. Each cap is set
where the surface stops being usable, and the total is a backstop under all of
them rather than the only rule.

The numbers are deliberately generous against real traffic: the longest IRAC
answer measured on this corpus is a few thousand characters with under twenty
citations. These are limits on the absurd, not on the large.
"""
from __future__ import annotations

import json

from app.core.exceptions import AppValidationError

# One message's text. Comfortably above the longest real answer; a question
# this long is a paste, not a question.
MAX_CONTENT_CHARS = 32_000

# Evidence attached to one answer. The generation prompt carries far fewer than
# this, so hitting it means something upstream is looping.
MAX_CITATIONS = 200
MAX_CLAIMS = 200

# Everything except `content`, serialised. Catches a single pathological
# citation (a full statute text smuggled into a field) that the counts miss.
MAX_METADATA_BYTES = 512_000

# The whole stored record. A backstop under the per-field caps: 400 of these is
# still an order of magnitude inside the 16MB document limit, which matters
# because the conversation summary and the messages are separate documents now
# but a legacy conversation still holds its messages inline.
MAX_MESSAGE_BYTES = 768_000

# What a client may ask for in one page of history.
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


def _serialised_size(value: object) -> int:
    """Bytes this would occupy as JSON. Never raises on odd input."""
    try:
        return len(json.dumps(value, default=str, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return len(repr(value).encode("utf-8"))


def check_content(content: str) -> None:
    if content is None:
        return
    if len(str(content)) > MAX_CONTENT_CHARS:
        raise AppValidationError(
            f"Message is too long ({len(str(content))} characters). "
            f"The limit is {MAX_CONTENT_CHARS}."
        )


def check_answer_payload(payload: dict | None) -> None:
    """Bound the evidence attached to an answer, before it is stored."""
    if not payload:
        return
    citations = payload.get("citations") or []
    claims = payload.get("claims") or []
    if isinstance(citations, list) and len(citations) > MAX_CITATIONS:
        raise AppValidationError(
            f"Too many citations on one answer ({len(citations)}); "
            f"the limit is {MAX_CITATIONS}.")
    if isinstance(claims, list) and len(claims) > MAX_CLAIMS:
        raise AppValidationError(
            f"Too many claims on one answer ({len(claims)}); "
            f"the limit is {MAX_CLAIMS}.")


def check_message(message: dict) -> None:
    """The final gate: per-field caps, then the whole record.

    Called on the assembled message rather than its parts, so a record that
    passes every individual limit and still cannot be stored is caught here
    instead of by Mongo.
    """
    check_content(message.get("content"))
    # Counts, before bytes. A serialised-size failure on an answer carrying
    # eight hundred citations reports a number of bytes, which says nothing
    # about what went wrong; the count says exactly what did. This ran in tests
    # only — the production path checked total size and never the counts it was
    # written to bound.
    check_answer_payload(message)

    metadata = {k: v for k, v in message.items() if k != "content"}
    metadata_size = _serialised_size(metadata)
    if metadata_size > MAX_METADATA_BYTES:
        raise AppValidationError(
            f"Answer metadata is too large ({metadata_size} bytes); "
            f"the limit is {MAX_METADATA_BYTES}.")

    total = _serialised_size(message)
    if total > MAX_MESSAGE_BYTES:
        raise AppValidationError(
            f"This message is too large to store ({total} bytes); "
            f"the limit is {MAX_MESSAGE_BYTES}.")


def check_turn_input(content: str) -> None:
    """Bound what a user sends BEFORE the graph runs.

    Separate from `check_message` on purpose: this one runs before any provider
    is called, so an oversized question costs nothing. `check_message` runs
    again on the assembled answer, because the answer's size is not knowable
    until it exists.
    """
    check_content(content)


def clamp_page_size(value: int | None) -> int:
    if not value or value < 1:
        return DEFAULT_PAGE_SIZE
    return min(int(value), MAX_PAGE_SIZE)
