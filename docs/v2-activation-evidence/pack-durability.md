# Making this pack durable

**Nothing was committed.** `git add` was not run. This file classifies what is
safe to commit and states the command; the decision and the commit are yours.

---

## Current state: entirely untracked

```
$ git ls-files docs/v2-activation-evidence/ | wc -l
0
```

Every file in the pack is `??` in `git status`. Nothing is ignored — `docs/` is
not in `.gitignore` and `git check-ignore` returns nothing for these paths — so
they are untracked simply because they were never added.

That means **the entire activation evidence pack exists only in this working
tree.** It is not in any branch, not on the remote, and not in any backup that
covers the repository rather than the disk. A clean checkout loses it; so does
`git clean -fdx`, which is a command anyone might run on a tree with this many
untracked files.

Its whole purpose is to be the record that someone consulted before touching
production data. A record that exists in one place, on one laptop, is not that.

---

## Classification

### Safe to commit — no credentials, no PII, no production data

| File | Why it is safe |
|---|---|
| `README.md` | Findings, code-derived behaviour tables, GO/NO-GO. Names the deployment by **host class** only (`mongodb+srv`, `*.mongodb.net`) — no host, no user, no password, no database contents. |
| `snapshot-runbook.md` | Procedure. Paths are placeholders (`<prod URI>`, `/srv/v2-validation`). |
| `snapshot-validation.md` | Procedure and tool documentation. |
| `index-runbook.md` | Index definitions and `explain` shapes. Placeholders for ids. |
| `allqueue-contract.md` | Design analysis of code already in the tree. |
| `outcome-counts.json` | Machine-readable summary. **The counts drawn from production data are `null`** — every `affected_count`, `blocked_records.counts_by_code`, and the observed index state — because the dry-run was never run. It does carry other numbers (schema versions, test and mutation counts, index key directions); none of those come from the estate. |
| `purge-backups-audit.md` | Aggregates and categories only. No name, address, hash, case detail or filename content. |
| `capture-manifest.md` | A schema definition with synthetic examples. |
| `mutation-evidence.json` | Mutation labels, catching test names, and SHA-256 hashes of the source and test files. No production data, no paths, no titles. |
| `backend/app/db/v2_capture_contract.py` | The shared contract module. |
| `backend/scripts/capture_v2_snapshot_manifest.py` | The producer. Tooling, and it has never been run. |
| `backend/scripts/v2_mutation_evidence.py` | The mutation harness that writes the evidence file. |
| `backend/tests/test_v2_capture_contract.py`, `test_capture_v2_snapshot_manifest.py`, `v2_fakes.py` | Their tests and fakes. Synthetic fixtures only. |
| `pack-durability.md` | This file. |
| `backend/scripts/validate_v2_snapshot.py` | Tooling. Belongs in the repo on its own merits. |
| `backend/tests/test_validate_v2_snapshot.py` | Its tests. Synthetic fixtures only. |

I re-read each of the above for this classification rather than assuming what I
wrote. The one that needed the closest look was `purge-backups-audit.md`,
because its subject is a file full of personal data — it reports counts and
domain classes, and quotes no record.

### Never commit

| Path | Why |
|---|---|
| `backend/data/purge_backups/**` | **27** user records (24 in the fixture purge + 3 in the test-accounts file), 23 password hashes, plus cases and notifications. Already excluded at `.gitignore:124` — **leave that line alone.** |
| `snapshot-validation.json` | The validator's report. Carries document ids and, with `--include-paths`, real file paths containing user-chosen titles. The runbook now writes it outside the repo; the ignore rule is the backstop. |
| `capture-manifest.json` | Describes production's estate document by document — every id, every path token, every hash. |
| `.env`, any URI with credentials | Never anywhere in the pack. |
| Any `mongodump` output | Production data by definition. |

### The ignore rule — **added**

A defaulted `--report` lands in this directory. If the directory were tracked
without a rule, the first person to follow the runbook would commit a report
containing document ids. Now at `.gitignore:131–135`:

```
docs/v2-activation-evidence/*.json
!docs/v2-activation-evidence/outcome-counts.json
!docs/v2-activation-evidence/mutation-evidence.json

capture-manifest*.json
```

Deny every JSON in the pack, re-admit the two that are verifiably free of
production data, and deny capture manifests anywhere in the tree — a manifest
describes production's estate document by document, which is also why the
producer's default output is `~/v2-capture/` and why it refuses any `--out`
inside the repository. The ordering matters: the negations only work after the
broader deny.

Verified with `git check-ignore`: `snapshot-validation.json` and
`capture-manifest.json` are ignored; `outcome-counts.json`,
`mutation-evidence.json` and every `.md` remain untracked-but-committable.

---

## Committing it

```
git add docs/v2-activation-evidence/*.md \
        docs/v2-activation-evidence/outcome-counts.json \
        docs/v2-activation-evidence/mutation-evidence.json \
        backend/app/db/v2_capture_contract.py \
        backend/scripts/capture_v2_snapshot_manifest.py \
        backend/scripts/validate_v2_snapshot.py \
        backend/scripts/v2_mutation_evidence.py \
        backend/tests/test_validate_v2_snapshot.py \
        backend/tests/test_v2_capture_contract.py \
        backend/tests/test_capture_v2_snapshot_manifest.py \
        backend/tests/v2_fakes.py
git status --short   # confirm nothing under backend/data/ appears
git commit
```

Run the `git status --short` line and read it. It is the last chance to notice
a purge backup that slipped in behind a wildcard.

Suggested message:

```
docs(v2): activation evidence pack, snapshot runbook and validator

Records what was checked before any DOCUMENTS_V2 migration, and why the
verdict is NO-GO. Adds a read-only snapshot validator that fails closed
when a restored snapshot is missing its artifact half -- the case that
otherwise produces a manifest falsely declaring the estate unrecoverable.

DOCUMENTS_V2 remains False. No migration was run and no manifest approved.
```

---

## Recommendation

Commit it, on a branch, before the maintenance window. Two reasons beyond
durability:

1. **It becomes reviewable.** The four policy decisions, the index procedure and
   the artifact-coverage argument are things another person should be able to
   read and disagree with. A diff is how that happens.
2. **It timestamps the NO-GO.** If the migration is later run, the record of
   what was known beforehand — and that the verdict at the time was NO-GO —
   should predate it in history rather than be reconstructed after.

Per the standing rule in this repository, I have not committed or pushed
anything. This is a recommendation with the command attached.
