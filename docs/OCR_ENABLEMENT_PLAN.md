# OCR Enablement Plan

**Status:** proposal. Nothing in this document is implemented, enabled, or approved.
**Date:** 2026-09-13
**Branch at time of writing:** `fix/intake-retention-deletion` @ `49a7531`

This plan is documentation only. No provider call has been made, no client document
has been read or uploaded, no product code or feature flag has been changed, and no
approval to enable OCR is assumed at any point.

Decisions that require the project owner's written approval are marked
**[APPROVAL REQUIRED]**. There are eleven. They are collected in the checklist at
the end.

---

## 1. What is true today

### 1.1 Verified from code and database

| Fact | Evidence |
|---|---|
| No OCR exists in product code | No match for OCR/tesseract/pytesseract in `backend/app/` except a comment at `app/ai/extraction.py:158` stating OCR "does not exist" |
| No OCR library is a dependency | `backend/requirements.txt` contains no tesseract, paddle, easyocr, trocr, surya or doctr |
| Images and `.doc` are stored, never analysed | `STORAGE_ONLY_MIMES` = `application/msword`, `image/jpeg`, `image/png`, `image/gif`, `image/webp` — `app/services/evidence_coverage.py:41-44` |
| Gemini is the FIRST provider tried | `_FALLBACK_ORDER = ["gemini", "groq", "groq2", "openrouter"]` — `app/ai/llm.py:42` |
| `LLM_PROVIDER` is ignored unless it is `ollama` | `app/ai/llm.py:200`. The deployed value `openrouter` has no effect on ordering |
| `llm_local_only` removes the cloud entirely | `_provider_order()` returns `["ollama"]` — `app/ai/llm.py:197` |
| The scanned-page signal already exists | `pages_with_text` per document, zero-text branch at `app/ai/extraction.py:393` |
| A measurement harness exists and is frozen | `backend/ocr_eval/`, `HARNESS_VERSION = "1.0.0"` |
| The harness has produced no accuracy evidence | `OCR_READINESS_REPORT.md` tags every accuracy section `NOT_MEASURED` or `HARNESS_TEST_ONLY`; `ocr_eval/fixtures/` contains zero image or PDF files |
| Tesseract was measured and rejected | `tessdata_best` scored no better than `tessdata_fast`; a PSM sweep did not help |
| No production intake carries evidence | Read-only query, 2026-09-13: 63 intakes, 0 with `evidence_files` |
| Extraction runner hardening is committed | `49a7531` — per-file child processes, owner-scoped dedup, `CONFIG_VERSION = "2"` |

### 1.2 Assumptions — to be tested, never asserted

| Assumption | Why it is not a fact |
|---|---|
| A vision model is the best available engine for Nastaliq | Published benchmarks are on **books and newspapers**, not Pakistani legal documents |
| Benchmark accuracy transfers to phone photographs of FIRs | Every source reviewed reports significant out-of-domain degradation |
| Any particular Gemini model id is current, available and priced as quoted | Not verified against Google's live model list or pricing page. `app/ai/llm.py:55` pins `gemini-2.0-flash`, which may be superseded |
| Evidence upload is wanted by clients | Zero uploads is **unexplained**, not evidence of no demand — see §1.4 |

### 1.3 Corrections to earlier drafts of this plan

Recorded so a reviewer can see what was wrong and why.

1. **Confidentiality was mis-stated.** An earlier draft claimed sending page images
   to Gemini was "not a new disclosure" because document text already went there.
   An image discloses strictly more than its extracted text: signatures,
   letterheads, CNIC photographs, handwriting, stamps and faces. The correct
   statement is: **Gemini already receives client case narratives, so it is an
   existing processor; page images would be a new category of content sent to it.**

   No claim is made here about whether document text has been sent historically.
   The current database contains no intake with evidence files, but present
   contents cannot establish past provider usage, and this plan does not rely on
   either answer.

2. **A benchmark figure was misread.** `0.133` is the **word** error rate for
   Gemini-2.5-Pro on the Urdu Newspaper Benchmark, not the character error rate.
   The earlier claim that it implied "one character in eight is wrong" conflated
   word-level and character-level rates.

3. **"The harness has never been run" was wrong.** Tesseract *was* exercised during
   the feasibility spike. The accurate claim is that **no committed accuracy
   measurement exists on real fixtures**.

4. **"Zero demand" was an overclaim.** Zero evidence files is a fact about the
   current database. It is equally consistent with pre-launch, an unusable upload
   flow, or users not knowing the feature exists.

### 1.4 A question worth answering before any of this

