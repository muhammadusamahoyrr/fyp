# The capture manifest — contract

**The producer is implemented. It has NOT been run against production, and no
capture has been taken.** Everything below was exercised against synthetic
fixtures and fake Mongo clients only.

Schema `v2-capture-manifest`, version **2**.

| | |
|---|---|
| Contract, shared | [`backend/app/db/v2_capture_contract.py`](../../backend/app/db/v2_capture_contract.py) |
| Producer | [`backend/scripts/capture_v2_snapshot_manifest.py`](../../backend/scripts/capture_v2_snapshot_manifest.py) |
| Consumer | [`backend/scripts/validate_v2_snapshot.py`](../../backend/scripts/validate_v2_snapshot.py) |

The two sides do not each implement this document. **They import one module**,
which holds the constants, the canonical serialisation, the fingerprint, the
path-token function, the source states and every validation rule. If they held
separate copies and one drifted, the validator would report tooling differences
in the language of data loss — a `_stable()` that differs by one character makes
every fingerprint mismatch and tells the operator the estate was corrupted.
Contract-drift tests assert both modules use the shared objects, that neither
has grown a private re-implementation, and that a manifest from the producer
passes through the validator's own loader and comparison.

### Version 1 is refused, not upgraded

Version 1 predates boundary evidence. A v1 manifest was produced without
recording who established the boundary or how — which is precisely the claim the
evidence exists to support. There is no migration path because the fields were
never collected, so the loader refuses v1 with that reason rather than filling
in defaults.

---

## Why a manifest is required rather than nice to have

On the validation host, these two situations are **observationally identical**:

- production genuinely had no file at that `file_path` — a real gap in the
  estate, which migration handles with a `*_no_file` outcome;
- production had the file and the restore lost it — a broken snapshot, and any
  manifest derived from it is worthless.

Both look like "no file here". No amount of care on the validation host tells
them apart, because the evidence that would distinguish them existed only at
capture time and was not written down.

That is why the validator **refuses to run** without a manifest rather than
proceeding and calling every gap a defect (which condemns a healthy estate) or
calling every gap normal (which lets a broken restore through).

`--no-manifest-mode` runs anyway for diagnosis. It reports
`snapshot_fidelity_ok: null`, `snapshot_fidelity_assessable: false` and
`dry_run_safe: false`, and **returns exit 2**. There is no combination of flags
that makes a manifest-less run succeed.

---

## Structure

```json
{
  "schema": "v2-capture-manifest",
  "schema_version": 2,

  "capture_id": "cap_20260906T020000Z_ab12cd",
  "database": "attorney_ai",
  "production_upload_root": "/app/backend/uploads",

  "capture_method": "quiesced",
  "writes_quiesced": true,
  "capture_started_at": "2026-09-06T02:00:00+00:00",
  "capture_finished_at": "2026-09-06T02:14:00+00:00",

  "boundary": {
    "method": "quiesced",
    "operator": "usama",
    "attestation": "Scaled the API to zero, confirmed no live connections, dumped Mongo and rsynced the artifact store, then resumed.",
    "deployment_id": "prod-atlas-cluster0",
    "snapshot_id": null,
    "externally_verified": false,
    "producer_cannot_prove_quiescence": true
  },

  "producer": {
    "tool": "capture_v2_snapshot_manifest",
    "version": 1,
    "credential_verified_read_only": true,
    "credential_roles": ["read"],
    "armed_for_production": true,
    "protection_verified": true,
    "output_protection": "owner-only ACL",
    "artifact_passes": 2
  },

  "document_count": 1284,
  "database_fingerprint": {
    "algorithm": "sha256-canonical-json-v1",
    "collections": {
      "documents": "9f2c…",
      "document_revisions": "41ab…"
    }
  },

  "documents": [
    {
      "document_id": "kR3f…",
      "path_token": "8c1d5e77a91b0f42",
      "source_state": "readable",
      "sha256": "e3b0c442…",
      "size": 148213,
      "path_flags": [],
      "error_class": null
    }
  ],

  "summary": {
    "source_states": {"readable": 1281, "missing_source": 2, "absent_path": 1},
    "path_flags": {},
    "collection_counts": {"documents": 1284, "document_revisions": 0}
  }
}
```

