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