Not an OCR question, and cheaper than the whole plan: **63 intakes, zero uploads.**
Before investing in reading documents better, it is worth establishing whether the
upload path works and whether clients are being asked to use it.

---

## 2. Milestone 1 — Authorized experiment

Produces a number. Changes no product code. Touches no client data.

### 2.1 Fixtures — authorized, non-sensitive, public only **[APPROVAL REQUIRED #1]**

**Only public documents already published by their issuing authority.** No client
evidence, no de-identified client evidence, no synthetic Urdu.

De-identification is excluded deliberately: redacting a scanned legal document
reliably is itself an unsolved problem, and a failed redaction would disclose the
exact material this milestone exists to protect.

Representative set, minimum **48 pages** — six slices × 8 pages — drawn from at
least four distinct sources:

Every acceptance slice in §2.4 must have its own fixtures. The classes map one-to-one
onto those slices, so no slice can pass implicitly.

| Slice (per §2.4) | Source | Min total pages | Min held-out pages | Why it must be present |
|---|---|---|---|---|
| English, typeset | SC / HC English judgments, Pakistan Code English text | 8 | 4 | English baseline — must be guaranteed, not incidental |
| English, photographed | Public English notices photographed by hand | 8 | 4 | Capture degradation without script difficulty |
| Urdu, typeset | Pakistan Code Urdu text | 8 | 4 | Clean Nastaliq baseline — the easiest Urdu case |
| Urdu, scanned | Public scanned orders, cause lists | 8 | 4 | Scan artefacts, skew, bleed-through |
| Urdu, photographed | Public notices, gazette pages photographed by hand | 8 | 4 | **The realistic client case** |
| Mixed Urdu/English | Any public document containing both scripts | 8 | 4 | Script switching within a line |

Each fixture records: source URL, retrieval date, publishing authority, and a
statement that it is public. A fixture without provenance is not admitted.

**Representativeness is the weakest point of this milestone and should be
challenged first.** Public judgments are typeset PDFs; a client is more likely to
photograph an FIR on a phone. The photographed class exists to reduce this gap but
does not close it. If the fixtures do not resemble what clients upload, the
measurement answers the wrong question.

### 2.2 Human transcription requirements

- Transcribed by a **person fluent in written Urdu**, not by any OCR or LLM.
- Stored per fixture beside the image, in UTF-8, with the transcriber recorded.
- **Layout policy fixed in advance and written down**: reading order for multi-column
  pages, treatment of headers/footers/page numbers, whether stamps and marginalia
  are transcribed. The normalisation policy already implemented in
  `ocr_eval/metrics.py:46` is applied to both sides at scoring time.
- **Critical tokens annotated explicitly** per page: dates, monetary amounts, CNIC
  numbers, case numbers, statute section numbers. These are scored separately — see
  §2.5a for what that score does and does not establish.
- **Field context recorded per token**, not just its value: which field the token
  belongs to (`fine_amount`, `imprisonment_years`, `section_number`, `order_date`)
  and its occurrence index on the page. Without this, §2.5a's association check
  cannot be computed, and the experiment can only measure presence.
- **Double transcription on the held-out set.** Two independent transcribers;
  disagreements resolved before scoring. A held-out score is only as trustworthy as
  its ground truth.

### 2.3 Document-level tuning and hold-out separation

**Split by document, never by page.** Pages from one document share layout, scan
quality, typeface and vocabulary; splitting by page leaks the test set into the
tuning set and inflates the result.

- **Tuning set:** 70% of documents. Prompt and configuration may be iterated here.
- **Held-out set:** 30% of documents, and it must independently satisfy the
  **per-slice minimums in §2.4** — 2 documents, 4 pages and 12 critical-token
  examples for every slice being claimed. The earlier "12 pages across 3 classes"
  rule is replaced: it allowed three slices to carry an acceptance table of six.
  Scored **once**, at the end, after configuration is frozen.
- The held-out set is not opened, viewed, or scored during tuning. If it is scored
  more than once, it is no longer held out and the milestone restarts with new
  documents.

### 2.4 Proposed acceptance thresholds **[APPROVAL REQUIRED #2]**

Registered **before any measurement**. Per `(language, capture)` slice, which the
harness already supports — a global average hides the photographed Urdu case behind
the typeset English one.

Thresholds apply to `primary_end_to_end` (§2.5), never to the diagnostic score.

