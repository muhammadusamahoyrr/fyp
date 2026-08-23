"""Labels are per (request_id, labeler), and every consumer respects that.

The original schema keyed labels on request_id alone. A second annotator
therefore OVERWROTE the first, which makes inter-annotator agreement
unmeasurable — and unmeasured agreement is the standard reason a legal-NLP
evaluation set is not believed.

Changing the key is not enough on its own: every consumer that assumed one
label per turn becomes a silent bug. These tests pin the three that did.
"""
import inspect

import pytest

from app.services import labeling_service as ls


def _src(fn):
    return inspect.getsource(fn)


# ── the key ──────────────────────────────────────────────────────────────────

def test_the_upsert_is_keyed_on_request_and_labeler():
    """Keyed on request_id alone, the second annotator's judgement replaces the
    first and the disagreement disappears before anyone can measure it."""
    src = _src(ls.save_label)
    assert '{"request_id": request_id, "labeler": labeler}' in src


def test_an_unattributed_label_is_rejected():
    assert "labeler is required" in _src(ls.save_label)


def test_the_adjudication_flag_is_recorded():
    assert '"is_adjudication": is_adjudication' in _src(ls.save_label)


def test_the_schema_version_was_bumped():
    """Consumers must be able to tell v1 single-annotator rows apart from v2."""
    assert ls.SCHEMA_VERSION == "label-v2"


# ── consumers that assumed one label per turn ────────────────────────────────

def test_the_work_queue_is_scoped_to_the_annotator():
    """Unscoped, annotator two opens the tool, is told there is nothing left,
    and the set can never be double-labelled."""
    assert "labeler" in inspect.signature(ls.unlabeled_records).parameters
    assert "labeled_request_ids(labeler)" in _src(ls.unlabeled_records)


def test_progress_counts_distinct_turns_not_label_documents():
    """Counting documents once a turn carries two annotators plus an
    adjudication reports 300% coverage and stops the annotators early.

    Scoped to the LABELS collection: counting provenance documents is correct
    and stays."""
    src = _src(ls.stats)
    assert 'get_retrieval_labels_col().distinct("request_id")' in src
    assert "get_retrieval_labels_col().count_documents({})" not in src


@pytest.mark.parametrize("fn", [ls.export_retrieval_dataset,
                                ls.export_calibration_pairs])
def test_exports_go_through_the_resolution_rule(fn):
    """A dict comprehension over the raw collection keeps whichever document
    the cursor yielded last, making the exported set depend on iteration order
    and discarding the disagreement entirely."""
    src = _src(fn)
    assert "authoritative_labels" in src
    assert 'd["request_id"]: d' not in src


def test_verdict_counts_come_from_the_authoritative_set():
    """Otherwise a disputed turn is counted twice, under two verdicts."""
    assert "authoritative_labels" in _src(ls.stats)


def test_stats_surfaces_the_resolution_summary():
    """Excluded-unresolved turns must be visible, not silently dropped."""
    assert '"resolution":' in _src(ls.stats)


# ── unchanged invariants ─────────────────────────────────────────────────────

def test_the_four_verdicts_are_intact():
    """The selective-prediction confusion matrix needs all four; collapsing the
    two refusal kinds is what makes abstention look free."""
    assert set(ls.VERDICTS) == {
        "correct", "incorrect", "correct_refusal", "wrong_refusal"
    }


def test_retrieval_faults_stay_out_of_the_labelling_pool():
    """A refusal caused by a retrieval error is not an abstention decision —
    the system never saw the evidence. Labelling it would put an outage into
    the risk-coverage curve."""
    assert ls._ANSWER_TURNS_ONLY["arbitration.source"] == {"$ne": "error"}


def test_labeled_depth_is_still_recorded():
    """Ranks below the pool are unjudged, not known-irrelevant."""
    assert '"labeled_depth"' in _src(ls.save_label)
