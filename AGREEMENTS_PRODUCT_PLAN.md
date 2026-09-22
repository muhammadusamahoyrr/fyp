# Agreements — Product Plan

Owner: Muhammad Usama
Written: 2026-09-20
Status: **decision required before engineering starts** (see §3)

Companion document: `AGREEMENTS_REMEDIATION_PLAN.md` holds the engineering
detail — file paths, line numbers, test matrix, phase gates. This document
holds the product decisions that determine *which* of that work is worth doing.

---

## 1. The core finding

**The agreements module is two different products sharing one screen, and only
one of them is load-bearing.**

### Product A — Engagement letters (infrastructure)

Auto-generated when a client accepts a lawyer's fee terms. Case-linked. Signed
by both parties. **Gates all billing** — a lawyer cannot raise a fee request
without an executed letter.

- Not optional. If this breaks, the lawyer marketplace cannot collect money.
- Nobody chooses to use it; it happens as part of hiring a lawyer.
- The generator is well built, with rollback if letter creation fails.
- **It is currently broken in a way that strands lawyers mid-matter** (§2.1).

### Product B — DIY contract builder (a separate product)

A 4-step wizard letting a client draft an NDA, lease, employment contract or
partnership agreement and send it to a lawyer to counter-sign.

- Six templates, **all six withdrawn** because the original text was US
  contract boilerplate ("[State]" incorporation, "$[Amount]" salaries, a
  non-compete over a "[Geographic Area]") unsuitable to sign in Pakistan.
- The backend refuses any body still carrying the withdrawal notice, so
  **no template in the gallery can currently produce a valid agreement**.
- Counterparties are restricted to lawyers, so the NDA and lease templates —
  the ones a client would actually want with another *person* — are
  structurally impossible.
- Lawyers cannot author anything at all, so the professional side of a
  professional legal product is absent.
- Writing replacement templates is legal work, not engineering work. It is
  blocked on the same dependency as the 10 CPC particulars.

They share one list view, one detail modal, one status vocabulary, and one API.
That is why a defect in either surfaces as "the agreements module is broken."

**This document's central recommendation is to separate them and fund them
differently.**

### Product C — Lawyer-authored, case-linked agreements (Phase 3, gate 3D)

**A third thing, and NOT a revival of Product B.** Phase 3 introduces a lawyer's
ability to author an agreement for a client on a case they already hold — a
retainer, an addendum, a scope variation.

It is separated from the parked wizard on every axis that matters:

| | **Product B — client DIY wizard (parked)** | **Product C — lawyer authoring (Phase 3)** |
|---|---|---|
| Who authors | Any client | KYC-verified lawyer only (**D5**, decided) |
| Counterparty | Chosen from a directory of lawyers | The one client on the named case |
| Case link | None | **Mandatory** and server-validated |
| Content | Six withdrawn templates | The lawyer's own wording |
| Flag | `agreements_diy_builder_enabled` — stays **off** | Independent; does **not** read that flag |

**Phase 3 must not unpark Product B.** A concrete guard: lawyer authoring gets
its own producer (`create_lawyer_agreement`), never `create_user_agreement`,
which is gated by design. Anything that makes the client wizard reachable is out
of Phase 3 scope by definition.

---

## 2. What is wrong today, in user terms

### 2.1 A lawyer can end up representing a client they can never invoice

**Severity: critical. Live in the current build.**

What happens:

1. Client accepts the lawyer's fee terms. The case is assigned. An engagement
   letter is generated and sent for signature.
2. Either party declines that letter.
3. The letter is cancelled — but **the engagement stays active and the case
   stays assigned**. The lawyer is still on the matter.
4. The lawyer raises a fee request and is told: *"the engagement letter is still
   'cancelled' — it must be signed by both you and the client."*
5. A cancelled letter can never be signed. The instruction is impossible to
   follow.

The lawyer is doing real work on a real case with no route to payment and no
message explaining why. There is no admin tool to unstick it.

**Who is harmed:** lawyers, directly and financially. This is the failure most
likely to make a lawyer abandon the platform.

### 2.2 The product makes two false promises at the moment of signing

**Severity: critical. Legal and reputational, not technical.**

In the panel where a user draws their signature, the product says:

> "AES-256 encrypted · Timestamped · Compliant with e-signature laws."

and on the review step:

> "All signatures are encrypted with AES-256, timestamped, and comply with
> e-signature laws."

**Two separate unsupported claims live in those strings, and both must go.**

**Claim 1 — "AES-256 encrypted".** Signatures are stored as plaintext base64 in
the database (`agreement_repo.py:43`). The only encryption in the system
protects CNICs, and it is Fernet — **AES-128-CBC with HMAC-SHA256**, not
AES-256.

**Claim 2 — "Compliant with e-signature laws".** Exactly as unverifiable as the
first, and arguably worse: it is a legal conclusion about ETO 2002 that no
lawyer has reviewed. It is the same overreach as §D3's "Advanced Electronic
Signature" label, in plainer words. Removing only the encryption half of the
sentence would leave the legal half standing.

**Four locations, not three.** The claim has propagated into the backend:

| Location | Text | Verdict |
|---|---|---|
| `ModAgreements.jsx:676` | "AES-256 encrypted · Timestamped · Compliant with e-signature laws." | Remove both claims |
| `ModAgreements.jsx:1021` | "All signatures are encrypted with AES-256, timestamped, and comply with e-signature laws." | Remove both claims |
| `OnboardingPage.jsx:1015` | "Security Active — AES-256 protected." | **Remove, do not relabel** — see below |
| `models/user.py:33` | `cnic_encrypted: str \| None = None  # AES-256 encrypted` | **Correct** to `# Fernet (AES-128-CBC + HMAC-SHA256)` |

On `OnboardingPage.jsx:1015`: it was worth checking whether this one describes
CNIC storage and could simply be corrected to AES-128. It does not. It is a
status card rendered beside "Profile Submitted" and "Waiting to Launch", under
the heading *"Your complete profile has been securely submitted"* — so it
describes **the profile submission as a whole**. Name, bar number and
specializations are all stored in plaintext; only `cnic_encrypted` is encrypted
at all. Re-labelling it "AES-128 protected" would trade a false claim for a
misleading one. Delete the card's subtitle.

The backend comment at `models/user.py:33` is different: it *does* describe CNIC
storage, so it gets corrected rather than deleted. Left alone, it is the seed
the UI claim grows back from.

This is not a missing feature. It is the product telling a user something untrue
about the safety and legal standing of their signature, at the exact moment they
are deciding to sign. In a legal product, aimed at a jurisdiction with a real
electronic signature statute, that is a liability question before it is an
engineering one.

**Cost to remove: one hour.** There is no reason for it to survive another day.

### 2.3 The product claims to save work it discards

- "Save Draft" shows a confirmation and saves nothing. The user navigates away
  and loses everything.
- Template "Preview" shows the template's own name and nothing else.
- A notification bell renders a permanent unread dot that means nothing.
- Every user sees the initials "JD" as their avatar.
- 24 formatting buttons (bold, headings, tables, undo) sit above a plain text
  box and do nothing.

Individually small. Together they tell a user the product is a mock-up, which is
the wrong impression to give in a signature flow.

### 2.4 The template gallery leads to a dead end

A user picks "Non-Disclosure Agreement" — labelled **Popular** — edits it,
chooses a counterparty, draws a signature, clicks "Sign & Send", and is
rejected. The refusal is correct; its timing is not. Four steps of work are
discarded at the last click, and nothing warned them.

### 2.5 One click can create two binding agreements

Creating and signing are two separate network calls. If the second fails, the
counterparty has already been notified about an agreement the sender never
signed, and the wizard stays open inviting a retry — which creates a second one.
There is no idempotency protection, unlike document generation and appointment
booking, which both have it.

### 2.6 Nobody can obtain a copy of a signed agreement

There is no PDF, no download, no print view. Signatures are captured, stored,
and then stripped from every API response — they are write-only. An agreement
whose purpose is to be producible as evidence cannot be produced.

---

## 3. Decisions required from you

Engineering cost varies by a factor of three depending on these. **Answer these
before any code is written.**

### D1 — Do we keep the DIY contract builder? **ANSWERED: PARK (2026-09-20)**

Implemented as option B. `agreements_diy_builder_enabled` is off, enforced in
the service layer as well as the route; the frontend mirror hides the templates
gallery, the create wizard, the dashboard call-to-action and the sidebar
entries. Listing, viewing, signing and declining are untouched, so engagement
letters — the load-bearing half — keep working exactly as before.

Reversible: flip the backend flag first, then the frontend one. Turning it on
still requires counsel-reviewed templates (§4.3), not a deployment.

Consequence for R3, as forecast: the atomic create-and-sign work is **deferred**,
since it serves only the parked wizard. Transactional, idempotent sign and
decline shipped anyway — engagement letters depend on them.

*Original options, for the record:*

| Option | Cost | Consequence |
|---|---|---|
| **A. Cut it** (recommended) | −1 day (deletion) | Agreements becomes engagement-letters-only. Honest, fully functional, defensible. The wizard code stays in git history if you revive it. |
| **B. Park it** | 2 hours | Hide behind a flag, keep the code. Reversible, costs nothing, ships nothing. |
| **C. Build it properly** | +6–8 days **and** counsel | Needs reviewed templates, lawyer authoring, a wider counterparty model, and a template registry. Not completable without a lawyer. |

**Recommendation: B now, A if no counsel is secured by end of October.** Option
C is not achievable on your timeline, and shipping a contract builder whose
every template is withdrawn is worse than not having the tab.

> **SUPERSEDED 2026-09-21 — the "A if no counsel by end of October" half is
> WITHDRAWN.** See **DG-25 (revised)** in §11: the owner will NOT delete the
> builder. It stays parked, with no deletion date. Option B stands; Option A is
> no longer a scheduled default. The rest of this recommendation — that C is
> not achievable now, and that shipping withdrawn templates is worse than no
> tab — is unchanged.

### D2 — Who may send an agreement to whom?

Currently: any authenticated user can send a signature request naming any
registered user id, with no shared case, no engagement, and no rate limit. That
is a spam and harassment vector in a product that handles legal matters.

> **SUPERSEDED wording.** This decision originally read: *"require an existing
> relationship — a shared case or engagement."* That is too vague to implement
> and too broad to be safe: "an engagement" would let a lawyer contact somebody
> years after a finished matter, and "a shared case" did not say who had to be
> on it. Replaced by the exact rule below.

**DECIDED — the initial counterparty rule, stated exactly:**

1. **Lawyer authoring only.** No client-authored agreements while Product B is
   parked.
2. **Exactly two parties**: the authenticated lawyer plus one client.
3. **`case_id` is mandatory** — there is no case-less lawyer-authored agreement.
4. The case must **exist**.
5. `case.lawyer_id` **must equal** the authenticated lawyer.
6. `case.client_id` **must equal** the selected client.
7. **A historical executed engagement is NOT permission to contact someone.**
   Rules 4–6 are the whole test; a finished matter grants nothing on its own.
   *(This narrows the Gate 1 recommendation, which had offered "executed
   engagement OR active assigned case" as alternatives — remediation §3.G1.2.
   Only the case-based limb survives.)*
8. **Out of scope:** client-to-client agreements, lawyer-to-unrelated-user,
   and cold outreach of any kind.
9. Lawyer-authored **generic** case agreements are allowed with
   `engagement_id = None`. The case link and the engagement link are
   independent.
10. **`engagement_id` is internal.** It is set only by the system-generated
    engagement-letter producer and must never be accepted from an external
    caller — Gate 2's backlink validation assumes exactly this.

Rules 4–6 together mean the client is reachable *because of this case*, not
because of history. That is the property that forecloses cold outreach.

### D5 — Must a lawyer be KYC-verified to author an agreement? **DECIDED: YES**

**Decision, 2026-09-20: a lawyer must be KYC-verified to author OR send an
agreement, and the check runs at BOTH points.**

Two checkpoints rather than one, because they are separated in time. A draft
authored while verified may be sent weeks later, by which time an admin may have
rejected or revoked that verification (`user_service.py:312` clears
`kyc_verified`). Checking only at create would let a de-verified lawyer send a
binding instrument; checking only at send would let them accumulate drafts they
can never use. Neither failure is acceptable, and the check is cheap.

Implemented in **gate 3B** as part of the authorization primitives. Engineering
detail: `AGREEMENTS_REMEDIATION_PLAN.md` §3.G1.2.

*Evidence and reasoning that led here:*

**Not invented here — the evidence, then the question.**

The agreements module enforces **no KYC check at all** today. Every other
lawyer-acting surface does:

| Surface | Line |
|---|---|
| Engagement acceptance | `engagement_service.py:58` |
| Appointment booking | `appointment_service.py:492` |
| Document review | `document_service.py:649` |
| Document transitions | `document_transitions.py:277` |
| Lawyer directory listing | `user_repo.py:90` |

Five enforcement points, no exceptions — so requiring it here would be
*consistent*, not novel. But no written product rule says "every lawyer action
requires KYC", and agreements has run without it, so the code does not settle
it either way.

**Recommendation: require it**, on the strength of those five. Authoring a
binding instrument is at least as consequential as reviewing a document.

**This was an owner decision, not an engineering conclusion** — and it has now
been made, in favour of consistency with the five precedents above.

### D3 — Do we ship any ETO 2002 classification before counsel reviews it?

The product currently tells users a drawn signature is an *"Advanced Electronic
Signature (ETO 2002 S.2(d)(i))"*. A line drawn in a browser is not, on its own,
sufficient evidence for that characterisation.

**Recommendation: no.** Replace with neutral factual descriptions — "drawn
signature captured in browser", "typed name" — and keep recording the underlying
evidence. Restore legal labels only in counsel-approved wording. The underlying
derivation logic is sound and should be kept; it is the labels that overreach.

### D4 — What is the counsel dependency, and who owns it?

Three separate items are blocked on a qualified Pakistani lawyer: template
wording (D1/C), ETO classification language (D3), and the evidence-certificate
text. This is the **critical path** for anything beyond engagement letters.

It is also the same blocker already holding the 10 CPC particulars and the
Punjab court dependency. **One outreach can clear three backlogs.** Treat
securing a reviewing lawyer as a product task with a named owner and a date, not
as a background wish.

---

## 4. Goals and non-goals

### Goals

1. No user is shown a false statement about security, persistence or legal
   effect.
2. A lawyer who takes on a case can always either invoice or be told plainly why
   not.
3. An executed agreement can be produced as a document by either party.
4. A lawyer can author an agreement for their own client.
5. One click never produces two binding instruments.

### Non-goals for this cycle

- A rich text editor. The plain text box is adequate; the fake toolbar is not.
- AI-assisted clause drafting. This would put unreviewed, authoritative-looking
  legal text into binding instruments — the exact failure the project already
  hardened the intake prompt against. Revisit only after a counsel-approved
  clause library exists.
- Signature encryption at rest. Real, worth doing, but **not a substitute for
  removing the claim** — and the claim must go first because it is free.
- Client-to-client agreements. Gated behind D1 and D2.

---

## 4b. Delivery status as of 2026-09-20 (`b506a00`)

The releases below were planned before any of them shipped. This section records
what actually happened, so the plan can be read as a record rather than only as
an intention. **R1 and R2 did not ship whole** — parts were superseded, parts
deferred by the D1 park decision.

### ✅ Shipped

| Item | Release | Evidence |
|---|---|---|
| Four false claims removed (2× AES-256, 2× e-signature compliance) | R0 | `test_no_unsupported_claims.py`, 9 tests |
| Fake controls removed (draft-save, preview, dead chrome, 24-button toolbar) | R0 | same guard, path-scoped |
| Sign/decline made transactional, fail-closed | R1 | `test_agreement_phase1.py`, 20 tests |
| Notification parked **inside** the transaction; outbox drainer added | R1 | `test_agreement_phase1.py` |
| Plain-text body: normalise, refuse control chars, stable hash | R1 | `test_agreement_phase1.py` |
| Decline-letter → engagement reversal, conditional case release | R2 | `test_agreement_phase2.py`, 27 tests |
| Review **and** billing now require an *executed* letter | R2 | `test_review_and_fee_gates.py`, 18 tests |
| Four state-specific fee-gate messages | R2 | `test_review_and_fee_gates.py` |

### ⚠️ Superseded (planned, then deliberately not built)

| Item | Why |
|---|---|
| `awaiting_signatures` activation model | Rejected after code analysis — see the R2 note below and remediation §2.G1.4 |
| Atomic **create-and-sign** for the client wizard | Serves only the parked builder (D1). Returns as gate 3C's *sign-and-send*, for the **lawyer** flow |
| Idempotency payload fingerprinting | Same reason; returns in 3C with a fuller contract |

### ⏸ Deferred because the DIY builder is parked (D1)

Client-side template authoring, template preview, client-chosen counterparties.
None of this is abandoned; none of it is scheduled. Reviving it needs
counsel-approved templates, not a deployment.

### ⬜ Still outstanding