| Slice | CER | WER | `critical_field_accuracy` | Min held-out docs | Min held-out pages | Min critical-token examples |
|---|---|---|---|---|---|---|
| English, typeset | ≤ 0.02 | ≤ 0.05 | ≥ 0.99 | 2 | 4 | 12 |
| English, photographed | ≤ 0.05 | ≤ 0.12 | ≥ 0.97 | 2 | 4 | 12 |
| Urdu, typeset | ≤ 0.10 | ≤ 0.25 | ≥ 0.95 | 2 | 4 | 12 |
| Urdu, scanned | ≤ 0.15 | ≤ 0.35 | ≥ 0.90 | 2 | 4 | 12 |
| Urdu, photographed | ≤ 0.20 | ≤ 0.45 | ≥ 0.85 | 2 | 4 | 12 |
| Mixed Urdu/English | ≤ 0.15 | ≤ 0.35 | ≥ 0.90 | 2 | 4 | 12 |

**Six slices, and every one must be independently satisfied.** An earlier draft had
five acceptance rows, no English-only fixture guarantee, no acceptance row for mixed
Urdu/English, and a hold-out requirement of only three classes — so a slice could
pass implicitly by never being tested. That is corrected here:

- **A slice with fewer than its minimum held-out documents, pages or critical-token
  examples reports `NOT_EVALUATED`.**
- `NOT_EVALUATED` is **not a pass**. The experiment may not claim any accuracy
  result for that slice, and Milestone 2 may not rely on it.
- An overall "pass" requires every claimed slice to be evaluated and within
  threshold. A partial result is reported as partial.

**The rationale for these numbers is an assumption, labelled as such.** An earlier
draft justified them as "where a reviewer could correct the output faster than
retyping it". **That has not been measured and is not a finding.** Either:

- measure it — time a fluent reviewer correcting OCR output against retyping the
  same page, on a handful of pages, and set thresholds from the result; or
- keep these numbers and record the rationale as **ASSUMPTION (untested)**.

