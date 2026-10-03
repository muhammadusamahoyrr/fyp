# Document Review Requests — Phase 1 plan

Status: **Phase 1 in progress.** D1 shipped first as its own fix. Slice 1 (model, indexes,
settings), slice 2 (client service and API), slice 3 (lawyer API), slice 4 (engagement-end
hook, retention, sweep, deletion hold) and slice 5 (notifications) are implemented, behind
`DOCUMENT_REVIEW_REQUESTS` (off). Slice 6 (client UI) is not. The client-side DOCUMENTS_V2 document
DELETE itself does not exist yet (§7.4). Written 2026-10-03; decisions D1–D4 **decided**
2026-10-03 (§14).
Scope owner: Muhammad Usama. Related: `DOC_ANALYZER_PLAN.md` (the analyzer engine),
`ENGAGEMENT_REDESIGN.md` (engagements).

## 0. Scope

**Phase 1:** a client sends an existing Vault document — one exact, frozen version — to the
lawyer of one of their **active engagements**, through an explicit review request. The lawyer
can see the request and the original document, and accept or decline it.

Ground rules (from the product decision of 2026-10-03):

- Creating, drafting, storing and analysing a document needs **no** case or engagement.
- **Sharing** a document with a lawyer needs an **active engagement**. Nothing is shared any
  other way: not by uploading, not by saving to the Vault, not by being attached to a case.
- The Document Analyzer stays lawyer-only (`registered-lawyer-only`, commit `1d94307`).

Out of scope for Phase 1 (later phases):

| Phase | What |
|---|---|
| 2 | Lawyer **Review Queue** UI (this plan designs its API fields now — §9) |
| 3 | **Completed Reports**: a lawyer-finalised report shared back with the client |
| — | Fees, reply-time promises, urgency tiers: **no UI**, there is no backend data for them |
| — | Analysing a client's REAL document: blocked, see §11 |

## 1. What exists today (and what this plan must not duplicate or break)

| Existing piece | Where | Relevance |
|---|---|---|
| Vault = DOCUMENTS_V2 documents | `documents`, `document_revisions`; `GET /documents/v2/mine` | The documents a client can send. Phase 1 covers **generated** v2 documents only: the Vault holds no client-uploaded files today. |
| Immutable revisions | `document_v2_service`, `artifact_store` | A revision's bytes are published once under an immutable key, identified by `pdf_sha256`. This is the "frozen version". **Reuse, never copy.** |
| v2 document review | `document_transitions.submit/review/withdraw`, `GET /documents/v2/review/queue` (lawyer Documents page) | An existing client→lawyer path: approve / return / reject a draft, status on the document itself. Two problems relative to this plan: (a) for a document **without a case** the client may pick **any** KYC-verified lawyer — no engagement needed; (b) it is gated on `lawyer_profile.kyc_verified`. See **Decision D1**. |
| Engagements | `engagement_repo`, `EngagementStatus` | `client_id`, `lawyer_id`, `case_id`, `status`. |
| Idempotency receipts, event outbox | `document_transitions`, `event_outbox` | Reuse the patterns: an Idempotency-Key receipt per mutation, and the notification as a durable intent written in the same atomic step as the state change. |
| Retention deletion | `document_deletion` (tombstone-first; legal holds win; off by default) | Must learn that a revision referenced by a live request is held (§7). |

## 2. Eligibility rules

### 2.1 "Active engagement"

Exactly **`accepted`**.

| Engagement status | New request? | Why |
|---|---|---|
| `requested`, `terms_proposed` | **No** | Still being negotiated; the lawyer has not taken the matter. |
| `accepted` | **Yes** | The only working relationship. |
| `completed`, `terminated` | **No** | The relationship ended. (They stay "retained" for reviews and billing elsewhere — that set is NOT reused here.) |
| `declined`, `cancelled` | **No** | Never became a relationship. |

The check runs at **create** and again at **submit** (the engagement can end in between).

