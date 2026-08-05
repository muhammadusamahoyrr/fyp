"""The seed query set is a paper artifact — its shape is what makes the
evaluation splits reproducible, so it gets pinned like any other fixture.

No network here: this imports the module and inspects the constant only.
"""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_traffic.py"


def _load():
    spec = importlib.util.spec_from_file_location("seed_traffic", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def seed():
    return _load()


def test_every_split_needed_for_the_benchmark_is_present(seed):
    """Drop any of these and the corresponding evaluation split is empty."""
    assert set(seed.KINDS) == {
        "answerable", "out_of_jurisdiction", "unanswerable",
        "code_switched", "adversarial", "off_topic",
    }


def test_no_split_is_left_with_a_single_example(seed):
    counts = {k: sum(1 for kind, _, _ in seed.QUERIES if kind == k) for k in seed.KINDS}
    thin = {k: n for k, n in counts.items() if n < 2}
    assert not thin, f"splits too thin to be meaningful: {thin}"


def test_queries_are_unique(seed):
    """A duplicate would be labeled twice and skew the verdict distribution."""
    texts = [q for _, q, _ in seed.QUERIES]
    assert len(texts) == len(set(texts))


def test_the_abstention_splits_are_not_outnumbered(seed):
    """If easy positives dominate, the labeling pass comes back ~all 'correct'
    and demonstrates nothing about abstention."""
    answerable = sum(1 for k, _, _ in seed.QUERIES if k == "answerable")
    others     = len(seed.QUERIES) - answerable
    assert others >= answerable, (
        f"{answerable} answerable vs {others} everything-else — "
        "the set is too easy to evaluate abstention"
    )


def test_every_query_carries_routing_metadata(seed):
    valid_types = {"civil", "criminal", "family", "constitutional"}
    valid_provs = {"punjab", "sindh", "kpk", "balochistan", "federal"}
    for kind, text, meta in seed.QUERIES:
        assert text.strip(), f"empty query in {kind}"
        assert meta.get("case_type") in valid_types, f"bad case_type in {kind}: {text[:40]}"
        assert meta.get("province") in valid_provs, f"bad province in {kind}: {text[:40]}"


def test_code_switched_split_actually_contains_non_english(seed):
    """Roman Urdu alone would not exercise the Urdu-script normalisation path."""
    texts = [q for k, q, _ in seed.QUERIES if k == "code_switched"]
    assert any(any("؀" <= ch <= "ۿ" for ch in t) for t in texts), \
        "no Urdu-script query — the transliteration path goes untested"
