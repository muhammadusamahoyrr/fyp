# Attorney.AI — Backend Progress Report
> SP23-BCS-069 | Muhammad Usama | April 2026

---

## What Was Built (Non-AI Backend)

The entire non-AI backend was built from scratch. The `backend/app/` directory went from a single empty `.gitkeep` file to a fully structured FastAPI application with **68 Python files** and **0 syntax errors**.

---

## File Tree (Complete)

```
backend/
├── requirements.txt
├── .env.example
└── app/
    ├── __init__.py
    ├── main.py                          # FastAPI factory, lifespan, CORS, rate limit
    ├── dependencies.py                  # Auth guards: get_current_user, role_required
    │
    ├── core/
    │   ├── config.py                    # pydantic-settings reads .env
    │   ├── constants.py                 # All enums: UserRole, CaseType, Province, etc.
    │   ├── security.py                  # JWT create/decode, bcrypt, AES-256 CNIC encrypt
    │   ├── exceptions.py                # AuthError, NotFoundError, PermissionError, etc.
    │   └── rate_limit.py                # slowapi Limiter singleton
    │
    ├── db/
    │   ├── mongodb.py                   # Motor AsyncIOMotorClient singleton
    │   ├── indexes.py                   # create_all_indexes() — runs at startup
    │   └── collections.py              # Typed collection accessors (get_users_col, etc.)
    │
    ├── models/                          # Internal MongoDB document shapes (Pydantic)
    │   ├── user.py
    │   ├── case.py
    │   ├── intake.py
    │   ├── document.py
    │   ├── agreement.py
    │   ├── notification.py
    │   └── chat.py
    │
    ├── schemas/                         # API request/response wire shapes (Pydantic)
    │   ├── common.py                    # PaginatedResponse[T], StatusResponse, ErrorResponse
    │   ├── auth.py
    │   ├── user.py
    │   ├── case.py
    │   ├── intake.py
    │   ├── lawyer.py
    │   ├── document.py
    │   ├── agreement.py
    │   └── admin.py
    │
    ├── repositories/                    # Only layer that touches Motor — pure DB I/O
    │   ├── base.py                      # find_one, find_many, insert, update, paginate
    │   ├── user_repo.py
    │   ├── case_repo.py
    │   ├── intake_repo.py
    │   ├── document_repo.py
    │   ├── agreement_repo.py
    │   ├── notification_repo.py
    │   └── chat_repo.py
    │
    ├── services/                        # Business logic — orchestrates repos
    │   ├── auth_service.py
    │   ├── user_service.py
    │   ├── case_service.py
    │   ├── intake_service.py
    │   ├── lawyer_service.py
    │   ├── document_service.py
    │   ├── agreement_service.py
    │   ├── notification_service.py
    │   └── admin_service.py
    │
    ├── api/v1/routes/                   # REST endpoints
    │   ├── auth.py
    │   ├── users.py
    │   ├── cases.py
    │   ├── intake.py
    │   ├── lawyers.py
    │   ├── documents.py
    │   ├── agreements.py
    │   ├── notifications.py
    │   └── admin.py
    │
    ├── websockets/
    │   ├── manager.py                   # ConnectionManager (multi-tab support)
    │   ├── notification_socket.py       # ws://host/ws/notifications/{user_id}
    │   └── chat_socket.py               # ws://host/ws/chat/{session_id} (AI stub)
    │
    └── utils/
        ├── validators.py                # CNIC (13-digit), PK phone, password strength
        ├── file_handler.py              # Upload save, extension whitelist, 10 MB cap
        └── email.py                     # aiosmtplib — password reset + KYC emails
```

---

## Layer-by-Layer Breakdown

---

### 1. Core (`app/core/`)

**`config.py`** — pydantic-settings reads all values from `.env`:
- MongoDB URL + DB name
- JWT secret, algorithm, token expiry
- AES-256 encryption key for CNIC
- LLM provider + API keys (for later)
- SMTP config for emails
- Frontend URL for CORS

**`constants.py`** — All enums used across the system:

| Enum | Values |
|---|---|
| `UserRole` | client, lawyer, admin |
| `CaseType` | civil, criminal, constitutional, family |
| `Province` | punjab, sindh, kpk, balochistan, federal |
| `CaseStatus` | draft, open, in_progress, pending_lawyer, closed, dismissed |
| `DocumentTemplate` | plaint_civil, written_statement, legal_notice, nda, rental_agreement |
| `SignatureMethod` | canvas, typed, image_upload |
| `AgreementStatus` | draft, pending, executed, cancelled |
| `NotificationType` | case_update, lawyer_assigned, hearing_scheduled, document_ready, agreement_signed, kyc_approved, kyc_rejected, review_received |

