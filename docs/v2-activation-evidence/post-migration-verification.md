# Post-migration verification — 2026-09-06

Read-only. Run under the `v2_survey` credential, whose roles were asserted to be
exactly `['read']` before any query; the script aborts otherwise. **Nothing was
repaired, cleaned up or written.** `DOCUMENTS_V2` is still `False`.

Script: `backend/scripts/_verify_migration.py`. Three independent references —
the approved manifest, the pre-migration backup, and the bytes on disk.

| Evidence | |
|---|---|
| Approved manifest | `v2-approved-20260906T031427Z.json` |
| `migration_id` | `mig-349ef601-6b65-447a-ba58-42dd8d1c6823` |
| Planning fingerprint | `e8cab67f…0a766bf5` (dry-run #1 = #2 = approved) |
| `decision_set_id` | `ds-20260906T031709Z-19docs-0-approval-outcomes` |
| Rollback plan | `v2-rollback-20260906T031954Z.json`, 19 entries, `6294d893…d1f95845` |
| Backup | `v2-backup-20260906T030705Z` (preserved, intact) |

## Result: 24 of 26 checks pass

Both failures are **environmental, pre-existing or unrelated to the migration**,
and are evidenced as such below. No mismatch attributable to the migration was
found.

### Documents, revisions, artifacts — all pass

* 19 documents, id set identical to the plan
* every document `schema_version == 2`
* every `current_revision_id` equals the **planned** revision id (not merely
  populated)
* every document carries the `migration_id` and a `rollback_token`
* exactly 19 revisions, ids exactly the planned ids, one per document, no orphans
* every revision `version == 1`, `status == "generated"`
* every revision `document_id` matches the plan
* every revision `pdf_sha256` matches the approved plan's `byte_sha256`
* all 19 V2 artifacts exist under `uploads/v2/docs/` and re-hash to the source bytes
* all 19 legacy `file_path` values byte-identical to the backup; all 19 legacy
  PDFs still on disk and unchanged
* both submitted documents: `review_status == "submitted"`, reviewer identical to
  the backup, `submitted_revision_id` populated
* `review_events`, `transition_receipts`, `event_outbox`, `deletion_tombstones`
  all 0; no `review_cycles` written; **zero notifications created**

### Failure 1 — legacy PDF count 13,386 → 13,691

Not migration output. All 305 additions post-date the apply by ~85 minutes and
none is referenced by any document.

```
pre-apply census (mtime < 2026-09-06 08:19:54 local)  13,371
files created 09:44–09:47 local                          320
existing files modified after the apply                    0
```

Names: 302 × `legacy-<10 hex>.pdf`, plus `test-guardianship-*`, `test-wak-*`.

Confirmed at the call site, not inferred from the names — all three families
call the **production** `generate_pdf()` with no `tmp_path` redirection, so it
writes where the application writes:

| Test | Call | Files |
|---|---|---:|
| `tests/test_v2_migration_*.py`, `test_v2_activation_readiness.py` | `generate_pdf("legacy-" + uuid4().hex[:10], "legal_notice", …)` | 302 |
| `tests/test_wakalatnama_checklist.py` | `generate_pdf("test-wak-…", …)` | 11 |
| `tests/test_guardianship_petition.py` | `generate_pdf("test-guardianship-N", …)` | 4 |

**The suite writes real PDFs into the live `backend/uploads/docs/` directory.**
A defect worth fixing on its own account — it is also why the directory grows
on every test run — but it did not touch a migrated document.

### Failure 2 — notifications 576 → 549

Not the migration. `notifications` carries a TTL index:

```
created_at_1  {created_at: 1}  expireAfterSeconds = 2592000   (30 days)
```

All 27 disappeared rows have `created_at` between `2026-08-07 03:11:06` and
`03:46:47` — precisely the rows that crossed the 30-day boundary between the
backup (03:07:05Z) and verification. The oldest survivor is `2026-08-07 19:51`,
still inside the window. Types are `payment_requested` (15) and
`payment_received` (12); none references a migrated document. **Zero
notifications appeared.** This is Mongo's TTL monitor on its normal cycle.

## Two unreferenced V2 artifacts (left in place)

`uploads/v2/docs/` holds 21 files for 19 revisions:

```
0cfc2d51-….0.pdf   2026-09-04 17:50   2,223 B
6fe999d4-….0.pdf   2026-09-04 17:53   2,223 B
```

Both predate the apply by two days (the 2026-09-04 probe), are referenced by no
revision, and their content matches none of the 19 planned sources. Orphans in
the artifact store, not migration output. **Not deleted** — cleanup was out of
scope.

## `/documents/v2/mine` — real `explain()`, re-run

Built from the route's own `mine_page_query()`, `MINE_SORT` and projection, so
the plan measured is the plan the endpoint issues. Busiest owner holds 6 of 19.

| | page 1 (no cursor) | page 2 (keyset `$or`) |
|---|---|---|
| stages | `LIMIT ← PROJECTION_SIMPLE ← FETCH ← IXSCAN` | `LIMIT ← PROJECTION_SIMPLE ← FETCH ← IXSCAN` |
| index used | `v2_owner_documents` | `v2_owner_documents` |
| `nReturned` | 6 | 3 |
| `totalKeysExamined` | 6 | 6 |
| `totalDocsExamined` | 6 | 6 |
| COLLSCAN | **no** | **no** |
| blocking SORT | **no** | **no** |
| rejected plans | 1 | 11 |

Both meet the runbook's acceptance criteria. The keyset page examines 6 keys to
return 3 — the `$or` over-scans by a small constant, which is expected and
bounded. With 19 rows a scan would also be instant, so **the plan shape is the
evidence here, not the timing.**

## Limitation — citation verification did NOT run

```
revisions with verification.ran == True :  0 of 19
revisions with verification.ran == False: 19 of 19
```

ChromaDB was not connected during apply, so every revision carries
`verification = {"ran": false, …}`. **This is "not verified", not "verified
clean".** No claim about the citation correctness of any migrated document is
supported by this run, and none should be made until verification is actually
executed against a connected ChromaDB.

## Still open

* `DOCUMENTS_V2` remains `False`, awaiting explicit authorisation.
* The `v2_survey` password was disclosed in a transcript and **must be rotated
  or the user deleted.**
* The `dbAdmin` credential used for apply should be removed.
