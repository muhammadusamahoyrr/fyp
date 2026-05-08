# Attorney.AI — Current State
> SP23-BCS-069 | Muhammad Usama | COMSATS | May 2026
> Read this at the start of every new session.

---

## Project Summary

AI-powered legal assistance platform for Pakistani citizens. FYP project.
- **Backend:** FastAPI + Motor (MongoDB) — COMPLETE
- **AI Pipeline:** LangGraph agentic RAG — COMPLETE & VERIFIED RUNNING
- **Knowledge Base:** 2,357 law chunks in ChromaDB — INGESTED
- **Lawyer Matching:** Embedding-based multi-factor scoring — COMPLETE
- **Frontend:** Next.js 15 App Router — UI COMPLETE, API wiring NOT DONE

---

## 1. Non-AI Backend — COMPLETE (April 2026)

**68 Python files, 0 syntax errors.** Full layered FastAPI application.

```
backend/app/
├── core/         config.py, constants.py, security.py, exceptions.py, rate_limit.py
├── db/           mongodb.py, indexes.py, collections.py
├── models/       user, case, intake, document, agreement, notification, chat
├── schemas/      auth, user, case, intake, lawyer, document, agreement, admin, common
├── repositories/ base.py + user, case, intake, document, agreement, notification, chat repos
├── services/     auth, user, case, intake, lawyer, document, agreement, notification, admin
├── api/v1/routes/auth, users, cases, intake, lawyers, documents, agreements, notifications, admin
├── websockets/   manager.py, notification_socket.py, chat_socket.py
└── utils/        validators.py, file_handler.py, email.py
```

### Security
| Concern | Implementation |
|---|---|
| Passwords | bcrypt cost 12 |
| Access token | JWT 60-min, `Authorization: Bearer` |
| Refresh token | JWT 7-day, `httpOnly; Secure; SameSite=Strict` cookie |
| Token revocation | MongoDB blocklist, TTL 7-day index |
| CNIC at rest | AES-256 Fernet encryption |
| Rate limiting | slowapi: login/register 5/min, forgot-password 3/min |
| File uploads | Extension whitelist (.pdf .jpg .jpeg .png .docx), 10 MB cap |
| Reset tokens | MongoDB TTL 1-hour index |

### Enums (`core/constants.py`)
- `UserRole`: client, lawyer, admin
- `CaseType`: civil, criminal, constitutional, family
- `Province`: punjab, sindh, kpk, balochistan, federal
- `CaseStatus`: draft, open, in_progress, pending_lawyer, closed, dismissed
- `SignatureMethod`: canvas, typed, image_upload
- `AgreementStatus`: draft, pending, executed, cancelled

### MongoDB Indexes (`db/indexes.py` — runs at startup)
- `users`: email (unique), cnic_encrypted (unique sparse), role, province, kyc_verified
- `cases`: case_number (unique), client_id, lawyer_id, status, case_type, province
- `intakes`: session_token (unique), client_id, completed
- `notifications`: user_id, read, created_at — **TTL 30 days**
- `refresh_token_blocklist`: token (unique) — **TTL 7 days**
- `password_reset_tokens`: token (unique), email — **TTL 1 hour**

---

## 2. REST API Routes — ALL COMPLETE

Base prefix: `/api/v1`

### Auth — `/auth`
| Method | Path | Rate Limit | Auth |
|---|---|---|---|
| POST | `/register` | 5/min | Public |
| POST | `/login` | 5/min | Public |
| POST | `/refresh` | 20/min | Refresh cookie |
| POST | `/logout` | — | Bearer |
| POST | `/forgot-password` | 3/min | Public |
| POST | `/reset-password` | 5/min | Public |

### Users — `/users`
| Method | Path | Auth |
|---|---|---|
| GET | `/me` | Any authenticated |
| PATCH | `/me` | Any authenticated |
| PATCH | `/me/lawyer-profile` | Any authenticated |
| GET | `/{user_id}` | Any authenticated |

### Cases — `/cases`
| Method | Path | Auth |
|---|---|---|
| POST | `/` | Any authenticated |
| GET | `/` | Any (scoped by role: own / assigned / all) |
| GET | `/{case_id}` | Owner / Assigned Lawyer / Admin |
| PATCH | `/{case_id}` | Owner / Assigned Lawyer / Admin |
| GET | `/{case_id}/timeline` | Owner / Assigned Lawyer / Admin |
| POST | `/{case_id}/milestones` | Lawyer only |
| POST | `/{case_id}/hearings` | Lawyer only |