### 2.2 Who may do what

| Action | Allowed for | Otherwise |
|---|---|---|
| Create / edit / delete a draft, submit, cancel | The **document owner** (`documents.client_id == caller`), who is also the engagement's `client_id` | 404 (§8) |
| See a submitted request and download its document | **Only** that engagement's `lawyer_id` | 404 |
| Accept / decline | That engagement's `lawyer_id` | 404 |
| Anyone else (another client, another lawyer, an admin through these routes) | — | 404 |

### 2.3 Which document and version

- The document is a DOCUMENTS_V2 document owned by the caller, not deleted.
- The client picks **one revision** explicitly (default: the current live revision). It must be
  `status == "generated"` with a published artifact; the request stores `revision_id`,
  `version` and `pdf_sha256`, and the submit re-checks `expected_pdf_sha256` (a revision that
  changed since the client loaded it → 409).
- **Case consistency:** if the document has a `case_id`, it must equal the engagement's
  `case_id` (409 `case_mismatch`). A document with no case may go to any of the client's
  active engagements — choosing the engagement is the explicit act of sharing.

## 3. Lifecycle

```text
draft ──submit──► submitted ──POST /view───► viewed ──┬─accept──► accepted
  │                   │                        │      └─decline─► declined
  │                   └──────client cancel─────┴────────────────► cancelled
  └──client deletes── (row removed; audit event kept)
```

| From | Event | To | Actor | Notes |
|---|---|---|---|---|
| — | create | `draft` | client | Invisible to the lawyer. Nothing is shared yet. |
| `draft` | edit note/focus, change version/engagement | `draft` | client | |
| `draft` | delete | (removed) | client | Audit event `draft_deleted` remains. |
| `draft` | submit | `submitted` | client | Engagement and revision re-checked; notification intent written. |
| `submitted` | lawyer calls `POST /{id}/view` | `viewed` | lawyer | Atomic `submitted→viewed`; later calls change nothing. Reading the request or downloading its document never does this (§5). |
| `submitted`, `viewed` | accept | `accepted` | lawyer | "I will review this." The review OUTCOME is Phase 2/3. |
| `submitted`, `viewed` | decline (optional reason ≤ 500 chars) | `declined` | lawyer | |
| `submitted`, `viewed` | cancel | `cancelled` | client | Lawyer access ends at once (§7). |
| `draft`, `submitted`, `viewed` | engagement leaves `accepted` | `cancelled` (`reason: engagement_ended`) | system | §7.3 |
| `accepted` | client cancel | **refused (409)** in Phase 1 | — | The lawyer is working on it; ending that is an engagement matter. |

Terminal: `accepted`, `declined`, `cancelled`. A terminal request never changes again. Sending
the document again — or a later version — is a **new** request.

**Later edits never touch a submitted request.** Editing the document creates a new revision;
the request keeps pointing at the frozen one. To share the new version the client makes a new
request.

**One open request per (document, engagement):** at most one in `draft | submitted | viewed`.
A second create returns 409 `open_request_exists` with the existing request's id (the UI offers
to open it).

## 4. Data model

### 4.1 `document_review_requests`

```text
_id                 str  (uuid hex)
state_version       int  (optimistic concurrency; +1 on every change)
status              draft | submitted | viewed | accepted | declined | cancelled
client_id           str  (= documents.client_id = engagements.client_id)
lawyer_id           str  (= engagements.lawyer_id, copied at create, frozen)
engagement_id       str
case_id             str | null   (the engagement's)
document_id         str
revision_id         str          ┐
version             int          │ the FROZEN version; never updated after submit
pdf_sha256          str          ┘
document_title      str          (snapshot at submit, for lists)
template            str | null   (snapshot at submit)
note                str | null   (≤ 2000 chars, optional, client's words)
focus               list[str]    (optional, ≤ 5 items of ≤ 120 chars: "rent clause", ...)
created_at, submitted_at, viewed_at, decided_at, cancelled_at   datetime | null
decline_reason      str | null
cancel_reason       client_cancelled | engagement_ended | document_deleted | null
receipts            {hash(Idempotency-Key): {op, fingerprint, result}}   (capped, as in document_transitions)
pending_events      [EventIntent]  (outbox intents, materialised by the reconciler)
```

