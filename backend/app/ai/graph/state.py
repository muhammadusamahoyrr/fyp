import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # ── Core query fields ─────────────────────────────────────────────────────
    query: str
    normalized_query: str       # Roman Urdu / Urdu normalized to standard Urdu; EN unchanged
    session_id: str
    case_id: str | None
    case_type: str              # civil | criminal | family | constitutional
    case_type_confidence: float # 0.0–1.0 confidence in case_type classification
    complexity: str             # simple | complex
    urgency: str                # low | medium | high | critical
    province: str               # punjab | sindh | kpk | balochistan | federal
    language: str               # en | ur | roman_urdu

    # ── Classifier output (fast keyword pass, no LLM) ─────────────────────────
    classifier_case_type:  str   # best guess from keyword signals (may differ from triage)
    classifier_confidence: float # 0.0–1.0 confidence from classifier_node
    routing_mode:          str   # "single" | "hybrid" (hybrid = unknown case_type)

    # ── Clarification ─────────────────────────────────────────────────────────
    needs_clarification: bool
    clarification_question: str

    # ── Retrieval ─────────────────────────────────────────────────────────────
    retrieved_chunks: list[dict]
    reranked_chunks: list[dict]
    relevance_score: float

    # ── Generation ────────────────────────────────────────────────────────────
    answer: str
    citations: list[dict]
    confidence: float
    is_grounded: bool

    # ── Convergence controller ────────────────────────────────────────────────
    prev_relevance_score: float     # relevance_score from the previous retrieval loop
    prev_confidence: float          # confidence from the previous generation loop
    known_facts: list[str]          # facts extracted from the query by triage_node
    fact_delta: int                 # new facts discovered since the last fact_gap check
    retrieval_attempts: int         # how many times retrieval_node has run this turn
    generation_attempts: int        # how many times generation_node has run this turn
    clarification_attempts: int     # clarifying questions sent to the user this session
    convergence_status: str         # pending | converged | needs_clarification | max_attempts | off_topic

    # ── Message history (append-only, managed by MemorySaver) ─────────────────
    messages: Annotated[list[BaseMessage], operator.add]
