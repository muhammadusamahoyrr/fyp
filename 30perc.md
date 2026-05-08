# Attorney.AI — 30% Milestone Reference
> SP23-BCS-069 | Muhammad Usama | May 2026
> Read this file at the start of any new session before planning next steps.

---

## Overall Project Status

| Phase | Status | Notes |
|-------|--------|-------|
| Non-AI Backend (auth, cases, docs, agreements, admin) | ✅ Complete | 68 files, 0 syntax errors |
| Legal Intake Backend | ✅ Complete | 5-step, session token, AI hook wired |
| Lawyer Matching Backend | ✅ Complete | ChromaDB + multi-factor scoring |
| AI Pipeline (LangGraph + RAG) | ✅ Complete | intake_graph + chat_graph both built |
| Voice / STT Module | ✅ Complete | Whisper singleton, two-lock design |
| Frontend Auth Infrastructure | ✅ Complete | AuthContext, ProtectedRoute, Providers |
| **API Layer — Intake wired** | ✅ **Complete this session** | province, case_type, urgency, AI summary |
| **API Layer — Lawyers wired** | ✅ **Complete this session** | search + AI match + mock fallback |
| **API Layer — Profile wired** | ✅ **Complete this session** | updateMe + AuthContext sync |
| **Admin embed-all route** | ✅ **Complete this session** | POST /admin/lawyers/embed-all |
| Chat / WebSocket wiring | 🔲 Next | ModChatbot.jsx |
| Cases module wiring | 🔲 Next | ModTracking, case list/detail |
| Documents module wiring | 🔲 Next | ModDocuments, ModAgreements |
| Knowledge base ingestion | 🔲 Next | PDFs → ChromaDB |
| Unit / integration tests | 🔲 Pending | |

**~55% of total project scope complete.**

---

## What Was Done This Session (30% Milestone)

### 1. Backend — `admin.py`
Added the missing embed-all endpoint:
```python
POST /admin/lawyers/embed-all
```
Calls `embed_all_lawyers()` from `app/ai/lawyer_embeddings.py`.
All other backend was already complete — no other changes needed.

### 2. Frontend — `src/lib/api.js`
Three new exported functions added at bottom of file:
```js
searchLawyers({ province, case_type, min_rating, availability, page, page_size })
  → GET /lawyers?...

matchLawyers(case_id)
  → GET /lawyers/match/{case_id}

submitReview(lawyer_id, stars, comment)
  → POST /lawyers/{lawyer_id}/review
```
`intakeGet(sessionToken)` was already exported (not new).

### 3. Frontend — `ModIntake.jsx` (full rewrite)

**Critical fix**: Backend `STEP_REQUIRED_FIELDS` requires:
- Step 1: `province` (was never collected before)
- Step 2: `case_type`, `urgency` (were never collected before)
- Step 3: `incident_description`
- Step 4: `{}` (no requirements)
- Step 5: `desired_outcome`

Without these fields the backend would reject `intakeConvert`.

**New state added**:
```js
province       // "punjab"|"sindh"|"kpk"|"balochistan"|"federal"
caseTypeInput  // "civil"|"criminal"|"family"|"constitutional"
urgency        // "low"|"medium"|"high"|"urgent"
aiStructured   // { summary, applicable_laws[], recommended_actions[], risk_level }
converting     // bool — true while intakeConvert is running
caseId         // returned by intakeConvert, stored in localStorage "aai-case-id"
```

**New step flow**:
| Frontend Step | What happens on Continue |
|---|---|
| Step 1 (Role + Province) | `intakeSaveStep(token, 1, {province})` → go to Step 2 |
| Step 2 (Case Type + Description) | `intakeSaveStep(token, 2, {case_type, urgency})` + `intakeSaveStep(token, 3, {incident_description})` → go to Step 3 |
| Step 3 (AI Questions) | `intakeSaveStep(token, 4, {})` + `intakeSaveStep(token, 5, {desired_outcome})` + `intakeConvert(token)` + `intakeGet(token)` → sets `aiStructured` → go to Step 4 |
| Step 4 (Case Summary) | Shows real AI data from `aiStructured`. Continue → Step 5 |
| Step 5 (Categorization) | Local-only: `completeIntake()` + `addNotification()`. No more API calls. |

**Key constants** (must match backend enums exactly):
```js
PROVINCES = ["punjab","sindh","kpk","balochistan","federal"]
CASE_TYPES = ["civil","criminal","family","constitutional"]
URGENCY_LEVELS = ["low","medium","high","urgent"]
```

