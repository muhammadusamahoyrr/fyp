# Capturing a snapshot the dry-run can actually use

**NOT EXECUTED.** Procedure only. Nothing here was run, no snapshot was taken,
and `DOCUMENTS_V2` stays `False` throughout.

---

## The correction

The earlier version of this pack said a `mongodump` would be enough. **It would
not**, and the failure mode is severe rather than partial.

`document_migration` does not read documents only from Mongo. For every legacy
row it calls:

```python
source = read_source(doc.get("file_path"))   # reads the bytes, hashes them
```

`classify()` then branches on `source.present`. On a Mongo-only restore every
`file_path` points at a file that is not there, so `read_source` returns
`FileNotFoundError → present=False`, and **every document in the estate
classifies as `*_no_file`**:

- every submitted document → `submitted_no_file` → `migration_unrecoverable`
- every approved document → `approved_no_file` → `needs_reapproval`

The dry-run would complete, report `complete: true`, and produce a manifest
stating the entire estate is unrecoverable. Nothing in it would look broken.
That is the worst possible evidence: confidently wrong, and pointing at exactly
the four decisions you are being asked to approve.

### And the paths are absolute

`document_service` stores `doc["file_path"] = str(file_path)` where the path
comes from `pdf_generator`, whose target is:

```python
UPLOADS_DIR = Path(settings.upload_root) / "docs"
```

`upload_root` defaults to `<repo>/backend/uploads` and is environment-specific.
So a production row holds an absolute path **from the production host**. Copying
the PDFs is not sufficient either — they must land where the stored absolute
paths resolve, or the paths must be rewritten. See "Path mapping" below.

---

## What has to be captured

### Mongo collections

| Collection | Why | Needed for |
|---|---|---|
| `documents` | the estate being migrated | dry-run, apply, readiness |
| `document_revisions` | planned-revision-id collision check; already-migrated detection | dry-run, apply |

Those two are what the migration itself reads and writes. Capture these as well,
because the evidence pack's other checks and any realistic post-restore
verification need them:

| Collection | Why |
|---|---|
| `cases` | `create_document` and `submit` authorise against it; queue-visibility reasoning |
| `users` | KYC and engagement checks in `submit` |
| `review_events`, `transition_receipts` | transition history; needed if you exercise the queue after restore |

A full-database dump is simpler and safer than an enumerated subset, and avoids
a later "we forgot X". Prefer it unless size forbids.

### Artifact directories

| Path | Contents | Needed |
|---|---|---|
| `${UPLOAD_ROOT}/docs/` | **the legacy PDFs `file_path` points at** | **Yes — this is the omission** |
| `${UPLOAD_ROOT}/v2/docs/` | V2 finals | Only if a prior migration ran; expected absent |
| `${UPLOAD_ROOT}/v2/tmp/` | staging + claims | No — transient by design |

Record the production `UPLOAD_ROOT` value at capture time. The validator needs
it to compute the path mapping.

---

## The capture boundary must be frozen

Rows and PDFs are two different stores. If they are captured at different
moments, they can disagree, and the disagreement is silent:

- a document row written **after** the file capture → its PDF is missing from
  the snapshot → classifies `*_no_file` → a false "unrecoverable"
- a file written **after** the row capture → an orphan PDF no row references →
  harmless, but it inflates the artifact-coverage check

Both directions corrupt the very counts the four policy decisions rest on.

**There are exactly two acceptable boundaries:**

1. **Application writes quiesced for both captures.** Stop writes (maintenance
   mode, scale to zero, or a read-only application credential), capture Mongo
   and the artifacts, resume. Nothing can change while the two captures run, so
   they cannot disagree.
2. **A genuinely atomic cross-store snapshot** — one storage-level operation
   covering both the database volume and the upload volume, at one instant. If
   the two live on volumes that cannot be snapshotted together atomically, this
   option does not apply; use option 1.

**Inside the boundary**, and before it closes, emit the
[capture manifest](./capture-manifest.md): capture id, start and end as UTC
ISO-8601, method, production `UPLOAD_ROOT`, document count, the canonical
per-collection fingerprint, and one entry per document recording whether its
source file was readable, missing, unreadable, or never recorded at all — with a
SHA-256 and byte size for each readable one.

The validator **refuses to run without it**, because it is the only evidence
that separates a file production never had from a file the restore lost.

Emitting it inside the boundary is not a detail. Run it before the boundary
opens or after it closes and it describes a different moment from the snapshot,
which puts the validator back to guessing while looking authoritative.

