# Creating the eight missing V2 indexes

**EXECUTED 2026-09-06. All eight indexes created and verified.**
`DOCUMENTS_V2` remained `False` throughout and afterwards.

| | |
|---|---|
| Scope | exactly the eight `V2_INDEX_REQUIREMENTS` — deliberately not `create_all_indexes()`, which makes 31 calls across unrelated collections |
| Pre-checks | flag off · exactly 8 unsatisfied · duplicate risk clear, checked sparse-aware · aborts before writing on any surprise |
| Verification | read-only re-evaluation with the same `evaluate()` the preflight uses: **0 unsatisfied requirements** |
| `v2_owner_documents` | `[client_id 1, schema_version 1, created_at -1, _id 1]`, non-unique, non-sparse — as specified |
| Side effect | `review_events` did not exist and was implicitly created by its index. It is empty |

The procedure below is retained as the record of what was done and how to
reverse it.

---

## Correction: the premise of the previous version was wrong

This runbook used to describe replacing a **malformed same-name index** —
`v2_owner_documents` existing under the right name with the wrong keys, where
`createIndex` is a silent no-op and you must `dropIndex` first, briefly leaving
owner listings unindexed.

A read-only preflight against production on 2026-09-06 found that
**`v2_owner_documents` does not exist at all.** Nor do the other seven. The
`documents` collection carries only:

```
_id_            [('_id', 1)]
case_id_1       [('case_id', 1)]
client_id_1     [('client_id', 1)]
created_at_-1   [('created_at', -1)]
```

So there is nothing to drop, no silent no-op, and no drop→create window. The
task is simply to create indexes that were never created. That is a smaller and
safer job than the one this document previously described, and the elaborate
ordering precautions it carried are not needed.

## Observed state

| Requirement | Collection | State |
|---|---|---|
| `uniq_revision_document_version` | `document_revisions` | missing |
| `uniq_revision_document_idempotency` | `document_revisions` | missing |
| `document_id_1_event_seq_1` | `review_events` | missing |
| `uniq_notification_logical_event` | `notifications` | missing |
| `v2_queue_pending` | `documents` | missing |
| `v2_queue_cycles` | `documents` | missing |
| `v2_queue_cycles_any` | `documents` | missing |
| `v2_owner_documents` | `documents` | missing |

Four correctness, four query. All eight absent.

---

## Duplicate risk: checked, and clear

A unique index refuses to build if existing data violates it, so each of the
four correctness requirements was checked against live data before recommending
anything.

| Index | Collection | Rows | Verdict |
|---|---|---:|---|
| `uniq_revision_document_version` | `document_revisions` | 0 | safe |
| `uniq_revision_document_idempotency` | `document_revisions` | 0 | safe |
| `document_id_1_event_seq_1` | `review_events` | **collection absent** | safe |
| `uniq_notification_logical_event` | `notifications` | 594 | **safe** |

### The notifications index, and a false alarm worth recording

The first check reported `uniq_notification_logical_event` as **WOULD FAIL**, on
one duplicate key group across 594 notifications. **That was wrong**, and the
mistake is instructive.

The index is **sparse**, and `v2_index_spec` says why in its own comment:
*"SPARSE IS NOT OPTIONAL. Legacy notifications carry no logical_event_id, and a
plain unique index treats every missing field as one shared null."* The naive
check grouped all 594 rows — including every row missing the field — and
manufactured a duplicate out of nulls.

Checked correctly, counting only rows where the field exists:

```
notifications total            : 594
  with logical_event_id        : 0
  without (excluded by sparse) : 594
  duplicate groups among indexed: 0
```

**Zero of 594 notifications carry a `logical_event_id`**, so the sparse index
indexes nothing today and builds cleanly. Note what that means: the sparse flag
is doing real work. Without it, creation would genuinely fail on 594 shared
nulls — exactly the failure the spec's comment predicts.

---

## Before the window

1. **Re-run the read-only preflight.** The state above was observed on
   2026-09-04–06; confirm nothing has changed.

   ```js
   db.documents.getIndexes()
   db.document_revisions.getIndexes()
   db.notifications.getIndexes()
   ```

2. **Re-check the duplicate risk** if `document_revisions` or `notifications`
   has grown, using the sparse-aware form above — not a plain group-by.

3. **Confirm `DOCUMENTS_V2` is `False`** and no migration is in progress.

4. **You need a credential with `dbAdmin` on `attorney_ai`.** The survey user
   `v2_survey` holds `read` and cannot create indexes — deliberately. Do not
   widen it; use a separate credential and remove it afterwards.

---

## The procedure

`create_all_indexes()` builds every requirement from `V2_INDEX_REQUIREMENTS`,
which is the same specification the preflight evaluates against — so the thing
created and the thing checked cannot drift.

```
python -c "import asyncio; from app.db.indexes import create_all_indexes; asyncio.run(create_all_indexes())"
```

Or explicitly, if you would rather see each statement:

```js
db.documents.createIndex({client_id: 1, schema_version: 1, created_at: -1, _id: 1},
                         {name: "v2_owner_documents", background: true})
// ...and the remaining seven, per V2_INDEX_REQUIREMENTS
```

### One side effect to expect

`review_events` **does not exist**. Creating an index on a missing collection
implicitly creates the collection. That is harmless — it will be empty, and the
application would create it on first write anyway — but it is a change to the
database's shape, so it should not come as a surprise afterwards.

---

## Verification

**1. Every requirement is satisfied.** Re-run the read-only preflight; it should
report no problems, correctness or query.

**2. The owner-listing plan is actually served.** Index conformance is not the
same as the query being served by it, so check the plan for the query
`/documents/v2/mine` really issues:

```js
db.documents.find(
  { client_id: "<a real owner id>", schema_version: 2,
    $or: [ { created_at: { $lt: ISODate("2026-01-01T00:00:00Z") } },
           { created_at: ISODate("2026-01-01T00:00:00Z"), _id: { $gt: "<an id>" } },
           { created_at: null } ] }
).sort({ created_at: -1, _id: 1 }).limit(26).explain("executionStats")
```

Acceptance: `winningPlan` names `v2_owner_documents`; no `COLLSCAN`; no blocking
`SORT` (a `SORT_MERGE` is fine); `totalDocsExamined` within a small constant of
`nReturned`.

With 19 documents a collection scan is instant, so **timings prove nothing here**
— check the plan shape, not the duration.

---

## Rollback

```js
db.documents.dropIndex("v2_owner_documents")   // and any others created
```

Safe at any point. None of these indexes carries data, and with
`DOCUMENTS_V2` off nothing reads them. The unique ones enforce constraints only
on collections that are empty (or, for `notifications`, on a field no row
currently has), so dropping cannot orphan anything.

---

## Impact

| | |
|---|---|
| **Window** | Effectively none. `documents` holds 19 rows, `document_revisions` 0, `review_events` absent, `notifications` 594. Builds are near-instant |
| **User-facing** | Nil. `/documents/v2/mine` 404s while the flag is off |
| **Writes** | The sparse unique index on `notifications` is the only new constraint touching a non-empty collection, and today it indexes zero rows |
| **Reversibility** | Full, at any moment |

## Rules for the window

1. `DOCUMENTS_V2` stays `False` throughout and afterwards. This is a
   precondition for activation, not part of it.
2. No migration step in the same window.
3. Do not paste credentials into tickets, chat or logs.
4. Record the actual `explain` output; the preflight re-checks definitions but
   never checks a plan.
5. Remove the `dbAdmin` credential afterwards.
