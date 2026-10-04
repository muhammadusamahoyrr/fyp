# Correction note — the 2026-10-04 locator benchmark (71 leaks)

The original record in `DEV_BENCHMARK_gliner_multi-v2.1.md` (commit
219ffe6) stays **unchanged**. This note records two harness defects found
afterwards and what they changed for that exact setup.

## The defects (pii-eval.1 harness)

1. **Locator spans passed as reviewer confirmations.** `score_document`
   handed the locator's spans to `pii_mask.prepare` as `confirmed`
   decisions. So, besides masking, they resolved any uncertainty they
   overlapped, as if a lawyer had approved it. A locator is a detector, not
   a reviewer.
2. **Party consistency scored on blocked documents.** The rubric scores it
   only "in what is sent".

Both are fixed in harness `pii-eval.1.1`.

## Re-measured: the same setup with the corrected harness

- Setup: masker `pii-mask.1` from 219ffe6, plus gliner_multi-v2.1
  (as_loaded tokenizer) at cut-off 0.3, mapping person+address+location.
- Inputs: the same saved locator output, and the same pii-eval-1 (sha256
  `2cdd9ecb…`).
- Run in a throwaway worktree of 219ffe6. The only patch passed locator
  spans as detections and scored party consistency on sent documents.
- Patched policy hash: `ad659965…`. It was not committed and not kept.

| Auto mode | Recorded (pii-eval.1) | Corrected |
|---|---|---|
| Sent / blocked | 46 / 2 | **46 / 2** (unchanged) |
| Leaks | 71 | **71** (unchanged) |
| Party consistency | 0.3125 (over 48 documents) | **0.326** (over the 46 sent) |

| Manual mode | Recorded | Corrected |
|---|---|---|
| Sent / blocked | 48 / 0 | 48 / 0 |
| Leaks | 75 | 75 |
| Party consistency | 0.3125 | 0.3125 |

**Effect: none on the blocked count or leaks of this setup.** pii-mask.1's
uncertainty candidates did not overlap the locator spans in a way that
changed any document's outcome. The defect does matter for pii-mask.2,
whose alias, OCR and Urdu checks sit exactly where the locator finds
names. The conclusion "model not selected, 71 leaks" stands.