**After successful convert**:
- `converted.case_id` stored in `localStorage.setItem("aai-case-id", ...)`
- `aai-intake-token` cleared from localStorage
- `aiStructured` populated from `intakeGet(token).ai_structured_case`

**Step 4 display**:
- If `aiStructured` available → shows real summary, applicable_laws[], recommended_actions[], risk_level badge
- If `aiStructured` null → shows static fallback panels with role/province/description

### 4. Frontend — `ModLawyers.jsx` (targeted edits)

**New imports**: `useEffect`, `useToast`, `searchLawyers`, `matchLawyers`

**Data loading**:
```js
// On mount: fetch real lawyers from backend
useEffect(() => {
  searchLawyers({}).then(({ data }) => {
    if (data?.items?.length) setApiLawyers(data.items.map(mapApiLawyer));
    setLoadingLawyers(false);
  });
}, []);

// Computed: use API data when available, mock when empty
const lawyers = apiLawyers.length > 0 ? apiLawyers : MOCK_LAWYERS;
```

**`mapApiLawyer(raw, idx)`** — maps backend user doc to UI shape:
| Backend field | UI field |
|---|---|
| `raw.full_name` | `name` |
| `lp.specializations.join(", ")` | `spec` |
| `raw.province` (capitalized) | `city` |
| `lp.experience_years` | `exp` |
| `lp.rating` | `rating` |
| `lp.availability` | `avail` |
| `lp.total_reviews` | `reviews` |
| `lp.bar_number` | `bar` |
| `raw.match_score` | `match_score` (AI match only) |
| `raw.match_reason` | `match_reason` |
| `lp.specializations` | `credentials` |
| `[]` | `reviewList` (empty — no review data from backend yet) |
| 5000 (hardcoded) | `fee` (fee not in backend schema yet) |

**AI Match Banner wiring**:
- Reads `localStorage.getItem("aai-case-id")` set by ModIntake after convert
- If no case_id → shows "Complete intake form first"
- Button "Find My Match" → calls `matchLawyers(case_id)` → sets `aiMatch` state
- Button "View Match" → navigates to `aiMatch` profile view

### 5. Frontend — `ModProfile.jsx` (targeted edits)

**New imports**: `useAuth` from `@/context/AuthContext.jsx`, `updateMe` from `@/lib/api.js`

**Display values derived from AuthContext**:
```js
const { user, updateUser } = useAuth();
const displayName    = user?.full_name || "Muhammad Usama"
const displayEmail   = user?.email     || "musamahoy@gmail.com"
const displayPhone   = user?.phone     || "+92 300 0000000"
const displayAddress = user?.province  → capitalized + ", Pakistan"
const initials       = derived from displayName
```

**Edit flow**:
1. `startEdit()` seeds `editData` from current `user` object
2. `EditField` now supports controlled mode (value + onChange) without breaking existing uncontrolled usage
3. `handleSave()` calls `updateMe({full_name, phone})` → on success calls `updateUser({full_name, phone})` to sync context
4. Cancel button restores previous values (editData was never committed)

---

## Backend File Map (what's where)

```
backend/app/
├── main.py                    — FastAPI app + lifespan (warmup whisper)
├── dependencies.py            — get_current_user, require_client, require_admin
├── api/v1/routes/
│   ├── auth.py                — login, register, logout, refresh, forgot/reset password
│   ├── users.py               — GET/PATCH /users/me
│   ├── cases.py               — CRUD for cases
│   ├── intake.py              — start, step save, convert, get
│   ├── lawyers.py             — search, match/{case_id}, review, embed (single)
│   ├── admin.py               — KYC, analytics, embed-all ← UPDATED
│   ├── voice.py               — POST /voice/transcribe
│   ├── chat.py                — REST wrapper (WebSocket is in websockets/)
│   ├── documents.py           — document CRUD
│   └── agreements.py          — agreement CRUD
├── services/
│   ├── intake_service.py      — start_intake, save_step, convert_to_case, _run_intake_ai
│   ├── lawyer_service.py      — search_lawyers, match_lawyers_for_case, submit_review
│   ├── whisper_service.py     — singleton WhisperService (two-lock design)
│   ├── case_service.py        — create_case
│   └── admin_service.py       — process_kyc, get_analytics
├── ai/
│   ├── graph/
│   │   ├── supervisor.py      — chat_graph + intake_graph (both built)
│   │   ├── state.py           — AgentState TypedDict
│   │   └── edges.py           — routing functions
│   ├── nodes/
│   │   ├── gatekeeper_node.py — legal vs off-topic gate
│   │   ├── intake_node.py     — structures intake into ai_structured_case JSON
│   │   ├── retrieval_node.py  — calls hybrid retriever
│   │   ├── generation_node.py — streams LLM tokens
│   │   ├── hallucination_node.py — grounding check
│   │   └── clarification_node.py — asks user for more info
│   ├── pipelines/
│   │   ├── retriever.py       — BM25 0.6 + Chroma 0.4, E5 embeddings, province filter
│   │   └── reranker.py        — RRF reranker
│   ├── lawyer_embeddings.py   — embed_lawyer, embed_all_lawyers, query_similar_lawyers
│   └── llm.py                 — Gemini/Ollama client factory
├── db/
│   ├── mongodb.py             — Motor async client
│   └── chroma.py              — PersistentClient, COLLECTIONS list, get_collection()
├── repositories/
│   ├── user_repo.py           — find_by_id, find_lawyers (paginated), update_rating
│   ├── case_repo.py           — find_by_id, find_many, create
│   └── intake_repo.py         — find_by_token, update_step, save_ai_structured_case
├── schemas/                   — Pydantic models (LawyerReview, StatusResponse, etc.)
├── models/                    — ODM-style field definitions
├── core/
│   ├── exceptions.py          — NotFoundError, AppValidationError, etc.
│   ├── rate_limit.py          — SlowAPI limiter instance
│   └── constants.py           — CaseType, Province enums
└── websockets/
    └── chat_socket.py         — /ws/chat/{session_id} streaming endpoint
```

