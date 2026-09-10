"""Binding an intake analysis to the evidence it was produced from.

WHY THIS IS NOT `answer_citations`
----------------------------------
The chat path resolves citations AFTER generation because it has to: its answer
is prose written for a human, so the only way back to a source is to parse the
text and look up what it names. Every weakness of that route — a phrasing the
regex does not know, a subsection, an alias — is unavoidable there.

Intake's answer is not prose. It is JSON produced under a schema this codebase
defines, so the model can be asked to name the evidence id it used, and binding
becomes a lookup instead of a parse. That changes what a failure MEANS:

    phantom      the model named an id that was never in the evidence.
                 A hallucinated citation, caught with certainty.
    mismatched   the id exists, but the section quoted is not that chunk's.
    bound        id exists and the section agrees.
    textual      no id was emitted; resolved by parsing, chat-style.
    unbound      neither route worked.

`unresolved` in the chat path cannot separate "the model cited something it was
never shown" from "my regex did not understand the phrasing". Those are a
hallucination and a tooling gap, and for a legal product they must not share a
label.

WHY EVERYTHING HERE IS PURE
---------------------------
No I/O, no model, no state. The whole verification story for intake citations
is decided by these functions, and on a CPU-only deployment an offline test is
the only kind that can be run often enough to be worth having.
"""
from __future__ import annotations

from typing import Any

from app.ai.answer_citations import (
    extract_citations,
    normalise_statute,
)

# How a citation was tied to its source.
BIND_ID = "id"                  # the model named an evidence id
BIND_TEXTUAL = "textual"        # parsed out of the text, chat-style
BIND_NONE = "none"              # nothing to bind

# Per-citation outcomes.
STATUS_BOUND = "bound"
STATUS_MISMATCHED = "mismatched"
STATUS_PHANTOM = "phantom"
STATUS_TEXTUAL = "textual"
STATUS_UNBOUND = "unbound"

# A citation the reader must not treat as verified.
UNTRUSTWORTHY = frozenset({STATUS_PHANTOM, STATUS_MISMATCHED, STATUS_UNBOUND})