No file bytes, no copy of the PDF, no analyzer output.

### 4.2 `document_review_request_events` (append-only audit)

`{request_id, seq, type, actor_id, actor_role, at, from_status, to_status, detail}`.
Types: `created`, `edited`, `draft_deleted`, `submitted`, `viewed`,
`document_download_authorized`, `accepted`, `declined`, `cancelled`, `retention_started`.
`document_download_authorized` is written (and committed) after the bytes are verified and
BEFORE they are returned, so it records that a download was authorised and started, not that
the client received the file -- a disconnect mid-transfer leaves the same event. `detail` holds ids and hashes only (revision id,
pdf_sha256, reason code) — never the note text or document text. Rows are never updated or
deleted by this module.

### 4.3 Indexes

| Index | Purpose |
|---|---|
| `uniq_open_request` — unique `(document_id, engagement_id)`, partial `status ∈ {draft, submitted, viewed}` | One open request per document and engagement; closes the race between two creates. |
| `(lawyer_id, status, submitted_at desc, _id)` | Lawyer inbox (Phase 2 queue), cursor-paginated. |
| `(client_id, status, created_at desc, _id)` | Client's list. |
| `(engagement_id, status)` | Engagement-ended sweep (§7.3). |
| `(revision_id, status)` | Deletion hold check (§7.4). |
| events: unique `(request_id, seq)` | Ordered, append-only history. |

## 5. API

Feature flag `DOCUMENT_REVIEW_REQUESTS` (default **off**; requires `DOCUMENTS_V2`). Off → 404
`feature_disabled` on every route. Every mutation takes an `Idempotency-Key` header (same rules
as `document_transitions`) and, where it changes an existing request, `expected_state_version`.

### Client (`require_client`)

| Method & path | Body | Result |
|---|---|---|
| `GET /review-requests/eligible-engagements?document_id=` | — | The caller's `accepted` engagements this document may go to (case rule applied): id, lawyer display name, case title. No fees, no reply times. |
| `POST /review-requests` | `{document_id, revision_id, expected_pdf_sha256, engagement_id, note?, focus?}` | 201 draft. 409 `open_request_exists` / `engagement_not_active` / `revision_changed` / `case_mismatch`. |
| `PATCH /review-requests/{id}` | `{expected_state_version, note?, focus?, revision_id?, expected_pdf_sha256?, engagement_id?}` | Draft only. |
| `DELETE /review-requests/{id}` | `expected_state_version` header | Draft only → 204. |
| `POST /review-requests/{id}/submit` | `{expected_state_version}` | `submitted`; engagement and revision re-checked. |
| `POST /review-requests/{id}/cancel` | `{expected_state_version}` | From `submitted`/`viewed` only. |
| `GET /review-requests?status=&cursor=` | — | The caller's requests. |
| `GET /review-requests/{id}` | — | One request (client view). Read-only. |

### Lawyer (`require_lawyer`, and the request's frozen `lawyer_id == caller`)

**Every GET is read-only.** A browser prefetch or a cache can issue a GET, so no GET changes a
request's status: opening a request is an explicit `POST /view`. (Changed during slice 3 from
an earlier draft in which the first GET of the request or its document marked it viewed.)

