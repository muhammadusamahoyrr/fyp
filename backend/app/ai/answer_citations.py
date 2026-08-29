"""What the ANSWER cited, matched against what retrieval actually supplied.

THE PROBLEM THIS FIXES
----------------------
`generation_node` builds the citation list from the top five retrieved chunks:

    citations = [... for c in state["reranked_chunks"][:5] if c["section_number"]]

Nothing reads the answer. So the "Sources" chips under an answer were retrieval
telemetry wearing a citation label, and the two sets are provably different —
citation_grounding measured 83% of answers carrying a parsed citation citing at
least one section that was never retrieved.

FOUR STATES, AND "VERIFIED" IS NOT ONE OF THEM
-----------------------------------------------
    matched      the answer cites it AND it is in this answer's evidence
    unresolved   the answer cites it, and it is NOT in this answer's evidence
    retrieved    it is in the evidence; the answer did not (parseably) cite it

There is deliberately no `verified`. Existence in the corpus is not
verification: `citation_verification` can say a section EXISTS, but a section
existing somewhere is not evidence that it says what the answer claims, nor that
it governs the user's question. Promoting "exists" to "verified" is the precise
error that module's docstring warns against, and this layer has strictly less
information than it does.

`unresolved` is likewise NOT an accusation. citation_grounding records the
reason at length: CrPC s.154 is exactly the FIR provision, and an answer citing
it from parametric memory is correct while being ungrounded. Unresolved means
"we cannot show you where this came from", which is a statement about our
evidence, not about the law.

WHY THIS PARSER IS SEPARATE FROM citation_grounding.extract_citations
---------------------------------------------------------------------
That function is deliberately conservative — it refuses a bare "PPC 302"
because that is also how a statute's year is written, and a false positive there
becomes a false accusation of hallucination in a published measurement. Its
semantics are frozen: test_a_bare_number_is_not_a_citation pins them, and the
provenance groundedness numbers are computed from it.

This layer can afford to parse more, because a false parse here has a different
and much smaller consequence. Every parsed citation is matched against THIS
answer's retrieved chunks; a mis-parse simply fails to match and is shown as
unresolved. The measurement module accuses, this module labels. Two risk
profiles, two parsers, and the strict one stays untouched.
"""
from __future__ import annotations

import logging
import re
from typing import NamedTuple

from app.ai.corpus_index import canonical_section, is_lettered

logger = logging.getLogger(__name__)

# Section numbers are 1-3 digits. Four-digit runs are years, and the pattern
# below cannot capture them — which is what stops "PPC 1860" being read as
# section 1860 and lets a bare "PPC 302" be parsed safely.
#
# The optional letter suffix captures amendment-inserted provisions — PPC 489-F,
# CrPC 22-A — written hyphenated, compact or spaced. It must be captured WHOLE:
# truncating to the digits made "PPC 489-F" resolve to s.489, a different
# offence, and then match s.489's evidence chunk as though it were the source
# the answer had cited. The lookaheads stop a following word being eaten as a
# suffix, and stop "PPC 302 A man is said to..." reading as s.302-A.
_SECTION = (
    r"(\d{1,3}(?!\d)"
    r"(?:\s*[-\u2013\u2014]\s*[A-Za-z]{1,2}(?![A-Za-z])"
    r"|[A-Za-z]{1,2}(?![A-Za-z])"
    r"|\s+[A-Z](?![A-Za-z])(?!\s+[a-z]))?)"
)
_SUBSECTION = r"(?:\s*\([0-9a-z]+\))?"
_MARKER = r"(?:Section|Sections|Sec\.?|ss?\.|§)"
_FAMILY = r"PPC|CrPC|CPC|QSO|PECA|MFLO"
_YEAR = r"(?:1860|1898|1908|1984|2016|1961|1872|1870|1899|1973)"

# "PPC 302", "PPC s.302", "PPC Section 302", "CrPC 1898 s.154".
# The marker is OPTIONAL — that is the whole difference from the strict parser.
_FAMILY_FIRST = re.compile(
    rf"\b({_FAMILY})\b[\s,]*{_YEAR}?[\s,]*{_MARKER}?\s*{_SECTION}{_SUBSECTION}",
    re.I,
)

