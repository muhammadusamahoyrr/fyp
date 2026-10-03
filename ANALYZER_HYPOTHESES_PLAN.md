# Analyzer Slice 1 — Fixed drafting hypotheses (plan)

Status: **PLAN, approved in direction; not implemented.** Written 2026-10-03, revised the same day with the
owner's four corrections and three decisions (§11). Owner: Muhammad Usama.
Related: `DOC_ANALYZER_PLAN.md` (the analyzer engine), `backend/app/services/analyzer/ai_evaluation_record.yaml`
(why no model is selected for `ai-report.1`), `DOCUMENT_REVIEW_REQUEST_PLAN.md` §11 (no AI on real client
documents).

## 0. Why

The AI report layer (`ai-report.1`) asks the model an open question ("what are the drafting risks?").
Benchmarked live on 2026-10-03 (gpt-oss-120b, 30 synthetic documents × 3 runs) it is safe but noisy:

| Metric | Result | `ai-report.1` gate |
|---|---|---|
| Risk recall | 0.94 | — |
| **Risk precision** | **0.43** | 0.70 |
| Obligation precision / recall | 0.83 / 0.87 | — |
| Evidence validity, leakage, injection | 1.0 / 0 / 0 | pass |

The problem is **false positives**, not recall. Slice 1 adds a new engine, `ai-hypothesis.1`: a fixed catalogue of
drafting questions answered by a **local scanner** over the whole document. A model may add a separate,
advisory **AI review signal** on evidence the scanner already found. It never changes what the scanner decided.

## 1. Non-negotiable rules

1. **Two separate catalogues.** Universal drafting questions (every document) and type-specific drafting
   questions (tenancy, NDA, employment) are separate files. Neither is a legal playbook.
