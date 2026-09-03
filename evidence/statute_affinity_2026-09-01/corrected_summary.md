# Named-statute affinity — corrected acceptance evidence

Generated 2026-09-01T22:31:36 · verdict **ACCEPTED**

## Provenance

The original raw data was **not rerun and not altered**. Only two *derived*
booleans in the original summary were wrong; every underlying measurement is
valid and is reused unchanged.

| file | sha256 | status |
|---|---|---|
| `trials.json` | `ec0b300cb3387bb81614e98cbc1fb20c06b42b2b95b012150e14c484a382d6ba` | UNMODIFIED — preserved exactly as produced by the acceptance run |
| `verify_field_fix.json` | `bdb72375cff28c9c34f0e8ab7b618f3cbf0c2dffb0efe110b97af7ce5b901b72` | supporting, post-fix single trial |

Measured trials **10** of 10 attempts, 0 provider failures.

## The measurement bug

- Harness read **`section_number`**; evidence items expose **`section`**
- Buggy predicate: `scripts/eval_statute_affinity.py :: one_trial() -> ppc379_in_evidence`
- Emitted by: `app/ai/answer_citations.py :: build_generation_evidence()`
- Effect: ppc379_in_evidence was False for all 10 trials; the derived 'accepted' flag was therefore False for all 10. Both are WRONG.
- Detected because: The same run reported rank_generation_evidence present in 10/10 and ppc379_in_evidence in 0/10. Two measurements of one fact disagreed; the chunk_id-based rank was correct.

Independent confirmations that PPC 379 *was* in generation evidence:

- rank_generation_evidence (chunk_id match) present in 10/10 trials, rank 1-6
- ppc379_matched True in 10/10 — citation status 'matched' resolves only against chunks present in that answer's generation evidence
- one-trial rerun with the corrected field reported 1/1

**Raw data affected: False.** Only the two derived booleans were wrong. Every underlying measurement in trials.json is valid and is reused unchanged here.

## Corrected results

| metric | result |
|---|---|
| rank_generation_evidence present | **10/10** |
| PPC 379 matched citation | **10/10** |
| punishment stated correctly | **10/10** |
| &nbsp;&nbsp;element `imprisonment` | 10/10 |
| &nbsp;&nbsp;element `three_years` | 10/10 |
| &nbsp;&nbsp;element `fine` | 10/10 |
| &nbsp;&nbsp;element `or_both` | 10/10 |
| PPC 382 cited | **0/10** |
| **fully accepted (corrected)** | **10/10** |
| top-8 inclusion, pre-affinity | 5/10 |
| top-8 inclusion, post-affinity | 10/10 |

- PPC 379 rank, pre-affinity: min 1 / median 10 / max 24
- PPC 379 rank, post-affinity: min 1 / median 1 / max 6
- PPC 379 rank, generation evidence: min 1 / median 1 / max 6

## Acceptance

| criterion | result |
|---|---|
| PPC 379 reaches generation evidence | 10/10 (required >= 9/10) |
| punishment stated in full | 10/10 |
| PPC 379 matched against evidence | 10/10 |
| PPC 382 absent | 10/10 |
| multi-statute control (`named` must be None) | `None` |

## Supporting evidence — post-fix verification

Single trial run AFTER the field-name correction, confirming the corrected predicate reports presence.

| field | value |
|---|---|
| `measured` | True |
| `rank_pre_affinity` | 20 |
| `rank_post_affinity` | 3 |
| `rank_generation_evidence` | 3 |
| `ppc379_in_evidence_corrected_field` | True |
| `ppc379_matched` | True |
| `states_punishment` | True |
| `cites_382` | False |
| `accepted` | True |

## Per-trial (original buggy vs corrected)

| trial | pre | post | graded | evid | in_evid (buggy) | in_evid (corrected) | matched | punish | 382 | accepted (buggy) | accepted (corrected) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 20 | 6 | 6 | 6 | False | True | True | True | False | False | True |
| 2 | 1 | 1 | 1 | 1 | False | True | True | True | False | False | True |
| 3 | 1 | 1 | 1 | 1 | False | True | True | True | False | False | True |
| 4 | 1 | 1 | 1 | 1 | False | True | True | True | False | False | True |
| 5 | 24 | 6 | 6 | 6 | False | True | True | True | False | False | True |
| 6 | 1 | 1 | 1 | 1 | False | True | True | True | False | False | True |
| 7 | 19 | 3 | 3 | 3 | False | True | True | True | False | False | True |
| 8 | 19 | 1 | 1 | 1 | False | True | True | True | False | False | True |
| 9 | 1 | 1 | 1 | 1 | False | True | True | True | False | False | True |
| 10 | 20 | 3 | 3 | 3 | False | True | True | True | False | False | True |