### Intake — `/intake`
| Method | Path | Auth |
|---|---|---|
| POST | `/start` | Client only |
| PATCH | `/{token}/step/{1-5}` | Client only |
| GET | `/{token}` | Client only |
| POST | `/{token}/convert` | Client only — **triggers AI pipeline** |

Step validation: Step 1 needs `province`, Step 2 needs `case_type`+`urgency`, Step 3 needs `incident_description`, Step 5 needs `desired_outcome`.

### Lawyers — `/lawyers`
| Method | Path | Auth |
|---|---|---|
| GET | `/` | Any authenticated |
| GET | `/match/{case_id}` | Client only — **AI matching** |
| POST | `/{lawyer_id}/review` | Client only |
| POST | `/{lawyer_id}/embed` | Admin only — re-embed one lawyer |

### Documents — `/documents`
| Method | Path | Auth |
|---|---|---|
| POST | `/generate` | Any authenticated |
| GET | `/{doc_id}/download` | Owner only (FileResponse) |

### Agreements — `/agreements`
| Method | Path | Auth |
|---|---|---|
| POST | `/` | Any authenticated |
| GET | `/{agreement_id}` | Party members only |
| POST | `/{agreement_id}/sign` | Party members only |

ETO 2002 auto-classification: canvas → Advanced Electronic Signature, typed/image → Basic Electronic Signature.

### Notifications — `/notifications`
| Method | Path | Auth |
|---|---|---|
| GET | `/` | Any authenticated |
| PATCH | `/{notification_id}/read` | Owner only |
| POST | `/read-all` | Any authenticated |

### Admin — `/admin`
| Method | Path | Auth |
|---|---|---|
| GET | `/kyc/pending` | Admin only |
| PATCH | `/kyc/{lawyer_id}` | Admin only |
| GET | `/analytics/overview` | Admin only |
| POST | `/lawyers/embed-all` | Admin only — batch embed all KYC-verified lawyers |

---

## 3. WebSockets — BOTH WIRED

### `/ws/chat/{session_id}?token=<jwt>`
- JWT auth via query param (WebSocket headers are not browser-standard)
- Closes with code 4001 if token invalid
- **Wired to `chat_graph.ainvoke()`** with `MemorySaver(thread_id=session_id)` — persistent multi-turn memory per session
- Message protocol:

| Type | Direction | Payload |
|---|---|---|
| `thinking` | Server→Client | AI processing (show spinner) |
| `final` | Server→Client | `{content, citations, confidence}` |
| `clarification` | Server→Client | `{question}` — query too vague |
| `error` | Server→Client | `{content}` — AI unavailable |

- All messages persisted to MongoDB `chat_sessions` collection

### `/ws/notifications/{user_id}?token=<jwt>`
- On connect: sends `{type: "unread_count", count: N}`
- Receives push messages from `notification_service.create_notification()`
- `ConnectionManager` supports multiple browser tabs per user

---

## 4. AI Pipeline — COMPLETE & VERIFIED RUNNING (May 2026)

### Knowledge Base (one-time ingestion — DONE)

| Collection | Source PDFs | Chunks |
|---|---|---|
| `criminal_collection` | PPC 1860, CrPC 1898, Police Law | 1,735 |
| `civil_collection` | Transfer of Property Act, Limitation Act 1908 | 396 |
| `family_collection` | Muslim Family Laws Ordinance 1961, Qanun-e-Shahadat 1984 | 226 |
| **Total** | | **2,357** |

Ingestion pipeline: `backend/knowledge_base/pipeline/`
```
ingest.py   → pdfplumber page-by-page extraction
chunk.py    → section-aware regex (detects "Section 302", "S.302(a)") + 800-char/100-overlap fallback
embed.py    → intfloat/multilingual-e5-base, 768-dim, batch 64, "passage: " prefix
store.py    → ChromaDB upsert by chunk_id (idempotent, safe to re-run)
```

Chunk metadata carried: `chunk_id, content, section_number, statute, law_type, province, source_file`

### Embedding Model
`intfloat/multilingual-e5-base` — 768-dim, supports Urdu + English in the same space.
- Documents: `"passage: " + text`
- Queries: `"query: " + text`
- **Required by e5 model contract** — omitting prefixes degrades retrieval quality significantly
- `@lru_cache(maxsize=1)` — ~1.1 GB, loaded once per server process, never reloaded