---

## Fields

### Identity and boundary

| Field | Type | Rule |
|---|---|---|
| `schema` | string | Must be `v2-capture-manifest` |
| `schema_version` | int | Must be `2`. Version 1 is refused, not upgraded |
| `capture_id` | non-empty string | Names this capture. Appears in the validation report so a report can be tied to a snapshot. |
| `database` | non-empty string | The database captured (i.e. `attorney_ai`). Recorded, not enforced. |
| `production_upload_root` | non-empty string | The production `UPLOAD_ROOT` at capture time. The validator uses it to remap absolute paths, so a wrong value here degrades every path to a basename match — which is itself fatal. |
| `capture_method` | enum | **`quiesced` or `atomic_snapshot` only.** Anything else is refused. |
| `writes_quiesced` | bool | Must be `true` when `capture_method` is `quiesced`. |
| `capture_started_at` | non-empty string | ISO 8601, **timezone-aware, UTC**. |
| `capture_finished_at` | non-empty string | ISO 8601, **timezone-aware, UTC**. |

`capture_method` is where the "ordering is not a boundary" rule lives as code
rather than prose. See [`snapshot-runbook.md`](./snapshot-runbook.md).

#### The timestamps are parsed, not merely present

Both are parsed with `datetime.fromisoformat` and then checked:

| Refused | Why |
|---|---|
| Malformed or non-ISO strings, non-strings | Not a timestamp |
| A naive value (no offset) | A boundary stated in an unknown zone cannot be compared with anything, including the other boundary |
| Any non-zero UTC offset | The contract is UTC. `+00:00` and `Z` are both accepted |
| `capture_finished_at` before `capture_started_at` | Not a real interval |
| A **zero-length** window when `capture_method` is `quiesced` | Quiescing, dumping and resuming takes time. Zero means the timestamps were stamped rather than measured, so the boundary is unevidenced |

A zero-length **atomic** snapshot is accepted: one instant is what atomic means.
The parsed duration is carried into the validation report as `capture_seconds`.

### `boundary` — the evidence, and what it is not

| Field | Rule |
|---|---|
| `method` | Must equal the top-level `capture_method`. A manifest whose two halves disagree does not describe one boundary |
| `operator` | Non-empty. Unattributed evidence is not evidence |
| `deployment_id` | Non-empty. Which deployment this came from |
| `attestation` | At least 20 characters stating **what was actually done**. Shorter is a checkbox, not a statement |
| `externally_verified` | Boolean. Must be `true` for `atomic_snapshot` |
| `snapshot_id` | Required and non-empty for `atomic_snapshot`; must be `null` for `quiesced` |
| `producer_cannot_prove_quiescence` | Must be `true` — see below |

**The producer cannot prove the application was quiesced.** Nothing observable
from a database client can. What it does instead is fingerprint the database
before and after the artifact scan and refuse if anything moved, and stat every
file before and after hashing it and refuse if it changed.

Those are tripwires, not proof. They detect a boundary that was never held or
that broke while the producer ran. **They do not establish one, and they are not
a substitute for stopping application writes** — a capture whose tripwires stay
silent for the fifteen seconds it looked is not evidence of a quiet fifteen
minutes.

`producer_cannot_prove_quiescence` is a required constant precisely so that
statement travels with the artefact rather than living only in a runbook nobody
re-reads. A manifest is refused if it is absent or false.

For `atomic_snapshot` the same logic applies one level up: the producer cannot
confirm that a storage snapshot was actually atomic, so it demands both a
`snapshot_id` and an explicit external verification, and refuses without them.

