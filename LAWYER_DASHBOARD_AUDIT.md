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
| **LD-01** | Open | Documents inbox reads `counts["Pending Review"]` while `counts` is still `null`; the keys are also display labels, but the server returns `submitted` / `approved` / `returned` / `rejected` | [DocumentsPage.jsx:339-357](frontend/src/components/lawyer/DocumentsPage.jsx#L339), state at [:1462](frontend/src/components/lawyer/DocumentsPage.jsx#L1462); server keys in `backend/app/services/document_transitions.py` (`queue_counts`) | Sidebar **Documents** page throws on first render. Even when loaded, the four stat cards would be blank |
| **LD-02** | Open | Case workspace forms use the shared `Input` as value-based, but it passes the raw DOM **event** to `onChange` and has no `label` prop | [CasesPage.jsx:917-922, 952-953, 1082, 1229](frontend/src/components/lawyer/CasesPage.jsx#L917); `Input` at [components.jsx:59](frontend/src/components/lawyer/components.jsx#L59) | Schedule hearing throws (`new Date(event)`), so nothing is saved. Record outcome with a next date throws and sticks on "Saving…". Document save throws on `form.title.trim`. Timeline date becomes an event object. Labels never render |
| **LD-03** | Open | `DELETE /agreements/drafts/{id}` returns `{"status": "deleted"}` but declares `response_model=StatusResponse` (`success`, `message`) | [agreements.py:338-345](backend/app/api/v1/routes/agreements.py#L338); model at [common.py:16](backend/app/schemas/common.py#L16) | Draft **is deleted**, then response validation fails → 500 → lawyer sees "Could not delete the draft." |
| **LD-04** | Open | Onboarding renders `err.detail` directly; on a 422 that is an array of objects. Step 1 also has no required-field check | [OnboardingPage.jsx:1110](frontend/src/components/lawyer/OnboardingPage.jsx#L1110), rendered at [:963](frontend/src/components/lawyer/OnboardingPage.jsx#L963); no check at [:498](frontend/src/components/lawyer/OnboardingPage.jsx#L498) | React crash on a validation error. Other errors show a misleading "check your connection". A blank submit can loop the lawyer back into onboarding |
| **LD-05** | Open | Clients maps `caseId: c.id`, but `CaseOut` serialises the id as `_id` | [ClientsPage.jsx:28](frontend/src/components/lawyer/ClientsPage.jsx#L28); alias at [case.py:93](backend/app/schemas/case.py#L93) | **Message** button never opens the client's case |
| **LD-06** | Open | AI Assistant opens an unbound (no-case) conversation on mount; the case-change effect skips its first render and runs before the case list loads; `send()` then posts a `case_id` into that unbound conversation | [AILegalPage.jsx:385-390](frontend/src/components/lawyer/AILegalPage.jsx#L385), mount at [:631-642](frontend/src/components/lawyer/AILegalPage.jsx#L631), send at [:768](frontend/src/components/lawyer/AILegalPage.jsx#L768); guard at [conversation_service.py:1116-1123](backend/app/services/conversation_service.py#L1116) | Arriving with a case already selected → first question gets **409** → shown as "AI service unavailable" |

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
