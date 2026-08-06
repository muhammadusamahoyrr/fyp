"""Graph-guided hop-2 expansion.

The graph previously had 44 edges across 2,639 nodes and was loaded by nothing.
Three causes: it looked for lawyer shorthand ("PPC 302") that appears zero times
in statutory text, it ignored the bare "section N" references statutes actually
use, and source nodes were keyed on canonical names while targets were keyed on
abbreviations so every edge landed on an orphan stub.
"""
import importlib.util
from pathlib import Path

import networkx as nx
import pytest

from app.ai.pipelines import law_graph

_BUILDER = Path(__file__).resolve().parent.parent / "scripts" / "build_law_graph.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_law_graph", _BUILDER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def builder():
    return _load_builder()


# ── node ids must agree across builder and reader ────────────────────────────

def test_node_id_is_identical_in_builder_and_reader(builder):
    """The original bug: builder wrote ppc_1860_302, reader looked for ppc_302,
    so nothing ever resolved. These two must never drift apart."""
    for statute, section in [("PPC 1860", "302"), ("CrPC 1898", "154"),
                             ("Qanun-e-Shahadat Order 1984", "3A")]:
        assert builder.node_id(statute, section) == law_graph.node_id(statute, section)


# ── statute resolution ────────────────────────────────────────────────────────

def test_bare_section_resolves_within_the_same_statute(builder):
    """How statutes actually cross-reference: "under section 12", no name."""
    assert builder.resolve_statute(None, "PPC 1860", {"PPC 1860"}) == "PPC 1860"


def test_anaphoric_reference_resolves_to_the_referring_statute(builder):
    """"this Code" inside the CrPC means the CrPC."""
    known = {"CrPC 1898"}
    for phrase in ("this Code", "the said Act", "the same Ordinance", "that Act"):
        assert builder.resolve_statute(phrase, "CrPC 1898", known) == "CrPC 1898"


def test_named_statute_resolves_through_the_alias_table(builder):
    known = {"PPC 1860", "CrPC 1898"}
    assert builder.resolve_statute("Pakistan Penal Code", "CrPC 1898", known) == "PPC 1860"


def test_a_statute_absent_from_the_corpus_yields_no_edge(builder):
    """Better no edge than an edge to law we do not hold."""
    assert builder.resolve_statute("Pakistan Penal Code", "CrPC 1898", {"CrPC 1898"}) is None


def test_ambiguous_short_names_are_refused(builder):
    """A false edge sends hop-2 to the WRONG statute, which is worse than none."""
    known = {"Punjab Tenancy Act 1887", "Punjab Pre-emption Act 1991"}
    assert builder.resolve_statute("Act", "PPC 1860", known) is None
    assert builder.resolve_statute("Punjab", "PPC 1860", known) is None


# ── expansion ────────────────────────────────────────────────────────────────

def _graph():
    g = nx.DiGraph()
    g.add_node(law_graph.node_id("PPC 1860", "302"),
               statute="PPC 1860", section_number="302", chunk_ids=["c_302"])
    g.add_node(law_graph.node_id("PPC 1860", "300"),
               statute="PPC 1860", section_number="300", chunk_ids=["c_300a", "c_300b"])
    g.add_node(law_graph.node_id("PPC 1860", "34"),
               statute="PPC 1860", section_number="34", chunk_ids=["c_34"])
    g.add_edge(law_graph.node_id("PPC 1860", "302"),
               law_graph.node_id("PPC 1860", "300"), relation="defined_by", weight=1.20)
    g.add_edge(law_graph.node_id("PPC 1860", "302"),
               law_graph.node_id("PPC 1860", "34"), relation="ref", weight=1.10)
    return g


@pytest.fixture
def fake_graph(monkeypatch):
    g = _graph()
    monkeypatch.setattr(law_graph, "get_graph", lambda: g)
    return g


def test_expansion_returns_every_chunk_of_a_referenced_section(fake_graph):
    """A section spanning several chunks must not lose the rest of itself."""
    ids = law_graph.expand([("PPC 1860", "302")])
    assert set(ids) == {"c_300a", "c_300b", "c_34"}


def test_stronger_relations_rank_first(fake_graph):
    """defined_by (1.20) outranks ref (1.10) — a definition matters more than a
    passing mention when the budget is limited."""
    ids = law_graph.expand([("PPC 1860", "302")])
    assert ids[-1] == "c_34"


def test_max_targets_is_respected(fake_graph):
    assert len(law_graph.expand([("PPC 1860", "302")], max_targets=1)) == 1


def test_unknown_section_expands_to_nothing(fake_graph):
    assert law_graph.expand([("PPC 1860", "999")]) == []
    assert law_graph.expand([("Nonexistent Act 1900", "1")]) == []


def test_incomplete_refs_are_skipped(fake_graph):
    assert law_graph.expand([("", "302"), ("PPC 1860", "")]) == []


def test_missing_graph_degrades_to_empty(monkeypatch):
    """A missing or stale graph must fall back to the text re-query, never raise."""
    monkeypatch.setattr(law_graph, "get_graph", lambda: None)
    assert law_graph.expand([("PPC 1860", "302")]) == []
    assert law_graph.stats() == {"available": False}
