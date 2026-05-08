# Attorney.AI — Intake & Lawyer Matching Pipeline

**As-built documentation** | Last verified: E2E test 2026-05-08 — 30/30 PASS in 98.4s

---

## 1. High-Level Flow

```
Client fills 5 intake steps
        │
        ▼
AI Clarification (up to 4 rounds, LLM-driven, server-side)
        │
        ▼
POST /intake/{token}/convert
        │
        ├── P1 (async)  _embed_case()        → case 768-dim vector → MongoDB
        ├── (blocking)  intake_graph.ainvoke  → ai_structured_case → MongoDB
        └── P5 (async)  _auto_match_lawyers() → top-5 cached on case doc → MongoDB
                │
                ▼
Client polls GET /lawyers/match/{case_id}
```

---

## 2. API Endpoints

All under `/api/v1`. Requires `Authorization: Bearer <JWT>` (client role) unless noted.

### Intake Routes

| Method | Path | Auth | Request Body | Response |
|--------|------|------|-------------|----------|
| POST | `/intake/start` | client | — | `{ session_token, message }` |
| PATCH | `/intake/{token}/step/{1-5}` | client | `{ data: {...} }` | `{ session_token, current_step, completed, case_id }` |
| POST | `/intake/{token}/clarify` | client | `{ answer: string \| null }` | `{ question, done, round }` |
| POST | `/intake/{token}/convert` | client | `{ language?: "en"\|"ur", urgency?: string }` | `{ session_token, current_step, completed, case_id }` |
| GET | `/intake/{token}` | client | — | `{ session_token, current_step, completed, case_id, ai_structured_case }` |

### Lawyer Routes

| Method | Path | Auth | Query / Body | Response |
|--------|------|------|-------------|----------|
| GET | `/lawyers` | any auth | `?province=&case_type=&min_rating=&availability=&page=&page_size=` | `{ items, total, page, page_size }` |
| GET | `/lawyers/match/{case_id}` | client | — | `[ { _id, full_name, province, match_score, match_reason, lawyer_profile, ... } ]` |
| POST | `/lawyers/{lawyer_id}/review` | client | `{ stars: 1–5, comment?: string }` | `{ success, message }` |
| POST | `/lawyers/{lawyer_id}/embed` | admin | — | `{ success, message }` |

---

## 3. Intake Step Schema

| Step | Required fields | Optional fields |
|------|----------------|----------------|
| 1 | `province` (enum: punjab\|sindh\|kpk\|balochistan\|federal) | — |
| 2 | `case_type` (criminal\|civil\|family\|constitutional), `urgency` | — |
| 3 | `incident_description` | `incident_date`, `incident_location` |
| 4 | — | `has_evidence` (bool), `evidence_description`, `opposing_party` |
| 5 | `desired_outcome` | `additional_notes` |

---

## 4. Multi-Round AI Clarification

**File:** `backend/app/services/intake_service.py`

`_MAX_CLARIFY_ROUNDS = 4`

State stored in MongoDB: `intake.clarification_qa: [{ q: str, a: str | null }]`

### LLM System Prompt (`_CLARIFY_SYSTEM`)

```
You are a Pakistani legal intake specialist. The user has described their legal issue.

Based on the context below, decide if any CRITICAL fact is still missing.
If all key facts are present, respond with exactly: DONE

Otherwise, ask the ONE most important missing question using the domain templates as a guide.
Ask in the same language the user used (English or Urdu). No explanations — just the question.
```

### Domain Fact Templates (`_CLARIFY_TEMPLATES`)

| case_type | Key missing facts |
|-----------|------------------|
| criminal | FIR filed + police station; nature/severity of harm; witnesses; exact date + location |
| family | MFLO 1961 marriage registration; children ages; Mehr amount; divorce/custody/inheritance/maintenance |
| civil | Written contract or registered agreement; proof of ownership; disputed amount/property value; formal legal notice |
| constitutional | Which fundamental right (Constitution 1973); responsible government authority; prior writ petition; individual vs public interest |

### Round Logic

