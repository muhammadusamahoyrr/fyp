# Open Dependency 001 — is the Punjab Special Court actually sitting?

**Status:** OPEN · **Type:** external, human-only · **Opened:** 2026-08-24
**Blocks:** real-user exposure of the property-dispute feature
**Does NOT block:** anything else in the application

> **This is not an engineering task.** No further automated verification is
> possible and none should be attempted. The source documents are administrative
> notifications — not gazetted, not machine-readable, not published anywhere a
> tool can reach. Re-running searches or fetches against this will consume effort
> and return the same nothing. It needs a person.

---

## The ask, verbatim

> Need the S&GAD notification designating Special Court Judges under the Punjab
> Establishment of Special Courts (Overseas Pakistanis Property) Act, or
> confirmation via the Lahore High Court roll, showing whether the court is
> operational as of **24 August 2026**.

That is the whole request. It fits in an email.

## Who can answer it

Someone with access to **S&GAD circulars** or a **contact at the Lahore High
Court**. Two realistic routes:

1. **The law faculty contact being approached for annotator recruitment**
   ([ANNOTATOR_ONBOARDING.md](ANNOTATOR_ONBOARDING.md)). A law faculty member
   either knows this directly or can name someone who does. It costs one extra
   paragraph in an email that is being sent anyway — and it is a question a
   senior lawyer will find easy, not an imposition.
2. Any practising advocate on the Punjab district circuit. This is the sort of
   thing the local bar simply knows.

## Why the code cannot settle it

The statutory text of the neighbouring regime *was* verifiable and *has* been
verified — the Punjab Gazette publishes Acts as scanned PDFs, readable
page-by-page (see [FAILURE_CASE_001.md](FAILURE_CASE_001.md) for the style of
that verification, and commit `d0423d2` for the result).

**Operational status is a different kind of fact.** Whether a court is *sitting*
depends on an executive notification designating judges — an S&GAD instrument or
an LHC administrative roll. Those are not Acts, so they are not gazetted, so
there is nothing to fetch. `punjablaws.gov.pk/laws/2907.html`, the one candidate
URL for the Act itself, returns 404.

The obstacle is not language and not paywalls. It is that the document is not
published.

## What is at stake

`special_court.py` currently records Punjab as `ENACTED_PENDING` — the Act passed,
the court not confirmed sitting. On that basis the system tells a Punjab user it
cannot promise a forum, and routes them to a lawyer.

**There is reason to think that is wrong.** Press reporting of an S&GAD
notification (The Nation, 11 Nov 2025) states that District and Additional
District & Sessions Judges have *already* been designated as Special Court Judges
**across all districts of Punjab**.

| If the answer is | Then | Consequence of being wrong |
|---|---|---|
| **Judges designated, court sitting** | Punjab should be `OPERATIONAL` | We are **understating** a real remedy — sending users the slow way round when a fast-track court is open to them |
| **Not yet sitting** | `ENACTED_PENDING` stays correct | No change; the current fail-safe was right |

It is held at `ENACTED_PENDING` deliberately. The fail-safe direction is not to
promise a court that may not exist — telling someone to file somewhere that
cannot hear them costs more than being cautious. But that reasoning only holds
while the fact is genuinely unknown, and it is doing real harm if the court *is*
sitting. **This is the most consequential unverified fact in the codebase.**

## What happens when it resolves

A one-line change to the `"PB"` entry in
[`backend/app/services/special_court.py`](backend/app/services/special_court.py):
`court_status` to `OPERATIONAL`, with the notification cited in `source` and the
`note` rewritten. If it stays pending, only the note changes — to record that it
was checked, by whom, and when.

Either way, update `EFFECTIVE_AS_OF` and close this file.

## Cross-references

- `special_court.py` → the `"PB"` entry carries an `UNRESOLVED:` marker pointing here
- [FEATURE_AUDIT.md](FEATURE_AUDIT.md) → listed under known defects
- Commit `d0423d2` → the gazette verification that resolved facts (1) and (2)
  and isolated this one

## Everything else on this feature is settled

Facts (1) and (2) — the 30-day tribunal clock and the false-complaint penalty —
were read off the Punjab Gazette and corrected in code. Both press figures turned
out to be wrong. No further verification work is outstanding on this feature
beyond the single question above.
