"""Statute disambiguation for everyday-language queries.

"Can a tenant be evicted without notice in Punjab?" retrieved the Punjab Tenancy
Act 1887 — AGRICULTURAL tenancy, cultivators and land — rather than the Punjab
Rented Premises Act 2009, which governs houses and shops and answers the
question. The right statute ranked sixth, losing by 1.5% of cosine similarity.

Both laws are genuinely about tenants and eviction, so this is an ambiguity of
scope, not a vocabulary gap. It got WORSE as the corpus grew: ingesting
provincial law introduced the lexically similar competitor.

Query expansion was measured and rejected: appending "rented premises eviction
landlord" lifted the target 0.845 -> 0.860 but left it at rank 6, because the
competitors rose too, and it pushed CrPC from rank 3 to 5 on another query.
"""
import pytest

from app.ai.nodes.retrieval_node import _apply_topic_rules
from app.ai.pipelines.topic_rules import (
    BOOST,
    PENALTY,
    active_rules,
    statute_weight,
)

RENTED = "Punjab Rented Premises Act 2009"
TENANCY = "Punjab Tenancy Act 1887"
UNRELATED = "PPC 1860"


# ── the rule fires on the right queries ──────────────────────────────────────

@pytest.mark.parametrize("query", [
    "Can a tenant be evicted without notice in Punjab?",
    "My landlord is not returning my security deposit",
    "How much rent increase is allowed for a shop?",
    "mera makan malik mujhe nikal raha hai",           # Roman Urdu: landlord evicting me
])
def test_urban_tenancy_queries_prefer_the_rented_premises_act(query):
    assert statute_weight(query, RENTED) == BOOST
    assert statute_weight(query, TENANCY) == PENALTY


@pytest.mark.parametrize("query", [
    "What are the rights of an agricultural tenant over occupancy land?",
    "Can a zamindar eject a tenant from cultivated land?",
    "land revenue assessment on a tenant's crop",
])
def test_agricultural_queries_are_left_alone(query):
    """The exclusion is what keeps this from breaking farmland questions, where
    the Tenancy Act 1887 is the CORRECT law."""
    assert statute_weight(query, RENTED) == 1.0
    assert statute_weight(query, TENANCY) == 1.0
    assert active_rules(query) == []


def test_unrelated_statutes_are_never_weighted():
    q = "Can a tenant be evicted without notice?"
    assert statute_weight(q, UNRELATED) == 1.0


def test_unrelated_queries_fire_no_rule():
    for q in ("What is the punishment for theft?", "grounds for khula", ""):
        assert active_rules(q) == []


# ── reordering behaviour ─────────────────────────────────────────────────────

def _chunk(statute, section="1"):
    return {"statute": statute, "section_number": section,
            "content": f"text of {statute} s.{section}", "chunk_id": f"{statute}:{section}"}


def test_the_correct_statute_is_promoted_to_the_front():
    """The live failure: the answer sat at rank 6 and the grader, which only
    scores the leading chunks, never saw it."""
    chunks = [_chunk(TENANCY, "45"), _chunk(TENANCY, "27"), _chunk(UNRELATED),
              _chunk(TENANCY, "35"), _chunk(TENANCY, "76"), _chunk(RENTED, "15")]
    out = _apply_topic_rules(chunks, "Can a tenant be evicted without notice in Punjab?")
    assert out[0]["statute"] == RENTED


def test_nothing_is_dropped():
    """This breaks near-ties; it does not filter. A demoted statute remains
    retrievable and citable."""
    chunks = [_chunk(TENANCY), _chunk(RENTED), _chunk(UNRELATED)]
    out = _apply_topic_rules(chunks, "tenant eviction from rented premises")
    assert len(out) == 3
    assert {c["statute"] for c in out} == {TENANCY, RENTED, UNRELATED}


def test_ordering_is_stable_for_untouched_chunks():
    """Chunks no rule mentions must keep their retrieval order, or reordering
    would silently churn results the rules have no opinion about."""
    chunks = [_chunk(UNRELATED, "1"), _chunk(UNRELATED, "2"), _chunk(UNRELATED, "3")]
    out = _apply_topic_rules(chunks, "tenant evicted from rented premises")
    assert [c["section_number"] for c in out] == ["1", "2", "3"]


def test_no_reordering_when_no_rule_fires():
    chunks = [_chunk(TENANCY), _chunk(RENTED)]
    out = _apply_topic_rules(chunks, "What is the punishment for theft?")
    assert out == chunks


def test_empty_input_is_handled():
    assert _apply_topic_rules([], "tenant eviction") == []


# ── the weights themselves ───────────────────────────────────────────────────

def test_the_adjustment_is_modest_by_design():
    """Large enough to break a 1.5% tie, small enough that it cannot promote a
    genuinely poor match over a good one."""
    assert 1.0 < BOOST <= 1.25
    assert 0.75 <= PENALTY < 1.0