```
Call 1:  answer=null
         → LLM invoked with description + template
         → returns Q1 or "DONE"

Call 2:  answer=A1
         → backend saves A1 to qa[-1].a
         → LLM invoked with description + Q1+A1 history + template
         → returns Q2 or "DONE"

...up to 4 rounds...

Force-stop: answered_rounds >= _MAX_CLARIFY_ROUNDS (4)
Early-stop: LLM response starts with "DONE" (case-insensitive prefix)
LLM error:  returns { done: true } silently (fail-safe)
```

Context sent to LLM each round:
```
Case type: {case_type}
Province:  {province}
Description: {incident_description}
Previous Q&A:
  Q1: ...   A1: ...
  Q2: ...   A2: ...
Domain key facts:
  {_CLARIFY_TEMPLATES[case_type]}
```

---

## 5. Convert Flow

**File:** `backend/app/services/intake_service.py :: convert_to_case()`

```
1. Validate all 5 steps present (none is None) — raises 422 if missing
2. Build enriched description (server-side):
     base = step3.incident_description
     for each answered Q&A in clarification_qa:
         base += "\n\nAdditional context from intake:\nQ: {q}\nA: {a}"
3. create_case() → MongoDB insert → returns { _id: case_id }
4. asyncio.create_task(_embed_case(case_id, enriched_desc))   ← P1, fire-and-forget
5. await _run_intake_ai(...)                                   ← BLOCKING (30–120s)
6. intake_repo.save_ai_structured_case(token, ai_data)
7. asyncio.create_task(_auto_match_lawyers(case_id))           ← P5, fire-and-forget
8. intake_repo.mark_completed(token, case_id)
9. Return { session_token, current_step: 5, completed: true, case_id }
```

### P1 — `_embed_case(case_id, description)`

- Model: `intfloat/multilingual-e5-base` via `_embeddings()` (supports Urdu + English)
- Input prefix: `"query: " + description[:512]`
- Output: 768-dim float vector stored as `case.case_embedding` in MongoDB
- Non-critical — silent pass on any exception

### P5 — `_auto_match_lawyers(case_id)`

Calls `match_lawyers_for_case(case_id, top_n=5)` and caches slim results on the case doc:

```json
{
  "lawyer_id":       "...",
  "full_name":       "Adv. Zafar Iqbal",
  "province":        "punjab",
  "match_score":     0.883,
  "match_reason":    "strong profile match; specializes in criminal; available now; 14 yrs experience",
  "rating":          4.5,
  "specializations": ["criminal", "family"],
  "availability":    true
}
```

Stored via `case_repo.set_matched_lawyers(case_id, slim_list)`. Non-critical — silent pass.

---

## 6. LangGraph — `intake_graph`

**File:** `backend/app/ai/graph/supervisor.py :: build_intake_graph()`

### Node Chain

```
retrieval_node
    └── retrieval_grader_node
            ├── relevance < 0.4  AND  retrieval_attempts < 2  →  retrieval_node  (retry once)
            └── ok  ──►  intake_node
                              └──  intake_hallucination_node  →  END
```

Entry point: `retrieval_node` (no triage, no fact_gap — those are chat graph only).

### State Passed to `intake_graph.ainvoke(state)`

```python
{
    "query":               enriched_description,   # desc + all clarification Q&A
    "case_type":           "criminal",
    "province":            "punjab",
    "urgency":             "high",                 # from /convert body or step2.urgency
    "language":            "en",
    "session_id":          intake_session_token,
    "case_id":             case_id,
    "retrieved_chunks":    [],
    "reranked_chunks":     [],
    "relevance_score":     1.0,
    "retrieval_attempts":  0,
    "generation_attempts": 0,
    "answer":              "",                     # JSON string on graph exit
    # ... full AgentState fields with zero-values
}
```

### Output

`result["answer"]` — parsed with `json.loads()`:

```json
{
  "summary":             "One-paragraph summary of the legal situation.",
  "applicable_laws":     ["PPC Section 352 — Assault", "CrPC Section 497 — Bail"],
  "recommended_actions": ["File FIR at nearest police station", "Apply for bail under CrPC 497"],
  "risk_level":          "high"
}
```

Valid `risk_level` values: `low`, `medium`, `high`, `urgent`

**Fallback** (any exception during `ainvoke`):

