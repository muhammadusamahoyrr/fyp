# Attorney.AI — Backend Flow Diagrams
> SP23-BCS-069 | Muhammad Usama | April 2026

---

## 1. Overall Request Architecture

Every HTTP request and WebSocket connection passes through the same layer stack.

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js)                       │
│          HTTP Requests          │        WebSocket              │
└──────────────┬──────────────────┴──────────┬────────────────────┘
               │  /api/v1/*                   │  /ws/*
               ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FastAPI  (app/main.py)                        │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│   │  CORS        │  │  slowapi     │  │  Exception Handlers  │ │
│   │  Middleware  │  │  Rate Limit  │  │  (401/403/404/429/   │ │
│   │              │  │  Middleware  │  │   500)               │ │
│   └──────────────┘  └──────────────┘  └──────────────────────┘ │
└──────────────┬──────────────────────────────┬───────────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────┐   ┌──────────────────────────────────┐
│   REST Routes            │   │   WebSocket Endpoints            │
│   app/api/v1/routes/     │   │   app/websockets/                │
│   ├── auth.py            │   │   ├── chat_socket.py             │
│   ├── users.py           │   │   └── notification_socket.py     │
│   ├── cases.py           │   └──────────────┬───────────────────┘
│   ├── intake.py          │                  │
│   ├── lawyers.py         │                  │
│   ├── documents.py       │                  │
│   ├── agreements.py      │                  │
│   ├── notifications.py   │                  │
│   └── admin.py           │                  │
└──────────────┬───────────┘                  │
               │                              │
               ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              app/dependencies.py                                │
│   get_current_user() → decode JWT → fetch user from MongoDB    │
│   role_required()    → check role → raise ForbiddenError       │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              app/services/   (Business Logic)                   │
│   auth_service  │ case_service  │ intake_service               │
│   user_service  │ lawyer_service│ document_service             │
│   agreement_service │ notification_service │ admin_service      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              app/repositories/  (Data Access Only)              │
│   BaseRepository → find_one, find_many, insert, update, paginate│
│   user_repo │ case_repo │ intake_repo │ document_repo           │
│   agreement_repo │ notification_repo │ chat_repo                │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              app/db/   (MongoDB via Motor)                      │
│   mongodb.py → AsyncIOMotorClient singleton                     │
│   collections.py → typed collection accessors (lazy)           │
│   indexes.py → all indexes created at startup                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              MongoDB (port 27017)                               │
│   users │ cases │ intakes │ documents │ agreements              │
│   notifications │ chat_sessions                                 │
│   refresh_token_blocklist │ password_reset_tokens               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Auth Flow

### 2a. Register + Login

```
Client                       FastAPI                    MongoDB
  │                             │                          │
  │── POST /auth/register ─────►│                          │
  │   { email, password, role } │                          │
  │                             │ validate password        │
  │                             │ validate email unique ──►│
  │                             │◄── user not found ───────│
  │                             │ bcrypt hash (cost 12)    │
  │                             │ insert user doc ────────►│
  │◄── 200 { success: true } ───│◄── inserted ─────────────│
  │                             │                          │
  │── POST /auth/login ────────►│                          │
  │   { email, password }       │ find_by_email ──────────►│
  │                             │◄── user doc ─────────────│
  │                             │ verify_password (bcrypt) │
  │                             │ create_access_token (JWT 60min)
  │                             │ create_refresh_token (JWT 7d)
  │◄── 200 {                ────│                          │
  │     access_token,           │                          │
  │     role, user_id           │                          │
  │   }                         │                          │
  │   Set-Cookie:               │                          │
  │   refresh_token=...         │                          │
  │   httpOnly;Secure;          │                          │
  │   SameSite=Strict           │                          │
```

### 2b. Every Authenticated Request

```
Client                   dependencies.py              MongoDB
  │                             │                          │
  │── ANY /api/v1/* ───────────►│                          │
  │   Authorization: Bearer     │                          │
  │   <access_token>            │                          │
  │                             │ decode_token(JWT)        │
  │                             │ check type == "access"   │
  │                             │ extract sub (user_id)    │
  │                             │ find_one(_id, is_active)►│
  │                             │◄── user doc ─────────────│
  │                             │ inject user into route   │
  │                             │──► route handler         │
  │◄── response ────────────────│                          │
```

### 2c. Token Refresh

```
Client              auth route           auth_service         MongoDB
  │                     │                     │                  │
  │── POST /auth/refresh►│                     │                  │
  │   Cookie:            │                     │                  │
  │   refresh_token=...  │ read cookie         │                  │
  │                      │──► refresh(token) ──►                  │
  │                      │                     │ decode_token     │
  │                      │                     │ check type==refresh
  │                      │                     │ check blocklist ►│
  │                      │                     │◄── not found ────│
  │                      │                     │ find_by_id ─────►│
  │                      │                     │◄── user doc ─────│
  │                      │                     │ create_access_token
  │◄── 200 {access_token}│◄────────────────────│                  │
```

### 2d. Logout

```
Client              auth route           auth_service         MongoDB
  │                     │                     │                  │
  │── POST /auth/logout ►│                     │                  │
  │   Cookie: refresh_token                    │                  │
  │                      │ read cookie         │                  │
  │                      │──► logout(token) ──►│                  │
  │                      │                     │ decode_token     │
  │                      │                     │ (validate JWT)   │
  │                      │                     │ insert blocklist►│
  │                      │                     │◄── ok ───────────│
  │◄── 200 success ───── │ delete_cookie        │                  │
```

---

## 3. Intake → Case Conversion Flow

```
Client (5 separate requests)              intake_service         case_service
  │                                            │                      │
  │── POST /intake/start ─────────────────────►│                      │
  │                                            │ generate session_token│
  │                                            │ insert intake doc     │
  │◄── { session_token: "abc123" } ────────────│                      │
  │                                            │                      │
  │── PATCH /intake/abc123/step/1 ────────────►│                      │
  │   { province: "punjab" }                   │ validate required fields
  │                                            │ update_step() → $max current_step
  │◄── { current_step: 2 } ────────────────────│                      │
  │                                            │                      │
  │── PATCH /intake/abc123/step/2 ────────────►│                      │
  │   { case_type: "civil", urgency: "high" }  │ validate             │
  │◄── { current_step: 3 } ────────────────────│                      │
  │                                            │                      │
  │── PATCH /intake/abc123/step/3 ────────────►│                      │
  │   { incident_description: "..." }          │ validate             │
  │◄── { current_step: 4 } ────────────────────│                      │
  │                                            │                      │
  │── PATCH /intake/abc123/step/4 ────────────►│                      │
  │   { has_evidence: true, ... }              │ (no required fields) │
  │◄── { current_step: 5 } ────────────────────│                      │
  │                                            │                      │
  │── PATCH /intake/abc123/step/5 ────────────►│                      │
  │   { desired_outcome: "..." }               │ validate             │
  │◄── { current_step: 6 } ────────────────────│                      │
  │                                            │                      │
  │── POST /intake/abc123/convert ────────────►│                      │
  │                                            │ assert all 5 steps   │
  │                                            │ merge step1+2+3 data │
  │                                            │──── create_case() ──►│
  │                                            │                      │ generate ATT-YYYY-XXXX
  │                                            │                      │ insert case doc
  │                                            │◄── case { _id } ─────│
  │                                            │ mark_completed()     │
  │                                            │ set case_id on intake│
  │                                            │ # TODO:AI structuring│
  │◄── { completed:true, case_id: "xyz" } ─────│                      │
```

---

## 4. WebSocket Chat Flow

```
Browser                 chat_socket.py           chat_repo          MongoDB
  │                          │                       │                 │
  │── ws://host/ws/chat/     │                       │                 │
  │   {session_id}?token=JWT►│                       │                 │
  │                          │ decode_token(JWT)      │                 │
  │                          │ validate type==access  │                 │
  │                          │ accept()               │                 │
  │                          │ find_by_session ──────►│                 │
  │                          │◄── None ───────────────│                 │
  │                          │ insert session doc ────►──────────────►  │
  │                          │                        │                 │
  │── { type:"message",  ───►│                        │                 │
  │    content:"...",        │ append user_message ──►│────────────────►│
  │    case_id, province,    │ update_session_meta ──►│────────────────►│
  │    case_type }           │                        │                 │
  │                          │ [STUB — AI not wired]  │                 │
  │◄── { type:"final",   ────│ append assistant msg ─►│────────────────►│
  │     content:"...",       │                        │                 │
  │     citations:[],        │                        │                 │
  │     confidence:0.0 }     │                        │                 │
  │                          │                        │                 │
  │   [connection stays      │                        │                 │
  │    open — loop repeats]  │                        │                 │
  │                          │                        │                 │
  │── disconnect ───────────►│ WebSocketDisconnect    │                 │
  │                          │ (handled silently)     │                 │
```

> **AI phase hook**: Replace stub block with `LangGraph supervisor.ainvoke()` → stream tokens via `websocket.send_json({"type":"token","content":chunk})`

---

## 5. WebSocket Notification Flow

```
Browser              notification_socket.py    notification_service    MongoDB
  │                          │                        │                  │
  │── ws://host/ws/           │                        │                  │
  │   notifications/          │                        │                  │
  │   {user_id}?token=JWT ───►│                        │                  │
  │                           │ decode_token(JWT)       │                  │
  │                           │ validate sub==user_id   │                  │
  │                           │ connect(user_id, ws)    │                  │
  │                           │ find_unread ──────────────────────────────►│
  │◄── { type:"unread_count", │◄──────────────────────────────────────────│
  │     count: N }            │                        │                  │
  │                           │                        │                  │
  │   [stays open, waiting]   │                        │                  │
  │                           │                        │                  │
  │         ← triggered by any service calling create_notification() →    │
  │                           │  ◄── set_ws_manager() wired at startup    │
  │                           │        ▲                │                  │
  │                           │        │ send_to_user() │                  │
  │◄── { type:"notification", │◄───────┘                │                  │
  │     title:"...",          │  notification_manager   │                  │
  │     body:"..." }          │  (ConnectionManager)    │                  │
```

---

## 6. Lawyer Matching Flow

```
Client (POST case created)        lawyer_service          user_repo (MongoDB)
  │                                    │                        │
  │── GET /lawyers/match/{case_id} ───►│                        │
  │                                    │ find_by_id(case_id) ──►│
  │                                    │◄── { province, case_type, ... }
  │                                    │                        │
  │                                    │ find_lawyers(          │
  │                                    │   province=case.province
  │                                    │   case_type=case.case_type
  │                                    │   kyc_verified=True    │
  │                                    │   limit=20             │
  │                                    │ ) ────────────────────►│
  │                                    │◄── [candidates list] ──│
  │                                    │                        │
  │                                    │ for each lawyer:       │
  │                                    │   rating_score = (rating/5) * 0.5
  │                                    │   avail_score  = 0.2 if available
  │                                    │   match_score  = rating + avail + 0.3
  │                                    │   # TODO:AI — 0.3 → cosine_similarity
  │                                    │   #           (case_emb, lawyer_emb) * 0.5
  │                                    │                        │
  │                                    │ sort by match_score DESC
  │                                    │ return top 5           │
  │◄── [ top 5 lawyers + scores ] ─────│                        │
```

---

## 7. Document Generation Flow

```
Client            document_service           doc_repo    MongoDB   Filesystem
  │                     │                       │           │           │
  │── POST /documents/  │                       │           │           │
  │   /generate ───────►│                       │           │           │
  │   { case_id,        │ find case ────────────────────────►           │
  │     template_type,  │◄─── case doc ─────────────────────            │
  │     fields: {...} } │                       │           │           │
  │                     │ insert doc (pending) ─►──────────►            │
  │                     │                       │           │           │
  │                     │ asyncio.to_thread:     │           │           │
  │                     │   DocxTemplate.render()──────────────────────►│
  │                     │   → output.docx        │           │           │
  │                     │                       │           │           │
  │                     │ asyncio.to_thread:     │           │           │
  │                     │   libreoffice          │           │           │
  │                     │   --headless           │           │           │
  │                     │   --convert-to pdf ──────────────────────────►│
  │                     │   → output.pdf         │           │           │
  │                     │   unlink .docx         │           │           │
  │                     │                       │           │           │
  │                     │ update_file_path ─────►──────────►            │
  │◄── { status:       ─│   (status: generated)  │           │           │
  │      "generated",   │                       │           │           │
  │      file_path }    │                       │           │           │
  │                     │                       │           │           │
  │── GET /documents/   │                       │           │           │
  │   {id}/download ───►│ get_document(id) ─────►──────────►            │
  │                     │ check ownership        │           │           │
  │◄── FileResponse     │ stream PDF ◄──────────────────────────────────│
  │    (application/pdf)│                       │           │           │
```

---

## 8. Agreement E-Signing Flow (ETO 2002)

```
Creator              agreement_service        agreement_repo       MongoDB
  │                        │                        │                 │
  │── POST /agreements ───►│                        │                 │
  │   { title,             │ build parties list     │                 │
  │     body_html,         │ create audit entry     │                 │
  │     party_ids }        │ insert doc (PENDING) ─►│────────────────►│
  │◄── agreement doc ──────│                        │                 │
  │                        │                        │                 │
  │                   ┌────────────────────────────────────────┐      │
  │                   │  Each party signs independently        │      │
  │                   └────────────────────────────────────────┘      │
  │                        │                        │                 │
  │── POST /agreements/    │                        │                 │
  │   {id}/sign ──────────►│                        │                 │
  │   { method:"canvas",   │ find agreement ───────►│────────────────►│
  │     signature_data }   │◄─── agreement ─────────│◄────────────────│
  │                        │ verify requester is party                │
  │                        │ check not already signed                 │
  │                        │ check not EXECUTED                       │
  │                        │ classify by ETO 2002:                    │
  │                        │  canvas → "Advanced Electronic Signature"│
  │                        │  typed  → "Basic Electronic Signature"   │
  │                        │ update_party_signature ►│────────────────►│
  │                        │ append_audit_log ──────►│────────────────►│
  │                        │                        │                 │
  │                        │ re-fetch all parties   │                 │
  │                        │ all signed? ──────────►│────────────────►│
  │                        │    YES → set_status(EXECUTED)            │
  │                        │    NO  → stays PENDING                   │
  │◄── agreement doc ──────│                        │                 │
```

---

## 9. Admin KYC Verification Flow

```
Lawyer           Admin              admin_service       notification_service  Email
  │               │                     │                      │               │
  │ registers,    │                     │                      │               │
  │ sets bar_number                     │                      │               │
  │               │                     │                      │               │
  │               │── GET /admin/kyc/   │                      │               │
  │               │   pending ─────────►│                      │               │
  │               │                     │ find lawyers where:   │               │
  │               │                     │   kyc_verified=False │               │
  │               │                     │   bar_number != null │               │
  │               │◄── [pending list] ──│                      │               │
  │               │                     │                      │               │
  │               │── PATCH /admin/     │                      │               │
  │               │   kyc/{lawyer_id}   │                      │               │
  │               │   { approved:true } ►                      │               │
  │               │                     │ find lawyer          │               │
  │               │                     │ set kyc_verified=True│               │
  │               │                     │──── create_notification ────────────►│
  │◄── WebSocket push: "KYC Approved" ──────────────────────── │               │
  │               │                     │──── send_kyc_result_email ──────────►│
  │◄── Email: "Your profile is verified" ─────────────────────────────────────│
  │               │◄── success ─────────│                      │               │
```

---

## 10. Password Reset Flow

```
Client                 auth route          auth_service      MongoDB    Email
  │                        │                    │               │          │
  │── POST /auth/           │                    │               │          │
  │   forgot-password ─────►│                    │               │          │
  │   { email }             │──── forgot_password(email) ───────►           │
  │                         │                    │ find_by_email►│           │
  │                         │                    │◄── user ──────│           │
  │                         │                    │ delete old tokens ───────►│
  │                         │                    │ insert new token ─────────►
  │                         │                    │ send_password_reset_email►│
  │◄── 200 (always) ────────│                    │               │          │
  │    "If email exists..." │                    │               │          │
  │                         │                    │               │          │
  │── POST /auth/           │                    │               │          │
  │   reset-password ──────►│                    │               │          │
  │   { token, new_password}│──── reset_password ────────────────►           │
  │                         │                    │ validate password strength│
  │                         │                    │ find token ──►│           │
  │                         │                    │◄── record ────│           │
  │                         │                    │ find user by email       │
  │                         │                    │ bcrypt new password       │
  │                         │                    │ update password_hash ────►│
  │                         │                    │ delete reset token ──────►│
  │◄── 200 success ─────────│                    │               │          │
```

---

## 11. Startup Sequence (lifespan)

```
uvicorn starts
     │
     ▼
app/main.py  lifespan()
     │
     ├─► connect_db()
     │       │── AsyncIOMotorClient(MONGODB_URL)
     │       └── ping MongoDB  ← crashes here if Mongo is down
     │
     ├─► create_all_indexes()
     │       ├── users: email(unique), cnic(unique sparse), role, province, kyc_verified
     │       ├── cases: case_number(unique), client_id, lawyer_id, status, case_type
     │       ├── intakes: session_token(unique), client_id
     │       ├── documents: case_id, client_id
     │       ├── agreements: status, parties.user_id
     │       ├── notifications: user_id, read, created_at TTL(30d)
     │       ├── chat_sessions: session_id(unique), client_id
     │       ├── refresh_token_blocklist: token(unique), created_at TTL(7d)
     │       └── password_reset_tokens: token(unique), email, created_at TTL(1h)
     │
     ├─► set_ws_manager(notification_manager)
     │       └── wires ConnectionManager into notification_service
     │           so create_notification() can push to open WebSockets
     │
     ▼
  Server ready — accepting requests on port 8000
     │
     ...
     │
  shutdown signal
     │
     └─► close_db()
             └── Motor client.close()
```

---

## 12. Error Response Contract

Every error in the system returns the same JSON shape:

```
HTTP 401  AuthError
{ "error": "Invalid or expired token", "status_code": 401 }
Headers:  WWW-Authenticate: Bearer

HTTP 403  ForbiddenError
{ "error": "Insufficient permissions", "status_code": 403 }

HTTP 404  NotFoundError
{ "error": "Case not found", "status_code": 404 }

HTTP 409  ConflictError
{ "error": "Email already registered", "status_code": 409 }

HTTP 422  AppValidationError
{ "error": "Missing required fields for step 2: ['urgency']", "status_code": 422 }

HTTP 429  RateLimitExceeded
{ "error": "Too many requests. Please slow down.", "status_code": 429 }

HTTP 500  Unhandled Exception
{ "error": "Internal server error", "status_code": 500 }
```

---

## 13. Data Flow Summary — Who Reads/Writes What

```
Collection              Written by                    Read by
─────────────────────────────────────────────────────────────────────
users                   auth_service (register)       auth_service (login)
                        user_service (update)         dependencies.py (auth)
                        admin_service (kyc)           lawyer_service (match)

cases                   case_service (create)         case_service (get/list)
                        case_service (update)         lawyer_service (match)
                        case_service (milestone/hearing)

intakes                 intake_service (start/step)   intake_service (convert)
                        intake_service (mark_completed)

documents               document_service (generate)   document_service (download)

agreements              agreement_service (create)    agreement_service (get/sign)

notifications           notification_service          notification_service
                        (any service via create_notification)
                                                      notification_socket (unread)

chat_sessions           chat_socket (create/append)   chat_socket (find)

refresh_token_blocklist auth_service (logout)         auth_service (refresh check)
                        (TTL auto-deletes after 7d)

password_reset_tokens   auth_service (forgot)         auth_service (reset)
                        (TTL auto-deletes after 1h)
```

---

*Attorney.AI | SP23-BCS-069 | Muhammad Usama | April 2026*
