# Backend Security Review — Attorney.AI

Session date: 2026-05-01  
Reviewer: Claude (claude-sonnet-4-6)  
Scope: Full read-through of `backend/app/` after initial non-AI backend completion

---

## What was reviewed

Every route, service, repository, schema, dependency, WebSocket handler, index definition, and the main app entrypoint. 68 files across:

```
api/v1/routes/   auth, users, cases, intake, lawyers, documents, agreements, notifications, admin
services/        auth, user, case, lawyer, document, agreement, intake, notification, admin
repositories/    base, user, case, intake, document, agreement, notification, chat
websockets/      chat_socket, notification_socket, manager
core/            config, constants, exceptions, security, rate_limit
db/              mongodb, collections, indexes
schemas/         all
dependencies.py
main.py
```

---

## Bugs found and fixed

### 1. `lawyer_service.search_lawyers()` leaked `password_hash` + `cnic_encrypted`

**File:** `backend/app/services/lawyer_service.py`  
**Severity:** High — any authenticated user querying `GET /lawyers` received hashed passwords

**Root cause:** The function called `user_repo.find_lawyers()` directly and returned the raw `PaginatedResponse` without sanitizing. `user_service.list_lawyers()` did the same thing correctly (with sanitization) but was never called — it was dead code.

**Fix:** Added a local `_sanitize()` helper and applied it to `result.items` before returning.

```python
def _sanitize(user: dict) -> dict:
    user = dict(user)
    user.pop("password_hash", None)
    user.pop("cnic_encrypted", None)
    return user

async def search_lawyers(...):
    result = await user_repo.find_lawyers(...)
    result.items = [_sanitize(u) for u in result.items]
    return result
```

Also removed the dead `user_service.list_lawyers()` function.

---

### 2. `lawyer_service.match_lawyers_for_case()` leaked `password_hash`

**File:** `backend/app/services/lawyer_service.py`  
**Severity:** High — `GET /lawyers/match/{case_id}` (client-only endpoint) returned raw user docs in scored list

**Fix:** Applied `_sanitize()` to each candidate before spreading into scored dict:

```python
scored.append({**_sanitize(lawyer), "match_score": match_score})
```

---

### 3. `admin_service.list_pending_kyc()` leaked `password_hash`

**File:** `backend/app/services/admin_service.py`  
**Severity:** High — admin endpoint `GET /admin/kyc/pending` returned full user documents

**Fix:** Stripped sensitive fields from the returned list:

```python
users = await user_repo.find_many({...})
return [{k: v for k, v in u.items() if k not in ("password_hash", "cnic_encrypted")} for u in users]
```

---

### 4. `notification_socket.py` accepted refresh tokens as auth

**File:** `backend/app/websockets/notification_socket.py`  
**Severity:** Low — refresh tokens could open a persistent WebSocket connection as the user

**Root cause:** Auth check only verified `payload["sub"] == user_id` but not the token type, so a valid refresh JWT passed the guard.

**Fix:**

```python
# Before
if not payload or payload.get("sub") != user_id:

# After
if not payload or payload.get("type") != "access" or payload.get("sub") != user_id:
```

---

## Everything else verified correct

These were inspected and found to be working as designed:

| Area | Status | Notes |
|---|---|---|
| `user_service._sanitize()` | Correct | Used on all `/users/me` and `/users/{id}` responses |
| `auth_service.register()` | Correct | `cnic_encrypted` omitted (not `null`) — sparse index skip works |
| `DuplicateKeyError` handling | Correct | Catches email + CNIC collisions gracefully |
| `BaseRepository.paginate()` | Correct | `PaginatedResponse` returned; routes that return lists use no `response_model` |
| `case_service._assert_access()` | Correct | Admin bypass, client/lawyer ownership check |
| `intake_repo.update_step()` | Correct | `$max` operator ensures `current_step` only advances |
| `agreement_repo.update_party_signature()` | Correct | Positional `$` operator correctly targets matched party |
| `admin_service.get_analytics()` | Correct | Return shape matches `AnalyticsOverview` schema |
| `indexes.py` sparse index | Correct | `cnic_encrypted` index is `sparse=True` — absent field skips indexing |
| JWT decode returns `{}` on error | Correct | No exception leakage from `decode_token()` |
| `email._send()` no-op in dev | Correct | Silently skips when `smtp_user` is empty |
| `redirect_slashes=False` + root routes use `""` | Correct | No 307 redirects |
| WebSocket chat stub | Correct | Stores messages, returns placeholder until AI phase |

---

## Requirements fixes (same session)

Two packages were installed in the venv but missing from `requirements.txt`:

```
bcrypt==5.0.0      # replaces passlib — used in security.py
websockets==16.0   # pulled in by uvicorn[standard]; needed explicitly for test client
```

Both added to `backend/requirements.txt` under `# Auth & Security`.

---

## Verification script

`backend/verify_security_fixes.py` — self-contained Python script, no manual curl needed.

**What it does:**
1. Registers fresh test accounts (client, lawyer, admin) with random suffixes
2. Admin approves lawyer KYC so they appear in search results
3. Client creates a case for the match endpoint test
4. Leaves a second lawyer unverified so the KYC pending list has entries

**Tests run:**

| Test | Endpoint | Check |
|---|---|---|
| 1a | `GET /lawyers` | `password_hash` absent |
| 1b | `GET /lawyers` | `cnic_encrypted` absent |
| 2a | `GET /lawyers/match/{case_id}` | `password_hash` absent |
| 2b | `GET /lawyers/match/{case_id}` | `cnic_encrypted` absent |
| 3a | `GET /admin/kyc/pending` | `password_hash` absent |
| 3b | `GET /admin/kyc/pending` | `cnic_encrypted` absent |
| 4a | `WS /ws/notifications/{id}?token=<refresh_jwt>` | Rejected (HTTP 403 or WS 4001) |
| 4b | `WS /ws/notifications/{id}?token=<access_jwt>` | Accepted (control — proves check is discriminating) |

**Run:**
```bash
cd backend
# Start server first
uvicorn app.main:app --reload --port 8000

# In another terminal
python verify_security_fixes.py
```

**Result:** 11/11 PASS (verified 2026-05-01)

**WS rejection note:** FastAPI/Starlette rejects the WebSocket upgrade handshake before `websocket.accept()` is called, so the client sees HTTP 403 (not WebSocket close code 4001). Both are valid — the connection is denied either way.

---

## Architectural notes (for AI phase)

These `# TODO: AI` markers exist in the codebase and define where LangGraph integrates:

| File | What to replace |
|---|---|
| `case_service.create_case()` | Embed case description → `case_embedding` field |
| `intake_service.convert_to_case()` | Trigger `ai_structured_case` async after conversion |
| `lawyer_service.match_lawyers_for_case()` | Replace `0.3` static score with `cosine_similarity(case_embedding, lawyer_embedding) * 0.5` |
| `document_service.generate_document()` | LLM field extraction from case data instead of manual `fields` dict |
| `chat_socket.py` | Replace stub response with `LangGraph supervisor.ainvoke()` + token streaming |

All stubs are wired correctly — the DB writes, session management, and message storage already work. Only the AI call needs to be plugged in.