Transactional termination + pending-letter cancellation (3A) · lawyer/case/client
authorization primitives and `case_id` plumbing (3B) · versioned drafts and
atomic sign-and-send (3C) · lawyer authoring UI (3D) · executed PDF and download
audit (3E) · chores (3F) · automated expiry (separate later gate).

### 📋 Census outcome — reported, not repaired

The reconciliation census found **zero engagements at every status**, so no
reconciliation was applied and `--apply` remains disabled. It did find **six
orphaned engagement letters — one of them `executed`** — whose engagement and
case rows are both gone. These are **reported and deliberately unrepaired**,
pending retention-policy work. Deleting a signed instrument is not a
reconciliation script's decision.

---

## 5. Release plan

Four releases, each independently shippable and each with a user-visible
outcome. Engineering detail is in the companion document.

### R0 — "Stop saying untrue things" · 1 hour · no dependencies

Remove **both** claims in each of the two signing-flow strings — the AES-256
encryption claim *and* "Compliant with e-signature laws" (§2.2). Delete the
onboarding "Security Active" subtitle. Correct the `models/user.py:33` comment
to name Fernet/AES-128 rather than AES-256. Remove the fake draft save, the fake
preview, the dead bell and search, the "JD" avatar, the inert toolbar. Badge the
withdrawn templates as withdrawn.

Replacement wording for the signing panel, which states only what is true:
*"Timestamped and recorded with a full audit trail."*

**Ship a regression guard in the same commit.** A plain test asserting that
`AES-256`, `AES-128`, `Draft saved` and `Compliant with e-signature` do not
appear in `frontend/src/`. Two design constraints, both taken from the existing
`test_no_tracked_example_secrets.py`:

- Scan by **explicit allowlist of paths**, not "everything except what we
  remember to exclude".
- **Do not scan the test suite.** The guard test necessarily contains the very
  strings it forbids, and a rule that scanned itself would force the safety
  test to be weakened to satisfy the safety test.

*User-visible outcome:* nothing in the signing flow claims a property the system
does not have.
*Metric:* 4 false claims → 0, and the guard makes the count stay at 0.
*Ship independently. Do not bundle this with anything.*

### R1 — "Signing is trustworthy" · 3 days · after R0

Create-and-sign becomes one atomic operation with an idempotency key.
Concurrent sign/decline can no longer produce contradictory records. The
template refusal moves to step 1 of the wizard instead of the last click.
`body_html` is sanitised on write, before R3's PDF makes it renderable.

**Ship the measurement counters here**, not later. Every "unknown" in §6 is
unknown because nothing counts it, and R2 cannot report a fix against a
baseline that was never taken.

*Outcome:* one click produces exactly one agreement, or none — never a
half-formed one.
*Metric:* zero unsigned-by-creator agreements in `pending`; zero duplicate
agreements per idempotency key.

*Required test — the "no leftover row" gate.* A forced signing failure must
leave **no row at all**, not merely no *pending* row. Assert absence by id, not
absence from a status filter. **Re-assert this same test once R3 introduces
drafts**, because a draft is a legitimate leftover row and the naive version of
this assertion will start passing for the wrong reason.

### R2 — "Lawyers never get stuck" · 2 days · after R1

> ### ⚠️ SUPERSEDED — the original R2 lifecycle
>
> This release was first specified as: *"An engagement becomes active only when
> its letter is executed. A declined or expired letter cancels the engagement
> and releases the case. A terminated engagement voids any pending letter."*
>
> **The activation half of that was rejected** after reading the code. Deferring
> activation (the `awaiting_signatures` model) would have rewritten
> `accept_terms`, whose two-step atomic claim is what stops two lawyers taking
> one case — and it would have left the case *unclaimed* while the letter was
> pending, opening a competing-lawyer race the system does not have today. The
> window it removed was already safe, because billing is blocked on the letter
> regardless. Engineering rationale: `AGREEMENTS_REMEDIATION_PLAN.md` §2.G1.4.
>
> The cancellation half was kept, and shipped.

**The lifecycle, as built:**

- **Acceptance claims the case** and produces the engagement letter in
  `pending`. This is the atomic case-claim operation and is not deferred.
- **Billing stays blocked** until that letter is `executed` — acceptance alone
  never makes a matter billable.
- **Declining the pending letter reverses the acceptance**: the engagement
  becomes `declined` and the case is released *only if* that engagement's
  lawyer still holds it. ✅ Shipped.
- **Terminating an accepted engagement** must be transactional and must
  conditionally cancel its correctly-linked pending letter. ⬜ **Outstanding —
  gate 3A.** Termination works today but is not transactional, and does not
  touch the letter.
- **Executed letters are permanent records** and are never modified by any
  later engagement event.

**R2 opens with a census, not with code.** The fix above only governs *new*
data. Every engagement stranded by this defect before the fix ships stays
stranded, and no target of "zero" is meaningful until you know the starting
number.

**Step 1 — read-only census (run first, before any code).** Count engagements
in a retained status whose linked agreement is not `executed`, split by
agreement status (`cancelled`, `pending`, missing entirely). Each row is a
lawyer who may be unable to invoice today.

**Step 2 — reconciliation.** A one-off script that applies the new rule to the
rows the census found: release the case, cancel the engagement, notify both
parties. Tombstone-first and re-runnable, following the pattern the intake and
V2 deletion paths already use. Executed letters are never touched.

**Name it `engagement_letter_reconcile.py`.** Do **not** call it
`agreement_report.py` — that name is already taken by the *annotator* agreement
report, the same collision that makes `test_agreement.py` misleading. Do not
add a third.

*Outcome:* §2.1 cannot occur, and any instance of it that already occurred is
cleared.
*Metric:* census count before → 0 after. Report the before-number whatever it
is.
*Note:* this is a contract change; existing billing tests will move.

### R3 — "Agreements are usable documents" · 4 days · after R2

*(≈2 days if D1 returns "park the DIY builder" — see below.)*

Lawyer authoring. PDF download with an evidence certificate. Real draft
persistence with a distinct send step. Case linkage so agreements appear on the
case timeline. Withdraw separated from decline. Pagination, rate limiting,
party validation.

**Log every download.** The metric below is a count of an event nothing
currently records; the counter ships with the endpoint or the metric is
unreportable.

If D1 is "park", the lawyer create flow still needs an explicit counterparty
rule — **their own clients only**, derived from `listCases`. D2 already supplies
that rule, so parking the builder does not leave the authoring flow undefined.

*Outcome:* a lawyer can send a retainer to their client, and either party can
download the signed result.
*Metric:* % of executed agreements downloaded at least once — the measure of
whether the feature is real to users.

### R4 — Counsel-gated · not schedulable

Reviewed template registry, ETO wording, signature encryption at rest. Starts
when D4 has an owner and a date.

---

## 6. Success metrics

Every row names a measurement source that exists or is scheduled. Rows whose
source was never built are marked **NO SOURCE** rather than given a number.

| Metric | Measured value | Source | Status |
|---|---|---|---|
| False claims in the signing flow | **4 → 0** | `test_no_unsupported_claims.py` | ✅ measured, guarded |
| Stranded engagements (retained + non-executed letter) | **0** | `engagement_letter_reconcile.py` census, run 2026-09-20 | ✅ measured |
| Engagements at any status | **0** | same census | ✅ measured — and why "0 stranded" means *unexercised*, not *safe* |
| Orphaned engagement letters | **6, one `executed`** | same census, reverse check | ✅ measured; unrepaired by design |
| Concurrent sign/decline yields one terminal state | pass | `test_agreement_phase2.py` | ✅ test-evidenced |
| Review requires an executed letter | pass | `test_review_and_fee_gates.py` matrix | ✅ test-evidenced |
| Agreements in `pending` never signed by their creator | **NO SOURCE** | — | ⚠️ the R1 "counter" was never built; only the atomic path was. With the wizard parked this shape is unreachable, so the metric is **retired**, not pending |
| Duplicate agreements per idempotency key | **NO SOURCE** | — | ⚠️ idempotency deferred with the wizard; returns with gate 3C |
| Executed agreements downloaded at least once | **NO SOURCE** | gate 3E download-audit event | ⬜ planned |
| Agreements authored by lawyers | **0** — capability does not exist | gate 3D | ⬜ planned |

> **Correction.** Earlier drafts of this table carried R1/R2 "counters" as
> though they had shipped. They did not: R1 shipped the *atomic path*, and the
> census — not a counter — is what produced the R2 numbers. Two rows are
> therefore marked NO SOURCE above rather than left implying data exists.

"Unmeasured" is the honest entry, not "0" and not "unknown, >0 possible" —
writing a number nobody counted is the same class of error as the AES-256
claim.

Two ordering rules follow from this table, and both are already folded into §5:

- **R1 ships the counters**, because R2 cannot demonstrate a fix against a
  baseline that was never taken.
- **R3 ships the download log**, because the download metric counts an event
  nothing currently records.

Note the false-claim count is **4, not 3** — §2.2 found a fourth in the backend.

---

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A user relies on the AES-256 or compliance claim | Low | **Severe** — false representation in a legal product | R0, today |
| A lawyer is stranded mid-matter and leaves the platform | **Reachable by a normal decline** — see note | High | R2 census + reconciliation |
| Duplicate binding agreements from a double-click | Medium | High | R1 |
| A withdrawn template is signed anyway | **Low** — backend refuses at create *and* sign | Severe | Already mitigated; keep the guard |
| Stored XSS via `body_html` | Low today — rendered as text | Medium, rises with R3's PDF | Sanitise in R1, before the PDF lands |
| Counsel never secured, R4 never ships | Medium | Medium — caps the product at engagement letters | ~~D1 option A; be willing to cut~~ **SUPERSEDED 2026-09-21 (DG-25 revised, §11): the builder stays parked and is NOT cut. Mitigation is now: accept the cap at engagement letters for as long as the park lasts.** |
| R2's contract change breaks billing | Medium | High | Re-read the fee gate's "ended engagements still count" reasoning first; it exists because this was got wrong once |

**Note on the stranded-lawyer row.** The likelihood is stated as *reachable*
rather than *high*, because how often it has actually happened is unmeasured
until the R2 census runs. Both outcomes are reportable results:

- **Census finds affected rows** → the risk was real, reconciliation clears
  them, and the before/after numbers are the evidence the fix worked.
- **Census finds none** → the defect is real but has not yet been triggered in
  practice. That is a good result and should be reported as such.

What is not acceptable is reporting neither. A supervisor will ask how many
lawyers were affected, and "we fixed it before anyone hit it" is only credible
if you looked.

---

## 8. Recommendation

**Ship R0 today.** It takes an hour, needs no decisions, and removes four false
claims — two about encryption, two about legal compliance — from a flow where
people sign legal instruments. Ship the guard test with it so they cannot creep
back. There is no version of this plan where R0 waits.

**Run the R2 census this week, independently of everything else.** It is
read-only, it takes minutes, and it answers a question you currently cannot
answer: is any real lawyer stuck right now? Do it before R1, not after — the
number is needed for the write-up either way, and if it comes back non-zero the
whole plan's ordering changes.

**Then R1 → R2 as one block, roughly a week.** Together they make the module
correct: no duplicate instruments, no stranded lawyers, and counters that prove
both. This is the minimum for the agreements module to be defensible in a demo
or a viva, because both failures are reachable by ordinary use and both are easy
to trigger in front of an examiner.

**Decide D1 before R3.** If the answer is "park the DIY builder", R3 shrinks to
lawyer authoring plus PDF — two days, not four — and the module becomes a
focused, honest engagement-letter system that does one thing completely. That is
a stronger product than a contract builder that cannot build contracts.

**Own D4 personally and start it this week.** One conversation with a
practising Pakistani lawyer unblocks agreements templates, the ETO wording, and
the 10 CPC particulars simultaneously. It is the highest-leverage hour available
to this project and it is not an engineering task.


---

## 9. Cross-plan traceability

One row per product decision or outcome, mapped to the engineering gate that
implements it and the evidence that proves it. **Product decisions live in this
document; gates, invariants and tests live in
`AGREEMENTS_REMEDIATION_PLAN.md`.** Where the two disagree, the code decides,
and whichever document was wrong gets a SUPERSEDED note rather than a silent
edit.

| # | Product decision / outcome | Gate | Status | Evidence |
|---|---|---|---|---|
| 1 | No false security or legal claim reaches a user | R0 / Phase 0 | ✅ shipped | `test_no_unsupported_claims.py` (9) |
| 2 | One click never produces two binding instruments | R1 / Phase 1 | ✅ shipped | `test_agreement_phase1.py` (20) |
| 3 | A notification cannot be lost to a crash after commit | R1 / Phase 1 | ✅ shipped | in-transaction park + ungated relay |
| 4 | Agreement body is plain text, never silently rewritten | R1 / Phase 1 | ✅ shipped | `normalise_body` tests |
| 5 | Declining a letter reverses the engagement | R2 / Phase 2 | ✅ shipped | `test_agreement_phase2.py` (27) |
| 6 | Billing requires an executed letter | R2 / Phase 2 | ✅ shipped | `test_review_and_fee_gates.py` (18) |
| 7 | Reviewing requires an executed letter | R2 / Phase 2 | ✅ shipped | eligibility matrix |
| 8 | Engagement activates only after execution | — | ⚠️ **superseded** | rejected; remediation §2.G1.4 |
| 9 | DIY client builder parked (D1) | — | ⏸ deferred | `agreements_diy_builder_enabled` off, service-enforced |
| 10 | Terminating an engagement is atomic and cancels its pending letter | **3A** | ⬜ outstanding | live integrity defect — remediation §3.G1.7 B1 |
| 11 | Counterparty rule: lawyer + one client + mandatory validated case (D2) | **3B** | ⬜ outstanding | remediation §3.G1.2 |
| 12 | `case_id` reaches persistence and is authorized | **3B** | ⬜ outstanding | remediation §3.G1.7 B2 |
| 13 | Drafts are versioned; send is one atomic idempotent call | **3C** | ⬜ outstanding | remediation §3.G1.3 |
| 14 | A lawyer can author an agreement for their client | **3D** | ⬜ outstanding | first point the capability is user-visible |
| 15 | Either party can obtain the executed document | **3E** | ⬜ outstanding | download-audit event feeds metric row 9 |
| 16 | Download adoption is measurable | **3E** | ⬜ outstanding | no source until 3E ships |
| 17 | Automated expiry (`cancellation_source="expired"`) | later gate | ⬜ deferred | reserved only; no scheduler specified |
| 18 | Lawyer KYC required to author **and** send (D5) | **3B** | ✅ **decided** — outstanding to build | §3 D5; checked at create and at send |
| 19 | Counsel-approved template registry | Phase 4.3 | 🔒 counsel-blocked | D4 unowned |
| 20 | ETO classification wording | Phase 4.1 | 🔒 counsel-blocked | neutral labels until reviewed |
| 21 | Evidence-certificate legal conclusions | Phase 4 | 🔒 counsel-blocked | factual PDF in 3E is **not** blocked |
| 22 | Signature encryption at rest | Phase 4.2 | 🔒 counsel/eng | claim already removed in R0 |
| 23 | Six orphaned letters | retention work | ⬜ reported, unrepaired | census output; out of Phase 3 scope |

---

## 10. Open owner decisions

Genuinely unresolved product or security choices. **None of these is settled by
engineering analysis**, and none should be read as decided because a gate
mentions it.

| # | Decision | Why it is open | Blocks |
|---|---|---|---|
| **D8** ✅ | Trusted-proxy / `X-Forwarded-For` policy | **CLOSED 2026-09-21.** `X-Forwarded-For` is trusted only when the immediate peer is a configured proxy address. If the client IP cannot be verified, it is **omitted** from the evidence document rather than printed with a caveat — an unverifiable IP asserts a false fact, and the certificate already states what it does not record. | 3E |
| **D4** | Who owns securing reviewing counsel, by when? | **ANSWERED 2026-09-21 as DG-25: accept the indefinite park — no owner assigned, deliberately. See §11.** Remains unowned by decision rather than by neglect; ~~the D1 default (cut the builder if no counsel by end of October) stands.~~ **REVISED 2026-09-21 — that default is WITHDRAWN; the builder stays parked indefinitely and is not deleted. See DG-25 (revised), §11.** Still unowned. Blocks templates, ETO wording and certificate conclusions — three backlogs, one conversation. | Phase 4 |

Five previously-open items are now **closed**: D1 (park the builder), D2 (the
counterparty rule, stated exactly in §3), **D5** (KYC required to author or
send, checked at both points), **D6** and **D7** (below).

### D6 — Sign-and-send rate limit. **DECIDED: `10/hour` per authenticated lawyer**

Applied to SEND ONLY, which is the abuse boundary: sending is what reaches
another person. Draft `PATCH` is autosave and must never be throttled —
throttling it loses the lawyer's work for no safety gain.

A **default, not a measured figure.** Ten sends an hour is comfortably above
normal practice and far below what a spam run needs. Revisit against real
traffic rather than treating the number as settled.

