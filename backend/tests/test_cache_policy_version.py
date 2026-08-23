"""Cached answers must not outlive the decision logic that produced them.

A cache hit routes straight to the finalizer, skipping the Decision Engine
entirely. So when arbitration changes, entries written under the old logic keep
being served as though nothing happened — and they are served at their ORIGINAL
confidence, which makes them indistinguishable from a fresh answer.

This was observed, not hypothesised. After the inverted lexical signal was fixed
and the answerability gate added, "What is the current stamp duty rate for
property transfer in Gilgit-Baltistan?" still answered at 0.85 confidence from
cache. The remedy at the time was a manual purge — a step that works exactly
once and is forgotten on the deployment where it matters.

The cache already versioned on embedding model, chunking strategy and
per-collection ingestion hashes. Decision policy is the fourth dimension, and it
is the one that governs whether an answer should have been given at all.
"""
import time

import pytest

from app.ai import cache


def _entry(**overrides):
    """A well-formed entry under the current versions."""
    base = {
        "payload":                   {"answer": "cached", "is_grounded": True},
        "embedding_model_version":   cache.EMBEDDING_MODEL_VERSION,
        "chunking_strategy_version": cache.CHUNKING_STRATEGY_VERSION,
        "decision_policy_version":   cache.DECISION_POLICY_VERSION,
        "collection_versions":       {},
        "cached_at":                 time.time(),
    }
    base.update(overrides)
    return base


# ── the new dimension ────────────────────────────────────────────────────────

def test_an_entry_from_a_different_policy_is_invalid():
    stale = _entry(decision_policy_version="v1")
    assert cache._valid(stale, ttl=600, current_col_versions={}) is False


def test_an_entry_written_before_policy_versioning_is_invalid():
    """Pre-existing entries carry no policy tag at all. They must be rejected,
    not admitted for want of a field to compare."""
    untagged = _entry()
    del untagged["decision_policy_version"]
    assert cache._valid(untagged, ttl=600, current_col_versions={}) is False


def test_a_current_entry_is_still_valid():
    assert cache._valid(_entry(), ttl=600, current_col_versions={}) is True


def test_new_entries_are_stamped_with_the_policy_version():
    built = cache._build_entry({"answer": "x"}, None, {})
    assert built["decision_policy_version"] == cache.DECISION_POLICY_VERSION


def test_bumping_the_version_invalidates_everything_written_before(monkeypatch):
    """The property that matters: changing the constant is sufficient. No purge
    script, no manual step, no dependence on remembering."""
    written = cache._build_entry({"answer": "x"}, None, {})
    assert cache._valid(written, ttl=600, current_col_versions={}) is True

    monkeypatch.setattr(cache, "DECISION_POLICY_VERSION", "v3")
    assert cache._valid(written, ttl=600, current_col_versions={}) is False


# ── the other dimensions still hold ──────────────────────────────────────────

@pytest.mark.parametrize("field,bad", [
    ("embedding_model_version",   "some/other/model"),
    ("chunking_strategy_version", "v0"),
])
def test_the_existing_version_dimensions_are_unaffected(field, bad):
    assert cache._valid(_entry(**{field: bad}), ttl=600, current_col_versions={}) is False


def test_a_stale_collection_still_invalidates():
    entry = _entry(collection_versions={"civil_collection": "hash_a"})
    assert cache._valid(entry, ttl=600,
                        current_col_versions={"civil_collection": "hash_b"}) is False


def test_ttl_is_still_enforced():
    old = _entry(cached_at=time.time() - 10_000)
    assert cache._valid(old, ttl=600, current_col_versions={}) is False


def test_the_policy_version_is_a_non_empty_string():
    """A None or empty default would make every comparison vacuously equal."""
    assert isinstance(cache.DECISION_POLICY_VERSION, str)
    assert cache.DECISION_POLICY_VERSION
