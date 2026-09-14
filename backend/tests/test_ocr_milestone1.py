"""Milestone 1 offline preparation: slices, field scoring, budget, inventory.

NO PROVIDER IS CONTACTED IN THIS FILE. Every "response" is a dict constructed in
the test. That is the point: budget accounting has to be correct before a single
paid call is issued, and the failures it guards against (a ceiling passed by
concurrent calls, a timeout billed but unrecorded) are precisely the ones that are
expensive to discover live.

The three properties under test that failed silently in review:

  * PRESENCE IS NOT CORRECTNESS. `critical_token_matches` scores a perfect result
    for output whose values are swapped between fields. That is reproduced here as
    a regression pin, and the field-aware metric is asserted to catch it.
  * MISSING IS NOT PASSING. A slice with no fixtures must report NOT_EVALUATED and
    must not contribute to an overall pass.
  * UNKNOWN IS NOT ZERO. A call that returns no usage keeps its reservation.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import pytest

from ocr_eval import budget as B
from ocr_eval import field_scoring as F
from ocr_eval import inventory as I
from ocr_eval import metrics as M
from ocr_eval import slices as S


# ══════════════════════════════════════════════════════════════════════════════
# Presence is not correctness
# ══════════════════════════════════════════════════════════════════════════════

REF = "fine 1000 imprisonment 3 years"
SWAPPED = "fine 3 imprisonment 1000 years"

_TOKENS = [
    {"kind": "amount", "value": "1000", "field": "fine_amount",
     "occurrence_index": 0, "context_before": "fine", "context_after": "imprisonment"},
    {"kind": "amount", "value": "3", "field": "imprisonment_years",
     "occurrence_index": 0, "context_before": "imprisonment", "context_after": "years"},
]


def test_the_presence_metric_scores_swapped_values_as_perfect():
    """REGRESSION PIN, not an aspiration.

    This documents a real property of the shipped metric so nobody re-derives it
    in a report. If this ever starts failing, `critical_token_matches` changed
    meaning and every number produced with it needs re-reading.
    """
    presence = M.critical_token_matches(_TOKENS, SWAPPED)
    assert presence["rate"] == 1.0, "the presence metric is expected to be fooled here"
    assert M.character_error_rate(REF, SWAPPED).rate > 0, "CER does see the difference"


def test_field_scoring_catches_the_swap_the_presence_metric_misses():
    score = F.score_fields(_TOKENS, SWAPPED)

    assert score.matched == 0
    assert score.wrong_field == 2
    assert score.accuracy == 0.0


def test_field_scoring_accepts_a_correct_reading():
    score = F.score_fields(_TOKENS, REF)

    assert score.matched == 2
    assert score.wrong_field == 0
    assert score.accuracy == 1.0


def test_a_value_absent_entirely_is_missing_not_wrong_field():
    score = F.score_fields(_TOKENS, "fine 1000 imprisonment unknown years")

    outcomes = {o.field: o.outcome for o in score.outcomes}
    assert outcomes["fine_amount"] == F.MATCHED
    assert outcomes["imprisonment_years"] == F.MISSING


def test_an_unannotated_token_is_indeterminate_not_a_free_pass():
    """Presence alone cannot establish a field. Scoring it as a match would
    reintroduce the exact defect this metric exists to fix."""
    bare = [{"kind": "amount", "value": "1000", "field": "fine_amount",
             "occurrence_index": 0}]

    score = F.score_fields(bare, SWAPPED)

    assert score.indeterminate == 1
    assert score.matched == 0
    assert score.decidable == 0
    assert score.accuracy is None, "no decidable tokens must not read as 0.0"


def test_repeated_fields_bind_by_occurrence_rather_than_collapsing():
    """Three fines must not all be satisfied by one number."""
    tokens = [
        {"kind": "amount", "value": "500", "field": "fine_amount",
         "occurrence_index": 0, "context_before": "first fine", "context_after": "rupees"},
        {"kind": "amount", "value": "700", "field": "fine_amount",
         "occurrence_index": 1, "context_before": "second fine", "context_after": "rupees"},
    ]
    both = "first fine 500 rupees and second fine 700 rupees"

    assert F.score_fields(tokens, both).matched == 2


def test_one_occurrence_cannot_satisfy_two_annotated_slots():
    """The same value annotated twice, present once. The second slot must not
    re-consume the first occurrence — otherwise a document listing two identical
    fines scores full marks when the engine read only one of them."""
    tokens = [
        {"kind": "amount", "value": "500", "field": "fine_amount",
         "occurrence_index": 0, "context_before": "first fine", "context_after": "rupees"},
        {"kind": "amount", "value": "500", "field": "fine_amount",
         "occurrence_index": 1, "context_before": "second fine", "context_after": "rupees"},
    ]
    only_one = "first fine 500 rupees and second fine omitted"

    score = F.score_fields(tokens, only_one)

    assert score.matched == 1, "one occurrence satisfied both annotated slots"
    assert score.missing == 1


def test_aggregate_sums_counts_rather_than_averaging_rates():
    """A page with one token must not weigh as much as a page with twenty."""
    small = F.score_fields(_TOKENS[:1], REF)                 # 1/1
    big = F.score_fields(_TOKENS, SWAPPED)                   # 0/2

    agg = F.aggregate([small, big])

    assert agg["decidable"] == 3
    assert agg["matched"] == 1
    assert agg["accuracy"] == pytest.approx(1 / 3)
    assert agg["accuracy"] != pytest.approx((1.0 + 0.0) / 2), "that is a mean of rates"


# ══════════════════════════════════════════════════════════════════════════════
# Slice keys: missing is not passing
# ══════════════════════════════════════════════════════════════════════════════

def test_every_required_slice_has_an_exact_machine_readable_key():
    keys = [s.key for s in S.REQUIRED_SLICES]

    assert len(keys) == len(set(keys)), "duplicate slice key"
    assert len(keys) == 6
    for key in keys:
        language, _, capture = key.partition(":")
        assert language in {"eng", "urd", "mixed"}, key
        assert capture in {"searchable", "scanned", "photograph"}, key


def test_a_slice_key_is_derived_from_the_fixture_not_written_by_hand():
    @dataclass
    class Fake:
        language: str
        capture: str

    assert S.fixture_slice_key(Fake("URD", "Photograph")) == "urd:photograph"
    assert S.fixture_slice_key({"language": "eng", "capture": "searchable"}) == "eng:searchable"


def test_a_missing_slice_reports_not_evaluated_and_blocks_an_overall_pass():
    good = {"holdout_documents": 2, "holdout_pages": 4, "critical_tokens": 12, "decidable_tokens": 12,
            "cer": 0.0, "wer": 0.0, "field_accuracy": 1.0}
    # Five of six slices perfect; one absent entirely.
    results = {s.key: dict(good) for s in S.REQUIRED_SLICES[:-1]}

    report = S.evaluate(results)

    missing = [s for s in report["slices"] if s["key"] == S.REQUIRED_SLICES[-1].key][0]
    assert missing["verdict"] == S.NOT_EVALUATED
    assert report["overall"] == S.NOT_EVALUATED, "five perfect slices must not carry a sixth"
    assert report["evaluated"] == 5


def test_thin_evidence_reports_not_evaluated_rather_than_a_flattering_pass():
    """One page can score 0.0. Reporting that as a pass would be the most
    misleading thing this harness could do."""
    thin = {"holdout_documents": 1, "holdout_pages": 1, "critical_tokens": 1, "decidable_tokens": 1,
            "cer": 0.0, "wer": 0.0, "field_accuracy": 1.0}

    verdict = S.evaluate_slice(S.REQUIRED_SLICES[0], **thin)

    assert verdict["verdict"] == S.NOT_EVALUATED
    assert len(verdict["reasons"]) == 4  # + decidable_tokens


def test_presence_only_runs_cannot_claim_field_correctness():
    measured = {"holdout_documents": 2, "holdout_pages": 4, "critical_tokens": 12, "decidable_tokens": 12,
                "cer": 0.0, "wer": 0.0, "field_accuracy": None}

    verdict = S.evaluate_slice(S.REQUIRED_SLICES[0], **measured)

    assert verdict["verdict"] == S.NOT_EVALUATED
    assert "field accuracy not computed" in verdict["reasons"][0]


def test_a_breach_of_any_single_threshold_fails_the_slice():
    measured = {"holdout_documents": 2, "holdout_pages": 4, "critical_tokens": 12, "decidable_tokens": 12,
                "cer": 0.99, "wer": 0.0, "field_accuracy": 1.0}

    assert S.evaluate_slice(S.REQUIRED_SLICES[0], **measured)["verdict"] == S.FAIL


def test_all_six_slices_satisfied_is_the_only_overall_pass():
    good = {"holdout_documents": 2, "holdout_pages": 4, "critical_tokens": 12, "decidable_tokens": 12,
            "cer": 0.0, "wer": 0.0, "field_accuracy": 1.0}
    # `approved=True` because the registry's own numbers are proposals: an
    # unapproved gate must never return PASS. See
    # test_ocr_milestone1_hardening.test_unapproved_thresholds_never_return_pass.
    report = S.evaluate({s.key: dict(good) for s in S.REQUIRED_SLICES},
                        approved=True)

    assert report["overall"] == S.PASS
    assert report["evaluated"] == report["required"] == 6


def test_a_fixture_in_an_unthresholded_slice_is_surfaced_not_ignored():
    good = {"holdout_documents": 2, "holdout_pages": 4, "critical_tokens": 12, "decidable_tokens": 12,
            "cer": 0.0, "wer": 0.0, "field_accuracy": 1.0}
    results = {s.key: dict(good) for s in S.REQUIRED_SLICES}
    results["urd:handwritten_scrawl"] = dict(good)

    report = S.evaluate(results)

    assert report["unslotted_slice_keys"] == ["urd:handwritten_scrawl"]


# ══════════════════════════════════════════════════════════════════════════════
# Budget: unknown is not zero
# ══════════════════════════════════════════════════════════════════════════════

PRICES = B.Prices(input_per_million=1.0, output_per_million=4.0)


def _ledger(ceiling=1.0, max_attempts=3, max_output=1000):
    return B.BudgetLedger(ceiling_usd=ceiling, prices=PRICES,
                          max_output_tokens=max_output, max_attempts=max_attempts)


def test_price_unit_conversion_is_per_million_tokens():
    """A stray factor of 1000 here is a 1000x accounting error."""
    assert PRICES.cost(1_000_000, 0) == pytest.approx(1.0)
    assert PRICES.cost(0, 1_000_000) == pytest.approx(4.0)
    assert PRICES.cost(500_000, 250_000) == pytest.approx(0.5 + 1.0)
    assert PRICES.cost(1, 1) == pytest.approx((1 + 4) / 1_000_000)


def test_a_reservation_is_worst_case_including_every_permitted_retry():
    ledger = _ledger(max_attempts=3, max_output=1000)
    one_attempt = PRICES.cost(1000, 1000)

    reservation = ledger.reserve("c1", input_tokens=1000)

    assert reservation.reserved == pytest.approx(one_attempt * 3)


def test_reserving_before_dispatch_is_what_the_ceiling_is_enforced_against():
    """A reservation occupies budget with nothing confirmed and no response back."""
    one = PRICES.cost(1_000_000, 1000) * 3          # worst case for one call
    ledger = _ledger(ceiling=one * 1.5)             # room for one, not two

    ledger.reserve("c1", input_tokens=1_000_000)

    assert ledger.committed == pytest.approx(one)
    assert ledger.confirmed_cost == 0.0, "nothing has been confirmed yet"
    with pytest.raises(B.BudgetExceeded):
        ledger.reserve("c2", input_tokens=1_000_000)


def test_two_concurrent_reservations_cannot_both_pass_one_budget(monkeypatch):
    """The failure this module exists for. Both callers check at once; the budget
    covers exactly one.

    THE RACE IS FORCED, NOT HOPED FOR. An earlier version of this test started two
    threads at a barrier and passed even with the lock removed — the critical
    section is a few bytecodes and the GIL hid the window. Mutation testing caught
    that, so the window is widened deliberately: `committed` is patched to sleep
    between the read and the write that follows it. With the lock, the second
    thread blocks at acquisition and never observes the stale total. Without it,
    both read zero and both reserve.
    """
    one = PRICES.cost(1000, 1000) * 3
    ledger = _ledger(ceiling=one * 1.5)          # room for one, not two

    real_committed = type(ledger).committed.fget

    def slow_committed(self):
        value = real_committed(self)
        time.sleep(0.05)                          # the window a lock must close
        return value

    monkeypatch.setattr(type(ledger), "committed", property(slow_committed))

    outcomes: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def attempt(call_id):
        barrier.wait()
        try:
            ledger.reserve(call_id, input_tokens=1000)
            result = "reserved"
        except B.BudgetExceeded:
            result = "refused"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=attempt, args=(f"c{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["refused", "reserved"], (
        "two concurrent callers both passed a budget that covers one")
    assert real_committed(ledger) <= ledger.ceiling_usd


def test_settling_releases_unused_retry_headroom():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    reserved = ledger.committed

    actual = ledger.record_attempt("c1", input_tokens=1000, output_tokens=10)
    ledger.settle("c1")

    assert actual < reserved
    assert ledger.confirmed_cost == pytest.approx(actual)
    assert ledger.unknown_exposure == 0.0
    assert ledger.unreconciled_calls == 0


def test_retries_are_charged_for_every_attempt_issued():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)

    once = PRICES.cost(1000, 50)
    for _ in range(3):
        ledger.record_attempt("c1", input_tokens=1000, output_tokens=50)
    actual = ledger.settle("c1")

    assert actual == pytest.approx(once * 3), "a retried call is billed three times"


def test_a_timeout_without_usage_keeps_its_charge():
    """THE UNKNOWN-COST RULE. A timed-out attempt was probably billed; treating
    the missing usage as zero understates spend exactly when a run is going
    wrong.

    The charge is ONE ATTEMPT at worst case, not the whole call's three-attempt
    reservation: one attempt timed out, and billing the other two before they
    happen would overstate spend as badly as dropping this one understates it.
    """
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    # Input AND the output cap: the prompt was certainly sent.
    one_attempt_worst_case = PRICES.cost(1000, 1000)

    ledger.record_unknown_attempt("c1", reason="read timeout")

    assert ledger.confirmed_cost == 0.0
    assert ledger.unknown_exposure == pytest.approx(one_attempt_worst_case)
    assert ledger.unreconciled_calls == 1


def test_unknown_exposure_still_blocks_further_spending():
    one = PRICES.cost(1000, 1000) * 3
    ledger = _ledger(ceiling=one * 1.5)
    ledger.reserve("c1", input_tokens=1000)
    ledger.record_unknown_attempt("c1")

    with pytest.raises(B.BudgetExceeded):
        ledger.reserve("c2", input_tokens=1000)


def test_an_unknown_call_can_be_reconciled_from_the_billing_console():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    ledger.record_unknown_attempt("c1")

    ledger.reconcile_unknown("c1", input_tokens=1000, output_tokens=20)

    assert ledger.unknown_exposure == 0.0
    assert ledger.unreconciled_calls == 0
    assert ledger.confirmed_cost == pytest.approx(PRICES.cost(1000, 20))


def test_a_run_with_unknown_exposure_reports_estimated_not_final():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    ledger.record_unknown_attempt("c1")
    ledger.settle("c1")          # closed, but its timed-out attempt is unresolved

    report = ledger.as_report_dict()

    assert report["status"] == "ESTIMATED"
    assert report["calls_unreconciled"] == 1
    assert report["confirmed_cost"] == 0.0
    assert report["unknown_exposure"] > 0
    assert "confirmed_cost" in report and "unknown_exposure" in report, \
        "the two figures are reported separately and never summed into one headline"


def test_a_fully_reconciled_run_reports_final():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    ledger.record_attempt("c1", input_tokens=1000, output_tokens=10)
    ledger.settle("c1")

    assert ledger.as_report_dict()["status"] == "FINAL"


def test_release_is_only_for_calls_that_never_dispatched():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)

    ledger.release("c1")

    assert ledger.unknown_exposure == 0.0
    assert ledger.confirmed_cost == 0.0


def test_a_call_id_cannot_be_reserved_or_settled_twice():
    ledger = _ledger()
    ledger.reserve("c1", input_tokens=1000)
    with pytest.raises(B.BudgetError):
        ledger.reserve("c1", input_tokens=1000)

    ledger.record_attempt("c1", input_tokens=1000, output_tokens=10)
    ledger.settle("c1")
    with pytest.raises(KeyError):
        ledger.settle("c1")


def test_a_simulated_run_with_fake_responses_never_exceeds_the_ceiling():
    """End to end over fabricated provider responses: successes, a retry, and a
    timeout that returns no usage."""
    ledger = _ledger(ceiling=5.0)
    fake_responses = [
        {"id": "p1", "input": 1200, "output": 300, "attempts": 1, "usage": True},
        {"id": "p2", "input": 1500, "output": 400, "attempts": 2, "usage": True},
        {"id": "p3", "input": 1100, "output": 0, "attempts": 3, "usage": False},
        {"id": "p4", "input": 900, "output": 250, "attempts": 1, "usage": True},
    ]

    for response in fake_responses:
        ledger.reserve(response["id"], input_tokens=response["input"])
        if response["usage"]:
            for _ in range(response["attempts"]):
                ledger.record_attempt(response["id"],
                                      input_tokens=response["input"],
                                      output_tokens=response["output"])
            ledger.settle(response["id"])
        else:
            ledger.record_unknown_attempt(response["id"], reason="timeout")
            ledger.settle(response["id"])

    report = ledger.as_report_dict()
    assert report["calls_settled"] == 4      # every call is settled, including
    #                                          the one whose attempt timed out
    assert report["calls_unreconciled"] == 1
    assert report["status"] == "ESTIMATED"
    assert ledger.committed <= ledger.ceiling_usd


# ══════════════════════════════════════════════════════════════════════════════
# Inventory: observed, never claimed
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FakeFixture:
    fixture_id: str
    language: str
    capture: str
    document_family: str
    split: str
    expected_page_count: int
    critical_tokens: tuple = ()
    transcript_path: object = None


def test_an_empty_fixture_tree_reports_zero_and_not_ready(tmp_path):
    tree = I.scan_fixture_tree(tmp_path)
    report = I.build_inventory([])

    assert tree["files"] == 0
    assert report["total_pages"] == 0
    assert report["ready"] is False
    assert report["slices_ready"] == 0
    assert len(report["slices"]) == 6, "every required slice is listed at zero, not omitted"


def test_a_missing_fixture_directory_is_reported_rather_than_raising(tmp_path):
    tree = I.scan_fixture_tree(tmp_path / "nope")

    assert tree["exists"] is False
    assert tree["files"] == 0


def test_the_scan_counts_only_renderable_files(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "b.png").write_bytes(b"x")
    (tmp_path / "README.md").write_text("not a fixture")
    (tmp_path / ".gitignore").write_text("*")

    tree = I.scan_fixture_tree(tmp_path)

    assert tree["files"] == 2
    assert tree["by_suffix"] == {".pdf": 1, ".png": 1}


def test_a_family_split_across_train_and_holdout_is_reported_as_a_leak():
    fixtures = [
        FakeFixture("f1", "urd", "scanned", "lahore_orders_2019", "train", 2),
        FakeFixture("f2", "urd", "scanned", "lahore_orders_2019", "holdout", 2),
    ]

    report = I.family_assignments(fixtures)

    assert report["leaks"] == ["lahore_orders_2019"]


def test_families_confined_to_one_side_are_not_a_leak():
    fixtures = [
        FakeFixture("f1", "urd", "scanned", "family_a", "train", 2),
        FakeFixture("f2", "urd", "scanned", "family_b", "holdout", 2),
    ]

    assert I.family_assignments(fixtures)["leaks"] == []


def test_inventory_names_each_shortfall_rather_than_only_failing():
    fixtures = [FakeFixture("f1", "urd", "scanned", "fam", "holdout", 1)]

    report = I.build_inventory(fixtures)
    row = [s for s in report["slices"] if s["key"] == "urd:scanned"][0]

    assert row["status"] == S.NOT_EVALUATED
    assert any("holdout documents" in s for s in row["shortfalls"])
    assert any("holdout pages" in s for s in row["shortfalls"])
    assert any("critical tokens" in s for s in row["shortfalls"])


def test_the_rendered_inventory_states_not_ready_when_nothing_exists(tmp_path):
    text = I.render_text(I.build_inventory([]), I.scan_fixture_tree(tmp_path),
                         I.family_assignments([]))

    assert "NOT READY" in text
    assert "0/6" in text
