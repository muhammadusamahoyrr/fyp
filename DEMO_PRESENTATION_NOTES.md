# Document Analyzer — presentation notes

Speaker notes for the FYP demo. Each claim is tied to code, a test or a committed artifact, so it can be checked during questions. How to run the demo: [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md).

---

## 1. Architecture and data flow

```
Browser (Next.js, :3001) ──same-origin /api/v1──► the normal FastAPI app (:8000) ──► MongoDB replica set (127.0.0.1:27018)
                                                   │  every module, one process          (transactions; local database)
                                                   ├─ encrypted upload store (ANALYZER_KEKS)
                                                   └─ analyzer worker, started once by the app's own lifespan
```

One analysis, stage by stage. Each stage is a state on the run, advanced in a MongoDB transaction with a compare-and-set on `state_version`:

1. **Upload.** The route gates read headers only: feature on → ready → synthetic attestation → idempotency key → size. Only then is the body parsed. The file is stored encrypted.
2. **Extraction** (text layer / OCR engines) → **segmentation** into sentences and clauses, plus a proposed document type and province, each with its evidence sentence.
3. **Lawyer confirms the document type**, then **the key terms**. Only confirmed terms decide which checks apply.
4. **Local checks** (`playbook_engine.py`):
   - the *General document review* pack runs on every document and makes no legal claim;
   - *legal playbooks* run only with an approval bound to their exact hash; otherwise they show **"Pending qualified lawyer validation"**.
5. **AI step, held for the lawyer** (`pii_confirmation.py`, lawyer-confirm mode):
   - evidence selection, then masking (`pii-mask.10`);
   - the lawyer reviews the original next to the masked text, decides each uncertain item, marks missed details and links aliases;
   - the lawyer previews the **exact** request (fingerprint = SHA-256), attests and approves.
6. **Request**: the client refuses messages that differ from the approved fingerprint. With `ANALYZER_AI_PROVIDER=simulated`, it also refuses any transport except the in-process simulation. Requests go to `http://simulated.invalid/…`, a reserved name that can never resolve, and no key is sent.
7. **Response validation** (`ai_report.py`):
   - schema check;
   - every item must cite sentence ids that were actually sent;
   - parties must be named in their evidence;
   - stated deadlines must appear in the evidence.
   Evidence is then re-quoted from the **original** text.
8. **Fenced persistence and receipt** (`receipts.py`): an append-only, hash-chained receipt of ids, hashes, versions and codes, shown by the receipt view.

## 2. What's implemented, and what the demo adds

**Implemented and exercised in the demo:**
- lawyer-only and owner-only access;
- synthetic attestation;
- extraction and segmentation;
- type and terms confirmation;
- the general drafting checks;
- legal packs held as pending;
- the masking review: uncertain items, marking missed details, identity linking, people confirmation;
- the exact-request preview, fingerprint, attestation and approval invalidation;
- validators;
- evidence from the original text;
- the processing receipt and its integrity chain.

**Added for this demo** (`simulated_provider.py`, `ProcessingReceipt.jsx`, `serve.py --env-overlay`, the fixtures):
- a **simulated provider** inside the normal pipeline. It is selected only by explicit configuration (`ANALYZER_AI=true` and `ANALYZER_AI_PROVIDER=simulated`; the default is `groq`). It is never a runtime fallback: under `groq` the simulation is refused, and under `simulated` everything else is (`test_analyzer_simulated_provider.py`);
- readiness keeps the analyzer closed unless the database is on this machine (no hosted cluster) and synthetic-only is on;
- every output names it: provider `simulated`, model `demo-simulated-1`, "Simulated AI response — demo mode", and evaluation "not applicable";
- its answers are built only from the approved request and still pass the real validators;
- the receipt view; an optional isolated backup launcher (`scripts/analyzer_demo.py`).

**Not shown, because it isn't ready:**
- the drafting-question scanner (section 4);
- any real AI model;
- legal checklists (no qualified-lawyer approval exists).

## 3. The PII masking result: reviewer-assisted, not automatic

Committed record: `backend/app/services/analyzer/pii_detection_record_pii_eval_8.yaml`.
- Dataset `pii-eval-8`: 48 synthetic documents, frozen before the run.
- Production pipeline (`production-rules-only`, `pii-mask.10`, review `pii-review.2`), scored on the PDF path.