# "Section 302 of the Pakistan Penal Code", "section 154 CrPC".
_SECTION_FIRST_FAMILY = re.compile(
    rf"\b{_MARKER}\s*{_SECTION}{_SUBSECTION}[\s,]*(?:of\s+the\s+|of\s+)?"
    rf"\b({_FAMILY}|Pakistan Penal Code|Code of Criminal Procedure|"
    rf"Code of Civil Procedure|Qanun-e-Shahadat(?: Order)?|"
    rf"Muslim Family Laws Ordinance)\b",
    re.I,
)

# "Section 15 of the Punjab Rented Premises Act 2009". Requires a statute-shaped
# tail word (Act/Ordinance/Order/Code/Constitution) so ordinary prose after a
# section number cannot be swallowed as a statute name.
# Lowercase connectors are part of a statute's name, not a break in it. Without
# them "Guardians and Wards Act 1890" captured only "Wards Act 1890", and
# "Punjab Protection of Women against Violence Act 2016" — a real corpus statute
# — lost its first four words. Both then failed to match their own chunk and
# were reported unresolved: the safe direction, but still a miss.
_NAMED_STATUTE = (
    r"([A-Z][\w'\-]*(?:\s+(?:[A-Z][\w'\-]*|and|of|the|for|against|to)){0,7}?"
    r"\s+(?:Act|Ordinance|Order|Code)(?:\s*,?\s*\d{4})?)"
)

_SECTION_FIRST_NAMED = re.compile(
    rf"\b{_MARKER}\s*{_SECTION}{_SUBSECTION}\s*of\s+(?:the\s+)?{_NAMED_STATUTE}",
)

# "Punjab Rented Premises Act 2009 s.15", "the Family Courts Act 1964, Section 7".
# The mirror image of the pattern above, and the way a lawyer more often writes
# it. Without this a claim resting on a named provincial statute produced no
# claim at all and so was never assessed for support — found end-to-end, where
# "...under Punjab Rented Premises Act 2009 s.13" parsed as nothing.
#
# The explicit section marker is REQUIRED here (unlike the short-family pattern,
# which tolerates a bare "PPC 302"). A named statute ends in its year, so
# allowing a bare number would read "Act 2009 15" and, worse, invite the year
# itself to be taken as a section.
_NAMED_STATUTE_FIRST = re.compile(
    rf"\b{_NAMED_STATUTE}[\s,]*{_MARKER}\s*{_SECTION}{_SUBSECTION}",
)

# Short form is canonical: the corpus stores "PPC 1860", "CrPC 1898".
_ALIASES = {
    "PAKISTAN PENAL CODE":          "PPC",
    "CODE OF CRIMINAL PROCEDURE":   "CRPC",
    "CODE OF CIVIL PROCEDURE":      "CPC",
    "QANUN-E-SHAHADAT":             "QSO",
    "QANUN-E-SHAHADAT ORDER":       "QSO",
    "MUSLIM FAMILY LAWS ORDINANCE": "MFLO",
    "PREVENTION OF ELECTRONIC CRIMES ACT": "PECA",
}

# Display names for the short families, so a chip reads as a statute rather than
# an acronym the user has to decode.
_DISPLAY = {
    "PPC":  "PPC 1860",
    "CRPC": "CrPC 1898",
    "CPC":  "CPC 1908",
    "QSO":  "Qanun-e-Shahadat Order 1984",
    "PECA": "PECA 2016",
    "MFLO": "Muslim Family Laws Ordinance 1961",
}

_TRAILING_YEAR = re.compile(r"[\s,]*\b(1[6-9]\d{2}|20\d{2})\s*$")
_WS = re.compile(r"\s+")

# How many uncited retrieved chunks to carry through. Matches the cap the old
# generation-side list used, so the panel does not suddenly grow.
_MAX_RETRIEVED = 5


class ParsedCitation(NamedTuple):
    statute: str   # display form, e.g. "PPC 1860"
    section: str   # e.g. "302"
    key:     tuple[str, str]


