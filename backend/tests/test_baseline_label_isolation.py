"""A machine-authored baseline label can never become evaluation data.

The baseline exists to smoke-test the labelling pipeline and to report how a
machine annotator compares against the humans. Stored in the same collection as
human judgements, it has two ways to corrupt the very numbers it is meant to
sanity-check:

  1. On a turn no human has reached, a singly-labelled turn is authoritative by
     rule, so the baseline would flow into the calibration set and the conformal
     coverage guarantee would be self-certified by the system under evaluation.

  2. On a turn a human does reach, the baseline counts as a second annotator, so
     Krippendorff's alpha would report machine-human concordance while claiming
     to report agreement between two independent people.

Both are silent. Nothing downstream would look wrong. These tests pin the
exclusion at the one place every consumer reads through.
"""
import inspect

import pytest

from app.services import agreement as ag
from app.services import labeling_service as ls


def _src(fn):
    return inspect.getsource(fn)


# ── the flag exists and is recorded ──────────────────────────────────────────

def test_save_label_accepts_and_records_the_baseline_flag():
    assert "is_baseline" in inspect.signature(ls.save_label).parameters
    assert '"is_baseline":     is_baseline' in _src(ls.save_label)


def test_a_baseline_label_still_requires_attribution():
    """An anonymous machine label is worse than an anonymous human one: nobody
    can later tell it apart from the humans it sits beside."""
    assert "labeler is required" in _src(ls.save_label)


# ── the single choke point ───────────────────────────────────────────────────

def test_labels_by_request_excludes_the_baseline_by_default():
    params = inspect.signature(ag._labels_by_request).parameters
    assert "include_baseline" in params
    assert params["include_baseline"].default is False


def test_the_human_only_filter_is_a_not_equal_not_a_false_match():
    """`{"is_baseline": False}` would match only rows that carry the field, so
    every human label written before the flag existed would vanish from
    agreement and from the authoritative set. `$ne: True` keeps them."""
    assert ag._HUMAN_ONLY == {"is_baseline": {"$ne": True}}


@pytest.mark.parametrize("fn", [
    ag.agreement_report,
    ag.disagreements,
    ag.authoritative_labels,
])
def test_every_agreement_consumer_reads_through_the_choke_point(fn):
    """None of these may query the labels collection directly — that is how the
    filter gets bypassed six months from now."""
    src = _src(fn)
    assert "_labels_by_request()" in src
    assert "get_retrieval_labels_col()" not in src


@pytest.mark.parametrize("fn", [
    ls.export_retrieval_dataset,
    ls.export_calibration_pairs,
])
def test_the_exports_inherit_the_exclusion_through_authoritative_labels(fn):
    """Both exports feed calibration and the conformal threshold. Neither may
    read raw labels."""
    src = _src(fn)
    assert "authoritative_labels" in src
    assert "get_retrieval_labels_col()" not in src


# ── progress reporting ───────────────────────────────────────────────────────

def test_coverage_counts_human_labels_only():
    """A machine baseline over the whole pool would otherwise report the set
    finished while not one human judgement exists."""
    src = _src(ls.stats)
    assert '"request_id", {"is_baseline": {"$ne": True}}' in src


def test_the_baseline_count_is_reported_separately_rather_than_hidden():
    assert '"baseline_labeled"' in _src(ls.stats)


def test_pooling_depth_ignores_the_baseline():
    """Metrics are reported only to the depth annotators actually looked. A
    machine pooling deeper or shallower than the humans must not move that
    bound."""
    src = _src(ls.stats)
    depth_block = src[src.index("depths = ["):]
    assert '{"is_baseline": {"$ne": True}}' in depth_block


def test_the_unscoped_work_queue_ignores_baseline_rows():
    """Scoped to a labeler, baseline rows are that labeler's own work. Unscoped,
    they must not empty the queue for the first human who opens the tool."""
    assert '{"is_baseline": {"$ne": True}}' in _src(ls.labeled_request_ids)