**[APPROVAL REQUIRED #3]** — which of the two. The numbers themselves are
proposals, not derived from any measurement of this system; the owner may set them
anywhere, provided they are fixed before the first score is seen.

**Failure is an acceptable and expected outcome.** If the held-out set misses the
thresholds, the plan ends at Milestone 1 and OCR is not built.

### 2.5 Scoring: two separately named results

An earlier draft said failed pages score 1.0 and then defined accuracy "over pages
that produced output". Those are two different denominators, and stating both under
one heading is how a failure silently leaves the score. **Two results are computed
and reported under distinct names. Neither may be quoted as "the" accuracy.**

#### `primary_end_to_end`  — the result acceptance is judged on

- Denominator: **every eligible reference page**, including pages that errored,
  timed out, were refused by the provider, or returned nothing.
- An unsuccessful transcription is scored as **empty output**, not skipped and not
  assigned a synthetic 1.0. Empty output against a non-empty reference yields edit
  distance equal to the reference length, which is the correct arithmetic
  consequence rather than an imposed constant.
- This is the only figure compared against the §2.4 thresholds.

#### `successful_pages_only` — diagnostic

- Denominator: pages that returned any output.
- Reported beside the primary score and labelled **diagnostic**. It answers "when it
  works, how good is it", which is useful for engine comparison and useless for
  acceptance.

#### Aggregation

Corpus figures are computed from **summed edit counts over summed reference
lengths** — never as the mean of per-page percentages, which weights a five-word
caption equally with a five-hundred-word page.

```
corpus_CER = Σ(edit_distance over all pages) / Σ(reference_characters over all pages)
corpus_WER = Σ(word_edits      over all pages) / Σ(reference_words      over all pages)
```

`ocr_eval/metrics.py` already supports this: `ErrorRate` retains `edits` and
`reference_units`, and `aggregate_error_rate` sums them rather than averaging rates.

#### Empty references

A reference page with no text (a blank page, a photograph with no legible text) has
a zero denominator and **no defined error rate**. Such pages are:

- excluded from the CER/WER denominators, and
- reported separately as `empty_reference_pages`, with the count of **spurious
  characters** the engine produced on them.

A model that hallucinates a paragraph onto a blank page is a serious failure that a
rate of `0/0` would hide entirely.

#### Values above 1.0 are never capped

CER and WER exceed 1.0 when the hypothesis is longer than the reference — the
engine inventing text. **Uncapped, and reported as measured.** Capping at 1.0 would
make unbounded hallucination indistinguishable from returning nothing, and on a
legal document those are opposite failures.

#### Coverage and omission, reported separately

- **Coverage** — pages that produced any output.
- **Omission rate** — reference tokens absent from the hypothesis. A short, clean,
  incomplete answer otherwise scores better than a complete one.

### 2.5a Token presence is not token correctness

**The existing `critical_token_matches` metric measures PRESENCE, not association,
and must be reported under the name `critical_token_presence`.**

This was demonstrated, not inferred. Running the shipped metric
(`ocr_eval/metrics.py:181`) offline on a constructed pair:

```
reference : fine 1000 imprisonment 3 years
hypothesis: fine 3 imprisonment 1000 years

critical_token_presence -> rate 1.0  (2/2 matched)
character_error_rate    -> 0.267
```

Both numbers appear, so both tokens "match" — while the sentence now says a fine of
3 and imprisonment for 1000 years. The metric is working as documented: it checks
whole-identifier presence with occurrence counting, deliberately without fuzzy
matching. It was never designed to check that a value landed in the right field.

**Consequences for this experiment, binding:**

1. The metric is renamed in all reporting to **`critical_token_presence`**. The term
   "critical-token accuracy" is not used.
2. **It must never be presented as evidence that dates, amounts or section
   references were correctly associated.** It is a necessary condition, not a
   sufficient one: a token absent from the output is definitely wrong, a token
   present may still be attached to the wrong field.
3. A second metric, **`critical_field_accuracy`**, is added for the experiment: a
   token counts only if it appears **in the correct field and at the correct
   occurrence index**, using the field context required in §2.2. This is what the
   §2.4 threshold column is judged on.
4. If `critical_field_accuracy` is not implemented before the run, that slice
   reports **`NOT_EVALUATED`** and the experiment **cannot claim** field-level
   correctness for any document class. **[APPROVAL REQUIRED #4]** — the owner
   decides whether to implement it or to run presence-only and accept the narrower
   claim.

Adding a metric bumps `HARNESS_VERSION` (see §2.8), since it changes what the ruler
measures.

### 2.6 Model, configuration and service terms **[APPROVAL REQUIRED #5]**

**Candidate:** the current Gemini vision-capable model, confirmed against Google's
live model list **at approval time**. This document deliberately does not pin a
model id: the ids referenced in the codebase and in public sources during research
are of uncertain currency, and a stale id in an approval document is worse than an
absent one.

Configuration pinned and recorded verbatim in the report:

| Field | Value |
|---|---|
| model id | *confirmed at approval* |
| temperature | `0` |
| prompt | one fixed string, recorded verbatim |
| render DPI | `300` |
| image format | PNG, one page per call |
| max output tokens | fixed |
| retries | ≤ 2, exponential backoff, counted |
| concurrency | ≤ 2 in-flight calls |

**Service terms to confirm before approval:** whether the API tier used trains on
submitted content, the data-retention period for submitted images, and the
processing region. A free or consumer tier with training rights is not acceptable
even for public fixtures, because it sets the precedent the integration would
inherit.

### 2.7 Cost calculation and budget enforcement **[APPROVAL REQUIRED #6]**

```
total_cost = Σ over every call actually issued, including:
               - retries
               - concurrent calls in flight
               - calls whose response was discarded
             of  (input_tokens × input_rate) + (output_tokens × output_rate)
```

Enforcement, in the harness runner, not in a spreadsheet:

1. A **hard ceiling** in USD, approved as a single figure.
2. A **running total** updated from each response's reported token usage.
3. A **pre-flight reservation**: before issuing a call, the worst-case cost of that
   call plus its permitted retries is added to the running total; if the ceiling
   would be exceeded, the call is not issued and the run stops.
4. Because up to 2 calls are in flight, the reservation is taken **before**
   dispatch, so two concurrent calls cannot both pass a check the budget only
   covers once.
5. The run **stops at the ceiling** and reports `BUDGET_EXHAUSTED` with the pages
   not attempted. It does not silently truncate the fixture set.
6. The report states **approved ceiling, actual spend, and calls issued** — the
   last of these makes retry amplification visible.

**Unknown-cost rule — a timed-out call may have been billed.** A call that times
out, drops the connection, or returns without usage metadata was very likely
processed and charged. Treating missing usage as zero understates spend exactly when
a run is going wrong.

- A call's **reservation is held, not released**, when its usage is unknown. It
  continues to occupy budget.
- The running total is reported as **two figures that are never summed into one
  headline number**:
  - `confirmed_cost` — from usage actually reported by the provider.
  - `unknown_exposure` — worst-case cost of calls with no usage returned, still
    reserved.
- The ceiling is enforced against **`confirmed_cost + unknown_exposure`**, so
  unknown calls cannot be spent twice.
- Reservations are released only on **reconciliation**: either usage arrives, or the
  provider's billing/usage console is checked after the run and the figure is
  recorded manually. Until then the exposure stands.
- The report states both figures and the count of unreconciled calls. A run ending
  with non-zero `unknown_exposure` is reported as **estimated, not final**.

A cost-per-page estimate is deliberately omitted: it would require a token count
this plan has not measured, and an unmeasured figure in a budget approval is the
kind of number that later gets quoted as fact.

### 2.8 Harness changes

- Register the engine in `_REAL_ENGINES` (`ocr_eval/harness.py:62`) and add a worker
  path beside `_run_tesseract` (`ocr_eval/worker.py:154`).
- **Bump `HARNESS_VERSION` to `1.1.0`.** The freeze docstring lists extraction,
  metrics, page accounting and thresholds as bump triggers, and adding an engine is
  none of those — but `OcrConfig.as_report_dict()` gains fields, and a number must
  be traceable to the exact invocation shape that produced it. A reviewer who
  disagrees should say so explicitly rather than leave it implicit.

### 2.9 Exit criteria

A committed report containing: per-slice CER, WER, critical-token accuracy,
coverage and omission rate on the **held-out** documents; measured against the
pre-registered thresholds; with approved-vs-actual spend and calls issued; stamped
with the harness version, model id and prompt.

---

## 3. Milestone 2 — Optional integration, flag off

**Entry condition: the owner has read Milestone 1's measured results and has
explicitly chosen to proceed.** Passing thresholds does not by itself authorise
this milestone. **[APPROVAL REQUIRED #8]**

Ships with `ocr_enabled: bool = False`, mirroring `intake_deletion_enabled`.
Nothing runs in production as a result of this milestone.

### 3.0 The exclusion rule ships here, not at rollout

**Unconfirmed OCR text is excluded from legal analysis server-side, and that
exclusion is implemented and tested in THIS milestone** — not deferred to
Milestone 3.

Milestone 2 is the milestone that first makes OCR text exist. If the exclusion
arrives later, there is an interval in which OCR text can reach the analysis with no
mechanism preventing it, and the only thing standing between an unreviewed machine
reading and a client's legal summary is that the flag happens to be off. A safety
rule that depends on a flag being off is not a safety rule.

Since Milestone 2 has no review UI, **every OCR page is unconfirmed by definition**,
so in this milestone the rule means: OCR text reaches the analysis prompt **never**.
Milestone 3 adds the path by which a page can become confirmed; it does not add the
exclusion. The full rule and its enforcement are specified in §4.1, and its test
(OCR text appears nowhere in the assembled prompt string) is part of Milestone 2's
acceptance.

### 3.1 Page-level and region-level decisions

**Mixed-page documents.** A PDF with text-bearing and scanned pages OCRs **only**
the scanned pages. The decision is per page, never per document. `pages_with_text`
is already tracked per document; Milestone 2 requires the same signal per page.

**Text headers above scanned bodies on one page.** A page can carry a native text
layer for a letterhead or header while its body is an image — a scanned document
with a typed header band, or a photograph pasted into a generated PDF. Handling:

1. Extract the native text layer for the page and record its **character count and
   bounding boxes**.
2. **Bounding-box area does not establish extraction completeness.** A page whose
   native text boxes cover most of its area can still be missing a scanned figure,
   a stamp, or a handwritten endorsement; a page with little native text may be
   complete. Area is recorded as a **signal for review**, never as the criterion
   that decides a page was fully extracted. Any page with *both* a native text
   layer and unextracted image regions is treated as partially native and OCR'd.
3. **No automatic duplicate deletion in the initial implementation.** An earlier
   draft dropped OCR lines matching native lines above a similarity threshold. That
   is unsafe: "fine of Rs 10,000" and "fine of Rs 100,000", or "section 302" and
   "section 342", are near-identical under any normalisation and differ in exactly
   the way that matters. Sharing the benchmark's normalisation makes the comparison
   *consistent*; it does not make deletion *safe*.
4. **Both outputs are preserved.** Native text and OCR text are stored separately
   for the page. Suspected duplicates are **flagged for review**, not removed:
   each suspected pair is recorded with both texts and a similarity score, and
   surfaced in the Milestone 3 review UI for a human to resolve.
5. **Native text is not automatically correct either.** A PDF's text layer can be
   produced by an earlier OCR pass, can carry a broken encoding, or can disagree
   with the visible page. Where native and OCR text conflict, the page is marked
   `ocr_reconciliation_uncertain` and **both** are retained for review. Native text
   is preferred as analysis input only when no conflict is flagged.
6. Automatic de-duplication may be reconsidered later, on evidence from review
   decisions about how often flagged pairs are genuine duplicates. It is out of
   scope for the initial implementation.

**Native and OCR text are never concatenated into one field.** They are stored
separately, per page, end to end.

### 3.2 `.doc` remains unsupported

`application/msword` is a binary word-processor format, not an image. OCR cannot
read it. It stays in `STORAGE_ONLY_MIMES`, is **never routed to OCR**, and continues
to report `storage_only` — "stored, but this format cannot be read at all", which is
already the honest message. A test asserts `.doc` never reaches the OCR path.

### 3.3 Deduplication identity

`_batch_key` (`app/ai/extraction_runner.py:196-213`) currently keys a shared result
on `[owner_id, EXTRACTOR_VERSION, CONFIG_VERSION, batch_timeout,
PER_FILE_TIMEOUT_SECONDS, [(file_id, resolved_path, content_sha256)]]`.

The OCR identity **extends** this. Two requests may share a result only if all of
the following also match:

| Component | Why |
|---|---|
| `ocr_model_id` | A different model is a different reading |
| `ocr_prompt_sha256` | The prompt determines the output; an unpinned prompt makes results incomparable |
| `ocr_render_dpi`, image format | The bytes the model saw differ |
| `ocr_page_selection` | Which pages were sent |
| `ocr_config_version` | Covers temperature, max tokens and retry policy as one bump |

`owner_id` remains in the identity, unchanged: identical bytes belonging to
different owners must never share a result. As today, an identity that cannot be
fully established disables sharing rather than guessing — extracting twice is
cheaper than serving the wrong result once.

### 3.4 Bounds

| Bound | Rule |
|---|---|
| Pages per file | Hard cap |
| Pages per intake | Hard cap across all files |
| Per-call timeout | Fixed; a timed-out page is a failure, not a retry loop |
| Retries | ≤ 2, exponential backoff, **counted against the cost ceiling** |
| Concurrency | ≤ 2 in flight |
| Per-intake cost ceiling | Checked **before** dispatch, with the same pre-flight reservation as §2.7 |
| Total failure | OCR failure never fails the intake; the file reports its status and conversion continues |

### 3.5 Local-only enforcement

If `llm_local_only` is true, OCR is **disabled and reports as disabled**. There is
no cloud fallback, silent or otherwise. This mirrors the reasoning already recorded
at `app/ai/llm.py:197`: "prefer local" and "never spend money" differ precisely when
the local path fails, and that is the moment the distinction matters.

A test asserts that with `llm_local_only=True` and `ocr_enabled=True`, no provider
call is attempted and the status reports OCR unavailable.

### 3.6 Persisted coverage and review metadata

**Backward compatibility is a hard requirement.** `validate_snapshot`
(`app/services/evidence_coverage.py:218`) rejects a snapshot whose category counts
do not sum to `files_total`. New OCR counters must be **additive and outside the
summed category set**, or every case written before OCR renders UNKNOWN — which
would silently erase the coverage guarantees shipped in `c625400`.

Persisted per page from the first release, so Milestone 3 has somewhere to write:

| Field | Purpose |
|---|---|
| `ocr_status` | `not_attempted` / `machine_read` / `failed` / `skipped_native` |
| `ocr_model_id`, `ocr_prompt_sha256`, `ocr_config_version` | Provenance of the reading |
| `harness_version` | Ties a page to the ruler that validated the engine |
| `ocr_confidence` | If and only if the provider reports one; absent, not zero |
| `duplicates_suppressed` | From §3.1 reconciliation |
| `text_sha256` | Of the machine transcription, for §4.2 binding |
| `source_sha256` | Of the source file bytes, for §4.2 binding |
| `confirmed` | `false` on write. Never defaulted true |

### 3.7 Review-to-analysis workflow **[APPROVAL REQUIRED #9]**

**This is the gap that makes the rest of the plan incoherent if left unresolved.**

`convert_to_case` (`app/services/intake_service.py:369`) runs the AI analysis and
marks the intake completed. A later conversion request **replays the stored result**
(`intake_service.py:396`) rather than re-analysing, and further uploads are refused
once completed (`intake_service.py:1120`).

So with OCR added but nothing else changed: a client converts, the analysis runs on
incomplete evidence, the client then reviews and confirms the OCR transcription —
and **the case summary silently continues to reflect the pre-OCR evidence.** The
confirmation appears to succeed and changes nothing. That is worse than not offering
review at all, because it manufactures false confidence.

Two workable options. One must be chosen before integration; they are not
combinable without a third design.

**Option A — review before initial analysis.** Conversion pauses after extraction
and OCR, presents the transcription for review, and runs the analysis only once the
client confirms or explicitly declines to review.

- *For:* one analysis, always built on the evidence the client saw and accepted. No
  stale summary is possible.
- *Against:* introduces a blocking human step into a flow that is currently
  automatic, and changes the conversion state machine — which is the most
  concurrency-sensitive code in intake (atomic claim, epoch fencing, replay). Also
  needs a path for a client who never returns to review.

**Option B — explicit versioned re-analysis after confirmation.** Conversion is
unchanged. Confirming OCR makes a **new analysis revision** available, requested
explicitly, with the case recording which evidence revision its summary was built
from.

- *For:* leaves the conversion state machine alone. Makes the stale-summary
  condition visible and fixable rather than silent.
- *Against:* two analyses per case, and a window in which the case carries a summary
  known to be built on incomplete evidence. That window must be **visible in the UI
  and in `ai_evidence_coverage`**, not merely tolerated.

**Recommendation: Option B**, on the grounds that it does not touch the conversion
claim/epoch/replay logic, which is load-bearing and already hard-won. Option A is
the cleaner end state and may be worth the cost, but it is a larger change to the
riskiest code in the module.

Whichever is chosen, **the case must record the evidence revision its summary was
built from**, so "this summary predates your corrections" is a state the system can
detect and display rather than something a user has to infer.

---

## 4. Milestone 3 — User-reviewed rollout

**Entry: separate approval. [APPROVAL REQUIRED #10]**

### 4.1 Unconfirmed OCR text is excluded server-side

**Unconfirmed OCR text is excluded from legal analysis on the server. There is no
alternative path, no warning-prompt variant, and no configuration that admits it.**

The earlier draft's option — including unconfirmed text under a prompt block
forbidding assertion — is **removed**. A prompt instruction is a request to a model,
not an enforcement mechanism; it cannot be tested, cannot be audited after the fact,
and fails exactly when the model is least reliable.

Enforcement:

- The prompt builder in `_extract_intake_evidence` includes a page's text only when
  `ocr_status == "machine_read"` **and** `confirmed == true` **and** the
  confirmation binding of §4.2 validates.
- Unconfirmed pages are listed in the manifest **by file id and page number only**,
  under a heading stating they were machine-read and not yet confirmed, so the model
  knows the evidence is incomplete without seeing its contents.
- A test asserts that unconfirmed OCR text appears **nowhere** in the assembled
  prompt — asserted against the built prompt string, not against the intent of the
  code that builds it.

### 4.2 Confirmation binds file, page and transcription revision

A confirmation is a statement about **one specific transcription**, not about a
page in general.

Each confirmation record stores `(file_id, page_number, source_sha256, text_sha256,
revision_id, confirmed_by, confirmed_at)`.

**`source_sha256` is part of the binding.** A confirmation attests that *this
transcription* is a correct reading of *this source file*. If the underlying file is
replaced — re-upload under the same id, a repaired scan, any path that changes the
bytes — the confirmation is void even though the transcription text is unchanged,
because it now attests to a document that is no longer there.

- **Any change invalidates it:** a different `text_sha256` (edited or re-run
  transcription) or a different `source_sha256` (replaced file) reverts `confirmed`
  to false, and the text leaves the analysis input until re-confirmed.
- **Re-running OCR invalidates prior confirmations** for the affected pages.

**Analysis reads a pinned immutable revision, not live mutable rows.** An earlier
draft said the binding is checked "at prompt-assembly time against stored hashes".
That is insufficient: comparing mutable rows at assembly time is itself a
read-modify-read race — a row can change between the check and the use, and a
multi-page document can be assembled from rows that were never simultaneously valid.

Instead:

1. Assembling an analysis **pins an immutable evidence revision**: a snapshot
   identifying, per page, the exact `source_sha256`, `text_sha256`, `revision_id`
   and confirmation record used.
2. The prompt is built **from that pinned revision**, not from live rows. Concurrent
   edits during assembly cannot alter what the model sees.
3. The analysis result **records the evidence revision id it was built from**, which
   is what makes §3.7's staleness detectable rather than inferred.
4. An edit landing after pinning produces a **new** evidence revision; it does not
   mutate the pinned one. The prior analysis remains a truthful record of what it
   was built on.

### 4.3 Review writes require authorization

- Only the intake's **owning client** or a **lawyer engaged on the resulting case**
  may edit or confirm a transcription. Ownership is checked server-side on every
  write, against the record, never against a client-supplied id.
- A write to a file that does not belong to the requester is refused and logged
  without echoing the requested identifiers.
- Confirmation records **who** confirmed, and that identity is retained even after
  later edits — the audit question is who attested to what, and when.

### 4.4 Corrections preserve provenance

- The **original machine transcription is never overwritten.** Corrections are
  stored as revisions alongside it.
- Each revision records author, timestamp, and the prior revision it replaced.
- The UI shows the **original page image beside the editable transcription**, so a
  reviewer is correcting against the source rather than against their memory of it.
- The analysis consumes the **confirmed revision**, and the record retains both what
  the machine said and what the human corrected it to.

### 4.5 Behaviour tests

| Scenario | Required behaviour |
|---|---|
| Provider failure mid-document | Pages already read are kept; failed pages report `failed`; the intake does not fail |
| User cancellation | In-flight work stops; completed pages persist; no partial page is written as complete |
| Browser refresh mid-review | Review state restores, matching the intake's existing restore behaviour; unsaved edits are not silently lost or silently saved |
| Flag disabled during review | Confirmed text already in the record survives; unconfirmed text does not enter analysis; no new OCR is attempted; the UI reports OCR unavailable rather than appearing broken |
| Confirmation then edit | Confirmation invalidated; text leaves the analysis input |
| Re-run OCR after confirmation | Prior confirmations for affected pages invalidated |
| Unauthorized review write | Refused server-side |

---

## 5. Sequencing

**The extraction-runner dependency is resolved.** `49a7531`
("fix(extraction): isolate results and enforce child lifecycle bounds") is committed
and is an ancestor of the current HEAD. It carries per-file child processes,
owner-scoped deduplication, and `CONFIG_VERSION = "2"`. Milestone 2 extends the
deduplication identity introduced there (§3.3) rather than colliding with in-flight
work, and the earlier note in this plan that Milestone 2 must wait no longer applies.

Milestone 1 touches only `backend/ocr_eval/` and is independent of product code.

---

## 6. What this plan does not claim

- That OCR makes Urdu legal evidence reliable. At the accuracy levels published for
  Nastaliq it does not; it makes evidence **triageable by a human**, which is why
  Milestone 3 exists and why §4.1 is absolute.
- That any published figure applies to these documents. Benchmarks are books and
  newspapers; every source reports out-of-domain degradation.
- That the thresholds in §2.4 are correct. They are proposals awaiting approval.
- That any model id or price in circulation is current.
- That this work is urgent. Zero clients have uploaded a document, and why that is
  remains unexplained.

---

## 7. Approval checklist

Nothing proceeds until the items for the relevant milestone are approved in writing.

**Before Milestone 1 — fixture preparation**

- [ ] **#1 — Fixtures (§2.1).** Public, non-sensitive documents only; no client
      data, no de-identified client data, no synthetic Urdu. Minimum 48 pages across
      the six slices, each meeting its total and held-out minimums.

**Before Milestone 1 — execution** *(all of #2–#7 must be filled in and approved)*

- [ ] **#2 — Acceptance thresholds (§2.4).** The per-slice CER / WER /
      `critical_field_accuracy` figures, or the owner's replacements, fixed before
      any measurement.
- [ ] **#3 — Threshold rationale (§2.4).** Either measure correction-versus-retyping
      time, or record the rationale as ASSUMPTION (untested).
- [ ] **#4 — Field-accuracy metric (§2.5a).** Implement `critical_field_accuracy`,
      or run presence-only and accept that field-level correctness is
      `NOT_EVALUATED` and cannot be claimed.
- [ ] **#5 — Model, configuration and service terms (§2.6).** Exact model id
      confirmed current; output limit fixed; training, retention and processing
      region confirmed acceptable.
- [ ] **#6 — Budget (§2.7).** Exact prices and a single USD ceiling, enforced by
      pre-flight reservation covering retries and concurrent calls, with the
      unknown-cost rule in force.
- [ ] **#7 — Authorisation to run the experiment**, on the understanding that
      failing the thresholds ends the plan here.

**After Milestone 1, before Milestone 2**

- [ ] **#8 — Proceed to integration (§3).** Having read the measured held-out
      results. Passing thresholds does not by itself authorise this.
- [ ] **#9 — Review-to-analysis workflow (§3.7).** Option A (review before initial
      analysis) or Option B (explicit versioned re-analysis). Must be decided before
      integration begins.

**Before Milestone 3**

- [ ] **#10 — Rollout approval (§4).** Including the review UI and the confirmation
      binding in §4.2.

**Before enabling in production**

- [ ] **#11 — Enable `ocr_enabled`.** Separate from every approval above. **Not
      requested by this document.**

Note that the server-side exclusion rule (§4.1) is **not** an approval item: it
ships and is tested in Milestone 2 (§3.0) and is not optional at any stage.
