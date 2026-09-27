# Next feature — two-step engagement flow

**Status:** BUILT 2026-09-10 on `feat/engagement-redesign` · **Opened:** 2026-08-24

> **Superseded in part.** Everything below describes the two-step flow as built
> in September 2026, when an engagement letter was still generated at
> acceptance. AGREEMENTS_PRODUCT_PLAN.md §17 has since removed the letter from
> the new flow (R5-3), moved the hire behind a completed consultation (R5-1)
> and changed what gates billing (R5-5) and reviews (R5-6). This document is
> kept as the record of that redesign; only its "What must not regress" section
> and the target-flow diagram have been corrected, and each correction says so.
> R3-1, R3-25 and R5-3 remain PENDING COUNSEL.

Scope items 1, 2, 3 and 5 are implemented; item 4 was already delivered by the
lawyer-directory work that landed just before this branch (`hourly_rate` passes
through `_sanitize`, is sortable via `fee_asc`/`fee_desc`, and renders as
"Fee/hr" on the card, the hire modal and the detail panel). Everything under
"What must not regress" has a test naming it.

Two things the build changed about the plan, both recorded because they are
decisions rather than details:

* **The claim guard had to widen, not just move.** `find_pending_for_case` and
  the `uniq_pending_engagement` index both named the single status `requested`.
  Left alone, an outstanding proposal would have read as "nothing pending" and
  a second lawyer could be asked in parallel — the redesign would have opened a
  race while closing a consent gap.
* **Completion is a handshake; termination is not.** Termination is the exit
  this document exists to create, so making it need the other party's agreement
  would rebuild the trap. Completion is a claim about shared reality, so it
  proposes and confirms — with a one-sided path that requires a written reason
  and is recorded as one-sided, for a counterparty who has stopped responding.

> **Build this as ONE change.** It resolves audit findings #1, #2 and most of #5
> together. Building them as three patches produces three half-fixes that each
> leave the others' failure modes intact — the fee problem and the no-exit
> problem are the same problem seen from two ends.

---

## What is wrong today

Verified live during the client↔lawyer audit (2026-08-24):

```
client requests  →  LAWYER ACCEPTS AND SETS THE FEE IN THE SAME CALL
                    ↓ case claimed, status → in_progress
                    ╔══════════════════════════════════════════╗
                    ║ client cannot cancel   (422)             ║
                    ║ lawyer cannot withdraw (422)             ║
                    ║ no completion · no termination           ║
                    ╚══════════════════════════════════════════╝
```

The client never sees a price before requesting, never agrees to one, and cannot
leave. `accepted` is an absorbing state; only an administrator can end the
relationship, by closing the case.

`8ef0dca` closed the money half of this — a lawyer can no longer bill against an
unsigned letter. **The consent gap itself is still open:** the case is still
claimed and the client still trapped the moment the lawyer accepts. The guard
stops the bleeding; it does not fix the sequence.

## The target flow

```
requested          client asks; lawyer sees the case facts
   ↓ lawyer proposes terms (fee, type, scope)
terms_proposed     NOTHING is claimed yet — case stays `open`
   ↓ client accepts            ↓ client declines
accepted                    declined
   ↓ case → in_progress, lawyer claimed HERE
   ↓
completed  /  terminated     either party can end it
```

**The load-bearing change is where the case gets claimed.** Today acceptance
claims it; afterwards it should be *client acceptance* that claims it. Until
then the case stays `open` and can still go to someone else.

## Concrete scope

1. **`EngagementStatus`** — add `TERMS_PROPOSED`, `COMPLETED`, `TERMINATED`.
2. **Split `accept_engagement`** into `propose_terms(lawyer)` and
   `accept_terms(client)`. Move the atomic case claim, the `in_progress`
   transition and the letter generation into the client-side call.
3. **Exits from `accepted`** — `complete` (either party proposes, other
   confirms, or one-sided with a note) and `terminate` (either party, with a
   reason recorded). Both must be reachable from the UI by both parties.
4. **Pre-request rates** — surface `hourly_rate` / a published fee range on the
   marketplace card. It is stored today and simply not returned, which is why
   the client currently decides blind.
5. **UI** — a terms panel for the lawyer, an accept/decline panel for the
   client, and an end-relationship action on both sides.

## What must not regress

- The atomic claim (`update_one` on `lawyer_id: None`) is what stops two lawyers
  taking one case. It moves; it does not disappear.
- A lawyer must not be able to bill a fee the client never agreed to. That is
  what the gate from `8ef0dca` protected, and it still holds — through a
  different mechanism. **RECONCILED 2026-09-23 (Gate 2 step 8):** this bullet
  read "an executed letter should be the normal state", which was true while a
  letter was the consent artifact. Since AGREEMENTS_PRODUCT_PLAN.md §17 R5-3 a
  new engagement generates no letter; the client's acceptance of the proposed
  terms is the consent, and billing validates the engagement itself (R5-5).
- **Also reconciled:** the bullet requiring `except Exception: pass` around
  letter generation to go. It did go — and then the generation went too (R5-3),
  so there is no longer a letter failure that could leave an engagement
  unrecorded. Legacy letters remain exactly as they were.

## Deliberately NOT in this change

- **Refunds / platform dispute resolution.** Held pending this work — most
  disputes plausibly originate in the unconsented fee this redesign removes, so
  building an arbitration mechanism first would be designing around a problem
  that is about to change shape. Revisit after this ships.
- **`kyc_rejection_reason` exposure** (audit finding #7). `lawyer_profile` is
  passed through unfiltered, so an admin's rejection note *would* reach clients
  if one were ever set. Currently **0 rows**, no live risk. Noted, not worth
  time.