def normalise_statute(name: str) -> str:
    """Match key for a statute name: upper-cased, de-yeared, alias-folded.

    The year is dropped because the answer and the corpus disagree about it
    constantly — "Punjab Rented Premises Act" and "Punjab Rented Premises Act
    2009" are the same statute, and an exact-string match would call the first
    unresolved.
    """
    text = _WS.sub(" ", (name or "").strip())
    text = _TRAILING_YEAR.sub("", text).strip(" ,.")
    upper = text.upper()
    return _ALIASES.get(upper, upper)


def _display_for(raw: str) -> str:
    key = normalise_statute(raw)
    if key in _DISPLAY:
        return _DISPLAY[key]
    return _WS.sub(" ", (raw or "").strip().strip(" ,."))


def _add(out: dict, raw_statute: str, section: str) -> None:
    # Canonical form, shared with citation_verification through
    # corpus_index.canonical_section, so the two parsers cannot disagree about
    # what "489F", "489-F" and "489 F" name.
    section = canonical_section(section)
    key = (normalise_statute(raw_statute), section)
    if not key[0] or not section:
        return
    # First mention wins, so repeating a citation cannot duplicate a chip.
    out.setdefault(key, ParsedCitation(_display_for(raw_statute), section, key))


def extract_citations(answer: str) -> list[ParsedCitation]:
    """Statutory citations mentioned in the answer, de-duplicated, in order."""
    found: dict[tuple[str, str], ParsedCitation] = {}
    text = answer or ""

    for m in _FAMILY_FIRST.finditer(text):
        _add(found, m.group(1), m.group(2))
    for m in _SECTION_FIRST_FAMILY.finditer(text):
        _add(found, m.group(2), m.group(1))
    for m in _SECTION_FIRST_NAMED.finditer(text):
        _add(found, m.group(2), m.group(1))
    for m in _NAMED_STATUTE_FIRST.finditer(text):
        _add(found, m.group(1), m.group(2))

    return list(found.values())


def _evidence_index(chunks: list[dict] | None) -> dict[tuple[str, str], dict]:
    """(statute, section) -> the retrieved chunk that supplies it."""
    index: dict[tuple[str, str], dict] = {}
    for chunk in chunks or []:
        statute = (chunk.get("statute") or "").strip()
        section = str(chunk.get("section_number") or "").strip()
        if not statute or not section:
            continue
        # Canonicalised on this side too: the corpus stores lettered sections
        # compactly ("365B") while a citation is canonicalised to "365-B", and
        # an un-normalised key would never match its own evidence.
        index.setdefault(
            (normalise_statute(statute), canonical_section(section)), chunk)
    return index


def _statute_entry(statute: str, section: str, status: str,
                   chunk: dict | None = None) -> dict:
    """One citation in the response. Shape matches what both UIs already read."""
    entry = {
        "statute": statute,
        "section": section,
        "source":  (chunk or {}).get("source_file", ""),
        "status":  status,
    }
    if chunk:
        # Enough to re-fetch the exact evidence behind this chip.
        entry["chunk_id"] = chunk.get("chunk_id", "")
        entry["province"] = chunk.get("province", "")
    return entry


def _judgment_cited(answer: str, chunk: dict) -> bool:
    """Did the answer actually refer to this judgment?

    Matched on the formatted reference, the case title and the judgment id —
    whichever the model echoed. No fuzzy matching: a judgment chip that links to
    a court PDF is something a lawyer may file against, so it says "cited" only
    when the citation is literally present.
    """
    haystack = (answer or "").lower()
    for field in ("citation", "title", "case_no", "judgment_id"):
        value = str(chunk.get(field) or "").strip().lower()
        if len(value) >= 6 and value in haystack:
            return True
    return False


