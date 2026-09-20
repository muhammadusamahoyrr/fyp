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
**Status: NOT STARTED — blocked on product decision D1.**

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

### The rule to enforce

One rule, chosen deliberately, applied in both directions:

- The engagement is **not active** until its letter is executed. Acceptance of
  terms moves it to `awaiting_signatures`, not `accepted`.
- **Letter executed** → engagement becomes `accepted`, case assignment
  activates.
- **Letter declined or expired** → engagement is cancelled and the case is
  released back to `pending_lawyer`, reusing the rollback already written at
  `engagement_service.py:366-380`.
- **Engagement terminated** → any still-pending letter is voided.
- An **executed** letter is a historical record and is never deleted, whatever
  later happens to the engagement.

This is a contract change. `ENGAGEMENT_RETAINED_STATUSES` and the fee gate's
"ended engagements still count" reasoning (`payment_service.py:100-105`) must be
re-read against the new `awaiting_signatures` state before any code moves —
that comment exists because scoping the gate wrongly once already stranded a
lawyer who finished a matter before invoicing.

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

**Step 2 — reconciliation script.** Applies the new rule to exactly the rows the
census found: release the case, cancel the engagement, notify both parties.
Tombstone-first and re-runnable, following the pattern `intake_deletion.py` and
`document_deletion.py` already use. Executed letters are never touched.

**Name it `scripts/engagement_letter_reconcile.py`.** Do **not** name it
`agreement_report.py` — that already exists and is the *annotator* agreement
report, the same collision that makes `test_agreement.py` misleading. Do not add
a third.

Report the census number whichever way it comes out. Zero affected rows means
the defect was real but never triggered, which is a result worth stating, not a
reason to say nothing.

**Phase 2 gate:** declining an engagement letter releases the case and cancels
the engagement; the lawyer sees why; a completed engagement whose letter was
executed can still be billed; the census returns zero after reconciliation.

---

## Phase 3 — Make the module do its job

**Estimated 4 days. Nothing here starts before Phases 1 and 2 land.**

### 3.1 The lawyer cannot author an agreement

The backend already allows it — `POST /agreements` has no role guard
(`agreements.py:15`, only `get_current_user`). This is purely a missing UI, and
it is the module's central use case: a lawyer cannot send a retainer, an
addendum, or any custom agreement to their own client.

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

Terminal states after this phase: `declined`, `withdrawn`, `expired`. Three, not
four — see §7.2.

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

**Phase 2** — engagement letter declined → case released, engagement cancelled;
letter executed → engagement active; engagement terminated → pending letter
voided; executed letter survives engagement termination; the fee gate against
each of these.

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

### 7.2 Four terminal states — reduced to three

The review proposed `declined`, `voided`, `expired` and `cancelled` without
saying what `cancelled` means that the other three do not. Three suffice:
`declined` (counterparty refused), `withdrawn` (creator pulled it), `expired`
(deadline passed). Each extra state is a migration over live rows and another
branch in every consumer.

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
