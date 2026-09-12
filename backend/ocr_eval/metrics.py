"""Accuracy metrics. Pure functions over strings — no I/O, no engine, no config.

Kept separate from the harness so they can be tested against known strings whose
answers were worked out by hand. A metric implementation that is only ever
exercised through a pipeline tends to be verified against its own output.

NORMALISATION IS A MEASUREMENT DECISION, SO IT IS EXPLICIT

Every OCR benchmark silently normalises something — whitespace, case, Unicode
form — and the choice moves the score by whole percentage points. Urdu makes this
sharper than usual: the same word can be NFC or NFD, Arabic-Indic and
Extended-Arabic-Indic digits look identical to a reader and are different code
points, and a scan may or may not carry the zero-width joiners that Nastaliq
shaping uses. So normalisation is a named, recorded policy rather than a helpful
default buried in a helper, and the policy name is written into the report beside
the number it produced.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Zero-width and directional marks. Invisible to the human who wrote the
#: transcript, and therefore not something an engine should be scored on.
_INVISIBLE = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x061C,
     0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0xFEFF],
    None,
)

#: Arabic-Indic (٠-٩) and Extended Arabic-Indic (۰-۹) digits -> ASCII.
#: Applied only under the `aggressive` policy: whether "۲۰۲۴" and "2024" are the
#: same answer is a product question about what we do with the extracted text,
#: and the two policies let the report show both.
_DIGIT_MAP = {
    **{0x0660 + i: str(i) for i in range(10)},
    **{0x06F0 + i: str(i) for i in range(10)},
}

_WS = re.compile(r"\s+")

NORMALISATION_POLICIES = ("strict", "standard", "aggressive")


def normalise(text: str, policy: str = "standard") -> str:
    """Apply a NAMED normalisation policy.

    strict      — NFC only. Nothing else is touched, so the score reflects the
                  bytes as they came out of the engine.
    standard    — NFC, invisible marks stripped, whitespace runs collapsed,
                  ends trimmed. The default, because line-wrapping differences
                  between a transcript and an engine's output are an artefact of
                  layout rather than a recognition error.
    aggressive  — standard, plus case folding and Arabic-Indic digits mapped to
                  ASCII. Answers "did it read the right content" rather than
                  "did it reproduce the right string".
    """
    if policy not in NORMALISATION_POLICIES:
        raise ValueError(f"unknown normalisation policy: {policy!r}")

    out = unicodedata.normalize("NFC", text or "")
    if policy == "strict":
        return out

    out = out.translate(_INVISIBLE)
    out = _WS.sub(" ", out).strip()
    if policy == "standard":
        return out

    out = out.translate(_DIGIT_MAP)
    return out.casefold()


def _levenshtein(a: list, b: list) -> int:
    """Edit distance with two rows rather than a full matrix.

    A page of Urdu prose is a few thousand characters; the full matrix would be
    millions of cells per fixture, and this is called once per fixture per
    configuration.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,          # deletion
                current[j - 1] + 1,       # insertion
                previous[j - 1] + (ca != cb),  # substitution
            ))
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class ErrorRate:
    """A rate plus the counts it came from.

    The counts are kept because a rate alone cannot be re-aggregated: averaging
    per-page CERs weights a 20-character caption the same as a 3000-character
    judgment. Corpus-level figures are computed from summed edits and summed
    reference lengths, which is only possible if both survive.
    """
    rate: float | None
    edits: int
    reference_units: int

    def as_dict(self) -> dict:
        return {"rate": self.rate, "edits": self.edits,
                "reference_units": self.reference_units}


def character_error_rate(reference: str, hypothesis: str,
                         policy: str = "standard") -> ErrorRate:
    """CER = edit distance / reference length, in characters.

    An empty reference yields rate None, NOT 0.0 and not 1.0: with nothing to
    compare against there is no error rate, and inventing one would let empty
    ground truth quietly improve or wreck a corpus average.
    """
    ref = normalise(reference, policy)
    hyp = normalise(hypothesis, policy)
    if not ref:
        return ErrorRate(None, _levenshtein(list(ref), list(hyp)), 0)
    edits = _levenshtein(list(ref), list(hyp))
    return ErrorRate(edits / len(ref), edits, len(ref))


def word_error_rate(reference: str, hypothesis: str,
                    policy: str = "standard") -> ErrorRate:
    """WER = edit distance / reference length, in whitespace-delimited tokens.

    Whitespace tokenisation is a deliberate floor, not an oversight: Urdu word
    segmentation is genuinely ambiguous, and a smarter tokeniser would make the
    metric depend on a component with its own error rate. Splitting on
    whitespace is wrong in the same way for both strings.
    """
    ref = normalise(reference, policy).split()
    hyp = normalise(hypothesis, policy).split()
    if not ref:
        return ErrorRate(None, _levenshtein(ref, hyp), 0)
    edits = _levenshtein(ref, hyp)
    return ErrorRate(edits / len(ref), edits, len(ref))


def critical_token_matches(tokens: list[dict], hypothesis: str,
                           policy: str = "standard") -> dict:
    """Exact-substring presence of each declared critical token.

    Deterministic by construction: no fuzzy matching, no nearest-neighbour, no
    confidence. A section number is either reproduced or it is not, and a
    threshold here would be a way of scoring 'PPC 3O2' as a hit.

    Token VALUES are not returned — only ids, kinds and a boolean — because this
    output lands in a report and the values are document content.
    """
    hyp = normalise(hypothesis, policy)
    results = []
    matched = 0
    for index, token in enumerate(tokens or []):
        value = normalise(str(token.get("value") or ""), policy)
        found = bool(value) and value in hyp
        matched += found
        results.append({
            "index": index,
            "kind": str(token.get("kind") or "other"),
            "matched": found,
        })
    total = len(results)
    return {
        "total": total,
        "matched": matched,
        "rate": (matched / total) if total else None,
        "tokens": results,
    }


def output_length_ratio(reference: str, hypothesis: str,
                        policy: str = "standard") -> float | None:
    """How much of the expected text LENGTH was produced. Not completeness.

    Renamed from `extraction_coverage`, which oversold it: this compares string
    lengths and knows nothing about which pages were processed or whether any
    content is missing. An engine that returns a page of the right size made of
    the wrong characters scores 1.0 here. Page-level completeness is a different
    measurement entirely and is reported separately.

    Separate from CER because the two fail differently and the difference is the
    diagnosis: an engine that returns nothing scores CER 1.0 and coverage 0.0,
    while one that returns a full page of confident nonsense scores CER 1.0 and
    coverage ~1.0. The first is a plumbing problem, the second is a model
    problem, and one number cannot tell them apart.

    Capped at 1.0 — over-production is an error CER already counts, and letting
    coverage exceed 1.0 would make a hallucinating engine look better than a
    correct one.
    """
    ref = normalise(reference, policy)
    hyp = normalise(hypothesis, policy)
    if not ref:
        return None
    return min(1.0, len(hyp) / len(ref))


def aggregate_error_rate(rates: list[ErrorRate]) -> ErrorRate:
    """Corpus-level rate from summed edits over summed reference units.

    NOT the mean of the per-page rates. See `ErrorRate` — a micro-average
    weights each page by its length, which is what "the error rate of this
    corpus" means; a macro-average answers a different question and is usually
    quoted by accident.
    """
    edits = sum(r.edits for r in rates)
    units = sum(r.reference_units for r in rates)
    return ErrorRate((edits / units) if units else None, edits, units)
