# Backend Audit Findings

Date: 2026-07-07

Scope: Updated review of `backend/`, including FastAPI routes, services, repositories, schemas, DB indexes, config, startup, auth, payments, AI routes, WhatsApp, cause-list, overseas POA, bail checker, calculators, and backend tests.

## Summary

- Parsed 175 backend Python files.
- Found 0 Python syntax errors.
- Backend grew since the previous audit with new `bail`, `calculators`, `overseas`, POA, labour demand, and related tests.
- The previous visible MongoDB URI in `backend/.env.example` is no longer present. The file is currently empty.
- Direct backend test scripts run:
  - `backend/tests/test_bail.py`: 21 passed, 0 failed.
  - `backend/tests/test_calculators.py`: 15 passed, 0 failed.
  - `backend/tests/test_inheritance.py`: passed.
  - `backend/tests/test_wasiyyat.py`: 13 passed, 0 failed.
  - `backend/tests/test_causelist_parser.py`: passed only when `PYTHONPATH` was set manually.
- `pytest` is still not installed in either checked virtualenv, so `python -m pytest backend/tests` is not currently available.

## Fixed Or Improved Since Last Audit

### 1. Visible Env Credential Removed

File: `backend/.env.example`

Previous issue:
- The file contained what looked like a real MongoDB Atlas URI with credentials.

Current state:
- The file no longer shows that credential.
- It is now empty.

Remaining recommendation:
- Keep the credential rotated if it was ever live.
- Add a safe placeholder `.env.example` so onboarding is still possible without leaking secrets.

### 2. New Deterministic Legal Tools Added

Files:
- `backend/app/api/v1/routes/bail.py`
- `backend/app/services/bail_checker.py`
- `backend/app/api/v1/routes/calculators.py`
- `backend/app/services/court_fee.py`
- `backend/app/services/labour_dues.py`

Good:
- Bail, court-fee, and labour-dues logic is deterministic rather than LLM-generated.
- Outputs carry disclaimers, assumptions, confidence/source notes, and legal-basis text.
- New direct tests pass.

Remaining recommendation:
- Add dates/source versions to each law table more explicitly.
- Treat these as estimators/reference tools, not authoritative legal conclusions.

### 3. POA Feature Adds Useful Safety Controls

Files:
- `backend/app/api/v1/routes/overseas.py`
- `backend/app/services/overseas_service.py`
- `backend/app/db/indexes.py`
- `backend/app/core/constants.py`

Good:
- POA ownership checks exist.
- Expiry tracking and scheduled checks exist.
- General POA blocks property-disposition powers.
- PDF SHA256 is stored for tamper evidence.
- POA collection indexes were added.

Remaining issue:
- CNIC fields are stored in plaintext in POA records and document fields. See Critical Finding 2.

### 4. More Structured Logging In Newer Paths

Improved examples:
- `backend/app/services/causelist_service.py`
- `backend/app/services/whatsapp_service.py`
- `backend/app/services/payment_service.py`
- `backend/app/services/overseas_service.py`

Good:
- Several newer failure paths now use `logger.exception`.

Remaining issue:
- Some old paths still silently pass or print tracebacks. See High Priority Finding 8.

## Critical Findings

### 1. Any Authenticated User Can Fetch Any User Profile

File: `backend/app/api/v1/routes/users.py`

`GET /users/{user_id}` still returns `user_service.get_profile(user_id)` for any authenticated user.

Risk:
- Password hash and CNIC are stripped, but email, phone, province, and profile metadata can still leak.

Fix:
- Restrict this route to admins, or
- Return a dedicated public profile DTO, or
- Allow access only when the requester has a real relationship with the target user.

### 2. Overseas POA Stores CNIC Data In Plaintext

Files:
- `backend/app/api/v1/routes/overseas.py`
- `backend/app/services/overseas_service.py`

The POA flow accepts and stores fields such as `principal_cnic` and `attorney_cnic` in normal document fields/records.

Risk:
- CNIC is sensitive identity data.
- The app already has CNIC encryption helpers, so plaintext storage creates inconsistent privacy posture.

Fix:
- Encrypt CNIC fields before storing them.
- Consider storing only masked CNIC for display.
- Keep full CNIC only in generated PDFs if legally required, and control access/downloads strictly.

### 3. Appointment Double-Booking Race Still Exists