def annotate_citations(
    answer: str,
    statute_chunks: list[dict] | None,
    case_law_chunks: list[dict] | None = None,
) -> list[dict]:
    """Citations for one answer, each labelled with where it came from.

    Ordered matched -> unresolved -> judgments -> retrieved, so the entries the
    answer actually leaned on lead the list and the merely-consulted ones sit
    below them.

    Matching is against `reranked_chunks`, the same evidence set
    citation_grounding measures against, so the two cannot disagree about what
    counts as grounded.
    """
    evidence = _evidence_index(statute_chunks)
    cited = extract_citations(answer)

    entries: list[dict] = []
    matched_keys: set[tuple[str, str]] = set()

    for citation in cited:
        chunk = evidence.get(citation.key)
        if chunk is not None:
            matched_keys.add(citation.key)
            entries.append(_statute_entry(
                citation.statute, citation.section, "matched", chunk))

    for citation in cited:
        if citation.key not in matched_keys:
            entries.append(_statute_entry(
                citation.statute, citation.section, "unresolved"))

    for chunk in case_law_chunks or []:
        label = (chunk.get("citation") or chunk.get("title") or "").strip()
        if not label:
            continue
        entries.append({
            "statute": label,
            "section": "",
            "source":  chunk.get("pdf_url", ""),
            "type":    "judgment",
            "url":     chunk.get("pdf_url", ""),
            "title":   chunk.get("title", ""),
            "status":  "matched" if _judgment_cited(answer, chunk) else "retrieved",
        })

    # Everything retrieved that the answer did not cite. Kept — and labelled —
    # rather than dropped: it is what the pipeline consulted, which stays useful
    # to show as long as it is not presented as what the answer cited.
    spare = 0
    for (norm, section), chunk in evidence.items():
        if (norm, section) in matched_keys:
            continue
        if spare >= _MAX_RETRIEVED:
            break
        spare += 1
        entries.append(_statute_entry(
            (chunk.get("statute") or "").strip(), section, "retrieved", chunk))

    return entries


# ══════════════════════════════════════════════════════════════════════════════
# Generation evidence, claims, and the id space that ties them together
# ══════════════════════════════════════════════════════════════════════════════
#
# THE BOUNDARY BUG THIS CLOSES
# ----------------------------
# annotate_citations() above matches against whatever chunk list it is handed.
# It used to be handed `reranked_chunks` — the full graded set — while
# generation_node only formatted the top 8 into the prompt, and
# hallucination_node independently formatted the top 5 under its OWN numbering.
# Three views of "the evidence", two of them numbered, and `[3]` meant a
# different source to each component.
#
# So a citation could be reported `matched` against a chunk the model never
# read. That is precisely the claim this system must not make: it says "the
# answer cited this and we can show you where it came from" about a source that
# was never in front of the model.
#
# build_generation_evidence() produces ONE ordered, id-stamped list. Generation
# formats from it, the grounding judge sees the same list under the same ids,
# and citation matching resolves against it. One id space, one boundary.

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z؀-ۿ\[])|\n+")

# "[1]", "[1,2]", "[1] [2]". The brackets are required: a bare "302" is never a
# source id, and "PPC 302" must not be read as one. The 1-2 digit cap keeps a
# bracketed year out of the id space too.
_MARKER = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")

# Headings and bare list scaffolding carry no legal claim of their own.
_STRUCTURAL = re.compile(
    r"^\s*(?:\*\*[^*]+\*\*\s*:?|#{1,6}\s|[-*•]\s*$|\d+\.\s*$)\s*$"
)

SUPPORT_VALUES = frozenset({"supported", "partial", "unsupported", "unassessed"})


def build_generation_evidence(
    statute_chunks: list[dict] | None,
    case_law_chunks: list[dict] | None = None,
    tool_results: list[dict] | None = None,
    statute_limit: int = 8,
) -> list[dict]:
    """The exact evidence handed to the model, in one numbered id space.

    `statute_limit` mirrors generation_node's own truncation (8 normally, 4 on a
    grounding retry) so the ids describe what was actually formatted into the
    prompt — not what retrieval happened to return.
    """
    evidence: list[dict] = []

    for chunk in (statute_chunks or [])[:statute_limit]:
        evidence.append({
            "id":       str(len(evidence) + 1),
            "kind":     "statute",
            "statute":  (chunk.get("statute") or "").strip(),
            "section":  str(chunk.get("section_number") or "").strip(),
            "chunk_id": chunk.get("chunk_id", ""),
            "source":   chunk.get("source_file", ""),
            "province": chunk.get("province", ""),
            "content":  chunk.get("content", ""),
        })

    for chunk in case_law_chunks or []:
        label = (chunk.get("citation") or chunk.get("title") or "").strip()
        if not label:
            continue
        evidence.append({
            "id":       str(len(evidence) + 1),
            "kind":     "judgment",
            "statute":  label,
            "section":  "",
            "chunk_id": chunk.get("judgment_id", ""),
            "source":   chunk.get("pdf_url", ""),
            "url":      chunk.get("pdf_url", ""),
            "title":    chunk.get("title", ""),
            "content":  chunk.get("content", ""),
        })

    for result in tool_results or []:
        evidence.append({
            "id":       str(len(evidence) + 1),
            "kind":     "engine",
            "statute":  f"{result.get('tool', 'engine')} (computed)",
            "section":  "",
            "chunk_id": "",
            "source":   "",
            "content":  str(result.get("result", ""))[:600],
            # The raw call, so generation can keep rendering engine output under
            # its existing STATUTORY DETERMINATION heading (tool name + args +
            # result) rather than flattening it into a generic source blob.
            "call":     result,
        })

    return evidence