| Method & path | Result |
|---|---|
| `GET /review-requests/inbox?status=&cursor=` | The caller's submitted/viewed/accepted/declined/cancelled requests (never drafts, nor a draft the system cancelled before submission), keyset-paginated on `(submitted_at DESC, _id ASC)`. |
| `GET /review-requests/{id}` | One request, lawyer view (same path as the client's; each role gets its own view). **Read-only.** |
| `POST /review-requests/{id}/view` | The ONLY way `submitted → viewed` happens. Idempotent: later calls return the request unchanged; one `viewed` event ever. |
| `GET /review-requests/{id}/document` | The FROZEN PDF from the existing artifact by `revision_id`. The revision, its artifact and its `pdf_sha256` are checked, then the bytes themselves are hashed; any mismatch → 409 `integrity` (missing file or revision → 409 `artifact_unavailable`), never the wrong bytes. Writes a `document_download_authorized` audit event (ids and hashes only); **does not change the status** or the state version. Allowed only while the request grants access (§7.1). |
| `POST /review-requests/{id}/accept` | `{expected_state_version}` + Idempotency-Key. From `submitted`/`viewed` only; the engagement must still be accepted. |
| `POST /review-requests/{id}/decline` | `{expected_state_version, reason?}` (≤ 500 chars) + Idempotency-Key. From `submitted`/`viewed` only. The reason is shown to the client, never written to the audit. |

The lawyer's responses carry the original document and the client's note/focus **only** —
no analyzer output exists for these requests, and none is attached. Analysis never starts
automatically; a lawyer starts it themselves (and today cannot, for a real document — §11).

## 6. Notifications

| Event | To | Type (new `NotificationType`) |
|---|---|---|
| submitted | lawyer | `review_request_submitted` |
| accepted / declined | client | `review_request_accepted` / `review_request_declined` |
| cancelled (client or system) after the lawyer could see it (`submitted`/`viewed`) | lawyer | `review_request_cancelled` |

Creating, editing or deleting a draft, `POST /view`, a download and retention starting notify
no one; nor does the system cancelling a draft (it was never shared).

The notification is a durable **intent** written in the same atomic update as the status
change (the `pending_events` + reconciler pattern of `document_transitions`). Sending it is the
reconciler's job: a failed or slow notification never rolls back or fails the request, and is
retried. The notification text names the document title and client — never the note or any
document text.

As built (slice 5, `services/review_request_notifications.py`):

- **Intent in the same write.** `_change` (submit, accept, decline, cancel) and the lifecycle
  hook (system cancel) `$push` the intent onto `pending_events` in the very update that changes
  the status, inside its transaction. A rolled-back change leaves no intent.
- **Exactly one.** Dedupe key `review_request:{request_id}:{event_seq}:{recipient_id}:{kind}`
  is the notification's `logical_event_id` (unique index). A retry, a crash between notifying
  and removing the intent, or concurrent reconcilers all end with one notification. Intents
  are removed by id (`$pull`), never by rewriting the array.
- **Delivery.** Best effort right after the commit (`deliver_now`, never raises — a committed
  submit is never turned into an error), and `reconcile()` every 30 s: bounded `_id`-ordered
  batches over the rows that hold intents (partial index `review_requests_pending_events`,
  hinted). A failure records the error class, backs off (2^n s, ≤ 10 min) and retries. No-op
  while the flag is off; intents written earlier are delivered once it is on again.
- **Recipient check.** At delivery the intent's recipient must still be the request's party in
  that role; anything else is dropped and logged, never delivered.
- **Content.** Title, the other party's name, and `payload = {review_request_id, link}` with
  `link = /{lawyer|client}/review-requests/{id}` (the UI routes arrive in slice 6). Never the
  note, the decline reason, document text, a storage path or a hash.
- **WebSocket.** `notification_service.create_notification` now treats the WebSocket push as a
  courtesy: a socket or Redis failure is logged and the stored notification stands.
- Email and payment integrations are out of scope.

## 7. Access, revocation and retention

### 7.1 When the lawyer can open the request and download the document

| Request status | Engagement `accepted` | Engagement ended (`completed`/`terminated`) |
|---|---|---|
| `draft` | no (invisible) | no |
| `submitted`, `viewed` | **yes** | — (auto-cancelled, §7.3) |
| `accepted` | **yes** | **read-only until `retention_until`** (D3: 30 days) |
| `declined`, `cancelled` | no — the request row stays listed without the document | no |

"No" means the document endpoint answers 404 and the inbox item shows its status but not the
document.

**Implementation status.** Enforced since slice 4: an open request whose engagement is no
longer `accepted` is 404 (and is cancelled by the hook or the sweep), and an accepted request is
404 from the instant `now >= retention_until`. The engagement-end hook writes `retention_until`
(§7.3); the document-deletion trigger is ready but has no caller yet (§7.4).

### 7.2 Client cancel

Allowed from `submitted` or `viewed`; access ends at once (the next download is 404). The
lawyer is notified if they could already see it. From `accepted`: refused in Phase 1 (409).

### 7.3 Engagement ends

A hook on every engagement transition out of `accepted` (completed, terminated) — and a
periodic sweep as a backstop — moves that engagement's `draft | submitted | viewed` requests to
`cancelled` (`cancel_reason: engagement_ended`, system actor). `accepted` requests keep their
status and start read-only retention (§7.4).

As built (slice 4, `services/review_request_lifecycle.py`):

- **Same transaction.** `terminate_engagement` (already transactional) and
  `complete_engagement` (made transactional for this: its final `accepted → completed` write is
  now conditional and shares a transaction with the hook) call
  `end_for_engagement(session, …)`. If the hook fails, the engagement transition rolls back.
- **Only while `DOCUMENT_REVIEW_REQUESTS` is on.** Off, the hooks and the sweep are no-ops and
  `complete_engagement` takes its original non-transactional path, so a standalone Mongo
  (local development) completes engagements exactly as before. On, transactions are mandatory
  and startup refuses a standalone server (`review_request_lifecycle.assert_ready`, after the
  index check) instead of failing a completion at runtime. Rows left open while the flag was off
  are caught up by the sweep once it is on again. (`terminate_engagement` was already
  transactional before this plan and still needs a replica set either way.)
- **Races.** Submit and accept write the request row, which the hook also writes, so the pair
  serialises (one retries and sees the other). Create, and a draft moved to another engagement,
  only READ the engagement, so they `$inc` a `review_request_guard` counter on the engagement
  row inside their transaction to force the same conflict (otherwise a draft could commit on an
  engagement whose termination committed a moment earlier). The counter is stripped from
  engagement API responses.
- **Sweep.** `sweep()` runs every `REVIEW_REQUEST_SWEEP_MINUTES` (default 15) while the flag is
  on. It pages open requests, then accepted ones without retention, by `_id` in bounded batches
  (index `review_requests_sweep`), and runs the same hooks — one transaction per ended
  engagement or missing document. Re-running writes nothing: processed rows no longer match.
- **Audit.** `cancelled` and `retention_started` events, `actor_role: system`, detail = ids and
  reason codes (and `retention_until`) only.

### 7.4 Retention and deletion (D3, decided)

```text
Engagement ends / client deletes the document
        ↓
accepted request becomes read-only
        ↓
retention_until = event time + REVIEW_REQUEST_RETENTION_DAYS (default 30)
        ↓
after retention_until: lawyer access → 404
        ↓
artifact deleted once no other hold exists
```

- **Configurable:** `REVIEW_REQUEST_RETENTION_DAYS` (setting, default 30).
- **Frozen, first trigger wins:** `retention_started_at`, `retention_until` and
  `retention_reason` are written ONCE, by the first triggering event (engagement leaves
  `accepted`, or the client deletes the document). A later event finds `retention_until` set
  and changes nothing — the 30 days are never reset or extended. Changing the setting later
  affects only future triggers.
- New fields on the request: `retention_started_at`, `retention_until`, `retention_reason`
  (`engagement_ended | document_deleted`).
- **Legal hold vs UI access:** a legal hold may keep the FILE beyond `retention_until`
  (`document_deletion` already lets holds win), but it never extends the lawyer's access in the
  UI or API: after `retention_until` the request's document endpoint is 404 regardless of holds.
- The PDF is never copied: the request references the revision's existing artifact.
- `document_deletion` gains a hold: a revision referenced by a request in `submitted`,
  `viewed`, or `accepted` with `retention_until` unset or in the future is **not deleted** —
  `delete_revision` returns `held` before writing anything, and `purge` counts it as held.
  Once `retention_until` passes, the same call deletes it. A draft, a declined or a cancelled
  request holds nothing.
- A client deleting a Vault document: its `draft | submitted | viewed` requests are cancelled
  (`document_deleted`); for an `accepted` request the client is told, before deleting, that the
  lawyer keeps read-only access to the version they were sent for 30 days.
- **Deferred to its own slice** (`feat(documents): add recoverable Vault document deletion`):
  DOCUMENTS_V2 has no client-facing document DELETE today — no route, no service.
  `end_for_document(session, …)` is implemented and tested, and the sweep applies it to any
  request whose document row is gone, so the review-request side is ready. Recommended design
  for that slice: a `deleted_at` tombstone (recoverable, not a hard delete) written in the same
  transaction as `end_for_document`, with an asynchronous purge afterwards that honours the
  revision hold above; and, when an accepted request exists, the 30-day lawyer-access warning
  shown before the client confirms. Tombstone semantics, recovery and the warning wording are
  that slice's design, not this one's.

## 8. Authorization, enumeration safety, audit

- **Role mismatch** (a lawyer calling a client route or the reverse) → 403.
- **Everything else not visible to the caller → 404**, with the same body as a truly missing id:
  another client's document or request, another lawyer's request, a draft (for a lawyer), a
  document in a case that is not the engagement's. A 403 here would confirm the id exists.
  (Note: today's v2 `submit` answers 403 "Document does not belong to you" — the new routes do not
  copy that.)
- Every state change and every document download writes an audit event (§4.2) in the same
  atomic step as the change.
- Request ids are random (uuid hex), never sequential.

## 9. Designed now for Phase 2 (Review Queue)

The inbox list and detail responses return, from Phase 1:

`id, status, state_version, submitted_at, viewed_at, decided_at, client {id, display_name},
engagement {id, case_id, case_title}, document {id, title, template, version, revision_id,
pdf_sha256}, note, focus, cancel_reason, decline_reason, access {can_download: bool},
analysis: null` — `analysis` is reserved for Phase 2 and stays `null`.

Cursor = `(submitted_at, _id)`, as in `document_transitions.review_queue`.

## 10. UI (client) states

Entry point: a **"Request lawyer review"** action on a Vault document row (and in the
document's detail), enabled only for a document with a generated revision.

1. **Pick a version** — default the current one; older generated versions listed with dates.
2. **Pick an engagement** — only eligible ones (lawyer name, case). Empty state: *"You have no
   active engagement with a lawyer. Hire a lawyer first to share documents."* with a link.
3. **Note and focus** — both optional; a counter at the limit.
4. **Review and submit** — shows exactly what will be shared: document, version, date, lawyer,
   note — and, before the Submit button (D4): *"Once the lawyer accepts this request you cannot
   cancel it here; you can cancel only until then."* Submit button disabled while submitting
   (idempotency key reused on retry).

Request states shown to the client: *Draft (only you can see this)*, *Sent*, *Opened by the
lawyer*, *Accepted*, *Declined* (+ reason), *Cancelled* (+ why). Actions: draft → edit / delete /
submit; sent or opened → cancel; terminal → none.

Errors with their own wording: version changed since loaded; engagement no longer active; an
open request already exists (open it); case mismatch; network retry (safe). **No fee, price,
urgency or reply-time element anywhere.**

The lawyer-side UI is Phase 2. The flag stays **off** until Phase 2 ships, so no client can
send what no lawyer can open.

## 11. The Analyzer restriction (unchanged by this plan)

The analyzer accepts **synthetic documents only** (attestation on every upload,
`ANALYZER_AI_SYNTHETIC_ONLY=true`, ZDR policy AAI-AI-DP-001 scope "synthetic evaluation
documents only"). A client's real document sent through a review request is therefore **not**
analysable today, by design. Allowing it needs its own decision — real-document policy, client
consent, data retention and the ZDR scope — and is not part of Phases 1–2.

## 12. Migration and rollout

1. Create the two collections and their indexes (startup index check, as for the analyzer).
2. No backfill: no existing data becomes a request.
3. New `NotificationType` values and their templates.
4. `document_deletion` hold check (no effect while deletion stays off).
5. Engagement-transition hook + sweep job.
6. Flag `DOCUMENT_REVIEW_REQUESTS` off; turned on together with Phase 2's lawyer UI.
7. Decision D1 applied (below).

## 13. Focused test matrix

| Area | Cases |
|---|---|
| Eligibility | each of the 7 engagement statuses at create and at submit; engagement ends between create and submit; case match / mismatch / document without case |
| Ownership & enumeration | another client's document, another client's request, another lawyer's request, a lawyer reading a draft, an admin — all 404 with identical bodies; role mismatch → 403 |
| Frozen version | submit pins revision + sha; a later edit creates a revision and the request still serves the old bytes; a tampered artifact → 409 `integrity`, no bytes |
| Lifecycle | every allowed transition; every refused one (409); terminal states never change; viewed set once |
| Idempotency | duplicate create / submit / cancel / accept with the same key → the original result; same key different body → 409; double-click race on create → one row (unique index) |
| Concurrency | stale `expected_state_version` → 409; cancel vs accept race → exactly one wins |
| Access & revocation | download allowed per §7.1 table, row by row; access ends on cancel/decline; engagement end auto-cancels open requests; accepted keeps read-only access |
| Retention | deletion skips a held revision; client deleting a document cancels open requests and warns about accepted ones |
| Notifications | intent written with the change; notifier failure leaves the request committed; reconciler retries; no note text in notifications |
| Audit | one event per change and per download, ordered by seq, ids/hashes only |
| No analyzer leak | inbox responses contain no analyzer fields beyond `analysis: null`; no run is created by any request action |
| Flag | off → 404 everywhere |
| UI | each state's wording; empty-engagement state; no fee/urgency/reply-time element; submit disabled while in flight; retry reuses the key |

## 14. Decisions (decided 2026-10-03)

| | Decision | Status |
|---|---|---|
| **D1** | Restrict the existing submit paths NOW: every client→lawyer submission needs an `accepted` engagement with that lawyer — a case-less document too, to the lawyer of one of the client's accepted engagements. Shipped as a separate security/consistency fix BEFORE Phase 1, because the live routes bypassed the engagement rule. | **Decided — implemented** (`document_sharing.require_accepted_engagement`, used by both the legacy and DOCUMENTS_V2 submit; the client's review step offers only engaged lawyers) |
| **D2** | No KYC gate and no "KYC" wording in review requests. The engagement relationship is the authorisation; the lawyer role stays registered-lawyer-only. | **Decided.** (The pre-existing KYC check in the two OLD submit paths is left as it is for now; removing it is a separate change.) |
| **D3** | Accepted request: 30-day read-only retention from the engagement's end or the document's deletion; configurable; `retention_until` frozen; legal holds extend file retention, never UI access (§7.4). | **Decided** |
| **D4** | No client cancellation after `accepted` in Phase 1 (409). Acceptance means the lawyer has started; the UI says so before submit (§10). | **Decided** |

Rollout constraint: the `DOCUMENT_REVIEW_REQUESTS` flag stays **off** until BOTH the client
submission flow and the lawyer Review Queue (Phase 2) are ready. The analyzer's synthetic-only
policy is unchanged (§11).
