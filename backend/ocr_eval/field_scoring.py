"""Field-aware critical token scoring, and the adjudication rules behind it.

WHY THE EXISTING METRIC IS NOT ENOUGH

`metrics.critical_token_matches` checks whole-identifier PRESENCE. Run against a
constructed pair it reports a perfect score for output whose meaning is inverted:

    reference : fine 1000 imprisonment 3 years
    hypothesis: fine 3 imprisonment 1000 years
    critical_token_presence -> 1.0   (both values present)
    character_error_rate    -> 0.267

That metric is doing exactly what it documents -- deterministic presence with
occurrence counting, no fuzzy matching. It was never designed to establish that a
value landed in the right slot. On a legal document that distinction is the whole
point: a fine of 1,000 and imprisonment for 3 years is a different order from a fine
of 3 and imprisonment for 1,000 years.

So presence is kept, renamed honestly, and a second metric is added that binds a
value to its FIELD.

HOW BINDING IS DECIDED WITHOUT A LAYOUT MODEL

The harness scores plain text against plain text; it has no bounding boxes for the
hypothesis. Binding is therefore decided by CONTEXT: the annotator records the
verbatim reference text immediately before and after the value, and a hypothesis
occurrence counts for that field only if the surrounding text matches.

This is deliberately conservative. Where context is too weak to decide, the
occurrence is adjudicated INDETERMINATE rather than guessed, and indeterminate
outcomes are reported separately instead of being folded into either side. A metric
that resolves its own ambiguity in silence is how the presence metric came to be
misread as correctness.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from ocr_eval.metrics import normalise

#: Per-token outcomes.
MATCHED = "matched"              # right value, right field, right occurrence
WRONG_FIELD = "wrong_field"      # value present, but bound to a different field
MISSING = "missing"              # value absent from the hypothesis entirely
INDETERMINATE = "indeterminate"  # present, but context cannot decide the binding

#: How much of the annotated context must survive for a binding to be accepted.
#: Not a similarity threshold on the VALUE -- the value is still matched exactly.
#: This governs only whether we can tell which slot an exact value sits in.
_MIN_CONTEXT_TOKENS = 1


@dataclass(frozen=True)
class TokenOutcome:
    index: int
    kind: str
    field: str
    occurrence_index: int
    outcome: str
    detail: str = ""

    def as_report_dict(self) -> dict:
        """Report-safe: no token VALUES, which are document content."""
        return {
            "index": self.index, "kind": self.kind, "field": self.field,
            "occurrence_index": self.occurrence_index,
            "outcome": self.outcome, "detail": self.detail,
        }


@dataclass
class FieldScore:
    total: int = 0
    matched: int = 0
    wrong_field: int = 0
    missing: int = 0
    indeterminate: int = 0
    outcomes: list[TokenOutcome] = dc_field(default_factory=list)

    @property
    def decidable(self) -> int:
        """Tokens whose binding could be adjudicated at all."""
        return self.total - self.indeterminate

    @property
    def accuracy(self) -> float | None:
        """Matched over DECIDABLE tokens, or None when nothing was decidable.

        Indeterminate tokens are excluded from the denominator rather than
        counted as failures: they are a shortfall in the ANNOTATION, not in the
        engine, and charging the engine for them would make a thin manifest look
        like a bad model. They are reported separately so a slice with many of
        them is visibly under-annotated.

        None rather than 0.0 when nothing is decidable -- "we could not tell" is
        not "it got everything wrong".
        """
        if self.decidable <= 0:
            return None
        return self.matched / self.decidable

    def as_report_dict(self) -> dict:
        return {
            "total": self.total,
            "matched": self.matched,
            "wrong_field": self.wrong_field,
            "missing": self.missing,
            "indeterminate": self.indeterminate,
            "decidable": self.decidable,
            "accuracy": self.accuracy,
            "outcomes": [o.as_report_dict() for o in self.outcomes],
        }


def _occurrences(needle: str, haystack: str) -> list[int]:
    """Start offsets of every whole-token occurrence of `needle`."""
    if not needle:
        return []
    found, start = [], 0
    while True:
        at = haystack.find(needle, start)
        if at < 0:
            return found
        before_ok = at == 0 or haystack[at - 1] == " "
        after = at + len(needle)
        after_ok = after >= len(haystack) or haystack[after] == " "
        if before_ok and after_ok:
            found.append(at)
        start = at + 1


def _context_tokens(text: str, limit: int = 4) -> list[str]:
    return [t for t in text.split() if t][-limit:] if text else []


def _context_score(hyp: str, at: int, value: str,
                   before: str, after: str) -> tuple[int, int]:
    """(matched_context_tokens, available_context_tokens) around one occurrence."""
    want_before = _context_tokens(before)
    want_after = [t for t in (after or "").split() if t][:4]
    available = len(want_before) + len(want_after)
    if available == 0:
        return 0, 0

    left = hyp[:at].split()
    right = hyp[at + len(value):].split()
    hit = 0
    for offset, token in enumerate(reversed(want_before), start=1):
        if len(left) >= offset and left[-offset] == token:
            hit += 1
    for offset, token in enumerate(want_after):
        if len(right) > offset and right[offset] == token:
            hit += 1
    return hit, available


def score_fields(tokens: list[dict], hypothesis: str,
                 policy: str = "standard") -> FieldScore:
    """Adjudicate each annotated token against the hypothesis.

    ADJUDICATION RULES, in order:

    1. Value absent entirely           -> MISSING.
    2. Value present, no context annotated
                                       -> INDETERMINATE. Presence alone cannot
                                          establish the field, and this is exactly
                                          the case the presence metric mis-reports.
    3. Value present at an occurrence whose surrounding text matches the annotated
       context                         -> MATCHED.
    4. Value present, context annotated, but no occurrence matches it
                                       -> WRONG_FIELD. The value survived OCR and
                                          landed somewhere else, which is the
                                          swapped-value failure.
    5. Context annotated but too weak to separate occurrences
                                       -> INDETERMINATE.

    Occurrence index is honoured: the Nth annotated occurrence of a field is
    matched against the Nth context-matching occurrence in the hypothesis, so a
    judgment listing three fines cannot satisfy all three with one number.
    """
    hyp = normalise(hypothesis, policy)
    score = FieldScore()

    # Group by field so occurrence_index is resolved within its own field.
    by_field: dict[str, list[tuple[int, dict]]] = {}
    for index, token in enumerate(tokens or []):
        by_field.setdefault(str(token.get("field") or ""), []).append((index, token))

    for field_name, entries in by_field.items():
        entries.sort(key=lambda pair: int(pair[1].get("occurrence_index") or 0))
        consumed: set[int] = set()

        for index, token in entries:
            score.total += 1
            kind = str(token.get("kind") or "other")
            occurrence_index = int(token.get("occurrence_index") or 0)
            value = normalise(str(token.get("value") or ""), policy)
            before = normalise(str(token.get("context_before") or ""), policy)
            after = normalise(str(token.get("context_after") or ""), policy)

            positions = _occurrences(value, hyp)
            if not positions:
                score.missing += 1
                score.outcomes.append(TokenOutcome(
                    index, kind, field_name, occurrence_index, MISSING,
                    "value not present in hypothesis"))
                continue

            if not before and not after:
                score.indeterminate += 1
                score.outcomes.append(TokenOutcome(
                    index, kind, field_name, occurrence_index, INDETERMINATE,
                    "no context annotated; presence cannot establish the field"))
                continue

            ranked = []
            for at in positions:
                if at in consumed:
                    continue
                hit, available = _context_score(hyp, at, value, before, after)
                ranked.append((hit, available, at))

            best = max(ranked, default=None)
            if best is None:
                # Every occurrence already bound to an earlier annotation of this
                # field: the hypothesis has fewer occurrences than the reference.
                score.missing += 1
                score.outcomes.append(TokenOutcome(
                    index, kind, field_name, occurrence_index, MISSING,
                    "fewer occurrences in hypothesis than annotated"))
                continue

            hit, available, at = best
            if available == 0:
                score.indeterminate += 1
                score.outcomes.append(TokenOutcome(
                    index, kind, field_name, occurrence_index, INDETERMINATE,
                    "annotated context carried no usable tokens"))
                continue
            if hit >= _MIN_CONTEXT_TOKENS:
                consumed.add(at)
                score.matched += 1
                score.outcomes.append(TokenOutcome(
                    index, kind, field_name, occurrence_index, MATCHED,
                    f"context matched {hit}/{available}"))
            else:
                score.wrong_field += 1
                score.outcomes.append(TokenOutcome(
                    index, kind, field_name, occurrence_index, WRONG_FIELD,
                    f"value present but context matched {hit}/{available}"))

    return score


def aggregate(scores: list[FieldScore]) -> dict:
    """Corpus field accuracy from SUMMED counts, never a mean of per-page rates.

    Same reasoning as `metrics.aggregate_error_rate`: averaging percentages weights
    a page with one annotated token equally with a page carrying twenty.
    """
    total = sum(s.total for s in scores)
    matched = sum(s.matched for s in scores)
    wrong = sum(s.wrong_field for s in scores)
    missing = sum(s.missing for s in scores)
    indeterminate = sum(s.indeterminate for s in scores)
    decidable = total - indeterminate
    return {
        "total": total,
        "matched": matched,
        "wrong_field": wrong,
        "missing": missing,
        "indeterminate": indeterminate,
        "decidable": decidable,
        "accuracy": (matched / decidable) if decidable > 0 else None,
    }