| Path | Documents sent | Personal pieces | Detected | Character coverage | Leaks |
|---|---|---|---|---|---|
| `pdf/report/auto` (scanner alone) | 10 / 48 | 472 | 55.1 % | 66.0 % | 23 |
| `pdf/report/manual` | 32 / 48 | 472 | 60.4 % | 75.0 % | 60 |
| `pdf/report/review` (**the gate**) | 39 / 48 | 472 | 100 % | 100 % | **0** |

- **What `detection_passed` means.** The gate is scored in *review* mode by a **simulated reviewer that decides by the gold labels** (`pii_evaluation._oracle`). It marked 204 missed details and made 310 identity decisions.
- **What the result shows.** The review workflow lets a careful reviewer reach zero leaks, keeps party identities consistent, and keeps 100 % of deadlines readable.
- **What it doesn't show.** It does **not** show that the scanner finds personal data on its own: alone, it leaked in 23 places.
- **Status line.** The app shows `current_pass` because the processing code still matches the pins in the record. `authorizes_real_documents` is always `false`.
- **In the demo.** The scanner misses the landlord's name in the tenancy fixture. That's this limitation, shown live.

**470 vs 472, reconciled from the committed code and data (no labels or results changed):**
- `coverage()` counts **470** gold personal spans in the dataset.
- Scoring first runs `_split_at_sentences()` (pii-eval.2.2), which cuts any gold span that crosses a sentence boundary into one piece per sentence. The request is built, and reviewed, sentence by sentence.
- Exactly **2** of the 470 spans cross a boundary, and each becomes 2 pieces: 470 − 2 + 4 = **472**.
- All 472 pieces fall in sentences that are sent.
- These counts were recomputed from the committed `pii-eval-8` dataset with the committed functions; only counts were read.

## 4. The scanner limitation

The **drafting-question scanner** (`ai-hypothesis.1`, `hypotheses/scanner.py`) has **not passed** its evaluation (`hypotheses/ai_hypothesis_evaluation_record.yaml`):
- dataset: validation-2, 70 documents, developer-labelled;
- attention precision is 0.861 and recall 0.941, both above the 0.80 / 0.85 thresholds;
- but the `no_weak_questions` check failed (some questions are individually weak);
- the holdout set hasn't been written;
- `production_approved: false`.

So it stays **off** in the demo (`analyzer_engine_hypotheses = False`, `analyzer_hypothesis_review_ui = False`). Wherever it is shown, the screen carries the server's "Evaluation not passed" status, and the scanner's status is shown separately from the AI review signal. The demo neither changes nor hides this.

## 5. Simulated vs live AI

| | Demo (this presentation) | Live (not demonstrated) |
|---|---|---|
| Provider | in-process simulation; no network; fails closed if anything else is tried | Groq, one pinned model from an allowlist, no fallback |
| Who answers | deterministic placeholder items from the approved request | a model |
| Labels | "Simulated AI response — demo mode", per-item badge, `simulated · demo-simulated-1`, evaluation "not applicable" | provider · model · prompt · schema, with the model's evaluation status |
| Receipt | "Demo mode — simulated provider. No external AI service was called" | "Live provider" |
| Everything else | the same code: masking, review, approval, fingerprint, validators, receipt | same |

A live run needs a verified zero-data-retention record, a policy record and an API key. None is configured for this demo. A Groq model (`gpt-oss-120b`) was benchmarked earlier and **not selected**.

## 6. Unsupported inputs and known limits

- English only; PDF, DOCX, JPG or PNG; up to 10 MB and 40 pages. Urdu script is withheld from AI requests.
- Synthetic documents only (`analyzer_ai_synthetic_only` stays true). Real client documents are not permitted.
- The local checks are drafting-completeness checks, not legal advice. "Not located automatically" means the reader didn't find it, not that it is absent or required.
- The masking scanner misses names, especially:
  - names after a role or in a list ("between Nargis Akhtar, holder of …");
  - nicknames and initials;
  - names split across a line break.
  The human review is required, not optional.
- The leak guard fails closed. A line such as `Signed …: ______ Signed by …` is read as a possible unmasked signer, and the request is blocked until it is fixed.
- Split names can produce two tokens (`[NAME_1] [NAME_2]`). Linking them is allowed, but then the token repeats.

## 7. Future work (production only, not done)

- Deployment: there are no containers or CI/CD, and the app has never run against the hosted database.
- A real provider behind a verified ZDR record, plus a model evaluation on a sealed holdout.
- The scanner: fix the weak questions, then write and score the holdout.
- Qualified-lawyer review and approval of the legal checklists.
- Independent (non-developer) PII labels; better unaided detection of names after roles, nicknames and initials.
- Retention and deletion jobs on production data, and an operational key store (the demo keys live in memory only).