Files:
- `backend/app/services/appointment_service.py`
- `backend/app/repositories/appointment_repo.py`
- `backend/app/db/indexes.py`

The booking flow still checks conflict first, then inserts the appointment separately.

Risk:
- Two concurrent requests can both pass `has_conflict()` and create overlapping bookings.

Fix:
- Use an atomic reservation strategy.
- Add a lock/reservation collection keyed by lawyer and normalized time slot.
- Or use MongoDB transactions with conditional writes.

### 4. Duplicate Pending Engagement Race Still Exists

Files:
- `backend/app/services/engagement_service.py`
- `backend/app/repositories/engagement_repo.py`
- `backend/app/db/indexes.py`

The flow still checks `find_pending_for_case()`, then inserts separately.

Risk:
- Concurrent requests can create multiple pending requests for the same case.

Fix:
- Add a partial unique index on pending engagements per case.
- Or atomically claim/update case engagement state before inserting.

## High Priority Findings

### 5. Password Policy Error Message Bug Still Exists

File: `backend/app/services/auth_service.py`

The service still raises the literal string `"{PASSWORD_POLICY}"`.

Fix:
- Replace `"{PASSWORD_POLICY}"` with `PASSWORD_POLICY`.

### 6. Long Passwords Can Still Break Bcrypt

Files:
- `backend/app/core/security.py`
- `backend/app/utils/validators.py`
- `backend/requirements.txt`

`bcrypt==5.0.0` raises on passwords over 72 bytes. Current password validation still has no max length.

Fix:
- Add max password length validation.
- Use Pydantic password fields with `min_length=8` and `max_length=72`.
- Keep error messaging consistent across register, reset, admin reset, and change-password flows.

### 7. Secure Refresh Cookie Still Breaks Local HTTP Development

File: `backend/app/api/v1/routes/auth.py`

Refresh cookies are still set with `secure=True` unconditionally.

Risk:
- On `http://localhost`, browsers will not store/send the refresh cookie.
- Token refresh can appear broken in local development.

Fix:
- Use `secure=settings.app_env != "development"` for local development.
- Consider centralizing cookie options in one helper.

### 8. Traceback Printing And Silent Passes Remain

Files:
- `backend/app/core/exceptions.py`
- `backend/app/websockets/chat_socket.py`
- several service notification/background paths

Examples:
- `traceback.print_exc()` remains in the generic exception handler.
- Some older paths still use `except Exception: pass`.

Risk:
- Production logs can leak noisy stack traces.
- Silent failures hide operational issues.

Fix:
- Replace traceback printing with structured logging.
- Use `logger.exception` for unexpected server failures.
- Only suppress expected non-critical failures with a clear log.

### 9. Admin API Can Still Write Invalid Roles Or Statuses

File: `backend/app/schemas/admin.py`

Admin schemas still use plain strings:
- `AdminUserCreate.role`
- `AdminUserUpdate.role`
- `CaseStatusUpdate.status`

Risk:
- Invalid roles/statuses can be persisted into MongoDB.

Fix:
- Use `UserRole` for role fields.
- Use `CaseStatus` for case status updates.

### 10. KYC Rejection Still Does Not Force `kyc_verified=False`

File: `backend/app/services/admin_service.py`

The rejection branch sets a rejection reason but does not explicitly set `lawyer_profile.kyc_verified` to `False`.

Risk:
- Rejecting a previously approved lawyer could leave them verified.

Fix:

```python
"lawyer_profile.kyc_verified": False
```

### 11. Payment Webhook Still Swallows Exceptions At Route Boundary

File: `backend/app/api/v1/routes/payments.py`

The Safepay webhook still catches `Exception` and returns `200` without route-level logging.

Good:
- Lower-level payment service logs some failures.

Risk:
- Route-level parsing/signature/settlement failures can disappear.

Fix:
- Keep fast-200 behavior if the gateway requires it.
- Add `logger.exception("Safepay webhook failed")` in the route-level catch.

## Medium Priority Findings

### 12. Startup Still Blocks On Heavy AI Warmups

File: `backend/app/main.py`

Startup still awaits:
- `whisper_service.warmup()`
- intent warmup

Risk:
- Slow API boot.
- Health checks can fail while models warm.
- Model failure can block the whole API.

Fix:
- Move heavy warmups to background readiness tasks.
- Or lazy-load on first request.

