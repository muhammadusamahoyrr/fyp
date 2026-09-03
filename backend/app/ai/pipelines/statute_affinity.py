"""Named-statute affinity: when the user names one statute, rank it first.

The problem
-----------
"What is the punishment for theft under the Pakistan Penal Code?" retrieved
PPC 379 — the provision that answers it — at ensemble rank 15-16, outside the
top eight that grading and generation actually see. Seven of the top eight were
CrPC: procedural provisions that mention PPC section numbers without stating
any offence. The query names the statute explicitly and retrieval gave that
name no weight at all.

This is deliberately NOT a filter
---------------------------------
Preference, never exclusion. A CrPC provision can be the right answer to a PPC
question — s.221 (form of charge) legitimately quotes penal sections, and the
theft query's own evidence set needs it. Removing the other statutes would
trade a ranking bug for a correctness bug. So the two groups are concatenated,
not filtered, and order WITHIN each group is preserved exactly.

Why the raw query and not the rewrite
-------------------------------------
Detection reads state["query"], the user's own words. `normalized_query` is
produced by an LLM rewrite that is free to introduce statute names the user
never typed — retrieval_node's _expand_query appends "PPC CrPC statute" style
terminology on purpose. Preferring a statute the model invented would be a
silent, unfalsifiable ranking change, and FAILURE_CASE_001 was exactly a
corrupted normalized_query steering retrieval.

Precision over recall
---------------------
Two or more distinct statutes named => no preference, because a comparison
question needs both sides. Subject words (theft, bail, evidence, cybercrime)
are NOT statute mentions; inferring intent from them would fire on almost every
legal query and quietly become a global reranker. A bare section number
("section 379") names no statute and gets no preference.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Iterable, Optional

from app.ai.answer_citations import statute_alias_map, statute_display_map

# Extra surface forms for the acronyms. These are spellings, not new statutes:
# every one folds onto a family key that already exists in the shared registry,
# so this cannot introduce a statute citation matching does not know.
_ACRONYM_FORMS: dict[str, tuple[str, ...]] = {
    "PPC":          ("PPC", "P.P.C.", "P P C"),
    "CRPC":         ("CrPC", "Cr.P.C.", "Cr P C", "CRPC"),
    "CPC":          ("CPC", "C.P.C."),
    "QSO":          ("QSO", "Q.S.O."),
    "PECA":         ("PECA",),
    "MFLO":         ("MFLO",),
    "CONSTITUTION": ("Constitution",),
}


def _pattern_for(form: str) -> str:
    """Boundary-safe pattern for one literal surface form.

    Lookarounds, not \\b. A trailing \\b cannot match after "P.P.C." because the
    final character is a dot: \\b needs a word/non-word transition and there is
    no word character to transition from. (?!\\w) has no such problem.

    The leading (?<!\\w) is what stops CPC matching inside CrPC — the preceding
    "r" is a word character, so the lookbehind fails. That matters more than it
    looks: every match is collected into a set, so a substring collision would
    register two families and silently produce NO preference at all rather than
    an obviously wrong one.
    """
    return r"(?<!\w)" + re.escape(form).replace(r"\ ", r"[ ]*") + r"(?!\w)"


@lru_cache(maxsize=1)
def _detectors() -> tuple[tuple[str, re.Pattern], ...]:
    """[(family_key, compiled pattern), ...] over every recognised surface form.

    Full names come from the shared registry; the year-suffixed variant is
    generated rather than listed, so "Pakistan Penal Code 1860" needs no second
    entry. Acronym spellings are the only literal data here.
    """
    out: list[tuple[str, re.Pattern]] = []
    for full_name, family in statute_alias_map().items():
        base = re.escape(full_name).replace(r"\ ", r"[ ]*")
        # Optional trailing year: "Pakistan Penal Code" and "... 1860" alike.
        out.append((family, re.compile(
            r"(?<!\w)" + base + r"(?:[ ,]*(?:1[6-9]\d{2}|20\d{2}))?(?!\w)",
            re.IGNORECASE)))
    for family, variants in _ACRONYM_FORMS.items():
        for v in variants:
            body = _pattern_for(v)
            if family == "CONSTITUTION" and v == "Constitution":
                # Unlike every other short form here, "constitution" is also an
                # ordinary English noun, and legal text uses it that way:
                # "the constitution of a partnership firm", "the constitution of
                # the board". Both matched, and would have preferred the
                # Constitution of Pakistan over the statute the user asked about.
                # Requiring that a following "of" be "of Pakistan" removes the
                # noun sense while keeping the real references — "under the
                # Constitution, Article 199" has no "of" at all, and "Constitution
                # of Pakistan" is matched by the full-name pattern regardless.
                body += r"(?!\s+of\s+(?!Pakistan\b))"
            out.append((family, re.compile(body, re.IGNORECASE)))
    return tuple(out)


def _registry_matches(query: str) -> set[str]:
    """Display names for every registry statute the query names."""
    if not query or not query.strip():
        return set()
    display = statute_display_map()
    families = {family for family, pattern in _detectors() if pattern.search(query)}
    # Repeated aliases for one statute collapse here — the set is keyed on the
    # family, so "PPC ... Pakistan Penal Code ..." is one statute, not two.
    return {display[f] for f in families if f in display}


def detect_named_statute(query: str) -> Optional[str]:
    """The one REGISTRY statute the query names, as a corpus `statute` value.

    Returns e.g. "PPC 1860", or None when the query names no registry statute or
    names more than one. Callers that also have candidate chunks should prefer
    detect_statute_for(), which additionally sees corpus-only statute names.
    """
    hits = _registry_matches(query)
    return next(iter(hits)) if len(hits) == 1 else None


def _statute_of(chunk: Any) -> str:
    """Statute name from either a dict chunk or a LangChain Document."""
    if isinstance(chunk, dict):
        return str(chunk.get("statute") or "")
    meta = getattr(chunk, "metadata", None) or {}
    return str(meta.get("statute") or "")


def prefer_statute(chunks: list, statute: Optional[str]) -> list:
    """Stable partition: `statute`'s chunks first, everything else after.

    Order within each group is preserved exactly, so this reorders across the
    boundary and nowhere else. With `statute` None — the common case — the input
    list is returned unchanged, not merely equal: no preference must mean no
    behaviour change at all.
    """
    if not statute or not chunks:
        return chunks

    from app.ai.answer_citations import normalise_statute
    want = normalise_statute(statute)

    preferred, others = [], []
    for c in chunks:
        (preferred if normalise_statute(_statute_of(c)) == want else others).append(c)

    # Nothing matched, or everything did — either way the order is unchanged and
    # returning the original list keeps that literally true.
    if not preferred or not others:
        return chunks
    return preferred + others


_TRAILING_YEAR = re.compile(r"[\s,]*\b(1[6-9]\d{2}|20\d{2})\s*$")


def detect_named_statute_in(chunks: Iterable, query: str) -> Optional[str]:
    """Stage two: a statute named in the query that is present in `chunks`.

    The acronym registry covers the seven families that have short forms. The
    corpus holds far more — Punjab Tenancy Act 1887, Punjab Rented Premises Act
    2009, Succession Act 1925 — and "under the Punjab Tenancy Act" must beat the
    generic urban-tenancy topic rule just as "under the PPC" beats it.

    Rather than hand-maintain a second table of those names (which would drift
    from the corpus the moment a statute is ingested), the candidate set IS the
    statutes present in the chunks being ordered. That is exactly the universe
    where a preference could change anything, it needs no database lookup, and a
    statute absent from the results cannot be preferred into existence.

    Full names only: the year is optional but the name is not, so "tenant
    eviction in Punjab" still matches nothing.
    """
    hits = _corpus_matches(chunks, query)
    return next(iter(hits)) if len(hits) == 1 else None


def _corpus_matches(chunks: Iterable, query: str) -> set[str]:
    """Display names for every chunk-present statute the query names."""
    if not query or not query.strip():
        return set()
    hits: set[str] = set()
    for name in {_statute_of(c) for c in chunks if _statute_of(c)}:
        bare = _TRAILING_YEAR.sub("", name).strip()
        if len(bare) < 8:          # too short to be an unambiguous full name
            continue
        pattern = r"(?<!\w)" + re.escape(bare).replace(r"\ ", r"[ ]*") + r"(?!\w)"
        if re.search(pattern, query, re.IGNORECASE):
            hits.add(name)
    return hits


def detect_statute_for(chunks: Iterable, query: str) -> Optional[str]:
    """The one statute the query names, across BOTH detectors combined.

    The two detectors must be unioned before the exactly-one rule is applied,
    not chained with `or`. Chaining short-circuits: "Compare the PPC and the
    Punjab Tenancy Act" satisfies the registry detector alone (one family, PPC)
    and would have returned a preference for PPC — silently tilting a comparison
    question toward one side, which is precisely the failure the exactly-one
    rule exists to prevent. Only the union sees both statutes.

    De-duplication is by normalise_statute, so a statute found by BOTH detectors
    (query says "PPC 1860", corpus chunk is "PPC 1860") counts once rather than
    cancelling itself out as two.
    """
    from app.ai.answer_citations import normalise_statute

    combined = _registry_matches(query) | _corpus_matches(chunks, query)
    canonical = {normalise_statute(name): name for name in combined}
    return next(iter(canonical.values())) if len(canonical) == 1 else None


def apply_affinity(chunks: list, query: str) -> tuple[list, Optional[str]]:
    """Detect and apply in one call. Returns (ordered_chunks, statute_or_None).

    Both call sites share this so the two choke points cannot disagree about
    what the user named.
    """
    statute = detect_statute_for(chunks, query)
    return prefer_statute(chunks, statute), statute