### ChromaDB Path
`pathlib.Path(__file__).parents[2] / "chroma_data"` from `app/db/chroma.py`
→ `parents[2]` resolves to `backend/` → `backend/chroma_data/`
**Note:** `parents[3]` was a prior bug (resolved to repo root which is empty) — fixed to `parents[2]`.

### LLM Factory (`app/ai/llm.py`)
Switch via `LLM_PROVIDER=gemini|groq|ollama` in `.env`. Temperature 0.1 everywhere.

| Provider | Model | Notes |
|---|---|---|
| `gemini` | `gemini-2.0-flash` | Free tier, fast — default |
| `groq` | `llama-3.3-70b-versatile` | Free tier cloud. **`llama-3.1-70b` was decommissioned — use 3.3** |
| `ollama` | `llama3.1` | Fully local, no API key |

### Two LangGraph Graphs (`app/ai/graph/supervisor.py`)

**`intake_graph`** — triggered by `POST /intake/{token}/convert`
```
retrieval_node → intake_node → END
```

**`chat_graph`** — triggered by WebSocket messages
```
gatekeeper_node
    ├─ off-topic → END  (canned response, no retrieval)
    └─ legal → retrieval_node
                   ├─ relevance < 0.75 → clarification_node → END
                   └─ relevance ≥ 0.75 → generation_node → hallucination_node → END
```
Compiled with `MemorySaver()` — each `ainvoke` call restores checkpoint for `thread_id=session_id`.

### AgentState (`app/ai/graph/state.py`)
```python
query, session_id, case_id, case_type, province, language,
needs_clarification, clarification_question,
retrieved_chunks, reranked_chunks, relevance_score,
answer, citations, confidence, is_grounded,
messages  ← operator.add reducer (appends across invocations)
```

### Node Details

**`gatekeeper_node`** — classifies query as "legal" or "off_topic". Off-topic sets `answer` to canned response; `route_after_gatekeeper` edge reads non-empty `answer` → routes to END.

**`retrieval_node`** — hybrid retrieval:
1. LLM rewrites plain query to legal terminology (`_expand_query`)
   - `"My landlord beat me"` → `"My landlord beat me PPC assault causing hurt criminal force"`
2. BM25 retriever (k=10) + Chroma semantic retriever (k=10) run via `EnsembleRetriever`
3. Weights: BM25 0.6, Chroma 0.4 — BM25 heavier for statute-reference queries
4. Province filter on Chroma: `{province} OR federal`
5. `@lru_cache(maxsize=6)` on BM25 per collection — expensive to rebuild
6. `relevance_score = min(len(docs) / 10.0, 1.0)` — triggers clarification if < 0.75

**`clarification_node`** — LLM generates one focused clarifying question.

**`generation_node`** — formats top-8 chunks as numbered context (statute + content[:400]). Uses `SYSTEM_PROMPT_EN` or `SYSTEM_PROMPT_UR` based on `state["language"]`. LLM appends `{"confidence": 0.85}` on last line — stripped from displayed answer. Legal disclaimer appended to every response.

**`hallucination_node`** — LLM checks if answer claims are supported by retrieved chunks. If not grounded: appends caution note, sets `confidence = 0.35`. **Graceful degradation — never hard-refuses.** Answer is always returned.

**`intake_node`** — uses `.with_structured_output(IntakeOutput)` for guaranteed JSON:
```python
class IntakeOutput(BaseModel):
    summary: str
    applicable_laws: list[str]
    recommended_actions: list[str]
    risk_level: str  # "low" | "medium" | "high"
```

### Verified Sample Output (intake — landlord assault, Punjab)
```json
{
  "summary": "Landlord physically assaulted client in Punjab — criminal case.",
  "applicable_laws": [
    "PPC Section 324 — Voluntarily causing hurt by dangerous weapons",
    "PPC Section 506 — Punishment for criminal intimidation"
  ],
  "recommended_actions": [
    "File a First Information Report (FIR) with the police",
    "Seek medical attention and preserve evidence",
    "Consider obtaining a restraining order"
  ],
  "risk_level": "high"
}
```

### Intake Service Integration (`app/services/intake_service.py`)
`convert_to_case()` calls `_run_intake_ai()` which lazy-imports `intake_graph` and wraps in try/except:
- Success: `json.loads(result["answer"])` saved to `ai_structured_case`
- Failure: safe fallback dict — **case creation never blocked by AI failure**