2. **The scanner decides status, and its status is immutable.** A deterministic local scanner reads the
   **entire** frozen text and sets each question's status: `present | not_located | ambiguous |
   unable_to_determine`. Nothing after the scanner — the model, the validator, the combiner — rewrites it.
   Only a lawyer's recorded decision (§6) adds a separate outcome beside it.
3. **The model never decides status.** It receives only located evidence and returns an `ai_review_signal`
   (`supports | does_not_support | unclear`) plus a short explanation, stored **beside** the scanner result. It
   cannot create, remove or change a status, cannot add a question, and cannot say something is absent.
4. **Every result is anchored, possibly across clauses.** `present` and `ambiguous` carry
   `evidence_groups[]`: one group per clause, `{clause_id, sentence_ids[]}`. Parties, conflicting values and
   cross-references routinely span several clauses. Evidence text is always cut by the server from the frozen
   text at stored offsets; the model never quotes.
5. **Legal playbooks stay separate.** `playbooks/*.yaml` (`scope: legal_playbook`, lawyer approval required,
   cites law) are untouched and run exactly as today. The hypothesis catalogue cites **no law**, states **no
   legal conclusion**, and never says anything is required by law.
6. **The v1 dataset is regression only.** The existing 30-document dataset (`analyzer_eval/dataset/v1`,
   SHA `f5f61196…`) is never used to write detectors, patterns, prompts or thresholds. It is run only to compare
   old against new.
7. **A separate, versioned gate for `ai-hypothesis.1`** (§7): attention precision ≥ **0.80**, attention recall
   ≥ **0.85**, evidence validity **1.0**, injection success **0**, leakage **0**. It lives in a **new** record.
   The `ai-report.1` record and its 0.70 threshold are immutable and are not edited.
8. **No legal approval without a lawyer.** A developer-labelled calibration can give at most
   `engineering_passed`. `production_approved` requires lawyer-labelled calibration, the sealed holdout and a
   qualified reviewer's sign-off.
9. **New versions; old reports immutable.** Schema `ai-hypothesis.1`, prompt `ai-hypothesis-prompt.1`,
   catalogue `drafting-hypotheses.v1`. Existing `ai-report.1` items and runs are never rewritten or re-labelled.
10. **A model failure never fails the scanner.** Timeout, rate limit, provider error, invalid output, the AI
    layer not ready or switched off: scanner results are published and shown; only the AI review signal is
    `unavailable` (with a reason code).
11. **No dynamic code from the catalogue.** Detector names in the YAML resolve through a **static whitelist
    registry** in code. An unknown name fails the catalogue load (closed). No `import_module`, no `getattr` on
    arbitrary names, no `eval`, no regex compiled from untrusted input at runtime beyond the reviewed catalogue.
12. **Slice 2 (PII masking) before any real document reaches a model.** Slice 1's model path stays
    synthetic-only (`ANALYZER_AI_SYNTHETIC_ONLY=true`). Scanner-only results on real documents (§8) still go only
    through the existing privacy, access and retention approvals. Slice 1 bypasses none of them.

## 2. Words the UI may use

| Status | UI label | Styling | Meaning |
|---|---|---|---|
| `present` | **Found** | neutral | Wording of this kind appears at the cited sentence(s). Not a statement that it is sufficient. |
| `not_located` | **Not located automatically** | **neutral review item, never red** | The scanner did not find it. **Never "Absent", never "Missing".** |
| `ambiguous` | **Unclear** | attention | Found, but vague, incomplete or conflicting (reason code shown). |
| `unable_to_determine` | **Could not check** | muted | The scanner could not answer (reason code shown). |

**"Missing"** may be shown **only after a lawyer confirms it** (§6). Until then every `not_located` result reads
"Not located automatically — a lawyer should confirm."

The AI review signal, when present, is shown separately and smaller, under the scanner result: "AI review:
supports / may not support / unclear", or "AI review unavailable". It never changes the label above it.

Every scanner-only result carries three labels: **"Automatic drafting check — no AI"**, **"No law applied"**,
**"Not lawyer reviewed"**. When an AI review signal is shown, the first label becomes "Automatic drafting check
— AI review attached".

## 3. The catalogues

New directory `backend/app/services/analyzer/hypotheses/` — **not** under `playbooks/`.

### 3.1 Universal (`universal.yaml`, every document, including an unknown type)

| id | Question | Scanner source |
|---|---|---|
| `parties_identified` | Are the parties identified? | designations in `doc_graph` ("the Landlord"), `between … and …` |
| `execution_date` | Is a date of making or effect stated? | date patterns (shared detector, also used by `general.yaml`) |
| `signature_block` | Is there a signature/execution block? | signature/witness patterns |
| `blank_placeholders` | Are there blanks or placeholders? | `segmentation.empty_form_field`, `____`, `[●]`, `TBD`, `[insert …]` |
| `conflicting_values` | Do amounts, dates or periods conflict? | one term (via `terms.py`) with two different values |
| `unresolved_references` | Do cross-references resolve? | `doc_graph` reference rows: `unresolved` / `ambiguous` |
| `undefined_terms` | Are capitalised terms used but not defined? | `doc_graph` `possible_undefined_term` |
| `dispute_resolution` | Does it say how disputes are resolved? | dispute / arbitration / court patterns |
| `governing_law_stated` | Does it name a governing law? | "governed by", "laws of" (drafting only, no legal claim) |

`blank_placeholders`, `conflicting_values`, `unresolved_references` and `undefined_terms` are
`polarity: attention_if_present`: finding one is something to look at. The rest are `attention_if_absent`.

### 3.2 Type-specific (run only when the confirmed document type matches)

| File | Questions (drafting completeness only) |
|---|---|
| `tenancy.yaml` | rent amount; rent period / due date; security deposit and its refund; term / duration; description of the premises; termination notice; utilities and maintenance responsibility; rent increase terms |
| `nda.yaml` | definition of confidential information; mutual or one-way stated; confidentiality duration; standard exclusions; return / destruction of information; disclosure when legally compelled |
| `employment.yaml` | position / role; start date; salary amount; pay date; working hours; probation; notice period; leave |

When the document type is unknown or unconfirmed, the **universal checks run normally** and every type-specific
check is recorded as skipped (`skipped: document_type_unknown`), not as `unable_to_determine` results that would
crowd the list.

### 3.3 Question schema

Each question declares:

- `id`, `question`, `applies_to`, `polarity` (`attention_if_absent` default | `attention_if_present`);
- `detector`: a **name from the whitelist registry** (§1 rule 11);
- `specificity`: what makes a found item `ambiguous` (e.g. "rent amount found but no figure", "notice found but
  no period"), expressed as named sub-checks of the same detector;
- `explain`: whether the AI review signal is requested at all.

The catalogue is data, versioned (`drafting-hypotheses.v1`) and hashed; every run records the hash. The loader
validates the schema, rejects unknown keys, unknown detectors, duplicate ids and law-like wording (the same
leakage rules the AI validator uses), and fails closed.

## 4. Pipeline

```text
frozen text + segmentation + doc_graph + term candidates          (existing, local)
        ↓
LOCAL SCANNER — universal always; type-specific when the type is confirmed
  → status (FINAL), evidence_groups[{clause_id, sentence_ids[]}], reason_code
  → PUBLISHED here: scanner results stand on their own                (no model)
        ↓
SELECT for AI review: present/ambiguous results with explain=true,
  their evidence sentences only (capped per item), minus sentences
  the injection scan flagged                                          (local)
        ↓
MODEL (pinned Groq, ZDR) — per item:
  {question_id, ai_review_signal: supports | does_not_support | unclear,
   explanation ≤ 240 chars}                       (cannot add items or change status)
        ↓
VALIDATE — schema; ids must be exactly those sent; explanation has no law,
  no legal conclusion, no quote; at most one answer per item          (local)
        ↓
ATTACH the signal beside the scanner result. On ANY model failure:
  ai_review_signal = unavailable(reason) for every item; scanner
  results unchanged                                                    (local)
        ↓
Lawyer: confirm / dismiss / point to evidence (§6)
```

### 4.1 Scanner status and AI review signal are independent

| Scanner status (final) | Sent to the model? | AI review signal |
|---|---|---|
| `present` | if `explain=true` | `supports` / `does_not_support` / `unclear` / `unavailable` |
| `ambiguous` | if `explain=true` | same |
| `not_located` | **never** | `not_requested` |
| `unable_to_determine` | **never** | `not_requested` |

The status column is written once, by the scanner, and is never edited. A `does_not_support` signal on a `present`
result is a hint for the lawyer, not a status change. Measuring whether the signal is useful is part of the
evaluation (§7), and it never enters the gate's attention set.

### 4.2 `unable_to_determine` reason codes

`ocr_unconfirmed`, `page_map_unavailable`, `text_limit_reached`, `detector_error`, `language_unsupported`,
`structure_unavailable` (where the question needs DOCX structure), `evidence_flagged` (every sentence the
detector located was flagged by the embedded-instruction scan; a flagged sentence is never evidence -- the same
policy as the playbook engine). `not_located` is used **only** when the
scanner read the whole document and every input the question relies on is available. An unknown document type is
not a document-level code: it skips the type-specific checks (§3.2). The one universal question that needs a type
to compare values (`conflicting_values`) answers `unable_to_determine` / `needs_document_type` instead; every other
universal question still runs.

A numbered title standing alone ("1. Security Deposit") is never evidence, exactly like a heading: segmentation
keeps it as a sentence, but it states nothing.

### 4.3 AI review `unavailable` reason codes

`ai_layer_off`, `ai_not_ready`, `synthetic_only_refused`, `provider_timeout`, `rate_limited`, `provider_error`,
`schema_invalid`, `injection_scan_missing`, `no_confirmed_text`, `text_integrity`, `nothing_to_review`, and per
item `item_dropped_or_unanswered` (the validator dropped it, or the model gave no answer for it). Each item's signal records
one; the run summary counts them. None of them changes a scanner result or the run's scanner outcome.

### 4.4 Data sent to the provider

Per run: the selected evidence sentences only (each ≤ 1,000 chars, as today), with their sentence and clause ids
and the question text. **Never** the whole document, never `not_located` or `unable_to_determine` questions,
never flagged sentences. The run records the exact sentence ids sent and their hashes (the Slice 3 "processing
receipt" builds on this).

## 5. Storage and versions

- New collection `analysis_hypothesis_results`, keyed `(run_id, question_id)`:
  - scanner part (written once, then immutable): `status`, `evidence_groups[{clause_id, sentence_ids[],
    offsets, hashes}]`, `reason_code`, `polarity`, scanner version, catalogue hash;
  - AI part (written separately, may stay absent): `ai_review_signal`, `explanation`, `unavailable_reason`,
    prompt and schema version, model id.

  Evidence is offsets + hashes, never text. Raw provider output is never stored.
- Which engine a run uses is set by `ANALYZER_ENGINE_HYPOTHESES` (default off) **when the run is created** and
  stored as `run.engine` (`ai-report.1` | `ai-hypothesis.1`); flipping the setting never moves an existing run.
  An `ai-hypothesis.1` run goes analysis → `queued_hypothesis_scan` → `hypothesis_scanning` → done, whatever the
  AI layer's state. *(Step 3, built.)*
- Two stages: `hypothesis_scan` (publishes scanner results) and `hypothesis_ai_review` (attaches signals). The
  second can fail, time out or be skipped without touching the first. A run using this engine does not run the
  `ai-report.1` stage. The engine is recorded on the run at creation; old runs keep theirs.
- *(Step 4, built.)* After the scan publishes, the run goes to `queued_hypothesis_review` only when the AI layer
  is on and ready and at least one item is reviewable; otherwise it ends `done` with the reason. The review stage
  (`hypothesis_review_stage.py`) re-checks synthetic attestation, readiness, the text hash and the
  embedded-instruction scan, calls the pinned model once outside any transaction under a heartbeat, validates
  (`hypotheses/review.py`), writes one insert-only row per sent item to `analysis_hypothesis_reviews`
  (signal + explanation, or `unavailable` + reason; sentence ids and SHA-256s, never text, never the raw
  response), and publishes through `commit_stage`. `report(run)` returns the published scanner rows unchanged
  with the published signal beside each (`not_requested` where none was asked).
- Old `ai-report.1` items and runs are never migrated, rewritten or re-labelled.
- Deletion follows the run's existing lifecycle.

## 6. Lawyer actions

Per result: **Confirm** (`not_located` → "Missing (confirmed by lawyer)"; `ambiguous` → "Needs drafting"),
**Dismiss** (with a reason code), or **Point to evidence** (pick the sentence the scanner missed; shown as "Found
by lawyer"). Every decision is an append-only event (actor, time, decision, reason code, sentence ids). The
scanner's result and the AI signal are never overwritten. These decisions are the raw material for a future
lawyer-labelled calibration set.

## 7. Evaluation

| Set | Use | Labels |
|---|---|---|
| **v1** (existing 30 docs) | **Regression comparison only.** Never used to write or tune anything. | developer |
| **calib-1** (new, ≥ 45 synthetic docs: 15 per type, all variants) | Engineering gate. Written only AFTER the catalogue is frozen. | developer (lawyer not yet available) |
| **holdout-1** (new, ≥ 15 docs) | **Sealed.** Written and hashed, then not opened or run until a qualified lawyer labels it. | lawyer (pending) |

Metrics on calib-1, per question and overall:

- **Attention precision / recall.** An attention item is a scanner result the UI flags: `not_located` or
  `ambiguous` for `attention_if_absent`; `present` or `ambiguous` for `attention_if_present`. The
  0.80 / 0.85 gate applies here, and it is about the **scanner**, because the scanner alone decides status.
- Evidence validity (1.0), injection success (0), leakage (0) — unchanged definitions, applied to the AI review
  explanations and to the scanner's evidence.
- `unable_to_determine` rate, reported. An item turned into `unable_to_determine` still counts as a miss for
  recall, so it cannot hide errors.
- **AI review signal usefulness (reported, not gated):** how often `does_not_support` lands on a scanner false
  positive versus a true one, and the `unavailable` rate by reason.

**The record:** a **new** file `ai_hypothesis_evaluation_record.yaml`, with the engine, catalogue, prompt and
schema versions, dataset hashes, the gate above, and `status: not_yet_evaluated | engineering_passed |
not_passed`, plus `label_review: developer_only | lawyer_reviewed`. `production_approved` is not a reachable
value while `label_review` is `developer_only`, and requires the holdout result. The `ai-report.1` record is not
edited.

**v1 regression:** map attention items to the v1 scorer's risk shape (`missing_detail`, `contradiction`,
`ambiguity`, with sentence ids) and report old vs new side by side. Not a gate; a check that nothing the old layer
caught is silently lost.

## 8. UI (lawyer dashboard, Analyzer)

- A "Drafting questions" section: universal first, then type-specific (or a "type not confirmed — type-specific
  checks skipped" note), each with the status label and styling from §2, clickable evidence grouped by clause,
  the reason code for Unclear / Could not check, the three labels, and the AI review signal separately when
  there is one.
- `not_located` is a neutral review item, never styled as a legal risk.
- Legal playbook results stay in their own section, unchanged, with their own approval state.
- No "Missing" until a lawyer confirms. No law cited by this section.
- Scanner-only results may be shown before the model passes its gate (decision 3, §11). On a real document they
  appear only where the existing privacy, access and retention approvals already allow the analyzer to process
  that document at all.

## 9. Tests (beyond the gate)

- Each detector: unit tests with positive, negative and ambiguous examples written for it (not from v1).
- Catalogue loader: unknown detector name, unknown key, duplicate id, law-like wording → load fails; no dynamic
  import path exists (asserted by test).
- The model cannot change or create anything: a scripted responder that returns extra ids, new questions,
  "absent", a different status or quotes → dropped, counted, and every scanner status is unchanged.
- Model failure: timeout, rate limit, provider error and invalid output each leave all scanner results published
  and set the matching `unavailable` reason.
- `not_located` and `unable_to_determine` are never in a prompt (asserted on the prompt builder).
- Multi-clause evidence: parties, conflicting values and references produce several evidence groups, each with
  the right clause id.
- Unknown document type: universal results present, type-specific recorded as skipped.
- Old `ai-report.1` runs render unchanged.
- Injection: flagged sentences never in the prompt; canaries never in kept output.

## 10. Order of work (Slice 1)

1. Catalogue schema + strict loader + detector whitelist registry; the universal and type-specific YAML
   (frozen before calib-1 is written).
2. Shared detectors (patterns factored out of `general.yaml` into reusable functions; `general.yaml` keeps
   working unchanged).
3. `hypothesis_scan` stage + storage; works end to end with **no model at all**.
4. `hypothesis_ai_review` stage: prompt `ai-hypothesis-prompt.1` + schema + validation + failure handling.
5. Evaluation harness: calib-1 scoring, signal-usefulness report, v1 regression mapping, new record.
6. Lawyer UI section + lawyer decision events.
7. Write calib-1 (after step 1 is frozen) and seal holdout-1; run calib-1; record.

Then **Slice 2 — PII masking** (mandatory before any real document reaches a model), Slice 3 — processing
receipt + audit, Slice 4 — per-layer retention, then lawyer-labelled calibration and the holdout, and only then a
decision on real documents.

## 11. Decisions (owner, 2026-10-03)

1. **Gate:** attention precision ≥ 0.80 and recall ≥ 0.85 (with evidence validity 1.0, injection and leakage 0)
   are approved **only** as the versioned gate of the new `ai-hypothesis.1` engine, in its own record. The
   `ai-report.1` record and its 0.70 stay as they are.
2. **Labels:** no lawyer is available now. calib-1 is developer-labelled and can give at most
   `engineering_passed`. holdout-1 stays sealed. Without a qualified lawyer there is no `production_approved`.
3. **Scanner-only results are shown to lawyers:** yes, labelled "Automatic drafting check — no AI", "No law
   applied", "Not lawyer reviewed". `not_located` is a neutral review item, not a red legal risk. Running the
   scanner on real documents does not bypass the existing privacy, access and retention approvals.
