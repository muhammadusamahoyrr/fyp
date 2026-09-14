"""Regressions found in committed revision 240d3bb, reproduced before fixing.

Every test here failed against 240d3bb. They are written first, and separately
from `test_ocr_milestone1.py`, so the reproduction is on record rather than
implied by a green suite afterwards.

WHAT WENT WRONG, IN ONE SENTENCE EACH

  * Two fields sharing the same annotated context both "matched" when their
    values were swapped -- the exact failure the field metric was added to catch,
    reappearing one level up.
  * A value followed by a comma was reported MISSING, because occurrence
    matching required whitespace on both sides.
  * Indeterminate tokens were excluded from the denominator, so a slice with one
    decidable token out of twelve scored 1.0 and PASSED.
  * NaN scores passed every threshold, because every comparison against NaN is
    False.
  * `Fixture` never carried `document_family` or `split`, so a real manifest
    loaded with the schema's required fields lost them, every fixture counted as
    neither train nor holdout, and a family split across both sides could not be
    detected at all.
  * A timed-out attempt's retained charge was ERASED when a later attempt of the
    same call succeeded; retries were billed as N copies of one attempt; and a
    reservation for possibly-dispatched work could be released outright.

No provider is contacted. Everything here is arithmetic, string handling and
local file IO.
"""
from __future__ import annotations

import json
import math

import pytest

from ocr_eval import budget as B
from ocr_eval import field_scoring as F
from ocr_eval import inventory as I
from ocr_eval import slices as S
from ocr_eval.manifest import load_manifest


# ══════════════════════════════════════════════════════════════════════════════
# 1. Shared context and punctuation boundaries
# ══════════════════════════════════════════════════════════════════════════════

_SHARED = [
    {"kind": "amount", "value": "1000", "field": "fine_first",
     "occurrence_index": 0, "context_before": "fine of", "context_after": "rupees"},
    {"kind": "amount", "value": "2000", "field": "fine_second",
     "occurrence_index": 0, "context_before": "fine of", "context_after": "rupees"},
]


def test_two_fields_sharing_context_do_not_both_match_when_swapped():
    """240d3bb scored this 2/2, accuracy 1.0.

    Both fields declare the same surrounding words, so context alone cannot tell
    them apart -- and the metric happily bound each value to whichever occurrence
    carried that context, which is every occurrence. Order has to decide.
    """
    swapped = "fine of 2000 rupees and fine of 1000 rupees"

    score = F.score_fields(_SHARED, swapped)

    assert score.matched == 0, "swapped values matched under a shared context"
    assert score.accuracy == 0.0


def test_two_fields_sharing_context_still_match_when_correct():
    """The counterweight: the ordering rule must not reject a correct reading."""
    correct = "fine of 1000 rupees and fine of 2000 rupees"

    score = F.score_fields(_SHARED, correct)

    assert score.matched == 2
    assert score.accuracy == 1.0


@pytest.mark.parametrize("hypothesis", [
    "fine of 1000, rupees",
    "fine of 1000. rupees",
    "fine of (1000) rupees",
    "fine of 1000; rupees",
])
def test_a_value_next_to_punctuation_is_found(hypothesis):
    """240b reported MISSING for all of these.

    Occurrence matching required a space on both sides, so an amount followed by
    a comma -- which is how amounts are actually written -- read as absent. That
    understates the engine and, worse, understates it in the direction that makes
    a bad engine look like a missing value.
    """
    token = [{"kind": "amount", "value": "1000", "field": "fine",
              "occurrence_index": 0, "context_before": "fine of",
              "context_after": "rupees"}]

    score = F.score_fields(token, hypothesis)

    assert score.outcomes[0].outcome == F.MATCHED, hypothesis


def test_a_value_embedded_in_a_longer_number_is_still_not_a_match():
    """The boundary must loosen for punctuation without loosening for digits:
    `1000` must not match inside `21000`."""
    token = [{"kind": "amount", "value": "1000", "field": "fine",
              "occurrence_index": 0, "context_before": "fine of",
              "context_after": "rupees"}]

    score = F.score_fields(token, "fine of 21000 rupees")

    assert score.outcomes[0].outcome != F.MATCHED


# ══════════════════════════════════════════════════════════════════════════════
# 1b. Conservative adjudication: one matching context token is not enough
# ══════════════════════════════════════════════════════════════════════════════