### D7 — Active-draft cap. **DECIDED: 20 per lawyer, as a named constant**

Drafts are cheap but unbounded, and an unbounded per-user collection is a
storage vector even without malice. Twenty is generous for real work.

**A named constant, not a literal**, so the number has one home and a later
change is one edit rather than a search. Counts only `draft` rows; deleting a
draft frees a slot, so the cap bounds live work rather than lifetime output.


---

## 11. Decision Record

Owner answers to the Decision Freeze Checklist (DG-00 .. DG-28), recorded as
given. Nothing here is inferred: where an answer names exceptions, the
exception text is the owner's own wording.

**Decided: 2026-09-21. Decided by: project owner (Muhammad Usama).**

### DG-00 — Is FR-11 authoritative for this repository?

**ANSWERED: ADOPT WITH RECORDED EXCEPTIONS.**

| Field | Value |
|---|---|
| Date | 2026-09-21 |
| Decided by | Project owner |
| Sources in play | **FR-11** (prompt-supplied), **PLAN** (this file + remediation plan) |
| Result | FR-11 binds, except for the four items below |

**Exceptions, as stated by the owner:**

1. **FR-11.7 — only two parties for now.**
2. **FR-11.8 / 11.11 — registered users only, no signing links for outsiders.**
3. **FR-11.6 / 11.10 — plain text, not rich text.**
4. **FR-11.9 — "Signed" shows only when everyone has signed.**

### DG-28 — Is the intended lifecycle (Steps 1-9) authoritative?

**ANSWERED: ADOPT WITH RECORDED EXCEPTIONS.**

| Field | Value |
|---|---|
| Date | 2026-09-21 |
| Decided by | Project owner |
| Sources in play | **LIFECYCLE** (prompt-supplied Steps 1-9), **PLAN** |
| Result | Steps 1-9 bind, except as below |

**Exception, as stated by the owner:**

1. **Two parties only for now. More than two can come later.**

### DG-07 — KYC on the engagement-letter path

**ANSWERED: RE-CHECK KYC AT ACCEPTANCE.**