def _norm_section(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _statute_evidence(evidence: list[dict] | None) -> list[dict]:
    return [e for e in (evidence or []) if e.get("kind") == "statute"]


def bind_intake_citations(
    law_citations: list[dict] | None,
    evidence: list[dict] | None,
) -> tuple[list[dict], str]:
    """Tie each cited law to the evidence entry it claims to come from.

    Returns `(citations, binding_mode)`. Citations are shaped like the chat
    path's so `apply_currency` and `apply_source_links` accept them unchanged —
    `statute`, `section`, `type`, `status`, `source` — plus the intake-specific
    `binding` and `evidence_id`.

    `binding_mode` reports HOW the set as a whole was resolved. A drop to
    `textual` means the model ignored the ids and the analysis fell back to
    parsing; that is a real degradation in what can be claimed about the
    citations, and it is recorded rather than absorbed silently.
    """
    entries = _statute_evidence(evidence)
    by_id = {str(e.get("id")): e for e in entries}

    citations: list[dict] = []
    saw_id = False

    for raw in law_citations or []:
        evidence_id = str(raw.get("evidence_id") or "").strip()
        statute = (raw.get("statute") or "").strip()
        section = str(raw.get("section") or "").strip()
        note = (raw.get("note") or "").strip()

        if evidence_id:
            saw_id = True
            source = by_id.get(evidence_id)
            if source is None:
                # The model named a source it was never given. There is no
                # reading of this that is a formatting problem.
                status = STATUS_PHANTOM
            elif _norm_section(section) and _norm_section(section) != _norm_section(
                source.get("section")
            ):
                # Real chunk, wrong section. Distinct from a phantom because the
                # fix is different: the model misread evidence it did have.
                status = STATUS_MISMATCHED
            else:
                status = STATUS_BOUND
        else:
            source = None
            status = STATUS_UNBOUND

        citations.append({
            "statute": statute or (source or {}).get("statute", ""),
            "section": section or str((source or {}).get("section", "")),
            "type": "statute",
            "status": status,
            "binding": BIND_ID if evidence_id else BIND_NONE,
            "evidence_id": evidence_id,
            # NOT `note`. `apply_currency` writes a repeal note under that key
            # with `entry.update(verdict)`, so a citation's own description was
            # silently blanked on its way through the finalizer.
            "description": note,
            "source": (source or {}).get("source", ""),
            "chunk_id": (source or {}).get("chunk_id", ""),
            "province": (source or {}).get("province", ""),
        })

    if saw_id:
        return citations, BIND_ID
    if citations:
        return citations, BIND_NONE
    return citations, BIND_NONE


def bind_textually(text: str, evidence: list[dict] | None) -> tuple[list[dict], str]:
    """Fallback for a provider that ignored the evidence ids.

    Reproduces the chat path's behaviour — parse the text, resolve against the
    evidence — so an older or weaker model degrades to today's quality rather
    than to a wall of `phantom`. Marked `textual` throughout so the record never
    claims id-level binding it did not have.
    """
    entries = _statute_evidence(evidence)
    index = {
        (normalise_statute(e.get("statute", "")), _norm_section(e.get("section"))): e
        for e in entries
    }

    citations: list[dict] = []
    for parsed in extract_citations(text or ""):
        key = (normalise_statute(parsed.statute), _norm_section(parsed.section))
        source = index.get(key)
        citations.append({
            "statute": parsed.statute,
            "section": parsed.section,
            "type": "statute",
            "status": STATUS_TEXTUAL if source else STATUS_UNBOUND,
            "binding": BIND_TEXTUAL,
            "evidence_id": str(source.get("id")) if source else "",
            "description": "",
            "source": (source or {}).get("source", ""),
            "chunk_id": (source or {}).get("chunk_id", ""),
            "province": (source or {}).get("province", ""),
        })
    return citations, (BIND_TEXTUAL if citations else BIND_NONE)


def build_intake_claims(
    summary: str,
    actions: list[dict] | None,
    citations: list[dict],
    evidence: list[dict] | None,
) -> list[dict]:
    """The judge's checklist, built from the analysis STRUCTURE.

    The chat path sentence-splits a paragraph to find claims. Intake does not
    need to: a recommended action already IS one claim, and the summary is one
    more. The list is the structure.

    Shaped for `parse_claim_support` and `grounding_veto`, which are reused
    unchanged — they only ever read `index`, `citation_status` and `support`.
    A claim counts as `matched` when it rests on at least one citation that
    actually bound; anything else stays `unassessed`, because there is nothing
    to check it against.
    """
    # An ACTION is checkable against any section that genuinely exists in the
    # evidence — including one the model did not think to list under
    # `law_citations`, and including the chunk behind a `mismatched` citation,
    # whose section label was wrong but whose text is real. Scoping this to the
    # cited-and-bound set instead would leave a perfectly checkable
    # recommendation unassessed because of an unrelated bookkeeping gap.
    real_ids = {str(e.get("id")) for e in _statute_evidence(evidence) if e.get("id")}

    # The SUMMARY asserts a legal position built on the cited laws, so it is
    # checkable only when at least one of those citations actually bound. With
    # none, there is nothing the position rests on to check it against.
    trustworthy_ids = {
        c.get("evidence_id")
        for c in citations
        if c.get("evidence_id") and c.get("status") not in UNTRUSTWORTHY
    }
    any_trustworthy = bool(trustworthy_ids)

    claims: list[dict] = []
    index = 1

    summary_text = (summary or "").strip()
    if summary_text:
        # The summary asserts the client's legal position. It went unjudged
        # entirely: the verdict covered recommended_actions and was then stamped
        # on the whole analysis, summary included.
        claims.append({
            "index": index,
            "kind": "summary",
            "text": summary_text,
            "source_ids": sorted(trustworthy_ids),
            "citation_status": "matched" if any_trustworthy else "unresolved",
            "support": "unassessed",
        })
        index += 1

    for action in actions or []:
        text = (action.get("text") or "").strip() if isinstance(action, dict) else str(action).strip()
        if not text:
            continue
        raw_ids = action.get("evidence_ids") if isinstance(action, dict) else None
        ids = [str(i).strip() for i in (raw_ids or []) if str(i).strip()]
        usable = [i for i in ids if i in real_ids]
        claims.append({
            "index": index,
            "kind": "action",
            "text": text,
            "source_ids": usable,
            "citation_status": "matched" if usable else "unresolved",
            "support": "unassessed",
        })
        index += 1

    return claims


def render_applicable_laws(citations: list[dict] | None) -> list[str]:
    """The legacy `applicable_laws` display strings, derived.

    The field stays a `list[str]` because the print view, the text export and
    the intake panel all render it directly, and none of them should have to
    change for this. `law_citations` carries the structure; this carries the
    words, in the format those readers already produce.

    A citation that did not bind is MARKED rather than dropped. Silently
    removing it would leave the reader with a shorter list and no reason to
    doubt what remains — and the entries most worth doubting are exactly the
    ones that would disappear.
    """
    out: list[str] = []
    for entry in citations or []:
        statute = (entry.get("statute") or "").strip()
        section = str(entry.get("section") or "").strip()
        if not statute and not section:
            continue
        label = statute
        if section:
            label = f"{statute} Section {section}" if statute else f"Section {section}"
        description = (entry.get("description") or "").strip()
        if description:
            label = f"{label} — {description}"
        if entry.get("status") in UNTRUSTWORTHY:
            label = f"{label} [unverified citation]"
        out.append(label)
    return out


def render_recommended_actions(actions: list[dict] | None) -> list[str]:
    """The legacy `recommended_actions` display strings, derived."""
    out: list[str] = []
    for action in actions or []:
        if isinstance(action, dict):
            text = (action.get("text") or "").strip()
        else:
            text = str(action).strip()
        if text:
            out.append(text)
    return out


def summarise_binding(citations: list[dict] | None) -> dict:
    """Counts per outcome, for the record and for the caution the UI shows."""
    counts = {
        STATUS_BOUND: 0, STATUS_MISMATCHED: 0, STATUS_PHANTOM: 0,
        STATUS_TEXTUAL: 0, STATUS_UNBOUND: 0,
    }
    for entry in citations or []:
        status = entry.get("status")
        if status in counts:
            counts[status] += 1
    counts["total"] = len(citations or [])
    counts["untrustworthy"] = sum(
        counts[s] for s in (STATUS_PHANTOM, STATUS_MISMATCHED, STATUS_UNBOUND)
    )
    return counts