def test_a_binding_needs_all_its_annotated_context_not_one_token_of_it():
    """The threshold was ONE token, so a value whose preceding context is
    entirely wrong still matched on a single word from the other side.

    "compensation of 1000 rupees" and "fine of 1000 rupees" are different
    findings. Matching on `rupees` alone binds the amount to whichever slot the
    annotator happened to describe second.
    """
    token = [{"kind": "amount", "value": "1000", "field": "compensation",
              "occurrence_index": 0, "context_before": "compensation of",
              "context_after": "rupees"}]

    score = F.score_fields(token, "fine of 1000 rupees")

    assert score.outcomes[0].outcome != F.MATCHED


def test_a_partially_matching_context_is_indeterminate_not_a_match():
    """Some context matched and some did not. That can be a wrong slot OR a
    correct slot whose surrounding words the engine misread, and the two are not
    distinguishable from here -- so it is adjudicated as undecidable rather than
    resolved in either direction."""
    token = [{"kind": "amount", "value": "1000", "field": "fine",
              "occurrence_index": 0, "context_before": "the total fine of",
              "context_after": "rupees only"}]

    score = F.score_fields(token, "the total fine of 1000 rupees payable")

    assert score.outcomes[0].outcome == F.INDETERMINATE
    assert score.decidable == 0


def test_a_fully_matching_context_still_matches():
    """The counterweight. Conservative must not mean useless."""
    token = [{"kind": "amount", "value": "1000", "field": "fine",
              "occurrence_index": 0, "context_before": "total fine of",
              "context_after": "rupees only"}]

    score = F.score_fields(token, "the total fine of 1000 rupees only payable")

    assert score.outcomes[0].outcome == F.MATCHED


def test_one_hypothesis_occurrence_cannot_satisfy_two_different_fields():
    """`consumed` was reset per field, so a single occurrence in the hypothesis
    was handed to every field that described it. Two fields both scored MATCHED
    against one number on the page."""
    tokens = [
        {"kind": "amount", "value": "50", "field": "fine_amount",
         "occurrence_index": 0, "context_before": "sum of", "context_after": "rupees"},
        {"kind": "amount", "value": "50", "field": "costs_amount",
         "occurrence_index": 0, "context_before": "sum of", "context_after": "rupees"},
    ]

    score = F.score_fields(tokens, "sum of 50 rupees")

    assert score.matched <= 1, "one occurrence satisfied two distinct fields"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Indeterminate tokens must not buy acceptance
# ══════════════════════════════════════════════════════════════════════════════

def test_a_slice_decided_on_one_token_out_of_twelve_is_not_evaluated():
    """240b: eleven unannotated tokens dropped out of the denominator, the
    twelfth matched, the slice scored 1.0 and PASSED.

    The minimum exists to stop a slice being judged on almost nothing. Applying
    it to ANNOTATED tokens while scoring only DECIDABLE ones let exactly that
    happen through the gap between the two counts.
    """
    verdict = S.evaluate_slice(
        S.REQUIRED_SLICES[0], holdout_documents=2, holdout_pages=4,
        critical_tokens=12, decidable_tokens=1,
        cer=0.0, wer=0.0, field_accuracy=1.0)

    assert verdict["verdict"] == S.NOT_EVALUATED
    assert any("decidable" in reason for reason in verdict["reasons"])


def test_a_slice_with_enough_decidable_tokens_still_passes():
    verdict = S.evaluate_slice(
        S.REQUIRED_SLICES[0], holdout_documents=2, holdout_pages=4,
        critical_tokens=12, decidable_tokens=12,
        cer=0.0, wer=0.0, field_accuracy=1.0)

    assert verdict["verdict"] == S.PASS


