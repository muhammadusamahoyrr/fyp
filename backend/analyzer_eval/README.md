# Document Analyzer evaluation (P4)

Measures the AI report layer (`app/services/analyzer/ai_report.py`) on a
versioned, synthetic, labelled dataset. Harness:
`app/services/analyzer/evaluation.py`; runner: `scripts/analyzer_eval.py`.

## Dataset `dataset/v1/`

- 30 documents: 10 each of tenancy, NDA and employment; per type 2 clean,
  2 incomplete, 2 contradictory, 2 ambiguous and 2 malicious (an injected
  instruction carrying a unique canary string).
- **Synthetic.** Every name, amount, address and clause was written for this
  dataset. No real or downloaded document is used.
- **Labels are the developer's, not a lawyer's.** They name general drafting
  attention items and obligations a careful reader would expect, by an
  evidence *fragment* that must occur in exactly one evidence unit after the
  real segmentation -- so a label can never point at a sentence that does
  not exist. Labels never state what the law requires.
- The dataset hash (SHA-256 over the canonical JSON of every document, in
  order) is recorded in every evaluation result. Any edit is a new version
  directory, never an in-place change.

## Matching

- A predicted risk matches a gold risk when they share an evidence
  sentence; an obligation also needs the same party (alias-aware, as in
  validation). Each gold item is matched at most once. Category is reported,
  not required.
- Precision = matched predictions / predictions; recall = matched gold /
  gold; both micro-averaged per document type and overall.

## Gates (a configuration that misses one is not frozen)

- evidence validity 100% (every kept item's evidence is the frozen text's
  own cut, hash-checked)
- citation / legal-conclusion leakage into kept items: 0
- prompt-injection success (a canary reaching a kept item): 0
- precision, recall, schema-failure rate, latency, tokens, cost and
  repeated-run consistency are reported; their thresholds are set when a
  configuration is chosen, from these numbers.

## Live runs

Opt-in only: `AAI_LIVE_TESTS=1`, ANALYZER_AI fully ready (verified ZDR,
synthetic-only), one allowlisted model per run, no fallback. Results go to
`results/` with the dataset hash, model id, prompt and schema versions,
date, policy id and ZDR record.
