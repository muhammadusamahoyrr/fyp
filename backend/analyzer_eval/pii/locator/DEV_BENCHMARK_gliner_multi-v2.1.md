# DEVELOPMENT benchmark — `urchade/gliner_multi-v2.1` as a PII locator (2026-10-04)

**Not a gate, and not a selection.**

> **Summary: MODEL NOT SELECTED.** Best measured pipeline: **71 leaks** in auto mode (194 for the
> masker alone), **party consistency 0.31**. Not safe for any real document.

- pii-eval-1 is a DEVELOPMENT set from this run on. Its failed baseline (194
  leaks in auto mode, masker alone) stays kept in `pii_detection_record.yaml`
  (7424f38).
- Urdu-script text stays BLOCKED until a FRESH evaluation proves Urdu
  detection.

## Setup

- Model: `urchade/gliner_multi-v2.1` at revision `443d26d6…`, with encoder
  tokenizer `microsoft/mdeberta-v3-base` at `a0484667…`.
- Files: verified against the Hub's published SHA-256 for the weights and
  `spm.model`; the other files are recorded. See
  `gliner_multi-v2.1.manifest.json`.
- The cache is outside Git.
- Isolated venv: `torch==2.11.0+cpu`, `transformers==4.57.6`,
  `gliner==0.2.29`, `sentencepiece==0.2.1`, `protobuf==6.32.1`. The backend
  venv was not touched.
- Fully offline: `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE` set, and every
  socket connection refused in-process.
- The locator received only the PLAIN texts. Marks were stripped, and no
  labels were passed.
- Labels asked: `person`, `address`, `location`, `organization`. Mapping:
  person → NAME, address/location → ADDRESS, organization → kept.
- Chunking:
  - overlapping chunks of 160 words, with 40-word overlap, cut by the
    model's own word splitter;
  - every chunk measured with the model's tokenizer plus the label prompt
    against 512 subwords;
  - gliner's truncation warning made an error (it never fired);
  - every word covered;
  - offsets mapped back to the original text.
- The pipeline is scored by the frozen pii-eval.1 harness. Leaks are
  measured on the request the fake provider actually captured. No live call.

## CPU and memory (this machine, no GPU)

| | |
|---|---|
| Model load | 28.7 s |
| 48 documents, 15,903 characters | 91.6 s total (≈ 63 s of inference) |
| Per document | median 1.13 s, p95 2.28 s, max 3.56 s |
| Peak RAM (locator process) | **2,851 MB** (above the 1.5–2 GB estimate) |

Throughput is ≈ 4 ms per character. A 50,000-character document would take
≈ 3–4 minutes on this CPU (extrapolated, not measured).

## The locator alone (gold NAME / ADDRESS spans; Urdu-script names counted apart)

| Cut-off | Names fully found | Names char coverage | Urdu-script names fully found | Addresses fully found | Look-alikes (NOT) hit |
|---|---|---|---|---|---|
| 0.3 | 138 / 214 | 0.77 | 20 / 28 | 5 / 28 | 20 / 52 |
| 0.5 | 131 / 214 | 0.75 | 17 / 28 | 3 / 28 | 17 / 52 |
| 0.7 | 122 / 214 | 0.70 | 16 / 28 | 0 / 28 | 16 / 52 |

## The pipeline (masker + locator spans), auto mode

| Variant @ cut-off | Sent / blocked | Char coverage | Fully masked | **Leaks** | Names leaked | Party consistency | Deadlines | Manual leaks |
|---|---|---|---|---|---|---|---|---|
| masker alone (kept baseline) | 39 / 9 | 0.36 | 0.28 | **194** | 160 | 0.92 | 1.0 | 233 |
| person+address @0.3 | 44 / 4 | 0.75 | 0.73 | **79** | 51 | 0.31 | 1.0 | 88 |
| person+address+location @0.3 | 46 / 2 | 0.85 | 0.74 | **71** | 54 | 0.31 | 1.0 | 75 |
| person+address @0.5 | 43 / 5 | 0.71 | 0.69 | 92 | 59 | 0.42 | 1.0 | 101 |
| person+address+location @0.5 | 44 / 4 | 0.81 | 0.69 | 83 | 61 | 0.42 | 1.0 | 88 |
| person+address @0.7 | 42 / 6 | 0.68 | 0.65 | 102 | 66 | 0.42 | 1.0 | 114 |
| person+address+location @0.7 | 44 / 4 | 0.77 | 0.65 | 101 | 70 | 0.42 | 1.0 | 107 |

## What this shows

- **A large gain, and still far from safe.** The locator cuts leaks from 194
  to 71–79 at cut-off 0.3. Zero leaks is the requirement, so the locator is
  not enough on its own. The L5 (OCR) and L6 (independent pattern and layout
  leak guard) layers, and the L0 Urdu block, are still needed.
- **Addresses are weak** (5 of 28 fully found). Address chains need the
  deterministic premises/residence patterns, plus layout.
- **Look-alikes:** 20 of 52 company, place and role spans were tagged person
  or address. That masks things that are not personal. It is not a leak, but
  it can hurt meaning.
- **Party consistency fell** (0.92 → 0.31–0.42). The locator masks name
  fragments with their own tokens, and, by the owner's rule, aliases are not
  merged automatically. Linking parties needs explicit definitions or
  reviewer confirmation (L4), so this metric drops until that exists.
- **Urdu-script names:** 20 of 28 were found here. That is encouraging, but
  it is a development set, so Urdu stays blocked until a fresh evaluation.
- **Caveat — tokenizer warning:** `transformers` warned that the
  mDeBERTa tokenizer, as loaded, has "an incorrect regex pattern" and
  suggests `fix_mistral_regex=True`. Tokenization may be affected; this was
  not investigated or changed in this run.
- **CPU cost is real:** 2.85 GB of RAM and seconds per short document. Long
  documents run to minutes.

Raw numbers: `analyzer_eval/pii/results/2026-10-04_pii-eval-1_DEV_gliner_multi-v2.1.json`
(local, git-ignored; regenerated by `scripts/pii_locator/bench_gliner.py`).