def test_the_aggregate_reports_how_much_it_could_not_decide():
    """An operator has to be able to see that a score rests on a thin base."""
    undecidable = [{"kind": "amount", "value": str(900 + i), "field": f"f{i}",
                    "occurrence_index": 0} for i in range(11)]
    decidable = [{"kind": "amount", "value": "77", "field": "ok",
                  "occurrence_index": 0, "context_before": "total",
                  "context_after": "only"}]
    hypothesis = " ".join(str(900 + i) for i in range(11)) + " total 77 only"

    agg = F.aggregate([F.score_fields(undecidable + decidable, hypothesis)])

    assert agg["indeterminate"] == 11
    assert agg["decidable"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 3. Non-finite and invalid numbers
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -0.5])
def test_a_non_finite_or_negative_score_is_never_a_pass(bad):
    """240b: NaN passed every threshold, because `nan > 0.02` is False. A metric
    that cannot be compared is missing evidence, not a good result."""
    verdict = S.evaluate_slice(
        S.REQUIRED_SLICES[0], holdout_documents=2, holdout_pages=4,
        critical_tokens=12, decidable_tokens=12,
        cer=bad, wer=0.0, field_accuracy=1.0)

    assert verdict["verdict"] != S.PASS


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 1.5])
def test_a_non_finite_or_out_of_range_field_accuracy_is_never_a_pass(bad):
    verdict = S.evaluate_slice(
        S.REQUIRED_SLICES[0], holdout_documents=2, holdout_pages=4,
        critical_tokens=12, decidable_tokens=12,
        cer=0.0, wer=0.0, field_accuracy=bad)

    assert verdict["verdict"] != S.PASS


