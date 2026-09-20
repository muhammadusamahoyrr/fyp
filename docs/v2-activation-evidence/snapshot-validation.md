# Validating a restored snapshot before the dry-run

**NOT EXECUTED against real data.** No snapshot exists, so this procedure has
never run outside synthetic fixtures. `DOCUMENTS_V2` stays `False`.

Tool: [`backend/scripts/validate_v2_snapshot.py`](../../backend/scripts/validate_v2_snapshot.py)
Tests: [`backend/tests/test_validate_v2_snapshot.py`](../../backend/tests/test_validate_v2_snapshot.py)
Contract it enforces: [`capture-manifest.md`](./capture-manifest.md)

---

## What this catches

A restored snapshot can be wrong in a way that looks entirely healthy. If Mongo
is restored and `UPLOAD_ROOT/docs` is not — or the PDFs land where the stored
absolute paths do not resolve — then `read_source()` returns
`FileNotFoundError → present=False` for every row, and `dry_run()` completes
successfully with a manifest declaring the entire estate unrecoverable.

Nothing about that manifest signals a problem. It has a real fingerprint, real
counts, `complete: true`, and it points squarely at the four decisions you are
being asked to approve.

---

## Two things this tool refuses to confuse

### 1. A gap in the estate is not a gap in the copy

A missing source file on the validation host has two possible causes, and they
are **observationally identical**: production genuinely had no file there, or
the restore lost it. The first is a fact about the estate that the migration
policy decisions exist to handle. The second invalidates everything downstream.

The only evidence that separates them was available at capture time — the
[capture manifest](./capture-manifest.md) — so **the validator refuses to run
without one.** Guessing "defect" condemns a healthy estate; guessing "normal"
passes a broken restore.

### 2. "Not found to be wrong" is not "checked and found sound"

Two different situations leave a hole where evidence should be, and neither may
produce a passing run:

- **A capture gap.** A source that was `unreadable_source` at capture has **no
  captured hash**, so nothing on the validation host can establish that the
  restored bytes are the right bytes — not even a file sitting there looking
  perfectly fine. It is recorded as a migration data issue *and* as
  unassessable, and it blocks approval.
- **A degraded mode.** `--no-hash`, `--no-fingerprint` and
  `--allow-unauthenticated` each switch off a check the approval rests on.

Both land in `unassessable`, tagged `source: "capture"` or
`source: "degraded_mode"` so the two are never mistaken for each other. Either
way, `dry_run_safe` is `false` and the exit code is non-zero.

---

## Verdicts, kept apart

| Verdict | Question | Effect |
|---|---|---|
| `snapshot_fidelity_ok` | Is anything demonstrably **wrong** with the copy? | False → exit 2 |
| `fully_assessable` | Could every document actually be **checked**? | False → exit 2 or 5 |
| `migration_data_issues` | What is wrong with the estate itself? | Informs the policy decisions. Never fails the run |
| `index_readiness` | Do the index definitions conform? | Gates activation, later. Never fails the run |
| `dry_run_safe` / `snapshot_approval_ready` | All of the above, with no degraded mode | The only thing that authorizes a dry-run |

Two consequences worth stating plainly:

- **Duplicate legacy paths and sources that were missing in production are
  migration data issues, not snapshot failures.** A faithful copy of a flawed
  estate is a *successful* copy.
- **A faithfully copied index problem is fidelity working.** All eight V2
  indexes are absent in production ([`index-runbook.md`](./index-runbook.md)),
  so `index_readiness: false` on a good snapshot is the expected result — the
  copy is reproducing production correctly.

### Why it is `index_readiness`, not `activation_readiness`

`document_migration.activation_readiness()` checks the flag, the approved
manifest, blocked records and the queue-visibility gap as well as the indexes.
This validator checks **index definitions only**. Naming its result after that
contract would invite a green index check to be read as a green activation,
which it is not — so the field is `index_readiness` and carries a `scope` note
saying what it is not.

---

## Running it

```
python backend/scripts/validate_v2_snapshot.py \
    --mongo-uri        "mongodb://v2_validator:<pw>@localhost:27017/?authSource=admin" \
    --db               attorney_ai_snapshot \
    --upload-root      /srv/v2-validation/uploads \
    --capture-manifest /srv/v2-validation/capture-manifest.json \
    --report           /srv/v2-validation/snapshot-validation.json
```

`--prod-upload-root` is taken from the manifest; pass it only to override.
Write the report **outside the repository** — it carries document ids.

| Exit | Meaning |
|:--:|---|
| 0 | Faithful, fully assessed, no degraded mode. A dry-run is worth running |
| 2 | **Failed** — fidelity broken, or something could not be assessed |
| 3 | **Refused** — the target or the inputs did not meet the contract |
| 4 | Validation ran; the report could not be written. Treat the run as not having happened |
| 5 | **Diagnostic** — nothing found wrong, but checks were weakened. Not approval |
| 6 | Unexpected error, reported by exception class only |

