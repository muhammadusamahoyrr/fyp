# Attorney.AI — Pipeline Context

Last updated: 2026-05-12

---

## Overview

Two separate LangGraph graphs share the same node implementations:

| Graph | Entry point | Purpose |
|-------|-------------|---------|
| `chat_graph` | `classifier_node` | Real-time WebSocket chat. Uses `MemorySaver` checkpointer for multi-turn context and `interrupt()` HITL. |
| `intake_graph` | `retrieval_node` | One-shot structured case analysis during intake conversion. No checkpointer, no interrupts. |

Both are compiled in `app/ai/graph/supervisor.py` and imported as module-level singletons (`chat_graph`, `intake_graph`).

---

## LLM Roles

| Function | Model | Used by |
|----------|-------|---------|
| `get_llm()` | Groq `llama-3.3-70b-versatile` (or Gemini/Ollama via `LLM_PROVIDER`) | `generation_node`, `fact_gap_node`, `retrieval_node` (query rewrite) |
| `get_fast_llm()` | Gemini 2.0 Flash (always, ignores `LLM_PROVIDER`) | `triage_node`, `clarification_node`, `retrieval_grader_node`, `hallucination_node` |
| `_get_triage_llm()` | Gemini Flash if `GEMINI_API_KEY` set, else Groq fallback | `triage_node` internal — intent detection + full LLM triage |

`get_fast_llm()` is hardcoded to Gemini Flash so classification and grading stay fast/cheap regardless of which generation model is configured.

---

## Chat Graph — Node-by-Node

### 1. `classifier_node`
**File:** `app/ai/nodes/classifier_node.py`  
**LLM:** None (pure regex)  
**Entry point for chat_graph.**

- Scores query against 4 regex signal tables (criminal, civil, family, constitutional) using weighted keyword patterns.
- Infers `province` from city names (Lahore → punjab, Karachi → sindh, Islamabad → federal, etc.).
- Sets `classifier_case_type`, `classifier_confidence`, `routing_mode` (`single` | `hybrid`).
- **High confidence (≥ 0.85):** also writes `case_type` to skip triage LLM confirmation.
- **Zero signals:** `routing_mode = hybrid`, `case_type = unknown` — needs clarification.
- **2+ categories above 0.15 overlap:** `routing_mode = hybrid` with best-guess `case_type`.
- Province inference **always runs**, even on early return (fix for silent filter failures).
- Always routes → `triage_node`.

### 2. `triage_node`
**File:** `app/ai/nodes/triage_node.py`  
**LLM:** `_get_triage_llm()` (Gemini Flash / Groq fallback)

Three fast-path exits before touching the LLM:

1. **Gibberish guard** — `_is_gibberish()`: fewer than 2 words of ≥ 3 chars (Latin or Arabic Unicode) → returns `_CANNED_GIBBERISH`, `convergence_status = off_topic`.
2. **Pre-set intent** — if `chat_socket` already injected `followup_intent ∈ {format, deepen}`, returns immediately without LLM call.
3. **Intent detection** — `_detect_intent(query, last_ai)` via `FollowupIntent` structured output:
   - `affirm` (confidence ≥ 0.65) → `_CANNED_AFFIRM`, `convergence_status = off_topic`.
   - `format` or `deepen` (confidence ≥ 0.65) → sets `followup_intent`, skips full triage.
   - Falls back to `intent = new` on any error.

Full LLM triage produces `TriageOutput`:
- `category`: `legal` | `off_topic` | `gibberish`
- `language`: `en` | `ur` | `roman_urdu`
- `normalized_query`: Roman Urdu → standard Urdu script; English unchanged
- `case_type`, `case_type_confidence`, `complexity`, `urgency`, `province`, `known_facts`, `reason`

Off-topic / gibberish → sets `convergence_status = off_topic`, routes → `finalizer_node`.  
Legal → routes to `clarification_node` or `fact_gap_node` via `route_after_triage`.

**`route_after_triage` logic:**
1. `convergence_status == off_topic` → `finalizer_node`
2. `routing_mode == hybrid AND confidence == 0.0` → `clarification_node`
3. `routing_mode == hybrid AND confidence > 0.0` → `fact_gap_node`
4. `province == unknown` → `clarification_node`
5. `case_type == unknown` → `clarification_node`
6. Default → `fact_gap_node`

### 3. `clarification_node`
**File:** `app/ai/nodes/clarification_node.py`  
**LLM:** `get_fast_llm()` (Gemini Flash)

Fires when triage can't resolve case type or province. Generates ONE targeted question referencing what the user already said. Asks in user's language (English/Urdu). Always routes → `fact_gap_node`.