@pytest.mark.parametrize("tokens", [float("nan"), float("inf"), -5, "12"])
def test_invalid_token_counts_are_refused_rather_than_priced(tokens):
    """240b returned `nan`, `inf` and NEGATIVE costs for these."""
    prices = B.Prices(1.0, 4.0)

    with pytest.raises((ValueError, TypeError)):
        prices.cost(tokens, 0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_an_unusable_price_or_ceiling_is_refused_at_construction(bad):
    """A NaN ceiling accepted every reservation, because the comparison was
    always False. A budget that cannot be exceeded is not a budget."""
    with pytest.raises(ValueError):
        B.Prices(bad, 4.0)
    with pytest.raises(ValueError):
        B.BudgetLedger(ceiling_usd=bad, prices=B.Prices(1.0, 4.0),
                       max_output_tokens=1000)


# ══════════════════════════════════════════════════════════════════════════════
# 4. The real manifest loader
# ══════════════════════════════════════════════════════════════════════════════

def _write_manifest(root, fixtures):
    (root / "pages").mkdir(parents=True, exist_ok=True)
    (root / "transcripts").mkdir(parents=True, exist_ok=True)
    entries = []
    import hashlib
    for spec in fixtures:
        body = f"page {spec['fixture_id']}".encode()
        (root / "pages" / f"{spec['fixture_id']}.txt").write_bytes(body)
        (root / "transcripts" / f"{spec['fixture_id']}.txt").write_bytes(body)
        entries.append({
            "fixture_id": spec["fixture_id"],
            "path": f"pages/{spec['fixture_id']}.txt",
            "sha256": hashlib.sha256(body).hexdigest(),
            "document_type": "court_order",
            "language": spec["language"],
            "script_style": "latin",
            "capture": spec["capture"],
            "writing": "printed",
            "rotation": "none",
            "expected_page_count": 1,
            "transcript_path": f"transcripts/{spec['fixture_id']}.txt",
            "document_family": spec["family"],
            "split": spec["split"],
            "critical_tokens": [
                {"kind": "section", "value": "Section 12",
                 "field": "section_number", "occurrence_index": 0},
            ],
            "de_identified": True,
            "consent": True,
        })
    manifest = {
        "schema_version": 2, "dataset_id": "regress",
        "created_utc": "2026-09-14T00:00:00Z",
        # Dataset-level attestations are OBJECTS carrying who and how; the
        # per-fixture keys above are the bare `true`. Two different shapes, and
        # the schema is right to insist -- "de-identification fails one page at
        # a time" is its own comment on the fixture key.
        "de_identified": {"confirmed": True, "confirmed_by": "regression-suite",
                          "method": "public documents, nothing to remove"},
        "consent": {"confirmed": True, "basis": "public domain court records"},
        "fixtures": entries,
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_a_loaded_fixture_keeps_its_family_and_split(tmp_path):
    """240b: the schema REQUIRED these, and `Fixture` did not carry them. They
    were validated on the way in and dropped on the way out -- so the split the
    manifest declared could not be read back by anything."""
    path = _write_manifest(tmp_path, [
        {"fixture_id": "f1", "language": "urd", "capture": "scanned",
         "family": "lahore_2019", "split": "holdout"},
    ])

    loaded = load_manifest(path)

    assert loaded.ok, loaded.issues_as_dicts()
    fixture = loaded.fixtures[0]
    assert fixture.document_family == "lahore_2019"
    assert fixture.split == "holdout"


def test_a_family_on_both_sides_of_the_split_blocks_readiness(tmp_path):
    """240b: `build_inventory` never consulted `family_assignments`, so a leak
    was reported in one function and ignored by the one that decides."""
    path = _write_manifest(tmp_path, [
        {"fixture_id": "a", "language": "urd", "capture": "scanned",
         "family": "shared", "split": "train"},
        {"fixture_id": "b", "language": "urd", "capture": "scanned",
         "family": "shared", "split": "holdout"},
    ])
    loaded = load_manifest(path)

    report = I.build_inventory(loaded.fixtures)

    assert report["ready"] is False
    assert report["leaks"] == ["shared"]


def test_the_loader_inventory_and_verdict_agree_end_to_end(tmp_path):
    """THE COMPOSED TEST. Real manifest file -> real loader -> inventory ->
    slice verdict.

    Each piece was unit-tested against hand-built objects and passed; the seam
    between them was where the family and split vanished. This drives the whole
    chain from a file on disk.
    """
    path = _write_manifest(tmp_path, [
        {"fixture_id": "t1", "language": "urd", "capture": "scanned",
         "family": "fam_train", "split": "train"},
        {"fixture_id": "h1", "language": "urd", "capture": "scanned",
         "family": "fam_hold", "split": "holdout"},
    ])
    loaded = load_manifest(path)
    assert loaded.ok, loaded.issues_as_dicts()

    inventory = I.build_inventory(loaded.fixtures)
    row = next(r for r in inventory["slices"] if r["key"] == "urd:scanned")

    # The split survived the loader and reached the inventory.
    assert row["train_documents"] == 1
    assert row["holdout_documents"] == 1
    assert inventory["leaks"] == []

    # And the thin evidence is reported as NOT_EVALUATED, not as a pass.
    verdict = S.evaluate(
        {"urd:scanned": {"holdout_documents": row["holdout_documents"],
                         "holdout_pages": row["holdout_pages"],
                         "critical_tokens": row["critical_tokens"],
                         "decidable_tokens": row["critical_tokens"],
                         "cer": 0.0, "wer": 0.0, "field_accuracy": 1.0}})

    assert verdict["overall"] == S.NOT_EVALUATED
    assert row["status"] == S.NOT_EVALUATED


# ══════════════════════════════════════════════════════════════════════════════
# 4b. Versioning: old manifests are refused, not silently reinterpreted
# ══════════════════════════════════════════════════════════════════════════════

def test_a_manifest_written_against_the_old_schema_is_refused(tmp_path):
    """`document_family`, `split`, `field` and `occurrence_index` became
    REQUIRED. A v1 manifest has none of them, and reading one as though it did
    would silently produce a dataset with no split and no field annotation --
    which scores, and scores meaninglessly.

    `schema_version` is a `const`, so the refusal is structural.
    """
    path = _write_manifest(tmp_path, [
        {"fixture_id": "f1", "language": "urd", "capture": "scanned",
         "family": "fam", "split": "holdout"},
    ])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 1                      # the superseded version
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_manifest(path)

    assert not loaded.ok
    assert any("schema_version" in issue["detail"]
               for issue in loaded.issues_as_dicts())


def test_the_harness_version_records_that_scoring_changed():
    """A score is only comparable to another score from the same ruler. The
    adjudication rules, the metric set and the budget model all changed, so the
    version has to move or two incomparable numbers look alike."""
    from ocr_eval import HARNESS_VERSION

    assert HARNESS_VERSION != "1.0.0"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Budget: per-attempt accounting, retained unknowns, guarded release
# ══════════════════════════════════════════════════════════════════════════════

PRICES = B.Prices(1.0, 4.0)


def _ledger(ceiling=100.0):
    return B.BudgetLedger(ceiling_usd=ceiling, prices=PRICES,
                          max_output_tokens=1000, max_attempts=3)


def test_a_timed_out_attempt_is_still_charged_after_a_later_attempt_succeeds():
    """240b ERASED it. The timeout's worst-case exposure disappeared the moment
    the retry succeeded, so a run that timed out repeatedly and eventually
    succeeded reported only the successful attempt."""
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    ledger.record_unknown_attempt("c1", reason="read timeout")
    retained = ledger.unknown_exposure
    assert retained > 0

    ledger.record_attempt("c1", input_tokens=1000, output_tokens=10)
    ledger.settle("c1")

    assert ledger.unknown_exposure == pytest.approx(retained), \
        "the timed-out attempt's charge was dropped"
    assert ledger.confirmed_cost > 0
    assert ledger.unreconciled_calls == 1


def test_each_attempt_is_priced_on_its_own_usage():
    """240b multiplied ONE attempt's usage by the attempt count, so three
    attempts with different sizes were billed as three copies of the last."""
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)

    ledger.record_attempt("c1", input_tokens=1000, output_tokens=500)
    ledger.record_attempt("c1", input_tokens=1200, output_tokens=20)
    ledger.settle("c1")

    expected = PRICES.cost(1000, 500) + PRICES.cost(1200, 20)
    assert ledger.confirmed_cost == pytest.approx(expected)


def test_a_dispatched_call_cannot_be_released():
    """`release` exists for work that provably never left the process. 240b let
    it free a reservation for a call that may already have been billed."""
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    ledger.mark_dispatched("c1")

    with pytest.raises(B.BudgetError):
        ledger.release("c1")

    assert ledger.committed > 0


def test_an_undispatched_call_can_still_be_released():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)

    ledger.release("c1")

    assert ledger.committed == 0
    assert ledger.unreconciled_calls == 0


