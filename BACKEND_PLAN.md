# ATTORNEY.AI — Backend Plan
> SP23-BCS-069 | Muhammad Usama | April 2026

---

## Open-Source Build Stack

### Tier 1 — Clone & Build From These First

| Repo | What to take |
|------|-------------|
| `GiovanniPasq/agentic-rag-for-dummies` | **Skeleton.** Copy `rag_agent/nodes.py` — specifically `request_clarification` and `rewrite_query` nodes. Replace Gradio with FastAPI WebSocket. Swap LLM to Gemini/Ollama. |
| `wassim249/fastapi-langgraph-agent-production-ready-template` | **FastAPI shell.** JWT auth, slowapi rate limiting, Langfuse tracing, Docker — all pre-wired. Replace its generic agent with your legal RAG agent. |
| `sougaaat/RAG-based-Legal-Assistant` | **Retrieval engine.** BM25 + Chroma hybrid, RRF reranking, `decide_query_complexity.py` router (simple = single retrieval, complex = multi-hop), RAGAS eval setup. |

### Tier 2 — Borrow One Specific Thing Each

| Repo | What to borrow |
|------|---------------|
| `nilsjennissen/langgraph` | EnsembleRetriever wiring — set keyword weight **0.6** for Pakistani legal text (statute refs like `PPC S.302` are keyword matches, not semantic) |
| `junfanz1/Cognito-LangGraph-RAG-Chatbot` | CRAG pattern — `GRADE_DOCUMENTS` node + hallucination grader prompt. Grade < 0.75 → clarification. Grounding check fails → refuse + suggest lawyer. |
| `JoshuaC215/agent-service-toolkit` | `interrupt()` pattern (LangGraph v1.0 HITL), ChromaDB RAG agent file, streaming endpoint design |
| `sardanaaman/langgraph-compass` | Drop-in follow-up question module → your clarification node |
| `sfantaye/legalmind` | Document generation pipeline pattern (structured inputs → LLM → docxtpl) |
| `arulkumarann/legalRAG` | Session-per-user isolation + `/sources/{session_id}` citation endpoint design |
| `sergio11/langgraph_legal_assistant` | Jurisdiction routing logic → adapt to Pakistani province + court level |

### Tier 3 — Ingestion Tools (run in this order)

```
Your PDF → UTRNet (scanned only) → Unstructured → llmsherpa → multilingual-MiniLM → Chroma
```

| Tool | Use |
|------|-----|
| `abdur75648/UTRNet` | Only if `pdftotext` returns garbled output (scanned Urdu PDF) |
| `Unstructured-IO/unstructured` | Run first — normalises raw PDF for llmsherpa |
| `nlmatics/llmsherpa` | Structure-aware chunking — keeps `Section 302(a)` intact, not split mid-clause |

### Your Own Assets (primary knowledge base)

| Asset | Use |
|-------|-----|
| `muhammadusamahoyrr/pakistan-legal-dataset` | Primary Chroma KB — folder names give free `court` + `province` metadata |
| `LEGAL-UQA` (HuggingFace) | (1) Seed constitutional collection with 619 pre-chunked Q&A pairs (2) Evaluation dataset — feed all 619 questions, report accuracy to supervisor |

---

## Folder Structure