### The diagnostic flags

| Flag | Switches off | What becomes invisible |
|---|---|---|
| `--no-hash` | artifact content verification | a corrupted PDF **of the same length** as the captured one |
| `--no-fingerprint` | database content verification | a **modified document** that leaves the row count unchanged |
| `--allow-unauthenticated` | the read-only credential guarantee | whether this run could write at all |
| `--no-manifest-mode` | fidelity assessment entirely | everything above |

Each is legitimate for diagnosis and none is legitimate for approval. A run
using any of them prints a `DIAGNOSTIC RUN` banner and cannot return exit 0.
Both invisible cases above are covered by paired tests: one proving the fault
really is invisible to the degraded run (so the flag genuinely must not bless
it), and one proving the same fault is caught with the check enabled.

---

## Production isolation: what is a guardrail and what is evidence

**The name and host checks are guardrails, not proof.** They stop a typo. They
do not stop an operator who means it, and they are not evidence that production
was untouched. The report says so in `target.guardrails_are_not_proof`.

Guardrails, all of which must pass:

- `attorney_ai` is refused outright; a database name lacking one of `snapshot`,
  `validation`, `restore`, `copy`, `scratch` is refused.
- `mongodb+srv://` is refused as the hosted-cluster scheme; any host matching
  `mongodb.net` is refused.
- After connecting, `client.nodes` is re-checked — what DNS, an SRV record or a
  hosts file **actually** resolved to, not what the URI asked for.

### The one real guarantee: a read-only credential

The validator runs `connectionStatus` and refuses unless every role held by the
connection is in `{read, readAnyDatabase, clusterMonitor}`. An unfamiliar or
custom role fails closed.

This is the only check here that is evidence rather than convention. A
credential with no write role cannot write — whatever this script does, whatever
a future edit to it does, and whatever the operator typed. Create the user on
the validation host with `read` on the restored database and nothing else.

Two escape hatches, both narrow:

- **`--allow-unauthenticated`** accepts a target with no auth at all. It is a
  degraded mode, so the run cannot pass.
- **`--allow-host`** accepts one non-local host. Exactly one value, no
  wildcards, no comma lists, not a host that is already local, not any
  hosted-cluster host. It does **not** relax the credential requirement, and
  combining it with `--allow-unauthenticated` is refused outright.

### Stability is not a zero-write proof

Collection contents are fingerprinted before and after the scan
(`canonical_content_fingerprint`), or counted only under `--no-fingerprint`
(`count_stability`). The report carries this, and no longer contains the words
"zero writes":

> This detects a change made between the two reads. It is NOT a proof that this
> process performed no writes: a write followed by a compensating write, or a
> write outside the fingerprinted collections, would not show here. The evidence
> for no writes is the read-only credential recorded under `target.credential`.

The script also contains no database write API — a property of the file, not of
the process, which is why it is stated after the credential rather than instead
of it:

```
grep -nE "insert|update_|replace_|delete_|drop|create_index|bulk_write|find_one_and" \
     backend/scripts/validate_v2_snapshot.py
```

It returns three lines, none a driver call — two from the module docstring and
`sys.path.insert` for the repo import. Read them rather than trusting the exit
code. The script's only local writes are the report file and the source PDFs it
reads; omit `--report` and it writes nothing.

### The production flag is not claimed

The report used to carry `documents_v2_enabled: false`, hardcoded. The
validation host cannot observe production's configuration, so the field is gone
rather than asserted. Confirm the flag on the production host itself.

---

## Errors are controlled and redacted

Connection, collection-listing, fingerprint, artifact-scan and report failures
are caught and turned into an exit code plus an **exception class name**. Never
the message: driver errors embed URIs and hostnames, filesystem errors embed
paths that carry document titles.

```
ERROR: artifacts stage failed (ServerSelectionTimeoutError). Details are
withheld: driver errors embed URIs and hostnames, and filesystem errors embed
paths that carry document titles.
```

The report-write failure and the missing-artifact-root refusal withhold their
paths for the same reason. The client is closed on every exit path, including
refusals and errors.

---

## What it checks

### The capture manifest

Fully validated before anything connects — see
[`capture-manifest.md`](./capture-manifest.md). Beyond the earlier contract:

- **`database_fingerprint` must name exactly `documents` and
  `document_revisions`.** Missing one is refused; an extra one is refused too,
  because a digest that is recorded and never compared reads as coverage the run
  does not have. Digests must be 64-hex (case-normalised); `null`, booleans,
  numbers, wrong lengths and non-hex characters are all refused, as are two
  collection names that are equivalent after normalisation.
