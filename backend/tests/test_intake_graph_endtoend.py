"""The intake graph, driven as a graph. Fake models, no database, no network.

WHY THIS FILE EXISTS

Every other intake test calls the nodes directly, and a node returns a plain
dict — so its whole return value is visible to the assertion. That is not what
the graph does. LangGraph merges a node's output into `AgentState` and DROPS
every key the schema does not declare.

`binding_mode` and `citation_binding` were returned by
intake_hallucination_node and discarded on the way out, so the service read
`None` and every analysis recorded `"none"`. The one signal that exists to make
a degraded binding route visible could never be observed — and no node-level
test could see it, because at that layer the field was still there.

So these tests assert on what comes OUT OF THE COMPILED GRAPH, and on the
shapes the frontend actually indexes into.
"""
from __future__ import annotations

import json

import pytest
from langgraph.graph import END, StateGraph

from app.ai.graph.state import AgentState
from app.ai.nodes import intake_hallucination_node as judge_mod
from app.ai.nodes import intake_node as analyst_mod
from app.ai.nodes.intake_finalizer_node import intake_finalizer_node
from app.ai.nodes.intake_hallucination_node import intake_hallucination_node
from app.ai.nodes.intake_node import intake_node

CHUNKS = [
    {"statute": "PPC", "section_number": "302", "chunk_id": "c-a",
     "content": "Punishment for qatl-i-amd.", "source_file": "ppc.pdf",
     "province": "federal"},
    {"statute": "CrPC", "section_number": "154", "chunk_id": "c-b",
     "content": "Information in cognizable cases.", "source_file": "crpc.pdf",
     "province": "federal"},
]


class _Fake:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, messages):
        return self.payload


def _retrieval(chunks):
    async def node(state):
        return {"retrieved_chunks": chunks, "reranked_chunks": chunks,
                "case_law_chunks": [], "retrieval_attempts": 1,
                "retrieval_error": False}
    return node


@pytest.fixture
def run_graph(monkeypatch):
    """Compile the real intake nodes behind a stubbed retrieval step.

    Retrieval is replaced because it needs Chroma; the three nodes whose
    contract this file is about are the real ones, wired exactly as
    `build_intake_graph` wires them.
    """
    def run(chunks, law_citations, actions, judge_grounded=True,
            claim_support="1:supported,2:supported"):
        analysis = analyst_mod.IntakeOutput(
            summary="The client has a strong claim.",
            law_citations=law_citations,
            recommended_actions=actions,
            risk_level="high",
        )
        verdict = judge_mod.IntakeGroundingOutput(
            is_grounded=judge_grounded, reason="ok", claim_support=claim_support)
        monkeypatch.setattr(analyst_mod, "get_structured_llm",
                            lambda schema, **kw: _Fake(analysis))
        monkeypatch.setattr(judge_mod, "get_structured_llm",
                            lambda schema, **kw: _Fake(verdict))

        builder = StateGraph(AgentState)
        builder.add_node("retrieval_node", _retrieval(chunks))
        builder.add_node("intake_node", intake_node)
        builder.add_node("intake_hallucination_node", intake_hallucination_node)
        builder.add_node("intake_finalizer_node", intake_finalizer_node)
        builder.set_entry_point("retrieval_node")
        builder.add_edge("retrieval_node", "intake_node")
        builder.add_edge("intake_node", "intake_hallucination_node")
        builder.add_edge("intake_hallucination_node", "intake_finalizer_node")
        builder.add_edge("intake_finalizer_node", END)

        return builder.compile().ainvoke({
            "query": "My brother was killed in Lahore.",
            "province": "punjab", "case_type": "criminal", "language": "en",
            "reranked_chunks": [], "case_law_chunks": [], "tool_results": [],
            "citations": [], "generation_evidence": [], "claim_assessments": [],
            "answer": "", "is_grounded": False, "messages": [],
        })

    return run


BOUND = [{"evidence_id": "1", "statute": "PPC", "section": "302", "note": "murder"}]
ACTION = [{"text": "File an FIR", "evidence_ids": ["2"]}]


# ── the fields must survive the graph, not just the node ───────────────────

async def test_binding_mode_survives_the_graph(run_graph):
    """The bug this file was written for.

    Returned by the judge, dropped by LangGraph because `AgentState` did not
    declare it, and read back as None by the service — which then recorded
    "none" for every analysis ever produced.
    """
    result = await run_graph(CHUNKS, BOUND, ACTION)
    assert result.get("binding_mode") == "id"


async def test_the_binding_counts_survive_the_graph(run_graph):
    result = await run_graph(CHUNKS, BOUND, ACTION)
    assert result.get("citation_binding", {}).get("bound") == 1


@pytest.mark.parametrize("field", [
    "citations", "claim_assessments", "generation_evidence",
    "grounding_status", "binding_mode", "citation_binding",
])
async def test_every_field_the_service_reads_is_declared(run_graph, field):
    """`_run_intake_ai` reads each of these off the graph result.

    A field absent from `AgentState` reads back as None and degrades silently,
    which is exactly how the binding signal was lost.
    """
    result = await run_graph(CHUNKS, BOUND, ACTION)
    assert field in result, f"{field} did not survive the graph"


# ── the shapes the frontend indexes into ───────────────────────────────────