### 4. `fact_gap_node`
**File:** `app/ai/nodes/fact_gap_node.py`  
**LLM:** `get_llm()` (Groq 70B)

Checks if enough facts exist to retrieve useful law sections. Fast-path bypasses:
- `complexity == simple` AND (`known_facts ≥ 1` OR `attempts ≥ 1`) → proceed
- `complexity == complex` AND (`attempts ≥ 2` OR `known_facts ≥ 3`) → proceed
- Has province + case_type + description ≥ 12 words + `known_facts ≥ 2` → proceed

Otherwise: LLM produces ONE targeted follow-up question using domain-specific templates (criminal / family / civil / constitutional). Returns `needs_clarification = True`, increments `clarification_attempts`.

Always routes → `retrieval_node` (interrupt() is handled outside this node in `clarification_node`).

### 5. `retrieval_node`
**File:** `app/ai/nodes/retrieval_node.py`  
**LLM:** `get_llm()` (for query rewrite only)

Two-hop hybrid retrieval:
1. **Alias normalization** — IPC→PPC, CrPC India→CrPC Pakistan, etc.
2. **Query rewrite** — LLM rewrites to formal Pakistani legal terminology (only used if output contains legal keywords).
3. **Hop 1** — `EnsembleRetriever`: BM25 (weight 0.6) + ChromaDB semantic (weight 0.4) with province filter (`province IN (user_province, "federal")`).
4. **Hop 2** — Extracts statute cross-references (PPC/CrPC/MFLO + section) from hop-1 results and runs a second retrieval to follow citations.
5. **RRF merge** — Reciprocal Rank Fusion deduplicates and merges both hops.

On retry (attempts > 1): appends `known_facts` to query for wider recall.  
Routes → `retrieval_grader_node`.

**ChromaDB collections:**

| Collection | Contents |
|---|---|
| `civil_collection` | CPC, contract law, property law |
| `criminal_collection` | PPC, CrPC, PECA 2016 |
| `family_collection` | MFLO 1961, family court rules, QSO 1984 |
| `constitutional_collection` | Constitution of Pakistan 1973 (chapters + articles) + LEGAL-UQA dataset (619 bilingual Q&A pairs → 924 chunks total) |

**Embeddings:** `intfloat/multilingual-e5-base` via `E5Embeddings` wrapper. `embed_documents()` adds `"passage: "` prefix internally; `embed_query()` adds `"query: "` prefix. **Never double-add these prefixes.**

### 6. `retrieval_grader_node`
**File:** `app/ai/nodes/retrieval_grader_node.py`  
**LLM:** `get_fast_llm()` (Gemini Flash)

Grades up to 8 chunks in a single LLM call. Returns binary relevance array `[1, 0, 1, ...]`. Filters out irrelevant chunks. Sets `relevance_score = kept/total`.