### Known Bugs Fixed During Development
1. **BM25 wrong sections** — "beat me up" returned CrPC warrant forms. Fix: LLM query expansion.
2. **LLM auto-switched to Urdu** — Groq saw Pakistani legal context and switched languages. Fix: explicit `SYSTEM_PROMPT_EN` / `SYSTEM_PROMPT_UR`.
3. **Hallucination node rejected everything** — caused by (a) Urdu mismatch + (b) chunk metadata section numbers wrong. Fix: language-aware prompts + removed metadata section labels from context.
4. **ChromaDB empty** — `parents[3]` resolved to repo root. Fix: `parents[2]`.
5. **LangChain 1.x imports** — `langchain.schema.Document` → `langchain_core.documents.Document`, `langchain.retrievers.EnsembleRetriever` → `langchain_classic.retrievers.ensemble`.
6. **Groq model decommissioned** — `llama-3.1-70b-versatile` → `llama-3.3-70b-versatile`.
7. **Venv not activating in start.ps1** — Fix: `& "$PSScriptRoot\venv\Scripts\python.exe" -m uvicorn ...` instead of activating then calling uvicorn.

---

## 5. Lawyer Matching — COMPLETE (May 2026)

### Architecture
```
[Lawyer KYC approved / profile updated]
    → embed_lawyer(lawyer_id) → build_profile_text() → E5 "passage: " → ChromaDB lawyers_collection

[Client: GET /lawyers/match/{case_id}]
    → match_lawyers_for_case(case_id)
    → embed case description with E5 "query: "
    → Chroma similarity search with province filter (top 20)
    → multi-factor scoring → top 5 returned
```

### `app/ai/lawyer_embeddings.py`
- `build_profile_text(lawyer, recent_cases)` — concatenates: specializations + province + experience + bio + last 5 case summaries (from EF_in_Legal_CQA: expert score = aggregated past work)
- `embed_lawyer(lawyer_id)` — fetches user + recent cases, builds text, embeds with E5, upserts to `lawyers_collection`
- `embed_all_lawyers()` — batch embeds all `role=lawyer, kyc_verified=True, is_active=True` lawyers
- `query_similar_lawyers(query_text, province, n_results)` — returns `[{lawyer_id, semantic_score, metadata}]`, returns `[]` if collection empty

### Chroma Metadata Schema (`lawyers_collection`)
```python
{
    "lawyer_id": str,
    "province": str,           # for WHERE filter
    "specializations": str,    # comma-joined (Chroma requires str/int/float/bool — no lists)
    "rating": float,
    "experience_years": int,
    "availability": bool,
}
```

### Multi-Factor Scoring (`app/services/lawyer_service.py`)
```
final_score =
    semantic_similarity   × 0.50   (cosine: 1 - chroma_distance)
  + specialization_boost  × 0.20   (exact match) or 0.10 (related term)
  + (rating / 5.0)        × 0.15
  + availability          × 0.10
  + min(exp / 20, 1.0)    × 0.05
```

**Fallback:** If `lawyers_collection` is empty (no lawyers embedded yet), falls back to MongoDB-only scoring with `semantic_score=0.3`. Route still returns results.

### Re-Embed Triggers
| Event | Action |
|---|---|
| KYC approved | `embed_lawyer(lawyer_id)` |
| Profile / bio / specializations updated | `embed_lawyer(lawyer_id)` |
| Lawyer closes a case | `embed_lawyer(lawyer_id)` (richer profile) |
| Initial setup | `POST /api/v1/admin/lawyers/embed-all` |

---

## 6. Frontend — UI COMPLETE, API NOT WIRED

Built with Next.js 15 App Router. All pages exist but no fetch/axios calls to the backend yet.

### Route Structure
```
frontend/src/app/
├── (auth)/         login, register, reset-password
├── (client)/       dashboard, intake, chat, cases, documents, agreements, tracking, lawyers
├── lawyer/         dashboard, cases, clients, communications, appointments,
│                   documents, doc-automation, profile, ai-assistant, onboarding
├── admin/          users, kyc, case-tracking, lawyer-monitoring,
│                   analytics, configuration, account-settings
├── page.jsx        Landing
├── about/          About
├── plans/          Plans/Pricing
├── faqs/           FAQs
└── blogs/          Blog
```