**The producer is implemented and has never been run against production:**
[`capture_v2_snapshot_manifest.py`](../../backend/scripts/capture_v2_snapshot_manifest.py).
Command and refusals in [`capture-manifest.md`](./capture-manifest.md). It needs
a **read-only Mongo credential on the production host** and refuses production
outright unless `--acknowledge-production-read` is passed.

Three things it can do, and one it cannot:

- It fingerprints the database before and after the artifact scan, and stats
  every file before and after hashing it, refusing if anything moved.
- It observes and hashes **every source twice**, comparing the two passes on
  path token, source state, size and SHA-256. A single pass cannot notice a file
  rewritten after it was hashed — that file's own stat pair had already closed.
- It refuses to write anywhere it cannot establish **and read back** owner-only
  permissions, and publishes the checksum before the manifest so a manifest
  never exists without one.
- **It cannot prove the application was quiesced.** No database client can. The
  tripwires are not a substitute for stopping writes — holding the boundary is
  still your job, and the manifest records that you attested to it rather than
  that anything verified it.

### Why ordering is not a third option

An earlier version of this runbook offered "files first, then Mongo, during a
quiet window" as an acceptable fallback. **It has been removed.** The reasoning
behind it was that the resulting inconsistency runs in the harmless direction —
orphan PDFs rather than missing ones.

That reasoning is wrong in the way that matters. Ordering controls **which
direction** the two stores disagree. It does nothing about **whether** they
disagree, and the validator's job is to establish that they do not.

Concretely, under a live ordered capture:

- A document row updated between the file capture and the Mongo capture — a
  regenerated PDF, say — is captured with the **new** `file_path` and the
  **old** bytes, or no bytes at all. That is a `source_lost_in_restore` the
  operator will spend a day chasing, and it originated in the capture, not the
  restore.
- "A demonstrably quiet window" is a claim about traffic, not a guarantee about
  it. One submission at the wrong second produces exactly the failure the
  capture was supposed to rule out, and nothing in the artefacts says which
  second that was.
- Recording the window bounds lets you *discount* a suspect document by hand.
  Discounting by hand is not verification — it is the operator overriding the
  check, on the same evidence that made the check fail.

The capture manifest schema encodes this: `capture_method` accepts only
`quiesced` and `atomic_snapshot`, and a manifest naming anything else is
**refused** by the validator rather than argued with.

---

## Restore

Restore under a name that cannot be confused with production:

```
mongorestore --uri "mongodb://localhost:27017" \
             --nsFrom "attorney_ai.*" --nsTo "attorney_ai_snapshot.*" <dump>
```

Place the artifacts under a validation root, e.g. `/srv/v2-validation/uploads`,
preserving the `docs/` subdirectory:

```
/srv/v2-validation/uploads/docs/<the legacy PDFs>
```

### Path mapping

Stored `file_path` values are absolute production paths. Two options:

**A — Mirror the production path on the validation host (preferred).**
Recreate the production `UPLOAD_ROOT` path exactly, or bind-mount /
symlink it to the validation root:

```
# production UPLOAD_ROOT was e.g. /app/backend/uploads
mkdir -p /app/backend
ln -s /srv/v2-validation/uploads /app/backend/uploads
```

Nothing is rewritten, so the snapshot stays byte-identical to production and the
dry-run exercises the same code path with the same inputs. **This is the option
that keeps the evidence trustworthy.**

**B — Rewrite `file_path` in the restored database.** Only on the restored copy,
never production. It changes the data the evidence is drawn from, so if you take
this route, record the exact transformation and re-run the validator afterwards.
Prefer A.

The validator (below) reports which mapping is in effect and refuses to pass if
neither resolves.

---

## After restore

Run the validator before the dry-run, as a **read-only Mongo user**:

```
python backend/scripts/validate_v2_snapshot.py \
    --mongo-uri        "mongodb://v2_validator:<pw>@localhost:27017/?authSource=admin" \
    --db               attorney_ai_snapshot \
    --upload-root      /srv/v2-validation/uploads \
    --capture-manifest /srv/v2-validation/capture-manifest.json \
    --report           /srv/v2-validation/snapshot-validation.json
```

Create that user on the validation host beforehand, with `read` on the restored
database and nothing else. The validator refuses a credential holding any
write-capable role — that refusal is the only isolation guarantee in the whole
procedure that does not depend on someone typing the right thing.

Write the report **outside the repository**. It carries document ids, and with
`--include-paths` it carries paths that embed document titles.

It fails closed on any fidelity problem, and it refuses to run at all without a
capture manifest, because without one a missing source file is indistinguishable
from a source file that was already missing in production. See
[`snapshot-validation.md`](./snapshot-validation.md).

Only when `snapshot_fidelity_ok` is `true` is a `dry_run()` worth running — and
only then are the counts in the owner decision table meaningful.