**`route_after_grader` logic:**
- `fact_delta == 0` AND `attempts > 1` → `generation_node` (re-running won't help)
- `score < 0.40` AND `budget left (< 3 attempts)` AND `still improving (delta > 0.05)` → retry `retrieval_node`
- Otherwise → `generation_node`

### 7. `generation_node`
**File:** `app/ai/nodes/generation_node.py`  
**LLM:** `get_llm()` (Groq 70B)

IRAC-structured answer (Issue / Applicable Law / Legal Analysis / Conclusion / Recommended Actions / Risks). Separate English and Urdu system prompts. Uses `normalized_query` (standard Urdu script) for generation.

On retry (attempts > 1): uses only top 4 chunks for stricter grounding.  
Appends `DISCLAIMER` footer. Extracts `{"confidence": float}` JSON from last line of response.  
Builds `citations` list from `reranked_chunks` metadata.  
Routes → `hallucination_node`.

### 8. `hallucination_node`
**File:** `app/ai/nodes/hallucination_node.py`  
**LLM:** `get_fast_llm()` (Gemini Flash)

Validates answer grounding against top-5 `reranked_chunks`. Returns `GroundingOutput(is_grounded, reason)`.

If not grounded: degrades confidence to `max(conf * 0.5, 0.2)`, appends caution note.

**`route_after_hallucination` logic:**
- `is_grounded == True` → `finalizer_node`
- `budget left (< 2 attempts)` AND `still improving (delta > 0.05)` → retry `generation_node`
- Otherwise → `finalizer_node`

### 9. `finalizer_node`
**File:** `app/ai/nodes/finalizer_node.py`  
**LLM:** None

Three cases:
1. `convergence_status == off_topic` — sanitise and return canned answer.
2. No answer generated — return refuse message, set `convergence_status = max_attempts`.
3. Normal — sanitise answer, set `convergence_status = converged` (grounded) or `max_attempts` (not grounded).

Sanitisation: strips prompt-leakage artifacts (System:/Human:/Assistant: prefixes), redacts CNIC (`\d{5}-\d{7}-\d`) and phone numbers, collapses blank lines.  
Writes final answer to `messages` as `AIMessage` (picked up by `MemorySaver`).

---

## Intake Graph

Simpler 4-node graph used only by `intake_service.convert_to_case()`:

```
retrieval_node → retrieval_grader_node
    ├─ relevance < 0.40 AND attempts < 2 → retrieval_node (retry once)
    └─ ok → intake_node → intake_hallucination_node → END
```

`intake_node` and `intake_hallucination_node` are separate from the chat nodes — they produce a structured JSON case summary (`summary`, `applicable_laws`, `recommended_actions`, `risk_level`) instead of a markdown answer.

---

## WebSocket Handler (`chat_socket.py`)

Key behaviours:

1. **Intent pre-detection** — before `ainvoke`, runs `asyncio.to_thread(_detect_intent, query, last_ai_content)` using DB message history. If `intent ∈ {format, deepen}` with confidence ≥ 0.65, injects into `state["followup_intent"]` so `triage_node` skips the full LLM call.
2. **Interrupt resume** — checks `aget_state()` for pending interrupt before each turn. If one exists, resumes with `Command(resume=query)` instead of a fresh `ainvoke`.
3. **Result reading** — always reads final state from `post_snapshot.values` (checkpointer), not ainvoke return value.
4. **DB history seed** — `_extract_last_ai(session)` seeds `last_ai_content` from MongoDB on reconnect so intent detection works from the first message of a new WebSocket connection.
5. **`case_type: "unknown"`** — always reset each turn so `classifier_node` re-scores the fresh query.

---

## Intake Service (`intake_service.py`)

- **`get_clarification()`** — multi-round (up to 4) LLM-powered clarification during intake steps 3-4. Uses `_CLARIFY_SYSTEM` prompt with domain-specific templates. LLM exception → `done=True` (never traps user in a loop).
- **`convert_to_case()`** — creates case, runs `intake_graph`, embeds case description (P1), auto-matches top-5 lawyers (P5). Returns `ai_case_type` from `_classify_description()`.
- **`_classify_description()`** — reuses `classifier_node._score_query()` to keyword-score the final intake description and return the dominant case type string.

---

## AgentState Key Fields

| Field | Type | Notes |
|-------|------|-------|
| `query` | `str` | Raw user input |
| `normalized_query` | `str` | Roman Urdu → Urdu script; EN unchanged |
| `case_type` | `str` | `civil\|criminal\|family\|constitutional\|unknown` |
| `classifier_confidence` | `float` | Keyword-based confidence (0–1) |
| `routing_mode` | `str` | `single\|hybrid` |
| `followup_intent` | `str\|None` | `format\|deepen\|affirm\|new\|None` |
| `province` | `str` | `punjab\|sindh\|kpk\|balochistan\|federal\|unknown` |
| `language` | `str` | `en\|ur\|roman_urdu` |
| `relevance_score` | `float` | Fraction of graded chunks kept |
| `retrieval_attempts` | `int` | Max 3 (chat), max 2 (intake) |
| `generation_attempts` | `int` | Max 2 |
| `clarification_attempts` | `int` | Persisted across turns via `chat_repo` |
| `convergence_status` | `str` | `pending\|converged\|needs_clarification\|max_attempts\|off_topic` |
| `is_grounded` | `bool` | Set by `hallucination_node` |
| `messages` | `list[BaseMessage]` | Append-only; managed by `MemorySaver` |

---

## Thresholds (edges.py)

| Constant | Value | Meaning |
|----------|-------|---------|
| `_RELEVANCE_THRESHOLD` | 0.40 | Below → retry retrieval if budget allows |
| `_CONVERGENCE_MIN_DELTA` | 0.05 | Improvement below this → stop retrying |
| `_MAX_RETRIEVAL_ATTEMPTS` | 3 | Chat graph retrieval budget |
| `_MAX_INTAKE_RETRIEVAL_ATTEMPTS` | 2 | Intake graph retrieval budget |
| `_MAX_GENERATION_ATTEMPTS` | 2 | Generation retry budget |
| `_CLASSIFIER_CONFIDENCE_THRESHOLD` | 0.85 | Above → skip triage clarification |
| `_OVERLAP_THRESHOLD` | 0.15 | 2+ categories above this → hybrid routing |