def evidence_index(evidence: list[dict] | None) -> dict[tuple[str, str], dict]:
    """(normalised statute, section) -> evidence entry, statute entries only."""
    index: dict[tuple[str, str], dict] = {}
    for item in evidence or []:
        if item.get("kind") != "statute":
            continue
        statute, section = item.get("statute", ""), item.get("section", "")
        if statute and section:
            index.setdefault(
                (normalise_statute(statute), canonical_section(section)), item)
    return index


def _marker_ids(sentence: str, valid: set[str]) -> list[str]:
    """Bracketed source ids in a sentence, keeping only ids that exist.

    Unknown ids are dropped rather than reported: a model that writes "[9]" when
    eight sources were supplied has produced a typo, not a citation to a ninth
    source, and creating an entry for it would fabricate exactly the kind of
    reference this module exists to prevent.
    """
    out: list[str] = []
    for match in _MARKER.finditer(sentence or ""):
        for raw in match.group(1).split(","):
            sid = raw.strip()
            if sid in valid and sid not in out:
                out.append(sid)
    return out


def split_claims(answer: str, evidence: list[dict] | None) -> list[dict]:
    """Sentences of the answer that cite something, each tied to its sources.

    A "claim" is a sentence carrying at least one citation — a bracketed source
    id or a textual statutory citation. Sentences citing nothing are not claims
    to assess: there is no source to check them against, and inventing an
    association would be worse than declining to make one.

    Fully deterministic. No model decides what a claim is.
    """
    entries = evidence or []
    valid = {item["id"] for item in entries}
    by_id = {item["id"]: item for item in entries}
    index = evidence_index(entries)

    claims: list[dict] = []
    for raw in _SENTENCE_SPLIT.split(answer or ""):
        sentence = raw.strip()
        if not sentence or _STRUCTURAL.match(sentence):
            continue

        source_ids = _marker_ids(sentence, valid)

        # Textual citations resolve into the SAME id space, so "s.15 of the
        # Punjab Rented Premises Act" and "[2]" name one source, not two.
        unresolved: list[dict] = []
        for citation in extract_citations(sentence):
            item = index.get(citation.key)
            if item is not None:
                if item["id"] not in source_ids:
                    source_ids.append(item["id"])
            else:
                unresolved.append({"statute": citation.statute,
                                   "section": citation.section})

        if not source_ids and not unresolved:
            continue

        claims.append({
            "index":      len(claims) + 1,
            "text":       sentence,
            "source_ids": source_ids,
            "sources":    [
                {"id": sid,
                 "statute": by_id[sid].get("statute", ""),
                 "section": by_id[sid].get("section", "")}
                for sid in source_ids
            ],
            "unresolved": unresolved,
            # A claim whose only citations are unresolved has no source to be
            # judged against, so it can never be "supported" — the citation is
            # the problem, and support is simply not assessable.
            "citation_status": "matched" if source_ids else "unresolved",
            "support":         "unassessed",
        })
    return claims