### `producer` — how the capture itself was taken

| Field | Rule |
|---|---|
| `tool` | Must be `capture_v2_snapshot_manifest` |
| `version` | Integer |
| `credential_verified_read_only` | **Must be `true`.** A capture taken on a connection that could write is not approval-grade, and the manifest has to say so itself |
| `protection_verified` | **Must be `true`.** Owner-only permissions on the output directory were established *and read back* before the manifest was written |
| `artifact_passes` | How many complete artifact observations were made. The producer makes two |

There is no unauthenticated capture path and there will not be one. The
validator has a diagnostic mode for an unauthenticated target because a
validation run that could write is merely not approval-grade; a *capture* taken
on such a connection is not evidence of anything.

### Database state

| Field | Type | Rule |
|---|---|---|
| `document_count` | int | Must equal `len(documents)`. A manifest that disagrees with itself is truncated, and a truncated manifest cannot prove anything about what was omitted — refused. |
| `database_fingerprint.algorithm` | string | Must be `sha256-canonical-json-v1`. |
| `database_fingerprint.collections` | object | **Exactly** `documents` and `document_revisions` — see below. |

#### `database_fingerprint.collections` is exact, not a minimum

| Refused | Why |
|---|---|
| A missing required collection | The migration reads and writes both; an unfingerprinted one is unverified |
| **Any extra collection** | It would be recorded and never compared, which reads as coverage the run does not have |
| A digest that is not a 64-character hex string — `null`, a boolean, a number, a list, the wrong length, non-hex characters | It is not a SHA-256 |
| Two keys equivalent after trimming and case-folding (`"documents"` and `" Documents "`) | One digest would silently win |

Digests are case-normalised to lowercase, so an uppercase hex digest is accepted
rather than rejected on presentation.

**`sha256-canonical-json-v1`**, exactly as `canonical_fingerprint()` computes it:

1. For each document, serialise with `json.dumps(doc, sort_keys=True,
   separators=(",", ":"), ensure_ascii=True)`, encoding BSON types the encoder
   cannot handle as `dt:<UTC ISO 8601>` for datetimes (naive treated as UTC),
   `bin:<sha256 hex>` for binary, and `<TypeName>:<repr>` otherwise.
2. SHA-256 each serialised document.
3. Sort the digests as raw bytes.
4. SHA-256 the concatenation.

Sorting the digests makes the fingerprint independent of the order the server
returns documents in, so it needs no indexed sort and cannot fail spuriously on
a differently-ordered restore.

### Per-document source state

One entry per document in the `documents` collection.

| Field | Type | Rule |
|---|---|---|
| `document_id` | non-empty string | The `_id`. Must be unique within the manifest. |
| `path_token` | 16-hex string, or null | `sha256(file_path)[:16]`. Identifies the path without carrying the title. **Null if and only if `source_state` is `absent_path`.** |
| `source_state` | enum | One of the four below. |
| `sha256` | string(64 hex) or null | **Required** when `readable`; **must be null** otherwise. |
| `size` | non-negative int or null | **Required** when `readable`; **must be null** otherwise. Booleans are not integers here. |

#### `path_token` ties the hash to a path, and is enforced

A hash is a claim about **one specific file**. A hash checked against the wrong
path proves nothing, and a swapped `path_token` is precisely how a manifest
entry could be made to "verify" a file it never described.

- `absent_path` with a token → refused: nothing could have produced it.
- Any other state without a 16-hex token → refused: a path was recorded, so it
  must be identified.
- Tokens are case-normalised to lowercase.
- **At comparison time the token is checked against the restored row's own
  `file_path`, before anything else about that document.** A mismatch is a fatal
  `file_path_mismatch`, reported alone — every other finding for that document
  would be derived from the wrong file and would only add noise.

#### The four source states

