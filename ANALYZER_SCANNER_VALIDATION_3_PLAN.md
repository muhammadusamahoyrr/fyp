# Drafting-question scanner: plan for a fresh independent validation (validation-3)

Status: **PLAN ONLY — not authored, not frozen, not scored** (2026-10-05).

The scanner's gate record is still `not_passed`: validation-2 (db59fd1, 2026-10-04), with
precision 0.861, recall 0.941, and 16 weak questions. That record and its dataset stay
exactly as they are. The later regex fixes do not change that score:

- `6b79e73`: the backspace byte in `undefined_terms`;
- the development fixes below: `notice` read as a street number, rent judged per
  sentence part, a letting "to Mr. X at Rs.", and two confidential-information
  definition forms.

Only a fresh, independent, frozen-before-scoring set can show whether the scanner now
meets the gate.

## Why not yet

The development data still shows two weak questions:

- `conflicting_values`: recall 0.78 on validation-1;
- `undefined_terms`: precision 0.60, recall 0.67 on validation-1.

Several development labels also disagree with the catalogue's own `ambiguous_when`
wording:

- `premises_description`: "his flat in Clifton, Karachi" is labelled ambiguous, but the
  catalogue counts a location as identifying;
- `undefined_terms`: "the Effective Date" and "the Purpose" are not flagged while
  similar terms are.

A qualified lawyer should settle those label questions before a gate set is written to
the same rubric (see "Human decisions" below). Scoring a new gate set now would mostly
measure rubric ambiguity.

## Conditions before authoring

1. A qualified lawyer has reviewed `LABELLING_RUBRIC.v2.md` (sha256 `d36d8b54…f6aaf70341`)
   and the catalogue (`drafting-hypotheses.v1`, sha256 `8594d27a…8690b4`). The two must
   be consistent on the questions above.
   - If either changes, it gets a new version and hash, and those are pinned instead.
   - A coding agent does not make that approval.
2. The scanner code is committed and unchanged since the last development measurement.
   Its hash at this plan is `b9a80445be31761a7543411c1140e1dfcc18253369ecf4df281d7255c8393e96`
   (`evaluation.scanner_code_sha256()`); the freeze records the hash at freeze time.

## Authoring

- A fresh author session gets ONLY the approved labelling rubric and the catalogue
  questions for tenancy, employment and NDA documents.
  - It is not told about validation-1/2, the scanner, or the weak questions.
- At least 8 gold attention AND 8 non-attention examples per question
  (`VALIDATION_MIN_EXAMPLES`).
- Synthetic only.
- The author's reads and limits are recorded in `AUTHORED.txt`, as for the PII gate sets.

## Frozen thresholds (unchanged from the validation-2 record; not tuned)

| Check | Threshold |
|---|---|
| attention precision (overall) | ≥ 0.80 |
| attention recall (overall) | ≥ 0.85 |
| evidence validity | 1.0 |
| injection success | 0 |
| leakage | 0 |
| weak questions | none (per question, the same precision/recall floors, support ≥ 3) |
| coverage | ≥ 8 attention and ≥ 8 non-attention examples per question |

## Procedure

1. Freeze before any scoring: `FROZEN.txt` records the dataset, rubric, catalogue and
   scanner code hashes, plus the commit.
2. Score EXACTLY ONCE, scanner-only and offline: `scripts/analyzer_hypothesis_eval.py
   --dataset validation-3 --write-record --baseline`. No AI signal can change a scanner
   status.
3. Commit the freeze and the kept record whatever the outcome.
   - If it fails: record `not_passed` and stop the cycle. Do not read the set for tuning
     and do not generate another set.
4. A pass is `engineering_passed` at most. It is NOT production approval: that also needs
   lawyer-reviewed labels and the sealed holdout.

## Invariants that stay in force

- "Not located automatically" is neutral, not a legal conclusion.
- Incomplete or OCR-uncertain text gives "Could not check".
- Every finding keeps its exact sentence and clause evidence.
- The review screen stays `internal_review_only` until a gate passes.
