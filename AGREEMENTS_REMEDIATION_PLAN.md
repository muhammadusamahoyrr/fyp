# Agreements Module — Remediation Plan

Status: approved for implementation. Written 2026-09-20.
Scope: the agreements module end to end — `POST /agreements` and the client
wizard, the lawyer sign/decline view, the engagement-letter producer, signature
capture and storage, and the fee gate that depends on all of it.

Phase 0 is a deletion of untrue statements and ships on its own, today.
Phases 1 and 2 are correctness defects that produce wrong or stuck records;
nothing in Phase 3 starts until both have landed. Phase 4 is blocked on counsel
and must not be started speculatively.

Every claim below was verified against the code on 2026-09-20 at the cited
line. Where a finding came from the Codex review, it was re-verified here
before being included; where the Codex review was wrong, §7 records why.

---

## What is already correct

Do not re-litigate these; they work and are tested.

- **`_derive_eto`** (`agreement_service.py:37`) — agreement-level classification
  derived from the *weakest* signature actually made, with an unknown method
  ranking below every known one. This replaced a last-writer-wins bug; do not
  reintroduce stored state that duplicates derivable state.
- **`body_digest`** (`agreement_service.py:78`) — SHA-256 of the body stamped
  into the row at creation and into every audit entry, so a later edit is
  detectable rather than merely unlikely.
- **The decline state machine** — non-party refused, executed cannot be
  declined, declining twice refused, a declined agreement cannot then be signed.
- **Strict response models** — `PartyOut` drops the raw signature blob and
  `AgreementOut` drops `audit_log` (and therefore signer IPs).
- **The unreviewed-template refusal**, checked at both create and sign, so
  withdrawn boilerplate cannot reach `executed` even for rows created before
  the templates were withdrawn.
- **The engagement-letter producer** (`engagement_service.py:343-390`) — it
  rolls back both the case claim and the engagement transition if letter
  generation fails.
- **The fee gate** (`payment_service.py:79`) — a lawyer cannot bill without an
  accepted engagement *and* an executed letter.
- 35 service tests in `test_agreement_service.py` and 14 frontend tests in
  `agreement_decline.test.mjs`, all green (verified by running them).

