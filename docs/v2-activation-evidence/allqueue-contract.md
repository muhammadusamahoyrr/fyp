# The merged "All" queue — consistency contract

Analysis only. **No implementation decision was made and no code was changed.**

## What the code does today

`queue_page_plans()` splits the All tab into two indexed streams rather than one
`$or`:

- **pending** — submitted to me now
- **decided** — a `review_cycles` entry naming me

`_merged_page()` runs both, each sorted on `_id` and limited, unions them into a
dict keyed on `_id`, re-sorts, and truncates to `limit`.

The union itself is exact. Each branch returns the smallest `limit` keys above
the cursor *within that branch*, so any key small enough to belong on this page
is present in at least one prefix. Nothing can be skipped, and de-duplication by
`_id` handles a document that is in both branches — pending with me now **and**
decided by me earlier. That property does not depend on timing.

**The two branches are two separate reads.** There is no snapshot, no session,
no `readConcern` beyond the default. Everything below follows from that.

---

## Behaviour under the four scenarios

### 1. A submission becomes approved between the two reads

The document is in the pending branch when it is read, and in the decided branch
when that is read. It appears **once**, because the merge de-duplicates on `_id`.

The row's *content* comes from whichever branch reached `merged.setdefault`
first — pending is read first, so the row shows the pre-approval state. The tab
is All, which contains both, so the document belongs on the page either way.

**Consequence:** a status shown one refresh stale. Not a missing row, not a
duplicate.

The reverse order — approved before the pending read — means it is absent from
pending and present in decided. Still exactly once.

### 2. A document changes between pages

Page 1 is a completed read; page 2 is a new one. A document that changes after
page 1 was served shows its old state until the user refreshes.

If a change moves it *across* the cursor — its `_id` cannot change, so this only
happens if it leaves or joins the scope entirely (e.g. the lawyer is unassigned)
— it is absent from page 2 despite having been on page 1, or vice versa.

**Consequence:** a document can appear on no page of a paging session, or on
one page and not a later re-read. `_id` is immutable, so it can never appear
**twice** across pages.

### 3. New documents appearing before or after the cursor

- **After the cursor** (`_id` greater): picked up normally by a later page. This
  is the ordinary case and is correct.
- **Before the cursor** (`_id` smaller): **missed for this paging session.** The
  cursor has already passed that key.

`_id` is `secrets.token_urlsafe(16)` — random, not monotonic — so a document
created *right now* is equally likely to sort before or after any cursor.
**Roughly half of documents created mid-scroll will be missed** until the user
starts over.

This is the sharpest consequence of keyset pagination on a random key, and it is
worth being explicit about: it is not a rare race, it is the expected behaviour
for half of new arrivals during a scroll.

### 4. Duplicate membership in both streams

Handled correctly and unconditionally by `merged.setdefault(row["_id"], row)`.
This is the one case that is fully solved rather than merely bounded.

---

## The two candidate contracts

### A. Live / keyset pagination, with documented movement

Each page reflects the data at the moment that page was read. Rows may be one
refresh stale; documents arriving mid-scroll may be missed until a fresh load.
No document is ever duplicated or skipped *within* a single page.

- Cost: none — this is what the code already does.
- Bounded and index-delivered on both branches.
- Honest only if the UI does not imply the list is a stable snapshot.

### B. Snapshot-consistent pagination with a snapshot token

All pages of one session read a single point in time.

- Requires a Mongo session with `snapshot: true` read concern, held across
  requests, plus a token threaded through the API and the client.
- Snapshot read concern needs a replica set or sharded cluster, and holds
  history for the session's lifetime — a lawyer who leaves a tab open for an
  hour pins a snapshot for an hour.
- Meaningfully more machinery and a new operational failure mode
  (`SnapshotTooOld`) on the surface a lawyer uses to find work.

---

## Recommendation: **A — live/keyset, documented**

The queue is a worklist, not a report. A lawyer wants to see what is waiting
*now*, and a stale-but-fresh-on-refresh row is closer to that than a consistent
view of ten minutes ago. Nothing here can duplicate a row or lose one within a
page, which is what would actually mislead someone.

Snapshot consistency would buy a guarantee this surface does not need, and pay
for it in held server-side history on the queue lawyers keep open all day.

**Does the current implementation satisfy A?** Yes, with one caveat that needs a
UI note rather than a code change:

> Because `_id` is random rather than time-ordered, documents submitted while a
> lawyer is scrolling are missed about half the time until they reload. Under
> contract A that is permitted, but it should be *visible* — a "new items —
> refresh" affordance, or simply not presenting the queue as complete.

Without that note, contract A is being satisfied technically while a lawyer
reasonably believes they have seen everything waiting for them.

**If you later want new arrivals to be reliably reachable without a full
reload**, the smaller change is not snapshot pagination — it is ordering the
queue on a time-based key (`submitted_at, _id`) so new work lands at a
predictable end. That is a different piece of work and is not proposed here.
