# Estate survey — the counts that dissolved two blockers

**Executed 2026-09-06 against production, read-only.** One connection, no writes,
no migration, no index change. `DOCUMENTS_V2` remained `False` throughout.

Tool: [`backend/scripts/v2_estate_survey.py`](../../backend/scripts/v2_estate_survey.py)
· Tests: [`backend/tests/test_v2_estate_survey.py`](../../backend/tests/test_v2_estate_survey.py) — 32 passing
· Raw output: `estate-survey.json`

Credential: a dedicated Atlas user `v2_survey` holding exactly `read` on
`attorney_ai` and nothing else. Verified by the tool before it read anything.
The connection string was supplied through an environment variable, never on the
command line. **That credential's password was disclosed in a chat transcript
and should be rotated or the user deleted.**

---

## Results

| | |
|---|---|
| Legacy documents (`schema_version != 2`) | **19** |
| V2 documents (excluded from every count) | 0 |
| `document_revisions` | **0 — empty** |
| Review status | 17 `None` (drafts), 2 `submitted` |
| Source states | **19 readable**, 0 missing, 0 unreadable, 0 absent path |
| Path flags (traversal, symlink, escape) | none |
| **Blocked documents** | **0** |
| Blocking condition occurrences | none |
| Outcomes | 17 `draft_with_file`, 2 `submitted_reviewable` |
| **Requires owner approval** | **0 documents** |

---

## Blocker 6 — the four policy decisions: **dissolved**

Zero documents fall into any of the four outcomes that require owner approval:

| Outcome | Affected documents |
|---|:--:|
| `submitted_no_file` | **0** |
| `submitted_no_reviewer` | **0** |
| `approved_no_file` | **0** |
| `approved_no_reviewer` | **0** |

Every document is either a draft that has its file, or a submitted document that
is properly reviewable. **There is nothing to approve**, no status will be
relabelled, no approval will be withdrawn, and no client needs notifying. The
decision table in the README describes behaviour that will not be exercised.

The consequence I flagged as the sharpest downside — *"a client who believed
they had an approved document will be told they do not"* — cannot occur. There
are no approved documents in the estate at all.

## Blocker 7 — blocked records: **zero**

No missing `client_id`, no missing `template_type`, no unreadable source, no
unsupported legacy status, no planned-revision-id collisions, no duplicate
planned ids. Every one of the 19 documents is plannable.

This also settles the design risk I raised: `unreadable_source` would have made
`snapshot_approval_ready: true` unreachable with no mechanism for recording an
owner's acceptance. **There are no unreadable sources**, so the deadlock does
not arise.

---

## A correction I owe the record

I previously reported the estate as **"~13,000 documents"**, inferred from a
filesystem census of `UPLOAD_ROOT/docs`. **It is 19.**

| | |
|---|---|
| PDFs on disk | 13,386 |
| PDFs referenced by a document row | **19** |
| Referenced and present | 19 |
| Referenced but missing | **0** |
| **Orphans on disk** | **13,367** |

Every referenced file is present. The other 13,367 are almost certainly
accumulated development and test output — 28.3 MiB of it — that no row points at.

This is precisely the error the survey's own documentation now warns about: a
directory listing describes what is **on disk**, while the migration reads paths
**recorded in rows**. The two sets can differ by three orders of magnitude, and
here they do. I stated the census figure as the estate size in the same stretch
of work in which I corrected the documentation against doing exactly that.

---

## What this means for the plan

**The tooling built for this migration is disproportionate to the job.**

The capture manifest, two-pass artifact verification, snapshot fidelity
comparison and crash-consistent publication exist to make a large, uncertain
estate safe to migrate. This estate is 19 documents, ~40 KB of referenced PDFs,
zero blocked records and zero decisions to make.

That tooling is not wasted — it is correct, tested, and would be the right
answer for a real estate — but running the full capture / restore / validate /
dry-run sequence for 19 documents would be ceremony, not diligence. At this size
the strongest possible verification is also the simplest: **read all 19 rows
before and after and compare them directly.**

### Proposed reduced sequence

1. **Create the eight missing V2 indexes.** They are absent, not malformed —
   a read-only preflight confirmed it, and duplicate risk for all four
   unique indexes is clear. Independent of everything else, fully
   reversible, near-instant at this size, and the endpoint 404s while the
   flag is off. See [`index-runbook.md`](./index-runbook.md).
2. **Back up.** `mongodump` of `attorney_ai` plus the 19 referenced PDFs —
   seconds, not a maintenance window. A backup is still warranted because the
   migration writes; the elaborate capture-boundary apparatus is not.
3. **Dry-run twice** and compare planning fingerprints. On 19 documents this is
   near-instant, so the determinism check is cheap to do properly.
4. **Apply**, keeping the rollback token.
5. **Verify directly**: read all 19 documents and their revisions and confirm
   each against the pre-migration snapshot. At this size this is stronger
   evidence than any sampling or fingerprint scheme.
6. **Only then** consider the `DOCUMENTS_V2` flag.

### What is deliberately dropped, and what that costs

Skipping the capture manifest and validator means giving up the guarantee that a
restored snapshot is byte-faithful to production. **That guarantee is replaceable
here**, because 19 documents can be verified exhaustively by direct comparison —
which is what the manifest machinery approximates for estates too large to check
by hand. If the estate grows materially before the migration runs, re-run the
survey and reconsider.

### Housekeeping, not blocking

The **13,367 orphan PDFs** are 28.3 MiB of dev output in `uploads/docs/`. They
are not referenced, not migrated, and not dangerous — but they are why a
filesystem census misleads, and worth clearing separately from this work.