*Supersedes the first record of DG-07 (2026-09-21, "record once-at-request as
deliberate"), which was changed by the owner before any code was written.*

| Field | Value |
|---|---|
| Date | 2026-09-21 (revised same day) |
| Decided by | Project owner |
| Sources in play | **IMPLEMENTATION** (verified behaviour), previously **UNDEFINED** |
| Result | **DECIDED + IMPLEMENTATION GAP** — the code does not do this yet |
| Counsel | **PENDING COUNSEL** — no legal conclusion is stated here |

**What was verified before the decision** (`884161a`):
`engagement_service.py:57-66` -- `_get_verified_lawyer` rejects an unverified
lawyer. Called once, at `:108`, inside `request_engagement` (`:84`).
`engagement_repo.insert(doc)` at `:127` is the only engagement-row creator in
the repository, so no engagement exists without that check having passed.
`propose_terms` (`:188`) and `accept_terms` (`:260`) re-check identity and
status only; neither re-checks KYC before `create_pending_engagement_letter`
at `:365`.

**Decision:** KYC must be re-verified at acceptance, before
`create_pending_engagement_letter` generates the letter. This aligns Producer
A with D5's treatment of Producer C, which re-checks at create, update and
send (`agreement_service.py:408, 467, 550`) precisely because verification can
be revoked.

**IMPLEMENTATION GAP — not yet built.** At `884161a` the only KYC check on this
path is the once-at-request one described above. `accept_terms`
(`engagement_service.py:260`) re-checks ownership and status only. Closing this
gap means adding a verification step on the acceptance path; no code is written
by this docs-only record, and the rollback behaviour of a failed check at
acceptance is **UNDEFINED** and not decided here.

**Pending counsel:** whether any particular verification point is sufficient
for an instrument a client signs is a legal question and is not answered
here.

### DG-25 — D4, reviewing counsel ownership — **SUPERSEDED**

> **SUPERSEDED 2026-09-21** by **DG-25 (revised)** below. Reason: the record
> beneath preserved the D1 default of deleting the builder at end of October.
> The owner has since withdrawn that default — the builder is **not** to be
> deleted. Kept visible because it is the record of what "accept the indefinite
> park" was taken to mean at the time.

**ANSWERED (SUPERSEDED): ACCEPT THE INDEFINITE PARK.**

| Field | Value |
|---|---|
| Date | 2026-09-21 |
| Decided by | Project owner |
| Owner assigned | **None** -- deliberately |
| Sources in play | **PLAN** (D1, D4) |
| Counsel | **PENDING COUNSEL** |

No counsel owner is assigned. ~~The recorded D1 default stands: park now, and
cut the builder if no counsel is secured by end of October.~~ **That sentence
is superseded — see DG-25 (revised).** D4 remains open by choice rather than
by neglect, and the certificate continues to state facts only.

### DG-25 (revised) — the builder stays parked and is NOT deleted

**ANSWERED: KEEP THE BUILDER PARKED. THE OCTOBER DELETION DEFAULT IS
WITHDRAWN.**

| Field | Value |
|---|---|
| Date | 2026-09-21 (revision of the record above) |
| Decided by | Project owner |
| Sources in play | **PLAN** (D1, D4) |
| Status | **PENDING COUNSEL** |

- The DIY builder is **not** deleted. It remains parked behind
  `agreements_diy_builder_enabled` (`core/config.py:283`, default false).
- The D1 default "cut it (A) if no counsel is secured by end of October" is
  **WITHDRAWN**. No deletion date replaces it.
- **Owner of providing templates: Muhammad Usama (project owner).**
- **Target date: none set.** Recorded from the owner's words: templates will
  be provided "later — anytime".

**PROVISION IS NOT VERIFICATION.** A template being supplied does not make it
verified. Before any specific template may be treated as usable, all of the
following must be recorded for that template:

1. a **named reviewer**;
2. a **review date**;
3. a **template version**;
4. the **jurisdiction** it was reviewed for;
5. an **unexpired review period**.

Until every one of those is recorded for a given template, the
withdrawn-template guard stays ON for it — `is_unreviewed_template`
(`agreement_service.py:83`), which refuses the marker at create **and** at
sign.

**A conflicting statement, recorded not resolved.** In the same answer the
owner stated that the templates to be provided "are verified \[ones\] already".
That is recorded here as **the owner's statement**, not as established
verification, because this decision also requires the five items above before
any template counts as verified. No assessment of the claim is made here, and
no legal conclusion is stated. **PENDING COUNSEL.**

### FR-11 source -- REQUIRED FOLLOW-UP

DG-00 was answered ADOPT WITH EXCEPTIONS, so FR-11 is now a binding
requirement source for this repository. **It does not exist here.** The audit
at `884161a` searched the repository by filename and by content and found no
SRS, requirements, specification, proposal or acceptance-criteria document;
the only `functional requirement` match repo-wide was untracked QA
boilerplate unrelated to agreements.

**The authoritative FR-11 text currently lives outside this repository** and
must be committed into it before it can be cited as a source. Until then,
every FR-11 reference in these plans points at text no reader of the
repository can open.

*The wording of FR-11 is not reproduced here, because it was supplied
conversationally and has not been seen in an authoritative form.*

### Consequences for the register -- now askable

Recorded per the Decision Freeze Checklist dependency chains. **These are
listed, not answered.**

| Unblocked by | Now askable |
|---|---|
| **DG-00** | DG-01, DG-03, DG-08, DG-18, DG-19 |
| **DG-28** | DG-04, DG-11 (in part), DG-12 |
| **DG-00 + DG-28 + DG-04** | DG-20 |
| **DG-25** | DG-21, DG-23 (and DG-24 after DG-23) |
| **DG-04 once answered** | DG-02, DG-14 |
| **DG-01 + DG-04 once answered** | DG-05, then DG-06 and DG-27 |
| **DG-03 once answered** | DG-22 |

### Consequences -- rows the exceptions already settle

The owner's exception wording states a position on four rows. Recorded here so
they are not re-asked, and NOT restated as independent decisions.

| Row | Settled by | Owner's wording |
|---|---|---|
| **DG-01** party count | DG-00 exception 1 + DG-28 exception 1 | "only two parties for now"; "More than two can come later" |
| **DG-03** identity model | DG-00 exception 2 | "Registered users only, no signing links for outsiders" |
| **DG-05** `Signed` semantics | DG-00 exception 4 | "Signed shows only when everyone has signed" |
| **DG-20** body format | DG-00 exception 3 | "Plain text, not rich text" |

Each matches current behaviour, so none of the four implies a code change:
`agreement_service.py:~844-848` (two parties), `:853` (registered users only),
`:~90` (executed on all signatures), `:~430` (`BODY_FORMAT_PLAIN_TEXT`).

**"For now" is recorded as stated.** DG-01 is time-scoped, not closed: the
owner reserved more-than-two parties for later. It is not marked CLOSED in
section 10 for that reason.

### DG-04 — Version model

**ANSWERED: IMMUTABLE VERSIONS REQUIRED. NO SECOND EXCEPTION.**

| Field | Value |
|---|---|
| Date | 2026-09-21 |
| Decided by | Project owner |
| Sources in play | **LIFECYCLE** Steps 4/5/7 (adopted at DG-28), **IMPLEMENTATION** |
| Result | **DECIDED + SUBSTANTIAL IMPLEMENTATION GAP** |

DG-28 was adopted with a party-count exception only. Lifecycle Steps 4, 5 and
7 — immutable versions, v1 preserved, signatures re-scoped on change — carry
no exception and **bind**. The owner declined a second exception, so the
current model must change.

**What exists at `884161a`:** `version` is an optimistic-concurrency counter
incremented in place (`agreement_service.py:491`,
`{"$set": updates, "$inc": {"version": 1}}`). There is no parent-version,
superseded flag, diff or version document anywhere in the service, schema or
repository. Editing a draft **overwrites** the prior body. A signature's audit
entry records a body digest but **no version id**.

**What the decision requires** (recorded, not designed): immutable versions
carrying at minimum a parent, an author, a timestamp, the exact body and its
digest; signatures scoped to the version signed; and v1 preserved when v2 is
created.

**Consequences for other rows, recorded not answered:**

- **DG-02** (acceptance distinct from signing) is now askable — lifecycle
  acceptance is per-version, and versions now exist as a requirement.
- **DG-14** (amendments) is now askable — Step 9 presupposes immutable
  originals.
- **DG-20** (body format) is settled as plain text by the DG-00 exception, but
  what a version *contains* now matters for diffing; that is a design question,
  not a further decision.
- **H.2 #5 no longer holds as a reason.** The audit observed that a v1
  signature could not be miscounted toward v2 because v2 could not exist. Once
  versions exist, that protection disappears and signature-to-version binding
  becomes load-bearing. **UNDEFINED** and not decided here.

*Note on scope: this is the largest structural change in the register. Nothing
is implemented by this record.*

### Consequence requiring confirmation -- DG-04 — **RESOLVED**

**SUPERSEDED 2026-09-21** by the DG-04 record above. This block asked the owner
to confirm whether adopting the lifecycle without a versioning exception was
intended. It was: the owner declined a second exception and chose immutable
versions. Retained for the record of how the question arose.


---

## 12. Decision Record — Round 2

Owner answers to the second Decision Sheet. **Decided 2026-09-21, by the
project owner.** Recorded as given; nothing is inferred and nothing here is
implemented.

Each record states whether it implies a code change. Where it does, it is
labelled **implementation gap, not scheduled** — the decision is made, the
work is not planned, and no code is written by this document.

### DG-08 — Producer separation

**ANSWERED: (c) Producer A is system-only; B and C share ONE rule set.**

| Field | Value |
|---|---|
| Sources | **PLAN** (D1, D2, D5, D6, D7), **IMPLEMENTATION** |
| Code change? | **YES — implementation gap, not scheduled** |

Engagement letters (A) stay system-generated, reachable only from
`accept_terms` and never over HTTP. The client builder (B) and lawyer-authored
agreements (C) converge on a single rule set.

**This does NOT remove or delete the builder.** B stays parked per DG-25
(revised); convergence describes the rules B will follow *when* it is
unparked, not its removal.

Today B and A share `_create_agreement` (`agreement_service.py:813`) while C
has its own path (`:397`), which is the opposite grouping from the one decided.
Aligning them is the gap.

### DG-11 — Party set after creation

**ANSWERED: (a) immutable after creation.**

| Field | Value |
|---|---|
| Sources | **LIFECYCLE** Step 7 (adopted at DG-28), **FR-11** silent on post-creation change |
| Code change? | **NO** — matches current behaviour; no party-mutation route exists |
| Exception | Records a **departure from LIFECYCLE Step 7**, which implies the party set may change |

### DG-12 — Required signers

**ANSWERED: (a) every party is a required signer.**

| Field | Value |
|---|---|
| Sources | **LIFECYCLE** ("all required parties"), **FR-11** silent |
| Code change? | **NO** — matches `agreement_service.py:~90`, where every `parties[]` entry gates execution |

### DG-02 — Acceptance distinct from signing

**ANSWERED: (b) acceptance is a separate per-party, per-version act that opens
signing.** **PENDING COUNSEL.**

| Field | Value |
|---|---|
| Sources | **LIFECYCLE** Steps 3–6, **UNDEFINED** in both plans before now |
| Code change? | **YES — implementation gap, not scheduled** |

No acceptance exists on agreements today; the only party acts are sign
(`routes/agreements.py:110`) and decline (`:127`). Acceptance is per-version,
so it depends on DG-04's immutable versions existing first.

**PENDING COUNSEL** — what a party is taken to have agreed to, and when, is a
legal question. No legal conclusion is stated here.

### DG-14 — Amendments

**ANSWERED: (a) deferred; reserve a supersedes / linked-agreement field in the
design.** **PENDING COUNSEL.**

| Field | Value |
|---|---|
| Sources | **LIFECYCLE** Step 9 (adopted at DG-28), **IMPLEMENTATION** |
| Code change? | **Deferred.** The reserved field is a design note, not scheduled work |
| Exception | Records a **deferral of LIFECYCLE Step 9**, which is otherwise binding |

Nothing is built. The decision reserves a `supersedes` / linked-agreement
field so a later amendment does not require re-modelling.

**PENDING COUNSEL** — the relationship between an executed instrument and a
later change to it is a legal question. No legal conclusion is stated here.

### DG-18 — Reference number

**ANSWERED: (a) add a dedicated human-readable reference-number field.**

| Field | Value |
|---|---|
| Sources | **FR-11.1** (binding since DG-00) |
| Code change? | **YES — implementation gap, not scheduled** |

No `reference_number` exists in `schemas/agreement.py`, the service, or either
screen. Human-readable is recorded as decided; its format is **UNDEFINED**.

### DG-19 — Agreement value

**ANSWERED: (a) add an optional agreement-value field.**

| Field | Value |
|---|---|
| Sources | **FR-11.1** (binding since DG-00) |
| Code change? | **YES — implementation gap, not scheduled** |

Optional is recorded as decided. Currency, precision, and whether it derives
from engagement fee terms are **UNDEFINED**.

### DG-21 — Template preview

**ANSWERED: (b) record an exception to FR-11.4 while the builder is parked.**

| Field | Value |
|---|---|
| Sources | **FR-11.4**, **PLAN** (D1, DG-25 revised) |
| Code change? | **NO** — the Preview button is already absent (`ModAgreements.jsx:457-459`) |
| Exception | **FR-11.4 does not apply while the builder is parked.** It resumes if the builder is unparked |

### DG-23 — Drawn and uploaded signature methods

**ANSWERED: (a) draw and upload move into the live screens, independent of the
builder.**

| Field | Value |
|---|---|
| Sources | **FR-11.9** (binding since DG-00) |
| Code change? | **YES — implementation gap, not scheduled** |

All three methods exist in the parked `PageCreate` (`ModAgreements.jsx:799`);
both live signing paths hardcode typed (`:1221`, `AgreementsPage.jsx:132`).
The backend already accepts all three (`core/constants.py:106-109`).

> **RISK NOTE — SVG.** An uploaded SVG can carry scripts. Any SVG must be
> sanitised or converted before it is displayed or included in a PDF. This is
> recorded as a constraint on the future work, not as a finding about current
> code: upload is not reachable today, so no SVG currently reaches a renderer.

### DG-24 — Upload type and size limits

**ANSWERED: (b) keep the server's smaller limit, correct the UI label, check
file type in the browser.**

| Field | Value |
|---|---|
| Sources | **FR-11.9**, **IMPLEMENTATION** |
| Code change? | **YES — implementation gap, not scheduled** |
| Exception | **FR-11.9's 2 MB does not apply.** The server limit governs |

The server caps `signature_data` at 200,000 characters
(`schemas/agreement.py:20`, `_MAX_SIGNATURE`) — roughly 146 KB of base64, about
14× stricter than 2 MB. The UI label "PNG, JPG or SVG · Max 2MB"
(`ModAgreements.jsx:955`) is unenforced and must be corrected to the real
limit. Browser-side type checking replaces the current `accept="image/*"` hint
(`:933`).

### DG-27 — Status vocabulary

**ANSWERED: (a) both screens use FR-11.1's vocabulary.**

| Field | Value |
|---|---|
| Sources | **FR-11.1** (binding since DG-00) |
| Code change? | **YES — implementation gap, not scheduled** |

The client screen already matches (`ModAgreements.jsx:158` — `Signed`,
`Rejected`). The lawyer screen does not (`AgreementsPage.jsx:13` — `Executed`,
`Cancelled`) and must change.

### DG-06 — Partly-signed display

**ANSWERED: (b) a derived display, not a new stored status.**

| Field | Value |
|---|---|
| Sources | **LIFECYCLE** Step 6, **FR-11** silent |
| Code change? | **YES — implementation gap, not scheduled** |

No enum member is added; `AgreementStatus` stays at four
(`core/constants.py:112-116`). The display derives from `parties[].signed`,
which is already present.

### DG-22 — Sharing

**ANSWERED: (a) out of scope for now; exception to FR-11.11.**

| Field | Value |
|---|---|
| Sources | **FR-11.11**, **PLAN** |
| Code change? | **NO** — nothing exists and nothing is added |
| Exception | **FR-11.11 does not apply for now** |

**DG-03 stands as already recorded** — registered users only, no signing links
for outsiders.

### Round 2 consequences

#### Register status, recounted from the 29 rows

Counts are recalculated from the rows themselves, not carried forward.

| Status | IDs | Count |
|---|---|---|
| **DECIDED** | DG-00, DG-01, DG-02, DG-03, DG-04, DG-05, DG-06, DG-07, DG-08, DG-11, DG-12, DG-14, DG-18, DG-19, DG-20, DG-21, DG-22, DG-23, DG-24, DG-25, DG-27, DG-28 | **22** |
| **DECIDED EARLIER, implementation outstanding** | DG-09, DG-10, DG-15 | **3** |
| **NOT A DECISION — implementation behaviour** | DG-13, DG-16, DG-17, DG-26 | **4** |
| **STILL OPEN** | *(none)* | **0** |
| **TOTAL** | | **29 ✓** |

22 + 3 + 4 + 0 = **29**, matching the register's DG-00 .. DG-28 inclusive.
**Every decision row in the register now has an answer.** What remains is
implementation and the items below.

#### Implementation gaps this round CREATES

Each is decided and unscheduled. No code is written by this document.

| Row | Gap | Evidence of the current state |
|---|---|---|
| **DG-08** | A system-only; B and C on one rule set | B+A share `agreement_service.py:813`; C has `:397` — the opposite grouping |
| **DG-02** | Per-party, per-version acceptance | No acceptance surface; depends on DG-04 landing first |
| **DG-18** | Human-readable reference number | Field absent everywhere |
| **DG-19** | Optional agreement value | Field absent everywhere |
| **DG-23** | Draw + upload in live screens, with SVG sanitised or converted | `ModAgreements.jsx:1221`, `AgreementsPage.jsx:132` hardcode typed |
| **DG-24** | Correct the UI limit label; browser-side type check | `ModAgreements.jsx:933, 955` |
| **DG-27** | Lawyer screen adopts FR-11.1 vocabulary | `AgreementsPage.jsx:13` |
| **DG-06** | Derived partly-signed display | `parties[].signed` exists; nothing renders it |

#### Implementation gaps CARRIED IN from earlier rounds

| Row | Gap | Status |
|---|---|---|
| **DG-04** | Immutable versions — the largest structural change in the register | Open gap; `agreement_service.py:491` still an in-place counter |
| **DG-07** | Re-check KYC at acceptance | Open gap; `accept_terms` does not verify |
| **DG-09** | Decline records a `cancellation_source` | Open gap (§3.G1.10) |
| **DG-10** | Withdraw-vs-decline notification copy | Open gap (§3.5) |
| **DG-15** | Expiry gate | Deferred, unscheduled (§3.G1.12) |

#### Left UNDEFINED by this round — not answered, listed so they are not lost

- **DG-18** reference-number **format**.
- **DG-19** value **currency and precision**, and whether it derives from
  engagement fee terms.
- **DG-02** rollback behaviour when acceptance is withdrawn or a new version
  supersedes an accepted one.
- **DG-07** rollback behaviour when the KYC re-check fails at acceptance.
- **DG-04** whether a signature stores a **version id** alongside its body
  digest. The audit's reason that a v1 signature could not be miscounted
  toward v2 relied on v2 being impossible; once versions exist that protection
  is gone.
- **DG-14** the reserved `supersedes` field's shape.
- **DG-23** which SVG treatment applies — sanitise, or convert to raster.
- **DG-13** deleted or deactivated party.

#### Ordering constraint, recorded not scheduled

**DG-02 depends on DG-04.** Acceptance is per-version, so immutable versions
must exist before per-version acceptance can. Nothing else in this round has a
stated prerequisite.


---

## 13. Design Decision Record — versioned agreements

Answers to the open questions raised in **§12 of the versioned-agreements
design** (produced read-only against `f2822f8`; the design itself is not
committed to this repository). Question numbering below is the design's.

**Decided 2026-09-22, by the project owner.** Nothing here is implemented, and
no gate is started.

### Q1 — Proposal authority

**ANSWERED: either party may propose a change.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **LIFECYCLE** Step 3 (adopted at DG-28), **PLAN** |
| Effect | **Confirms** the design's §3 assumption; nothing in the design changes |

### Q2 — Withdraw after a signature exists

**ANSWERED: BLOCKED once any signature exists on any version.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**; **FR-11 silent**; **LIFECYCLE silent** |
| Effect | **Confirms** the design's §3 assumption |

Withdraw remains available while no version carries a signature. The check is
across **all** versions, not only the current one, so a signature on a
superseded version also blocks withdrawal.

### Q3 — Title edits

**ANSWERED: a title edit does NOT create a new version.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **IMPLEMENTATION** (`body_digest`, `agreement_service.py:147-159`) |
| Effect | `title` stays on the agreement, not inside `versions[]` |

The digest covers the **body only**. A title is not part of the signed
instrument, so changing it does not change what anyone signed.

### Q4 — Version cap

**ANSWERED: at most 20 versions per agreement (open + superseded combined).**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Effect | New refusal on the propose-change path |

The 21st proposal attempt is refused with a message telling the parties to
resolve the current version or start a new agreement.

**This cap is what keeps the embedded `versions[]` list valid.** The design's
§1.2 chose an embedded list over a separate collection on the explicit ground
that version count is bounded. **If this cap is ever raised or removed, the
collection-shape decision must be revisited** — an unbounded embedded list
grows the document without limit and eventually breaks the single-document
transaction the signing path relies on (`agreement_service.py:614`, `:1192`).

### Q5 — Does proposing imply accepting?

**ANSWERED: NO. Proposing a version is not an implicit acceptance.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**, consistent with **DG-02** (acceptance is a separate act) |
| Effect | The proposer must explicitly accept their own version, like any other party |

A new version therefore starts with **zero** acceptances, including the
proposer's.

### Q8 — Downloading a superseded version

**ANSWERED: either party may download a superseded version as a PDF.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**; **FR-11.12** covers the finalized agreement only |
| Effect | Extends the PDF route; adds a visual watermark requirement |

Two requirements, both mandatory:

1. The document must be **visually watermarked "SUPERSEDED — NOT EXECUTED"**.
2. It **must not be presented as evidence of agreement.**

This is a presentation rule recorded as decided. Whether such a document has
any standing is **not** addressed here — see Q9, pending counsel.

### Q12 — One-party rows in existing data

**ANSWERED: KEEP THEM AS THEY ARE, AND EXCLUDE THEM FROM THE VERSIONED
MODEL.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**; **FR-11 silent**; **LIFECYCLE silent** |
| Counsel | Not a legal question — no counsel input needed |

**The decision, in three parts:**

1. **The two rows are NOT deleted.** They stay in the collection exactly as
   they are.
2. **They are excluded from the `versions[]` system entirely.** No
   `versions[]`, no `current_version`, no backfill.
3. **Gates V1 through V9 must skip them and leave them untouched.** The skip
   rule is: **skip any agreement with fewer than 2 parties.** Stated as a
   property, not as two hard-coded ids, so a third such row — if one is ever
   found — is skipped by the same rule rather than silently migrated.

**What this leaves true of those rows:** they keep `status: "pending"`, no
digest, and a single party who is not a registered user. They cannot be
signed, executed or downloaded, and nothing in the versioned model will make
them so. They are inert historical records.

**Consequence recorded, not decided:** because they are skipped rather than
migrated, any later code that assumes *every* agreement has `versions[]` must
tolerate their absence. That is a constraint on V1-V9, not a further decision.

Raised by the V0 census (§14); kept here in full because the evidence below is
what the decision rests on.

Two of the 8 rows in the V0 census have only one party. Current code blocks
creating a one-party agreement — `_create_agreement` refuses fewer than two
(`agreement_service.py:~836`) — but these rows already exist.

This needed answering **before V1**, because V3 and later assume two required
signers everywhere (DG-12, and the design's §5 execution rule). It is now
answered above: they are excluded, so that assumption holds for every row the
versioned model touches.

#### Read-only check performed 2026-09-22 — they are NOT the orphaned letters

The obvious hypothesis was that these are the same rows as the six orphaned
engagement letters already awaiting classification (§6 item 9 / MERGE_CHECKLIST
§5). **They are not.** Verified by a read-only query — `find` and `find_one`
only, no writes:

| Set | Ids |
|---|---|
| One-party rows | `e4Cudbr_Zr8_6ayUNKrW-A`, `k08OkiZ9eGfLKTOG-woPag` |
| Orphaned letters | `4-T9z5ytWB7T65K9VXxHxQ`, `__Nz57j2lWmCWOsMG-8TFw`, `SNo8_Cs-24dHKB0ZV_wtww`, `viB8boFhSccF9OuY4KanBQ`, `KVyL7i3Ia-d-Klk8wZJBOg`, `HukSk3NcijoL9PG1P5Jg5w` |
| **Intersection** | **empty — the two sets are disjoint** |

The two populations cannot overlap by construction: an orphaned letter is
defined by having an `engagement_id` whose engagement row is gone, and both
one-party rows have `engagement_id = None`.

#### What was observed about the two rows

Facts only, from the same read-only query:

| Property | Both rows |
|---|---|
| `title` | `"NDA"` — one of the six withdrawn DIY templates |
| `parties` | `['abc']` — a single entry |
| `engagement_id` | `None` |
| `case_id` | `None` |
| `created_by` | `9NqEjxFJhASN_crK3KIO-g` |
| `created_at` | 2026-05-01, 05:59:24 and 06:01:06 — 102 seconds apart |
| Party `abc` exists in `users`? | **No** |
| Creator exists in `users`? | Yes — role `client`, email `test@example.com` |

**These observations are consistent with manual test data from the DIY builder
before it was parked:** a test-account creator, a withdrawn template title, a
party id that is not token-shaped and matches no user, and two rows created
under two minutes apart. **That is an inference, not a verdict, and the
decision is not made here.** Neither row is modified or deleted by this
record.

### Still open after this round

| Q | Question | Status |
|---|---|---|
| **Q6** | Rollback when the DG-07 KYC re-check fails at engagement acceptance | **RESOLVED** — placement confirmed before the first claim (§16 H-6, §17 R5-2): a check before the engagement claim writes nothing, so there is nothing to roll back. Open only if the check is placed between the two claims |
| **Q7** | Reference-number format (DG-18); value currency and precision (DG-19) | **OPEN — owner decision.** Already recorded UNDEFINED in §12 |
| **Q9** | Whether a signature on a superseded version has any standing, and how the certificate should describe it | **OPEN — PENDING COUNSEL.** No legal conclusion is stated. The design keeps such a signature as history and excludes it from execution; that is a data rule, not a statement about its effect |
| **Q10** | Whether auto-accepting an engagement letter on the client's behalf (design §6) adequately represents their assent, given Q5 and DG-02 require explicit acceptance everywhere else | **OPEN — PENDING COUNSEL.** No legal conclusion is stated |
| **Q11** | Whether the evidence certificate may state that a version *was superseded*, or only list what was recorded | **OPEN — PENDING COUNSEL.** No legal conclusion is stated |

**Q10 is the one that interacts with a decision made above.** Q5 settles that
proposing is not accepting, and DG-02 settles that acceptance is a separate
act — while design §6 has the system auto-accept a letter for both parties so
that Producer A's behaviour does not change. Those sit in tension. It is
recorded, not resolved, and no legal conclusion is drawn.


---

## 14. V0 census — run on 2026-09-22, commit `f2822f8`

Read-only aggregation, `$group` and `$sort` only. The pipeline was asserted
free of `$out`/`$merge` before connecting, and the only driver calls used were
`aggregate` and `count_documents`. Nothing was written.

### Raw result

**8 rows total.**

| n | status | has `version` | has `body_sha256` | is letter | max version | max parties | signed in group |
|---|---|---|---|---|---|---|---|
| 5 | `pending` | no | no | yes | — | 2 | 0 |
| 2 | `pending` | no | no | **no** | — | **1** | 0 |
| 1 | `executed` | no | no | yes | — | 2 | 2 |

**Collection-wide extremes:** `maxVersion = None` · `maxParties = 2` ·
`minParties = 1`

**Partly signed** (≥1 signature but not all): **0** — 7 `pending` and 1
`executed`, none partial.

**Rows with a party count other than 2: 2.**

### Two things §7 of the design did not anticipate

**1. Two rows have ONE party.** The design assumed every row is two-party, and
current code enforces it — `_create_agreement` refuses fewer than two
(`agreement_service.py:~836`) and more than two (`:~844`). These two rows are
`pending`, not letters, and predate that guard. They cannot be migrated into a
two-party model without a decision: a one-party agreement has no counterparty
to accept or sign, so **every** step of the versioned design is undefined for
them.

**OWNER DECISION — Q12. ANSWERED 2026-09-22 at §13:** the two rows are kept
as they are, not deleted, and **excluded from the versioned model**. V1-V9
skip any agreement with fewer than 2 parties.

> **CORRECTED 2026-09-22.** This paragraph originally read that these rows are
> "likely the same population as the six orphaned engagement letters". A
> read-only check has since shown the two sets are **disjoint** — see §13. The
> speculation was wrong and is struck here so it is not carried forward.

**2. NO row has a `body_sha256` — not one of the eight.** The design's §7
said A/B rows carry a "digest at creation" on the strength of
`_create_agreement:898`. That is true of rows created by today's code and
false of every row actually in the database: all eight predate it. The
consequence is broader than the single pre-3C executed letter the earlier
audit identified — **every** row would migrate to `versions[0].body_sha256 =
null`, and any of them that later reached `executed` would be refused a PDF by
`agreement_pdf.py:125`.

This does not change a decision. It corrects a factual assumption in the
design's migration section, and it means the "pre-3C rows refuse to render"
note in the MERGE_CHECKLIST describes the whole collection, not an edge case.

### What the census confirms

- **No `version` field anywhere** — consistent with `_create_agreement` never
  writing one. There are also **zero drafts**, so Producer C has never been
  used against this database.
- **No partly-signed rows**, so the V3 migration has no mid-flight signature
  state to preserve.
- **Max 2 parties**, so nothing exceeds the design's assumed maximum; the
  deviation is in the other direction.


---

## 15. Decision Record — Round 3

**Decided 2026-09-22, by the project owner.** Recorded as given. Nothing here
is implemented, no gate is started, and the NEEDS REVIEW list below is
deliberately unresolved.

Round 3 changes the shape of the module, not only its details. Where a decision
reverses a position recorded in §11-§13, the reversal is marked, so no reader
takes the earlier text as current.

---

### R3-1 — The engagement letter requirement is REMOVED

**ANSWERED: booking or accepting a lawyer is enough to start billing. No signed
step is required before a lawyer can invoice.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Status | **PENDING COUNSEL** |
| Code change? | **YES — large. Implementation gap, not scheduled** |

**This REPLACES the rule "billing requires an executed engagement letter."**
That rule is implemented today at `payment_service.py:79`
(`_require_executed_engagement_letter`), called at `:187` before a fee request
is created. Under R3-1 that gate no longer expresses the product rule.

**Stated plainly, as the owner asked: this removes any signed record of fee
terms.** After R3-1 there is no point in the system at which the client
countersigns a price. The executed engagement letter was the only such record —
`payment_service.py:82-86` describes it as "the only place in this system where
the CLIENT has agreed to a price".

**Recorded history, as fact and not as argument.** The same file documents the
incident the gate was written after (`payment_service.py:87-92`): a lawyer
accepted an engagement, set a fee of Rs 500,000 the client had never seen, and
raised a fee request while the letter sat unsigned — HTTP 200 — while the client
could not decline, because `accepted` was terminal. That is what the code
records. Whether the absence of a signed record is acceptable is not an
engineering question, and no conclusion is drawn here.

**PENDING COUNSEL.** Whether a lawyer may lawfully bill a client without any
signed agreement is a legal question. It is not answered in this document, and
nothing in this section should be read as an opinion on it.

---

### R3-2 — The DIY builder (Product B) is KEPT

**ANSWERED: keep it. The owner will supply new templates to replace the six
withdrawn ones. A client may edit a template before sending it.**

> **CLARIFIED 2026-09-22.** This first read "new *verified* templates". Asked
> directly, the owner's position is: **the templates are believed sound, but no
> review record exists** — no named reviewer, no review date, no version, no
> jurisdiction. Recorded as the owner's statement, not as established
> verification. The registry rules in §13 are unchanged, so **the
> withdrawn-template guard stays ON for the new templates** until those details
> exist. The word "verified" is removed above to avoid asserting something the
> record does not support.

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** (D1, DG-25 revised) |
| Code change? | **YES — unparking, plus template loading. Not scheduled** |

Consistent with **DG-25 (revised)**, §11: the builder was already not to be
deleted. R3-2 goes further — it is kept *and* to be populated, rather than kept
parked indefinitely.

**Client editing of a template is new.** No recorded decision previously said a
client may edit template wording before sending. The parked wizard allowed it;
R3-2 records that as intended rather than incidental.

---

### R3-3 — Product C gains templates

**ANSWERED: a lawyer may send one of their own templates to their own client,
not only free-typed text.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES — a lawyer-owned template store. Not scheduled** |

Today Product C supplies no templates at all: the lawyer types the terms, and
the system deliberately offers nothing. R3-3 adds lawyer-owned templates as a
first-class feature.

---

### R3-4 — "Ask a lawyer to write this for me"

**ANSWERED: add this option inside the DIY builder. A client may request an
agreement from a lawyer instead of building it themselves.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES — a new request flow. Not scheduled** |

---

### R3-5 — The engagement / hire flow moves to the appointment flow

**ANSWERED: the whole hire flow leaves the agreements module. Request, propose
terms and accept move to appointments.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Status | **PENDING COUNSEL** (inherits R3-1) |
| Code change? | **YES — the largest in Round 3. Not scheduled** |

R3-1 removed the letter. R3-5 moves what produced it. Together they mean the
agreements module stops owning "a client hires a lawyer" entirely.

**What reads engagements today**, and therefore what this move has to carry or
replace — verified at `0947ad5`:

| Consumer | What it uses engagements for |
|---|---|
| `payment_service.py:79` | The fee gate. Superseded by R3-1, but see NR-2 |
| `lawyer_service.py:689` | Review eligibility — "an accepted engagement OR a completed appointment" |
| `user_service.py:193-204` | Account closure blockers — open engagements on both sides |
| `engagement_service.py:887` | The case claim and release: `case.lawyer_id` |
| `agreement_service.py` | Gate 2's reversal and Gate 3A's reverse arrow |
| `constants.py` | `EngagementStatus`, `ENGAGEMENT_RETAINED_STATUSES`, `ENGAGEMENT_OPEN_STATUSES` |
| `indexes.py` | `uniq_pending_engagement` |

**`appointment_service.py` does not reference engagements today** — one passing
comment at `:605` and no code. This is a new integration, not a relocation of
existing wiring.

**One observation, recorded as fact, not as an objection:**
`lawyer_service.py:689` already treats *"a completed appointment"* as an
alternative basis for review eligibility, so the appointment module is already
a recognised relationship signal. That is the nearest existing precedent for
R3-5; it is not the same thing as owning the hire flow.

---

### R3-6 — A client may send an agreement to ANY registered user

**ANSWERED: client-to-client agreements are allowed. The counterparty need not
be a lawyer.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES — replaces the authorisation basis. Not scheduled** |
| Supersedes | **NR-14**, which listed this as undecided |

This **replaces D2's counterparty rule**, which requires a mandatory `case_id`
and confines parties to `{case.client_id, case.lawyer_id}`
(`_authorise_case_link`). A case row holds one client slot and one lawyer slot,
so "any registered user" cannot be expressed in the current model at all.

**Recorded consequence, stated as fact.** The case was not merely a link — it
was the *authorisation*. Removing it leaves nothing deciding who may send an
agreement to whom. The plan already describes what that state looks like, at
§3.G1.7 **B3**: *"no relationship check and no rate limit, so any authenticated
user can name any `user_id` and push an `AGREEMENT_CREATED` notification at
them"*, recorded there as **"masked today only by the park flag"**.

R3-2 unparks. So B3 stops being masked, and **what replaces the case as the
authorisation basis is undefined** — tracked as NR-15 and NR-16. No conclusion
is drawn here and no replacement is proposed.

---

### R3-7 — A case is OPTIONAL

**ANSWERED: a user does not need a case in AttorneyAI to make an agreement with
another registered user.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES. Not scheduled** |
| Supersedes | **D2's mandatory `case_id`**, and completes R3-6 |

**What the code does today.** `_create_agreement` refuses outright when there
is neither a case nor an engagement:

> *"An agreement must be attached to a case you are a party to. Creating one
> for an unrelated user is not permitted."*

That refusal is the mandatory-case rule. Under R3-7 it no longer expresses the
product rule, and `case_id` becomes an optional link rather than a
precondition.

**What stays true.** An agreement MAY still carry a `case_id` — a retainer for
a real matter is the normal case, and §3.G1.4 already allows case-linked
agreements with no engagement. R3-7 makes the link optional, not forbidden.

**What this settles, and what it does not.** NR-16 asked what replaces the case
as the authorisation basis. R3-7 answers half of it: **a case is not required.**
It does not say what, if anything, decides who may send an agreement to whom.
That half stays open — see NR-16 as restated below.

---

---

### R3-8 — Who may send an agreement to whom

**ANSWERED, in the owner's words:**

> Any registered user may create and send an agreement to any other registered
> user. No prior case, appointment, engagement, or connection between the
> parties is required. `case_id` remains optional and may associate an
> agreement with an existing matter when applicable. Sending is subject to
> authentication, two-party agreement rules, signing requirements, and platform
> abuse/rate controls.

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES. Not scheduled** |
| Closes | **NR-16**, and the open half of **NR-15 / B3** |

**This is the replacement authorisation rule.** D2 made a shared case the
authorisation; R3-7 made the case optional; R3-8 states what governs instead.
Membership of the platform is the relationship — there is no second
relationship test.

#### The four guards the owner named, and where each stands today

| Guard | Status at `0947ad5` |
|---|---|
| **Authentication** | **In place.** Every agreement route depends on `get_current_user` or `require_lawyer` |
| **Two-party rules** | **In place.** Exactly two parties, refused above and below that; duplicate parties refused. Consistent with DG-01 and DG-12 |
| **Signing requirements** | **In place, and extended by §13.** Explicit consent at send, digest check, all parties required for execution; acceptance-before-signing is decided but not built |
| **Platform abuse / rate controls** | **PARTIAL — this is the gap** |

#### The rate-control gap, stated precisely

`_LIMIT_SEND = "10/hour"` exists and is applied to **one** route:
`POST /agreements/drafts/{id}/send` (`routes/agreements.py:23, 205`). That is
Producer C's send.

**`POST /agreements` — Producer B's create-and-send, the path R3-2 unparks —
carries no rate limit at all** (`routes/agreements.py:26-31`). Creating an
agreement notifies the counterparty, so under R3-8 that route reaches any
registered user with no relationship test and no limit.

This is the condition §3.G1.7 records as **B3**, and the plan notes it is
*"masked today only by the park flag"*. R3-8 supplies the missing half of the
answer — abuse controls are required — so B3 stops being an open question and
becomes **scheduled work**: the control has to exist before Product B unparks.

**What is NOT decided here:** the limit's value, its window, whether it is per
sender, per recipient or per pair, and what happens on breach. D6 set `10/hour`
for Producer C's send; nothing states it carries to this path. Tracked as
NR-21.

---

---

### R3-9 — Hiring is a step AFTER the appointment

**ANSWERED: the appointment is a meeting. Hiring remains a separate step, with
fee terms, and that step lives in the appointment area rather than in
agreements.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES. Not scheduled** |
| Refines | **R3-5** |

**This narrows R3-5 in an important way: the hire record does not disappear.**
Request → propose terms → accept, with a fee, still exists as a concept. What
changes is where it lives and that it no longer produces a signed letter
(R3-1).

So the work is a **relocation plus a de-coupling**, not a deletion. The
consumers listed under R3-5 (case claim, review eligibility, closure blockers,
the status enum and the unique index) still have something to read — it is
reached from a different place.

---

### R3-10 — The fee is shown at booking

**ANSWERED: the lawyer's rate is displayed when the client books, or when the
lawyer accepts. The client sees the price. Nothing is signed.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Status | **PENDING COUNSEL** (inherits R3-1) |
| Code change? | **YES. Not scheduled** |

**What exists today.** `hourly_rate` is on the lawyer profile
(`schemas/user.py:63`). Fee *terms* — amount and type, with labels for hourly,
fixed and contingency — live on the **engagement**, formatted by `_fee_str`
(`engagement_service.py:37, 77-80`) and shown in the letter.

**What does not exist today.** `appointment_service.py` has **no fee or rate
handling at all** — a search for fee/rate in that service returns only
unrelated comments. Showing a rate at booking is new work, not a re-use.

**Recorded plainly:** under R3-1 and R3-10 the client SEES a price but does not
countersign one. The system will hold a displayed rate, not an agreed one. This
is recorded as a fact about the design, not as an assessment of it.
**PENDING COUNSEL**, as R3-1 already is.

---

### R3-11 — "Ask a lawyer" goes to one chosen lawyer

**ANSWERED: the client picks a specific lawyer. That lawyer receives a request
and may accept or decline, then writes and sends the agreement.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES — a new request/accept flow. Not scheduled** |
| Refines | **R3-4** |

A directed request, not an open marketplace. The nearest existing shape is
`request_engagement` → `propose_terms` → `accept_terms`: a directed ask that the
recipient may refuse. That is a precedent for the shape, not a plan to reuse the
code.

**Not decided here:** whether the lawyer may charge for writing it, and what
happens if they decline — tracked as NR-22.

---

### R3-12 — ONE agreement flow for everyone

**ANSWERED: there is a single "create an agreement" flow. Being a lawyer or a
client changes only which templates you see.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES — merges two producers. Not scheduled** |
| Completes | **DG-08**, which already had B and C sharing one rule set |
| Closes | **NR-12, NR-13** |

Products B and C stop being separate flows. DG-08 had already put them on one
rule set; R3-12 goes further and makes them one screen.

**Consequences, recorded:**

- **"Ask a lawyer" (R3-11) is not a fourth producer.** It is a request that
  results in the same single flow, authored by the lawyer. NR-12 closes.
- **The role check changes meaning.** Producer C requires `require_lawyer` on
  its routes and a KYC check on its author (D5). With one flow open to any
  registered user (R3-8), a role gate on the flow itself no longer fits.
  Whether D5's KYC requirement survives, and on what, is **NR-23**.
- **Two template sets, one picker.** R3-2 gives clients owner-supplied
  templates; R3-3 gives lawyers their own. Under one flow these are two sources
  feeding one gallery, filtered by who is looking.

---

---

### R3-13 — A lawyer may be the AUTHOR without being a party

**ANSWERED: when a client asks a lawyer to write an agreement, the lawyer
writes it and the CLIENT sends it to a third person. Parties = client + third
person. The lawyer does not sign.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES — a new concept in the data model. Not scheduled** |
| Refines | **R3-4, R3-11** |

**This is the first time author and party come apart.** Today they are the same
person by construction:

- `_create_agreement` puts the creator into `parties` if not already there;
- `create_draft` builds `parties` from exactly `(creator_id, client_id)`;
- `created_by` is therefore always one of the two signers.

Under R3-13 an agreement has **three people on it**: two parties who sign, and
an author who does not. `created_by` stops implying "party".

**Consequences, recorded as facts — none of them decided here:**

| Area | What changes |
|---|---|
| Party rules | Still exactly two SIGNERS (DG-01, DG-12 hold). The author is a third role, not a third party |
| `created_by` | No longer implies membership. Every reader that treats it as "a party" needs re-checking |
| Draft privacy | `_refuse_if_someone_elses_draft` grants the author access via `created_by`; after the client sends it, whether the lawyer keeps visibility is **undefined** — NR-24 |
| Visibility in lists | `visible_to` returns rows where `created_by == user` OR the user is a party, so an author would keep seeing an agreement between two other people indefinitely — NR-24 |
| The evidence certificate | It lists parties and signatures. Whether the author is named on it, and how, is **undefined** — NR-25 |

**A tension with R3-11, recorded not resolved.** R3-11 says the lawyer "writes
and sends". R3-13 says the lawyer is not a party. In the current model sending
IS signing for a lawyer-authored agreement — `sign_and_send_draft` captures the
sender's signature in the same call. A non-party cannot sign, so either the
lawyer hands the draft back to the client to send, or sending is decoupled from
signing on this path. **NR-26.**

---

### R3-14 — A client may ask ANY lawyer on the platform

**ANSWERED: the picker is not limited to verified lawyers. Any user with the
lawyer role may be asked.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Status | **PENDING COUNSEL** |
| Code change? | **YES. Not scheduled** |

**Stated plainly: an unverified lawyer may draft an agreement that two other
people then sign.** That is the direct consequence, recorded as a fact about
the design.

**What this sits against.** **D5** (§11, `PRODUCT_PLAN:262`) decided that a
lawyer must be KYC-verified to author or send an agreement, checked at both
points — implemented as `_require_verified_lawyer`
(`agreement_service.py:408, 467, 550`). R3-14 does not repeal D5; it creates a
path D5 did not contemplate, because under R3-13 the lawyer authors without
sending and without signing.

Whether D5 still applies, to what, and at which point, is **NR-23** —
restated below and now sharper.

**Precedent, for accuracy.** The parked builder's counterparty picker was
populated from **verified** lawyers only (`ModAgreements.jsx:509-511`, *"Verified
lawyers are the counterparties available on the platform"*). R3-14 is a
departure from that, not a continuation of it.

**PENDING COUNSEL.** Whether an unverified person may draft legal documents for
others on this platform is a legal and regulatory question. No conclusion is
drawn here.

---

---

### R3-15 — The drafting lawyer's name appears on the agreement

**ANSWERED: when a lawyer drafts an agreement for someone else (R3-13), that
lawyer's name appears on the agreement they drafted.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES. Not scheduled** |
| Closes | **NR-25** |

Under R3-13 the lawyer is the author and not a party, so without this rule they
would appear nowhere: the document lists parties, and they are not one. R3-15
makes the drafter visible on the document itself.

**What is decided:** the name appears on the agreement.

**What is NOT decided here, and is not invented:**

- the wording or label used (for example "Drafted by", or anything else);
- whether it also appears on the evidence certificate, which is a separate
  document with its own rules — **NR-27**;
- whether anything beyond the name is shown, such as a firm or bar number.

The certificate question is kept separate deliberately: §13 Q9-Q11 record that
what the certificate may state is **pending counsel**, and R3-15 is a decision
about the agreement, not about the evidence document.

---

### R3-16 — Version authorship need not be displayed between parties

**ANSWERED: in a normal two-party flow, when one party edits and a new version
is created, the version does not need to show WHO made the edit. Both parties
are already named on the agreement, and both must accept a version before it
can be signed.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**, consistent with **Q5** (proposing is not accepting) |
| Code change? | **NO — this removes a display requirement rather than adding one** |

The reasoning as given: both names appear on the agreement, and per Q5 and DG-02
neither party is bound until they have explicitly accepted that exact version.
Consent is therefore established by the acceptance record, not by attributing
each edit.

**A distinction recorded so it is not lost: this is a DISPLAY rule, not a
storage rule.**

The versioned design stores `versions[].author_id` on every version, and it is
load-bearing for three things unrelated to display:

1. **Q4's cap** — 20 versions per agreement needs to count them;
2. **the audit trail** — every transition already records `actor_id`;
3. **acceptance logic** — Q5 requires the proposer to accept their own version,
   which cannot be checked without knowing who proposed it.

R3-16 says that value need not be **shown to the other party**. It does not say
it is not recorded. If the intent were to stop recording it, Q5 could not be
enforced — flagged here rather than assumed either way.

**Scope:** R3-16 covers versions authored by a PARTY. It does not override
R3-15, which is about a non-party lawyer drafting the original.

---

---

### R3-17 — The handover flow: the drafter hands over, the party sends

**ANSWERED, as the owner drew it:**

```
Ahmed writes                    Ahmed = the lawyer who was asked
   |
Ahmed submits / hands over draft
   |
Ali reviews                     Ali = the client who asked
   |
Ali sends to Bilal              Bilal = the counterparty
   |
Ali + Bilal sign
```

The agreement itself carries **"Drafted by Ahmed"**. Ahmed does not sign; he is
a third person.

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES. Not scheduled** |
| Closes | **NR-26** |
| Refines | **R3-11, R3-13, R3-15** |

**This resolves the tension NR-26 recorded.** R3-11 read as though the lawyer
"writes and sends"; R3-13 made the lawyer a non-party; and sending currently
captures the sender's signature, which a non-party cannot give. The handover
step removes the conflict without changing how signing works:

- **the lawyer never sends** — he submits the draft to the person who asked;
- **the sender is always a party** — Ali sends, Ali signs;
- `sign_and_send_draft`'s existing shape survives: whoever sends, signs.

**R3-15 is now specific.** The label is **"Drafted by {name}"**. Earlier that
was recorded as decided-in-substance but open in wording; the wording is now
given.

**Two new consequences, recorded and NOT decided:**

| # | Consequence |
|---|---|
| **NR-28** | **May Ali edit the draft after handover?** "Ali reviews" may or may not include changing the wording. Today `update_draft` refuses anyone who is not `created_by` (`agreement_service.py:~474-478`), so Ali could not edit Ahmed's draft without either transferring `created_by` or decoupling edit rights from it |
| **NR-29** | **What is the state of a draft between handover and sending?** It is no longer Ahmed's working copy and not yet sent. The status enum has `draft` and `pending` and nothing between; whether handover is a status, a flag, or merely a change of who may act is undefined |

**NR-24 is unchanged by this.** Whether Ahmed keeps visibility of the agreement
after handing it over — and after Ali and Bilal sign it — is still open.

---

---

### R3-18 — The requesting party may edit after handover

**ANSWERED: after the lawyer hands over, the requesting party may edit the
draft, until it is sent and signed.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES. Not scheduled** |
| Closes | **NR-28** |

In the R3-17 flow: Ahmed hands over, and **Ali may change the wording** before
sending it to Bilal.

**Consequence: `created_by` stops controlling edit rights.** Today
`update_draft` refuses anyone who is not `created_by`
(`agreement_service.py:~474-478`). Under R3-18 the editor is Ali, who is not
`created_by`; under R3-20 the `created_by` lawyer may *not* edit. So the check
cannot remain "are you `created_by`". Whether `created_by` transfers at
handover or edit rights become a separate concept is an implementation choice,
not a further decision.

---

### R3-19 — A new `awaiting_sender` state

**ANSWERED: add `awaiting_sender` for the period after the lawyer hands over
and before the requesting party sends.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES — a new status value. Not scheduled** |
| Closes | **NR-29** |

```
draft ──hand over──► awaiting_sender ──send──► pending ──all sign──► executed
```

**This is the first new status value these plans have accepted, and the
reasoning that rejected earlier ones does not apply here.** §7.2 and §3.G1.10
both argue against new statuses, but both are specifically about **terminal**
states — `declined`, `withdrawn`, `expired` — where the argument was that
`cancelled` plus `cancellation_source` already carries every distinction.
`awaiting_sender` is an **intermediate** state describing who may act, which no
existing field expresses. The earlier objection is not being overridden; it is
about a different thing.

**Consequence: every reader that branches on status must be re-checked.** The
known ones, at `0947ad5`:

| Reader | Why it matters |
|---|---|
| `visible_to` (`agreement_repo.py:22`) | Drafts are author-only; `awaiting_sender` has a different rightful reader |
| `update_draft`'s filter — `status: DRAFT` | Editing must now be allowed in the new state too (R3-18) |
| `_refuse_if_someone_elses_draft` | Its privacy rule is written against `draft` |
| The D7 cap — counts `draft` rows only (`MAX_ACTIVE_DRAFTS_PER_LAWYER`) | Whether a handed-over draft still occupies the lawyer's slot is **NR-33** |
| `sign_and_send_draft`'s filter — `status: DRAFT` | Sending now happens from `awaiting_sender` |
| The list status filter and both screens' pills | A fifth value needs a label under FR-11.1's vocabulary |

---

### R3-20 — The drafting lawyer keeps read-only access, permanently

**ANSWERED: after handover, and after execution, the drafting lawyer retains
READ-ONLY access. No party rights, no signing, no editing.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES. Not scheduled** |
| Closes | **NR-24** |

**This formalises a split that does not exist today.** `created_by` currently
grants both read and write: read through `_refuse_if_someone_elses_draft` and
`visible_to`, write through `update_draft`'s author check. R3-20 keeps the read
half and removes the write half; R3-18 gives the write half to someone else.
After both, `created_by` means **"drafted this, may read it forever, may not
change it"**.

**Recorded plainly, as a fact about the design:** Ahmed can read an executed
agreement between Ali and Bilal indefinitely. Bilal never chose Ahmed and may
never have met him. Whether Bilal is told that a third person can read their
signed agreement is **NR-32** — not decided here, and no conclusion is drawn
about it.

---

---

### R3-21 — Any edit after handover creates a new immutable version

**ANSWERED: a body edit after handover creates a NEW version. An existing
version is never mutated.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**, consistent with **DG-04** |
| Code change? | **YES. Not scheduled** |
| Closes | **NR-30** |

The ambiguity NR-30 recorded was that a post-handover edit happens **before
send**, when the digest is not yet frozen — `body_sha256` is `None` on a draft
(`agreement_service.py:433`) and stamped only at send (`:622`). R3-21 resolves
it in favour of immutability: versioning does not wait for the freeze.

**Consequence:** the version number can advance while `body_sha256` is still
null. A version's digest is computed when that version is created, not when the
agreement is sent — otherwise "immutable" would only begin at send, and the
handover draft Ahmed wrote could be silently overwritten.

---

### R3-22 — Author attribution is version-aware

**ANSWERED: the initial version may display "Drafted by Ahmed". If a later
version is authored by another person, display "Originally drafted by Ahmed".**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES. Not scheduled** |
| Closes | **NR-31** |
| Refines | **R3-15** |

The label is **derived per version**, not stored once. `versions[].author_id`
(retained by R3-16) is what makes the distinction computable: compare the
author of version 1 against the author of the version being displayed.

**This keeps the statement true as the document changes** — the concern NR-31
recorded. Ahmed drafted the original; if Ali rewrote it, the document says so
rather than continuing to attribute Ali's words to Ahmed.

**Not decided here:** the wording for a third case — a later version authored by
Ahmed again after Ali edited. R3-22 names two forms, not three. **NR-35.**

---

### R3-23 — `awaiting_sender` does not consume the D7 quota

**ANSWERED: a handed-over agreement does not count against the drafting
lawyer's active-draft cap.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**, refining **D7** |
| Code change? | **NO — this is what the status change already does** |
| Closes | **NR-33** |

The cap counts `status == draft` for that `created_by`
(`agreement_service.py:415`). Once the status becomes `awaiting_sender` the row
falls out of the count automatically.

**Recorded because it was accidental, and is now intended.** NR-33 flagged that
this behaviour falls out of the status change rather than a decision — so a
lawyer could hand over twenty drafts and start twenty more. R3-23 confirms that
is wanted: the cap bounds *live drafting work*, and a handed-over draft is no
longer the lawyer's work.

---

### R3-24 — 10 sends per hour per user, on all sending

**ANSWERED: apply a 10 sends/hour/user limit to agreement sending, for all
authenticated users. Reuse the existing rate-limit infrastructure.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**, extending **D6** |
| Code change? | **YES — a decorator on one more route. Not scheduled** |
| Closes | **NR-21** |

**What exists.** `_LIMIT_SEND = "10/hour"` is applied to exactly one route:
`POST /agreements/drafts/{id}/send` (`routes/agreements.py:23, 205`). The
limiter is `core/rate_limit.py` with `key_func=_user_or_ip`, already
per-authenticated-user.

**What R3-24 adds.** The same limit on the other sending path —
`POST /agreements` (`routes/agreements.py:26`), which notifies the counterparty
immediately and is unlimited today. That is the route R3-2 unparks and R3-8
opens to any registered user.

**Scope, as stated:** per user, per hour, on **sending**. Editing stays
unlimited (D6's reasoning: throttling autosave loses work). Draft creation stays
bounded by the D7 cap rather than a rate.

**Not decided:** what the user sees on breach. **NR-36.**

---

### R3-25 — Billing follows the validated Hire, not an executed letter

**ANSWERED (wording revised 2026-09-22, Round 5 — §17 R5-5): Appointment is
the required entry path for a new hire. Engagement remains the authoritative
Hire relationship. Billing is governed by the validated Engagement/Hire
relationship and its billing eligibility rules; the appointment itself is not
the billing relationship. An executed agreement or engagement letter is NOT
required for billing.**

> *Original wording, superseded:* "billing requires an active billable
> hire/relationship established by the Appointment → Hire flow." Revised
> because "active" conflicts with billing a terminated Engagement (§17 R5-5).

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**, completing **R3-1** and **R3-9** |
| Status | **PENDING COUNSEL** (inherits R3-1) |
| Code change? | **YES. Not scheduled** |
| Closes | **NR-2** |

**This names the replacement the audit found missing.** The current gate
(`payment_service.py:79`, called at `:187`) performs **two** checks, and only
the second is about the letter:

1. an engagement in `ENGAGEMENT_RETAINED_STATUSES` exists for this case and
   lawyer — *the relationship check*;
2. that engagement's agreement is `executed` — *the letter check*.

R3-1 removed (2). R3-25 replaces (1) with the hire record from the Appointment →
Hire flow. **Both halves are accounted for**, which NR-2 as originally written
did not capture.

> **Superseded in part by §17 (R5-5, R5-12):** (1) is **retained and
> validated**, not replaced — billing is governed by the Engagement for (case,
> lawyer, client), with `case.lawyer_id` also required while it is `accepted`
> or `completed`, and new fee requests refused once it is `terminated`. The
> appointment is the entry path to a new hire, not the billing relationship.

**SEQUENCING RISK, recorded as a constraint on implementation.** The
Appointment → Hire flow does not exist yet — `appointment_service.py` has no
hire or fee handling. If the letter gate is removed before that flow exists,
there is a window in which **nothing gates a fee request at all**. The two
changes are order-dependent: the replacement must exist before the removal
lands. This is a fact about sequencing, not a further decision.

> **Restated by §17 R5-11:** the replacement that must land first is the
> **validated billing predicate** (step 2), before letter removal (step 4). The
> Appointment → Hire entry (step 1) is not what gates billing.

**A second dependent** — ~~still open~~ **closed by H-2 / §17 R5-6.**
`engagement_repo.py:95` matches `letter.status == EXECUTED` for **review
eligibility**, not billing. R3-25 does not address it — see **NR-18** (closed).

---

### R3-26 — `case_id` is a reference, never an ownership claim

**ANSWERED: `case_id` is optional and may only reference a case the
authenticated user is authorised to access or participate in. Agreement
creation and signing must never establish or change case ownership.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**, completing **R3-7** |
| Code change? | **YES. Not scheduled** |
| Closes | **NR-34** (raised by the 2026-09-22 audit) |

**Two distinct rules:**

1. **Read-side authorisation survives.** A user may attach a `case_id` only for
   a case they are authorised on. This replaces `_authorise_case_link`
   (`agreement_service.py:327-345`), which today requires the creator to be the
   case's client or lawyer AND confines both parties to that case — far
   stricter than a reference check.
2. **No ownership mutation, ever.** The agreement module must not write
   `case.lawyer_id`.

**What this changes in current code.** Agreement creation and signing already
never write `case.lawyer_id` — they only read it at `:306` and `:333` to
authorise. But **one agreement path does write it**: `:1553-1556` releases the
case when an engagement letter is declined (Gate 2's reversal). That write is
removed along with the letter requirement (R3-1), so rule 2 is satisfied by
that removal rather than by a separate change.

---

### R3-27 — `awaiting_sender` visibility is explicit

**ANSWERED: the author retains read-only access; `current_editor_id` may read
and edit; the other party must NOT see the unsent agreement.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN**, completing **R3-19, R3-20** |
| Code change? | **YES. Not scheduled** |

| Who | `awaiting_sender` |
|---|---|
| `author_id` (the lawyer) | **read only** |
| `current_editor_id` (the requester) | **read and edit** |
| The other party (Bilal) | **no access — must not see it exists** |

**This closes the highest-risk item the audit found.** `visible_to`
(`agreement_repo.py:47`) excludes non-authors only from rows whose status is
`draft`:

> `{"parties.user_id": user_id, "status": {"$ne": DRAFT}}`

A fifth status added without changing that line makes `awaiting_sender` **not
draft**, so the counterparty would see an unsent agreement — silently, with no
error. R3-27 makes the rule explicit rather than leaving it to the shape of a
`$ne`.

---

### R3-28 — Four separate fields, replacing `created_by`

**ANSWERED: keep `author_id`, `parties`, `current_editor_id` and `sender_id` as
separate concepts. Do not overload `created_by`.**

| Field | Value |
|---|---|
| Date | 2026-09-22 |
| Decided by | Project owner |
| Sources | **PLAN** |
| Code change? | **YES — schema plus every call site. Not scheduled** |

| Field | Meaning | Rule |
|---|---|---|
| `author_id` | Who drafted it | Never implies party. Read-only forever (R3-20) |
| `parties[2]` | The two signers | Exactly two (DG-01), all required (DG-12) |
| `current_editor_id` | Who may edit now | Moves at handover (R3-18) |
| `sender_id` | Who sent it | **Must be in `parties`** — enforces R3-17's "whoever sends, signs" |

**The audit found `created_by` carrying six authorities**, at
`agreement_service.py:415` (D7 subject), `:448`/`:927` (writer), `:472` (edit),
`:513` (delete), `:556` (send/sign), `:1099`/`:1126` (read). Three of the six
move to other fields; the split cannot be done by renaming.

**Also affected:** `agreement_repo.py:49` (`visible_to`'s draft branch) and
`schemas/agreement.py:95, 131` (both response models expose `created_by`).

---

---

## NEEDS REVIEW — reopened by Round 3

Listed so nothing is lost. **None of these is decided here**, and none should be
read as leaning either way. One line of reason each.

### Reopened by R3-1 — the engagement letter requirement is gone

| # | Item | Why it needs review |
|---|---|---|
| NR-1 | The letter producer | **DECIDED (§17 R5-8):** the production call at `engagement_service.py:365` and its rollback are removed. `create_pending_engagement_letter` itself is **kept** as legacy test-fixture support during migration testing; it may later move into test support |
| ~~NR-2~~ | ~~The fee gate~~ | **CLOSED 2026-09-22 by R3-25 (revised in Round 5).** Billing follows the validated Engagement/Hire relationship — §17 R5-5. SEQUENCING RISK stands: the replacement must exist before the removal lands |
| ~~NR-3~~ | ~~Gate 2's decline reversal~~ | **CLOSED 2026-09-22 by R5-12 (C-A).** Removed: a legacy letter decline neither reverses the Engagement nor writes `case.lawyer_id`. Historical `decline_source` stays readable |
| NR-4 | Gate 3A's reverse arrow | **DECIDED (§17 R5-4):** retain the transactional termination, case release **and** the cancellation of a linked pending legacy letter. Remove only the `no_letter` anomaly (`engagement_service.py:968`), which would otherwise fire on every new termination. `letter_missing` / `letter_superseded` remain |
| NR-5 | `scripts/engagement_letter_reconcile.py` | **Retain read-only** until the six orphans are classified; it is the only tool that lists them |
| NR-6 | The six orphaned engagement letters | Still unclassified; R3-1 changes what they represent but not that a human must classify them |
| ~~NR-7~~ | ~~DG-07 KYC re-check~~ | **CLOSED 2026-09-22 by H-6.** Before the atomic claim in `accept_terms` |
| NR-8 | Fee-gate copy | **Remove** the four letter-state messages. Replacement copy distinguishes "no valid hire relationship for this case" from "this engagement has been terminated; new fee requests are refused" (§17 R5-5, C-B). Wording itself not decided |

### Reopened by R3-2 and R3-3 — real templates in play

| # | Item | Why it needs review |
|---|---|---|
| ~~NR-9~~ | ~~D2 — the counterparty rule~~ | **SUPERSEDED 2026-09-22 by R3-6**, which replaces D2 outright. The open part moved to NR-16: what authorises a send now |
| NR-10 ✅ | The template registry rules — named reviewer, review date, version, jurisdiction, unexpired review period (§13, DG-25 revised) | **CONFIRMED 2026-09-22: they still apply to the new templates.** The owner states the templates are sound but has no review record, so the guard stays ON until those details exist. See the clarification under R3-2 |
| NR-11 | `is_unreviewed_template` (`agreement_service.py:83`), refusing the marker at create and at sign | It is what keeps unreviewed wording unsendable; its relationship to the new templates follows from NR-10 |

### Reopened by R3-4 — "Ask a lawyer"

| # | Item | Why it needs review |
|---|---|---|
| ~~NR-12~~ | ~~Is "Ask a lawyer" a fourth producer?~~ | **CLOSED 2026-09-22 by R3-12.** One flow, so it is a request into that flow, not a producer |
| ~~NR-13~~ | ~~DG-08's two-way split~~ | **CLOSED 2026-09-22 by R3-12**, which completes DG-08: B and C become one flow |
| NR-22 | "Ask a lawyer" — may the lawyer charge for writing it, and what happens if they decline? | R3-11 defines the request and the accept/decline; it does not define payment or the decline outcome |
| NR-23 | D5 — KYC required to author or send | Decided when authoring was lawyer-only. **Sharpened by R3-14**, which lets an unverified lawyer author for others, and by R3-12's single flow. What D5 applies to, and at which point, needs restating |
| ~~NR-24~~ | ~~Author visibility after sending~~ | **CLOSED 2026-09-22 by R3-20.** Read-only, permanently, with no party or editing rights |
| NR-32 | Is the counterparty told a non-party can read the agreement? | R3-20 lets the drafter read an executed agreement indefinitely; the counterparty never chose them. Disclosure is undefined |
| ~~NR-25~~ | ~~The author on the agreement~~ | **CLOSED 2026-09-22 by R3-15.** The drafting lawyer's name appears on the agreement |
| NR-27 | The author on the EVIDENCE CERTIFICATE | R3-15 covers the agreement. The certificate is a separate document whose contents are pending counsel (§13 Q9-Q11); whether the drafter is named there is undefined |
| ~~NR-26~~ | ~~Who sends, when the author cannot sign~~ | **CLOSED 2026-09-22 by R3-17.** The drafter hands over; the party sends and signs |
| ~~NR-28~~ | ~~May the recipient edit a handed-over draft?~~ | **CLOSED 2026-09-22 by R3-18.** Yes, until send |
| ~~NR-29~~ | ~~The state between handover and sending~~ | **CLOSED 2026-09-22 by R3-19.** `awaiting_sender` |
| ~~NR-34~~ | ~~What stops attaching an agreement to an unrelated case?~~ | Raised by the 2026-09-22 audit. **CLOSED same day by R3-26**: `case_id` may only reference a case the user is authorised on, and never changes ownership |
| ~~NR-30~~ | ~~Pre-send edit: new version or update?~~ | **CLOSED 2026-09-22 by R3-21.** Always a new immutable version |
| ~~NR-31~~ | ~~Is the author label still accurate after an edit?~~ | **CLOSED 2026-09-22 by R3-22.** Attribution is version-aware |
| NR-35 | Wording when a later version returns to the original author | R3-22 names two forms; a third case is unstated |
| ~~NR-33~~ | ~~Does `awaiting_sender` use the D7 quota?~~ | **CLOSED 2026-09-22 by R3-23.** It does not |

### Standing items this round does not resolve

| # | Item | Why it needs review |
|---|---|---|
| ~~NR-14~~ | ~~Counterparty model vs the case model~~ | **CLOSED 2026-09-22 — decided as R3-6.** Client-to-client agreements are allowed |
| NR-15 | B3 — unauthorised create (§3.G1.7) | **Reframed by R3-8.** Open sending is now intended, so B3's "no relationship check" half is answered by decision. What remains is its other half: **no rate limit on `POST /agreements`**, which R3-8 requires. Tracked concretely as NR-21 |
| ~~NR-16~~ | ~~What decides who may send an agreement to whom~~ | **CLOSED 2026-09-22 — decided as R3-8.** Any registered user to any registered user, subject to authentication, two-party rules, signing requirements and abuse/rate controls |
| ~~NR-21~~ | ~~The abuse / rate control~~ | **CLOSED 2026-09-22 by R3-24.** 10 sends/hour/user on all sending, reusing `core/rate_limit.py` |
| NR-36 | What the user sees when the send limit is hit | R3-24 sets the limit and not the breach behaviour |

### Reopened by R3-5 — the hire flow moves to appointments

| # | Item | Why it needs review |
|---|---|---|
| ~~NR-17~~ | ~~The case claim~~ | **CLOSED 2026-09-22 by H-4.** `case.lawyer_id` is set at hire acceptance, in the existing claim at `engagement_service.py:314`, unchanged |
| ~~NR-18~~ | ~~Review eligibility~~ | **CLOSED 2026-09-22 by H-2 / §17 R5-6.** Completed appointment OR `ENGAGEMENT_RETAINED_STATUSES`. Supersedes R5 |
| ~~NR-19~~ | ~~Account-closure blockers~~ | **CLOSED 2026-09-22 by H-4.** Engagements stay the hire record, so `user_service.py:212-221` needs no change. Appointment blockers are separate — NR-37 |
| ~~NR-20~~ | ~~Engagement enum, tuples, index~~ | **CLOSED 2026-09-22 by H-4.** All retained. Only `exists_executed_relationship`'s `$lookup` changes (H-2) |


---

## 16. Decision Record — Round 4: Engagement Letter → Appointment/Hire

Dated 2026-09-22. Evidence verified read-only at `0947ad5`.

**Two kinds of entry, kept distinct.** **DECIDED** entries were stated by the
project owner. **RECOMMENDED** entries are evaluations requested by the owner
and **await the owner's approval** — they are not decisions until approved, and
nothing downstream may treat them as settled.

---

### H-4 — Appointment is the entry point; Engagement is the Hire — **DECIDED**

| Field | Value |
|---|---|
| Decided by | Project owner |
| Sources | **PLAN**, refining **R3-5** and **R3-9** |
| Code change? | **YES — small and subtractive. Not scheduled** |

**Appointment is the entry point. `Engagement` remains the authoritative Hire
record and state machine. The hire subsystem is NOT rebuilt.**

R3-5 said the hire flow "moves to appointments". H-4 fixes what that means: the
*entry point* moves, the *record* does not. `request_engagement` →
`propose_terms` → `accept_terms` (`engagement_service.py:84, 188, 260`) already
is a hire with fee terms, which is exactly what R3-9 described.

**Why not rebuild.** `accept_terms` claims the engagement (`:295`) and then the
case (`:314`) in an order §2.G1.4 of the remediation plan calls
*"load-bearing and carefully argued"*. Reimplementing it inside
`appointment_service` would reopen the race that ordering closes.

**What changes:** the letter call at `:365` and its rollback (`:374-390`) go; an
`appointment_id` is added to the engagement to record which consultation
the hire followed — **required on every NEW engagement per §17 R5-1**, absent
on legacy rows. Nothing else in the engagement subsystem moves — **except**
the two checks §17 later adds: the completed-appointment validation in
`request_engagement` (R5-1, NR-39/40) and the KYC re-check in `accept_terms`
(R5-2). The claim sequence itself is untouched.

---

### H-6 — DG-07 restated: KYC re-check before the atomic claim — **DECIDED**

| Field | Value |
|---|---|
| Decided by | Project owner |
| Sources | **PLAN**, restating **DG-07** (§11) |
| Code change? | **YES. Not scheduled** |

**The KYC re-check runs in `accept_terms`, immediately before the atomic
claim.** Its purpose changes from "verify before a letter is generated" to
**"verify before the lawyer takes the case"**.

**Placement, recorded precisely — CONFIRMED by the owner (§17 R5-2): before step 1.** The atomic claim
is a **two-step sequence**, not one write:

1. claim the engagement → `accepted` (`engagement_service.py:295`)
2. claim the case → `lawyer_id` (`:314`)

| Placement | Consequence |
|---|---|
| **Before step 1** (after `lawyer_id` is read at `:284`) | Nothing has been written. A failed check refuses cleanly. **No rollback needed** |
| Between steps 1 and 2 | The engagement is already `accepted`. A failed check must undo it — reopening **Q6** |

This record reads "immediately before the atomic claim" as **before step 1**,
because that is the only placement with nothing to undo. **Doing so resolves
§13's Q6** (rollback when the KYC re-check fails) by making the rollback
unnecessary. ~~If the owner intended between the steps, Q6 stays open.~~
**Confirmed before step 1 (§17 R5-2); Q6 is resolved.**

---

### H-1 — Hire without a case — **DECIDED (Round 5): V1 requires an existing case**

| Field | Value |
|---|---|
| Status | **DECIDED 2026-09-22 by the project owner (Round 5, §17)** — was recommended |
| Sources | **IMPLEMENTATION**, **PLAN** (R3-7, R3-26) |

**Today a hire cannot exist without a case, and neither can billing.**
`request_engagement` refuses with `NotFoundError("Case")`
(`engagement_service.py:87-89`); `create_fee_request` requires `case_id`,
requires `case.lawyer_id == lawyer_id`, and derives the client from
`case.client_id` (`payment_service.py:176-182`). An appointment, by contrast,
may have no case (`appointment_service.py:377`, `case_id: str | None`).

| Option | Billing | `case.lawyer_id` | `uniq_pending_engagement` | Verdict |
|---|---|---|---|---|
| **A. Hire requires a case** | unchanged | set at `:314`, unchanged | valid | **zero change** |
| B. Hire creates the case | unchanged *if* created at request | changes the claim ordering | **breaks if created at acceptance** | risky |
| C. Hire without a case | **rebuilt**: `:176-182` re-keyed on engagement | never set | **breaks** | largest |

**The index finding decides it.** `uniq_pending_engagement` is a unique index on
`case_id` whose partial filter is `{"status": {"$in": OPEN}}` only
(`indexes.py:~116-119`, `:835`) — it does **not** require `case_id` to exist. An
engagement with no case therefore indexes under a null key, and **at most one
caseless open engagement could exist in the whole system**. The second would be
refused as a duplicate. Option C hits this directly; option B hits it whenever
the case is created at acceptance rather than at request, because the
engagement is open (`requested`, `terms_proposed`) before it is accepted.

**Recommendation: A for V1.** Every downstream consumer — billing, the claim,
the guard index, termination's case release — is case-scoped. A changes none of
them. The appointment-to-hire UX handles the caseless consultation by asking
the client to select or create a case before requesting the hire; case
creation already exists.

**Not affected by this recommendation:** agreements. R3-7 and R3-26 make
`case_id` optional on an *agreement*; H-1 concerns the *hire*. The two are
independent, and neither may establish case ownership through the other.

---

### H-2 — R5 supersession: review eligibility — **DECIDED (Round 5)**

| Field | Value |
|---|---|
| Status | **DECIDED 2026-09-22 by the project owner (Round 5, §17)** — was recommended |
| Sources | **PLAN** (supersedes R5), **IMPLEMENTATION** |

**Recommendation: a client may review a lawyer when there is a retained
engagement (`accepted`, `completed` or `terminated`) OR a completed
appointment.** The executed-letter condition is removed.

**Current rule:** `lawyer_service.py:694-698` —
`exists_executed_relationship` OR `exists_completed`. The first
(`engagement_repo.py:~78-99`) already filters on `ENGAGEMENT_RETAINED_STATUSES`
(`:84`) and then `$lookup`s the letter to require it executed (`:95`).

**Why this cannot stay as it is.** Once letters stop being generated, the
`$lookup` finds nothing and `exists_executed_relationship` **returns False for
every new engagement**. A client who hired a lawyer but had no completed
appointment would silently be unable to review them. The change is removing
the `$lookup`; the retained-status match stays.

**This supersedes a recorded decision.** Remediation plan §2 **R5** tightened
eligibility to an *executed* letter because *"an accepted engagement whose
letter is still pending is also not yet a relationship anybody agreed to in
writing."* R3-1 removes the writing, so R5 cannot survive. **R5 must be marked
SUPERSEDED in the remediation plan when that plan is next updated** — it is not
changed here, per this round's scope.

**A stricter alternative — NOT adopted (§17 R5-6 keeps all three retained statuses):** `completed` or
`terminated` only, excluding `accepted`, so a review requires work to have
actually happened. The recommendation keeps `accepted` because acceptance of
fee terms is now the strongest consent signal the system records.

---

### H-3 — Existing pending engagement letters — **DECIDED (Round 5)**

| Field | Value |
|---|---|
| Status | **DECIDED 2026-09-22 by the project owner (Round 5, §17)** — was recommended |
| Sources | **PLAN** (R7, §2), **IMPLEMENTATION**, V0 census (§14) |

**Recommendation: leave every existing letter row exactly as it is. No
migration, no mutation, no cancellation.** Once billing and reviews stop
reading letter status (H-2, R3-25), a pending letter gates nothing and is inert.

| Existing row | Treatment |
|---|---|
| **Executed letter** | **Never touched.** A signed instrument; immutable per the Phase 3 contract |
| **Pending letter** | Left as-is while its engagement is live. **Cancelled when that engagement terminates** (existing Gate 3A behaviour, retained — §17 R5-4). Never left signable behind a terminated engagement |
| **Decline of a legacy letter** | **CORRECTED 2026-09-22.** The decline path writes **no** `cancellation_source` — it sets `status: cancelled` and an audit entry only (`agreement_service.py:~1790-1805`). Today Gate 2's reversal also writes `decline_source: "engagement_letter"` on the **engagement** (`:1347`, `_reverse_engagement`). **Decided (C-A, §17 R5-12): the reversal is removed**; historical `decline_source` values stay readable |
| **The six orphans** | Unchanged. Still under **R7** — classified by a human before any cleanup |

**Current real exposure is the six orphans only.** The V0 census (§14) found 5
pending letters and 1 executed letter, all six the known orphans, and §2.0
found **zero engagements at any status**. No pending letter is attached to a
live engagement today.

**Two facts that make "leave as-is" safe:**

- An orphaned pending letter **cannot be declined today** — Gate 2 aborts on a
  missing engagement (remediation plan test matrix, *"missing engagement …
  abort everything"*). Removing the reversal is what makes decline work for
  them, not what breaks it.
- The executed orphan has **no `body_sha256`** (§14), so the PDF builder already
  refuses it. Leaving it untouched changes nothing.

**Required before cutover:** re-run the read-only census (the pre-cutover
legacy-letter census, §17 R5-11), because the database
can change between now and implementation. The recommendation rests on "zero
live engagements"; that must be true on the day, not only today.

**Rejected alternative:** cancelling every pending letter with a new
`cancellation_source`. It is a destructive write to records R7 says not to
touch, it would need a migration, and it buys nothing once the letters gate
nothing.

---

### H-5 — Appointments as account-closure blockers — **DECIDED (Round 5): DEFER**

| Field | Value |
|---|---|
| Status | **DECIDED 2026-09-22 by the project owner (Round 5, §17)** — was recommended |
| Sources | **IMPLEMENTATION** |

**Recommendation: explicitly defer. Record it as a pre-existing gap, outside
this migration.**

`user_service.py:212-221` blocks closure on open or accepted **engagements** and
live payments. It does not count **appointments**, so a lawyer can close their
account with consultations booked. That was true before this migration and is
not caused by it.

**Why defer:** it touches no letter and no engagement; adding it changes
account-closure behaviour for every user; and appointments have their own
lifecycle (`pending`, `confirmed`, `completed`, `no_show`, `expired`,
`cancelled`), so which states block is its own question. Tracked as **NR-37**.

**Under H-4 closure needs no change for this migration.** Engagements stay the
hire record, so the existing engagement blockers remain correct.

---

### Dependencies between these decisions

| Decision | Depends on | Why |
|---|---|---|
| **H-4** | **H-1 = A** | "Do not rebuild" holds only if hires stay case-scoped. B or C would force changes to the claim ordering and the guard index |
| **H-2** | the letter stop | Reviews break silently the moment letters stop; H-2 must ship **in the same change** as stopping generation |
| **H-3** | **H-2** and **R3-25** | Leaving pending letters untouched is safe only once nothing reads their status |
| **H-6** | nothing | Independent; can ship first. Its placement decides whether Q6 survives |
| **H-5** | nothing | Independent, and deferred |
| **H-1** | nothing | But **H-4** and **H-3** both assume its recommendation |

**H-1 is the root.** If the owner chooses B or C instead of A, H-4's "do not
rebuild" no longer holds and this round must be revisited.

---

### Effect on the open-item list

"CLOSED" is used only where the closing entry is **DECIDED**. Items resolved by
a **RECOMMENDED** entry are annotated, not closed.

| # | Item | Why it needs review |
|---|---|---|
| NR-37 | Appointments as account-closure blockers | **DEFERRED by owner decision (H-5 / §17 R5-9).** Pre-existing gap; not part of this migration |
| NR-38 | Supersessions to record in the remediation plan | H-2 / R5-6 supersede **R5**; C-A (R5-12) supersedes the shipped **Gate 2 letter→engagement reversal rules (R1-R8, §2)**; C-B reverses terminated-engagement billing, which exists only in code and tests (`payment_service.py:100-105`, `test_engagement_termination_3a.py:532`), not as a remediation-plan rule. The remediation plan is out of scope until dependency step 8 |


---

## 17. Decision Record — Round 5: Agreements/Hire reconciliation

Dated 2026-09-22. Decided by the project owner. Reconciled read-only against the
code at `0947ad5`. Docs only — nothing here is implemented.

**C-A and C-B were first recorded OPEN** because the instructions conflicted
with an existing decision or with what the schema can express. **Both were
DECIDED by the owner later on 2026-09-22 (final reconciliation, R5-12)**; the
original analysis is kept below as the reasoning trail.

---

### R5-10 — Final architecture — **DECIDED**

| Concept | Record | Is NOT |
|---|---|---|
| **Appointment** | the consultation / meeting | the Hire, the billing relationship |
| **Engagement** | the Hire relationship and its state machine | rebuilt, duplicated, or a new collection |
| **Case** | the legal matter being represented; `case.lawyer_id` is ownership | optional for a new Hire |
| **Agreement** | a separate user-to-user document | a hire, a consent gate, a case owner |

Agreement `case_id` remains a reference only and **never establishes or changes
case ownership** (R3-26).

---

### R5-1 — Appointment → Hire — **DECIDED**

**V1 requires a COMPLETED appointment before a NEW hire.**

```
Lawyer discovery → Book appointment (case optional)
  → the LAWYER marks the appointment COMPLETED (manual; after its scheduled end)
  → "Hire this lawyer" → case-bound appointment: that case
                        | case-less appointment: select | create a client-owned case
  → request_engagement(case_id, lawyer_id, appointment_id)   [KYC check #1]
  → propose_terms (fee/scope) → accept_terms:
        KYC check #2 → claim Engagement → ACCEPTED → claim case.lawyer_id
  → billing / case work
```

| Rule | Status |
|---|---|
| An appointment may be created without a case | unchanged (`appointment_service.py:377`) |
| A NEW engagement requires a case | unchanged (`engagement_service.py:87-100`) |
| A NEW engagement **must** carry `appointment_id` | new |
| That appointment must be `completed`, and have the same `client_id` and `lawyer_id` | new |
| Completion is a **manual lawyer action** today — there is no automatic completion | existing (`appointment_service.py:899-918`) |
| One completed appointment supports **at most one** new Engagement for that client-lawyer relationship | **DECIDED — NR-39** |
| Case-bound appointment → the new Engagement **must** use that case; case-less → a client-owned case selected or created during hiring | **DECIDED — NR-40** |
| No appointment-age limit in V1; `completed` is the only requirement | **DECIDED — NR-41** |
| Appointment is not the Hire record; no Hire collection or second state machine | H-4 |
| The direct-hire path on the lawyer page (`ModLawyers.jsx:703-745`) is **eventually replaced** by the completed-appointment entry | new |

**Consequences, recorded, not decided:**

- **Only the lawyer can complete an appointment**, and only after its scheduled
  end, from `confirmed` (`appointment_service.py:899-918`;
  APPOINTMENT_REMEDIATION_PLAN.md transition table). The lawyer therefore
  controls whether a client may hire them. `no_show`, `cancelled` and `expired`
  do not qualify.
- **Legacy engagements** have no `appointment_id`. The requirement applies to
  new engagements only; nothing is backfilled.
- **NR-39, NR-40, NR-41 are DECIDED** (R5-12). Two consequences, recorded:
  - a case-bound appointment whose case is no longer hireable (lawyer
    assigned, closed, or draft — `engagement_service.py:87-100`) cannot lead
    to a hire, because NR-40 forbids substituting another case;
  - whether an Engagement that ends `declined` or `cancelled` has used up
    its appointment is **not stated** — **NR-42**.

---

### R5-2 — KYC — **DECIDED**

The existing check in `request_engagement` (`_get_verified_lawyer`,
`engagement_service.py:108`) **stays**. A second check is added in `accept_terms`
**immediately before the first claim/write**:

```
KYC re-check  →  claim Engagement → ACCEPTED (:295)  →  claim case.lawyer_id (:314)
```

**Not between the two claims.** A refused check writes nothing, so no rollback
exists to design; **§13 Q6 is resolved**. Purpose: the lawyer is still an
active, verified lawyer at the moment the hire is accepted. `accept_terms` has
**no KYC check today**, and `propose_terms` has none either.

---

### R5-3 — New engagement letters — **DECIDED** (inherits **PENDING COUNSEL** from R3-1)

New hires generate **no** engagement letter. Removed from the new flow:

| Dependency | Where |
|---|---|
| letter generation | `engagement_service.py:350, 365`, `_engagement_letter_text` (`:483`) |
| generation rollback and its 503 | `:374-406` |
| storing a new `agreement_id` on the engagement | `:410` |
| review requiring an executed letter | `engagement_repo.py:~78-99` — **both** the `agreement_id != None` match and the `$lookup` |
| letter-specific billing gates | `payment_service.py:117-160` |

Existing letters are neither invalidated nor migrated (R5-4).

---

### R5-4 — Legacy letters — **DECIDED** (C-A decided in R5-12)

Legacy letters are **historical compatibility data**, not part of the new Hire flow.

| Legacy row | Behaviour |
|---|---|
| **Executed** | Untouched, always |
| **Pending, engagement live** | Keeps its existing lifecycle — signable, declinable |
| **Pending, engagement terminates** | **Cancelled** by termination (retained `_cancel_pending_letter`, `engagement_service.py:951`, `cancellation_source: engagement_terminated`). Never left signable |
| **New engagement terminates** | No letter, **no anomaly recorded** — `no_letter` (`:968`) is removed. `letter_missing` / `letter_superseded` stay for legacy links |
| **The six orphans** | Unchanged, under R7 |
| **Decline of a pending legacy letter** | Writes `status: cancelled` and an audit entry. **No `cancellation_source`** (H-3 corrected). **Does not reverse the Engagement and does not touch `case.lawyer_id`** (C-A). Orphans are declinable without a linked Engagement |
| **Historical `decline_source` / `declined_agreement_id`** | Remain on existing rows and readable for compatibility and audit. **New declines never write them** |

#### C-A — does Gate 2's reversal survive for legacy linked letters? — **DECIDED: NO** (R5-12)

*Analysis as first recorded, kept for the trail:*

- **For removal:** the 2026-09-22 dependency-map instruction (item 9) listed
  "Gate 2 decline reversal" for removal, and **R3-26** (DECIDED) says the
  agreement module must never write `case.lawyer_id`. The reversal writes it
  (`agreement_service.py:1553-1556`); R3-26 records that write as removed.
- **For retention:** Round 5 asks to "preserve the actual legacy
  `decline_source` behaviour where applicable". `decline_source` is written
  **only** by the reversal, so it can only be preserved *as behaviour* by keeping
  the reversal.
- **Reading compatible with both:** remove the reversal, keep the
  `decline_source` / `declined_agreement_id` fields readable on existing rows
  (`schemas/engagement.py:103-105`). That is not recorded as decided because
  the instruction's wording admits the other reading.
- **Practical exposure today: none.** The census found zero engagements, so no
  pending letter is linked to a live engagement. The choice still decides
  whether R3-26 holds.
- **Side effect if removed:** `_linked_engagement` goes too, so the 5 pending
  orphans become declinable (today their decline aborts).

---

### R5-5 — Billing — **DECIDED** (C-B decided in R5-12)

Billing is governed by the **valid retained Engagement / Hire relationship**,
not by `case.lawyer_id` alone and not by a letter. The term "active hire" is
**not** used for the terminated case.

| Engagement | Relationship check | New fee request | Existing fee requests |
|---|---|---|---|
| `accepted` (active) | engagement for (case, lawyer, `case.client_id`) **and** `case.lawyer_id == lawyer` | allowed | payable |
| `completed` | same — completion **keeps** `case.lawyer_id` (`engagement_service.py:~739-742`) | allowed | payable |
| `terminated` | the engagement for (case, lawyer, client) — `case.lawyer_id` is **cleared** by termination | **refused** (C-B) | payable (below) |
| requested / terms_proposed / declined / cancelled | — | refused | — |

**Existing fee requests survive termination already.** `create_checkout`
(`payment_service.py:306-318`) checks only the payer, the status and expiry;
termination writes nothing to payments. A fee request raised before termination
stays payable through the existing payment lifecycle until it expires
(`fee_request_expiry_days`, `:227`) or reaches another terminal status. No
change. *Fact:* `PaymentStatus.CANCELLED` exists (`constants.py:184`) but no
code path writes it today, so in practice expiry is the only end besides
payment.

**`engagement_id` integrity — DECIDED.** `create_fee_request` must not store a
caller-supplied `engagement_id` unchecked (`payment_service.py:207`). The stored
value is the engagement the gate validated for the authenticated lawyer, the
case and its client. A supplied id that does not match is refused. Existing rows
are not backfilled; note that `PaymentsPage.jsx:47` never sends `engagement_id`,
so UI-created fee requests carry `null` today.

#### C-B — may a lawyer raise a NEW fee request after termination? — **DECIDED: option (a)** (R5-12)

*Analysis as first recorded, kept for the trail:*

The three instructions cannot all be met by the current schema:

1. allow outstanding fee claims for a terminated engagement although
   `case.lawyer_id` is cleared;
2. do not let termination authorise unlimited new work;
3. do not invent a "work performed" field.

A fee request has `created_at`, `amount`, `purpose`, `note`, `hearing_id`; an
engagement has `accepted_at`, `terminated_at`, `fee_amount`, `fee_type`.
**Nothing records when the billed work was done.** So a request raised after
`terminated_at` cannot be told apart from new work. The options are:

| Option | Meets 1 | Meets 2 | Meets 3 |
|---|---|---|---|
| (a) refuse new requests after `terminated_at`; existing ones stay payable | only for requests already raised | yes | yes |
| (b) allow new requests after termination, unbounded | yes | **no** | yes |
| (c) allow within a bound (time window after `terminated_at`, or cap by `fee_amount`) | yes | yes | yes — but the bound is a **new rule** nobody has stated |

**V1 boundary, recorded either way:** the system cannot verify that a fee
raised against a terminated engagement is for work performed before
termination. ~~Owner decision required between (a) and (c).~~ **Decided: (a),
with no new field and no grace period.**

---

### R5-6 — Reviews — **DECIDED**

A client may review a lawyer if there is a **completed appointment OR a retained
engagement**, using the existing `ENGAGEMENT_RETAINED_STATUSES`
(`constants.py:166`): **`accepted`, `completed`, `terminated`**. No second,
review-specific list. **R5 (executed-letter requirement) is SUPERSEDED**; the
remediation plan must say so (NR-38, dependency step 8).

---

### R5-7 — Product-plan corrections — **DONE in this record**

- **H-3**: the `cancellation_source: "declined"` claim is withdrawn; the decline
  row now states what the code does.
- **R3-25**: rewritten to the owner's wording; the original is kept as history.
- **H-1, H-2, H-3, H-5**: relabelled DECIDED.
- **NR-1, 2, 3, 4, 18, 37**: updated. NR-3 was OPEN (C-A) and is now CLOSED (R5-12).

---

### R5-8 — The legacy letter producer — **DECIDED**

`create_pending_engagement_letter` (`agreement_service.py:776`) will have **no
production caller** once `:365` is removed. It is **not deleted**: four test
files use it as a legacy fixture producer (`test_agreement_phase1.py`,
`test_agreement_drafts_3c.py`, `test_agreement_list_3f.py`,
`test_engagement_two_step.py`), and those fixtures are needed while migration
testing proves legacy rows still behave. It may later move into test support.

---

### R5-9 — Account closure — **DECIDED: deferred**

The appointment / account-closure gap stays **deferred as NR-37**. No
appointment closure blocking is added in this migration.

---

### R5-11 — Implementation order — **DECIDED** (steps 1–2 done, uncommitted; step 3 in progress)

| # | Step | Status | Blocked by |
|---|---|---|---|
| 1 | `appointment_id` required + completed-appointment → Hire entry (NR-39/40/41): backend enforcement, the per-lawyer eligible-consultation query, and the minimal lawyer-page gate | **DONE** | — |
| 2 | Validated billing predicate + `engagement_id` integrity; refuse new fee requests on a terminated Engagement (C-B) | **DONE** | — |
| 3 | KYC re-check in `accept_terms`, before the first claim (R5-2) | **DONE** | — |
| 4 | Remove new engagement-letter generation and dependencies, including Gate 2's reversal and `_linked_engagement` (C-A) | — | step 2 landed; **pre-cutover legacy-letter census** run immediately before implementation |
| 5 | Review eligibility (R5-6) | — | ships **with** step 4 — otherwise reviews fail silently |
| 6 | Appointment uniqueness / reuse rule | — | **NR-42** (owner decision, still OPEN) |
| 7 | Frontend completion/integration: "Hire this lawyer" from the completed-appointment view + stale letter copy | — | step 1 |
| 8 | Final reconciliation/cleanup: remediation plan updated and R5 marked SUPERSEDED (NR-38); ENGAGEMENT_REDESIGN.md reconciled; **final reconciliation census** of the post-cutover state | — | last |

**Renumbered 2026-09-22 — numbering only; no product decision changed.** The
order is the one actually being implemented. Earlier numberings of this table
are superseded. Step 1 delivered part of step 7 (the lawyer-page hire entry is
gated and names a chosen consultation); step 7 keeps the dedicated entry from
the appointment screen and the stale letter copy. Step 6 cannot start until
NR-42 is decided. The former separate "remediation plan" step is carried in
step 8.

**Two censuses, two purposes.** Both are read-only.

1. **Pre-cutover legacy-letter census** — run immediately before step 4's
   letter-removal implementation, to establish the legacy-letter baseline
   before new-flow letter generation stops. This is the re-run that H-3
   requires "before cutover".
2. **Final reconciliation census** — stays in step 8, to verify and reconcile
   the post-cutover state.

**Stale document — REQUIRES RECONCILIATION DURING GATE 2, not edited now:**
ENGAGEMENT_REDESIGN.md "What must not regress" still says the executed-letter
billing gate must keep holding and that the letter is the consent artifact.
Superseded by R3-1 / R3-25 / R5-3 (PENDING COUNSEL). Reconcile it with step 8.


---

### R5-12 — Final reconciliation — **DECIDED**

Decided by the project owner, 2026-09-22.

| # | Decision |
|---|---|
| **C-A** | A legacy engagement-linked agreement decline **does not reverse the Engagement and does not mutate `case.lawyer_id`**. R3-26 stays authoritative: Agreement `case_id` is reference-only. Historical `decline_source` values stay readable for compatibility and audit; new declines do not write `decline_source` through engagement reversal. Orphan legacy letters can be declined without a linked Engagement |
| **C-B** | A **new** fee request is **refused** once its Engagement is `terminated`. Fee requests created before termination stay payable through the existing payment lifecycle until expiry or cancellation. **V1 does not claim to know when the underlying legal work occurred.** No new timestamp or field; no grace period |
| **NR-39** | One completed appointment supports **at most one** new Engagement/Hire for that client-lawyer relationship |
| **NR-40** | A case-less completed appointment may lead to a client-owned case selected or created during hiring. A **case-bound** completed appointment requires the new Engagement to use **that same case** |
| **NR-41** | **No appointment-age limit** in V1. The appointment must be `completed`; no time-window rule |

**Distinctions preserved, unchanged by this record:**

- historical legacy letter data stays compatible (executed untouched; pending
  keeps its lifecycle; the six orphans stay under R7);
- new Engagements do not generate letters (R5-3);
- a linked pending legacy letter is **cancelled** when its legacy Engagement
  terminates (R5-4, NR-4);
- the obsolete `no_letter` anomaly is removed **only for the new flow**;
  `letter_missing` / `letter_superseded` stay for legacy links.

**Counsel status, unchanged:** R3-1, R3-25 and R5-3 remain **PENDING COUNSEL**.
Nothing in R5-12 is a legal conclusion.

**Consequences of C-A and C-B, recorded as facts:**

- With the reversal gone, declining a legacy pending letter while its
  Engagement is `accepted` leaves that Engagement `accepted` — still billable and
  reviewable, because neither gate reads letters any more (R5-3, R5-5, R5-6).
  Live exposure today is none: the census found zero engagements.
- C-B changes behaviour the code currently tests for:
  `test_engagement_termination_3a.py:532`
  (`test_a_terminated_engagement_with_an_executed_letter_is_still_billable`)
  asserts the opposite at the helper level. It is inverted in Gate 2. The
  `payment_service.py:100-105` comment ("scoping this to `accepted` would have
  made … terminating an engagement a way to escape the bill") is superseded
  and must be rewritten then.

---

### New open items

| # | Item | Why it needs review |
|---|---|---|
| ~~NR-39~~ | ~~One completed appointment, several hires?~~ | **CLOSED (R5-12):** at most one new Engagement |
| ~~NR-40~~ | ~~Appointment `case_id` vs hire `case_id`~~ | **CLOSED (R5-12):** case-bound → same case |
| ~~NR-41~~ | ~~Age limit on the completed appointment~~ | **CLOSED (R5-12):** none in V1 |
| ~~C-A~~ | ~~Gate 2's reversal for legacy linked letters~~ | **CLOSED (R5-12):** no reversal, no `case.lawyer_id` write |
| ~~C-B~~ | ~~New fee requests after termination~~ | **CLOSED (R5-12):** refused; pre-termination requests stay payable |
| NR-42 | Does a `declined` / `cancelled` Engagement use up its appointment? | NR-39 says "at most one new Engagement"; whether one that never became a hire counts toward that limit is unstated. It decides whether the uniqueness rule covers every Engagement or only open + retained ones |