```json
{
  "summary": "AI structuring unavailable — case created successfully.",
  "applicable_laws": [],
  "recommended_actions": ["Consult a qualified Pakistani lawyer for advice."],
  "risk_level": "medium"
}
```

### Multi-hop RAG (inside `retrieval_node`)

```
Hop 1: Semantic search on enriched description → top-K chunks from ChromaDB (legal_kb)
Hop 2: Extract statute refs from Hop-1 results via regex (PPC \d+, CrPC \d+, MFLO \d+, etc.)
       → targeted queries per statute → additional chunks
Final: Merge all chunks with RRF (Reciprocal Rank Fusion) → reranked_chunks → intake_node
```

---

## 7. Chat Graph (separate — WebSocket chatbot)

**File:** `backend/app/ai/graph/supervisor.py :: build_chat_graph()`

7-node graph with HITL breakpoint and convergence control. NOT used in intake convert flow.

```
triage_node
    ├── off_topic  ──────────────────────────────────────►  finalizer_node → END
    └── legal  ──►  fact_gap_node
                      ├── needs_clarification  ───────────►  END  (HITL breakpoint)
                      └── proceed  ──►  retrieval_node
                                          └──  retrieval_grader_node
                                                   ├── poor + budget  ──►  retrieval_node (≤3 retries)
                                                   └── ok  ──►  generation_node
                                                                    └──  hallucination_node
                                                                             ├── not grounded  ──►  generation_node (≤2 retries)
                                                                             └── done  ──►  finalizer_node → END
```

Uses `MemorySaver` checkpointer for multi-turn conversation state.

---

## 8. Lawyer Matching Pipeline

**File:** `backend/app/services/lawyer_service.py :: match_lawyers_for_case()`

### Multi-factor Scoring Formula

```
final_score = semantic_score × 0.50
            + spec_boost     × 1.0    # 0.20 exact match, 0.10 related-term match
            + (rating / 5.0) × 0.15
            + availability   × 0.10   # bool: 1.0 if available
            + min(exp / 20.0, 1.0) × 0.05
```

### Specialization Boost (`_RELATED_TERMS`)

| case_type | Exact match (spec_boost = 0.20) | Related term match (spec_boost = 0.10) |
|-----------|---------------------------------|---------------------------------------|
| criminal | "criminal" in lawyer specializations | penal, defense, fir, bail, crime, prosecution |
| civil | "civil" | property, contract, dispute, possession, rent |
| family | "family" | divorce, custody, marriage, inheritance, khula |
| constitutional | "constitutional" | rights, fundamental, constitution, writ |

### Three-tier Fallback

```
Tier 1 (primary):
    → ChromaDB semantic search (province filter, n_results = top_n × 4)
    → fetch full lawyer docs from MongoDB
    → filter: kyc_verified=true AND is_active=true
    → apply multi-factor score
    → sort descending

Tier 2 (Chroma empty):
    → MongoDB find_lawyers(province, case_type, min_rating=0)
    → apply multi-factor score with semantic_score=0.3
    → sort descending

Tier 3 (still empty — last resort):
    → MongoDB find_lawyers(no filters)  OR  find_many({role: "lawyer", is_active: true})
    → NO kyc_verified requirement
    → apply multi-factor score with semantic_score=0.1
    → match_reason appended with " (unverified)"
    → sort descending
```

`_sanitize()` always strips `password_hash` and `cnic_encrypted` before returning.

### Lawyer ChromaDB Embedding

- Admin `POST /lawyers/{id}/embed` → `embed_lawyer(lawyer_id)` in `app/ai/lawyer_embeddings.py`
- Embeds lawyer bio + specializations + province text into ChromaDB collection `lawyers`
- Required for Tier 1 semantic matching

---

## 9. Frontend — Intake Module

**File:** `frontend/src/components/client/ModIntake.jsx`

### localStorage Keys

| Key | Value |
|-----|-------|
| `aai-intake-token` | Intake session token from `POST /intake/start` |
| `aai-case-id` | Case ID from `POST /convert` response |

### Clarification Round State (`clarifyRound`)

```
0  →  initial / loading (waiting for first POST /clarify with answer=null)
1  →  Q1 displayed to user
2  →  Q2 displayed to user
3  →  Q3 displayed to user
4  →  Q4 displayed to user
5  →  done (backend returned done=true or round >= 4)
```

