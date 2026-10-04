# Local entity detector for PII masking — shortlist (L3 of `pii-mask.2`)

Status: SHORTLIST ONLY, documented 2026-10-04.
- Nothing has been downloaded, installed, run or selected.
- No model is approved.
- CPU latency and detection quality can only be measured after an approved
  download.

The owner's preference: assess `gliner_multi-v2.1` FIRST, as a locator for
names and places only. CNIC, phone and account numbers stay with the
deterministic detectors, whichever model is chosen.

All facts below come from the official Hugging Face metadata and model
cards. That is: the Hub API (`/api/models/<id>?blobs=true`), each repo's
`gliner_config.json` at the pinned revision, and the `gliner` package on
PyPI. Read 2026-10-04; no weights were fetched.

## The two candidates

| | `urchade/gliner_multi-v2.1` | `knowledgator/gliner-pii-large-v1.0` |
|---|---|---|
| Pinned revision | `443d26d654e0324125a96bebd8e796c14ff2efe6` (last modified 2025-12-08) | `f847f54fbc97ad6e78bfa20ed9c5e5d5c43327b9` (last modified 2026-05-07) |
| Licence | Apache-2.0 (card + tags) | Apache-2.0 (card + tags) |
| Gated | no | no |
| Hub language tag | `multilingual` | **`en`** |
| Base encoder (`gliner_config.json`) | `microsoft/mdeberta-v3-base` (multilingual, MIT, revision `a0484667b22365f84929a935b5e50a51f71f159d`) | `microsoft/deberta-v3-large` (English) |
| Parameters (card) | 209M | not stated (a DeBERTa-v3-large backbone) |
| Max input | 384 tokens; span width ≤ 12 words; ≤ 25 entity types per call | 768 tokens; span width ≤ 100; ≤ 30 types; whitespace word splitter |
| Files in the repo | `model.safetensors` 1155.8 MB **and** `pytorch_model.bin` 1155.9 MB (the same weights twice; total 2311.7 MB) | `pytorch_model.bin` 1761.0 MB; `onnx/model.onnx` 1763.4 MB; `onnx/model_quint8.onnx` 647.9 MB; `tokenizer.json` 8.6 MB (total 4181.0 MB) |
| **Download actually needed** | `model.safetensors` 1155.8 MB + config, and the base tokenizer from `microsoft/mdeberta-v3-base` (`spm.model` 4.31 MB + configs; this repo ships no tokenizer) → **≈ 1.16 GB** | the PyTorch path: `pytorch_model.bin` + `tokenizer.json` → **≈ 1.77 GB**; or the quantized ONNX path: `model_quint8.onnx` + `tokenizer.json` → **≈ 0.66 GB** |
| RAM (estimate, to be measured) | fp32 weights ≈ 0.85–1.2 GB; ≈ 1.5–2 GB process | fp32 ≈ 1.8 GB weights, ≈ 3–4 GB process; quint8 ONNX ≈ 1–1.5 GB |
| Entity types | open, label-prompted ("person", "location", "address", ...) | 60+ PII labels: `name`, `first name`, `last name`, `location address`, `location city`, `phone number`, `account number`, ... |
| Reported quality | no benchmark on the card | F1 83.25 / P 87.42 / R 79.4 on `synthetic-multi-pii-ner-v1` (the card's own synthetic set) |
| Urdu / South Asian | **not mentioned**; the card shows English only. The mDeBERTa base was pre-trained on a corpus that includes Urdu, but that does NOT show usable Urdu name detection | **not mentioned**; English backbone and `en` tag. Urdu support is unlikely and undemonstrated |
| Stated limitations | not stated | not stated |

Notes:
- The knowledgator card's summary quotes ONNX sizes of 330 MB (FP16) and
  197 MB (UINT8). Those do not match this repository's files (1763.4 MB and
  647.9 MB). The repository's file sizes are used above; the card text may
  describe a different model of the family.
- The owner's earlier note said "multilingual tag" for the PII model. The
  Hub API lists only `en` for it.

## Dependencies (both run through the `gliner` package)

- `gliner` 0.2.29 (PyPI, Apache-2.0). It requires:
  - `torch>=2.0.0` — installed 2.11.0 CPU;
  - `transformers>=4.51.3,<5.17.0` — installed 4.57.6;
  - `huggingface_hub>=0.21.4` — installed 0.36.2;
  - `safetensors` — installed 0.7.0;
  - `numpy`, `packaging`, `tqdm`;
  - **`sentencepiece` — NOT installed** (needed by the mDeBERTa tokenizer).
- Optional:
  - the `onnx` extra → `onnxruntime` (installed 1.19.2), for the quantized
    knowledgator path;
  - `tokenizers` / `stanza` extras: not needed.
- New installs required: `gliner` and `sentencepiece`, both pinned in
  `requirements.txt`.
- The model weights are pinned by REVISION and by file SHA-256. They are
  stored locally and loaded offline (`HF_HUB_OFFLINE=1` at run time). The
  model id, revision and weights hash enter the masking policy hash.

## How it would be assessed (after an approved download)

On `pii-eval-1`, which becomes a DEVELOPMENT set from the first tuning
change; its failed baseline is kept at 7424f38:

1. Per-entity recall, as a NAME/ADDRESS locator, for:
   - Pakistani names, Roman Urdu and Urdu script;
   - OCR-damaged names;
   - names in tables;
   - untitled names;
   - addresses.
2. Look-alike false positives: companies, shops, places, roles.
3. CPU latency per document and peak RAM on this machine (no GPU), against
   a budget. The ai-report path sends whole documents of up to about 200k
   characters, chunked to the 384- or 768-token window.
4. Urdu script: if detection is not demonstrated, Urdu-script text stays
   BLOCKED (L0). That holds whatever the model card says.

Then the layered masker (`pii-mask.2`) is judged once, on a fresh
independent `pii-eval-2`. A pass there is still not a real-document
approval.