### Client Modules (`components/client/`)
`ModIntake.jsx`, `ModChatbot.jsx`, `ModLawyers.jsx`, `ModAgreements.jsx`, `ModDocuments.jsx`, `ModTracking.jsx`, `ModProfile.jsx`, `ModOverview.jsx`

### Shared State
`CaseContext` (`components/shared/CaseContext.jsx`) — all client modules consume `useCase()` for shared case data.

### UI Primitives (`components/ui/`)
`Button`, `Input`, `Modal`, `Card`, `Spinner`, `Table`

---

## 7. How to Run

### Backend
```powershell
# Use explicit venv path (Activate.ps1 alone is unreliable in scripts)
cd backend
& ".\venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000
# OR use start.ps1 which already does this correctly
.\start.ps1
```

### Frontend
```bash
cd frontend
npm install
npm run dev   # Vite dev server on port 5173
```

### Environment Variables

**`backend/.env`:**
```
MONGODB_URL=mongodb://localhost:27017
DB_NAME=attorney_ai
SECRET_KEY=<generate with openssl rand -hex 32>
ENCRYPTION_KEY=<generate with python: from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
GEMINI_API_KEY=<your-key>
GROQ_API_KEY=<your-key>
LLM_PROVIDER=gemini
CHROMA_PATH=./chroma_data
```

**`frontend/.env.local`:**
```
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_WS_URL=ws://localhost:8000
```

### Re-ingest Knowledge Base (if needed)
```bash
cd backend/knowledge_base/pipeline
python ingest.py
python chunk.py
python embed.py
python store.py
```

### Seed Lawyer Vectors (after adding lawyers to DB)
```
POST /api/v1/admin/lawyers/embed-all   (admin JWT required)
```

---

## 8. What Is NOT Done

| Item | Status |
|---|---|
| Frontend → Backend API wiring | **THE main remaining milestone** |
| Unit / integration tests | Not written |
| Docker / docker-compose | Skipped by user request — not planned for v1 |
| Provincial legislation (Sindh/Punjab acts) | v2 only — federal law only in v1 |
| Real bar council API integration | v2 only — manual KYC admin in v1 |
| Voice input | v2 only |

---

## 9. Key Design Decisions (quick reference)

| Decision | Choice | Why |
|---|---|---|
| LangGraph over sequential calls | LangGraph | Conditional routing, MemorySaver state, node = diagram box |
| Hybrid retrieval | BM25(0.6) + Chroma(0.4) | Statute refs need exact keyword match; plain language needs semantic |
| Query expansion | LLM rewrites before BM25 | "beat me up" has zero keyword overlap with PPC "causing grievous hurt" |
| Hallucination handling | Degrade, don't refuse | Hard refusal breaks UX; caution note preserves usefulness |
| Prefix convention | `"passage: "` / `"query: "` | E5 model contract — required for correct asymmetric retrieval |
| BM25 + embedding cache | `@lru_cache` | BM25 rebuild + 1.1 GB model load once per server lifetime |
| Separate law collections | criminal / civil / family | Scopes retrieval to case type — prevents family law noise in criminal queries |
| Lawyer profile text | bio + specs + past case summaries | EF_in_Legal_CQA: expert score = aggregated past work, not just bio |
| Fallback on empty Chroma | MongoDB-only scoring | Prevents 500 errors when no lawyers are embedded yet |
| Lazy import of graphs | Inside service/socket functions | Avoids circular imports; delays 1.1 GB model load to first request |
| Two language prompts | SYSTEM_PROMPT_EN / SYSTEM_PROMPT_UR | Groq auto-switched to Urdu on Pakistani legal context — explicit instruction needed |

---

## 10. Reference Papers Used

| Source | Concept |
|---|---|
| Askari et al., ECIR 2022 — EF_in_Legal_CQA | Two-level scoring, Dirichlet smoothing, expert profile = aggregated past work |
| FreeLawProject/Inception | Profile text construction, `"search_document:"` prefix pattern, async executor for embeddings |
| GiovanniPasq/agentic-rag-for-dummies | Node structure, conditional edge pattern, clarification branch |
| sougaaat/RAG-based-Legal-Assistant | BM25 retriever setup, RRF reranker class, routing concept |
| nilsjennissen/langgraph | BM25/semantic weight recommendation (0.6/0.4) for statute-heavy text |

---

*Attorney.AI | SP23-BCS-069 | Muhammad Usama | May 2026*