Note: `backend/tests/test_agreement.py` is **annotator agreement**
(Krippendorff's alpha) and has nothing to do with this module despite the name.
Renaming it is a Phase 3 chore, not a test gap.

---

## Verified completion, before this plan

| Surface | Complete |
|---|---|
| Client agreements | ~72% |
| Lawyer agreements | ~65% |
| Production-safe agreements system | ~55% |

The lawyer side scores **lower** than the client side, not higher: a lawyer
cannot author an agreement at all, which is the central use case for a legal
platform.

---

## Phase 0 — Delete the untrue statements ✅ DONE

**Implemented 2026-09-20.** All four claim sites cleared, both `alert()` lies
removed, dead chrome and the 24-button toolbar deleted, withdrawn templates
badged, guard test green (6 tests). Frontend suite 869/869 after the change.

### Two things the plan did not anticipate

**The guard test initially forbade its own explanation.** Every AES hit on the
first run was a comment written to record *why* the claim was removed —
including the `models/user.py` note this plan explicitly asks to keep. The
policy is now: a comment may name a claim in order to refuse it; a rendered
string may not make one. Comments are exempt, and `_comment_lines` tracks block
state so a multi-line `{/* … */}` continuation is exempt too. Line-based
matching was not sufficient and reported claims from lines no user can reach.

**The guard also forbade a true claim.** `Draft Saved` in
`DocAutomationPage.jsx:621` is correct — lawyer document drafts really do
persist through `saveDocDraft`. Each rule is now path-scoped to the surfaces
where the capability is genuinely absent. A guard that forbids true statements
gets disabled, which is worse than no guard.

---

### Original scope, for the record

These are not UX polish. Each one is the product asserting something false to a
user who is about to sign a legal instrument.

### 0.1 Two false claims, in four places

The two signing-flow strings each carry **two** unsupported claims, and both
must go:

1. **"AES-256 encrypted"** — `signature_data` is written as plaintext base64
   into the Mongo document (`agreement_repo.py:43`). The only encryption in the
   codebase is `encrypt_cnic` (`core/security.py:55`), which is **Fernet —
   AES-128-CBC with HMAC-SHA256** — so the label is wrong even where encryption
   is genuinely applied, and it is applied to CNICs, not to signatures.
2. **"Compliant with e-signature laws"** — an unreviewed legal conclusion about
   ETO 2002, the same overreach as §4.1's classification labels in plainer
   words. Removing only the encryption half leaves this standing.

| Location | Text | Action |
|---|---|---|
| `ModAgreements.jsx:676` | "AES-256 encrypted · Timestamped · Compliant with e-signature laws." | Remove both claims |
| `ModAgreements.jsx:1021` | "All signatures are encrypted with AES-256, timestamped, and comply with e-signature laws." | Remove both claims |
| `OnboardingPage.jsx:1015` | "Security Active — AES-256 protected." | **Delete the subtitle** |
| `models/user.py:33` | `cnic_encrypted: str \| None = None  # AES-256 encrypted` | **Correct** to `# Fernet (AES-128-CBC + HMAC-SHA256)` |

`OnboardingPage.jsx:1015` was checked to see whether it describes CNIC storage
and could simply be relabelled AES-128. It does not: it is a status card beside
"Profile Submitted" and "Waiting to Launch", under *"Your complete profile has
been securely submitted"*, so it characterises the whole profile — of which
name, bar number and specializations are plaintext. Relabelling would trade a
false claim for a misleading one.

`models/user.py:33` is the opposite case: it *does* describe CNIC storage, so it
is corrected rather than deleted. Left alone it is the seed the UI claim grows
back from.

**Action:** replace the signing-panel copy with what is actually true —
*"Timestamped and recorded with a full audit trail."* Do not substitute a
different security claim. Real signature encryption is §4.2 and it is not a
Phase 0 job.

### 0.7 Regression guard, shipped in the same commit

A test asserting that `AES-256`, `AES-128`, `Draft saved` and
`Compliant with e-signature` do not appear under `frontend/src/`.

Two design constraints, both inherited from `test_no_tracked_example_secrets.py`
which solves the same shape of problem:

- Scan by **explicit allowlist of paths**, never "everything except what we
  remember to exclude".
- **Do not scan the test suite.** This guard necessarily contains the strings it
  forbids, and a rule that scanned itself would force the safety test to be
  weakened to satisfy the safety test.

### 0.2 `alert("Draft saved!")` — `ModAgreements.jsx:521`

Nothing is saved. This is worse than an inert button: it affirmatively confirms
persistence that does not exist, and the user then navigates away and loses the
draft.

**Action:** remove the button. Real draft persistence is §3.4.

### 0.3 `alert("Preview: ${tmpl.name}")` — `ModAgreements.jsx:402`

**Action:** remove the Preview button. The templates are withdrawn; there is
nothing to preview.

### 0.4 Dead chrome — `ModAgreements.jsx:1440-1466`

- 🔍 search button, no handler.
- 🔔 bell, no handler, **rendering a permanent unread dot** — a notification
  badge that is always on and means nothing.
- Hardcoded `JD` avatar shown to every user regardless of who they are.

**Action:** delete all three. The real notification drawer already exists in
`Dashboard.jsx`; this bar is a decorative duplicate.

### 0.5 The 24 inert formatting buttons — `ModAgreements.jsx:414-423, 547-559`

`TOOLBAR_ACTIONS` renders B, I, U, H1–H3, lists, tables, undo and redo above a
plain `<textarea>`. They hover and do nothing. The body is plain text stored in
a field called `body_html`, so the toolbar is a lie in both directions.

**Action:** delete the toolbar. A real editor is out of scope for this plan.

### 0.6 Mark the withdrawn templates as withdrawn

All six carry `UNREVIEWED_MARKER` and the backend refuses them at create *and*
sign, but the gallery still labels four of them "Popular" and the marker is
never checked in the UI.

**Action:** badge every card "Withdrawn — pending legal review", remove the
"Popular" flags, and disable selection. The full fix is §1.4.

**Phase 0 gate:** grep the frontend for `AES`, `alert(`, `TOOLBAR_ACTIONS` and
`e-signature laws` and get nothing back from this module; the §0.7 guard test
passes and would fail if any string were restored.

---

## Phase 1 — Integrity

**Estimated 3 days. Backend and frontend verified separately.**
**Status: D1 answered — PARK. §1.1c, §1.1d, §1.1e, §1.1g and the park flag
IMPLEMENTED 2026-09-20. §1.1a (idempotency fingerprint) and the atomic
create-and-sign remain, and are deliberately deferred: per §1.1f they serve the
wizard path, which is now parked.**

### What landed

- **Park flag** `agreements_diy_builder_enabled` (off). Enforced in the
  SERVICE, not only the route, so an internal caller cannot walk past it.
  Frontend mirror `NEXT_PUBLIC_AGREEMENTS_DIY_ENABLED` gates the sidebar, the
  dashboard call-to-action and the page routes — parked pages are unreachable
  by route, not merely unlinked. Listing, viewing, signing and declining stay
  available to everyone.
- **Plain text** (§1.1d): `normalise_body` canonicalises line endings so the
  same wording hashes identically on Windows and Linux, and REFUSES unsafe
  control characters rather than stripping them. `body_format` stamped. No
  `nh3`.
- **Two named producers** (§1.1c): `create_user_agreement` (gated) and
  `create_pending_engagement_letter` (never gated — it gates billing).
- **Transactional sign and decline** (§1.1b): one conditional write per
  transition, audit entry and status in the same write, notification parked
  **inside** the transaction, **fail closed** where transactions are
  unavailable. `_run_in_transaction` refuses rather than degrading.
- **Outbox drainer** (§1.1g): ungated `_event_outbox_relay` in `main.py`.

### Verification

| Run | Result |
|---|---|
| Targeted baseline, committed Phase 0, standalone | 296 pass / 0 fail |
| Same 296 after Phase 1, replica set | 296 pass / 0 fail — no regressions |
| New `test_agreement_phase1.py`, replica set | 20 pass |
| Agreement suites, standalone | skip cleanly, with a reason and a fix |

### Two things this phase did not anticipate

**The test suite had no transactions to test with.** `conftest.py:197` connects
to a standalone, so the first run of the transactional code turned 10 existing
sign/decline tests red with a 503 — the fail-closed path working exactly as
designed, and proving nothing about the transactional one. Fixed by a
`mongo_transactional` fixture that skips with an actionable reason, and by
standing up a throwaway single-node replica set to actually run them. **A
fail-closed guarantee needs an environment where the open path exists, or the
only branch under test is the refusal.**

**Parking changed what the existing tests were asserting.** With the flag off,
every test that created an agreement through the user path began exercising the
refusal instead of the thing it was written for. They now enable the flag
explicitly via an autouse fixture, which keeps both properties under test: that
parking refuses, and that nothing else broke while it was parked.

### Design corrections adopted before implementation

Six amendments from the Phase 0 review. They change the shape of the work, not
just its detail, and supersede the paragraphs below where they conflict.

**1.1a Idempotency needs a payload fingerprint, not just a key.**
Returning the same agreement id for a repeated key is insufficient: a client
that reuses a key with a *different* body would silently receive the first
agreement and believe the second was created. Scope the key by
`(creator_id, operation)` and store a canonical fingerprint of the request —
title, body, party ids, signature. Same key + same fingerprint → the original
result. Same key + different fingerprint → **409**, never a silent alias.

**1.1b The outbox event is written INSIDE the transaction.**
The original text below says notifications are enqueued after the write
commits, which leaves a crash gap: commit succeeds, process dies, nobody is
ever told. Correct shape:

```
transaction:
    insert agreement
    save creator signature
    append audit event
    save idempotency receipt
    insert notification outbox event      <-- inside
commit
worker delivers notification / websocket  <-- outside
```

`event_outbox.py` already exists and is the intended mechanism.

**1.1c Split the two creation paths explicitly.**
`POST /agreements` requires the creator's signature; `engagement_service`
legitimately creates an *unsigned* letter awaiting two signatures. Forcing both
through one ambiguous function is how the signature becomes optional again by
accident. Two named operations:

- `create_and_sign_agreement(...)` — the external wizard path
- `create_pending_engagement_letter(...)` — the internal producer

**1.1d Do NOT run `nh3` over the agreement body.** *(supersedes §1.5)*
The editor now declares plain text, and Phase 0 made that explicit to the user.
Sanitising plain text as HTML can silently alter valid agreement wording that
contains `<` or `>` — mangling the very content whose hash is the evidentiary
record. Correct handling:

- normalise line endings;
- reject NUL and unsafe control characters;
- hash the exact normalised text the user reviewed;
- **escape at every rendering sink** (HTML view, PDF), which is where injection
  actually matters;
- rename toward `body_text`, or add `body_format="plain_text"`.

Reach for `nh3` only if rich HTML is ever deliberately supported.

**1.1e Transaction tests need a real replica set.**
Production Atlas supports transactions; a standalone local Mongo does not.
Tests must use a replica-set fixture or an explicit mocked transaction
boundary. Production must **fail closed** if transactions are unavailable —
never silently degrade to non-transactional writes, which would reintroduce the
exact race this phase exists to close.

*Confirmed during implementation:* `tests/conftest.py:197` connects to
`mongodb://localhost:27017` — a **standalone**, so transactions are
unavailable in the suite as it stands. A replica-set fixture that skips (with a
named reason, never silently) is therefore required before the transactional
tests can mean anything.

**1.1g The event outbox had no drainer — found during implementation.**

Moving the notification enqueue inside the transaction (§1.1b) is only half a
fix. `event_outbox` is documented as *"DORMANT until DOCUMENTS_V2; no scheduler
drains it yet"*, and the one relay that calls `drain_once` —
`_documents_v2_relay` — returns immediately while `documents_v2` is off, which
is the default.

So parking events there without a drainer would have replaced best-effort
delivery that mostly works with durable queuing that **never delivers**: a
worse failure than the crash gap being closed, and a silent one.

`main.py` now runs `_event_outbox_relay()`, ungated, for the same reason the
provenance relay is ungated — *a config default must never be able to leave an
outbox undrained*. `drain_once` is lease/CAS-guarded, so it running in both
relays is safe.

**This is the general shape to watch for in the rest of Phase 1:** a durability
mechanism is not finished when the write is durable, only when something reads
it back out.

**1.1f Sequencing against D1.**
If the DIY builder is being parked, do not spend this phase building atomic
create-and-sign for a hidden workflow. **Transactional, idempotent sign and
decline are required either way** — engagement letters depend on them — so
those proceed regardless. Only the create-and-sign wizard path waits on D1.

### 1.1 Create + sign is two non-atomic calls

`ModAgreements.jsx:1051-1066` calls `createAgreement`, then `signAgreement`.
Creation notifies every counterparty immediately (`agreement_service:176-184`).
If the second call fails, the result is a `pending` agreement **the creator has
not signed**, already announced to the counterparty, with the wizard still open
— so the user retries and creates a second binding instrument.

**Action:** one endpoint, one service call. `POST /agreements` accepts the
creator's signature in the same body and performs create → sign → notify as a
single operation. Notifications are enqueued only after the write commits.

### 1.2 No idempotency

No `Idempotency-Key` anywhere in this module, while `documents_v2.py:47` and
the appointment booking path both require one. A double-click produces two
agreements.

**Action:** require `Idempotency-Key` on create, reusing
`_require_key` / `tx.validate_idempotency_key` from `documents_v2.py:47-56`
rather than writing a second scheme.

### 1.3 Sign and decline race

Signature write, audit append, classification `$set`, and status update are four
separate writes (`agreement_repo.py:34-63`; `agreement_service.py:253-283`).
Concurrent operations can interleave into contradictory records: a party signs
while another declines; two final signatures each fire the executed
notification; the audit append fails after the signature is stored.

**Action:** wrap each transition in a transaction. This deployment is
`mongodb+srv` (Atlas replica set) and `payment_service.py:364` already runs
`session.with_transaction` — **copy that pattern**. Do not design a
non-transactional fallback for a constraint this deployment does not have.

Every transition filters on its expected current status, so a lost race fails
cleanly instead of overwriting. Signing and declining become idempotent by
`(agreement_id, user_id)`.

### 1.4 The wizard discovers the template refusal four steps too late

`UNREVIEWED_MARKER` is defined at `ModAgreements.jsx:88` and used only to
*build* bodies — never to check one. The user picks a template, edits, selects a
counterparty, draws a signature, clicks "Sign & Send", and gets a red toast.

**Action:** block at step 0. Disable "Next" while the marker is present and
show the backend's own refusal text inline.

### 1.5 `body_html` is 300 KB of unsanitised HTML — SUPERSEDED by §1.1d

*Kept for the record. The conclusion below (run `nh3` on write) was wrong: the
body is plain text, and sanitising it as HTML would corrupt agreement wording
containing angle brackets — the same text whose hash is the evidence. Escape at
the rendering sinks instead.*

`nh3==0.3.7` is already a dependency and already used at
`document_service.py:959`, but not here. Both UIs currently render the body as
text (`whiteSpace: "pre-wrap"`), so there is no live XSS — the field *name* is
the trap, and §3.2's PDF export is exactly what makes it live.

**Action:** sanitise on write with the existing `nh3` allow-list, before the
PDF lands rather than after.

**Phase 1 gate:**
- A forced `signAgreement` failure leaves **no** row and sends no notification.
- Two concurrent signs produce one `executed` and exactly one executed notice
  per party.
- A concurrent sign and decline resolve to one terminal state, with an audit log
  a human can read.
- The same `Idempotency-Key` returns the same agreement id.
- A body containing the marker cannot leave step 0.

---

## Phase 2 — Gate 1: state map and design decision (ANALYSIS ONLY)

**Written 2026-09-20. Nothing implemented. Stops here for review.**

### 2.G1.1 The complete transition map, as the code actually behaves

Every arrow below was read off the source, not the docstrings.

**Engagement lifecycle** (`engagement_service`)

| From | Event | To | Case effect | Letter effect |
|---|---|---|---|---|
| — | `request_engagement` | `requested` | `open` → `pending_lawyer` | — |
| `requested` | `propose_terms` | `terms_proposed` | none (deliberate) | — |
| `terms_proposed` | `accept_terms` | `accepted` | claim: `lawyer_id` set, → `in_progress` | letter created **`pending`** |
| `terms_proposed` | `decline_terms` (client) | `declined` | `_reopen_case`: → `open` | — |
| `requested`/`terms_proposed` | `decline_engagement` (lawyer) | `declined` | `_reopen_case` | — |
| `requested`/`terms_proposed` | `cancel_engagement` (client) | `cancelled` | `_reopen_case` | — |
| `terms_proposed` | accept loses the case race | `cancelled` | — | — |
| `accepted` | `complete_engagement` | `completed` | → `closed`, **lawyer stays on the case** | — |
| `accepted` | `terminate_engagement` | `terminated` | released: `lawyer_id` → None, → `open` | — |

**Letter lifecycle** (`agreement_service`)

| From | Event | To | Engagement effect | Case effect |
|---|---|---|---|---|
| — | `create_pending_engagement_letter` | `pending` | — | — |
| `pending` | both parties sign | `executed` | **none** | **none** |
| `pending` | either party declines | `cancelled` | **NONE ← THE DEFECT** | **NONE** |

`decline_agreement` reads `engagement_id` nowhere. The field is written at
`agreement_service.py:142` and acted on by nothing.

### 2.G1.2 What the stranded state actually does to each consumer

Four consumers read engagement status. After a declined letter the engagement
is still `accepted`, so:

| Consumer | Reads | Result after a declined letter | Correct? |
|---|---|---|---|
| **Fee gate** `payment_service:106` | `status ∈ RETAINED` | engagement FOUND, letter `cancelled` ≠ `executed` → **refuses** | Refusal right, **message wrong** |
| **Review gate** `exists_accepted` → `lawyer_service:691` | `status ∈ RETAINED` | client **may review** a lawyer whose letter was refused | **No** — no agreed representation |
| **New request** `request_engagement:86` | `case.lawyer_id` | `ConflictError` — **client cannot engage anyone else** | **No** |
| **Unique index** `uniq_pending_engagement` | `status ∈ OPEN` | `accepted` not in OPEN, so no index conflict | n/a |

**The fee-gate message is the sharpest edge.** `payment_service:129` says *"the
engagement letter is still 'cancelled' — it must be signed by both you and the
client"*, and `submit_signature` refuses a `cancelled` agreement permanently.
The lawyer is instructed to do the one thing the system will never allow.

**Correction to the earlier write-up: the state is escapable.**
`terminate_engagement` accepts any `accepted` engagement from either party and
releases the case. So a stuck pair is not permanently trapped — but nothing
tells them, the fee-gate error points the wrong way, and escaping requires the
lawyer to "terminate" a representation that arguably never began. The defect is
a misdirection plus a wrong state, not an inescapable deadlock. That is less
severe than stated and should be reported that way.

### 2.G1.3 The required terminal state — decision needed

The new state must satisfy four constraints, all derived from §2.G1.2:

1. **NOT in `ENGAGEMENT_RETAINED_STATUSES`** — no signed letter means no agreed
   fee, so it must fall out of both the billing gate and the review gate.
2. **NOT in `ENGAGEMENT_OPEN_STATUSES`** — the negotiation is over, and adding
   it would make the `uniq_pending_engagement` partial index reject a fresh
   request on the same case.
3. **Terminal** — no transition out, like `declined` and `cancelled`.
4. **Distinguishable in audit** from "client declined the terms", because the
   cause and the timing differ.

Every existing terminal status already satisfies 1–3. Only 4 is open.

| Option | Cost | Assessment |
|---|---|---|
| **A. `declined` + `declined_by` / `decline_reason`** *(recommended)* | No enum change, no index change, no consumer change. Fields already exist and `decline_terms` already sets them. | Closest meaning: somebody refused. Widens `declined` to include post-acceptance refusals — low risk, no consumer distinguishes by timing. |
| **B. `cancelled` + `cancelled_reason`** | Same zero cost. | `cancelled` already carries two meanings (client withdrew; lost the case race). A third weakens it further. |
| **C. New `letter_declined`** | Enum value, both status tuples re-checked, index partial re-created, migration. | Most explicit, most expensive. §7.2 already argued against multiplying terminal states. |

**Recommendation: A**, with `declined_by: "lawyer"|"client"` and a distinct
`decline_source` of `"engagement_letter"` so reporting can separate the two
causes without a fifth state.

> **Corrected.** An earlier draft of this paragraph put the discriminator in
> `decline_reason`. That field holds the reason a PERSON typed and is rendered
> to the counterparty, so a sentinel there would either be shown to them or
> force every reader to know which values are prose. R2 is authoritative: the
> machine value lives in `decline_source`, the human text in `decline_reason`.

### 2.G1.4 Activation model — a revision of this plan's own §2

*(The comparison below is the ANALYSIS THAT REJECTED `awaiting_signatures`.
Option B is recorded so the reasoning survives, not as a live alternative.)*

The original §2 proposed an `awaiting_signatures` state: the engagement would
not become `accepted` until the letter executed. **Reading the code, that is
the more expensive and riskier of the two designs, and I no longer recommend
it.**

| | **Option A — reverse on decline** *(recommended)* | **Option B — `awaiting_signatures`** |
|---|---|---|
| `accept_terms` | unchanged | rewritten; its two-step atomic claim ordering is load-bearing and carefully argued |
| Case claim | at acceptance, as today | deferred until the letter executes |
| New race | none | **yes** — the case sits unclaimed while the letter is pending, so a second lawyer can take it mid-signature |
| Enum / index / gates | untouched | new value, both tuples, partial index, both gates |
| Window where case is claimed but letter unsigned | exists today, and the fee gate already refuses billing in it | eliminated |

The window Option B removes is **already safe**: the fee gate refuses billing
whenever the letter is not `executed`. Only the *decline* path is broken. Option
A fixes exactly that and leaves the atomic claim alone.

**Proposed rule (Option A):** a letter moving `pending` → `cancelled` moves its
engagement `accepted` → `declined` and releases the case
(`lawyer_id` → None, → `open`), reusing the rollback already written at
`engagement_service.py:366-380`. An `executed` letter is never touched by
anything.

> **NOT a Gate 2 rule.** "A terminated engagement voids a still-`pending`
> letter" appeared here as though it were part of this change. It is the
> OPPOSITE arrow — engagement→letter rather than letter→engagement — with its
> own authorization question (who may void, and does a client's termination
> cancel a lawyer's copy?). **Deferred to Phase 3.** Gate 2 implements
> letter→engagement only.

### 2.G1.5 Migration and cleanup for existing stranded records

**Current production scope: zero.** The census
(`scripts/engagement_letter_reconcile.py`, read-only) reports 0 retained
engagements and 0 engagements at *any* status. The 6 orphaned letters it found
are §2.0b — a different defect, out of Phase 2 scope, and not to be repaired by
this work.

The migration is still specified, because the scope is a property of this
database today and not of the code.

**Detection.** Engagements with `status ∈ RETAINED` whose `agreement_id`
resolves to an agreement with `status == "cancelled"`. `pending` letters are
counted but **not** reconciled — a pending letter may still be signed, and
retiring it is expiry (§C1), a separate decision.

**Classification before action.** For each hit, record `created_at`,
`created_by`, the case's current `lawyer_id`, and whether the case still
exists. Rows whose case is gone, or whose case has since been claimed by a
*different* lawyer, are reported and skipped — not repaired. A reconciliation
that clobbers a live reassignment creates the incident it was written to clear.

**Action per row.** Inside one transaction: engagement → `declined` with
`decline_source: "engagement_letter"` (and `decline_reason` carrying the human
reason from the letter's audit entry, or null), `declined_by` taken from that
same entry; case released only when it is still held by *that* lawyer; both
parties notified through the outbox, parked in the same transaction.

**Idempotency.** Every write conditional on the state the census observed, so a
second run matches nothing. A row that moved in between is skipped, not forced.

**Never touched.** `executed` letters, in any circumstance. Cases held by
another lawyer. Anything in §2.0b.

**Reporting.** Before and after counts, both stated even when zero — "we fixed
it before anyone hit it" is only credible if the looking is on record.

### 2.G1.6 Open questions — ALL ANSWERED 2026-09-20

1. **Terminal state** — ✅ Option A. Reuse `declined`; no new status. (R1)
2. **Activation model** — ✅ Option A. Reverse on decline; `awaiting_signatures`
   rejected and every instruction for it voided. (R4)
3. **Review rights** — ✅ Removed. Eligibility now requires an **executed**
   letter, which is stricter than the mechanical consequence of R1: an accepted
   engagement whose letter is merely *pending* is also not reviewable. No
   representation was agreed until both parties signed. (R5)
4. **Fee-gate copy** — ✅ Four state-specific messages, in §2.G2.3. It must NOT
   point at `terminate_engagement`: after the automatic reversal that
   transition is neither available nor needed. (R6)

---

## Phase 2 — The engagement desync

**Estimated 2 days. This is producing broken states in the current build.**

`decline_agreement` never reads `engagement_id`. The field is written at
`agreement_service.py:142` and acted on nowhere.

Today's sequence:

1. Client accepts terms → engagement `accepted`, case assigned to the lawyer,
   engagement letter created `pending`.
2. Either party declines the letter → agreement `cancelled`.
3. Engagement **stays `accepted`**. The case stays assigned. The lawyer stays on
   the matter.
4. The lawyer tries to bill → `payment_service.py:129` refuses with
   *"the engagement letter is still 'cancelled' — it must be signed by both you
   and the client"*.

`cancelled` is terminal: `submit_signature` refuses it permanently. The error
instructs the lawyer to do the one thing the system will never allow. There is
representation without an engagement letter, no way to invoice, and no state
that explains it.

### The rule to enforce — APPROVED 2026-09-20

> **SUPERSEDED: `awaiting_signatures`.** An earlier draft of this section
> proposed deferring activation — acceptance would move the engagement to a new
> `awaiting_signatures` state and the case would not be claimed until the letter
> executed. **That design is rejected.** It would rewrite `accept_terms`, whose
> two-step atomic claim ordering is load-bearing, and it introduces a race the
> current code does not have: the case sits unclaimed while the letter is
> pending, so a second lawyer can take it mid-signature. The window it removes
> is already safe, because the fee gate refuses billing whenever the letter is
> not `executed`. Only the DECLINE path was ever broken.
>
> Every `awaiting_signatures` instruction elsewhere in this document is void.
> The rules below are the approved ones.

**R1 — Reuse `declined`.** No `letter_declined` status is added. Every existing
terminal status already satisfies the three mechanical constraints (not in
`RETAINED`, not in `OPEN`, terminal); only audit distinguishability was open,
and fields solve that more cheaply than an enum value plus an index rebuild.

**R2 — Metadata written on the reversal.**

| Field | Value |
|---|---|
| `declined_by` | `"client"` or `"lawyer"`, from comparing the requester against the engagement's own ids |
| `declined_at` | server time of the transition |
| `decline_source` | `"engagement_letter"` — the machine discriminator |
| `decline_reason` | the human reason the decliner typed, or null. **Never a sentinel** — it is shown to the other party |
| `declined_agreement_id` | the letter that was refused |

`decline_source` and `decline_reason` are deliberately separate fields. Putting
a machine sentinel in `decline_reason` would either be rendered to a person or
force every reader to know which values are real prose.

**R3 — The accept-terms case claim is unchanged.** It stays exactly as written.

**R4 — A declined pending letter reverses the engagement**, in one transaction:

- agreement `pending` → `cancelled`
- engagement `accepted` → `declined`, with the R2 metadata
- case `lawyer_id` → null **only if still assigned to that engagement's lawyer**
- case status → `open`

**R5 — Review eligibility requires an EXECUTED engagement letter.** An accepted
engagement whose letter is still pending is not yet a reviewable relationship.

**R6 — Never instruct the user to terminate.** The reversal is automatic, and
after it `terminate_engagement` is neither available (the engagement is no
longer `accepted`) nor necessary. Earlier copy that pointed there is removed.

**R7 — The six orphaned letters stay out of scope** (§2.0b). Not deleted, not
modified, not repaired by this work.

**R8 — Reconciliation `--apply` stays disabled.** The census found zero
engagements at every status, so there is nothing to reconcile and no reason to
ship a mutating path.

**Unchanged from the earlier draft, and still true:** an `executed` letter is a
historical record and is never touched, whatever later happens to the
engagement.

**A terminated engagement voiding a still-pending letter is a PHASE 3 arrow**,
not a Gate 2 rule and not an R1–R8 obligation. It runs engagement→letter, the
opposite direction to everything here, and raises its own authorization
question. Gate 2 implements letter→engagement only; nothing in this phase
inspects an engagement's termination to act on its letter.

`ENGAGEMENT_RETAINED_STATUSES` and the fee gate's "ended engagements still
count" reasoning (`payment_service.py:100-105`) are unaffected by R1–R8: no
status joins or leaves either tuple. What changes is that the fee gate now
distinguishes *why* a letter is not executed, and that review eligibility reads
the letter rather than the engagement alone.

### 2.0 Census result — run 2026-09-20 ✅

`scripts/engagement_letter_reconcile.py`, read-only, `--apply` disabled.

```
Retained statuses scanned    : accepted, completed, terminated
Retained engagements scanned : 0
Engagements, ALL statuses    : 0
STRANDED (reconcilable)      : 0
ORPHANED LETTERS             : 6   <-- new finding
  of which: 6 with a deleted case, 0 with a live case
```

**No lawyer is stranded.** The §2.1 defect is real but has not been triggered.

**That result is weaker than it looks, and the report now says so itself.** The
engagements collection is empty at *every* status, so the forward scan had
nothing to scan — it could not have found the defect even if it were occurring.
"Clean" here means **unexercised**, not verified safe.

> **Method note.** The first version of this census printed a narrative wider
> than its own queries: it checked only that the engagement was missing, yet the
> write-up asserted the cases were gone too and that there were zero engagements
> at any status. Both happened to be true, but from separate ad-hoc queries the
> checked-in script never ran. The script now performs the case lookup
> (`case_exists`, explicitly tri-state) and the all-status breakdown, so every
> line of the report is backed by something it measured. **A census that
> narrates beyond its evidence is the same failure class as the AES-256 claim.**

### 2.0b NEW DEFECT — orphaned engagement letters

The census's reverse check found **6 engagement letters whose engagement row no
longer exists**, and — verified by explicit lookup — whose case is gone in all
six cases. One is `executed`: a signed instrument referring to an engagement and
a case that have both been deleted.

**Classification.** All six were created on **2026-08-24 between 02:19 and
03:19 UTC**, each by a different `created_by`. A one-hour window with six
distinct creators is the shape of a seed or test run, not of real retained
records — but that is an inference, not a verdict, and the ids are recorded so
it can be settled rather than assumed. Confirm against the seed scripts before
any cleanup decision.

This is **not** the stranded-engagement defect. It is its mirror image: nothing
deletes an agreement when its engagement or case is deleted, so agreement rows
outlive the things they describe. The forward scan is structurally blind to it —
there is no engagement left to walk from — which is why the reverse check exists.

Reported, deliberately **not repaired**. Deleting a signed agreement is not a
decision a reconciliation script makes on its own, and an orphaned `pending`
letter is still evidence of what somebody was asked to sign. Track as its own
item, to be scheduled with the retention work rather than folded into Phase 2.

### 2.1 Census first, then reconciliation

The rule above governs **new** data only. Every engagement already stranded by
this defect stays stranded, and a target of "zero stranded cases" is meaningless
without the starting number.

**Step 1 — read-only census, run before any code changes.** Count engagements in
a retained status whose linked agreement is not `executed`, grouped by agreement
status (`cancelled`, `pending`, missing entirely). Each row is a lawyer who may
be unable to invoice today.

**Step 2 — reconciliation script. SPECIFIED, NOT SHIPPED.** `--apply` is
disabled and stays disabled: the census found **zero engagements at every
status**, so there is nothing to reconcile and no reason to carry a mutating
path (R8).

Were it ever needed, it would apply the same rule the live code applies: move
the engagement `accepted` → **`declined`** — not `cancelled`, per R1 — with the
R2 metadata, release the case only when it is still held by that engagement's
lawyer, and notify both parties through the outbox.

**Only `cancelled` letters are in scope.** A `pending` letter is counted by the
census and **not reconciled**: it may still be signed, and retiring one is
expiry (§C1), a separate decision with its own approval. Executed letters are
never touched.

**Name it `scripts/engagement_letter_reconcile.py`.** Do **not** name it
`agreement_report.py` — that already exists and is the *annotator* agreement
report, the same collision that makes `test_agreement.py` misleading. Do not add
a third.

Report the census number whichever way it comes out. Zero affected rows means
the defect was real but never triggered, which is a result worth stating, not a
reason to say nothing.

**Phase 2 gate:** declining an engagement letter moves its engagement to
`declined` and releases the case when that engagement's lawyer still holds it;
the lawyer is told why, in copy matched to what actually happened; a completed
engagement whose letter was executed can still be billed; and the census
reports **zero stranded rows with `--apply` never run** — nothing was
reconciled, because there was nothing to reconcile.

---

## Phase 3 — Gate 1: design and code survey (ANALYSIS ONLY)

**Written 2026-09-20 against the tree at `b506a00`. NO BEHAVIOR IMPLEMENTED.**
No backend, frontend, schema, migration or test file was changed for this gate;
only this document. Every line reference below was re-read from the current
files rather than carried over from earlier drafts.

### 3.G1.1 Reverse lifecycle arrow — termination with a pending letter

**Verified current behaviour.** `terminate_engagement`
(`engagement_service.py:759`) requires `status == accepted` (`:776`), sets
`terminated` with `terminated_at` / `terminated_by` / `termination_reason`
(`:789`), releases the case with a filter scoped to that lawyer (`:801-805`),
and writes a milestone (`:812`). **It never reads or writes the agreement.** So
a termination while the letter is `pending` leaves that letter pending forever.

**Severity: low, unlike the Gate 2 defect.** The residue is inert — the fee gate
already refuses a non-executed letter, and the case is released by `:801`. This
is tidiness, not a stuck state, and must not be argued for as though it were.

**Who may terminate / who is recorded.** Unchanged: either party, no handshake
(`:768-771`), with `_party_of` deciding the actor. The letter-void actor must be
that same value — the engagement is authoritative about who is involved, and
re-deriving it from the agreement's party list could disagree.

**Pending letter outcome — recommend `cancelled`, not a new value.** The letter
never became binding, so `cancelled` is exactly right; it is already terminal,
already non-executed to the fee gate, and already rendered as "Rejected" by both
UIs. A `withdrawn` value would need a fifth status for no observable difference.
Distinguish the cause in fields, using the ONE cancellation model defined in
§3.G1.10. **No enum change.**

**Executed letters stay immutable.** The void must filter on
`status == pending`; an executed letter simply does not match, and the
engagement ends as `terminated` — a properly formed relationship that later
ended, which is not a letter-derived state.

**Transaction boundary.** One transaction spanning: engagement → `terminated`
(conditional on `accepted`), case release (conditional on that lawyer), case
milestone, agreement → `cancelled` (conditional on `pending`) **plus its audit
entry with `body_sha256`**, and the outbox park. Today's four writes at
`:789`–`:812` are **not** transactional — see §3.G1.7 B1.

**Notifications.** The non-terminating party, as now. Copy must not say the
letter was "declined": nobody refused it. *"The engagement was ended by the
{party}, so the engagement letter is no longer awaiting signature."*

**Concurrency.**
- *Termination vs first signature* — both may commit; the letter is still
  `pending`, so the void wins and the signature is discarded with it. Acceptable.
- *Termination vs final signature* — the dangerous one. If the signature commits
  first the letter is `executed` and the void must match nothing; the
  `status == pending` filter is the guarantee, not a pre-read.
- *Duplicate termination* — the `accepted` filter already makes the second a
  no-op; the void must be gated on the same `modified_count` so it cannot fire
  twice.

**Verdict: existing statuses suffice.** No new status for this arrow.

### 3.G1.2 Lawyer agreement authoring — PRIMITIVES IMPLEMENTED (gate 3B)

**2026-09-20.** The authorization primitives are built; the ROUTE and UI are
still 3D, so nothing external can reach lawyer authoring yet.

- `create_lawyer_agreement` — Product C's producer. Deliberately does **not**
  read `agreements_diy_builder_enabled`: reading Product B's flag would tie the
  two together again, which is what parking existed to prevent. Test:
  `test_lawyer_authoring_is_not_gated_by_the_parked_builder_flag`.
- `_require_verified_lawyer` — D5, callable at create **and** send.
- `_require_case_relationship` — D2 rules 3-6, distinct message per failure.
- `_authorise_case_link` — used by every producer carrying a `case_id`.
- `_create_agreement` now refuses an agreement with **no case and no
  engagement**, and refuses more than two parties.
- `case_id` plumbed schema → route → service → persistence;
  `AgreementCreate` gains `extra="forbid"` so an unknown field is a 422 rather
  than silently dropped.

**EVERY GUARD WAS PROVED ABLE TO FAIL** — disabled one at a time, its test
required to go red, then restored and required to go green. That exercise found
a real gap: `_authorise_case_link`'s `outsiders` check had NO test, because the
case-relationship test reaches it through `create_lawyer_agreement`, which
refuses earlier. A guard whose test cannot go red is decoration;
`test_a_party_who_is_not_on_the_case_is_refused` now drives the shared
implementation directly.

**Not in this gate, by instruction:** rate limits (D6), draft cap (D7),
trusted-proxy/IP (D8).

#### Original analysis, for the record

**Backend capability already exists; the UI does not.**
`POST /agreements` (`agreements.py:15-18`) depends only on `get_current_user` —
no role guard. `AgreementsPage.jsx:8` imports only `listAgreements`,
`signAgreement`, `declineAgreement`.

**Authorization today is insufficient, and this is the gate's main security
finding.** `_create_agreement` (`agreement_service.py:331-335`) validates only
that every `party_id` resolves to a registered user, plus ≥2 parties. There is
**no relationship check and no rate limit**, so any authenticated user can name
any `user_id` and push an `AGREEMENT_CREATED` notification at them.

Mitigated today only by the park flag: `create_user_agreement` refuses while
`agreements_diy_builder_enabled` is false. **Unparking without fixing this
re-opens it**, so the relationship rule is a prerequisite for §3.1, not a
companion to it.

**Defining "client" — NARROWED BY DECISION.** This gate recommended *"an
executed engagement, OR an active assigned case"*.

> **SUPERSEDED by product decision D2** (`AGREEMENTS_PRODUCT_PLAN.md` §3). Only
> the case-based limb survives. **A historical executed engagement is not
> permission to contact someone** — it would let a lawyer reach a client years
> after a finished matter, which is cold outreach with extra steps. The
> `exists_executed_relationship` helper stays where it belongs, gating REVIEWS;
> it is not an authoring credential.

The implemented rule is D2's: lawyer authoring only; exactly two parties;
mandatory `case_id`; the case exists; `case.lawyer_id == authenticated lawyer`;
`case.client_id == selected client`.

**Plus D5, decided 2026-09-20: the lawyer must be KYC-verified, checked at BOTH
create and send.** Two checkpoints because they are separated in time — a draft
authored while verified may be sent after an admin revokes that verification
(`user_service.py:312` clears `kyc_verified`). Checking only at create lets a
de-verified lawyer send a binding instrument; checking only at send lets them
build drafts they can never use. The existing helper at `lawyer_service.py:359`
reads the same field the five precedent surfaces read.

**`case_id` selection and validation.** The lawyer picks from their own assigned
cases; the server re-validates that `case.lawyer_id == creator`. Never trust the
submitted id. `_create_agreement` already accepts `case_id` but
`agreements.py:23-25` does not pass it — see §3.G1.7 B2.

**Interaction with the parked builder.** Lawyer authoring must NOT reuse
`create_user_agreement`: that function is gated by design. A third named
producer — `create_lawyer_agreement` — keeps the client wizard parked while the
lawyer path ships. Withdrawn templates are irrelevant here: a lawyer supplies
their own wording, and `is_unreviewed_template` still guards the marker.

### 3.G1.3 Draft/send lifecycle — IMPLEMENTED (gate 3C)

**2026-09-20.** `draft` is reachable at last: it was declared in the enum and
written by nothing.

- `create_draft` / `update_draft` / `delete_draft` / `sign_and_send_draft`,
  routed at `POST|PATCH|DELETE /agreements/drafts[/{id}]` and
  `POST /agreements/drafts/{id}/send`. **Product C is now reachable.**
- **Versioning**: drafts start at 1; every edit `$inc`s it; `PATCH` requires
  `expected_version` and a stale write is a 409, never a silent merge.
- **Sign-and-send is ONE call and ONE transaction**: freeze body, verify the
  reviewed digest, capture signature + explicit consent, audit, transition,
  park the outbox event, write the idempotency receipt. Fails closed.
- **`body_sha256` is null on a draft** and stamped only at send. The digest is
  the record of what was SIGNED; stamping a mutable draft would invite reading
  it as evidence.
- **Idempotency**: key scoped by actor and operation, stored with a canonical
  fingerprint binding draft, version, body hash, parties, case, signature hash
  and consent. Same key + same payload replays; different payload is 409.
- **D5 and D2 re-checked at SEND**, not inherited from create — verification
  can be revoked and a case reassigned in between.
- **D6**: `10/hour` on send only. Autosave `PATCH` is deliberately unlimited.
- **D7**: `MAX_ACTIVE_DRAFTS_PER_LAWYER = 20`, counting `draft` rows only.
- Sent agreements refuse edit and delete.

**All nine guards proved able to fail** — disabled one at a time, each test
required red, then restored and required green, with both source files verified
byte-identical afterwards.

**Still NOT gated by `agreements_diy_builder_enabled`**, tested explicitly. The
client wizard stays parked.

#### Original design, for the record

**`AgreementStatus.DRAFT` is declared (`constants.py:113`) and unreachable.**
The only writer is `models/agreement.py:31`, a Pydantic model nothing persists
through. Creating is currently sending.

**Recommended state machine — four live states, no new terminal values:**

```
draft ──send──► pending ──all sign──► executed        (terminal, immutable)
  │                │
delete          ├──counterparty declines──► cancelled (terminal)
(row removed)   ├──creator withdraws──────► cancelled (terminal)
                └──deadline passes────────► cancelled (terminal)
```

`withdrawn` and `expired` are **fields, not statuses** — carried in
`cancellation_source`, per the single model in §3.G1.10. This is the §7.2
argument applied again: three terminal values already carry every distinction
consumers need, and each new one is a migration plus a branch in every reader.

**Operations.** `POST /agreements/drafts` (create), `PATCH .../drafts/{id}`
(update, draft-only), `DELETE .../drafts/{id}` (creator-only, draft-only),
`POST .../{id}/send`. Send is where `body_sha256` is computed and frozen.

**Immutable after send:** `body_html`, `body_format`, `body_sha256`, `parties`,
`case_id`, `engagement_id`. A `PATCH` against a non-draft must 409.

**Idempotency.** `Idempotency-Key` on create and on send, using
`documents_v2.py:47`'s validator — the mechanism Phase 1 adopted. A concurrent
update-and-send is resolved by the send's `status == draft` filter: the update
either lands before the freeze or is refused.

**Withdraw vs decline.** Separate *operations* with separate audit actions and
separate notification copy, converging on one status. Gate 2 already proved the
notice must match the actor.

### 3.G1.4 Case linkage and timeline

**Validation.** `case_id` must exist and the creator must be a party to it
(`client_id` or `lawyer_id`). `engagement_id` may only be set by the internal
producer (`create_pending_engagement_letter`), never from a request body — that
is what Gate 2's backlink check assumes.

**Milestone writers today:** `engagement_service.py:420` (engaged), `:740`
(completed), `:812` (terminated); `agreement_service.py:863` (letter declined,
release-gated); `case_service.py:357` (lawyer-only, **no UI calls it** — see
§3.G1.7 I1). Phase 3 adds at most two: *letter sent* and *letter executed*.

**Case deleted / reassigned / closed / released.** Gate 2's answers extend
unchanged: a missing case is broken linkage and aborts; a reassigned case is
never written to; a closed case still accepts an executed record. A released
case is the normal post-decline state.

**Generic case-linked agreements: yes, allowed** — a retainer for a matter with
no engagement is legitimate. `engagement_id` stays null, so Gate 2's reversal
never triggers. The two links are independent and must stay so.

### 3.G1.5 Executed PDF and signature evidence

**Route.** `GET /agreements/{id}/pdf`, parties-only, `status == executed` only.
Follow `documents.py:174`'s `FileResponse` pattern.

**Evidence available today:** `body_sha256` (row + every audit entry),
`actor_id`, `timestamp`, `ip_address`, `signature_method`, per-party
`eto_classification`, and the raw `signature_data`.

**Missing today:** a version/revision number, an explicit consent
acknowledgement, session/authentication assurance, user-agent, and a download
audit event.

**Signature rendering without JSON exposure.** Already correct and must stay:
`agreement_service.py:415` strips `signature_data` from the list path, and
`PartyOut` (`schemas/agreement.py:42`) omits the field so it cannot serialise.
The PDF renderer must read the blob **server-side from the row**, never via the
API models. *(Note: `PartyOut`'s docstring says "STRICT (no extra)" but the class
sets no `model_config`; the effect is right by omission, not by strictness —
§3.G1.7 I2.)*

**Canonical hash.** The PDF must print the same `body_sha256` the row holds, and
`normalise_body` guarantees it is platform-stable. With drafts, the hash is
frozen at **send**, and the PDF must cite the sent version.

**Trusted proxy / IP.** `request.client.host` behind a proxy records the proxy.
A `trusted_hosts` / `X-Forwarded-For` policy is needed **before** an IP appears
on an evidence certificate, or the document asserts a false fact.

**Download audit + metric.** One event per download (agreement id, requester,
timestamp) — this is the only way the product plan's adoption metric (% of
executed agreements downloaded) becomes reportable.

**Facts, not conclusions.** The certificate states what was recorded. It must
not assert enforceability; that wording is Phase 4.1, counsel-gated.

### 3.G1.6 Dependency-ordered implementation gates

| Gate | Scope | Depends on | Files likely to change | Migration / index | API contract | Tests |
|---|---|---|---|---|---|---|
| **3A** | Reverse arrow (§3.G1.1) | Gate 2 only | `engagement_service.py`, `agreement_service.py` | none (fields only) | none | backend: void, executed-immutable, 3 concurrency cases, duplicate terminate |
| **3B** | Authorization + `case_id` wiring (§3.G1.2, §3.G1.4) | — | `agreements.py`, `agreement_service.py`, `schemas/agreement.py` | none | **breaking**: unrelated `party_ids` now 403 | backend: relationship matrix, case-party validation, rate limit |
| **3C** | Draft/send lifecycle (§3.G1.3) | 3B | routes, service, schemas, `constants.py` | index on `(created_by, status)` | **additive**: 4 new endpoints | backend: state machine, immutability-after-send, idempotent send, concurrent update/send |
| **3D** | Lawyer authoring UI | 3B, 3C | `AgreementsPage.jsx`, `lib/api.js` | none | none | frontend: counterparty scoping, draft editing |
| **3E** | PDF + evidence (§3.G1.5) | 3C (version), 3B | new `agreement_pdf.py`, routes | download-audit collection | **additive** | backend: authz, hash match, no blob in JSON, audit row |
| **3F** | Chores | — | pagination, rate limit, delete `models/agreement.py`, rename `test_agreement.py` | none | pagination is **breaking** for list | regression |

**3A and 3B are independent and both reviewable alone.** 3B is the security
gate and should go first if only one ships.

### 3.G1.7 Defects found during inspection

**Blockers for the items that depend on them:**

- **B1 — `terminate_engagement` is not transactional.** Four separate writes at
  `engagement_service.py:789-812`. A crash between them leaves an engagement
  `terminated` with the case still assigned — the mirror of the Gate 2 defect,
  in code Gate 2 did not touch. **Must be fixed as part of 3A**, not after.
- **B2 — the create route drops `case_id`.** `agreement_service._create_agreement`
  accepts it; `agreements.py:23-25` never passes it, so every wizard-created
  agreement is unlinked. Prerequisite for 3B/3C.
- **B3 — no relationship check or rate limit on create** (§3.G1.2). Masked by
  the park flag; unparking without this re-opens arbitrary-user notification.

**Improvements, explicitly NOT Phase 3 scope expansion:**

- **I1** — `case_service.add_milestone:357` is lawyer-only and reachable from no
  UI; the lawyer cannot curate the timeline the client reads.
- **I2** — `PartyOut`'s "STRICT (no extra)" docstring describes a `model_config`
  the class does not set. No leak today; fix the comment or set `extra="forbid"`.
- **I3** — `AgreementStatus.DRAFT` and `models/agreement.py` are dead. 3C uses
  the former; the latter should be deleted (3F).

### 3.G1.8 Decisions requiring approval before implementation

1. ~~**"Client" definition** — executed engagement **or** active assigned
   case?~~ **CLOSED — decided as D2**: the case-based test only. A historical
   executed engagement grants nothing.
2. **Withdraw/expire as fields, not statuses** — confirm, keeping three terminal
   values.
3. **Case-linked generic agreements** — allowed, as recommended?
4. **Rate limit** on create: `10/hour` per creator, matching the earlier §3.8
   proposal?
5. ~~**Trusted-proxy policy** — needed before any IP reaches a PDF.~~
   **CLOSED 2026-09-21 as D8**: `X-Forwarded-For` is trusted ONLY when the
   immediate peer is a configured proxy address. If the client IP cannot be
   verified under that rule, it is OMITTED from the evidence document rather
   than printed with a caveat. An unverifiable IP on an evidence document is a
   false assertion of fact; saying nothing is the only honest alternative, and
   the document already states what it does not record.

### 3.G1.9 Risks and migration implications

- **3B is a breaking API change.** Existing rows with unrelated parties stay
  readable; only new creates are refused. No data migration, but any client
  relying on arbitrary `party_ids` breaks — none exists today, because the only
  caller is parked.
- **3C touches the status field's meaning.** Adding `draft` makes a previously
  unreachable value reachable; every reader filtering `status == pending` must
  be re-checked, including Gate 2's reversal and both gates.
- **Phase 1's "no leftover row" test must be re-asserted** once drafts exist —
  already flagged in the Phase 1 matrix, and 3C is the moment it comes due.
- **3E's evidence certificate is partly counsel-gated** (Phase 4.1). Ship the
  factual document; leave legal characterisation out.

**No behavior was implemented for this gate.** The only file changed is this
one.

---

### 3.G1.10 ONE cancellation metadata model

Earlier drafts used `void_source` in one place and `cancelled_reason` in
another. **Both are withdrawn.** One model, used everywhere:

| Field | Type | Meaning |
|---|---|---|
| `status` | enum | Stays **`cancelled`**. No new terminal status, ever, for any of these causes. |
| `cancellation_source` | enum | Machine-readable: `declined`, `withdrawn`, `expired`, `engagement_terminated` |
| `cancellation_reason` | string, optional | Human prose, shown to the counterparty. **Never a sentinel.** |
| `cancelled_at` | datetime | Server time |
| `cancelled_by` | user id, **nullable** | Null for system actions (expiry) |

`cancellation_source` and `cancellation_reason` stay separate for the reason
Gate 2 established: one is read by code, the other by a person.

**COMPATIBILITY — Gate 2 already stores different field names.** The shipped
reversal writes `declined_by`, `declined_at`, `decline_source`,
`decline_reason`, `declined_agreement_id` on the ENGAGEMENT
(`agreement_service.py:816-824`). Those are not the names above.

Consequences, stated plainly:

- **No consumer may assume `cancellation_source` is always present** until a
  backfill decision is made and executed.
- A reader wanting "why was this cancelled" must, for now, handle both shapes.
- **This pass does NOT implement the migration.** The decision — backfill,
  dual-read, or adopt-forward-only — is owner-level and belongs with the gate
  that first needs it (3C).

The engagement-side fields and the agreement-side model are different records
and need not be unified; only the AGREEMENT adopts the table above.

### 3.G1.11 Rate limiting at the abuse boundary

An earlier note put the limit on *create*; another left it to chores. Resolved:

**The abuse boundary is SIGN-AND-SEND**, because that is the operation that
causes a notification to reach another human. Creating or editing a private
draft harms nobody.

| Operation | Limit | Why |
|---|---|---|
| `POST .../{id}/send` | **`10/hour`** per authenticated user *(starting point, decision D6)* | Reaches another person |
| `PATCH .../drafts/{id}` | **no limit** | Autosave; throttling it loses the lawyer's work |
| `POST /agreements/drafts` | active-draft **cap**, not a rate limit *(decision D7)* | Bounds storage without blocking a burst of legitimate drafting |

**Infrastructure verified.** `core/rate_limit.py:52` constructs a SlowAPI
`Limiter` with `key_func=_user_or_ip` (`:8`) — already per-authenticated-user,
with an IP fallback. The decorator pattern is in use at
`appointments.py:45,122,257` and `intake.py:40,46`. No new infrastructure; the
final placement is confirmed against this when 3C lands.

### 3.G1.12 Automated expiry — deferred to its own gate

`cancellation_source = "expired"` is **reserved in the enum and nothing more.**

Expiry is NOT part of 3C and must not be described as ready. Before it can be
built it needs, at minimum: an `expires_at` field; a decision on **who sets it**
(sender at send time, a system default, or both); a scheduler or worker to sweep
it; conditional transition semantics (`pending` → `cancelled` only); audit and
outbox rows like every other transition; replay safety so a restart cannot
re-expire or double-notify; and tests.

The appointment expiry work is the precedent — including its hard lesson that a
sweep and its guard must ship behind **one** flag, or a half-enabled state
becomes reachable.

### 3.G1.13 Gate order, corrected

**3A precedes 3B, and the reason is exposure, not severity of concept.**

- **3A is live today.** `terminate_engagement` (`engagement_service.py:759`)
  runs four non-transactional writes (`:789`, `:801`, `:812`) on a path any
  party can invoke right now. A crash between them leaves an engagement
  `terminated` with its case still assigned — the Gate 2 defect's mirror, in
  code Gate 2 did not touch.
- **3B's defect is masked.** Unauthorized create is real
  (`agreement_service.py:331-335`) but unreachable: `create_user_agreement`
  refuses while the builder is parked. It becomes live the moment authoring
  ships — which is why 3B must precede 3D, and why 3D is the first
  externally-visible change.

Final order: **3A → 3B → 3C → 3D → 3E → 3F**, with automated expiry as a
separate later gate. 3A and 3B remain independently reviewable.

### 3.G1.14 Termination safety invariants (gate 3A)

**Termination is a SAFETY EXIT and must never be blocked by the agreement
side.** A client wanting out of a representation cannot be held there because a
letter row is missing, corrupt or superseded. This inverts Gate 2's rule, and
the inversion is deliberate: declining is an action *about* the letter, so a
broken letter link aborts it; terminating is an action about the *engagement*,
so a broken letter link must not.

Invariants:

1. One transaction covers: engagement `accepted` → `terminated`; conditional
   case release; **release-gated** milestone; audit entry; durable outbox park;
   and conditional cancellation of the correctly-linked pending letter.
2. **Executed letters are never modified.** The letter update filters on
   `status == pending`; an executed letter matches nothing.
3. **Missing or superseded letter linkage does not block termination.** It
   completes and records an anomaly (logged, and a field on the engagement) so
   the orphan is discoverable rather than silent.
4. A case already unassigned or reassigned is **not mutated** — no field, no
   milestone. Reuse Gate 2's structured case disposition (`released` /
   `reassigned` / `already_unassigned`).
5. **Messages must not say the case is open when it was not released.** Same
   rule, same reason, as Gate 2's notice.
6. **Replace the direct `_notify` call with a transactional outbox park.**
   `terminate_engagement:820` currently notifies directly. Adding a park beside
   it would double-send; the direct call is removed, not supplemented.

### 3.G1.15 Draft concurrency and atomic sign-and-send (gate 3C)

> **SUPERSEDED AS A TARGET MODEL, 2026-09-21** — by **DG-04** in
> `AGREEMENTS_PRODUCT_PLAN.md` §11: immutable versions are required, with no
> exception for lifecycle Steps 4/5/7. Everything below remains an ACCURATE
> description of the code shipped at gate 3C — `expected_version`, the `$inc`
> counter and the 409-on-stale-write are all real and still in force. What is
> superseded is the assumption that an optimistic-concurrency counter is the
> whole version story: editing still overwrites the prior body, and the
> decision requires that it stop doing so. Not yet implemented.

**Phase 3 must not repeat the parked wizard's two-call create-then-sign
design** (`ModAgreements.jsx:1051-1066`), which could leave a pending agreement
its creator never signed.

**Versioning.**

- Drafts carry an integer `version`, starting at **1**.
- `PATCH` requires `expected_version`.
- Its conditional update filters on `{_id, status: draft, version:
  expected_version}` and `$inc`s the version.
- A stale write matches nothing → **409**, never a silent overwrite.

**SIGN-AND-SEND is one call and one transaction.** It requires
`expected_version` **and** `expected_body_sha256`, and in a single transaction:

1. freezes the reviewed body, parties and case linkage;
2. verifies the hash matches what the signer actually reviewed;
3. captures the creator's signature and an explicit consent acknowledgement;
4. writes the audit entry;
5. transitions `draft` → `pending`;
6. parks notifications;
7. creates or replays the idempotency receipt.

The hash check is the point: without it a concurrent edit could be signed
unseen.

**The internal producer keeps its own path.** `create_pending_engagement_letter`
still creates an UNSIGNED pending letter — a different system flow with a
different contract (Phase 1 §1.1c). Sign-and-send must not absorb it.

**Durable idempotency.**

- Key scoped to **actor + operation**.
- Stored with a canonical payload **fingerprint**.
- Same key + same fingerprint → **replays the committed result**.
- Same key + different fingerprint → **409**, never a silent alias.
- The fingerprint binds: draft id, expected version, body hash, parties, case
  id, signature payload (or its hash), and the consent fields.

### 3.G1.16 Executed document and evidence (gate 3E)

**MAY include:** the agreement body; the immutable version and `body_sha256`;
party and signer identities; signature capture method (`canvas` / `typed` /
`image_upload`, as neutral description); server-recorded timestamps; and neutral
audit facts.

**MUST NOT include:** legal enforceability conclusions; ETO "advanced
signature" classifications (Phase 4.1, counsel-gated); **IP-address evidence
until trusted-proxy handling is configured and tested** (decision D8 — without
it the document may assert the proxy's address as the signer's); or raw
signature data in ordinary agreement/list API responses.

**Raw signature material stays server-side.** It is read from the row by the
renderer and exposed only through the narrowly-authorized executed-document
path. The existing protections stay: stripped at `agreement_service.py:415`,
and absent from `PartyOut` (`schemas/agreement.py:42`) so it cannot serialise.

**Every successful download writes an audit event** (agreement id, requester,
timestamp). The product plan's adoption metric has no other source.

---

## Phase 3 implementation contract

**Invariants an implementation must not violate.** If a change requires
breaking one, it needs a plan amendment first, not a workaround.

1. **Executed agreements are immutable.** No later event modifies one.
2. **No new terminal status.** `cancelled` plus `cancellation_source`.
3. **Never write another lawyer's case.** No field, no milestone, no status.
4. **Never claim a case is open unless it was actually released** in that
   transaction.
5. **One transaction per cross-domain transition**, with the outbox park inside
   it, and fail closed where transactions are unavailable.
6. **Conditional filters carry the whole precondition.** A pre-read is never
   the guarantee.
7. **Authorization is re-asserted inside the transaction**, on rows read with
   that session — never inherited from a caller's preflight.
8. **`engagement_id` is never accepted from an external caller.**
9. **`case_id` is mandatory for lawyer-authored agreements**, and validated as
   `case.lawyer_id == creator` and `case.client_id == counterparty`.
10. **Exactly two parties** for lawyer-authored agreements.
11. **Termination is never blocked** by a missing or superseded letter link.
12. **No two-call create-then-sign.** Sign-and-send is one atomic call.
13. **Raw signature data never appears** in ordinary JSON responses.
14. **No UNVERIFIED IP on an evidence document** (D8, closed 2026-09-21). An
    IP appears only when the immediate peer is a configured trusted proxy, or
    when there is no proxy in front at all. Otherwise the field is omitted.
15. **No legal or enforceability claim** without counsel-approved wording.
16. **Phase 3 must not unpark Product B.** Lawyer authoring uses its own
    producer and never reads `agreements_diy_builder_enabled`.
17. **A durability mechanism is not finished until something reads it back**
    — the §1.1g lesson.

---

## Phase 3 — Make the module do its job

**Estimated 4 days. Nothing here starts before Phases 1 and 2 land.**

### 3.0 The reverse arrow — a terminated engagement voids its pending letter ✅ IMPLEMENTED

**Gate 3A, 2026-09-20.** `terminate_engagement` now runs one transaction
covering: engagement `accepted`→`terminated` (conditional); case release
(conditional on that lawyer); release-gated milestone; pending-letter
cancellation under the §3.G1.10 model with an audit entry carrying
`body_sha256`; and the outbox park. The direct `_notify` is **replaced**, not
supplemented.

Broken letter links (`no_letter`, `letter_missing`, `letter_superseded`) record
an anomaly and the termination completes — termination is a safety exit.
`scripts/engagement_letter_reconcile.py` reads those anomalies back
(`_letter_anomalies`), so the field is surfaced rather than written into a void.

**Two things this gate did not anticipate:**

*The rollback test was proved, not assumed.* Removing the transaction wrapper
was verified to make `test_a_failure_on_the_last_write_rolls_back_every_earlier_one`
FAIL with `engagement not rolled back`, then the wrapper was restored and the
test passed again. A rollback assertion that cannot fail is decoration.

*The anomaly field had no reader.* It was written and surfaced nowhere — the
same "durable but unread" shape as the outbox before §1.1g gave it a drainer. A
record nobody can see is a comment. The census now reports it.

15 tests, all on a real replica set, no mocked transaction boundary.

#### Original analysis, for the record

**Deferred here from Gate 2**, where it was mistakenly written as though it were
part of the same change. It is not: Gate 2 runs letter→engagement, this runs
engagement→letter, and the direction is what makes it a different problem.

Open questions it must answer, none of which Gate 2 addresses:

- **Who may void?** Either party can terminate an engagement. Does a client's
  termination cancel a letter the lawyer has already signed?
- **What if the letter executed first?** An executed letter is immutable, so a
  termination arriving after full execution voids nothing — it ends a
  relationship that was properly formed, which is `terminated`, not `cancelled`.
- **Idempotency and atomicity**, to the same standard as Gate 2: one
  transaction, conditional filters, outbox parked inside.

Until it lands, a terminated engagement can leave a `pending` letter behind.
That is benign — the fee gate refuses a non-executed letter, and the case is
already released by `terminate_engagement` — but it is untidy and should not be
mistaken for the Gate 2 defect, which was neither benign nor self-resolving.

**Tests, moved here from the Phase 2 matrix:**

- engagement terminated → its still-`pending` letter is voided;
- an **executed** letter survives engagement termination untouched, and the
  engagement ends as `terminated` rather than anything letter-derived;
- termination by each party in turn, since who may void is an open question
  above;
- one transaction, conditional filters, outbox parked inside — the same
  atomicity and idempotency standard Gate 2 was held to.

### 3.1 The lawyer cannot author an agreement

The backend already allows it — `POST /agreements` has no role guard
(`agreements.py:15`, only `get_current_user`).

> **SUPERSEDED — "purely a missing UI".** This section originally called lawyer
> authoring a UI-only gap. Gate 1 disproved that: the route has no role guard,
> no relationship check, no rate limit, and does not even pass `case_id`
> (§3.G1.7 B2, B3). Shipping a UI on top of that endpoint would expose an
> arbitrary-user agreement/notification vector that is currently masked only by
> the park flag. **Authoring is gate 3D and depends on 3B**, which builds the
> authorization primitives first.

The UI gap is real, and the capability matters -- it is the module's central
use case: a lawyer cannot send a retainer, an addendum, or any custom agreement
to their own client. But the UI is the LAST step, not the only one.

**Action:** add a create flow to `AgreementsPage.jsx`, with the counterparty
scoped to the lawyer's own clients via `listCases`.

### 3.2 No PDF, and signatures are write-only

Signature data is stored, stripped from every response, and never rendered.
There is no way for anybody to produce a copy of an executed agreement. For an
instrument whose whole purpose is evidentiary, this is the largest product gap
in the module.

**Action:** `GET /agreements/{id}/pdf` — parties only, executed only. The
document carries body, each party's signature, method, server timestamp, and
the `body_sha256`, so it proves its own integrity. A separate evidence
certificate records the facts listed in §3.6.

**Log each download** (agreement id, requester, timestamp). The product plan's
adoption metric — % of executed agreements downloaded at least once — counts an
event nothing currently records, so the counter ships with the endpoint or the
metric is unreportable.

### 3.3 Client agreements are orphaned from their case

`create_agreement` accepts `case_id` and `engagement_id`, but the route never
passes them (`agreements.py:19-25`). Only the engagement producer sets them. A
wizard-created agreement is therefore invisible to the case timeline, to the fee
gate, and to every case-scoped view.

**Action:** accept an optional `case_id` on create, authorise it (the creator
must be a party to that case), and write a case milestone on execution.

### 3.4 Real draft persistence, and a real send step

`AgreementStatus.DRAFT` exists in the enum and is unreachable — create always
writes `PENDING`, which means creating is sending.

**Action:** draft create / update / delete endpoints; a separate `send` that
locks the body, stamps the digest, and notifies. Drafts survive refresh and
navigation.

### 3.5 Withdraw is not decline

The creator is a party, so they can `decline` their own agreement — and every
counterparty is told *"X declined your agreement"* when X is the person who sent
it.

**Action:** split `withdraw` (creator, pre-execution) from `decline`
(counterparty), with distinct notification copy. Record both through the
existing audit-plus-digest path.

> **SUPERSEDED.** This originally read: *"Terminal states after this phase:
> `declined`, `withdrawn`, `expired`."* Those were proposed as STATUSES. They
> are not: the status stays `cancelled`, and the cause is carried in
> `cancellation_source` — see §3.G1.10. Adding two terminal statuses would be a
> migration plus a branch in every consumer, for no distinction the field does
> not already make.

### 3.6 Signature evidence

Capture per signature: agreement id and version, canonical body SHA-256, signer
id and displayed legal name, server timestamp, authentication/session assurance,
method, explicit consent acknowledgement, client IP under a trusted-proxy rule,
idempotency key, audit-event id.

The evidence certificate states **facts**. It must not assert enforceability.

### 3.7 Counterparty selection is lawyer-only

`ModAgreements.jsx:452` populates the list from `searchLawyers`, so client↔client
agreements are structurally impossible — including the NDA and Lease templates
in your own gallery.

**Action:** widen once §3.3's relationship rule exists.

### 3.8 API and model chores

- Paginated list with server-side status/search filters; a light list response
  that does not ship full bodies.
- Max party count, duplicate-party rejection, whitespace-normalised title/body.
- **SUPERSEDED — rate limit placement.** The line below put the limit on
  *create*. That is the wrong boundary once drafts exist: autosave `PATCH`
  would be throttled while the actual abuse vector (sending a notification to
  another person) went unlimited. See §3.G1.11. Original text follows.
- Rate limit on create — `@limiter.limit("10/hour")`. This module is one of the
  few endpoints that pushes a notification to an arbitrary user id, and it
  currently has no relationship check and no limit.
- Delete or align `models/agreement.py`. It is unused for writes, it drifts
  from what the service actually stores, and it uses naive
  `datetime.utcnow()` where the service uses aware `datetime.now(timezone.utc)`.
- Rename `test_agreement.py` → `test_annotator_agreement.py`.

---

## Phase 4 — Blocked on counsel

**Do not start speculatively. Same blocker class as the withdrawn templates and
the 10 CPC particulars.**

### 4.1 Electronic-signature classification

`ETO_CLASSIFICATION` (`agreement_service.py:13`) maps a canvas drawing to
"Advanced Electronic Signature (ETO 2002 S.2(d)(i))". A drawn line in a browser
is not sufficient evidence for that classification on its own — identity
verification, exclusive signer control, integrity and attribution all bear on
it.

The *mechanism* here is good: deriving from the weakest signature, and
degrading an unknown method rather than promoting it, are both correct
instincts. The **labels** are the problem.

**Action, pending counsel:** replace the definitive labels with neutral
technical descriptions ("drawn signature captured in browser", "typed name")
and keep storing the factual evidence. Restore legal characterisations only with
counsel-approved wording.

### 4.2 Signature encryption at rest

Envelope encryption for signature artifacts, or encrypted private object
storage with only a reference, digest and metadata in Mongo. Plus a retention
and secure-deletion policy.

Note this is **separate from Phase 0**: Phase 0 removes a false claim, which is
urgent and free. This builds the thing the claim described, which is neither.

### 4.3 Counsel-approved template registry

Server-side, versioned, each template carrying jurisdiction, document type,
reviewing counsel, review date, version, mandatory and optional clauses, and a
review expiry. Until a template exists in that registry, it does not appear in
the product.

---

## Test matrix

Added per phase, not deferred to the end.

**Phase 0** — the §0.7 string guard.

**Phase 1** — atomic create-sign rollback; concurrent sign/sign; concurrent
sign/decline; idempotent double-submit; signature size, base64 and MIME
validation; the marker guard at step 0.

*The rollback test needs care.* A forced signing failure must leave **no row at
all**, not merely no `pending` row — assert absence **by id**, not absence from
a status filter. **Re-assert it when §3.4 introduces drafts**: a draft is a
legitimate leftover row, so a status-filtered version of this assertion will
start passing for the wrong reason at exactly the moment it stops being true.

**Phase 2** — the letter→engagement decline reversal, and the gates that read
it. As implemented:

- *Reversal* — a declined letter moves its engagement `accepted` → `declined`
  with the R2 metadata; the case is released only when still held by that
  engagement's lawyer; an already-ended engagement is not rewritten; a generic
  agreement touches no engagement or case.
- *Linkage* — missing engagement, missing case, superseded backlink and a
  backlink changed between preflight and the transaction each abort everything.
- *Authorization* — the callback carries its own contract: a non-party cannot
  invoke it directly, a requester removed from the parties after preflight is
  refused, and an agreement-party/engagement-party mismatch is refused even
  when the engagement has already completed or terminated.
- *Review and fee gates* — eligibility and billing both require an **executed**
  letter; the four state-specific fee-gate messages; an ended engagement with an
  executed letter stays billable.
- *Concurrency and retry* — concurrent sign vs decline resolves to one coherent
  terminal state; a full-callback retry across two real transactions duplicates
  no audit entry, milestone or outbox row; a duplicate park fails closed.
- *Notification* — the released branch alone says the case is open again and
  suggests a new engagement; reassigned and already-unassigned cases get
  truthful neutral copy and no impossible instruction.

> **Not Phase 2, and deliberately absent from the list above.** "Letter executed
> → engagement active" belongs to the rejected `awaiting_signatures` activation
> model — the engagement is already `accepted` before the letter executes, so
> there is no activation to test. "Terminated engagement → pending letter
> voided" is the opposite arrow and moved to §3.0 with its tests.

**Phase 3** — full status-transition matrix; withdraw vs decline notification
copy; PDF hash and evidence-certificate contents; route-level authorization
(non-party gets 403 on get/sign/decline, and `audit_log` / `signature_data`
genuinely do not cross the wire); pagination.

**Cross-cutting** — end-to-end client → lawyer → execution → fee request, which
is the path Phase 2 currently breaks. Frontend tests should drive real React
interactions rather than inspecting source strings.

---

## Rejected from the Codex review, with reasons

### 7.1 `PARTIALLY_SIGNED` as a stored status — rejected

It is fully derivable from `parties[].signed`. Storing it creates a
sync-bug class, which is exactly the bug `_derive_eto` was written to fix: the
previous code let whoever signed last overwrite the agreement's legal
characterisation. Do not reintroduce the pattern this module already learned
from. Derive it for display.

### 7.2 Four terminal states — reduced to three, then to ONE

The review proposed `declined`, `voided`, `expired` and `cancelled` without
saying what `cancelled` means that the other three do not. Each extra state is a
migration over live rows and another branch in every consumer.

> **SUPERSEDED by §3.G1.10.** This section originally concluded with three
> terminal STATUSES: *"`declined` (counterparty refused), `withdrawn` (creator
> pulled it), `expired` (deadline passed)."* Gate 1 took the same argument one
> step further and found that **none** of them needs to be a status. The status
> is `cancelled`; the cause lives in `cancellation_source ∈ {declined,
> withdrawn, expired, engagement_terminated}`. Do not implement the three-status
> version.