def test_an_unknown_attempt_is_charged_for_its_input_as_well_as_its_output():
    """The exposure was `cost(0, max_output)` -- ZERO input tokens.

    A timed-out attempt sent its whole prompt; a page image is the overwhelming
    majority of the cost of an OCR call. Charging only the output cap understates
    the exposure by roughly the thing being measured.
    """
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=100_000)

    charged = ledger.record_unknown_attempt("c1", reason="timeout")

    assert charged == pytest.approx(PRICES.cost(100_000, 1000)), \
        "unknown exposure ignored the input tokens that were certainly sent"


def test_a_call_still_open_is_reported_incomplete_not_final():
    """FINAL meant "nothing unreconciled", which was true before a single call
    had settled. A run reporting FINAL while work is still in flight invites the
    number to be quoted as the total."""
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    ledger.record_attempt("c1", input_tokens=1000, output_tokens=10)

    report = ledger.as_report_dict()

    assert report["calls_open"] == 1
    assert report["status"] == "INCOMPLETE"


def test_a_settled_and_reconciled_run_is_final():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    ledger.record_attempt("c1", input_tokens=1000, output_tokens=10)
    ledger.settle("c1")

    assert ledger.as_report_dict()["status"] == "FINAL"


@pytest.mark.parametrize("bad", [0, -1, 2.5, float("nan"), "3", True])
def test_max_attempts_must_be_a_positive_whole_number(bad):
    """Zero attempts makes `worst_case` zero, so every reservation costs nothing
    and the ceiling stops binding entirely."""
    with pytest.raises(ValueError):
        B.BudgetLedger(ceiling_usd=10.0, prices=PRICES,
                       max_output_tokens=1000, max_attempts=bad)


def test_a_call_cannot_record_more_attempts_than_it_reserved_for():
    """The reservation covers `max_attempts`. Recording more spends budget that
    was never reserved, which is how a retry loop escapes its own ceiling."""
    ledger = B.BudgetLedger(ceiling_usd=100.0, prices=PRICES,
                            max_output_tokens=1000, max_attempts=2)
    ledger.reserve("c1", input_tokens=1000)
    ledger.record_attempt("c1", input_tokens=1000, output_tokens=10)
    ledger.record_unknown_attempt("c1", reason="timeout")

    with pytest.raises(B.BudgetError):
        ledger.record_attempt("c1", input_tokens=1000, output_tokens=10)


def test_reconciling_an_unknown_attempt_moves_it_into_confirmed():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    ledger.record_unknown_attempt("c1", reason="timeout")
    ledger.settle("c1")
    assert ledger.unreconciled_calls == 1

    ledger.reconcile_unknown("c1", input_tokens=1000, output_tokens=7)

    assert ledger.unknown_exposure == 0.0
    assert ledger.unreconciled_calls == 0
    assert ledger.confirmed_cost == pytest.approx(PRICES.cost(1000, 7))
    assert ledger.as_report_dict()["status"] == "FINAL"