def parse_claim_support(raw: str, claims: list[dict]) -> list[dict]:
    """Apply the judge's "1:supported,2:partial" verdict string to the claims.

    A flat string rather than a nested schema on purpose: llm.py records that the
    8B fast tier emits malformed tool calls when asked for a wide structured
    output, which is why triage runs on the main tier. Keeping the judge's schema
    at three flat fields stays inside what an 8B reliably emits, and puts the
    structure in this function — deterministic, and tested offline.

    Anything unparseable leaves the claim `unassessed`. A missing verdict is not
    evidence of support.
    """
    verdicts: dict[int, str] = {}
    for part in re.split(r"[,;\n]+", raw or ""):
        bits = part.split(":")
        if len(bits) != 2:
            continue
        idx, value = bits[0].strip(), bits[1].strip().lower()
        if idx.isdigit() and value in SUPPORT_VALUES:
            verdicts[int(idx)] = value

    for claim in claims:
        # A claim we could not resolve to a source stays unassessed however
        # confidently the judge labelled it: there was nothing to check against.
        if claim.get("citation_status") != "matched":
            continue
        verdict = verdicts.get(claim["index"])
        if verdict:
            claim["support"] = verdict
    return claims


# ══════════════════════════════════════════════════════════════════════════════
# Currency: is the cited provision still on the books?
# ══════════════════════════════════════════════════════════════════════════════
#
# TWO VALUES, AND "in_force" IS DELIBERATELY NOT ONE OF THEM
# -----------------------------------------------------------
#     repealed   the Act itself declares this section omitted — positively known
#     unknown    everything else
#
# `unknown` is not a soft yes. Repeal data exists for 4 of the 43 statutes in
# the corpus, it is a self-declared LOWER BOUND (statute_omissions parses range
# and single declarations but not the footnote style PPC uses), amendment is not
# modelled at all, and no statute carries an as-of date. Absence of an omission
# record is therefore absence of evidence, and inferring currency from it would
# be the single most dangerous claim this system could make — a lawyer files on
# "in force" in a way they never would on "not verified".
#
# So there is no code path that emits in_force, and none may be added without
# data that actually supports the conclusion.
#
# WHY JURISDICTION IS HANDLED HERE AND NOT IN corpus_index
# ---------------------------------------------------------
# `CorpusIndex.is_omitted()` is jurisdiction-blind by construction — it answers
# "does the map list this section", which is the right question for coverage
# density. Repeal, though, is scoped: a section killed by a Punjab notification
# is alive in Sindh, and asserting it dead nationally would be a false statement
# of law in three provinces. That scoping is applied here rather than by
# changing the index, so the existing verifier and its tests are untouched.

CURRENCY_REPEALED = "repealed"
CURRENCY_UNKNOWN = "unknown"

# Jurisdictions a repeal record may name that bind everywhere in the corpus.
_NATIONWIDE = frozenset({"", "federal"})


def currency_for(statute: str, section: str, province: str = "",
                 index=None) -> dict:
    """What we can honestly say about whether this provision still stands.

    Fail-open: any lookup problem yields `unknown`, never a claim of currency
    and never an exception. A currency check must not be able to fail an answer.

    `index` is explicit so callers in a request path can pass the cached index
    and tests can inject a controlled one. When it is None the shared index is
    used; if that cannot be built (no Chroma), the result is `unknown`.
    """
    blank = {"currency": CURRENCY_UNKNOWN, "instrument": "", "date": "",
             "jurisdiction": "", "note": ""}
    if not statute or not section:
        return blank

    try:
        idx = index
        if idx is None:
            from app.ai.corpus_index import get_index
            idx = get_index()
        cov = idx.coverage(statute)
        if cov is None:
            return blank

        # A lettered provision must never inherit the base section's repeal
        # status. `is_omitted` and `omission_record` both key on the leading
        # digits, and the omission map is built only from numbered declarations
        # — statute_omissions skips lettered sections by design — so it can
        # never speak to 489-F. Consulting it would report s.489's repeal as
        # though it were 489-F's, which is the same wrong-provision error the
        # verifier's VERIFIED-as-s.489 bug produced.
        if is_lettered(section):
            return blank

        if not cov.is_omitted(section):
            return blank

        record = cov.omission_record(section)
        jurisdiction = (getattr(record, "jurisdiction", "") or "").strip().lower()

        # A province-scoped repeal binds only that province. With no province on
        # the turn we cannot place the user, so we do NOT assert the repeal —
        # under-claiming is the safe direction, and the section stays `unknown`
        # rather than being declared dead for someone it may not bind.
        if jurisdiction not in _NATIONWIDE:
            here = (province or "").strip().lower()
            if here != jurisdiction:
                return blank

        return {
            "currency":     CURRENCY_REPEALED,
            "instrument":   getattr(record, "instrument", "") or "",
            "date":         getattr(record, "date", "") or "",
            "jurisdiction": jurisdiction,
            "note":         getattr(record, "note", "") or "",
        }
    except Exception:
        logger.exception("currency lookup failed for %s s.%s — reporting unknown",
                         statute, section)
        return blank


