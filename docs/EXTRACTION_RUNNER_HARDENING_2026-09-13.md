# Extraction runner hardening — 2026-09-13

## Implemented contracts

- Shared work is keyed by authenticated owner, ordered file IDs and resolved
  paths, content hashes, extractor/config versions and timeout policy. Equal
  bytes alone do not identify an interchangeable result. Unknown owners disable
  sharing. Intake and document-tool callers pass their owner/file identity.
- Duplicate callers get independent result objects and stale-input checks.
  Cancelling a waiter does not cancel or restart its owner. Cancelling the owner
  cancels the shared future, settles its waiters and removes only its own entry.
- Subprocess creation is tracked even when cancellation arrives before the OS
  handle returns. Timeout/cancellation cleanup kills and reaps the child before
  releasing its capacity slot. Repeated cancellation cannot abandon cleanup.
- Files run sequentially in separate child processes. The 30-second file budget
  includes startup; the 120-second batch budget includes capacity queueing.
  Earlier successful results survive later failures; a timed-out file does not
  prevent later files from running while batch time remains. Exhausted batches
  report timeouts for unstarted files rather than omitting them.
- Extraction `CONFIG_VERSION` is now `2`; OCR evaluation code is unchanged.

## Limits and tradeoffs

Per-file children add startup overhead compared with one process for a batch.
These are extraction deadlines, not hard real-time request SLAs: initial content
hashing, result validation and mandatory kill/reap cleanup add time. OS process
creation must return a handle before cleanup can reap it. Process-tree cleanup
continues to use the existing best-effort psutil helper.

Concurrency (two active children) and deduplication remain per API process, not
host-wide. No shared queue, distributed lock, OCR engine, retention deletion,
historical reprocessing, frontend change or production-data change was added.

## Verification

- Offline affected suites: **104 passed, 82 deselected**, 0 failed/errors
  (61.89 seconds); `.test-tmp/runner-regression.xml`.
- Expanded affected suites with explicitly local MongoDB and enforced `_test`
  database/temporary uploads: **196 passed, 0 failed, 0 errors, 0 skipped**
  (61.10 seconds); `.test-tmp/runner-local-regression.xml`.
- The expanded run covered runner lifecycle/bounds, extraction hardening and
  honesty, evidence coverage, document tools, intake evidence lifecycle and
  Stage 5 case-context privacy tests. Live-provider tests were excluded.
- The new lifecycle file contains **19 cases**, including a real synthetic
  child cancellation/reaping check and deterministic stubbed lifecycle cases.
- In-memory mutations (no source edits): reverting result identity caused four
  regression failures; removing child cleanup caused one. The owner-isolation
  control still passed. `.test-tmp/runner-mutation.xml` records this intentional
  red run separately from the clean runs.
- An initial test fixture omitted required ExtractionResult fields. It was
  corrected, and the corrected tests were rerun green and mutation-checked;
  that initial run is not used as acceptance evidence.
- Subsequent full backend run: **4928 passed, 0 failed, 0 errors, 86 skipped,
  2 xfailed, 0 deselected**, exit 0 (662.92 seconds); JUnit artifact
  `backend/.test-tmp/full-runner-20260913.xml`. JUnit records 5016 cases and
  88 skips, including the two expected failures. The run used `-m "not llm"`,
  explicitly local MongoDB with the `_test` database, temporary uploads, offline
  model settings, and a Python audit hook refusing non-loopback socket connects.
  No live-provider or production access was permitted.
- This full run started at 10:41 and completed at 10:52 on 2026-09-13, before
  the separate dependency and retention commits later that day. SHA-256 checks
  confirmed all six runner implementation/test files and the requirements file
  still matched the tested bytes before preparing this checkpoint. The full run
  does **not** establish regression coverage of the later retention commits;
  their tests are absent from this JUnit artifact.
- Frontend suites and frontend build were not rerun for this backend-only task.
  `git diff --check` passed.

The dependency pins were committed separately by the concurrent session as
`7776704f254cf0948cef533bd9375ab853308e13`; this task preserves that commit and
does not duplicate it. This note accompanies the extraction-runner checkpoint.
No push or production changes are part of this task.
