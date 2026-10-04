# Analyzer processing receipt — design (`receipt.1`)

Slice 3 of ANALYZER_HYPOTHESES_PLAN.md ("processing receipt + audit"). It
builds on what each run already records: the sentence ids sent, hashes, the
masking version and policy hash. Nothing here enables real documents. The
synthetic-only gate and `not_passed` are unchanged.

## What it answers

For one analysis run, a reviewer (the owner lawyer) can see:

1. Which document version was processed: the text hash, whether the document
   was attested synthetic, and the attestation version.
2. Which local steps ran, with their versions: extraction/OCR, segmentation,
   the injection scan, and the scanner (catalogue hash, scanner version).
3. **Every time anything left the server for an AI provider:**
   - when;
   - which provider, pinned model, policy id and ZDR status;
   - prompt and schema version;
   - masking version, policy hash and counts by kind;
   - the sentence ids sent (and which were withheld as flagged);
   - the SHA-256 of the exact request messages;
   - the provider's request id and token usage;
   - the outcome (complete / partial / failed with code).
4. **Every time the analyzer decided NOT to send,** and why:
   `pii_confirmation_required`, `not_synthetic` / `synthetic_only_refused`,
   AI layer off or not ready, text integrity, injection scan missing,
   nothing to review.
5. Whether the receipt is intact: entries are hash-chained, and the chain is
   re-verified on every read.

It carries NO document text, NO masked or unmasked values and NO model
output. It holds only ids, hashes, versions, codes and counts.

## Storage and reliability

- New collection `analysis_processing_receipts`, APPEND-ONLY (never updated).
  Unique indexes:
  - `(run_id, stage, fence, kind)`: one attempt, one outcome or one
    not-sent entry per stage attempt;
  - `(run_id, seq)`.
  - It is purged with the source.
- **Attempt before sending (owner's correction).** A provider call is
  preceded by its OWN transaction. That transaction proves the source is
  live and the lease is still ours, records the encrypted PII map, and
  appends an `ai_attempt` entry: request digest, ids, provider and model,
  policy and masking. Only then is the request sent. If that transaction
  fails, nothing is sent.
- **Outcome after.** The `ai_outcome` entry (status, error code, request id,
  usage) is appended in the transaction that publishes the result, and the
  PII map's record is deleted in that same transaction.
- **A crash or lost lease between the two** leaves an attempt with no
  outcome. The reader shows it as `delivery_or_outcome_unknown`, "Delivery/
  outcome unknown", or `in_progress` while the same fence still holds a live
  lease. It never shows "nothing sent".
- **Hash chain and pinned head.** `entry_sha256 = sha256(prev + canonical
  entry)`. Every append also sets `run.receipt_head = {count, last_sha256}`
  in the same transaction. The reader verifies the chain AND compares it with
  the head. Deleting the LAST entry leaves a shorter chain that is still
  internally consistent, so the head is what detects it (`head_mismatch`).
- A decision not to send is a single `not_sent` entry, written with the
  published outcome.

## Retention (synthetic demo policy, owner's decision 2026-10-04)

| Layer | Retention |
|---|---|
| Original file, canonical text, scanner results | 7 days from source creation (`expires_at`) |
| AI items/signals, reviewer decisions, receipt | until the same source expiry |
| Encrypted PII map | deleted when its attempt finishes; a crashed attempt's map within 24 hours (`sweep_stale_maps`, housekeeping) |

- The 7-day expiry purges the WHOLE source through the existing deletion
  outbox (`expire_due` → `purge_source`).
- Immediate delete (`DELETE /documents/analyses/{source_id}`) stays.
- The receipt is NOT retained after the document is deleted.
- Saved reports and evidence never need the map: evidence is cut from the
  original text by offset, and model text keeps its tokens (tested).
- The review-request module's own 30-day retention is unchanged.
- A real-client retention policy will be decided separately.

## Reading it

`GET /documents/analyses/runs/{run_id}/processing-receipt`, registered
lawyer, owner only, the same gates as the other run routes. It returns:

- the run header, built at read time from the run and source: engine,
  attestation, text hash, local step versions;
- `entries` in `seq` order;
- `chain: {intact, entries}`.

A broken chain answers `intact: false`; it never hides entries. There is no
client route, and no UI in this slice beyond the API (a later screen can
render it).

## Open issue — one unexplained test failure (UNRESOLVED, 2026-10-04)

- `tests/test_analyzer_receipts.py::test_an_attempt_is_durable_before_the_request_and_the_outcome_follows`
  failed ONCE, in a receipts-only run made right after a full analyzer
  suite on the dev replica set (27018).
- The output of that run was not saved: only the summary line was kept.
  The assertion and the traceback are therefore unknown.
- These runs all passed:
  - 8 isolated runs of the test;
  - 6 runs of receipts plus confirmation tests;
  - a targeted diagnostic run (`-vv --tb=long -l -rA`, log kept in the
    session scratchpad).
- Ruled out: millisecond rounding of the chain timestamp (BSON truncation
  matches the hash's isoformat).
- Status: UNRESOLVED. The durable-attempt guarantee is not claimed as
  clean-gated until the failure is captured or explained. Every future run
  of these tests keeps its full log.

### Investigation (2026-10-04, later)

**Demonstrated failure mode (deterministic reproduction).** The test's final
privacy check searched the receipt JSON for digit fragments ("0300",
"35202"). The receipt carries long hex strings: entry hashes (which include
timestamps, so they change every run), request and policy hashes, and ids.
A fragment occurs in random hex roughly once in 16⁴ positions. With one
entry hash forced to begin with "0300", the unchanged test fails with
exactly `AssertionError: 0300`, and the match is inside a SHA-256, not
personal data. Per run this is roughly a 0.5–1% event; the policy hash also
changes with every code edit, which can flip it for a whole code version.

**Fix (tests only).** `tests/_analyzer_support.without_hex` removes uuids
and hex tokens of 16 or more characters before a fragment search. A real
leaked number is shorter, or carries separators, and is still caught
(`test_a_hash_that_happens_to_contain_digits_is_not_a_leak`). Three other
tests that made the same check were corrected too.

**Status.** The original failure's output was never saved, so this cannot
be PROVEN to be its cause. It is a demonstrated mechanism that produces
exactly that test failing intermittently with no product fault, and it is
removed.

The receipt's own behaviour was re-checked and held:
- the attempt is durable before the request;
- the outcome is committed with the run;
- a lost lease reads "outcome unknown";
- a crash INSIDE the provider call reads "in progress", then "outcome
  unknown", never "nothing sent"
  (`test_an_unexpected_error_inside_the_provider_call_reads_outcome_unknown`);
- the hash chain stays intact.

If the test ever fails again for another reason, keep the full traceback.

**A second, more frequent mechanism (found when the broad suite failed again).**
Stored timestamps are cut to milliseconds, so their fraction always ends in
"000". Any millisecond value of the form x03 therefore gives ".x03000",
which contains "0300": about 1% per timestamp, and a receipt holds several.

- **Deterministic reproduction:** with the receipt clock pinned to
  `.503000`, the ORIGINAL check fails at the original test's privacy
  assertion with `AssertionError: 0300`, and nothing is leaked.
- **Fix:** the helper (now `without_ids`) also removes ISO timestamps
  (`test_a_timestamp_that_happens_to_contain_digits_is_not_a_leak`).

Both mechanisms produce exactly the observed symptom, and nothing in the
product needed to change. The unsaved original run still cannot be
attributed with certainty.
