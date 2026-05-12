# Attorney.AI — Pipeline Context & Architecture Decisions

> Last updated: 2026-05-12  
> Session: Muhammad Usama (SP23-BCS-069) — FYP

---

## LLM Provider Strategy

### Current State (`LLM_PROVIDER=groq` in `.env`)

| Node | Function | Provider | Model | Reason |
|---|---|---|---|---|
| `generation_node` | Full IRAC legal answer | Groq | `llama-3.3-70b-versatile` | Quality — needs 70B reasoning |
| `triage_node` | Legal intent + category | Gemini Flash | `gemini-2.0-flash` | `get_fast_llm()` |
| `_detect_intent` (via triage) | format/deepen/affirm/new | Gemini Flash | `gemini-2.0-flash` | `get_fast_llm()` |
| `retrieval_grader_node` | Binary relevance grading | Gemini Flash | `gemini-2.0-flash` | `get_fast_llm()` |
| `hallucination_node` | Grounding check | Gemini Flash | `gemini-2.0-flash` | `get_fast_llm()` |
| `clarification_node` | Question generation | Gemini Flash | `gemini-2.0-flash` | `get_fast_llm()` |
| `fact_gap_node`, `intake_node`, `gatekeeper_node`, `retrieval_node` | Various | Groq (via `get_llm()`) | `llama-3.3-70b-versatile` | Unchanged |

### `llm.py` exports
```python
get_llm()       # Routes via LLM_PROVIDER env var (currently Groq 70B)
get_fast_llm()  # Always Gemini 2.0 Flash — ignores LLM_PROVIDER
```

### Recommended Next Step: Provider-Per-Node Split

**Problem:** All control nodes share one Gemini Flash quota (15 RPM / 1500 req/day).  
Control nodes are high-frequency, low-value, rate-limit sensitive.

**Recommended architecture:**

```python
get_triage_llm()   # Groq llama-3.1-8b-instant  — intent + triage (fastest, 30 RPM)
get_grader_llm()   # Gemini Flash                — structured JSON grading
get_clarify_llm()  # Groq mixtral-8x7b           — question generation (better instruction-following)
```

**Node assignment after split:**

| Node | Function | →  Target |
|---|---|---|
| `triage_node`, `_detect_intent` | Classification | `get_triage_llm()` → Groq 8B instant |
| `retrieval_grader_node`, `hallucination_node` | Grading | `get_grader_llm()` → Gemini Flash |
| `clarification_node` | Question gen | `get_clarify_llm()` → Groq Mixtral |

**Required `.env` keys for this:**
```
GROQ_API_KEY=...         # already present
GEMINI_API_KEY=...       # needs to be filled
```

---

## Follow-up Intent Pipeline

### Problem Solved
`triage_node` was calling `_detect_intent(query, last_ai)` but `last_ai` was always `None` because `_build_state()` in `chat_socket.py` creates a fresh state with only the current `HumanMessage` — no history.

### Fix Applied
1. `chat_socket.py` seeds `last_ai_content` from MongoDB session history on connect.
2. Before every `ainvoke`, it calls `_detect_intent(query, last_ai_content)` via `asyncio.to_thread`.
3. If intent is `format` or `deepen` with confidence ≥ 0.65, sets `state["followup_intent"]` before passing to graph.
4. `triage_node` checks `state.get("followup_intent")` first — if pre-set, returns immediately (no LLM call, no risk of overwrite).
5. `last_ai_content` is updated after every turn.

### Intent Routing (in `edges.py`)
```
format  → generation_node directly (skip retrieval, reformat existing chunks)
deepen  → normal flow (re-retrieval with existing context)
affirm  → finalizer (canned "Understood. Any follow-up?" response)
new     → full triage pipeline
```

---

## Case Classification (Intake)

### Problem Solved
User filing for `khula` (family law) was seeing "Civil" because:
- Frontend default `caseTypeInput = "civil"`
- `_classify_description()` was called in `intake_service.py` but the function didn't exist → `NameError`

### Fix Applied
- Added `_classify_description(description)` to `intake_service.py` — calls `_score_query` from `classifier_node`, picks highest-scoring `CaseType`, falls back to `"civil"` on zero score.
- `IntakeResponse` schema now includes `ai_case_type: str | None = None`.
- Frontend `ModIntake.jsx`: after convert, reads `converted.ai_case_type` → calls `setCaseTypeInput(ai_case_type)` if not `"unknown"`.
- `CaseContext.jsx`: `completeIntake` now derives `caseRef` from real `caseId` instead of hardcoded `"AIQ-2026-0042"`.

---

## Frontend Hardcoded Items Fixed

| File | Was | Now |
|---|---|---|
| `CaseContext.jsx` | `caseRef: "AIQ-2026-0042"` | `caseRef: null`, derived from `caseId` on complete |
| `ModIntake.jsx` step 2 nav | `📁 Case AIQ-2026-0042` | `📁 Draft · …<token tail>` |
| Step 4 header | Stub "Edit All" + "Save" buttons | Removed |
| Step 4 AI laws | Stub "✏️ Edit" per law | Removed |
| Step 5 banner | "AI identified" (was manual pick) | "AI classified" only when `caseId` exists |
| Step 5 sidebar | Stub PDF/Email/Print card | Removed |
| Step 2 nav | Stub "💾 Save Draft" | Removed |

---

## Fail-Closed Fixes

| File | Issue | Fix |
|---|---|---|
| `intake_service.py` `get_clarification()` | On LLM exception: returned `done: False` with fallback question, trapping user in loop | Now returns `done: True` so user can proceed to convert |
| `hallucination_node.py` | ✅ Already correct — returns `is_grounded: False` + caution + degraded confidence on exception | No change needed |

---

## PR #1 Claims vs Reality

10 of 11 claims from the PR audit were **already fixed** in the codebase. Only real gaps:
1. `done: False` on clarification LLM exception — **fixed this session**
2. Query expansion validation in `retriever.py` — **still missing**, not implemented

---

## Environment

```
# backend/.env critical keys
LLM_PROVIDER=groq             # generation_node uses this
GROQ_API_KEY=...              # for get_llm() → Groq 70B
GEMINI_API_KEY=               # REQUIRED for get_fast_llm() — fill this in
```

---

## Key Files Reference

```
backend/
  app/ai/llm.py                        # get_llm() + get_fast_llm()
  app/ai/graph/
    state.py                           # AgentState — followup_intent field at Layer 9
    edges.py                           # route_after_triage handles format/affirm
    supervisor.py                      # chat_graph + intake_graph
  app/ai/nodes/
    triage_node.py                     # LLM intent + legal triage; uses get_fast_llm()
    generation_node.py                 # IRAC generation; uses get_llm() (Groq 70B)
    retrieval_grader_node.py           # Binary grading; uses get_fast_llm()
    hallucination_node.py              # Grounding check; uses get_fast_llm()
    clarification_node.py              # Question gen; uses get_fast_llm()
    classifier_node.py                 # Keyword classifier; NO LLM
  app/ai/pipelines/retriever.py        # BM25 + Chroma ensemble; province filter
  app/services/intake_service.py       # _classify_description() for ai_case_type
  app/websockets/chat_socket.py        # last_ai_content seeded from DB; intent pre-check
frontend/
  src/components/client/ModIntake.jsx  # reads ai_case_type from convert response
  src/components/shared/CaseContext.jsx # caseRef derived from real caseId
```