**`security.py`** — All cryptography in one place:
- `hash_password(plain)` → bcrypt cost 12
- `verify_password(plain, hashed)` → constant-time compare
- `encrypt_cnic(cnic)` / `decrypt_cnic(token)` → AES-256 Fernet
- `create_access_token(user_id, role)` → 60-min JWT
- `create_refresh_token(user_id)` → 7-day JWT
- `decode_token(token)` → returns payload dict or `{}`

**`exceptions.py`** — HTTP exception subclasses with fixed status codes:

| Exception | Status |
|---|---|
| `AuthError` | 401 |
| `PermissionError` | 403 |
| `NotFoundError` | 404 |
| `ConflictError` | 409 |
| `ValidationError` | 422 |
| `AIServiceError` | 503 |

**`rate_limit.py`** — Single slowapi `Limiter` instance imported by all routes.

---

### 2. Database Layer (`app/db/`)

**`mongodb.py`** — Motor client lifecycle:
- `connect_db()` → creates client + pings MongoDB (called at startup)
- `close_db()` → closes client (called at shutdown)
- `get_database()` → returns `AsyncIOMotorDatabase`

**`collections.py`** — Typed collection accessors:
- `get_users_col()`, `get_cases_col()`, `get_intakes_col()`, `get_documents_col()`, `get_agreements_col()`, `get_notifications_col()`, `get_chat_sessions_col()`, `get_refresh_blocklist_col()`, `get_password_reset_col()`

**`indexes.py`** — `create_all_indexes()` runs at startup:

| Collection | Indexes |
|---|---|
| `users` | email (unique), cnic_encrypted (unique sparse), role, province, kyc_verified, is_active |
| `cases` | case_number (unique), client_id, lawyer_id, status, case_type, province, created_at |
| `intakes` | session_token (unique), client_id, completed |
| `documents` | case_id, client_id, created_at |
| `agreements` | status, parties.user_id, created_at |
| `notifications` | user_id, read, created_at, **TTL 30 days** |
| `chat_sessions` | session_id (unique), client_id |
| `refresh_token_blocklist` | token (unique), **TTL 7 days** |
| `password_reset_tokens` | token (unique), email, **TTL 1 hour** |

---

### 3. Models (`app/models/`)

Internal Pydantic shapes matching MongoDB documents exactly.

**`user.py`** — `UserDocument` + `LawyerProfile` sub-document:
```
role, email, password_hash, full_name, phone, province,
cnic_encrypted, avatar_url, is_active,
lawyer_profile: { bar_number, specializations, kyc_verified,
                  rating, total_reviews, availability, bio,
                  specialization_embedding }   ← 384-dim, AI phase
```

**`case.py`** — `CaseDocument` + `Milestone` + `Hearing` sub-documents:
```
case_number, client_id, lawyer_id, intake_id, case_type, province,
status, title, description, milestones[], hearing_dates[],
case_embedding   ← 384-dim, AI phase
```

**`intake.py`** — `IntakeDocument` + `AIStructuredCase` sub-document:
```
session_token, client_id, current_step, completed,
step1..step5 (dict),
ai_structured_case: { summary, applicable_laws, recommended_actions, risk_level }
case_id   ← set after convert
```

**`document.py`** — `DocumentDocument`:
```
case_id, client_id, template_type, title, fields, file_path, status
```

**`agreement.py`** — `AgreementDocument` + `Party` + `AuditEntry` sub-documents:
```
title, body_html, eto_classification,
parties: [{ user_id, full_name, signed, signed_at, signature_method, signature_data }],
status, audit_log: [{ action, actor_id, timestamp, ip_address, note }]
```

**`notification.py`** — `NotificationDocument`:
```
user_id, type, title, body, payload, read, read_at
```

**`chat.py`** — `ChatSessionDocument` + `ChatMessage` + `Citation` sub-documents:
```
session_id, client_id, case_id, case_type, province,
messages: [{ role, content, citations, confidence }],
langgraph_checkpoint   ← AI phase
```

---

### 4. Schemas (`app/schemas/`)

API wire shapes — what the frontend sends and receives.

**`common.py`:**
- `PaginatedResponse[T]` — `{ items, total, page, page_size, pages }`
- `StatusResponse` — `{ success, message }`
- `ErrorResponse` — `{ error, status_code }`