---

## Frontend File Map (what's where)

```
frontend/src/
├── app/
│   ├── layout.jsx             — Root layout wraps <Providers>
│   ├── Providers.jsx          — 'use client' boundary around AuthProvider
│   └── (route groups)/
│       ├── (auth)/            — login, register, reset-password
│       ├── (client)/          — /dashboard, /intake, /chat, /cases, /lawyers, ...
│       ├── (lawyer)/lawyer/   — /lawyer, /lawyer/cases, ...
│       └── (admin)/admin/     — /admin, /admin/users, /admin/kyc, ...
├── context/
│   └── AuthContext.jsx        — useAuth(), AuthProvider, hydrates from GET /users/me
├── lib/
│   └── api.js                 — ALL backend calls go through here
├── components/
│   ├── shared/
│   │   ├── CaseContext.jsx    — useCase(), CaseProvider — shared case state
│   │   ├── ProtectedRoute.jsx — auth guard for route groups
│   │   ├── Landing.jsx        — public landing page
│   │   ├── shared.jsx         — Card, BtnPrimary, BtnOutline, ThemedInput, Badge, etc.
│   │   └── Toast.jsx          — useToast() hook + ToastProvider
│   ├── client/
│   │   ├── ModIntake.jsx      ← UPDATED (province+casetype+urgency+AI summary)
│   │   ├── ModLawyers.jsx     ← UPDATED (real API + AI match)
│   │   ├── ModProfile.jsx     ← UPDATED (AuthContext + updateMe)
│   │   ├── ModChatbot.jsx     — WebSocket chat (NOT YET WIRED to backend)
│   │   ├── ModTracking.jsx    — Case milestones (NOT YET WIRED)
│   │   ├── ModDocuments.jsx   — Document management (NOT YET WIRED)
│   │   ├── ModAgreements.jsx  — E-signature flows (NOT YET WIRED)
│   │   ├── ModOverview.jsx    — Dashboard overview (partially wired)
│   │   ├── CaseContext.jsx    — re-export from shared/CaseContext.jsx
│   │   ├── theme.js           — useT() theme hook
│   │   └── Ic.jsx             — icon component
│   ├── lawyer/
│   │   ├── AILegalPage.jsx    — Lawyer AI chat page
│   │   ├── OnboardingPage.jsx — Lawyer KYC onboarding
│   │   └── layout.jsx         — Lawyer layout
│   └── admin/
│       └── (admin dashboard components)
```

---

## API Endpoints — Complete Reference

### Auth
```
POST   /api/v1/auth/login
POST   /api/v1/auth/register
POST   /api/v1/auth/logout
POST   /api/v1/auth/refresh
POST   /api/v1/auth/forgot-password
POST   /api/v1/auth/reset-password
```

### Users
```
GET    /api/v1/users/me
PATCH  /api/v1/users/me          ← wired in ModProfile
```

### Intake
```
POST   /api/v1/intake/start
PATCH  /api/v1/intake/{token}/step/{1-5}
POST   /api/v1/intake/{token}/convert
GET    /api/v1/intake/{token}
```

### Lawyers
```
GET    /api/v1/lawyers                        ← wired in ModLawyers
GET    /api/v1/lawyers/match/{case_id}        ← wired in ModLawyers (AI match)
POST   /api/v1/lawyers/{lawyer_id}/review     ← in api.js, not yet called from UI
POST   /api/v1/lawyers/{lawyer_id}/embed      ← admin only
```

