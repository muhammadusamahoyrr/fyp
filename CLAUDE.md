# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Project Overview

**Attorney.AI** — An AI-powered legal assistance platform for Pakistani citizens. Connects users to legal information, document automation, lawyer matching, and case tracking. Built as a university final-year project (SP23-BCS-069, COMSATS).

The authoritative design document is `ATTORNEY_AI_CONTEXT.md` at the repo root. Refer to it for module specs, data flows, and architectural decisions.

---

## Tech Stack Constraints

These are fixed — do not suggest alternatives:

- **Frontend:** Next.js 15 (App Router) + React 18 — *current `package.json` uses Vite as a placeholder; migrate to Next.js before adding features*
- **Backend:** FastAPI + Uvicorn
- **Primary DB:** MongoDB via Motor (async)
- **Vector DB:** ChromaDB (local Docker)
- **Agent Framework:** LangGraph (not CrewAI, not AutoGen)
- **LLMs:** Gemini Flash (free tier) or Ollama — no paid LLM APIs in the core pipeline
- **Embeddings:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (Urdu + English)

---

## Development Commands

### Frontend
```bash
cd frontend
npm install
npm run dev          # Vite dev server (placeholder — will change to `next dev` post-migration)
npm run build        # Production build
npm run preview      # Preview production build
```

### Backend (Python — FastAPI)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Knowledge Base Ingestion
```bash
cd knowledge_base/pipeline
python ingest.py    # Parse raw PDFs
python chunk.py     # Chunk documents
python embed.py     # Generate embeddings
python store.py     # Store to ChromaDB
```

### Environment Variables
Copy these to `.env` (backend) and `.env.local` (frontend):

**Backend `.env`:**
```
MONGODB_URL=mongodb://mongodb:27017
DB_NAME=attorney_ai
SECRET_KEY=<generate>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
GEMINI_API_KEY=<your-key>
GROQ_API_KEY=<your-key>
CHROMA_HOST=chroma
CHROMA_PORT=8001
LLM_PROVIDER=gemini
```

**Frontend `.env.local`:**
```
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_WS_URL=ws://localhost:8000
```

---

## Architecture

### Frontend (`frontend/src/`)

Uses **Next.js 15 App Router** with three role-based route groups:

| Route group | Who sees it | URL prefix |
|---|---|---|
| `(auth)/` | Login, register, reset-password | `/login`, `/register`, `/reset-password` |
| `(client)/` | Client dashboard + 8 feature modules | `/dashboard`, `/intake`, `/chat`, `/cases`, `/documents`, ... |
| `(lawyer)/lawyer/` | Lawyer workspace | `/lawyer`, `/lawyer/cases`, `/lawyer/clients`, ... |
| `(admin)/admin/` | Admin panel | `/admin`, `/admin/users`, `/admin/kyc`, ... |

**Global state** is managed via `CaseContext` (`components/shared/CaseContext.jsx`). All client-side modules consume `useCase()` for shared case data — intake completion state, notifications, and matched lawyers all flow through this context.

**Client modules** in `components/client/`:
- `ModIntake.jsx` — 5-step legal intake form
- `ModChatbot.jsx` — Real-time AI chat (WebSocket to `/ws/chat/{session_id}`)
- `ModLawyers.jsx` — Lawyer search + embedding-based matching
- `ModAgreements.jsx` — E-signature flows (canvas, typed, image upload)
- `ModDocuments.jsx` — Document generation and management
- `ModTracking.jsx` — Case milestones and hearing dates
- `ModProfile.jsx` — User profile
- `ModOverview.jsx` — Dashboard overview

Shared primitives (Button, Card, Badge, Modal, Spinner, Table) live in `components/ui/` and `components/shared/shared.jsx`.

### Backend (`backend/app/`)

Layered FastAPI architecture:

```
api/v1/routes/  →  services/  →  repositories/  →  db/
                ↘  ai/                            ↘  MongoDB / ChromaDB
```

REST API routes: `auth`, `users`, `cases`, `intake`, `lawyers`, `documents`, `agreements`, `chat`, `admin`.

WebSocket endpoints:
- `/ws/chat/{session_id}` — streaming LLM responses
- `/ws/notifications/` — push updates to clients

### Agentic RAG Pipeline (`backend/app/ai/`)

```
User query
  └─ intake node
       └─ gatekeeper node (legal vs. off-topic)
            └─ LangGraph supervisor
                 ├─ civil_agent
                 ├─ criminal_agent
                 ├─ constitutional_agent
                 └─ document_agent
                      └─ retrieval (BM25 + Chroma hybrid)
                           └─ reranker (RRF)
                                └─ grader node
                                     └─ hallucination check
                                          └─ generation node → response
```

`graph/` holds the LangGraph supervisor. `nodes/` has each pipeline step. `pipelines/` has the hybrid retriever. `memory/` handles per-session conversation state.

### Knowledge Base (`knowledge_base/`)

Pakistani federal law only (v1). Every Chroma chunk **must** carry province metadata (`punjab`, `sindh`, `kpk`, `balochistan`, `federal`).

| Partition | Content |
|---|---|
| `constitution/` | Constitution of Pakistan 1973 |
| `criminal/` | PPC 1860, CrPC 1898 |
| `civil/` | CPC 1908 |
| `family/` | Family laws |
| `statutes/` | ETO 2002, PECA 2016, PDPA, 1,030 federal statutes |
| `court_judgments/` | Judgments from 6 Pakistani courts |

---

## Pakistani Law Conventions

- **PPC** = Pakistan Penal Code 1860 (not Indian Penal Code)
- **CrPC** = Code of Criminal Procedure 1898 (Pakistan version, not Indian)
- All legal citations must reference Pakistani statutes exclusively — never UK, US, or Indian law
- The system must support both **English and Urdu** queries

---

## System Boundaries (v1)

The system does **not** do in v1:
- Real bar council API integration (mocked with manual KYC)
- Provincial legislation (Sindh/Punjab acts) — federal only
- Voice input
- Blockchain e-signature validation

Always include the "informational only — not legal advice" disclaimer in AI-generated legal responses.