def _worst_currency(entries: list[dict]) -> str:
    """`repealed` wins. One dead source contaminates the claim that rests on it."""
    return (CURRENCY_REPEALED
            if any(e.get("currency") == CURRENCY_REPEALED for e in entries)
            else CURRENCY_UNKNOWN)


def apply_currency(citations: list[dict], claims: list[dict],
                   province: str = "", index=None) -> None:
    """Stamp currency onto citations, then onto the claims that cite them.

    In place, and never raises. Judgments are left `unknown`: the omission map
    is statutory, and a judgment is not repealed by an amending Act — it is
    overruled, which this system does not track at all.
    """
    by_key: dict[tuple[str, str], dict] = {}

    for entry in citations or []:
        if entry.get("type") == "judgment":
            entry.setdefault("currency", CURRENCY_UNKNOWN)
            continue
        verdict = currency_for(entry.get("statute", ""), entry.get("section", ""),
                               province, index)
        entry.update(verdict)
        by_key[(normalise_statute(entry.get("statute", "")),
                str(entry.get("section", "")))] = verdict

    for claim in claims or []:
        verdicts = []
        for source in claim.get("sources") or []:
            key = (normalise_statute(source.get("statute", "")),
                   str(source.get("section", "")))
            verdict = by_key.get(key) or currency_for(
                source.get("statute", ""), source.get("section", ""),
                province, index)
            source.update(verdict)
            verdicts.append(verdict)
        claim["currency"] = _worst_currency(verdicts)


def annotate_citations_from_evidence(answer: str,
                                     evidence: list[dict] | None) -> list[dict]:
    """annotate_citations(), resolving against the generation evidence.

    Evidence entries carry `section`/`url`; retrieval chunks carry
    `section_number`/`pdf_url`. Translating here keeps the shape-juggling in one
    place instead of spreading it through finalizer_node, and keeps
    annotate_citations usable on raw chunks for the paths that still have them.

    Engine entries are deliberately excluded: a computed bail verdict or court
    fee is not a citation, it is a determination, and listing it as a source
    would invite a lawyer to cite an engine call in a filing.
    """
    statute_chunks = [
        {"statute": e.get("statute", ""), "section_number": e.get("section", ""),
         "source_file": e.get("source", ""), "chunk_id": e.get("chunk_id", ""),
         "province": e.get("province", "")}
        for e in (evidence or []) if e.get("kind") == "statute"
    ]
    case_law_chunks = [
        {"citation": e.get("statute", ""), "title": e.get("title", ""),
         "pdf_url": e.get("url") or e.get("source", ""),
         "judgment_id": e.get("chunk_id", "")}
        for e in (evidence or []) if e.get("kind") == "judgment"
    ]
    return annotate_citations(answer, statute_chunks, case_law_chunks)


def format_evidence_for_prompt(evidence: list[dict] | None) -> str:
    """Render the id-stamped evidence. Shared by generation and the judge, so
    `[3]` cannot mean different things to the two of them."""
    lines: list[str] = []
    for item in evidence or []:
        if item["kind"] == "statute":
            head = item["statute"] + (
                f" Section {item['section']}" if item["section"] else "")
        elif item["kind"] == "judgment":
            head = f"{item['statute']} ({item.get('title', '')}) [judgment]"
        else:
            head = f"{item['statute']} [engine: computed ground truth]"
        lines.append(f"[{item['id']}] {head}\n{(item.get('content') or '')[:600]}")
    return "\n\n".join(lines)