### Voice
```
POST   /api/v1/voice/transcribe               ← wired in ModIntake
```

### Cases
```
POST   /api/v1/cases
GET    /api/v1/cases
GET    /api/v1/cases/{case_id}
PATCH  /api/v1/cases/{case_id}
DELETE /api/v1/cases/{case_id}
```

### Documents
```
POST   /api/v1/documents
GET    /api/v1/documents
GET    /api/v1/documents/{doc_id}
DELETE /api/v1/documents/{doc_id}
```

### Agreements
```
POST   /api/v1/agreements
GET    /api/v1/agreements
PATCH  /api/v1/agreements/{agreement_id}
```

### Chat (REST wrapper — real comms via WebSocket)
```
POST   /api/v1/chat/sessions
GET    /api/v1/chat/sessions
GET    /api/v1/chat/sessions/{session_id}
WS     /ws/chat/{session_id}
```

### Admin
```
GET    /api/v1/admin/kyc/pending
PATCH  /api/v1/admin/kyc/{lawyer_id}
GET    /api/v1/admin/analytics/overview
POST   /api/v1/admin/lawyers/embed-all       ← ADDED this session
```

---

## Data Flows — Key Integrations

### Intake → AI → Lawyer Match (the full E2E path)

```
User fills Step 1 (role + province)
  → frontend saves: intakeSaveStep(token, 1, {province})

User fills Step 2 (case_type + urgency + description)
  → frontend saves: intakeSaveStep(token, 2, {case_type, urgency})
  → frontend saves: intakeSaveStep(token, 3, {incident_description})

User completes Step 3 (AI questions)
  → frontend saves: intakeSaveStep(token, 4, {})
  → frontend saves: intakeSaveStep(token, 5, {desired_outcome})
  → frontend calls: intakeConvert(token)
      backend:
        1. Creates Case document in MongoDB
        2. Runs intake_graph.ainvoke(state) — LangGraph
           state has: query, case_type, province, session_id, case_id
        3. intake_graph: retrieval_node → intake_node → END
           intake_node calls LLM to structure into:
             { summary, applicable_laws[], recommended_actions[], risk_level }
        4. Saves ai_structured_case to intake document
        5. Returns { session_token, case_id, completed: true }
  → frontend calls: intakeGet(token)
      gets: { ai_structured_case } ← displayed in Step 4
  → frontend stores: localStorage["aai-case-id"] = case_id

User visits ModLawyers
  → clicks "Find My Match"
  → frontend reads localStorage["aai-case-id"]
  → calls: matchLawyers(case_id)
      backend:
        1. Loads case from MongoDB
        2. Queries ChromaDB lawyers_collection with case description
           (province filter: match province OR federal)
        3. For each hit: fetches full lawyer doc + applies scoring formula
           score = semantic×0.50 + specialization×0.20 + rating×0.15 + availability×0.10 + exp×0.05
        4. Falls back to MongoDB-only if ChromaDB empty
        5. Returns top 5 scored lawyers
  → frontend displays top match in AI Match Banner
  → user can click "View Match" → lawyer profile view
```

### ChromaDB Collections
```
civil_collection          — civil law chunks
criminal_collection       — criminal law chunks
family_collection         — family law chunks
constitutional_collection — constitutional law chunks
statutes_collection       — federal statutes chunks
judgments_collection      — court judgment chunks
lawyers_collection        — lawyer profile embeddings ← populated by embed-all
```

`lawyers_collection` is currently EMPTY (no lawyers have been embedded yet).
Until lawyers are embedded, `match_lawyers_for_case` falls back to MongoDB-only scoring.
To populate: call `POST /admin/lawyers/embed-all` as admin.

### Lawyer Embedding (how it works)
```python
build_profile_text(lawyer, recent_cases):
  "Pakistani legal professional specializing in {specs}."
  "Province: {province}."
  "{n} years of experience in Pakistani law."
  "{bio}"
  "Past cases handled: {case1} | {case2} | ..."

embed_lawyer(lawyer_id):
  → builds profile text
  → E5 embed with "passage: " prefix
  → upserts to lawyers_collection with metadata:
    { lawyer_id, province, specializations, rating, experience_years, availability }
```

---

## What's NOT Done Yet (Remaining Work)

### Frontend Modules Not Wired to Backend