**`auth.py`:** `RegisterRequest`, `LoginRequest`, `TokenResponse`, `RefreshResponse`, `ForgotPasswordRequest`, `ResetPasswordRequest`

**`case.py`:** `CaseCreate`, `CaseUpdate`, `MilestoneAdd`, `HearingAdd`, `CaseResponse`

**`intake.py`:** `IntakeStep1–5` (typed per step), `IntakeStepData` (generic), `IntakeStartResponse`, `IntakeResponse`

**`lawyer.py`:** `LawyerSearchParams`, `LawyerReview`, `LawyerListItem`, `MatchedLawyer`

**`agreement.py`:** `AgreementCreate`, `SignatureSubmit`, `AgreementResponse`

**`admin.py`:** `KYCAction`, `PendingKYCItem`, `AnalyticsOverview`

---

### 5. Repositories (`app/repositories/`)

Only layer that touches Motor. No business logic here.

**`base.py`** — `BaseRepository`:
- `find_one(filter)`, `find_many(filter, sort, limit, skip)`
- `insert(document)` → returns inserted `_id`
- `update_one(filter, update)` → bool
- `delete_one(filter)` → bool
- `count(filter)` → int
- `paginate(filter, page, page_size, sort)` → `PaginatedResponse`

**Per-collection repos** — domain-specific query methods:
- `user_repo` — `find_by_email`, `find_by_id`, `find_lawyers` (filter by province/case_type/rating/availability), `update_rating`
- `case_repo` — `find_by_client`, `find_by_lawyer`, `add_milestone`, `add_hearing`, `update_milestone_status`
- `intake_repo` — `find_by_token`, `update_step`, `mark_completed`
- `document_repo` — `find_by_case`, `update_file_path`, `mark_failed`
- `agreement_repo` — `find_by_party`, `append_audit_log`, `update_party_signature`, `set_status`
- `notification_repo` — `find_unread`, `find_all_for_user`, `mark_read`, `mark_all_read`
- `chat_repo` — `find_by_session`, `append_message`, `upsert_checkpoint`

---

### 6. Services (`app/services/`)

All business logic lives here — coordinates repositories, applies rules.

#### `auth_service.py`
| Function | What it does |
|---|---|
| `register(data)` | Validates password strength, checks email uniqueness, hashes password (bcrypt 12), creates user |
| `login(email, password)` | Verifies credentials, issues access + refresh token pair |
| `refresh(token)` | Validates refresh token against blocklist, returns new access token |
| `logout(token)` | Adds refresh token to MongoDB blocklist (TTL auto-cleans after 7 days) |
| `forgot_password(email)` | Generates reset token, persists to DB (TTL 1hr), sends email — silent if email not found |
| `reset_password(token, new_password)` | Validates token, updates hash, deletes reset record |

#### `user_service.py`
| Function | What it does |
|---|---|
| `get_profile(user_id)` | Returns user without `password_hash` and `cnic_encrypted` |
| `update_profile(user_id, updates)` | Partial update of top-level user fields |
| `update_lawyer_profile(user_id, updates)` | Updates `lawyer_profile.*` sub-fields, rejects if not lawyer |
| `get_lawyer_by_id(lawyer_id)` | Returns sanitized lawyer document |
| `list_lawyers(...)` | Delegates to `user_repo.find_lawyers` with pagination |

#### `case_service.py`
| Function | What it does |
|---|---|
| `create_case(client_id, data)` | Generates `ATT-YEAR-XXXX` case number, persists |
| `get_case(case_id, requester_id, role)` | Fetches + enforces owner/assigned-lawyer/admin access |
| `list_cases(user_id, role, page, page_size)` | Scopes by role: client→own, lawyer→assigned, admin→all |
| `update_case(case_id, updates, ...)` | Partial update with access check |
| `add_milestone(case_id, milestone, lawyer_id)` | Only assigned lawyer can add |
| `add_hearing(case_id, hearing, lawyer_id)` | Only assigned lawyer can schedule |

#### `intake_service.py`
| Function | What it does |
|---|---|
| `start_intake(client_id)` | Creates intake record, returns `session_token` (UUID) |
| `save_step(token, step, data, client_id)` | Validates required fields per step, persists step data |
| `convert_to_case(token, client_id)` | Asserts all 5 steps complete, creates case, marks intake done |

Step validation rules:
- Step 1: `province` required
- Step 2: `case_type`, `urgency` required
- Step 3: `incident_description` required
- Step 4: no required fields
- Step 5: `desired_outcome` required

