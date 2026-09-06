# DOCUMENTS_V2 — activation evidence pack

**Status: NO-GO. Held at step 1 (target identification). No dry-run was run.**

Prepared read-only. Nothing was approved, applied, rolled back, indexed or
flipped. `DOCUMENTS_V2` remains `False`. No connection was opened to the
production database — see §1 for why that is a finding rather than an omission.

Policy version `2026-09-04.decision-matrix-v1` · manifest schema 2 · rollback
schema 1.

### The pack

| File | What it is |
|---|---|
| `README.md` | This document — findings and the GO/NO-GO |
| [`estate-survey.md`](./estate-survey.md) | **The counts.** 19 legacy documents, 0 blocked, 0 approvals needed |
| [`snapshot-runbook.md`](./snapshot-runbook.md) | How to capture a snapshot the dry-run can actually use |
| [`capture-manifest.md`](./capture-manifest.md) | Contract for the capture manifest, and the producer that emits it |
| [`snapshot-validation.md`](./snapshot-validation.md) | How to prove a restored snapshot is faithful before trusting it |
| [`index-runbook.md`](./index-runbook.md) | Creating the eight missing V2 indexes |
| [`allqueue-contract.md`](./allqueue-contract.md) | Consistency contract for the merged All queue |
| [`purge-backups-audit.md`](./purge-backups-audit.md) | Read-only audit of `backend/data/purge_backups/` |
| [`pack-durability.md`](./pack-durability.md) | What is safe to commit, and why none of it is committed yet |
| `mutation-evidence.json` | Every hardened behaviour reverted in turn, with source and test hashes |
| `estate-survey.json` | Raw survey output, aggregates only |
| `outcome-counts.json` | Machine-readable summary; every count *drawn from production* is `null` — no dry-run was run |

Tooling: [`v2_capture_contract.py`](../../backend/app/db/v2_capture_contract.py) (shared)
· [`capture_v2_snapshot_manifest.py`](../../backend/scripts/capture_v2_snapshot_manifest.py) (producer)
· [`validate_v2_snapshot.py`](../../backend/scripts/validate_v2_snapshot.py) (consumer)
· [`v2_mutation_evidence.py`](../../backend/scripts/v2_mutation_evidence.py)

---

## §1 · Target identification — **BLOCKED**

