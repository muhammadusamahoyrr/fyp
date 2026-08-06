"""The retrieval grader's LLM output was never validated.

The grader asks a fast-tier model for a JSON array of 0/1, one per chunk. On the
model actually serving this deployment (llama-3.1-8b via OpenRouter) it was
observed returning an array of 130 zeros for 8 chunks. score_retrieval_batch
pads and truncates its inputs, so that ran straight through as "all eight chunks
are irrelevant" — a malformed response became a confident negative judgement,
indistinguishable in the audit trail from a real one.

The neutral degradation path already existed for provider outages. A
wrong-length reply belongs in it: it is not a grade.
"""
import asyncio
import json

import pytest

from app.ai.nodes import retrieval_grader_node as mod


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        return type("R", (), {"content": self.payload})()


def _chunks(n):
    return [{"content": f"statute text {i}", "statute": "PPC 1860",
             "section_number": str(i), "chunk_id": f"c{i}"} for i in range(n)]


def _run(monkeypatch, payload, n=4, grades_seen=None):
    monkeypatch.setattr(mod, "get_fast_llm", lambda: _FakeLLM(payload))
    # Keep the test off Chroma and off the threshold/drift writers.
    monkeypatch.setattr(mod, "similarity_scores", lambda q, c, ct: [0.5] * len(c))

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(mod, "_record_observation", _noop)

    real_batch = mod.score_retrieval_batch

    def _spy(**kwargs):
        if grades_seen is not None:
            grades_seen.append(list(kwargs.get("llm_grades") or []))
        return real_batch(**kwargs)
    monkeypatch.setattr(mod, "score_retrieval_batch", _spy)

    state = {"query": "What is the punishment for theft?", "retrieved_chunks": _chunks(n),
             "case_type": "criminal"}
    return asyncio.run(mod.retrieval_grader_node(state))


def test_a_wrong_length_grade_array_is_rejected(monkeypatch):
    """The observed failure: 130 grades for 8 chunks."""
    seen = []
    _run(monkeypatch, json.dumps([0] * 130), n=8, grades_seen=seen)
    assert seen and seen[0] == [mod._NEUTRAL_GRADE] * 8


def test_a_short_grade_array_is_rejected_too(monkeypatch):
    """Padding a short reply would invent grades the model never gave."""
    seen = []
    _run(monkeypatch, json.dumps([1, 1]), n=6, grades_seen=seen)
    assert seen and seen[0] == [mod._NEUTRAL_GRADE] * 6


def test_a_correct_length_array_is_used_as_given(monkeypatch):
    seen = []
    _run(monkeypatch, json.dumps([1, 0, 1, 0]), n=4, grades_seen=seen)
    assert seen and seen[0] == [1.0, 0.0, 1.0, 0.0]


def test_unparseable_output_still_degrades_to_neutral(monkeypatch):
    seen = []
    _run(monkeypatch, "I think chunks 1 and 3 are relevant.", n=4, grades_seen=seen)
    assert seen and seen[0] == [mod._NEUTRAL_GRADE] * 4


def test_rejection_does_not_fail_the_query(monkeypatch):
    """Degrading is the point — the lexical and embedding signals still decide."""
    out = _run(monkeypatch, json.dumps([0] * 99), n=4)
    assert out["reranked_chunks"]
    assert out["relevance_score"] > 0.0


def test_no_chunks_short_circuits_without_calling_the_llm(monkeypatch):
    called = {"n": 0}

    def _boom():
        called["n"] += 1
        raise AssertionError("grader must not call the LLM with zero chunks")

    monkeypatch.setattr(mod, "get_fast_llm", _boom)
    out = asyncio.run(mod.retrieval_grader_node({"query": "q", "retrieved_chunks": []}))
    assert out["relevance_score"] == 0.0
    assert out["reranked_chunks"] == []
    assert called["n"] == 0
