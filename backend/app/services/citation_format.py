"""One way to write a statutory citation, so the checker can always read it.

WHY THIS EXISTS.

The generators used to hand-write citations in prose, and they did not agree
with each other. Two templates emitted the Prevention of Electronic Crimes Act
in two different shapes:

    fia_cybercrime         "sections 20 — offences against dignity, 21 —
                            offences against modesty, and 24 — cyberstalking"
    (an intake field)      "sections 20 and 24 PECA"

`citation_verification` reads the second and is blind to the first. A citation
it cannot see is reported as **"no citations found"** — which reads as approval.
So a complaint resting entirely on PECA was recorded as citing no authority at
all, and nothing anywhere said otherwise.

The tempting fix is to teach the parser to read the gloss list. That is an arms
race against our own templates: every new drafting flourish becomes a new blind
spot, discovered — if ever — by someone auditing a migration. This module is the
other side of that trade. Generators ask for a citation and get back the one
form the parser is tested against, and
`tests/test_template_citation_binding.py` walks every template to prove no
generator has drifted from it.

WHAT CANONICAL MEANS HERE

    section 20 of the Prevention of Electronic Crimes Act, 2016
    sections 20, 21 and 24 of the Prevention of Electronic Crimes Act, 2016

Marker, then the numbers as a plain list, then `of the` and the statute's full
name. Glosses are legitimate and often necessary — they just belong AFTER the
citation, not threaded between its members, where they break the list.

The statute is always named in full. "of the Code" is how a lawyer refers back
to a statute named earlier in the same document, and it is perfectly good
drafting, but a citation checker has no anaphora and cannot resolve it — so it
silently drops the citation.
"""
from __future__ import annotations

import re

# Section tokens as lawyers write them: 302, 489-F, 489F, 489 F, 22A. Kept
# deliberately narrow -- this reads OUR OWN structured input, not free prose.
#
# The space-separated form is included to match what the VERIFIER's own
# `_SECTION_NUM_INNER` accepts. If this were stricter, an intake field reading
# "489 F" would normalise to s.489 -- a different offence entirely, and exactly
# the lettered-section confusion the verifier was hardened against.
_SECTION_TOKEN = re.compile(
    r"\d{1,4}(?:\s*[-–—]\s*[A-Za-z]{1,2}(?![A-Za-z])"
    r"|[A-Za-z]{1,2}(?![A-Za-z])"
    r"|\s+[A-Z](?![A-Za-z]))?")

# Four-digit years are statute names, never section numbers. Without this,
# "sections 20 and 24 PECA 2016" contributes a phantom s.2016.
_YEARLIKE = re.compile(r"^(1[5-9]|20)\d{2}$")


def normalise_section(token: str) -> str:
    """`489 - f` / `489f` / `489-F` -> `489-F`. One spelling, so a list cannot
    contain the same provision twice under two names."""
    text = re.sub(r"\s+", "", str(token or "")).upper()
    match = re.fullmatch(r"(\d{1,4})[-–—]?([A-Za-z]{1,2})?", text)
    if not match:
        return text
    number, suffix = match.groups()
    return f"{number}-{suffix}" if suffix else number


def section_numbers(text: str) -> list[str]:
    """Section tokens out of a free-text field, in the order written.

    Intake fields are typed by people: "sections 20 and 24 PECA", "20, 24",
    "s.20". Whatever arrives, the generator emits canonical form -- so an
    operator's phrasing can never decide whether a citation is checkable.
    """
    out: list[str] = []
    for raw in _SECTION_TOKEN.findall(text or ""):
        token = normalise_section(raw)
        if _YEARLIKE.match(token) or token in out:
            continue
        out.append(token)
    return out


# A BARE defined short form takes no article: "of PECA", not "of the PECA".
#
# Deliberately does NOT match a short form carrying its year. "of the PPC 1860"
# is how that is written and how this module already emitted it; dropping the
# article there would churn every existing citation for no gain. The narrow case
# is the second-reference short form a document has just defined -- `("PECA")`.
_ACRONYM = re.compile(r"^[A-Z][A-Za-z.]{0,7}$")

