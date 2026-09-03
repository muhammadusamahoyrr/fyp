import operator
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    # ── Core query fields ─────────────────────────────────────────────────────
    query: str
    normalized_query: str
    session_id: str
    case_id: str | None
    # Server-fetched, authorization-checked, whitelisted case facts.
    #
    # Case context reached the model only as free text the BROWSER put in
    # `history` — so the client decided what the model believed about the case,
    # nothing verified the sender was assigned to it, and the pre-filled context
    # prompt fell out of the last-four-message window a few turns in and
    # silently stopped applying. This field is built server-side from the case
    # record after case_service.get_case() has authorised the caller, and is
    # re-supplied on every turn so it cannot age out of a history window.
    case_context: dict | None
    case_record_version: str | None
    # A bounded, case-derived widening of the RETRIEVAL query only. The user's
    # `query` is never replaced: named-statute affinity reads the raw query and
    # generation answers it, so overwriting it would silently change both.
    retrieval_query_supplement: str
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
    # WHERE the jurisdiction came from. The province filter silently reduced an
    # unknown province to federal-only, hiding 1,608 provincial chunks (15.1% of
    # the statute corpus) from any question that did not name a province — and
    # the client UI sent province: null on every message. Retrieval no longer
    # narrows on unknown, and this field is how the answer says which
    # jurisdiction it actually assumed:
    #   "user_selected"       the user chose it (or their case/profile did)
    #   "inferred_from_query" triage read it out of the question text
    #   "unspecified"         nobody said; all jurisdictions were searched
    jurisdiction_basis: str
    language: str

    # ── Classifier output (fast keyword pass, no LLM) ─────────────────────────
    classifier_case_type:          str
    classifier_confidence:         float
    classifier_scores:             dict
    precomputed_collection_names:  list
    routing_mode:                  str

    # ── Intermediate intent (typed Any to avoid serializer warnings) ──────────
    followup_intent: Optional[Any]
    # Set when a node caught its own contract being broken and repaired it.
    # Carried into provenance so a turn produced from repaired-but-suspect input
    # is not graded as if the pipeline had behaved. None on a healthy turn.
    invariant_violation: Optional[str]

    # ── Clarification ─────────────────────────────────────────────────────────
    needs_clarification:    bool
    clarification_question: str
    clarification_depth:    int

    # ── Retrieval ─────────────────────────────────────────────────────────────
    web_search_enabled: bool
    retrieved_chunks: list[dict]
    reranked_chunks:  list[dict]
    # The LLM query rewrite and the exact input it was derived from. Carried so a
    # decision-engine "defer" retry on an unchanged question reuses the rewrite
    # rather than spending a second fast-tier call to recompute the same string.
    expanded_query:   str
    expansion_for:    str
    # Case-law (LHC judgment) hits — kept out of the statute grading loop so they
    # don't skew relevance_score, but folded into generation + grounding context.
    case_law_chunks:  list[dict]
    relevance_score:  float
    signal_variance:  float
    bm25_confidence:  float
    # Where the three signals above came from. They are initialised to 0.0, and a
    # cache hit skips retrieval entirely — so without this the state reported
    # relevance 0.0 / bm25 0.0 alongside confidence 0.85, which reads as "we
    # measured the evidence and it was worthless" when the truth is "we never
    # looked". Observed: two identical runs of the theft query reported
    # 0.416/0.393 and 0.0/0.0 respectively, and nothing distinguished them.
    #   "unmeasured"    — retrieval has not run yet on this turn
    #   "measured"      — the grader computed them from this turn's chunks
    #   "cached_source" — restored from the cache entry, measured on an earlier turn
    #   "cached_legacy" — cache entry predates signal storage; values unknown
    # Any retrieval experiment must exclude everything except "measured".
    signal_origin:    str
    # True when retrieval FAILED (exception), as opposed to running fine and
    # finding nothing. Both yield zero chunks; only one is an abstention.
    retrieval_error:  bool
    cache_hit:        bool
    # Attribution restored from a cache entry: who wrote the answer when it
    # was first generated. None for entries written before this existed.
    cached_answer_llm: Optional[dict]
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
    # Set only when the corpus cannot answer the question by its nature (a live
    # rate, a court statistic, a personal record) rather than for want of a good
    # enough match. Lets the finalizer say WHY and point somewhere useful,
    # instead of emitting the generic "I could not find this" that a user cannot
    # distinguish from a retrieval miss. See pipelines/answerability.py.
    refusal_kind:     str
    refusal_reason:   str
    refusal_redirect: str
    answer:      str
    citations:   list[dict]
    confidence:  float
    # The model's own self-reported figure, preserved separately for diagnostics.
    # `confidence` above is consumed internally (degraded by hallucination_node,
    # stored by the cache); neither is what the UI shows — see answer_confidence.
    model_confidence: float
    # The EXACT id-stamped evidence generation was given. Citation matching and
    # the grounding judge both resolve against this, so a source id cannot mean
    # one thing in the prompt and another downstream.
    generation_evidence: list[dict]
    # Per-claim support verdicts from the grounding judge: supported / partial /
    # unsupported / unassessed. See ai/answer_citations.py.
    claim_assessments: list[dict]
    is_grounded: bool
    # Set when the per-claim assessment contradicted a "grounded"
    # verdict. None on an ordinary ungrounded turn, so the audit trail
    # distinguishes "the judge refused" from "the judge said yes and
    # its own claims said no".
    grounding_veto:              Optional[str]
    # WHY the grounding verdict is what it is. `is_grounded` alone cannot
    # distinguish "checked and it held" from "could not check" — and the second
    # used to be reported as the first. Written by intake_hallucination_node.
    grounding_status: str

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