```
backend/
├── app/
│   ├── main.py                  # FastAPI factory, lifespan, CORS, rate limit
│   ├── dependencies.py          # get_current_user, role_required
│   ├── core/
│   │   ├── config.py            # pydantic-settings — reads .env
│   │   ├── security.py          # JWT create/decode, bcrypt
│   │   ├── constants.py         # UserRole, CaseType, Province enums
│   │   ├── exceptions.py        # AuthError, NotFoundError, AIServiceError
│   │   └── rate_limit.py        # slowapi limiter
│   ├── db/
│   │   ├── mongodb.py           # Motor singleton
│   │   ├── indexes.py           # create_indexes() at startup
│   │   └── collections.py       # typed collection accessors
│   ├── models/                  # MongoDB document shapes (internal Pydantic)
│   │   ├── user.py
│   │   ├── case.py
│   │   ├── intake.py
│   │   ├── document.py
│   │   ├── agreement.py
│   │   ├── notification.py
│   │   └── chat.py
│   ├── schemas/                 # Request / Response wire shapes
│   │   ├── auth.py
│   │   ├── user.py
│   │   ├── case.py
│   │   ├── intake.py
│   │   ├── lawyer.py
│   │   ├── document.py
│   │   ├── agreement.py
│   │   ├── admin.py
│   │   └── common.py            # PaginatedResponse, StatusResponse
│   ├── repositories/            # Only layer that touches Motor
│   │   ├── base.py              # CRUD helpers, pagination
│   │   ├── user_repo.py
│   │   ├── case_repo.py
│   │   ├── intake_repo.py
│   │   ├── document_repo.py
│   │   ├── agreement_repo.py
│   │   ├── notification_repo.py
│   │   └── chat_repo.py
│   ├── services/                # Business logic — orchestrates repos + AI
│   │   ├── auth_service.py
│   │   ├── user_service.py
│   │   ├── case_service.py
│   │   ├── intake_service.py
│   │   ├── lawyer_service.py
│   │   ├── document_service.py
│   │   ├── agreement_service.py
│   │   ├── notification_service.py
│   │   └── admin_service.py
│   ├── api/v1/routes/
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── cases.py
│   │   ├── intake.py
│   │   ├── lawyers.py
│   │   ├── documents.py
│   │   ├── agreements.py
│   │   ├── notifications.py
│   │   └── admin.py
│   ├── websockets/
│   │   ├── manager.py           # ConnectionManager registry
│   │   ├── chat_socket.py       # ws://.../ws/chat/{session_id}
│   │   └── notification_socket.py
│   ├── ai/
│   │   ├── llm.py               # LLM factory — reads LLM_PROVIDER env var
│   │   ├── graph/
│   │   │   ├── state.py         # AgentState TypedDict
│   │   │   ├── supervisor.py    # routes to specialist agents by case_type
│   │   │   └── edges.py         # conditional routing functions
│   │   ├── agents/
│   │   │   ├── civil_agent.py
│   │   │   ├── criminal_agent.py
│   │   │   ├── constitutional_agent.py
│   │   │   └── document_agent.py
│   │   ├── nodes/               # from GiovanniPasq + junfanz1
│   │   │   ├── intake_node.py
│   │   │   ├── gatekeeper_node.py
│   │   │   ├── clarification_node.py   # sardanaaman/langgraph-compass
│   │   │   ├── retrieval_node.py
│   │   │   ├── reranker_node.py
│   │   │   ├── grader_node.py          # junfanz1 GRADE_DOCUMENTS
│   │   │   ├── hallucination_node.py   # junfanz1 answer grader
│   │   │   └── generation_node.py
│   │   ├── pipelines/
│   │   │   ├── retriever.py     # BM25 + Chroma hybrid (sougaaat)
│   │   │   └── reranker.py      # RRF (sougaaat)
│   │   ├── memory/
│   │   │   ├── session_memory.py       # LangGraph checkpointer (arulkumarann isolation)
│   │   │   └── conversation_store.py   # chat history → MongoDB
│   │   ├── tools/
│   │   │   ├── legal_search.py
│   │   │   ├── case_builder.py
│   │   │   └── doc_tool.py
│   │   ├── generators/
│   │   │   └── doc_generator.py  # docxtpl + LibreOffice (sfantaye pattern)
│   │   └── matchers/
│   │       └── lawyer_matcher.py  # cosine sim ranking
│   └── utils/
│       ├── file_handler.py
│       ├── email.py
│       └── validators.py         # CNIC, PK phone, email regex
```

---

## MongoDB Collections (key fields only)

### `users`
```python
{ role, email, password_hash, cnic, province,
  lawyer_profile: { bar_number, specializations, kyc_verified,
                    rating, availability, specialization_embedding } }
# Indexes: email (unique), cnic (unique sparse), role, province, kyc_verified
```

### `cases`
```python
{ case_number, client_id, lawyer_id, case_type, province, status,
  milestones: [{title, date, completed}],
  hearing_dates: [{date, court}],
  case_embedding,   # 384-dim — used for lawyer matching
  intake_id }
# Indexes: case_number (unique), client_id, lawyer_id, status, case_type
```

### `intakes`
```python
{ session_token,  # UUID — frontend uses this to resume
  client_id, current_step, completed,
  step1..step5,   # accumulated across 5 form POSTs
  ai_structured_case: { summary, applicable_laws, recommended_actions, risk_level },
  case_id }       # set after intake→case conversion
```

### `agreements`
```python
{ title, body_html, eto_classification,
  parties: [{ user_id, signed, signature_method, signature_data }],
  status, audit_log: [{ action, actor_id, timestamp, ip_address }] }
```

