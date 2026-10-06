# Lawyer Dashboard — Fix Plan (v2, decisions applied)

**Date:** 2026-10-05
**Source of issues:** [LAWYER_DASHBOARD_AUDIT.md](LAWYER_DASHBOARD_AUDIT.md) (IDs `LD-01`…`LD-06`, plus the secondary list)
**Goal:** a lawyer dashboard that does not crash, does not show false data, and has no dead controls — ready for the FYP live demo. Payments stay out of scope.

**Order:** Step 0 checkpoint → Phase 1 → Phase 2 (2.1, 2.2, 2.4, 2.6 only) → Phase 3 → demo smoke test. Phase 4 is skipped.

---

## Ground rules

1. **One issue per commit**, each with a test that exercises the broken path and fails before the fix.
2. **Tests render or call the real thing:**
   - Frontend: mount the component in JSDOM against `tests/support/api-stub` (pattern: `tests/analyzer_live_dom.test.mjs`).
   - Backend: hit the HTTP route, not only the service.
3. **Gate after every phase:** `npm test`, `npm run build`, and the touched backend test files. Backend checks never run against the real `.env` (hosted Atlas/Upstash).
4. **No commit or push without explicit approval.** As each item lands, record its commit hash in the Status column of `LAWYER_DASHBOARD_AUDIT.md`.
5. **Smallest correct change.** No redesign inside a fix; UI improvements come after this plan.

---

## Step 0 — Checkpoint the analyzer work (decision: A)

1. Review the uncommitted analyzer-demo work on `feat/doc-analyzer-p3`: the diff, a secrets scan, and the analyzer test files.
2. Commit it as **its own checkpoint** on `feat/doc-analyzer-p3`, with no dashboard changes mixed in. **Needs explicit commit approval.**
3. Create `fix/lawyer-dashboard` from that commit.
4. Record the baseline: the `npm test` count and the `npm run build` result.

---

## Phase 1 — Demo-breaking bugs (LD-01 … LD-06), ~1 day

### LD-01 — Documents inbox crashes on mount
**Fix** (`DocumentsPage.jsx` `ScreenInbox`):
- Never index a null `counts`.
- **V2 mode:** map the cards to the server keys: `submitted` → Pending Review, `approved`, `returned`, `rejected`.
- **Legacy mode** (V2 off, `queueCounts` never set): compute the card totals from the loaded documents through `_tabCount` (`:1367`), the same function the tab badges already use correctly.
- While loading, show `—`; show `0` for a real zero.

**Test:** mount `DocWorkflowApp` with the stub and assert:
- (a) no throw while the counts are pending;
- (b) V2 cards show the server numbers;
- (c) legacy mode cards show the totals of the loaded documents.

### LD-02 — Case workspace forms store a DOM event
**Fix:** in `CasesPage.jsx`, replace `<Input label=… onChange={v => …}>` with the file's value-based `FieldInput`.
- The calls are at `:917-922` and `:952-953`, plus `:1082` and `:1229`, which are hidden in Phase 3 but fixed anyway.
- The shared `components.jsx` `Input` is left unchanged: Clients, Documents, Profile and Settings use it the event way.

**Test:** mount the workspace and check two flows.
- **Schedule hearing:** enter a date, court and purpose and submit. Assert `addHearing` receives an ISO date and the label text is visible.
- **Record outcome with a next date:** assert the request is sent and the button returns from "Saving…".

### LD-03 — Delete agreement draft returns a false 500
**Fix:** `agreements.py:345` should return `StatusResponse(success=True, message="Draft deleted")`.

**Test:** a targeted HTTP regression test. `DELETE /api/v1/agreements/drafts/{id}` returns 200 with the `success`/`message` shape, and the draft is gone. (No sweep over unrelated routes: a static check found the other 20 `StatusResponse` routes already return the correct shape.)

### LD-04 — Onboarding crashes on a 422
**Fix** (`OnboardingPage.jsx`):
- `:1110` should use `err.message`; `formatResponseError` already turns it into a string. Never render `detail`.
- Step 1 validation: the bar number must match the backend pattern (`schemas/user.py:55-58`), and at least one specialization must be picked before "Continue".
- Write the `ONBOARDED_KEY` localStorage flag only after a successful server save.

**Test:**
- Stub a 422 with an array `detail`; assert a readable message and no crash.
- Assert "Continue" is blocked while the fields are empty.

### LD-05 — Clients "Message" goes nowhere
**Fix:** `ClientsPage.jsx:28` should use `caseId: c.case_number || c._id`. The workspace finds a case by `case_number || _id` (`CasesPage.jsx:1736`), so `_id` alone would still fail whenever a case number exists.

**Test:** check two stubbed cases, one with a case number and one without. Clicking Message should call `setOpenCaseId` with the key the workspace uses, and the workspace should mount.

### LD-06 — AI Assistant first question gets a 409
**Fix** (`AILegalPage.jsx`):
- When an `activeCase` is set, delay the mount bootstrap (`:631-642`) until the case list has resolved, then start the conversation **bound** to `activeCaseObj._id`.
- Make the case-change effect (`:385-390`) depend on the resolved `activeCaseObj?._id` instead of skipping the first render.
- **Defensive check:** if a reopened thread's stored case differs from the selected case, start a new bound thread rather than sending.

**Test:**
- Mount with an active case and a delayed `listCases`, then send. The request's `case_id` must equal the conversation's binding; the stub returns 409 on a mismatch.
- Second case: a remembered unbound thread plus a selected case.

**Phase 1 exit:** all six marked fixed in the audit file, the gate is green, and the six paths clicked through manually on the local stack.

---

## Phase 2 — Minimum truthfulness items (2.1, 2.2, 2.4, 2.6), ~1 day