# Everything a bare section list is allowed to contain besides the numbers:
# separators, section markers, and the short forms of statutes.
_LIST_FURNITURE = re.compile(
    r"\d+|[,&.\-–—/()\s]|\band\b|\bor\b|\bsections?\b|\bsecs?\b|\bss?\b|\bu/ss?\b"
    r"|\bPECA\b|\bPPC\b|\bCrPC\b|\bCPC\b|\bQSO\b|\bMFLO\b|\bETO\b|\bATA\b"
    r"|\bCNSA\b|\bNAO\b|\bof\b|\bthe\b",
    re.I)

# An explicit section marker: enough on its own to read the field as a citation.
_HAS_MARKER = re.compile(r"\b(?:sections?|secs?\.?|ss?\.|u/ss?\.?)\s*\d", re.I)


def section_list(text: str):
    """Section numbers if the field READS as a section list, else None.

    `None` means "this is not a citation -- show what the person wrote".

    WHY THIS IS NOT JUST `section_numbers`.

    `section_numbers` pulls digits out of anything, which is right when the
    caller already knows it is holding a citation. Applied to a free-text intake
    field it is dangerous: "he sent 500 messages" yields ["500"], and the
    complaint would then allege an offence under section 500 of an Act the
    complainant never mentioned. A fabricated citation is a worse failure than
    an unverifiable one -- the whole verifier exists to avoid exactly that.

    So a field counts as a section list only when it says so: either it carries
    a section marker ("s.20", "sections 20 and 24"), or it contains nothing but
    numbers, separators and statute short forms ("20, 24").
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if not _HAS_MARKER.search(raw) and _LIST_FURNITURE.sub("", raw).strip():
        return None                       # prose, not a list of sections
    return section_numbers(raw) or None


def cite(statute: str, sections, *, marker: str = "section") -> str:
    """The canonical citation string for one statute and its sections.

    >>> cite("Prevention of Electronic Crimes Act, 2016", ["20", "21", "24"])
    'sections 20, 21 and 24 of the Prevention of Electronic Crimes Act, 2016'

    Raises on an empty section list rather than emitting a bare Act name. A
    citation with no provision cannot be existence-checked, and returning one
    from a function called `cite` would quietly reintroduce exactly the gap this
    module exists to close -- see `tests/test_template_citation_binding.py`,
    which refuses to let a bare Act count as a citation.
    """
    tokens = [normalise_section(s) for s in sections if str(s).strip()]
    if not tokens:
        raise ValueError(
            f"cite({statute!r}) needs at least one section: a bare Act name is "
            f"not a citation and cannot be verified")
    if len(tokens) == 1:
        body = tokens[0]
    else:
        body = f"{', '.join(tokens[:-1])} and {tokens[-1]}"
    plural = "" if len(tokens) == 1 else "s"
    article = "" if _ACRONYM.match(statute.strip()) else "the "
    return f"{marker}{plural} {body} of {article}{statute}"


def cite_with_glosses(statute: str, pairs, *, marker: str = "section") -> str:
    """Canonical citation, with the per-section glosses moved AFTER it.

    >>> cite_with_glosses("PECA, 2016", [("20", "dignity"), ("21", "modesty")])
    'sections 20 and 21 of the PECA, 2016 (respectively: dignity; modesty)'

    The glosses are the reason the old fia_cybercrime string was unreadable:
    they sat BETWEEN the section numbers and broke the list apart. They are
    genuinely useful to a reader, so they are kept -- just moved to where they
    cannot interrupt the citation.
    """
    pairs = [(normalise_section(s), (g or "").strip()) for s, g in pairs]
    citation = cite(statute, [s for s, _ in pairs], marker=marker)
    described = [f"{s}: {g}" for s, g in pairs if g]
    if not described:
        return citation
    return f"{citation} ({'; '.join(described)})"