| State | Means | Observed at capture by |
|---|---|---|
| `readable` | A path is recorded and its bytes were read | `read_bytes()` succeeded |
| `absent_path` | The row records **no** `file_path` at all | `file_path` is null/absent |
| `missing_source` | A path is recorded and nothing is there | `FileNotFoundError` |
| `unreadable_source` | A path is recorded and the read failed for another reason | any other `OSError` |

These mirror `document_migration.read_source()` exactly, and the last two are
kept apart for the same reason it keeps them apart: `missing` withdraws an
approval, `unreadable` **blocks** the record for a human. A capture that
collapsed them would destroy the distinction before validation ever saw it.

A `readable` entry with no hash is refused — a readable source without a hash
cannot be verified after restore, which is the manifest's whole purpose. A
non-`readable` entry carrying a hash is refused too: nothing could have produced
it, so the manifest is not describing what it claims to describe.

---

## How the validator uses each state

**Checked first, for every state:** the manifest's `path_token` against the
restored row's `file_path`. A mismatch is `file_path_mismatch` — **fatal** — and
nothing else is evaluated for that document.

| At capture | After restore | Verdict |
|---|---|---|
| `readable` | resolved, sha + size match | **fidelity OK** |
| `readable` | resolved, sha differs | `source_content_mismatch` — **fatal** |
| `readable` | resolved, size differs | `source_size_mismatch` — **fatal** |
| `readable` | matched by basename only | `weak_match` — **fatal** |
| `readable` | missing / unreadable / outside root | `source_lost_in_restore` — **fatal** |
| `missing_source` | missing | `source_missing_in_production` — **migration data issue**, copy is faithful |
| `missing_source` | present | `source_appeared_after_restore` — **fatal** |
| `missing_source` | no path recorded | `file_path_lost` — **fatal** |
| `unreadable_source` | **anything at all** | `source_unreadable_in_production` (migration data issue) **and** `source_unassessable_no_capture_hash` — **blocks approval** |
| `absent_path` | no path recorded | **fidelity OK** |
| `absent_path` | a path appeared | `file_path_appeared` — **fatal** |
| in manifest, not in restore | — | `omitted_document` — **fatal** |
| not in manifest, in restore | — | `unexpected_document` — **fatal** |

Two rows carry most of the design.

**`missing_source` → missing** is the case that used to fail the run and now
passes it, correctly: the copy did its job, and the gap is a fact about the
estate that the migration policy decisions already exist to handle.

**`unreadable_source` → anything** fails closed. Capture could not read the
file, so **no captured hash exists**, so nothing on the validation host can
establish that the restored bytes are the right bytes — including the case where
a perfectly readable file is sitting there after the restore. It is a real fact
about the estate *and* a hole in the evidence, so it is recorded as both, and
`dry_run_safe` stays `false`. All five restored states are covered by tests.

---

## Producing it

**Implemented, never run against production.**
[`capture_v2_snapshot_manifest.py`](../../backend/scripts/capture_v2_snapshot_manifest.py).

It must run **on the production host, inside the boundary**, because a
`file_path` is only resolvable there. Run before the boundary opens or after it
closes and the manifest describes a different moment from the snapshot, which
puts the validator back to guessing while looking authoritative.

```
python backend/scripts/capture_v2_snapshot_manifest.py \
    --mongo-uri     "mongodb://v2_capture:<pw>@<host>/?authSource=admin" \
    --db            attorney_ai \
    --upload-root   /app/backend/uploads \
    --capture-method quiesced \
    --operator      "<name>" \
    --attestation   "Scaled the API to zero, confirmed no live connections, …" \
    --deployment-id prod-atlas-cluster0 \
    --acknowledge-production-read \
    --out           ~/v2-capture/capture-manifest.json
```

| Exit | Meaning |
|:--:|---|
| 0 | A manifest and its detached checksum were written |
| 2 | Refused — the target, the arming, or the inputs did not meet the contract |
| 3 | **The boundary did not hold** — the database or a file changed mid-capture |
| 4 | Unexpected error, reported by exception class only |

