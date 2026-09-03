"""Deterministic end-of-pipeline check for named-statute affinity.

CI must not depend on an external LLM, so this drives the real retrieval_grader_node
over a fixed candidate list with the grading and embedding calls replaced. The
substitutes are deliberately adversarial: every CrPC chunk is scored higher than
PPC 379, so the assertion can only pass if affinity actually reorders — not if the
scorer happens to agree.

The live 10-trial evaluation lives in scripts/eval_statute_affinity.py; it needs
Chroma, Mongo and a provider, and is not part of the suite.
"""
import pytest

from app.ai.pipelines.statute_affinity import apply_affinity


def _c(statute, section, cid=None):
    return {"statute": statute, "section_number": section, "content": f"{statute} {section}",
            "chunk_id": cid or f"{statute}:{section}"}


# The composition actually observed for "punishment for theft under the PPC":
# PPC 379 sat at rank 15+ behind a wall of CrPC procedural provisions.
OBSERVED_CANDIDATES = [
    _c("CrPC 1898", "221"), _c("CrPC 1898", "260"), _c("CrPC 1898", "221b"),
    _c("CrPC 1898", "234"), _c("CrPC 1898", "367"), _c("CrPC 1898", "108"),
    _c("CrPC 1898", "235"), _c("CrPC 1898", "196"), _c("CrPC 1898", "75"),
    _c("CrPC 1898", "76"), _c("PPC 1860", "108"), _c("CrPC 1898", "337"),
    _c("CrPC 1898", "265"), _c("CrPC 1898", "345"),
    _c("PPC 1860", "379", "statutes_ppc_1860_0598"),
]


def test_observed_composition_puts_ppc379_outside_the_graded_window():
    """Guard the premise: without affinity the target is beyond chunks[:8]."""
    from app.ai.nodes.retrieval_grader_node import _MAX_TO_GRADE
    idx = next(i for i, c in enumerate(OBSERVED_CANDIDATES)
               if c["chunk_id"] == "statutes_ppc_1860_0598")
    assert idx >= _MAX_TO_GRADE


def test_affinity_brings_ppc379_into_the_graded_window():
    from app.ai.nodes.retrieval_grader_node import _MAX_TO_GRADE
    out, named = apply_affinity(list(OBSERVED_CANDIDATES),
                                "What is the punishment for theft under the Pakistan Penal Code?")
    assert named == "PPC 1860"
    idx = next(i for i, c in enumerate(out) if c["chunk_id"] == "statutes_ppc_1860_0598")
    assert idx < _MAX_TO_GRADE
    assert len(out) == len(OBSERVED_CANDIDATES)


def test_crpc_material_is_still_present_after_preference():
    out, _ = apply_affinity(list(OBSERVED_CANDIDATES),
                            "punishment for theft under the Pakistan Penal Code")
    assert any(c["statute"] == "CrPC 1898" and c["section_number"] == "221" for c in out)
    assert sum(1 for c in out if c["statute"] == "CrPC 1898") == 13


def test_multi_statute_query_keeps_original_composition():
    """Comparison queries must not be tilted toward either side."""
    q = "Compare the Pakistan Penal Code and the Code of Criminal Procedure on theft"
    out, named = apply_affinity(list(OBSERVED_CANDIDATES), q)
    assert named is None
    assert [c["chunk_id"] for c in out] == [c["chunk_id"] for c in OBSERVED_CANDIDATES]


@pytest.mark.asyncio
async def test_full_grader_path_with_mocked_scoring(monkeypatch, stub_grader_llm):
    """Real node, hostile scorer: CrPC scores 0.9, PPC 379 scores 0.0.

    The LLM is stubbed at get_fast_llm — the actual seam — with exactly
    _MAX_TO_GRADE grades, and the call is asserted, so this cannot pass via the
    grader's neutral-degradation branch the way the earlier version did.
    """
    import app.ai.nodes.retrieval_grader_node as g

    stub = stub_grader_llm(g, monkeypatch, n_grades=g._MAX_TO_GRADE)
    monkeypatch.setattr(
        g, "similarity_scores",
        lambda q, items, ct: [0.0 if c.get("statute") == "PPC 1860" else 0.9 for c in items])

    state = {"query": "What is the punishment for theft under the Pakistan Penal Code?",
             "normalized_query": "theft punishment",
             "retrieved_chunks": list(OBSERVED_CANDIDATES),
             "case_type": "criminal", "province": "punjab"}
    out = await g.retrieval_grader_node(state)

    assert stub["calls"] == 1, "the grader LLM seam was bypassed"
    ordered = out["reranked_chunks"]
    assert ordered[0]["statute"] == "PPC 1860"
    assert out["signal_origin"] == "measured"
    assert len(ordered) == len(OBSERVED_CANDIDATES)


@pytest.mark.asyncio
async def test_grader_stub_receives_exactly_max_to_grade_chunks(monkeypatch, stub_grader_llm):
    """Pins the contract the stub relies on: the LLM grades chunks[:_MAX_TO_GRADE]."""
    import app.ai.nodes.retrieval_grader_node as g

    stub = stub_grader_llm(g, monkeypatch, n_grades=g._MAX_TO_GRADE)
    monkeypatch.setattr(g, "similarity_scores", lambda q, items, ct: [0.5] * len(items))

    state = {"query": "theft under the Pakistan Penal Code",
             "normalized_query": "theft", "retrieved_chunks": list(OBSERVED_CANDIDATES),
             "case_type": "criminal", "province": "punjab"}
    await g.retrieval_grader_node(state)

    assert stub["calls"] == 1
    user_msg = stub["messages"][1]["content"]
    # One bracketed marker per graded chunk, and no more.
    assert user_msg.count("\n[") + user_msg.count("[1]") >= 1
    assert f"[{g._MAX_TO_GRADE}]" in user_msg
    assert f"[{g._MAX_TO_GRADE + 1}]" not in user_msg