### 7.3 The transactions hedge — unnecessary

The review proposed transactions "where the deployment supports a replica set,
otherwise conditional atomic updates plus an outbox". This deployment is
`mongodb+srv` (Atlas replica set), `payment_service.py:364` already uses
`session.with_transaction`, and `event_outbox.py` / `provenance_outbox.py`
already exist. Copy the existing pattern; do not design a fallback for a
constraint you do not have.

### 7.4 AI-assisted drafting — cut entirely

A new feature inside a plan about fixing a broken one, and it pushes toward the
exact failure this project already decided against: unverified,
authoritative-looking legal text in a binding instrument. The templates stay
withdrawn until counsel reviews them (§4.3). Revisit only after Phase 4.

### 7.5 Completion estimates — corrected

The review scored the lawyer side (85%) above the client side (78%), then
correctly observed that a lawyer cannot author an agreement at all. The lawyer
side is the weaker one. Corrected figures are at the top of this document.

---

## Execution order and estimates

| Phase | Work | Estimate | Blocks |
|---|---|---|---|
| — | **§2.1 census (read-only)** | **minutes** | nothing — run it first |
| 0 | Delete false claims, dead chrome, ship the string guard | 1 hour | nothing |
| 1 | Atomicity, idempotency, concurrency, sanitisation, counters | 3 days | Phase 3 |
| 2 | Engagement ↔ agreement sync + reconciliation script | 2–3 days | Phase 3 |
| 3 | Lawyer authoring, PDF, drafts, case linkage, API chores | 4 days | — |
| 4 | ETO wording, signature encryption, template registry | counsel-gated | — |

