"""Synthetic traffic is audited, counted for warmup, and never labellable.

Threshold warmup needs ~1000 queries and the labelling pool is built from the
SAME provenance records. So traffic generated to warm the threshold arrives in
the annotators' queue looking exactly like a user's question — which would
manufacture, with our own tooling, the "evaluation questions are
developer-authored or LLM-generated" threat the paper already concedes.

The flag is written at record time because it cannot be recovered afterwards:
once real and synthetic turns are mixed with nothing to tell them apart, every
turn in the pool inherits the doubt.
"""
import inspect

import pytest

from app.services import labeling_service as ls
from app.services import provenance_service as ps


def _src(fn):
    return inspect.getsource(fn)


# ── written at record time ───────────────────────────────────────────────────

def test_the_record_carries_the_flag():
    rec = ps.build_record({}, "sess", "user", "req")
    assert rec["is_synthetic"] is False


def test_it_defaults_to_real_when_nobody_thinks_about_it(monkeypatch):
    """A driver that never heard of the flag must produce REAL records, not
    synthetic ones — the failure mode of the opposite default is silently
    discarding genuine traffic."""
    monkeypatch.delenv(ps.SYNTHETIC_ENV_VAR, raising=False)
    assert ps.build_record({}, "s", "u", "r")["is_synthetic"] is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_the_environment_variable_marks_traffic(monkeypatch, value):
    monkeypatch.setenv(ps.SYNTHETIC_ENV_VAR, value)
    assert ps.build_record({}, "s", "u", "r")["is_synthetic"] is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "  "])
def test_other_values_leave_traffic_real(monkeypatch, value):
    monkeypatch.setenv(ps.SYNTHETIC_ENV_VAR, value)
    assert ps.build_record({}, "s", "u", "r")["is_synthetic"] is False


def test_state_overrides_the_environment(monkeypatch):
    """For a driver running mixed traffic in one process."""
    monkeypatch.setenv(ps.SYNTHETIC_ENV_VAR, "1")
    assert ps.build_record({"is_synthetic": False}, "s", "u", "r")["is_synthetic"] is False
    monkeypatch.delenv(ps.SYNTHETIC_ENV_VAR, raising=False)
    assert ps.build_record({"is_synthetic": True}, "s", "u", "r")["is_synthetic"] is True


def test_the_schema_version_was_bumped():
    """Consumers must be able to tell rows that predate the field from rows
    that carry it."""
    assert ps.SCHEMA_VERSION == "prov-v2"


# ── gated out of the pool ────────────────────────────────────────────────────

def test_the_labelling_pool_excludes_synthetic_turns():
    assert ls._ANSWER_TURNS_ONLY["is_synthetic"] == {"$ne": True}


def test_the_filter_is_not_equal_true_not_equal_false():
    """`{"is_synthetic": False}` matches only rows carrying the field, so every
    turn recorded before it existed — all of them real — would vanish from the
    pool. That is the same trap as _HUMAN_ONLY in agreement.py."""
    assert ls._ANSWER_TURNS_ONLY["is_synthetic"] != {"$eq": False}
    assert ls._ANSWER_TURNS_ONLY["is_synthetic"] != False  # noqa: E712


@pytest.mark.parametrize("fn", [
    ls.export_retrieval_dataset,
    ls.export_calibration_pairs,
])
def test_the_exports_re_assert_the_exclusion(fn):
    """Defence in depth. The pool already excludes synthetic turns, but these
    two functions BUILD the published eval set and the calibration pairs, so a
    synthetic record arriving by any other route — a hand-written label, a
    restored backup — must not become a benchmark question or a coverage
    guarantee."""
    assert '"is_synthetic": {"$ne": True}' in _src(fn)


def test_the_unlabelled_queue_inherits_the_pool_filter():
    assert "_ANSWER_TURNS_ONLY" in _src(ls.unlabeled_records)


# ── still counted, still audited ─────────────────────────────────────────────

def test_synthetic_turns_are_still_written_not_dropped():
    """They are audit records and they are what warmup counts. Excluding them
    from LABELLING is not the same as refusing to record them."""
    src = _src(ps.record_answer)
    assert "insert_one" in src
    assert "is_synthetic" not in src  # no early return that skips the write


def test_the_count_is_reported_rather_than_hidden():
    """Labelable and warmup counts moving apart is correct behaviour, and an
    operator watching warmup needs to see both."""
    assert '"synthetic_excluded"' in _src(ls.stats)