@pytest.mark.parametrize("chunks,laws,actions", [
    (CHUNKS, BOUND, ACTION),                                  # happy path
    (CHUNKS, [{"evidence_id": "9", "statute": "PPC",
               "section": "302"}], ACTION),                   # phantom
    ([], [], [{"text": "Consult a lawyer", "evidence_ids": []}]),   # no retrieval
    (CHUNKS, [], [{"text": "Consult a lawyer", "evidence_ids": []}]),  # no citations
])
async def test_the_display_fields_are_always_lists_of_strings(
        run_graph, chunks, laws, actions):
    """ModIntake calls `.map()` and `.join()` on both of these.

    `intake_node` emits structured objects now, and the finalizer derives the
    strings. If that derivation is ever skipped the print view and the text
    export render "[object Object]" — so the shape is asserted on every path
    through the graph, not only the happy one.
    """
    result = await run_graph(chunks, laws, actions)
    analysis = json.loads(result["answer"])

    for field in ("applicable_laws", "recommended_actions"):
        value = analysis.get(field)
        assert isinstance(value, list), f"{field} is not a list"
        assert all(isinstance(x, str) for x in value), \
            f"{field} contains non-strings; the UI would render objects"


async def test_the_answer_is_still_parseable_json(run_graph):
    """`_run_intake_ai` json.loads this. A finalizer that broke it would land
    the whole conversion on the pipeline_failed path."""
    result = await run_graph(CHUNKS, BOUND, ACTION)
    assert json.loads(result["answer"])["summary"]


async def test_a_phantom_never_leaves_the_graph_marked_grounded(run_graph):
    result = await run_graph(CHUNKS, [{"evidence_id": "9", "statute": "PPC",
                                       "section": "302"}], ACTION,
                             judge_grounded=True)
    assert result["is_grounded"] is False
    assert result["grounding_status"] == "citations_unverified"


async def test_zero_retrieval_never_leaves_the_graph_grounded(run_graph):
    result = await run_graph([], [], [{"text": "Consult a lawyer",
                                       "evidence_ids": []}])
    assert result["is_grounded"] is False
    assert result["grounding_status"] == "no_evidence_retrieved"


async def test_a_clean_run_is_grounded_and_carries_its_evidence(run_graph):
    result = await run_graph(CHUNKS, BOUND, ACTION)
    assert result["is_grounded"] is True
    assert [e["chunk_id"] for e in result["generation_evidence"]] == ["c-a", "c-b"]
    assert all("currency" in c for c in result["citations"])


# ── currency, asserted against a controlled index ───────────────────────────
#
# The presence check above is nearly vacuous on its own: `currency_for` needs
# the corpus index, which needs ChromaDB, which is not connected in a unit test
# — so it fails open to `unknown` and the field appears either way. That is the
# correct production behaviour (a currency check must never fail an answer) but
# it means the assertion cannot tell a working stamp from a silent fallback.
#
# So the repeal path is exercised the way the existing currency tests do it,
# with an injected index, on the citation shape the intake binder produces.


def _repeal_index():
    from app.ai.corpus_index import CorpusIndex, StatuteCoverage
    from app.ai.statute_omissions import OmissionRecord

    def coverage(statute, sections, omitted=(), records=None):
        return StatuteCoverage(
            statute=statute,
            sections=frozenset(str(s) for s in sections),
            numbered=frozenset(int(s) for s in sections),
            highest=max((int(s) for s in sections), default=0),
            artifacts=frozenset(),
            ceiling_outliers=frozenset(),
            omitted=frozenset(int(s) for s in omitted),
            omission_records=dict(records or {}),
        )

    crpc = coverage(
        "CrPC 1898", range(1, 412), omitted=(10,),
        records={10: OmissionRecord(
            10, "omitted", "Ordinance XXXVII of 2001", "2001-08-13",
            "federal", "")},
    )
    return CorpusIndex({"CrPC 1898": crpc})


def test_a_repealed_section_is_stamped_on_an_intake_citation():
    """An intake citation is the same shape the chat path stamps.

    If it were not, `apply_currency` would silently leave every intake citation
    `unknown` and a repealed provision would reach a client reading as sound.
    """
    from app.ai.answer_citations import CURRENCY_REPEALED, apply_currency
    from app.ai.intake_evidence import bind_intake_citations

    evidence = [{"id": "1", "kind": "statute", "statute": "CrPC 1898",
                 "section": "10", "chunk_id": "c-x", "source": "crpc.pdf"}]
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "CrPC 1898", "section": "10",
          "note": "District Magistrate"}], evidence)

    apply_currency(citations, [], province="", index=_repeal_index())

    assert citations[0]["currency"] == CURRENCY_REPEALED
    # The binding verdict is preserved; currency is a separate axis.
    assert citations[0]["status"] == "bound"


def test_the_citation_description_survives_the_currency_stamp():
    """`apply_currency` writes its own `note` key with `entry.update(verdict)`.

    The binder therefore stores its descriptive line under `description`. Had it
    used `note`, every intake citation would have arrived at the reader with its
    explanation blanked — which is how this was found.
    """
    from app.ai.answer_citations import apply_currency
    from app.ai.intake_evidence import bind_intake_citations, render_applicable_laws

    evidence = [{"id": "1", "kind": "statute", "statute": "CrPC 1898",
                 "section": "10", "chunk_id": "c-x", "source": "crpc.pdf"}]
    citations, _ = bind_intake_citations(
        [{"evidence_id": "1", "statute": "CrPC 1898", "section": "10",
          "note": "District Magistrate"}], evidence)

    apply_currency(citations, [], province="", index=_repeal_index())

    assert citations[0]["description"] == "District Magistrate"
    assert render_applicable_laws(citations) == [
        "CrPC 1898 Section 10 — District Magistrate"]