### 13. More Scheduler Work Added In-Process

File: `backend/app/main.py`

The app now starts:
- cause-list scheduler
- POA expiry scheduler

Risk:
- In multi-worker deployments, every worker may run the same scheduler.
- In-process jobs are lost on restart.

Fix:
- Move scheduled jobs to a single worker/queue/cron process.
- Or add distributed locking.

### 14. Missing Optional AI Dependencies Remain

Files:
- `backend/app/ai/llm.py`
- `backend/requirements.txt`

`llm.py` supports Gemini and Ollama imports, but the matching packages are still not declared in `requirements.txt`.

Fix:
- Add optional extras, or remove unsupported provider branches.
- Pin LangChain packages to known-good versions.

### 15. Tests Exist But Test Tooling Is Still Incomplete

Files:
- `backend/tests/*`
- `backend/requirements.txt`

Good:
- More self-contained tests were added and passed when run directly.

Issues:
- `pytest` is still missing from the checked virtualenvs.
- `test_causelist_parser.py` requires manual `PYTHONPATH` setup when run directly.

Fix:
- Add a dev requirements file with `pytest` and `pytest-asyncio`.
- Add a one-command test runner.
- Ensure tests set up import paths consistently.

### 16. Too Many Untyped API Responses Remain

Examples:
- `response_model=dict`
- `response_model=list`

Risk:
- Weak OpenAPI contract.
- Frontend/backend drift is easier.

Fix:
- Add typed response models for high-traffic endpoints first:
  - auth
  - users
  - cases
  - appointments
  - documents
  - payments
  - engagements
  - overseas POA

### 17. Mutable Defaults Still Exist In Some Schemas

Files:
- `backend/app/schemas/document.py`
- `backend/app/models/user.py`
- `backend/app/api/v1/routes/ai.py`
- `backend/app/api/v1/routes/overseas.py`

Examples:
- `fields: dict[str, Any] = {}`
- `specializations: list[CaseType] = []`
- `history: list[dict] = []`
- `powers: list[str] = []`

Fix:
- Use `Field(default_factory=dict)` and `Field(default_factory=list)`.

### 18. Upload And Generated File Handling Still Needs Hardening

Files:
- `backend/app/services/intake_service.py`
- `backend/app/utils/file_handler.py`
- `backend/app/services/pdf_generator.py`

Good:
- Intake evidence upload checks magic bytes.

Issues:
- Generic upload helper still trusts extension only.
- Original filenames are stored/returned.
- Upload roots are split across helpers/services.

Fix:
- Normalize extension from detected MIME.
- Treat original filenames as display-only.
- Use one absolute upload root from settings.
- Consider malware scanning before evidence/document ingestion.

## New Feature Notes

### Bail Checker

Status:
- Tests pass.
- Deterministic lookup is safer than AI guessing.

Recommendation:
- Add a clear `effective_as_of` date to the offence table.
- Add source references per special-law entry where possible.

### Court Fee Calculator

Status:
- Tests pass.
- Includes assumptions, source text, and verification warning.

Recommendation:
- Avoid returning unknown province as if it were accepted. Current fallback keeps `province` as the unknown input while using Islamabad/default schedule. Add `schedule_used`.

### Labour Dues Calculator

Status:
- Tests pass.
- Labour demand PDF renders.

Recommendation:
- Add province/establishment caveats to inputs if this becomes more than an estimate.

### Overseas POA

Status:
- Good ownership checks and lifecycle structure.

Recommendations:
- Encrypt CNIC fields.
- Validate dates as date/datetime fields rather than raw strings.
- Replace mutable `powers=[]` default with `Field(default_factory=list)`.
- Consider attorney-side acknowledgement auth/linking rather than principal-only acknowledgement.

## Recommended Fix Order

1. Fix public user profile access.
2. Encrypt or avoid storing POA CNIC fields.
3. Fix password policy string and password max length.
4. Fix local dev refresh cookie behavior.
5. Add appointment booking atomicity.
6. Add pending engagement uniqueness.
7. Add admin enum validation and KYC rejection correction.
8. Add route-level payment webhook logging.
9. Add dev test dependencies and a single test command.
10. Move in-process schedulers/heavy warmups to durable background infrastructure.
11. Replace mutable defaults and add typed response models.
12. Harden generic upload/file storage.