### Step 2 Right Panel (Evidence + Desired Outcome)

Real data collected here, sent in convert handler:
- `hasEvidence` (bool) — Yes/No toggle buttons
- `evidenceDesc` (string) — textarea, visible only when `hasEvidence === true`
- `desiredOutcome` (string) — textarea

### Convert Handler (`handleConvertAndSummarise`)

```
1. intakeSaveStep(token, 4, {
       has_evidence: hasEvidence,
       evidence_description: evidenceDesc.trim() || null,
       opposing_party: null
   })
2. intakeSaveStep(token, 5, {
       desired_outcome: desiredOutcome.trim() || "Legal assistance and representation",
       additional_notes: null
   })
3. intakeConvert(token, { language: "en", urgency: step2_urgency })
4. localStorage.setItem("aai-case-id", case_id)
5. intakeGet(token) → display ai_structured_case in step 4
```

---

## 10. Frontend — Lawyer Module

**File:** `frontend/src/components/client/ModLawyers.jsx`

### Filter → Backend Wiring

Debounced effect (400ms delay) on `[filters.city, filters.specialization, filters.rating, filters.availability]`.

If all filters at defaults → skips fetch (no unnecessary API call).

Translation maps (UI display values → API enum values):

```js
CITY_TO_PROVINCE = {
    lahore/rawalpindi/multan/faisalabad  →  "punjab"
    karachi/hyderabad                   →  "sindh"
    islamabad                           →  "federal"
    peshawar                            →  "kpk"
    quetta                              →  "balochistan"
    punjab/sindh/kpk/balochistan/federal →  pass-through
}

SPEC_TO_CASE_TYPE = {
    "employment law" / "civil rights" / "contract" / "property"  →  "civil"
    "criminal defense" / "criminal"                               →  "criminal"
    "family law" / "family"                                       →  "family"
    "constitutional"                                              →  "constitutional"
    "civil"                                                       →  "civil"
}
```

Calls `searchLawyers({ province, case_type, min_rating, availability, page_size: 20 })`.

### AI Match Tab

```
1. case_id = localStorage.getItem("aai-case-id")
2. matchLawyers(case_id) → GET /lawyers/match/{case_id}
3. Response: sorted list with match_score + match_reason
4. Top match displayed in banner
```

### Review Form

```
"Write a Review" button → shows:
  - 5-star SVG selector (reviewStars state, default 5)
  - Comment textarea (reviewComment state)
  - Submit button → submitUserReview(lawyer._id)

submitUserReview(lawyerId):
  1. Guard: !lawyerId || lawyerId.startsWith("api-") → warn toast
  2. submitReview(lawyerId, reviewStars, reviewComment.trim() || null)
  3. On success: success toast + reset (showReviewForm=false, stars=5, comment="")
```

---

## 11. Frontend — Auth Module

**File:** `frontend/src/app/(auth)/login/page.jsx`

- Sends `POST /auth/login` with `{ email, password }` only — no role field
- Role is determined server-side from user document
- On success: stores JWT → `aai-token`, role → `aai-role`, user_id → `aai-uid`
- `AuthContext` auto-hydrates from `GET /users/me` on page load
- `ProtectedRoute` gates `client` and `lawyer` routes by `aai-role`

---

## 12. Data Models (MongoDB)

### Intake Document

```json
{
  "_id": "...",
  "session_token": "...",
  "client_id": "...",
  "current_step": 5,
  "completed": true,
  "step1": { "province": "punjab" },
  "step2": { "case_type": "criminal", "urgency": "high" },
  "step3": {
    "incident_description": "My landlord physically assaulted me... [enriched with Q&A on backend]",
    "incident_date": "2026-05-05",
    "incident_location": "Gulberg, Lahore, Punjab"
  },
  "step4": { "has_evidence": true, "evidence_description": "Medical cert + injury photos" },
  "step5": { "desired_outcome": "File FIR, criminal charges under PPC 352/337" },
  "case_id": "...",
  "clarification_qa": [
    { "q": "Has an FIR been filed? At which police station?", "a": "Not yet filed." },
    { "q": "What is the nature and severity of the injuries?", "a": "Facial and arm injuries, treated at Services Hospital." }
  ],
  "ai_structured_case": {
    "summary": "Client was physically assaulted by landlord...",
    "applicable_laws": ["PPC Section 352 — Assault", "CrPC Section 154 — FIR Registration"],
    "recommended_actions": ["File FIR at nearest police station", "Obtain medical certificate"],
    "risk_level": "high"
  }
}
```

