import operator
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # ── Core query fields ─────────────────────────────────────────────────────
    query: str
    normalized_query: str
    session_id: str
    case_id: str | None
    # Authenticated caller. Document tools are BOUND to this id — it is never a
    # tool argument, so the model cannot reach another user's uploads.
    user_id: str
    user_role: str
    case_type: str
    case_type_confidence: float
    complexity: str
    urgency: str
    province: str
    province_inferred: bool
    language: str

    # ── Classifier output (fast keyword pass, no LLM) ─────────────────────────
    classifier_case_type:          str
    classifier_confidence:         float
    classifier_scores:             dict
    precomputed_collection_names:  list
    routing_mode:                  str

    # ── Intermediate intent (typed Any to avoid serializer warnings) ──────────
    followup_intent: Optional[Any]

    # ── Clarification ─────────────────────────────────────────────────────────
    needs_clarification:    bool
    clarification_question: str
    clarification_depth:    int

    # ── Retrieval ─────────────────────────────────────────────────────────────
    web_search_enabled: bool
    retrieved_chunks: list[dict]
    reranked_chunks:  list[dict]
    # Case-law (LHC judgment) hits — kept out of the statute grading loop so they
    # don't skew relevance_score, but folded into generation + grounding context.
    case_law_chunks:  list[dict]
    relevance_score:  float
    signal_variance:  float
    bm25_confidence:  float
    # True when retrieval FAILED (exception), as opposed to running fine and
    # finding nothing. Both yield zero chunks; only one is an abstention.
    retrieval_error:  bool
    cache_hit:        bool
    cache_confidence: float

    # ── Tool calls (deterministic engines) ────────────────────────────────────
    # Held out of retrieved_chunks on purpose: engine output is ground truth, so
    # it must not be scored by the relevance grader nor overwritten by a
    # retrieval retry. Each entry: {"tool": str, "args": dict, "result": Any}.
    tool_results:     list[dict]
    tool_calls_made:  list[str]

    # ── Arbitration / generation ──────────────────────────────────────────────
    arbitration_output:     str
    arbitration_source:     str
    arbitration_confidence: float
    answer:      str
    citations:   list[dict]
    confidence:  float
    is_grounded: bool

    # ── Convergence controller ────────────────────────────────────────────────
    prev_relevance_score:   float
    prev_confidence:        float
    known_facts:            list[str]
    fact_delta:             int
    retrieval_attempts:     int
    generation_attempts:    int
    clarification_attempts: int
    convergence_status:     str

    # ── Message history (append-only, managed by MemorySaver) ─────────────────
    messages: Annotated[list[BaseMessage], operator.add]