### What it refuses

- **Production, by default.** `--acknowledge-production-read` is required before
  it will read a target whose database name, `mongodb+srv` scheme or hosted host
  identifies it as production. Reading production is the point of this tool; it
  is never the default, and a refused target is never connected to.
- **A connection that could write**, checked **before** anything is read, and
  before the credential appears in the manifest. There is no unauthenticated
  path.
- **An ordered live capture** — `argparse` does not offer it as a choice.
- **An atomic snapshot without a `snapshot_id` and external verification.**
- **Overwriting an existing manifest.** A manifest is evidence tied to one
  boundary.
- **Writing anywhere inside the repository.** A manifest names every document in
  the estate; the default output is under `~/v2-capture/`.

### What it never does

**It does not repair, normalise or rewrite a stored path.** A `..` in a
`file_path`, a symlink, a file resolving outside `UPLOAD_ROOT` — each is
recorded as a `path_flag` and left exactly as it is. A capture that fixes
something has captured a state that never existed in production, and the
migration would then be planned against a fiction.

It also never loads a file into memory to hash it: sources are hashed by
streaming, in one-megabyte chunks, because a legacy estate can hold files large
enough that `read_bytes()` is a choice rather than a detail.

### Two complete artifact passes

Every source is observed and hashed, Mongo is fingerprinted, and then **every
source is observed and hashed again**. The two passes are compared on
`path_token`, `source_state`, `size`, `sha256` and `path_flags`, and any
difference is `BOUNDARY_BROKEN`.

The second pass is not belt-and-braces. A single pass structurally cannot notice
a file rewritten *after* it was hashed — that file's own before/after stat pair
had already closed. Readable→missing, missing→readable, readable→unreadable, a
same-size replacement, and a symlink retargeted mid-capture are all invisible to
one pass and caught by two.

### Output safety

**The invariant: a final manifest never exists without a valid checksum beside
it.** Publication is ordered to guarantee it:

1. **preflight both finals** — if either the manifest or the checksum already
   exists, the run refuses before staging anything;
2. **stage both**, fsynced, owner-only;
3. **publish the checksum first**;
4. **publish the manifest last**, as the completion marker.

A crash between steps 3 and 4 leaves an orphan checksum: detectable, harmless,
and obviously incomplete. The reverse order would leave a manifest whose
integrity nobody could confirm — which looks exactly like a good one. Each
publication uses `os.link`, which refuses when the target exists, falling back
to an `O_CREAT|O_EXCL` claim on filesystems without hard links. Neither path can
overwrite.

On a **handled** failure, only files this invocation created are removed, newest
first. A pre-existing file is never touched: cleanup that deletes someone else's
evidence is worse than the failure it is tidying after. Abrupt termination
cannot clean up at all, which is why the ordering rather than the cleanup is
what carries the guarantee.

Files are written **in binary**: text mode translates newlines on Windows, so
the bytes on disk would not be the bytes that were hashed and the detached
`<manifest>.sha256` would never verify on the platform that wrote it.

### Output protection

Owner-only, applied **and read back** — "we called chmod" is not the same claim
as "the permissions are what we asked for":

- **POSIX:** directory `0700`, files `0600`, verified by `stat`.
- **Windows:** `icacls /inheritance:r` then a single grant to the running
  account, verified by parsing `icacls` back and refusing if any other principal
  retains access. A POSIX mode check there would pass while the directory stayed
  readable by everyone, because Windows ignores `chmod` beyond the read-only bit.

A failure to establish protection is **refused**, not logged and shrugged at —
the run exits non-zero and writes nothing. `protection_verified: true` is
required by the contract, so a manifest cannot claim approval-grade without it.

### Redaction

Nothing it prints carries a credential, a path, a document title, or a raw
driver exception — failures are reported as a stage plus an exception class
name. The manifest itself carries `path_token`s, never paths.