### `chat_sessions`
```python
{ session_id,  # UUID — WebSocket URL key
  client_id, case_type, province,
  messages: [{ role, content, citations, confidence }],
  langgraph_checkpoint }  # serialized checkpointer — enables interrupt() resume
```

---

## API Endpoints

### Auth `/api/v1/auth`
| Method | Path | Auth |
|--------|------|------|
| POST | `/register` | Public |
| POST | `/login` | Public |
| POST | `/refresh` | Refresh cookie |
| POST | `/forgot-password` | Public |
| POST | `/reset-password` | Public |

### Cases `/api/v1/cases`
| Method | Path | Auth |
|--------|------|------|
| POST | `/` | Client |
| GET | `/` | Client / Lawyer |
| GET | `/{id}` | Owner / Assigned Lawyer |
| PATCH | `/{id}` | Client / Lawyer |
| GET | `/{id}/timeline` | Owner / Lawyer |
| POST | `/{id}/milestones` | Lawyer |
| POST | `/{id}/hearings` | Lawyer |

### Intake `/api/v1/intake`
| Method | Path | Notes |
|--------|------|-------|
| POST | `/start` | Returns `session_token` |
| PATCH | `/{token}/step/{1-5}` | Saves each step independently |
| POST | `/{token}/convert` | Intake → Case, triggers AI structuring |

### Lawyers `/api/v1/lawyers`
| Method | Path | Notes |
|--------|------|-------|
| GET | `/` | `?province=Punjab&case_type=civil&min_rating=4` |
| GET | `/match/{case_id}` | Embedding-based ranking |
| POST | `/{id}/review` | Star rating + comment |

### Documents `/api/v1/documents`
| Method | Path | Notes |
|--------|------|-------|
| POST | `/generate` | Template + case_id → PDF |
| GET | `/{id}/download` | Stream PDF |

### Admin `/api/v1/admin`
| Method | Path | Notes |
|--------|------|-------|
| GET | `/kyc/pending` | Lawyers awaiting verification |
| PATCH | `/kyc/{lawyer_id}` | Approve / reject |
| GET | `/analytics/overview` | Counts by type/status |

---

## AI Pipeline (LangGraph)

### AgentState
```python
class AgentState(TypedDict):
    query: str; session_id: str; case_id: str | None
    case_type: str; province: str; language: str      # "en" | "ur"
    needs_clarification: bool; clarification_question: str
    retrieved_chunks: list[dict]; reranked_chunks: list[dict]
    relevance_score: float                             # < 0.75 → back to clarification
    answer: str; citations: list[dict]; confidence: float
    is_grounded: bool                                  # False → refuse + suggest lawyer
    messages: list[BaseMessage]
```

### Node Flow
```
query → intake_node → gatekeeper_node
                           │ non-legal → canned response
                           ↓
                      supervisor  ──routes by case_type──→  civil_agent
                                                         →  criminal_agent
                                                         →  constitutional_agent
                           ↓
                      retrieval_node  (BM25 0.6 + Chroma 0.4, province filter)
                           ↓
                      reranker_node   (RRF)
                           ↓
                      grader_node     (relevance < 0.75 → clarification_node → interrupt())
                           ↓
                      generation_node (LLM streams tokens via WebSocket)
                           ↓
                      hallucination_node (not grounded → refuse)
```

### Hybrid Retriever (sougaaat pattern, nilsjennissen weights)
```python
# EnsembleRetriever: 0.6 keyword (BM25) + 0.4 semantic (Chroma)
# Reason: "Section 302 PPC" is a keyword match — pure semantic search misses it

province_filter = {
    "$or": [{"province": {"$eq": province}}, {"province": {"$eq": "Federal"}}]
}

# decide_query_complexity.py (from sougaaat):
# simple query  → single retrieval pass
# complex query → multi-hop (retrieve → generate sub-query → retrieve again)
```

### LLM Factory (`ai/llm.py`)
```python
def get_llm():
    if settings.LLM_PROVIDER == "gemini":   # demo day
        return ChatGoogleGenerativeAI(model="gemini-2.0-flash", ...)
    elif settings.LLM_PROVIDER == "ollama": # daily dev
        return ChatOllama(model="llama3.1", ...)
    elif settings.LLM_PROVIDER == "groq":   # backup
        return ChatGroq(model="llama-3.1-70b-versatile", ...)
```

---

## WebSocket Protocol

```
ws://host/ws/chat/{session_id}   — streaming chat (LangGraph tokens)
ws://host/ws/notifications/{user_id}  — push notifications
```