### Case Document

```json
{
  "_id": "...",
  "client_id": "...",
  "case_type": "criminal",
  "province": "punjab",
  "title": "My landlord physically assaulted me on 5 May 2026...",
  "description": "Full enriched description + Q&A appended by backend",
  "intake_id": "...",
  "case_embedding": [0.023, -0.114, ...],
  "matched_lawyers": [
    {
      "lawyer_id": "e2e-lawyer-seed-001",
      "full_name": "Adv. Zafar Iqbal",
      "province": "punjab",
      "match_score": 0.883,
      "match_reason": "strong profile match; specializes in criminal; available now; 14 yrs experience",
      "rating": 4.5,
      "specializations": ["criminal", "family"],
      "availability": true
    }
  ]
}
```

---

## 13. Key Files Reference

| File | Role |
|------|------|
| `frontend/src/components/client/ModIntake.jsx` | 5-step intake UI, clarification rounds, convert |
| `frontend/src/components/client/ModLawyers.jsx` | Lawyer search, AI match, review submission |
| `frontend/src/components/client/ModChatbot.jsx` | Chat UI + HITL lawyer connect card |
| `frontend/src/lib/api.js` | All API wrappers: `intakeStart`, `intakeSaveStep`, `intakeClarify`, `intakeConvert`, `intakeGet`, `searchLawyers`, `matchLawyers`, `submitReview` |
| `backend/app/api/v1/routes/intake.py` | REST routes for intake |
| `backend/app/api/v1/routes/lawyers.py` | REST routes for lawyers |
| `backend/app/services/intake_service.py` | Business logic: clarification, convert, embed, auto-match |
| `backend/app/services/lawyer_service.py` | Multi-factor scoring, 3-tier fallback matching |
| `backend/app/ai/graph/supervisor.py` | `build_intake_graph()` + `build_chat_graph()` |
| `backend/app/ai/nodes/retrieval_node.py` | Multi-hop RAG with RRF merge |
| `backend/app/ai/nodes/retrieval_grader_node.py` | Relevance quality gate |
| `backend/app/ai/nodes/intake_node.py` | Structured JSON output (summary, laws, actions, risk) |
| `backend/app/ai/nodes/intake_hallucination_node.py` | Grounding check on intake output |
| `backend/app/ai/nodes/triage_node.py` | Language detection, case_type, complexity, urgency (chat only) |
| `backend/app/ai/nodes/fact_gap_node.py` | HITL clarification decision + domain templates (chat only) |
| `backend/app/ai/lawyer_embeddings.py` | `embed_lawyer()` — lawyer profile → ChromaDB |
| `backend/app/repositories/intake_repo.py` | MongoDB intake CRUD |
| `backend/app/repositories/case_repo.py` | `set_embedding()`, `set_matched_lawyers()` |
| `backend/test_full_e2e.py` | Full E2E validation (30/30 PASS, 98.4s) |

---

## 14. E2E Test Validation Results

**File:** `backend/test_full_e2e.py` | **Date:** 2026-05-08

```
Result: 30/30 PASS in 98.4s

Test scenario: Physical assault by landlord, Gulberg Lahore, criminal case, Punjab province

  Convert time:           32.2s
  Clarification rounds:   4 rounds, distinct questions each round
  Top lawyer match score: 0.883  (Adv. Zafar Iqbal, criminal specialist, 14yr exp, KYC verified)
  Match reason:           "strong profile match; specializes in criminal; available now; 14 yrs experience"
  CrPC statute reference: FOUND in ai_structured_case.applicable_laws
  PPC statute reference:  FOUND in ai_structured_case.applicable_laws
  password_hash in response: NO
  cnic_encrypted in response: NO
```

---

*Attorney.AI — SP23-BCS-069 COMSATS | Pakistani law coverage only*
