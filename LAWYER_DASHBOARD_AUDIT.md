# Lawyer Dashboard Audit — Initial Findings

**Date:** 2026-10-05
**Baseline:** branch `feat/doc-analyzer-p3`, HEAD `a62656b` (plus uncommitted analyzer-demo work)
**Scope:** every page under `/lawyer/*` — frontend → `lib/api.js` → FastAPI route → service/DB. **Payments excluded.**
**Method:** read-only static trace (5 parallel audits), independently cross-checked by a second review (Codex). No source files were changed.

This file records what was found **before** any fixes, so later work can be checked against it. When an issue is fixed, mark it in the Status column with the commit hash — do not delete rows.

---

## 1. Summary

- **The backend is real everywhere.** Every lawyer page calls registered `/api/v1` routes that read/write MongoDB. No route is missing, and no role guard blocks lawyers.
- **The defects are in the frontend:** 6 bugs that crash or fail a demo path, several features that only exist in browser state, and a number of dead controls.
- **Why tests did not catch them:** frontend tests (1,284 passing) and the production build pass, but no test renders or calls any of the 6 broken paths — e.g. the Documents tests read the source as text and never mount it.

---

## 2. Must-fix (demo-breaking)

All six were verified by hand against the code, not only by the automated audits.

| ID | Status | Issue | Location | Effect |
|---|---|---|---|---|
| **LD-01** | Fixed `216c12d` | Documents inbox reads `counts["Pending Review"]` while `counts` is still `null`; the keys are also display labels, but the server returns `submitted` / `approved` / `returned` / `rejected` | [DocumentsPage.jsx:339-357](frontend/src/components/lawyer/DocumentsPage.jsx#L339), state at [:1462](frontend/src/components/lawyer/DocumentsPage.jsx#L1462); server keys in `backend/app/services/document_transitions.py` (`queue_counts`) | Sidebar **Documents** page throws on first render. Even when loaded, the four stat cards would be blank |
| **LD-02** | Fixed `d5af894` | Case workspace forms use the shared `Input` as value-based, but it passes the raw DOM **event** to `onChange` and has no `label` prop | [CasesPage.jsx:917-922, 952-953, 1082, 1229](frontend/src/components/lawyer/CasesPage.jsx#L917); `Input` at [components.jsx:59](frontend/src/components/lawyer/components.jsx#L59) | Schedule hearing throws (`new Date(event)`), so nothing is saved. Record outcome with a next date throws and sticks on "Saving…". Document save throws on `form.title.trim`. Timeline date becomes an event object. Labels never render |
| **LD-03** | Fixed `b98f8a2` | `DELETE /agreements/drafts/{id}` returns `{"status": "deleted"}` but declares `response_model=StatusResponse` (`success`, `message`) | [agreements.py:338-345](backend/app/api/v1/routes/agreements.py#L338); model at [common.py:16](backend/app/schemas/common.py#L16) | Draft **is deleted**, then response validation fails → 500 → lawyer sees "Could not delete the draft." |
| **LD-04** | Fixed `792ef5d` | Onboarding renders `err.detail` directly; on a 422 that is an array of objects. Step 1 also has no required-field check | [OnboardingPage.jsx:1110](frontend/src/components/lawyer/OnboardingPage.jsx#L1110), rendered at [:963](frontend/src/components/lawyer/OnboardingPage.jsx#L963); no check at [:498](frontend/src/components/lawyer/OnboardingPage.jsx#L498) | React crash on a validation error. Other errors show a misleading "check your connection". A blank submit can loop the lawyer back into onboarding |
| **LD-05** | Fixed `7a16f52` | Clients maps `caseId: c.id`, but `CaseOut` serialises the id as `_id` | [ClientsPage.jsx:28](frontend/src/components/lawyer/ClientsPage.jsx#L28); alias at [case.py:93](backend/app/schemas/case.py#L93) | **Message** button never opens the client's case |
| **LD-06** | Fixed `9c4043b` | AI Assistant opens an unbound (no-case) conversation on mount; the case-change effect skips its first render and runs before the case list loads; `send()` then posts a `case_id` into that unbound conversation | [AILegalPage.jsx:385-390](frontend/src/components/lawyer/AILegalPage.jsx#L385), mount at [:631-642](frontend/src/components/lawyer/AILegalPage.jsx#L631), send at [:768](frontend/src/components/lawyer/AILegalPage.jsx#L768); guard at [conversation_service.py:1116-1123](backend/app/services/conversation_service.py#L1116) | Arriving with a case already selected → first question gets **409** → shown as "AI service unavailable" |

---

## 3. Page-by-page connectivity

| Page | Status | Notes |
|---|---|---|
| Dashboard | Partial | Recent cases + appointment count are real. "Pending Docs" tile hardcoded `—`, progress bars fake, hearing-date column always empty, "Good morning" fixed. "Active cases" excludes `in_progress`. |
| Cases — list + engagement inbox | Connected | Send terms, decline, complete, end engagement all real. |
| Cases — workspace | Mixed | Messages, tasks, record hearing outcome: connected. **Documents tab, Timeline tab, hearing edit/delete: browser state only, lost on reload.** Scheduling broken (LD-02). AI tab (`WorkspaceAI`) is dead code. No Hearings tab button. |
| Cause List | Connected | Live scrape of the LHC cause-list endpoint, paste matcher, 6-hourly background sweep. |
| Clients | Partial | Derived from the case list (no clients endpoint). "Add Client" and "Schedule" only push fake local notifications. Message broken (LD-05). |
| Documents (review inbox) | **Crashes** | LD-01. Backend (queue, approve/return/reject, preview, revisions) is connected. |
| Draft Generator | Connected | AI drafting (`/ai/draft/stream`), save drafts, Urdu translation, Save-to-Documents PDF. Templates are frontend-defined; Export Word is client-side. |
| Agreements (+ DraftComposer) | Connected | List, sign, decline, PDF, create/save/sign-and-send drafts. Delete draft broken (LD-03). |
| Appointments | Connected | Accept, reject, done, no-show, working hours, meeting link, outcome queue, server pagination. Video = pasted https link, not an integrated call. Reminders built but off. |
| AI Assistant | Connected | Real research with history, stop, citations, provenance. LD-06. |
| Case Law | Connected | Semantic search over the Chroma judgments index + "cited by". |
| Document Analyzer | Flag-gated | With `DOC_ANALYZER` off (real `.env`), shows a **labelled fictional demo**. Live only with the demo overlay. |
| Review Queue | Flag-gated | Needs `DOCUMENTS_V2` **and** `DOCUMENT_REVIEW_REQUESTS`; the latter is off, so the item is hidden. |
| Profile | Partial | Name/phone/province and lawyer profile save are real. Email edits discarded; "Verified" badge hardcoded; camera button dead; errors show "[object Object]". |
| Settings | Partial | Password, sessions, logout real. Notification toggles store nothing; Delete Account unwired (backend `/users/me/close` and `closeAccount()` exist). |
| Onboarding | Partial | Final submit real. Council, photo, credentials, working days, office hours, max fee never sent. Fee note saved as `bio`; city defaults to "Lahore" and is persisted. |
| Overseas Disputes | Hidden | Out of scope since 2026-09-23; still routable at `/lawyer/disputes`, read-only, connected. |

---

## 4. Secondary issues

### Data and correctness
- **50-item caps:** Cases list, Clients, Dashboard, AI Assistant case picker, DraftComposer case picker, Draft Generator case picker stop at the first 50 cases (backend max page size).
- **Case status mapping** (`CasesPage.jsx:1719`) maps `open/active`; backend uses `in_progress` / `pending_lawyer`. "Under Hearing" and "Adjourned" never appear.
- **Dashboard "Today's Schedule"** reads the first 50 appointments, sorted ascending — busy lawyers see the oldest, not today's.
- **Hearings** opened from Dashboard/banner skip seeding → 0 hearings shown. New hearings are added locally without the server `_id`, so "Add Outcome" is refused until reload.
- **Final document screen** shows the logged-in lawyer as approver, not the stored reviewer.
- **Profile save** with a cleared field sends `null`, which `exclude_none` drops — old value kept, success toast shown.
- **Agreements** stats counted from loaded rows only.

### Error handling
- AI Assistant collapses every error (403/409/413/422) to "AI service unavailable".
- Rename/archive/delete conversation ignore errors; ratings show "recorded" before the request succeeds.
- Document downloads (review page, Draft Generator, Disputes) ignore returned errors.
- `ProfilePage.jsx:61` and `OnboardingPage.jsx:1110` read `.detail` instead of `.message`.

### Shell / notifications
- Notification websocket never reconnects after closing.
- Notification icon keys (`hearing`, `message`, …) never match real types (`case_message`, `hearing_scheduled`, …).
- Unread-messages badge filters a type the server never sends.
- Review Queue nav is hidden on **any** probe error, not only `feature_disabled`.

### Dead controls (no handler)
Documents: Upload Document, AI Generate, row checkbox, "Request changes" toggle, Lawyer Notes · Appointments: View Details, calendar events, stat cards · AI Assistant: Search globe, clock, mic · Draft Generator: Insert Link · Clients: "more" menu · Dashboard: row "more" · Profile: camera · Settings: Delete Account, notification toggles · Onboarding: Take Photo, credential uploads, Admin Support.

### Backend / config
- `.env.example` lists `ANALYZER_ENGINE_HYPOTHESES` twice and never defines `DOCUMENTS_V2`.
- `causelist_service.check_lawyer_watches` only catches `ServiceUnavailableError`; a parse error fails the whole Check Now.
- `citator_service.search` runs blocking embedding/Chroma calls inside `async` (performance only).

---

## 5. Demo environment

| Flag | Real `.env` | Needed for demo |
|---|---|---|
| `DOCUMENTS_V2` | `true` | `true` |
| `DOCUMENT_REVIEW_REQUESTS` | absent (false) | `true` for Review Queue |
| `DOC_ANALYZER` (+ analyzer overlay) | absent (false) | on via `backend/.env.analyzer-demo.example` |

---

## 6. Not verified

- Live reachability of the LHC cause-list endpoint.
- How many judgments/statutes are actually indexed in Chroma.
- Runtime confirmation of LD-03 and LD-06 (inferred from code; LD-03's payload was separately validated against the Pydantic model by the Codex review).
- Payments module (out of scope).

---

## 7. Fix log (branch `fix/lawyer-dashboard`, not pushed)

Every commit has a regression test that fails without the fix and passes with it; the full frontend suite was green after each commit and the production build passed at each phase boundary. The original findings above are left unchanged.

| Item | Commit | What changed |
|---|---|---|
| LD-01 | `216c12d` | Documents inbox no longer crashes; stat cards use server counts (V2) or loaded rows (legacy) |
| LD-02 | `d5af894` | Hearing forms store typed values (value-based `FieldInput`) |
| LD-03 | `b98f8a2` | Delete-draft returns its declared `StatusResponse` (HTTP-level test) |
| LD-04 | `792ef5d` | Onboarding Step 1 validation; 422 shown as text |
| LD-05 | `7a16f52` | Clients → Message opens the case by `case_number \|\| _id` |
| LD-06 | `9c4043b` | AI Assistant sends case questions into a thread bound to that case |
| LD-06 follow-up | `ef3a414` | No stray empty thread while cases load; opening a thread from another case adopts its case, or shows a notice |
| 2.1 | `31d594b` | Case status labels cover every backend status, shared by Cases and Dashboard |
| 2.2 | `8ec1a4f` | Dashboard: active cases include `in_progress`; pending docs from the review queue; real zeros; "N+" when only part of the list loaded; fake progress bars removed |
| 2.4 | `0947a5f` | Hearings seed however a case is opened; scheduled and auto-scheduled hearings take server ids |
| 2.6a | `8bc4376` | AI Assistant names 403/409/413/422 failures; ratings and thread actions report errors |
| 2.6b | `83bf105` | Failed PDF downloads show their reason (Documents, My Documents, Draft Generator) |
| 2.6c | `9f10780` | Profile and hearing-outcome errors show the server's message |
| 3.1 | `992a336` | Settings → Delete Account wired to `closeAccount` behind a password |
| 3.2 | `8bc749e` | Settings notification toggles removed (no store) |
| 3.3 | `8336e4a` | Documents: AI Generate → Draft Generator; Upload, Request-changes toggle, notes box, checkbox removed |
| 3.4 | `60a9abe` | Appointments: View Details removed; false click affordances dropped |
| 3.5 | `21b87c4` | AI Assistant: clock opens history; globe, mic, Pro badge, Upgrade Plan removed |
| 3.6 | `187f8b1` | Draft Generator: no-op Insert Link removed |
| 3.7 | `89be26e` | Clients/Dashboard: fake Add Client, fake notifications, inert overflow buttons removed |
| 3.8a | `9fa98a1` | Profile: inert camera button removed |
| 3.8b | `e46d996` | Onboarding: never-sent fields (council, max fee, fee tier, phone type, schedule) and dead support link removed |
| 3.9 | `7978b08` | Case workspace: browser-only Documents/Timeline tabs and hearing edit/delete hidden |
| 3.10 | `1ba40e7` | Never-rendered components deleted (WorkspaceAI, Documents/Timeline tabs, EditMenu, StatusBadge, DocTopbar, Topbar, LoginPage stub) |

### Follow-ups (approved after Phase 3)

| Item | Commit | What changed |
|---|---|---|
| Client close-account | `5203b7f` | `ConfirmDialog` renders its children, so the password field appears; the refusal reason is read from `.message` (client module, own commit) |
| Case-status filter | `c7e332e` | `GET /cases?status=` — optional, validated against `CaseStatus` (422 otherwise), applied inside the caller's scope; dashboard Active = server `open` + `in_progress` totals |
| KYC uploads — backend | `56601fd` | `POST/GET /users/me/kyc/documents` (lawyer only, 5 MB, type from bytes, replace per kind), `GET /admin/kyc/{id}/documents/{kind}` (admin only, inline, no-store), new optional `lawyer_profile.kyc_documents`; files + record removed on account close |
| KYC uploads — onboarding | `7f6bed5` | Step 2 uploads for real, shows what the server holds or why it refused; real initials; camera capture input; honest banner |
| KYC uploads — admin | `c4f6804` | Admin KYC review lists each lawyer's real uploads and opens them (was hardcoded "Bar License, ID Proof") |
| Smoke finding 1 | `0e1f4a7` | Saving a hearing kept the server's bare case, blanking the client name in the workspace header (and duplicating a React key) |
| Smoke finding 2 | `c6a837a` | The AI history list's search debounce used a mount-time closure and reloaded unfiltered last, listing general threads under a selected case |

---

## 8. Demo smoke test (release gate) — 2026-10-06

**Environment:** local only. Backend on `127.0.0.1:8000` via `serve.py start --env-overlay .env.analyzer-demo.local` (`doc_analyzer_ready ai=simulated`), Mongo replica set `127.0.0.1:27018` / `attorney_ai_local`, no Redis, blank SMTP, frontend dev server on `3001`. `.env` unchanged. No hosted provider was called: no AI question, AI drafting, translation, cause-list "Check Now" or payment was exercised, and onboarding was submitted with an empty address (no geocoding). Fictional `@example.com` accounts; synthetic upload files. The stack was stopped afterwards (ports 8000 / 3001 / 27018 free).

| Path | Result |
|---|---|
| Dashboard numbers (2.1, 2.2, status filter) | ✅ Active 2 (open + in_progress, server totals), Pending Docs 0, Clients 1, real status labels |
| Documents inbox (LD-01, 3.3) | ✅ Renders, cards 0/0/0/0, no Upload, AI Generate present |
| Case status filter options (2.1) | ✅ Open / In Progress / Awaiting Lawyer / Closed / Dismissed |
| Schedule hearing (LD-02) | ✅ Labels render; POST 200; hearing listed. **Found:** client name blanked after save → fixed `0e1f4a7` |
| Record outcome with next date (2.4) | ✅ Add Outcome works on the just-scheduled hearing; auto-scheduled hearing appears with its own Add Outcome; no stuck "Saving…" |
| Hearing edit/delete, Documents/Timeline tabs (3.9) | ✅ Not offered; Overview / Messages / Tasks only |
| Clients → Message (LD-05, 3.7) | ✅ Opens the case workspace; hearings seeded when opened from outside the list (2.4); no Add Client |
| Agreement draft → delete (LD-03) | ✅ Unverified lawyer correctly refused (403, message shown); after KYC approval: create 201, delete 200, no false error |
| Onboarding Step 1 validation (LD-04) | ✅ Empty Continue blocked with reason; no Bar Council field |
| Onboarding Step 2 uploads (KYC) | ✅ PDF uploaded and listed; text-as-PDF refused with the server's reason (422); photo uploaded with preview; real initials; files on local disk |
| Onboarding Step 3/4 (3.8b) | ✅ No never-sent fields; submitted; no Admin Support link; returning lawyer lands on the dashboard |
| Admin KYC review | ✅ Real uploads listed ("Bar Council Certificate ↗", "Photo ↗"; "No documents uploaded" for the other); file opened (200); approval works |
| AI Assistant binding (LD-06 + follow-up) | ✅ One conversation created, bound to the selected case; no stray thread; clock reopens history; inert controls gone. **Found:** history list ended unfiltered → fixed `c6a837a` |
| Appointments (3.4) | ✅ Loads; no View Details |
| Settings (3.1, 3.2) | ✅ No notification toggles; Delete Account closed the account behind the password; user anonymised; KYC files and record removed |
| Client close-account dialog (`5203b7f`) | ✅ Password field shown; request reaches the server (403 on a wrong password). ⚠️ The refusal toast is not visible — see below |

**Not exercised (by design):** Review Queue (flag off), Document Analyzer, Cause List "Check Now" (fetches the LHC site), AI answers / Draft Generator AI / translation (hosted LLM), payments, the Documents review screen with a real submission (none in the local DB).

**Open findings from the smoke test**

- **Client app shows no toasts at all (pre-existing, client module).** `ClientApp` mounts no `ToastContainer`, so `useToast()` falls back to a no-op on every client screen. The close-account fix is correct but its message is invisible until a provider is mounted. Not fixed — outside this plan.
- Console noise only: Next dev HMR websocket (dev server), the Review Queue probe's expected 404 (`feature_disabled`), and a pre-existing React style warning (a card mixing `border` and `borderLeft`).
- Hearing form pre-fills Court with the province and Judge with "—" (D6, deferred).

**Still open:** the client toast provider (above); the deferred Phase 2 items (2.3, 2.5, 2.7–2.10) and Phase 4; pre-existing backend failures in `test_v2_migration_matrix.py`, `test_engagement_two_step.py`, `test_analyzer_lawyer_only.py` (44 tests, identical with and without these changes).