- **`path_token` is required and checked.** `absent_path` must carry `null`;
  every other state must carry a 16-hex token. **The token is then compared with
  the restored row's own `file_path`, and a mismatch is a fatal
  `file_path_mismatch`** — checked *before* the hash, because a hash verified
  against the wrong path proves nothing. Tests cover swapping hashes between
  documents and swapping path tokens between paths; both are caught.
- **Timestamps are parsed, not merely present.** ISO-8601, timezone-aware, UTC.
  Naive values, non-UTC offsets, malformed strings and reversed intervals are
  refused. A **zero-length quiesce window** is refused — quiescing, dumping and
  resuming takes time, so zero means the timestamps were stamped rather than
  measured. A zero-length *atomic* snapshot is accepted, because that is what
  atomic means.

### Collections and counts

`documents` and `document_revisions` must exist — absence is fatal. `cases` and
`users` are reported as warnings. `--expect-documents N` is **refused** if it
contradicts the manifest's `document_count` rather than silently preferring one.

### Fidelity, per document

Full state-by-state table in [`capture-manifest.md`](./capture-manifest.md).
Fatal: `file_path_mismatch`, `source_lost_in_restore`,
`source_content_mismatch`, `source_size_mismatch`, `weak_match`,
`source_appeared_after_restore`, `file_path_lost`, `file_path_appeared`,
`omitted_document`, `unexpected_document`, `document_count_mismatch`,
`fingerprint_mismatch`.

### Migration data issues

`source_missing_in_production`, `source_unreadable_in_production`,
`duplicate_legacy_path`, `stored_path_traversal`. Counted, grouped by code, and
listed. They shape the policy decisions; they never fail the run — except
`source_unreadable_in_production`, which is *also* an unassessable entry and
does block approval, for the reason given at the top.

`duplicate_content` (identical bytes at different paths) is informational.

---

## Privacy of the report

Every per-document entry carries a 16-character `path_token`
(`sha256(file_path)[:16]`), never the path — paths embed user-chosen document
titles. `--include-paths` opts in when an operator needs to go and look.

No client ids, titles, emails or connection strings appear anywhere in the
report. A test asserts that a URI containing a password leaks into neither
stdout, stderr, nor the report — and it runs against a *failing* document,
because a clean run produces no per-document entries and would pass the test
without the redaction ever executing.

---

## Test coverage of the tool itself

Synthetic fixtures only — no Mongo, no network, no production, no provider. The
database is a hand-built fake; the CLI tests drive `main()` with an injected
fake `MongoClient`. Run them from `backend/`:

```
cd backend && venv/Scripts/python.exe -m pytest tests/test_validate_v2_snapshot.py
```

From the repository root they error in `conftest.py` at `Settings()` — the
existing suite-wide `.env` requirement, not a fault in these tests.

Every hardened behaviour is covered by a revert: the behaviour is undone in the
source, and the suite must fail. Counts and the per-mutation results are in the
handover notes for this change.

---

## Known limitations

1. **Never run against real data.** Every guarantee above is a property of the
   code and its synthetic tests. The first real run may surface scale or
   deployment problems none of this predicts.
2. **The capture side is implemented but has never been run.** See
   [`capture-manifest.md`](./capture-manifest.md). Every guarantee it offers is
   a property of its synthetic tests, and it cannot prove application
   quiescence -- only that nothing moved while it looked.
3. **`unreadable_source` can never be resolved by this tool**, only reported. If
   production holds even one such document, no validation run can reach
   `snapshot_approval_ready: true` until that document is made readable at a fresh
   capture, or the owner accepts it as a known, itemised exception. There is
   currently **no mechanism for recording that acceptance**, which means a
   single unreadable file blocks approval outright.
4. **Artifact observations are held in memory** — one entry per document, plus
   the whole manifest. Fine at this estate's size; it would need streaming at a
   much larger one.
5. **Fingerprinting reads whole collections twice**, and the artifact scan reads
   every file. On a large restore or slow storage this is the dominant cost, and
   the only lever is `--no-fingerprint`, which cannot produce an approval.
6. **`weak_match` is fatal**, which may be too strict for a restore that
   deliberately flattens the directory structure. It is fatal because a basename
   match is not evidence that the right file met the right row; if that proves
   impractical, the fix is a better path mapping, not a softer verdict.
7. **Role checking assumes standard role names.** A custom role granting writes
   under an unfamiliar name fails closed, which is correct — but a legitimately
   read-only custom role is refused too.
8. **`path_token` is a 16-hex prefix of a SHA-256**, chosen to keep titles out
   of the report. It is a redaction, not a collision-resistant identifier; two
   paths could in principle share one. Nothing in the estate's size makes that
   likely, and a collision would produce a false pass on one document.
9. **The stability check runs inside one process.** A concurrent writer on the
   validation host would be detected only if it changed the fingerprinted
   collections between the two reads.
