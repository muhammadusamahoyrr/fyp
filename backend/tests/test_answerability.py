"""Questions a statutory corpus cannot answer, whatever retrieval returns.

The abstention failure this guards against: "What is the current stamp duty rate
for property transfer in Gilgit-Baltistan?" is a real legal question, so the
gatekeeper passes it (not an attack) and triage passes it (not off-topic).
Retrieval then returns genuine Transfer of Property Act sections that share its
vocabulary, every signal reads as moderate, and the system answers confidently
from law that does not contain the answer.

Thresholds cannot fix it. Measured on this corpus, unanswerable queries score
0.273-0.412 and answerable ones 0.309-0.662 — overlapping, so every cut trades
false refusals for false answers. The difference is in the KIND of fact asked
for, which is decidable from the query alone.

The precision cases below matter more than the recall cases. A false positive
refuses a question the system could have answered, and the user cannot tell that
refusal apart from a genuine gap.
"""
import pytest

from app.ai.decision_engine import run_decision_engine
from app.ai.pipelines.answerability import check


# ── precision: these must NEVER be refused ───────────────────────────────────

@pytest.mark.parametrize("query", [
    "What is the punishment for theft under the Pakistan Penal Code?",
    "Can a tenant be evicted without notice in Punjab?",
    "What are the grounds for khula under Pakistani family law?",
    "How do I file an FIR if the police refuse to register it?",
    "What are the fundamental rights guaranteed by the Constitution of Pakistan?",
    "What is the limitation period for filing a civil suit for recovery?",
    "How is a woman's share calculated in Islamic inheritance?",
    "mujhe police ne bina warrant ke giraftar kiya, main kya karun?",
])
def test_ordinary_legal_questions_are_never_blocked(query):
    assert check(query) is None


@pytest.mark.parametrize("query", [
    # Each of these tripped an earlier, looser version of a rule.
    "How many days do I have to file an appeal?",        # limitation, not a statistic
    "How many witnesses are required to prove a will?",  # evidence law
    "What is the procedure to recover my lawyer's fee?", # law of costs
    "What is the rate of interest allowed on a decretal amount?",
    "What is the stamp duty chargeable under the Stamp Act 1899?",
    "What court fee is prescribed by the Court Fees Act schedule?",
])
def test_near_misses_stay_answerable(query):
    """These share vocabulary with the unanswerable classes but ask what the
    statute itself says, which is exactly what the corpus holds."""
    assert check(query) is None


# ── recall: these must be refused ────────────────────────────────────────────

@pytest.mark.parametrize("query,kind", [
    ("What is the current stamp duty rate for property transfer in Gilgit-Baltistan?", "live_rate"),
    ("What is the latest court fee for a civil suit?",           "live_rate"),
    ("the stamp duty rate as of 2025",                           "live_rate"),
    ("How many cases were pending in the Lahore High Court in 2019?", "court_statistic"),
    ("What is the pendency in the Supreme Court?",               "court_statistic"),
    ("What is my lawyer's phone number?",                        "personal_record"),
    ("What is my advocate's contact number?",                    "personal_record"),
    ("What is the status of my case?",                           "personal_record"),
    ("Will I win my case?",                                      "outcome_prediction"),
    ("What are my chances of winning this appeal?",              "outcome_prediction"),
])
def test_unanswerable_questions_are_identified(query, kind):
    verdict = check(query)
    assert verdict is not None, f"not caught: {query}"
    assert verdict.kind == kind


def test_every_verdict_explains_itself_and_points_somewhere():
    """A refusal the user cannot act on is barely better than a wrong answer —
    they will just rephrase and hit the same wall."""
    for q in ("What is the current stamp duty rate?", "Will I win my case?",
              "What is my lawyer's phone number?", "What is the pendency figure?"):
        v = check(q)
        if v is None:
            continue
        assert v.reason and v.reason.endswith((".", "!"))
        assert v.redirect


def test_empty_and_blank_queries_are_not_refused_here():
    assert check("") is None
    assert check("   ") is None
    assert check(None) is None


# ── the gate is wired into routing ───────────────────────────────────────────

def _state(query, chunks=1):
    return {
        "query": query,
        "reranked_chunks": [{"content": "some statute text", "statute": "X"}] * chunks,
        "relevance_score": 0.85,     # deliberately HIGH
        "signal_variance": 0.0,
        "bm25_confidence": 0.85,
    }


def test_high_confidence_does_not_override_the_gate():
    """The whole point: retrieval was confident and still wrong. If this test
    ever fails because someone moved the check below the evidence branches, the
    regression is back."""
    out = run_decision_engine(_state("What is the current stamp duty rate in Punjab?"))
    assert out["arbitration_output"] == "refuse"
    assert out["arbitration_source"] == "unanswerable"
    assert out["arbitration_confidence"] == 0.0


def test_the_refusal_carries_its_reason_into_state():
    out = run_decision_engine(_state("What is my lawyer's phone number?"))
    assert out["refusal_kind"] == "personal_record"
    assert out["refusal_reason"]
    assert out["refusal_redirect"]


def test_answerable_questions_still_route_on_evidence():
    out = run_decision_engine(_state("What is the punishment for theft under the PPC?"))
    assert out["arbitration_output"] == "answer"
    assert out["arbitration_source"] != "unanswerable"


def test_zero_chunks_still_refuses_with_its_own_source():
    """The unanswerable gate must not swallow the no-evidence case — they are
    different abstentions and the audit trail distinguishes them."""
    out = run_decision_engine(_state("What is the punishment for theft?", chunks=0))
    assert out["arbitration_output"] == "refuse"
    assert out["arbitration_source"] == "none"


# ── the cache must not bypass the gate ───────────────────────────────────────

def test_the_cache_declines_unanswerable_queries(monkeypatch):
    """A cache hit routes straight to finalizer_node, skipping the Decision
    Engine. A pre-fix answer to 'the current stamp duty rate in
    Gilgit-Baltistan' therefore survived the fix and kept being served at 0.85
    confidence — verified live before this was closed."""
    import asyncio

    from app.ai.nodes import cache_node

    async def _boom(*a, **k):
        raise AssertionError("cache must not be consulted for an unanswerable query")

    monkeypatch.setattr(cache_node.cache, "get_result", _boom)
    out = asyncio.run(cache_node.cache_lookup_node(
        {"query": "What is the current stamp duty rate in Gilgit-Baltistan?"}))
    assert out == {"cache_hit": False}


def test_the_cache_is_still_used_for_ordinary_questions(monkeypatch):
    import asyncio

    from app.ai.nodes import cache_node

    async def _hit(*a, **k):
        return {"answer": "cached", "citations": [], "confidence": 0.9, "is_grounded": True}

    monkeypatch.setattr(cache_node.cache, "get_result", _hit)
    out = asyncio.run(cache_node.cache_lookup_node(
        {"query": "What is the punishment for theft under the PPC?"}))
    assert out["cache_hit"] is True
    assert out["arbitration_source"] == "cache"
