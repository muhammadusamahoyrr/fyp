# Next feature — two-step engagement flow

**Status:** QUEUED · **Opened:** 2026-08-24 · **Position:** next in queue after
annotator/labelling work resumes.

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
   ↓ case → in_progress, lawyer claimed HERE, letter generated
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
- The billing gate from `8ef0dca` must keep holding — after the redesign the
  letter is generated at client acceptance, so an executed letter should be the
  normal state rather than a rarity.
- `except Exception: pass` around letter generation should go. Once the letter
  is the consent artifact, silently proceeding without one is the bug it already
  nearly was.

## Deliberately NOT in this change

- **Refunds / platform dispute resolution.** Held pending this work — most
  disputes plausibly originate in the unconsented fee this redesign removes, so
  building an arbitration mechanism first would be designing around a problem
  that is about to change shape. Revisit after this ships.
- **`kyc_rejection_reason` exposure** (audit finding #7). `lawyer_profile` is
  passed through unfiltered, so an admin's rejection note *would* reach clients
  if one were ever set. Currently **0 rows**, no live risk. Noted, not worth
  time.