| Fact | Value |
|---|---|
| Configured deployment | hosted Atlas cluster (`mongodb+srv`, `*.mongodb.net`) |
| Configured database | `attorney_ai` |
| Is it a copy? | **No — this is the live database** |
| Local mongod databases | `attorney_ai_test` only (0 documents, the suite's throwaway) |
| Mongo dump / restore artefacts | **none** — see the inventory below |
| Restore tooling in repo | none |

### Artefacts that look like copies and are not

The first scan for these timed out and a narrower one was substituted, which
missed `evidence/`. The full scan was re-run; everything it found is inventoried
here rather than summarised as "none", so nobody has to wonder later whether one
of these would have done.

| Artefact | What it is | Usable as a target? |
|---|---|---|
| `evidence/statute_affinity_2026-09-01/before_snapshot.json` | 260 bytes of counts from a statute-affinity experiment. Its `mongo` key literally reads `"unavailable: ConfigurationError"` — the Mongo read failed when it was taken. | No |
| `backend/data/purge_backups/fixture_purge_*.json` | Purge record for 24 **fixture** accounts removed from `attorney_ai` on 2026-09-01. Contains **1** document, legacy-shaped (`review_status`, `submitted_to`, `file_path`, no `schema_version`). | No — one already-deleted fixture row, not an estate |
| `backend/data/purge_backups/attorney_ai_test_accounts_*.json` | 2.5 KB of test accounts. | No |
| `backend/chroma_data_backup_*` | Chroma vector-store directories. | No — not Mongo |
| `backend/models/backup` | Model files. | No |

The purge backup holds real user-shaped records; it is gitignored
(`.gitignore:124`) and untracked, so it is not in version control. Looking at it
turned up a finding unrelated to the migration and more urgent than it — 23
password hashes and 7 cases' worth of narrative sitting in the working tree in
plaintext, with no retention rule and no restore path. Audited separately, with
no PII reproduced: **[`purge-backups-audit.md`](./purge-backups-audit.md)**.
Nothing was deleted.

Credentials and connection strings were never read into output; only the host
class and suffix were inspected.

**Identity is unambiguous. The problem is that the only real-data target is
production, and you asked me to prefer a verified copy.** No copy exists.

### Why I did not proceed against live production

Not caution — two of your own steps become *unsound* against a live database,
and would produce evidence that cannot support the decision the pack exists to
inform.

**§2 requires running `dry_run()` twice against unchanged data and comparing
planning fingerprints.** On a live database the data changes between the two
runs because people are using it. A fingerprint mismatch would then be
indistinguishable from non-determinism in the planner — which is the exact
property the check exists to prove. A matching pair would be luck, not evidence.

**§6 requires proving zero writes by comparing before/after counts and content
hashes.** Live traffic changes both. I could not distinguish a write of mine
from a client submitting a document mid-scan, so a difference would prove
nothing and an absence of difference would prove nothing either.

There is also a measured operational cost: earlier in this engagement, access to
the hosted cluster from this machine took 15+ minutes for a full pass and failed
non-deterministically on DNS. `dry_run()` scans every legacy document. That is a
long unindexed read against production to produce evidence that would not be
sound anyway.

### What unblocks it

A frozen copy — **of both Mongo and the legacy PDFs** — restored under a clearly
non-production name.

> **Correction to an earlier version of this pack.** It said a `mongodump` alone
> would do. It will not, and the way it fails is worse than an obvious error:
> migration hashes the bytes at `document.file_path`, which holds an **absolute
> production path**. Restore Mongo without `UPLOAD_ROOT/docs` and every document
> classifies `*_no_file`, producing a manifest that reports the whole estate as
> unrecoverable while looking completely healthy.

Full procedure — collections, artifact directories, the frozen capture boundary
and how absolute paths are mapped after restore:
**[`snapshot-runbook.md`](./snapshot-runbook.md)**. The capture must also emit a
**[capture manifest](./capture-manifest.md)**: a missing source file on the
validation host is otherwise indistinguishable from a source that was already
missing in production, and that distinction is exactly what the policy decisions
below turn on. The producer is **implemented and has never been run**.

Then validate it before trusting anything it produces:
**[`snapshot-validation.md`](./snapshot-validation.md)**, backed by
[`backend/scripts/validate_v2_snapshot.py`](../../backend/scripts/validate_v2_snapshot.py)
— requires a read-only Mongo credential, refuses non-copy targets, refuses to
run without a capture manifest, and reports snapshot fidelity, assessability,
migration data issues and index readiness as separate verdicts. It cannot
return success from a diagnostic run (`--no-hash`, `--no-fingerprint`,
`--allow-unauthenticated`), and it cannot approve a document whose source was
unreadable at capture, because no hash exists to check the restored bytes
against.

Run by you, not by me — capture reads production and writes a dump to disk,
which is outside the read-only remit of this task. Once the snapshot exists and
the validator passes, point `db_name` at it and §2, the counts in §3, the live
half of §4 and §6 all become sound, because the data cannot move underneath
them.

---

## §2 · Dry-run — **NOT RUN**

Blocked by §1. Nothing to report, and no manifest to save. The determinism
comparison is meaningless without a frozen target.

---

## §3 · The four owner-policy decisions

**Counts and representative records are blocked by §1.** The *behaviours* are
not — they are hardcoded in `classify()` and were read out of the code, not
inferred.

### What you are actually deciding

These four behaviours are already written into `document_migration.classify()`.
`approve()` does not select them; it records that an owner saw them and accepted
them. Approving is consent to what the code will do. Rejecting means the code
changes before any migration runs — it does not mean picking a different option
from a menu that exists today.

All four carry `requires_owner_approval: True`, which is what makes `apply()`
refuse until a decision set names them.

### The exact state migration would write

Read from `_OUTCOME_BY_CODE`:

| Outcome | make_revision | point_current | reviewable | cycle | new review_status |
|---|:--:|:--:|:--:|:--:|---|
| `submitted_no_file` | yes | **no** | no | none | `migration_unrecoverable` |
| `submitted_no_reviewer` | yes | yes | no | none | `migration_unrecoverable` |
| `approved_no_file` | yes | **no** | no | none | `needs_reapproval` |
| `approved_no_reviewer` | yes | yes | no | none | `needs_reapproval` |

`reviewable: no` means `submitted_revision_id`, `submitted_version` and
`submitted_pdf_sha256` are all cleared, and for a previously-submitted document
`submitted_to` is cleared too. That is what removes it from the lawyer's queue.

### Decision table

| | `submitted_no_file` | `submitted_no_reviewer` | `approved_no_file` | `approved_no_reviewer` |
|---|---|---|---|---|
| **Legacy state** | `review_status: submitted`, has `submitted_to`, file gone | `review_status: submitted`, file present, **no** `submitted_to` | `review_status: approved`, has approver, file gone | `review_status: approved`, file present, **no** approver recorded |
| **Affected count** | *blocked — needs the copy* | *blocked* | *blocked* | *blocked* |
| **Revision written** | v1, `status: failed`, no bytes, `verification.ran: false` | v1, `generated`, real bytes | v1, `failed`, no bytes | v1, `generated`, real bytes |
| **Client sees** | "Needs to be sent again" + explanation + regenerate route | same | "Needs approval again" + explanation + resubmit route | same |
| **Lawyer queue** | **Removed** — it was in a queue, and the submission is dropped | **Never appeared** (no `submitted_to`), so no change | No change — an approval is not a queue item | No change |
| **Recovery** | Owner regenerates and resubmits | Owner picks a lawyer and submits | Owner resubmits; a lawyer re-approves | same |
| **Recommendation** | **Accept** | **Accept** | **Accept** | **Accept** |
| **Downside** | A lawyer's pending item vanishes without them acting on it | Client believes it was sent; it never was, and now says so | An approval a client relied on is withdrawn | Same, and the client may not know who approved it |

### Why I recommend accepting all four

Each refuses to assert something the legacy data cannot support, and the
alternative in every case is worse:

- **No file** means the approved or submitted bytes do not exist. Carrying an
  approval forward would state that a document nobody can produce was signed off
  — the strongest claim this system makes, resting on nothing. Leaving a
  submission pending would put a row in a lawyer's queue that can never be
  opened or cleared.
- **No reviewer** means `submitted_to` is absent, and it is the only evidence of
  who was involved. Naming somebody would attribute a decision to a real person
  who may never have made it. Leaving it submitted-to-nobody means it sits in no
  queue forever.

The honest downside is real and worth stating plainly: **a client who believed
they had an approved document will be told they do not.** That is correct, but
it will generate support contact, and it is worth deciding whether those users
are notified rather than discovering it themselves.

### Every other outcome

| Outcome | new review_status | Needs approval |
|---|---|:--:|
| `draft_with_file` | unchanged | no |
| `draft_no_file` | unchanged | no |
| `submitted_reviewable` | unchanged | no |
| `decided_bound_unverified` | unchanged | no |
| `negative_decision_no_file` | unchanged | no |
| `negative_decision_no_reviewer` | unchanged | no |

Counts for these are blocked by §1.

---

## §4 · Index preflight — expected side only

**Live definitions are blocked by §1.** The expected side and the runbook are
not.

### `v2_owner_documents`

**Expected** (`V2_INDEX_REQUIREMENTS`):

```
{ client_id: 1, schema_version: 1, created_at: -1, _id: 1 }
unique: false · sparse: false · kind: query
```

**Superseded by the read-only preflight of 2026-09-06: the index does not
exist at all**, so there is no malformed definition to replace. The expectation
recorded below was wrong, and is kept only to show what was assumed:

```
{ client_id: 1, schema_version: 1, _id: 1 }
```

Same name, different keys — the case the runbook was written around. The
preflight found no index of that name at all, so this scenario never arose. I verified the validator detects it: given the old keys it returns
`missing — expected keys [('client_id', 1), ('schema_version', 1),
('created_at', -1), ('_id', 1)]`.

Until it is replaced, `activation_readiness()` will correctly return
`ready: false` on the indexes gate.

### Blocking codes the preflight and planner can raise

`already_migrated`, `duplicate_planned_revision_id`, `missing_client_id`,
`missing_template_type`, `planned_revision_id_collision`,
`source_file_unreadable`, `unsupported_legacy_review_status`.

**Any blocked record means no approval recommendation** — `apply()` refuses a
manifest with blocked records outright.

Runbook: [`index-runbook.md`](./index-runbook.md) — written, reviewed, **not
executed**.

---

## §5 · Merged All-queue contract

Full analysis: [`allqueue-contract.md`](./allqueue-contract.md).

**Recommendation: live/keyset pagination with documented movement.** The current
implementation already satisfies it, with one caveat that needs a UI note rather
than a code change.

---

## §6 · Zero writes — **NOT APPLICABLE**

No connection was opened to production, so there is nothing to compare and
nothing could have been written. The local `attorney_ai_test` database was not
touched by this task either.

This is not the proof you asked for — that proof requires the copy, and it
requires the copy precisely because it cannot be produced against live data.

---

## §7 · Durability of this pack — **currently untracked**

`git ls-files docs/v2-activation-evidence/` returns **0**. The whole pack exists
only in this working tree: not on a branch, not on the remote, and lost to a
clean checkout or a `git clean -fdx`.

Classification of what is safe to commit, what must never be, the `.gitignore`
rule to add first (the validator writes its report *into* this directory), and
the exact command: **[`pack-durability.md`](./pack-durability.md)**.

**Nothing was committed.** `git add` was not run.

---

## GO / NO-GO

**Status: counts obtained, migration not run.** Two of the eight blockers are
dissolved and one is resolved; three remain, all small.

A read-only production survey on 2026-09-06 found **19 legacy documents**, all
readable, **0 blocked**, and **0 requiring owner approval**. Full findings:
**[`estate-survey.md`](./estate-survey.md)**.

### Dissolved or resolved

| Was | Now |
|---|---|
| Four owner-policy decisions unmade | **Nothing to decide** — 0 documents affected by any of the four outcomes |
| Blocked-record count unknown | **Zero** — no blocking condition occurs anywhere in the estate |
| No read-only credential | Created (`v2_survey`, `read` on `attorney_ai`). **Rotate or delete it** — the password was disclosed in a chat transcript |
| `document_revisions` empty and static — assumed | **Confirmed empty** |
| Eight V2 indexes missing | **Created and verified** 2026-09-06 — 0 unsatisfied requirements. See [`index-runbook.md`](./index-runbook.md) |

### Remaining

1. **No backup taken.** A `mongodump` of `attorney_ai` plus the 19 referenced
   PDFs. Seconds, not a maintenance window — but the migration writes, so a
   backup is still warranted.
2. **The evidence pack is untracked**, so the record of this review is not
   durable. See [`pack-durability.md`](./pack-durability.md).

### The proportionality point

The capture manifest, snapshot validator, two-pass artifact verification and
crash-consistent publication in this pack were built for an estate of unknown
size. **The estate is 19 documents.** That tooling is correct and tested and
would be the right answer for a real migration, but running the full
capture / restore / validate sequence here would be ceremony rather than
diligence. At this size the strongest verification is also the simplest: read
all 19 rows before and after and compare them directly.

The reduced sequence is set out in [`estate-survey.md`](./estate-survey.md).

### Corrections on the record

**The index was assumed malformed; it is absent.** This pack expected
`v2_owner_documents` to exist under the right name with the wrong keys, and
`index-runbook.md` was written around the drop→create trap that implies. A
read-only preflight found it, and all seven other V2 requirements, simply
missing. The runbook has been rewritten; the job is smaller and safer than the
one it described.

**A duplicate-risk false alarm.** The first check of
`uniq_notification_logical_event` reported it would fail on a duplicate across
594 notifications. The index is sparse, and the check had grouped rows missing
the field, manufacturing a duplicate out of nulls. Checked correctly, zero of
594 rows carry the field and the index builds cleanly.

**The estate size.** An earlier version of this pack reported it as
"~13,000 documents",
inferred from a filesystem census. **It is 19.** There are 13,386 PDFs on disk
and 19 referenced by any row — 13,367 orphans, and every referenced file is
present. A directory listing describes what is on disk; the migration reads
paths recorded in rows.

Nothing in this pack should be read as approval. No migration was run, no
manifest was approved, and `DOCUMENTS_V2` remains `False`.
