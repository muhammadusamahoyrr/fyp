# Attorney.AI — Progress Report
> SP23-BCS-069 | Muhammad Usama | May 2026

---

## Overall Progress

| Phase | Status | Coverage |
|-------|--------|----------|
| Non-AI Backend (core infra, auth, cases, docs, agreements, admin) | ✅ Complete | 68 files, 0 syntax errors |
| Legal Intake Module | ✅ Complete | 5-step form, session token, convert-to-case |
| Lawyer Matching Module | ✅ Complete | Filter + score-based ranking, rolling reviews |
| **Voice / STT Module** | ✅ **Complete** | This milestone |
| **Frontend Auth Infrastructure** | ✅ **Complete** | This milestone |
| **API Layer (frontend ↔ backend)** | 🔄 **In Progress** | Voice + Auth wired; remaining modules pending |
| AI Pipeline (LangGraph + RAG) | 🔲 Next | Steps 1–6 |
| Knowledge Base Ingestion | 🔲 Next | — |
| Testing & Evaluation | 🔲 Pending | — |

**~40% of total project scope is done.**

---

## ✅ Module 3 — Voice / STT (Fully Complete)

### What Was Built

End-to-end voice transcription pipeline for the legal intake form — browser mic → WAV → backend Whisper → transcript with language detection.

### Backend: `app/services/whisper_service.py`

| Feature | Implementation |
|---------|---------------|
| Singleton | `__new__` pattern — one `WhisperModel` instance per process |
| Thread-safe model init | `threading.Lock()` in `load()` — prevents double-load under concurrent startup |
| Lazy loading | `model` property auto-loads on first access |
| Startup warmup | `async def warmup()` — fires `asyncio.create_task(to_thread(load))` at lifespan startup; first user never waits 30 s |
| Request queue protection | `asyncio.Lock() (_alock)` in `transcribe_async()` — serialises CPU inference, prevents saturation under 5+ concurrent requests |
| Audio decoding | `_decode(bytes, filename)` — soundfile primary (WAV/FLAC/OGG, no system deps), temp-file ffmpeg fallback (webm/mp4) |
| Language detection | Returns `language` (ISO 639-1 code), `language_name` (display name), `language_probability` (0–1) |
| Pakistani language map | `ur→Urdu`, `en→English`, `pa→Punjabi`, `sd→Sindhi`, `ps→Pashto`, `hi→Hindi`, `ar→Arabic`, `fa→Persian` |
| Model config | `base` / `cpu` / `int8` — no GPU required |

**Two-lock design:**
- `_lock` (threading) — guards sync `load()` which runs in a thread pool
- `_alock` (asyncio) — guards `transcribe_async()` which runs in the event loop

### Backend: `app/api/v1/routes/voice.py`

```
POST /api/v1/voice/transcribe
```

| Property | Value |
|----------|-------|
| Auth | Bearer token required |
| Rate limit | 10 requests / minute |
| Max file size | 10 MB |
| Queue | `await whisper_service.transcribe_async(...)` — single-request serialisation |
| Response | `{ transcript, language, language_name, language_probability }` |

### Backend: `app/main.py` (lifespan update)

```python
await whisper_service.warmup()   # replaces 3-line inline asyncio.create_task block
```

### Frontend: `ModIntake.jsx` — Voice UI State Machine

6-state machine replaces simple boolean flags:

| State | Icon | Badge | Meaning |
|-------|------|-------|---------|
| `idle` | 🎙️ | — | No recording yet |
| `recording` | 🎤 | ● REC | Mic active |
| `stopped` | ⏸️ | STOPPED | Recorded, ready to convert |
| `transcribing` | ⏳ | ⏳ PROCESSING | API call in-flight |
| `ready` | ✅ | ✅ READY | Transcript available |
| `error` | ❌ | ❌ FAILED | API error |

Additional features:
- `MAX_REC_SECS = 120` — auto-stops at 2 min; 15-second countdown warning shown
- Browser-side WAV conversion: WebM → 16 kHz mono PCM via `AudioContext` → `_pcmToWav()` (custom 17-line encoder, no ffmpeg dep on backend)
- `voiceLang` state — shows detected language + confidence pill next to badge (`Urdu · 94%`)
- Toast on success: `"Transcript ready — detected Urdu (94%)"`
- Convert disabled when `voiceStatus === "ready"` (prevents redundant re-transcription)
- Clear disabled during transcription (prevents in-flight API response overwriting cleared state)

### Frontend: `lib/api.js` — `transcribeAudio`

Moved from raw `fetch` to `apiFetchMultipart` — full parity with `apiFetch`:
- Bearer token attached automatically
- 401 retry via `_tryRefresh()` + new access token
- Consistent `{ data, error, status }` return shape

---

## ✅ Module 4 — Frontend Auth Infrastructure (Fully Complete)

### What Was Built

Global auth state management so every page knows who is logged in — replaces raw `localStorage` guards with React Context.

### `src/context/AuthContext.jsx`