#### `lawyer_service.py`
| Function | What it does |
|---|---|
| `search_lawyers(...)` | Filter by province, case_type, min_rating, availability with pagination |
| `match_lawyers_for_case(case_id)` | Filter by case province+type, score by rating+availability, return top 5 |
| `submit_review(lawyer_id, client_id, stars, comment)` | Recalculates rolling average rating |

#### `document_service.py`
| Function | What it does |
|---|---|
| `generate_document(case_id, client_id, template_type, fields)` | Loads `.docx` template → docxtpl fills fields → LibreOffice headless → PDF |
| `get_document(doc_id, requester_id)` | Ownership-checked fetch |

#### `agreement_service.py`
| Function | What it does |
|---|---|
| `create_agreement(title, body_html, parties, creator_id)` | Creates draft agreement with all parties |
| `get_agreement(agreement_id, requester_id)` | Party-membership access check |
| `submit_signature(agreement_id, user_id, method, data, ip)` | Records signature + ETO 2002 classification in audit log; auto-sets `executed` when all parties sign |

ETO 2002 classification applied automatically:
- Canvas → Advanced Electronic Signature (ETO 2002 S.2(d)(i))
- Typed / Image → Basic Electronic Signature (ETO 2002)

#### `notification_service.py`
| Function | What it does |
|---|---|
| `create_notification(user_id, type, title, body, payload)` | Persists + pushes to WebSocket if user is connected |
| `get_notifications(user_id)` | Last 30 notifications |
| `mark_read(notification_id, user_id)` | Single notification |
| `mark_all_read(user_id)` | Bulk update |

#### `admin_service.py`
| Function | What it does |
|---|---|
| `list_pending_kyc()` | Lawyers with bar_number set but kyc_verified = False |
| `process_kyc(lawyer_id, approved, reason)` | Flips kyc_verified, sends notification + email |
| `get_analytics()` | Counts: users by role, cases by type/status, pending KYC, agreements, documents |

---

### 7. REST API Routes (`app/api/v1/routes/`)

Base prefix: `/api/v1`

#### Auth — `/api/v1/auth`
| Method | Path | Rate Limit | Auth |
|---|---|---|---|
| POST | `/register` | 5/min | Public |
| POST | `/login` | 5/min | Public |
| POST | `/refresh` | 20/min | Refresh cookie |
| POST | `/logout` | — | Bearer |
| POST | `/forgot-password` | 3/min | Public |
| POST | `/reset-password` | 5/min | Public |

Refresh token stored as `httpOnly; Secure; SameSite=Strict` cookie. Access token returned in response body.

#### Users — `/api/v1/users`
| Method | Path | Auth |
|---|---|---|
| GET | `/me` | Any authenticated |
| PATCH | `/me` | Any authenticated |
| PATCH | `/me/lawyer-profile` | Client or Lawyer |
| GET | `/{user_id}` | Any authenticated |

#### Cases — `/api/v1/cases`
| Method | Path | Auth |
|---|---|---|
| POST | `/` | Any authenticated |
| GET | `/` | Any authenticated (scoped by role) |
| GET | `/{case_id}` | Owner / Assigned Lawyer / Admin |
| PATCH | `/{case_id}` | Owner / Assigned Lawyer / Admin |
| GET | `/{case_id}/timeline` | Owner / Assigned Lawyer / Admin |
| POST | `/{case_id}/milestones` | Lawyer only |
| POST | `/{case_id}/hearings` | Lawyer only |

#### Intake — `/api/v1/intake`
| Method | Path | Auth |
|---|---|---|
| POST | `/start` | Client only |
| PATCH | `/{token}/step/{1-5}` | Client only |
| POST | `/{token}/convert` | Client only |

#### Lawyers — `/api/v1/lawyers`
| Method | Path | Auth |
|---|---|---|
| GET | `/` | Any authenticated |
| GET | `/match/{case_id}` | Client only |
| POST | `/{lawyer_id}/review` | Client only |

#### Documents — `/api/v1/documents`
| Method | Path | Auth |
|---|---|---|
| POST | `/generate` | Any authenticated |
| GET | `/{doc_id}/download` | Owner only (FileResponse) |

#### Agreements — `/api/v1/agreements`
| Method | Path | Auth |
|---|---|---|
| POST | `/` | Any authenticated |
| GET | `/{agreement_id}` | Party members only |
| POST | `/{agreement_id}/sign` | Party members only |

#### Notifications — `/api/v1/notifications`
| Method | Path | Auth |
|---|---|---|
| GET | `/` | Any authenticated |
| PATCH | `/{notification_id}/read` | Owner only |
| POST | `/read-all` | Any authenticated |