| # | Issue | Fix |
|---|---|---|
| 2.1 | Case status mapping (`CasesPage.jsx:1719`) treats `in_progress`/`pending_lawyer` as "Filed"; "Adjourned" is not derived from server data | Map every backend status (`draft`, `open`, `in_progress`, `pending_lawyer`, `closed`, `dismissed`) to a label, in one shared map that Dashboard also uses. Remove the "Under Hearing"/"Adjourned" filters and cards, which have no backend source. |
| 2.2 | Dashboard numbers | "Active cases" includes `in_progress` and comes from the server `total`, not the loaded row count. "Pending Docs" comes from the review-queue `submitted` count (same source as LD-01). Remove the fake progress bars. Next hearing comes from `hearing_dates`. Show a real `0` instead of `—`. |
| 2.4 | Hearings show 0 when a case is opened from Dashboard/banner; new hearings lack `_id` | Seed hearings inside `CaseWorkspace` from the case record rather than in `handleOpenCase`. After `addHearing` or recording an outcome, rebuild local hearings from the returned `CaseOut`, so "Add Outcome" works without a reload. |
| 2.6 | Errors swallowed or generic | Show `error.message` in: the AI Assistant (separate wording for 409/403/413/422); conversation rename/archive/delete; ratings ("recorded" only after success); document downloads (review page, Draft Generator); `ProfilePage.jsx:61`; `MyDocuments.jsx:67`. |

Each row is its own commit with a test.

---

## Phase 3 — Controls: wire, hide, remove, ~half a day

**Rule:** unsupported controls are **hidden or removed**, never labelled "coming soon".

| Control | Action | Basis |
|---|---|---|
| Settings → Delete Account | **Wire** to `closeAccount()` behind a modal that requires the password | Backend `/users/me/close` and api.js already exist. Check whether the route verifies the password; if not, the modal must not pretend it does |
| Settings → notification toggles | Hide | No backend store |
| Documents → AI Generate | Link to Draft Generator (`doc-automation`) | — |
| Documents → Upload Document | Hide | No lawyer upload endpoint on this page |
| Documents → review-screen "Request changes" toggle and "Lawyer Notes" textarea | **Remove** | Verified dead: the toggle only flips its own label, and the textarea is uncontrolled and never read (`DocumentsPage.jsx:646, 724-739, 959`). The **decision screen's** approve/return/reject notes are functional (`:1053-1081` → `handleDecide` → `reviewDocumentV2`) and are kept |
| Appointments → View Details | Remove | No detail modal exists (`AppointmentsPage.jsx:1426`); the card already shows the data |
| Appointments → calendar events, stat cards | Drop `cursor: pointer` | They have no handler |
| AI Assistant → clock | Open the existing history sidebar (`setSideOpen(true)`, `AILegalPage.jsx:304`) | — |
| AI Assistant → globe, mic, Upgrade Plan | Remove | — |
| Draft Generator → Insert Link | Remove | No-op |
| Dashboard row "more", Clients "more" | Remove | No handler |
| Clients → Add Client, Schedule fake notifications | Remove Add Client. Schedule navigates to Appointments with no fake notification | Fake actions |
| Profile → camera; Onboarding → photo, Take Photo, credential uploads, Admin Support | Remove | No upload endpoint |
| Onboarding → council, max fee, working days, office hours | Remove from the form (working hours already live in Appointments) | Collected but never sent |
| **Case workspace → Documents tab, Timeline tab, hearing edit/delete** | **Hide** (Phase 4 skipped) | Browser-only state, lost on reload. Hearing scheduling and outcome stay (connected once LD-02 is fixed) |
| Dead code: `WorkspaceAI`, `EditMenu`, `StatusBadge`, `DocTopbar`, `LoginPage`, Topbar search | Delete | Never rendered; `EditMenu`/`StatusBadge` would throw if rendered |

**Tests are targeted and behavioural**, not a generic scan of every button:
- Delete Account calls `closeAccount` only after the password is entered.
- AI Generate navigates to `doc-automation`.
- The clock opens the sidebar.
- The removed controls and the hidden tabs are absent from the rendered page.
- Hearing scheduling is still present.

---

## Step 5 — Demo smoke test

Run on the local stack (local DB plus the demo overlay, never the hosted `.env`) and click through every lawyer sidebar page:
- each Phase 1 path;
- schedule a hearing and record its outcome;
- delete an agreement draft;
- finish onboarding with bad and then good input;
- go from Clients to Message;
- go from a case to the AI Assistant and ask a question;
- open the Documents inbox in both V2 and legacy modes.

Record the result in the audit file.

---

## Deferred (not in this plan)

| Item | Reason / note for later |
|---|---|
| 2.3 Today's schedule drawn from the 50 oldest appointments | Needs date-range params on `GET /appointments` |
| 2.5 50-case cap | **No eager `listAllCases()`.** Use pagination/"Load more" for lists, and server-side search or aggregation for pickers and Clients |
| 2.7 Profile email / Verified badge / clearing a field | Not demo-blocking |
| 2.8 Onboarding fee note saved as `bio`, Lahore default | Fix later with the onboarding redesign |
| 2.9 Final screen approver name | Needs **backend enrichment**: the queue supplies the reviewer's id, not a reliable name |
| 2.10 Notification icons, websocket reconnect, unread badge, Review Queue probe | Not demo-blocking |
| 2.11 Clients fake actions | Covered by Phase 3 |
| Cause-list per-source error handling; `.env.example` cleanup | Not part of the dashboard; handle separately if needed |
| Phase 4: persist the case Timeline and Documents tabs and hearing edit/delete | Skipped for the demo; the tabs are hidden in Phase 3 |
| Payments, reminders, in-app video, lawyer reschedule, Overseas Disputes | Out of scope |
