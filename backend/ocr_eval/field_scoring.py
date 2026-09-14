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

#: CONSERVATIVE ADJUDICATION. Every annotated context token must survive for a
#: binding to be accepted. Not a similarity threshold on the VALUE -- the value
#: is still matched exactly; this governs only whether we can tell which slot an
#: exact value sits in.
#:
#: The threshold used to be ONE token, and one token is not evidence of a slot.
#: "compensation of 1000 rupees" annotated against "fine of 1000 rupees" matched
#: on `rupees` alone, binding the amount to a finding it does not belong to.
#: Context exists precisely to separate slots that share a value, so accepting a
#: fraction of it defeats the reason it is collected.
_REQUIRE_FULL_CONTEXT = True


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


def _is_boundary(char: str) -> bool:
    """Anything that is not part of a word or number ends a token.

    Whitespace ALONE was the rule, and it reported `1000` absent from
    "fine of 1000, rupees" -- which is how amounts are actually written. That
    understated the engine in the worst direction: a correctly read value looked
    like a missing one.

    Alphanumerics stay excluded so `1000` still does not match inside `21000`;
    loosening the boundary for punctuation must not loosen it for digits.
    """
    return not char.isalnum()


def _occurrences(needle: str, haystack: str) -> list[int]:
    """Start offsets of every whole-token occurrence of `needle`."""
    if not needle:
        return []
    found, start = [], 0
    while True:
        at = haystack.find(needle, start)
        if at < 0:
            return found
        before_ok = at == 0 or _is_boundary(haystack[at - 1])
        after = at + len(needle)
        after_ok = after >= len(haystack) or _is_boundary(haystack[after])
        if before_ok and after_ok:
            found.append(at)
        start = at + 1


def _words(text: str) -> list[str]:
    """Whitespace tokens with their outer punctuation removed, empties dropped.

    "fine of (1000) rupees" tokenises to `["fine", "of", "(1000)", "rupees"]`,
    so a context of "of" compared against the raw token "(" never matched and a
    correctly read value scored WRONG_FIELD. Bracketed and quoted values are
    ordinary in legal prose, so the comparison strips the punctuation rather than
    treating it as part of the word.
    """
    cleaned = (t.strip("".join(c for c in t if not c.isalnum())) for t in text.split())
    return [t for t in cleaned if t]


def _context_tokens(text: str, limit: int = 4) -> list[str]:
    return _words(text)[-limit:] if text else []


def _context_score(hyp: str, at: int, value: str,
                   before: str, after: str) -> tuple[int, int]:
    """(matched_context_tokens, available_context_tokens) around one occurrence."""
    want_before = _context_tokens(before)
    want_after = _words(after or "")[:4]
    available = len(want_before) + len(want_after)
    if available == 0:
        return 0, 0

    left = _words(hyp[:at])
    right = _words(hyp[at + len(value):])
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
    #: index -> (context signature, bound offset), for the ordering check below.
    bound: dict[int, tuple] = {}

    # Group by field so occurrence_index is resolved within its own field.
    by_field: dict[str, list[tuple[int, dict]]] = {}
    for index, token in enumerate(tokens or []):
        by_field.setdefault(str(token.get("field") or ""), []).append((index, token))

    # ONE OCCURRENCE BELONGS TO ONE ANNOTATION. `consumed` used to be reset per
    # field, so a single number on the page satisfied every field that described
    # it -- two fields, one occurrence, both MATCHED. It is shared across fields
    # now, and a later field finding its only occurrence already taken reports
    # MISSING, which is what actually happened: the page carried one of them.
    consumed: set[int] = set()

    for field_name, entries in by_field.items():
        entries.sort(key=lambda pair: int(pair[1].get("occurrence_index") or 0))

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
            if hit == available:
                # Every annotated context token survived. This is the only
                # evidence that establishes a slot.
                consumed.add(at)
                score.matched += 1
                score.outcomes.append(TokenOutcome(
                    index, kind, field_name, occurrence_index, MATCHED,
                    f"context matched {hit}/{available}"))
                bound[index] = (_signature(token, policy), at)
            elif hit == 0:
                # Nothing around the value resembles the annotation: the value
                # survived OCR and landed somewhere else entirely.
                score.wrong_field += 1
                score.outcomes.append(TokenOutcome(
                    index, kind, field_name, occurrence_index, WRONG_FIELD,
                    f"value present but no annotated context matched (0/{available})"))
            else:
                # PARTIAL. This is either the right slot with a misread context
                # word, or the wrong slot that happens to share one -- and
                # nothing here can separate those. Undecidable is the honest
                # answer; resolving it either way invents evidence.
                score.indeterminate += 1
                score.outcomes.append(TokenOutcome(
                    index, kind, field_name, occurrence_index, INDETERMINATE,
                    f"context matched {hit}/{available}; cannot establish the slot"))

    _demote_out_of_order(score, bound)
    return score


def _signature(token: dict, policy: str) -> tuple[str, str]:
    """The annotated context, normalised. Two fields with the same signature
    cannot be told apart by context alone."""
    return (normalise(str(token.get("context_before") or ""), policy),
            normalise(str(token.get("context_after") or ""), policy))


def _demote_out_of_order(score: FieldScore, bound: dict[int, tuple]) -> None:
    """Demote matches that sit in the wrong ORDER within a shared context.

    THE FAILURE THIS CLOSES. Two fields can declare identical surrounding text --
    "fine of X rupees" twice on one page. Context then identifies the KIND of
    slot but not WHICH one, so a hypothesis with the two amounts swapped matched
    both: each value really did appear with that context somewhere. That is the
    same "present, therefore correct" error the field metric exists to prevent,
    reappearing one level up.

    Reading order decides. Within one signature the annotated tokens are in
    document order, so the Nth annotated token must bind to the Nth occurrence in
    the hypothesis. A token whose position RANK differs from its annotation rank
    is in somebody else's slot.

    RANK EQUALITY RATHER THAN A LONGEST INCREASING RUN. The first version kept
    the longest increasing subsequence, which is too lenient and overstates
    accuracy in exactly the case this exists for: with two values swapped, LIS
    keeps one of them as MATCHED, though neither is in its own slot. On three
    tokens read as positions 1,3,2 it keeps two where only the first is right.
    Rank equality gives 0 and 1 respectively, which is what actually happened.
    """
    groups: dict[tuple, list[tuple[int, int]]] = {}
    for index, (signature, at) in bound.items():
        groups.setdefault(signature, []).append((index, at))

    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort()                       # annotation order
        order = sorted(range(len(members)), key=lambda i: members[i][1])
        rank = [0] * len(members)
        for position_rank, slot in enumerate(order):
            rank[slot] = position_rank

        for slot, (index, _) in enumerate(members):
            if rank[slot] == slot:
                continue
            outcome = next(o for o in score.outcomes if o.index == index)
            score.outcomes[score.outcomes.index(outcome)] = TokenOutcome(
                outcome.index, outcome.kind, outcome.field,
                outcome.occurrence_index, WRONG_FIELD,
                "value appears out of reading order for its shared context")
            score.matched -= 1
            score.wrong_field += 1


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