#### Admin — `/api/v1/admin`
| Method | Path | Auth |
|---|---|---|
| GET | `/kyc/pending` | Admin only |
| PATCH | `/kyc/{lawyer_id}` | Admin only |
| GET | `/analytics/overview` | Admin only |

---

### 8. WebSockets (`app/websockets/`)

**`manager.py`** — `ConnectionManager`:
- Maintains `user_id → [WebSocket]` registry (multiple browser tabs supported)
- `connect`, `disconnect`, `send_to_user`, `broadcast`, `is_connected`
- Single `notification_manager` instance shared across app

**`notification_socket.py`** — `ws://host/ws/notifications/{user_id}?token=<jwt>`
- Authenticates via JWT query param
- On connect: sends `{ type: "unread_count", count: N }`
- Stays alive — receives push messages from `notification_service.create_notification`

**`chat_socket.py`** — `ws://host/ws/chat/{session_id}?token=<jwt>`
- Authenticates via JWT query param
- Creates `chat_sessions` record on first connect
- Persists user messages to MongoDB
- Returns stub response (AI not wired yet):
  ```json
  { "type": "final", "content": "AI legal assistant is not yet connected. Your query has been recorded.", "citations": [], "confidence": 0.0 }
  ```

---

### 9. Utilities (`app/utils/`)

**`validators.py`**
- `validate_cnic(cnic)` → 13-digit numeric, no dashes
- `validate_pk_phone(phone)` → `03XXXXXXXXX` or `+923XXXXXXXXX`
- `validate_password_strength(password)` → min 8 chars + at least 1 digit

**`file_handler.py`**
- `save_upload(file, subfolder)` → validates extension (`.pdf .jpg .jpeg .png .docx`) + 10 MB cap → saves to `uploads/{subfolder}/`
- `delete_file(path)` → safe unlink

**`email.py`** — async SMTP via `aiosmtplib`
- `send_password_reset_email(email, token)` → sends reset link
- `send_kyc_result_email(email, approved, reason)` → approved / rejected template
- Silent no-op if `SMTP_USER` not configured (safe in development)

---

## Security Implementation Summary

| Concern | Implementation |
|---|---|
| Password hashing | bcrypt, cost factor 12 |
| Access token | JWT, 60-minute expiry, `Authorization: Bearer` header |
| Refresh token | JWT, 7-day expiry, `httpOnly; Secure; SameSite=Strict` cookie |
| Refresh token revocation | MongoDB blocklist with TTL index (auto-expires in 7 days) |
| CNIC storage | AES-256 Fernet encryption at rest |
| Brute-force protection | slowapi rate limits on `/login` and `/register` (5/min) |
| File uploads | Extension whitelist, 10 MB cap |
| Password reset tokens | Stored in MongoDB with TTL index (expires in 1 hour) |

---

## AI Stub Points (3 exact hooks for later)

| File | Line context | What plugs in |
|---|---|---|
| `services/intake_service.py` | `convert_to_case()` → `# TODO: AI` | LangGraph intake_node to fill `ai_structured_case` |
| `websockets/chat_socket.py` | stub response block → `# TODO: AI` | LangGraph supervisor invocation + token streaming |
| `services/lawyer_service.py` | `match_lawyers_for_case()` → `# TODO: AI` | `cosine_similarity(case_embedding, lawyer_embedding) * 0.5` |

---

## How to Run

```bash
# 1. Copy and fill environment file
cp backend/.env.example backend/.env
# Edit SECRET_KEY, ENCRYPTION_KEY, MONGODB_URL

# 2. Install dependencies
cd backend
pip install -r requirements.txt

# 3. Start MongoDB (local)
mongod --dbpath ./data/db

# 4. Run the API
uvicorn app.main:app --reload --port 8000

# 5. Open interactive docs
# http://localhost:8000/docs
```

Generate the Fernet encryption key for CNIC:
```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

---

## What Is NOT Done Yet

| Feature | Reason deferred |
|---|---|
| Docker / docker-compose | Skipped by user request |
| AI chatbot (LangGraph) | AI phase — separate milestone |
| Embedding-based lawyer matching | Needs sentence-transformers + Chroma |
| AI case structuring (intake) | Needs LLM integration |
| ChromaDB connection | AI phase |
| Knowledge base ingestion pipeline | Separate milestone |
| Frontend API integration | Frontend work |
| Unit / integration tests | Next backend milestone |

---

*Attorney.AI | SP23-BCS-069 | Muhammad Usama | April 2026*