Phases 0–3 are roughly **nine to ten working days**. Phase 4 is not scheduled
because it is not schedulable by an engineer.

If the product decision is to park the DIY contract builder
(`AGREEMENTS_PRODUCT_PLAN.md` §D1), Phase 3 drops to about **two days** —
lawyer authoring plus PDF. The authoring flow still needs its counterparty rule
(the lawyer's own clients, from `listCases`), which §D2 supplies.

**Run the §2.1 census this week, before anything else.** It is read-only, takes
minutes, and answers a question nothing currently answers: is a real lawyer
stuck right now? Then Phase 0 — an hour, removing four false claims from a
product that asks people to sign legal instruments.


---

## Deployment checklist

Settings that change what the product ASSERTS, not merely how it performs.
Each one has a safe default and a consequence for leaving it there.

### `trusted_proxies` (D8) — empty by default

Comma-separated peer addresses of the reverse proxies in front of the API.

**Empty is safe and is the default.** `X-Forwarded-For` is then ignored
entirely and the client IP is whatever the socket reports.

**Empty is not free.** Behind a real proxy, every request appears to come from
that proxy, so `ip_is_verifiable` returns false and **every evidence
certificate prints "origin not recorded"** for every signature. That statement
is true — we genuinely cannot establish the address — but it is weaker
evidence than the system is capable of producing, on every document, silently.

**To configure:**

1. Set `TRUSTED_PROXIES` to the address(es) the API actually sees as the peer.
   Not the public load-balancer hostname — the address of the last hop, as the
   application observes it. If unsure, log `request.client.host` once in
   staging and read it off.
2. Restart, then execute a test agreement end to end.
3. Download the PDF and **confirm an IP appears** beside each signature. If it
   still says "origin not recorded", the configured value does not match the
   observed peer, and nothing else in the document will tell you that.
4. Confirm the address shown is the CLIENT's, not the proxy's. A proxy address
   printed as a signer's origin is a false statement about a real person, and
   it is the failure D8 exists to prevent.

**Never** set this to a wildcard or to a range you do not control. Trusting an
untrusted hop lets a signer write their own IP into the signature record.

---

## What the frontend tests do and do not cover

**They stub at the API-CLIENT seam, not the network.**

`tests/support/jsx-loader.mjs` replaces `@/lib/api.js` with generated spies
whenever *component* code imports it, so a mounted test controls what
`getAgreement` and friends RETURN — the `{data, error, status}` shape
`apiFetch` produces — and never sees a URL, a method, a header or a status
code. The components, their state and their rendering are real; the transport
is not exercised at all.

**What that leaves uncovered**, and where it is covered instead:

| Not visible to a mounted test | Covered by |
|---|---|
| route, method, query string | `agreement_draft_api.test.mjs`, which imports the REAL client and stubs `fetch` |
| `Idempotency-Key` and other headers | same |
| HTTP status handling inside `apiFetch` (401 refresh, JSON parse) | same |
| the server's actual response shape | the backend suites |

**The gap this leaves is real and has bitten once.** A mounted test cannot
tell that the server stopped sending a field, because the stub sends whatever
the test says. Gate 3F removed `body_html` from list rows; the backend tests
asserted the removal, the frontend tests asserted the calls, and every
agreement rendered "No content." beside a working Sign button until somebody
opened one.

`test_the_frontend_reads_only_fields_the_list_row_provides` exists for exactly
that seam: it reads `mapAgreement` as text and compares the keys it touches
against `AgreementListItem`'s declared fields. It is the only test that holds
both halves of the contract at once, and it is why a field the list stops
carrying now fails a build instead of a user.

## Decision Record — pointer

The owner answers to the Decision Freeze Checklist (DG-00 .. DG-28) are
recorded in **`AGREEMENTS_PRODUCT_PLAN.md` §11**, not here, so there is one
home for them.

What they change for THIS document:

- **FR-11 and the Section 1-9 lifecycle are now adopted as requirement
  sources**, each with recorded exceptions. Until now this plan cited neither.
- **Two-party (D2) and plain-text bodies are reinforced, not challenged** —
  both are named exceptions to FR-11, so §3 D2 and `BODY_FORMAT_PLAIN_TEXT`
  stand as written. DG-01 is recorded as time-scoped ("for now"), not closed.
- **Registered-users-only is now a recorded position**, so the absence of an
  invitation or signing-link mechanism is intended rather than missing.
- **Lifecycle Steps 4/5/7 (immutable versions) are binding, and DG-04 is now
  answered: immutable versions are REQUIRED, with no second exception.** This
  plan's §3C implements `version` as an optimistic-concurrency counter, which
  remains an accurate description of the shipped code but is **no longer the
  target model**. See the SUPERSEDED note at §3.G1.15.
- **DG-07 was revised the same day** — KYC must be re-verified at acceptance,
  not only at request. Recorded as a decision plus an implementation gap; the
  code at `884161a` does not do this.
- **D4 is answered** — see the MERGE_CHECKLIST note below.

**Round 2 (2026-09-21)** — thirteen further decisions are recorded in
`AGREEMENTS_PRODUCT_PLAN.md` **§12**. What they change for THIS document:

- **The builder is NOT deleted.** DG-25 was revised; the end-of-October
  deletion default is withdrawn and marked superseded in every place it
  appeared, here and in the product plan.
- **Producer A becomes system-only; B and C converge on one rule set**
  (DG-08). This inverts today's grouping, where A and B share
  `_create_agreement` and C does not. Implementation gap, not scheduled.
- **Immutable party set (DG-11) and all-parties-required (DG-12)** match the
  code as shipped and change nothing here.
- **FR-11.4 (preview), FR-11.9's 2 MB and FR-11.11 (sharing) now carry
  recorded exceptions**, so their absence is intended rather than outstanding.
- **Every register row DG-00 .. DG-28 now has an answer.** What remains is
  implementation, and none of it is scheduled by these documents.

**Versioned-agreements design decisions (2026-09-22)** — recorded in
`AGREEMENTS_PRODUCT_PLAN.md` **§13**, answering the open questions from the
design produced against `f2822f8`. What they fix for THIS document:

- **Either party may propose a change; proposing is NOT accepting** (Q1, Q5).
  Each new version starts with zero acceptances, the proposer's included.
- **Withdraw is blocked once any signature exists on any version** (Q2) —
  across superseded versions too, not only the current one.
- **A title edit does not create a version** (Q3): the digest covers the body
  only (`agreement_service.py:147-159`).
- **At most 20 versions per agreement** (Q4). This cap is load-bearing for the
  design's embedded-`versions[]` shape; **raising it means revisiting the
  collection-shape decision**, because an unbounded embedded list eventually
  breaks the single-document transaction the signing path relies on.
- **A superseded version may be downloaded, watermarked "SUPERSEDED — NOT
  EXECUTED", and must not be presented as evidence of agreement** (Q8).

Q6 and Q7 stay open as owner decisions; **Q9, Q10 and Q11 stay open and
PENDING COUNSEL**, with no legal conclusion stated. None of this is
implemented, and no gate is started.

## MERGE_CHECKLIST — `fix/agreements-phase0`

Everything below is a gate on merging, not a wish list. The engineering items
are verifiable now; the last group is not engineering at all and does not block
the merge, but does block calling the module finished.

### 1. Tests

- [ ] **Full backend suite green**, run once against a real replica set, and
      compared BY FAILING TEST ID against the last full baseline (6587 passed /
      0 failed at `b0ce79f`). Targeted runs are not a substitute: Gate 3F's
      party rule passed its own tests and broke eight engagement tests in a
      module it never touched.
- [ ] **Frontend suite green** (`npm test`, whole suite).
- [ ] No test was weakened to make it pass. A test that moved must have a
      recorded reason.

### 2. Configuration

- [ ] **`trusted_proxies` set** for the target environment, and an IP verified
      to appear on a generated certificate — see the deployment checklist
      above. Leaving it empty ships a product whose evidence documents all say
      "origin not recorded".
- [ ] **Park flag reviewed.** `agreements_diy_builder_enabled` is **false** and
      must stay false: all six DIY templates were withdrawn as United States
      boilerplate, and the backend refuses any body still carrying the
      withdrawal notice. Turning it on requires counsel-reviewed templates
      (D1 / Phase 4.3), not a deployment decision. Engagement letters are
      unaffected by the flag and must remain so.

### 3. Transactions in production

The signing, declining and termination paths are transactional and
**fail closed**: with no replica set they raise rather than degrading to
non-atomic writes.

- [ ] **Confirm the production MongoDB is a replica set.** Atlas is; a
      standalone `mongod` is not.
- [ ] **Verify the fail-closed behaviour deliberately**, in staging, by
      pointing the app at a standalone instance and confirming a sign attempt
      returns 503 rather than writing a partial state. A fail-closed path that
      has never been observed failing is an assumption.
- [ ] Confirm the **event outbox relay** is running. Parked events with no
      drainer are silently undelivered notifications.

### 4. Data

- [ ] **Indexes created** on the target database — `create_all_indexes()`
      covers `agreement_downloads` (by agreement, by user, by time) and the
      `(created_by, status)` pair the draft cap and draft visibility both use.
- [ ] **Pre-3C executed rows will refuse to render.** Any agreement executed
      before Gate 3C carries no `body_sha256`, and the PDF builder refuses it
      with a clear message rather than printing a certificate whose digest
      section is empty. Confirmed: 1 such row exists today (the executed
      orphaned letter). It is NOT back-filled — computing a digest now would
      assert the text is unchanged since signing, which is the one thing a
      missing digest makes unverifiable.

### 5. Open, and NOT engineering

These do not block the merge. They block calling the module done, and each has
been open long enough to be worth naming in the same place.

- [ ] **D4 — reviewing counsel has no owner.** One conversation unblocks three
      backlogs: contract templates, ETO wording, and whether the evidence
      certificate may ever state a legal conclusion. Until then the certificate
      states facts only, which is correct but deliberately limited.
      **SUPERSEDED as a question, 2026-09-21** — answered as DG-25 in
      `AGREEMENTS_PRODUCT_PLAN.md` §11: **accept the indefinite park, no owner
      assigned, PENDING COUNSEL.** The item stays on this checklist because the
      *consequence* is unchanged — templates, ETO wording and certificate
      conclusions remain blocked. What is superseded is the framing of it as an
      undecided question.
      **REVISED 2026-09-21 (DG-25 revised):** the clause that "the D1
      end-of-October default still stands" is **WITHDRAWN**. There is no
      deletion date; the builder stays parked indefinitely.
- [x] ~~**DIY builder cutoff — end of October.** The recorded decision is
      "park now (B), cut it (A) if no counsel is secured by end of October".
      That date is a decision point, not a reminder: if it passes unowned, the
      default is to DELETE the builder rather than leave a parked feature
      indefinitely.~~
      **SUPERSEDED 2026-09-21 — the October deletion default is WITHDRAWN.**
      Answered as **DG-25 (revised)** in `AGREEMENTS_PRODUCT_PLAN.md` §11: the
      builder is **not** deleted and stays parked with no deletion date.
      Templates will be provided later by the project owner (no target date).
      **Provision is not verification** — a template needs a named reviewer,
      review date, version, jurisdiction and an unexpired review period before
      the withdrawn-template guard is lifted for it. No longer a merge gate;
      kept here, struck through, so the old default is not re-read as live.
- [ ] **Six orphaned engagement letters, unclassified.** Agreements whose
      engagement and case rows are both gone (five `pending`, one `executed`),
      all created 2026-08-24. Nothing deletes an agreement when its engagement
      is deleted, so letters outlive what they describe. They must be
      classified as real retained records or fixture residue BY A HUMAN before
      any cleanup: deleting a signed instrument is not a script's decision.
      `scripts/engagement_letter_reconcile.py` lists them with `created_by` and
      `created_at` for exactly this purpose, and its `--apply` path stays
      disabled.