| Module | File | What's missing |
|--------|------|----------------|
| Chat | `ModChatbot.jsx` | WebSocket connection to `/ws/chat/{session_id}`, session creation via POST /chat/sessions |
| Case Tracking | `ModTracking.jsx` | GET/PATCH /cases/{case_id}, milestone display |
| Documents | `ModDocuments.jsx` | POST/GET /documents, file upload |
| Agreements | `ModAgreements.jsx` | POST/GET /agreements, signature flows |
| Overview | `ModOverview.jsx` | Aggregate dashboard data from cases + notifications |

### Backend Still Needed

| Feature | File | Notes |
|---------|------|-------|
| Knowledge base ingestion | `knowledge_base/pipeline/` | ingest.py → chunk.py → embed.py → store.py |
| Fee field on lawyer profile | `user_repo`, schemas | Currently hardcoded to 5000 in frontend |
| Review listing endpoint | `lawyers.py` route | `GET /lawyers/{id}/reviews` — currently reviews are embedded in user doc |

### AI Pipeline Gaps

| Gap | Notes |
|-----|-------|
| lawyers_collection empty | Run `POST /admin/lawyers/embed-all` once lawyers are KYC-approved |
| Knowledge base collections empty | Run ingestion pipeline once law PDFs are in `knowledge_base/raw/` |
| Chat WebSocket not integrated in frontend | `ModChatbot.jsx` still uses placeholder/mock responses |

---

## Environment Setup

### Backend
```bash
cd backend
pip install -r requirements.txt
# Copy .env.example to .env, fill in MONGODB_URL, SECRET_KEY, GEMINI_API_KEY
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev    # runs on port 3000 (Next.js)
```

### Key env vars (backend `.env`):
```
MONGODB_URL=mongodb://localhost:27017
DB_NAME=attorney_ai
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
GEMINI_API_KEY=<your key>
GROQ_API_KEY=<your key>  (fallback LLM)
LLM_PROVIDER=gemini
```

### Key env vars (frontend `.env.local`):
```
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

---

## Known Issues / Watch Points

1. **`lawyers_collection` is empty** — `matchLawyers()` will fall back to MongoDB-only scoring until an admin calls `POST /admin/lawyers/embed-all`. The frontend handles empty results gracefully (toast: "No matched lawyers found").

2. **`fee` field** — Lawyer consultation fee is not in the backend User schema. `mapApiLawyer()` hardcodes 5000 PKR. Add a `fee` field to `lawyer_profile` schema when needed.

3. **`reviewList` is empty from API** — Profile view shows "No reviews yet" for real lawyers. Reviews are stored as a rolling average in `lawyer_profile.rating` + `total_reviews`, not as individual records. To show individual reviews, need a separate reviews collection or embedded array.

4. **`distance` field** — Backend has no geolocation. `mapApiLawyer()` sets `distance: null`. Map view in ModLawyers will show null distance for API lawyers. Mock lawyers still have hardcoded distances.

5. **Intake token after convert** — After `intakeConvert`, the token is cleared from localStorage. If user refreshes mid-intake, they start fresh. This is intentional — one convert per session.

6. **ModChatbot WebSocket** — Currently uses a static stub response. The backend `/ws/chat/{session_id}` is built and ready. Wiring it is the next major frontend task.

7. **`@/context/AuthContext.jsx`** — If this path doesn't resolve, check `frontend/src/context/AuthContext.jsx` exists. It was created in a prior session.

---

## Next Session Priorities (in order)

### Priority 1: Wire ModChatbot.jsx to WebSocket
- Create chat session: `POST /chat/sessions` → get `session_id`
- Connect: `ws://localhost:8000/ws/chat/{session_id}`
- Send: `{"type": "message", "content": "...", "case_id": "...", "province": "...", "case_type": "..."}`
- Receive stream: `{"type": "token", "content": "..."}` | `{"type": "final", "content": "...", "citations": [...]}` | `{"type": "clarification", "question": "..."}`
- Read `case_id` from `localStorage["aai-case-id"]` and `case_type`/`province` from CaseContext or localStorage

### Priority 2: Wire ModTracking.jsx (Case Status)
- `GET /cases` → list user's cases
- `GET /cases/{case_id}` → case detail + milestones
- Display hearing dates, status changes

### Priority 3: Knowledge Base Ingestion
- Place Pakistani law PDFs in `backend/knowledge_base/raw/`
- Run: `python ingest.py && python chunk.py && python embed.py && python store.py`
- Verify collections are populated in ChromaDB

### Priority 4: Documents + Agreements
- Wire `ModDocuments.jsx` to `POST/GET /documents`
- Wire `ModAgreements.jsx` to `POST/GET /agreements`

---

*Attorney.AI | SP23-BCS-069 | Muhammad Usama | May 2026*
*Generated: 2026-05-08*