| Feature | Detail |
|---------|--------|
| Hydration | On mount: reads stored token → `GET /users/me` → sets full profile |
| Offline fallback | Network error during hydration → reads `aai-role` from `localStorage` so routing still works |
| `login(tokenData)` | Sets token + `{ _id, role }` immediately (unblocks routing), then enriches with full profile in background fetch |
| `logout()` | Calls `authLogout`, clears token + `aai-role`, sets `user = null` |
| `updateUser(patch)` | Shallow-merges partial updates into user object (used by profile edit) |
| Exports | `useAuth()` hook, `AuthProvider` component |
| Context value | `{ user, role, isAuthenticated, loading, login, logout, updateUser }` |

### `src/app/Providers.jsx`

Server-component-safe wrapper — `'use client'` boundary around `<AuthProvider>` for use in Next.js root layout.

### `src/components/shared/ProtectedRoute.jsx`

| Scenario | Behaviour |
|----------|-----------|
| Loading | Shows `AuthSpinner` (dark bg, teal CSS spinner) |
| Not authenticated | `router.replace('/login')` + `return null` |
| Wrong role | `router.replace(ROLE_HOME[role])` + `return null` |
| Correct role | Renders `children` |

All three route group layouts (`(client)`, `(lawyer)`, `(admin)`) changed from `<AuthGuard requiredRole>` to `<ProtectedRoute allowedRoles={[...]}>`

### `src/app/layout.jsx`

Root layout now wraps `<body>` with `<Providers>` so auth context is available everywhere.

### Auth pages updated

- **Login** — calls `auth.login(data)` after success; redirects already-authenticated users away
- **Register** — auto-logins after successful registration (backend returns `StatusResponse`, not token), falls back to `/login` redirect on failure

---

## 🔄 API Layer — `src/lib/api.js`

### Network Error Safety

Both `fetch()` calls inside `apiFetch` (initial + post-refresh retry) wrapped in `try/catch` — loading states no longer get stuck on network failure.

### `apiFetchMultipart(path, formData)` — new private helper

Mirrors `apiFetch` for `FormData` uploads:
- No `Content-Type` header set — browser injects `multipart/form-data; boundary=…`
- Bearer token attached
- 401 retry with refresh
- Consistent `{ data, error, status }` return

### Functions added

| Function | Endpoint |
|----------|----------|
| `transcribeAudio(blob)` | `POST /voice/transcribe` (via `apiFetchMultipart`) |
| `getMe()` | `GET /users/me` |
| `updateMe(updates)` | `PATCH /users/me` |

---

## AI Pipeline Design (Unchanged — Pending Implementation)

### Node Flow (8 nodes)

```
query → intake_node → gatekeeper_node
                          │ non-legal → canned response
                          ↓
                     supervisor ──routes by case_type──→ civil_agent
                                                      → criminal_agent
                                                      → constitutional_agent
                          ↓
                     retrieval_node  (BM25 0.6 + Chroma 0.4, province filter)
                          ↓
                     reranker_node   (RRF)
                          ↓
                     hallucination_node  (relevance check + grounding check — merged)
                          │ relevance < 0.75 → clarification_node → interrupt()
                          │ not grounded     → refuse + suggest lawyer
                          ↓
                     generation_node  (LLM streams tokens via WebSocket)
```

### AI Stub Hooks (3 exact insertion points — unchanged)

| File | Function | What plugs in |
|------|----------|---------------|
| `services/intake_service.py` | `convert_to_case()` | LangGraph `intake_node` → fills `ai_structured_case` |
| `websockets/chat_socket.py` | stub response block | LangGraph supervisor + token streaming |
| `services/lawyer_service.py` | `match_lawyers_for_case()` | `cosine_similarity(case_emb, lawyer_emb) * 0.5` |

---

## WebSocket Protocol (Unchanged)

### Client → Server
```json
{"type": "message", "content": "...", "case_id": "...", "province": "Punjab", "case_type": "civil"}
```

### Server → Client
```json
{"type": "token",         "content": "..."}
{"type": "final",         "content": "...", "citations": [...], "confidence": 0.87}
{"type": "clarification", "question": "..."}
{"type": "error",         "message": "AI service unavailable — please try again"}
```

---

## Remaining Work

| # | Feature | Status |
|---|---------|--------|
| 1 | Wire remaining frontend modules to backend API (cases, chat, documents, agreements, lawyers, notifications, admin) | 🔲 Next |
| 2 | AI Pipeline — LangGraph supervisor + 8 nodes | 🔲 Next |
| 3 | Knowledge base ingestion (parse → chunk → embed → Chroma) | 🔲 Next |
| 4 | Embedding-based lawyer matching (replace scoring stub) | 🔲 Next |
| 5 | AI case structuring at intake convert | 🔲 Next |
| 6 | Unit / integration tests | 🔲 Pending |

---

*Attorney.AI | SP23-BCS-069 | Muhammad Usama | May 2026*