```python
# Client → Server
{"type": "message", "content": str, "case_id": str, "province": str, "case_type": str}

# Server → Client (three types)
{"type": "token",         "content": str}                          # streaming
{"type": "final",         "content": str, "citations": [...], "confidence": float}
{"type": "clarification", "question": str}                         # interrupt() pause
```

---

## Lawyer Matching
```python
score = cosine_similarity(case_emb, lawyer_emb) * 0.5 \
      + (lawyer.rating / 5.0)                   * 0.3 \
      + (1.0 if lawyer.availability else 0.0)   * 0.2

# Filter mandatory: province + case_type + kyc_verified = True
# Return top 5
```

---

## Document Generation
```
User selects template → LLM extracts fields from case data
→ docxtpl fills .docx → LibreOffice headless → PDF → /uploads/docs/{id}.pdf
```
Templates: `plaint_civil`, `written_statement`, `legal_notice`, `nda`, `rental_agreement`
Pattern sourced from: `sfantaye/legalmind`

---

## Knowledge Base Ingestion

```bash
# Run in order:
python ingest.py    # pdftotext check → UTRNet (scanned) or pass-through
python chunk.py     # Unstructured → llmsherpa (structure-aware, keeps section hierarchy)
python partition.py # assign to collection by source dir + content signals
python embed.py     # multilingual-MiniLM-L12-v2, batch 64
python store.py     # upsert to Chroma with full metadata
```

**Chroma metadata on every chunk:**
```python
{"court": str, "province": str, "law_type": str,
 "section_type": str, "statute": str, "section_number": str,
 "source_file": str, "chunk_id": str}
```

**Collections:**
| Collection | Source |
|-----------|--------|
| `civil_collection` | CPC + civil judgments + family |
| `criminal_collection` | PPC + CrPC + criminal judgments |
| `constitutional_collection` | Constitution + ETO 2002 + LEGAL-UQA 619 pairs |
| `statutes_collection` | 1,030 federal statutes |
| `judgments_collection` | pakistan-legal-dataset (6 courts, province-tagged) |

---

## Auth & Security

```python
# Dependencies
get_current_user()          → decodes JWT, checks is_active
role_required(*roles)       → 403 if role not in allowed

# Rate limits (slowapi)
/auth/login, /register      → 5/minute  (brute-force protection)
/ws/chat                    → 20/minute per user

# Security checklist
- bcrypt cost 12
- Refresh token in httpOnly + Secure + SameSite=Strict cookie
- Refresh token blocklist in MongoDB on logout
- CNIC encrypted at rest (AES-256)
- File uploads: whitelist extensions, 10 MB max
- No secrets in structlog output (redact password, token, api_key)
```

---

## Infrastructure

```yaml
# docker-compose.yml services
frontend  → port 3000  (Next.js)
backend   → port 8000  (FastAPI + Uvicorn)
mongodb   → port 27017 (persistent volume)
chroma    → port 8001  (persistent volume ./chroma_data)
```

```dockerfile
# Dockerfile.backend — key extra
RUN apt-get install -y libreoffice poppler-utils
# LibreOffice needed for .docx → PDF conversion
```

---

## Build Order (6 Steps)

| Step | What | Repos |
|------|------|-------|
| 1 | Get GiovanniPasq running with Ollama/Gemini. Clarification node working end-to-end. | GiovanniPasq + nilsjennissen |
| 2 | Ingest LEGAL-UQA + pakistan-legal-dataset into Chroma on Kaggle GPU. Province metadata attached. | LEGAL-UQA + pakistan-legal-dataset + llmsherpa + Unstructured |
| 3 | Plug sougaaat hybrid retrieval. Test `Section 302 PPC` returns correctly. | sougaaat |
| 4 | Add junfanz1 GRADE_DOCUMENTS + hallucination grader between retrieval and generation. | junfanz1 |
| 5 | Wrap everything in wassim249 FastAPI template. JWT, rate limit, Langfuse wired up. | wassim249 |
| 6 | Feed all 619 LEGAL-UQA questions → pipeline → record accuracy score for supervisor. | LEGAL-UQA + LRAGE methodology |

---

## Monitoring

```python
# Langfuse — trace every LLM call
langfuse_handler = CallbackHandler(public_key=..., secret_key=..., host=...)
graph.ainvoke(state, config={"callbacks": [langfuse_handler]})
# Tag each trace: case_type, province, session_id
# Free tier: 50,000 observations/month
```

---

*ATTORNEY.AI | SP23-BCS-069 | April 2026*
