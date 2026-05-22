import operator
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # ── Core query fields ─────────────────────────────────────────────────────
    query: str
    normalized_query: str
    session_id: str
    case_id: str | None
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
    retrieved_chunks: list[dict]
    reranked_chunks:  list[dict]
    relevance_score:  float
    signal_variance:  float
    bm25_confidence:  float
    cache_hit:        bool
    cache_confidence: float

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
