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

### D1 — Do we keep the DIY contract builder?

| Option | Cost | Consequence |
|---|---|---|
| **A. Cut it** (recommended) | −1 day (deletion) | Agreements becomes engagement-letters-only. Honest, fully functional, defensible. The wizard code stays in git history if you revive it. |
| **B. Park it** | 2 hours | Hide behind a flag, keep the code. Reversible, costs nothing, ships nothing. |
| **C. Build it properly** | +6–8 days **and** counsel | Needs reviewed templates, lawyer authoring, a wider counterparty model, and a template registry. Not completable without a lawyer. |

**Recommendation: B now, A if no counsel is secured by end of October.** Option
C is not achievable on your timeline, and shipping a contract builder whose
every template is withdrawn is worse than not having the tab.

### D2 — Who may send an agreement to whom?

Currently: any authenticated user can send a signature request naming any
registered user id, with no shared case, no engagement, and no rate limit. That
is a spam and harassment vector in a product that handles legal matters.

**Recommendation:** require an existing relationship — a shared case or
engagement — with an exception for a lawyer sending to their own client. This is
a product rule, and it needs your decision because it forecloses cold outreach.

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

An engagement becomes active only when its letter is executed. A declined or
expired letter cancels the engagement and releases the case. A terminated
engagement voids any pending letter. Executed letters remain permanent records.

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

| Metric | Now | Measured by | Target |
|---|---|---|---|
| Cases assigned with no executed engagement letter | **unmeasured** | R2 census | 0 after R2 |
| Fee requests blocked by an unreachable letter state | **unmeasured** | R2 census | 0 after R2 |
| Agreements in `pending` never signed by their creator | **unmeasured** | R1 counter | 0 after R1 |
| Duplicate agreements per idempotency key | n/a — no keys exist | R1 counter | 0 after R1 |
| Executed agreements downloaded at least once | 0% — no endpoint | R3 download log | reported from R3 |
| Agreements authored by lawyers | 0 | R3 | >0 |
| False claims in the signing flow | **4** | R0 guard test | **0** after R0 |

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
| Counsel never secured, R4 never ships | Medium | Medium — caps the product at engagement letters | D1 option A; be willing to cut |
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
