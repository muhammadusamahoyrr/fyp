# OCR Measurement-Readiness Report — Intake Evidence Pipeline

**Date:** 2026-09-12
**Scope:** measurement readiness only. No OCR was implemented, no production behaviour changed.
**Headline:** **OCR accuracy is NOT MEASURED and cannot be measured on this machine today.** No OCR engine is installed and no ground-truth dataset exists. A harness now exists that will measure it, and refuses to produce a number until both are supplied.

---

## 0. Legend

| Tag | Meaning |
|---|---|
| `VERIFIED_FROM_CODE` | Read in the source and re-confirmed by executing the real functions |
| `VERIFIED_FROM_ENVIRONMENT` | Output of the read-only capability probe on this machine |
| `HARNESS_TEST_ONLY` | Numbers describing harness mechanics on synthetic input — never accuracy |
| `NOT_MEASURED` | No measurement exists. Not zero, not estimated |
| `OWNER_INPUT_REQUIRED` | Blocked on a human decision or asset |
| `PROPOSED_NOT_IMPLEMENTED` | Design only. No code was written for it |

---

## 1. Current-state audit — `VERIFIED_FROM_CODE`

Claims below were confirmed by calling the real `app.utils.file_handler` and
`app.ai.tools.document_tools` functions, not by reading alone.

### 1.1 Which formats are accepted

Seven MIME types, detected from **magic bytes** — never from the filename or the
client's `Content-Type`. That part is done well.

| Detected MIME | Stored as |
|---|---|
| `image/jpeg` | `.jpg` |
| `image/png` | `.png` |
| `image/gif` | `.gif` |
| `image/webp` | `.webp` |
| `application/pdf` | `.pdf` |
| `application/msword` | `.doc` |
| `application/…wordprocessingml.document` | `.docx` |

Note: the allow-list exists **twice** — `file_handler._MIME_EXT` and
`intake_service._ALLOWED_MIME` are independent literals that presently agree.
Intake evidence uploads use the second; `save_upload()` is not on the intake path.

### 1.2 Which formats can actually be extracted

`document_tools._extract_text_sync` branches on suffix only:

| Suffix | Result |
|---|---|
| `.pdf` | pypdf text-layer extraction |
| `.docx` | python-docx paragraphs |
| `.txt` / `.md` | read as UTF-8 |
| `.doc`, `.jpg`, `.png`, `.gif`, `.webp` | `ValueError: unsupported file type` |

**So five of the seven accepted formats cannot be read at all.**

### 1.3 Scanned-PDF and image behaviour

Both fail, but **through different paths and with different messages** — verified
by building an image-only PDF and a PNG and calling `_read_file`:

- **Scanned PDF** → pypdf returns empty text → the honest, user-facing message:
  *"This file has no readable text layer — it is most likely a scan or photo"*,
  plus a hint to type the key details.
- **Image (PNG/JPG)** → never reaches that branch. It raises
  `unsupported file type '.png'`, which is developer-facing and says nothing
  about scans.

Both end up recorded as status `unreadable`, so the analysis is not corrupted.
Credit where due: the pipeline **never represents an unread file as read** — the
prompt and the tool descriptions both instruct the model to say so plainly. That
is the single most important property for a legal product, and it currently holds.

### 1.4 The accepted-but-unreadable legacy `.doc` mismatch — **CONFIRMED**

`detect_mime` recognises the OLE2 header `D0 CF 11 E0 A1 B1 1A E1` and
`application/msword` is in the allow-list (verified `True`). `_extract_text_sync`
then refuses `.doc`. A client can upload a Word 97-2003 document, be told it was
accepted, and have it silently contribute nothing to the analysis.

### 1.5 Arbitrary ZIP detected as DOCX — **CONFIRMED**

`PK\x03\x04` is the magic number for **ZIP**, not for DOCX. DOCX merely happens
to be a ZIP. Verified by building an ordinary zip containing one text file:

```
magic bytes : b'PK\x03\x04'
detect_mime : application/vnd.openxmlformats-officedocument.wordprocessingml.document
stored as   : .docx
extraction  : KeyError "There is no item named '[Content_Types].xml' in the archive"
```

Any `.zip`, `.xlsx`, `.pptx`, `.jar`, `.apk` or ZIP-framed payload is accepted
and stored as a Word document. The extraction `KeyError` is caught by a broad
`except Exception` in `_read_file` and returned as
`"Could not read the file: <library error>"`, which puts a library internal into
model-visible text.

Not exploited to RCE — nothing executes the archive — but it defeats the stated
purpose of content-based validation, and it is the kind of gap that matters more
once an OCR worker starts unpacking these files.

### 1.6 Current limits

| Limit | Value | Constant |
|---|---|---|
| Per file | 10 MB | `_MAX_EVIDENCE_SIZE` |
| Files per intake | 12 | `_MAX_EVIDENCE_FILES` |
| Total per intake | 40 MB | `_MAX_EVIDENCE_TOTAL` |
| Upload read chunk | 1 MB | `_EVIDENCE_CHUNK` |
| Text into the prompt | 12 000 chars | `_MAX_EVIDENCE_PROMPT_CHARS` |
| Text per tool call | 12 000 chars | `document_tools._MAX_CHARS` |
| Evidence uploads | 20/min | `_LIMIT_EVIDENCE` |
| Conversions | 6/min | `_LIMIT_CONVERT` |
| **Page count** | **none** | — |
| **Extraction timeout** | **none** | — |

The two 12 000-char ceilings are separate constants that happen to be equal, and
`file_handler.MAX_MB = 10` is a third size limit on a different path.

### 1.7 Where extraction runs — it **can** exhaust an API worker

`POST /intake/{token}/convert` awaits `convert_to_case` **inline in the request**.
That calls `_extract_intake_evidence` → `_read_file` → `asyncio.to_thread`.

`asyncio.to_thread` uses the interpreter's **default shared** `ThreadPoolExecutor`:
`min(32, cpu_count + 4)` = **12 workers on this 8-CPU machine**
(`VERIFIED_FROM_ENVIRONMENT`), shared process-wide with every other `to_thread`
caller in the app.

So one conversion can parse up to 12 files / 40 MB of PDF, with **no timeout and
no page cap**, holding a pool thread per file, while the client's HTTP request
waits. Two concurrent conversions of large PDFs can occupy a meaningful share of
that pool. The event loop is not blocked, but the pool is a shared, finite,
undifferentiated resource.

**This is a pre-existing property of text extraction. It is the single biggest
reason OCR must not be added in-process** — OCR is 10-100× more expensive per
page than a text-layer read.

### 1.8 Extraction state, provenance and retention

**State** — a fixed status vocabulary per file, which is better than most:
`readable` · `unreadable` · `missing` · `invalid_path` · `omitted_limit`, plus a
`truncated` flag.

**Provenance** — carried as `intake_evidence_status` through the graph state and
persisted as `analysis["evidence_extraction"]` on the intake, the case analysis
and the provenance record.

**Gap:** the status records *that* a file was readable, never *how*. No extractor
name, no version, no configuration. Today that is survivable because there is
exactly one extractor. **The moment OCR exists it is not** — "this text came from
Tesseract 5.3.4, `urd+eng`, 300 dpi" is what makes a bad extraction reproducible,
and what lets you find every case decided on output from a version you later find
to be broken.

**Retention** — more developed than I first assumed, and worth stating precisely:
`app/services/retention.py` **does** cover intake sessions and their evidence
uploads, with a declared 365-day policy (`USER_DATA_SECONDS`) and legal-hold
awareness. But it is **plan-only**: `_plan_intakes` counts rows and
`evidence_files_that_would_go`, and **no delete or unlink path exists anywhere in
the module**. There is also no TTL index on `intakes`.

**Net effect: uploaded evidence is retained indefinitely on disk and in Mongo.**
The policy is written and instrumented; the enforcement is not built.

---

## 2. Capability probe — `VERIFIED_FROM_ENVIRONMENT`

`python -m ocr_eval.probe` — read-only, installs nothing, does not touch PATH.
Actual output from this machine, 2026-09-12:

| Capability | Result |
|---|---|
| **Tesseract executable** | **UNAVAILABLE** — not on PATH, and not at any well-known install location |
| **Tesseract version** | n/a |
| **`eng` / `urd` / `osd` packs** | **all three missing** (no engine to query) |
| `pypdfium2` | **available**, 5.8.0 |
| `Pillow` | **available**, 10.4.0 |
| `pytesseract` | **NOT INSTALLED** (`ModuleNotFoundError`) |
| `pypdf` | available, 6.14.2 |
| `python-docx` | available, 1.2.0 |
| **Docker CLI** | **available**, 29.3.1 |
| **Docker daemon** | **UNAVAILABLE** (`exit_1`) — reported separately, on purpose |
| OS | Windows 11 (10.0.26200), AMD64 |
| Python | CPython 3.12.10 |

**Benchmark gate: `engine_ready_for_benchmark: false`**
Blockers: `tesseract binary not available on PATH`; `missing language packs: eng, urd, osd`.

Two notes worth acting on:

- **The raster half of an OCR pipeline is already installed.** `pypdfium2` +
  `Pillow` are present as transitive dependencies. Only the engine is missing.
- **CLI and daemon are deliberately separate rows.** Docker is installed and not
  running. Collapsing those into "docker: yes" is how a plan to ship OCR in a
  sidecar gets approved against a machine that cannot start one.

### Undeclared dependencies found while probing — `OWNER_INPUT_REQUIRED`

Not OCR, but directly load-bearing for the extraction being audited:

- **`python-docx` is imported by `document_tools` and is not in
  `requirements.txt`.** It resolves only as a transitive dependency of
  `docxtpl==0.18.0`. If docxtpl's dependencies change, DOCX extraction breaks in
  production with `ModuleNotFoundError`.
- **`pypdf` is unpinned** (as are `beautifulsoup4`, `faster-whisper`,
  `soundfile`). Everything else in the file is pinned. PDF extraction is the
  most-used path in this audit and it floats.
- `jsonschema` and `psutil` — used by the new harness — are likewise present but
  undeclared. The harness degrades safely without either (it reports the
  degradation rather than skipping validation), but Stage 2 should declare them.

I have **not** modified `requirements.txt`: changing dependency pinning is a
deployment decision, not an audit finding to self-approve.

---

## 3. Evaluation dataset contract

**Schema:** `backend/ocr_eval/ocr_evaluation_manifest.schema.json` (JSON Schema
2020-12). Every field you listed is required per fixture: id, relative path,
SHA-256, document type, language (`eng`/`urd`/`mixed`), script style, capture
(`searchable`/`scanned`/`photograph`), writing (`printed`/`handwritten`/`mixed`),
rotation category, expected page count, transcript path, critical tokens, and
per-fixture de-identification and consent confirmations.

Design decisions worth flagging:

- **Handwriting is declared, never inferred.** `writing: handwritten|mixed`
  *requires* `handwriting_policy: "unsupported_by_policy"`, enforced twice — by
  the schema's `if/then` rule and independently in code. Those fixtures are
  **skipped and counted**, not scored. Deriving handwriting from OCR confidence
  would let a bad guess reclassify the ground truth it is being judged against.
- **`script_style` distinguishes Naskh from Nastaliq.** Urdu legal documents
  appear in both and Tesseract handles them very differently. Without this field
  a bad aggregate is merely bad; with it, it is diagnosable.
- **Critical-token values must already be de-identified** — they are the one
  piece of fixture content the harness compares against, so a real name there
  would leak into every report.
- **Consent may carry `expires_utc`.** A run after expiry fails closed.
- Thresholds are **per `(language, capture)` slice**, not global. A global CER
  would be dominated by the largest slice and would hide Urdu photographs, which
  is precisely the slice this product depends on.

**Dataset status: `NOT_RUN_FIXTURES_MISSING`.**
No dataset has been supplied. Nothing was substituted — no internet files, no
generated scans, no repository PDFs. The target remains 30–50 representative
pages.

**Storage:** `backend/ocr_eval/fixtures/` with a nested allow-list `.gitignore`
(`*` then re-admit only `README.md` and `.gitignore`) plus a root `.gitignore`
rule. **Verified** by writing a probe file into the directory and confirming
`git check-ignore` catches it. No document content or transcript can be committed.

---

## 4. Benchmark harness

`backend/ocr_eval/` — **imports nothing from `app/`**, opens no database, makes no
provider calls.

| Module | Responsibility |
|---|---|
| `status.py` | The closed vocabulary of run outcomes and failure categories |
| `probe.py` | Read-only capability probe (§2) |
| `manifest.py` | Load, schema-validate, hash-verify. Fails closed |
| `metrics.py` | CER, WER, critical tokens, coverage. Pure functions |
| `memory.py` | Sampled process-tree RSS |
| `worker.py` | One fixture, one config, one **fresh child process** |
| `harness.py` | Gating, orchestration, aggregation, report hygiene |
| `thresholds.py` | Threshold **shape**, deliberately unset |

### Gating

A run proceeds only if **both** hold: the engine and every required language pack
are available, **and** a valid manifest resolves to fixtures that exist and hash
correctly. Otherwise it returns `NOT_RUN_*` with `results: null` and
`aggregates: null`.

`_assert_no_scores()` enforces this **structurally** on the way out and *raises*
rather than repairs. This is the specific defect the package exists to prevent: a
skipped run whose scores default to 0.0 and read as "OCR accuracy is zero".

### Metrics

- **CER / WER** — Levenshtein over characters / whitespace tokens.
- **Micro-averaged**, never the mean of per-page rates: `ErrorRate` keeps both
  `edits` and `reference_units` so corpus figures are summed edits over summed
  reference length. A macro-average weights a 20-character caption the same as a
  3 000-character judgment.
- **Empty reference → `rate: None`**, never 0.0. There is no error rate against
  nothing, and inventing one lets empty ground truth quietly improve an average.
- **Named normalisation policies** (`strict` / `standard` / `aggressive`),
  recorded beside every number. Urdu forces the issue: NFC vs NFD, Arabic-Indic
  vs ASCII digits, and Nastaliq zero-width joiners each move the score by whole
  points. The policy is explicit rather than a helpful default buried in a helper.
- **Coverage is separate from CER on purpose.** An engine returning nothing
  scores CER 1.0 / coverage 0.0; one returning a page of confident nonsense
  scores CER 1.0 / coverage ~1.0. One is plumbing, the other is the model. A
  single number cannot tell them apart.
- **Critical tokens are exact substring matches.** No fuzzy matching, no
  threshold — a threshold here is how `PPC 3O2` gets scored as a hit.

### Language ordering

`urd+eng` and `eng+urd` are **separate configurations** with separate results,
never averaged. The order sets which model leads and changes output materially on
mixed pages; averaging them would describe a configuration nobody would deploy.

### Memory — contract honoured exactly

- **`tracemalloc` is not used anywhere**, and a test enforces its absence. It
  measures Python allocations; Tesseract is a separate executable and pdfium and
  Pillow hold native buffers, so tracemalloc would report a small, stable,
  authoritative-looking fiction.
- Every fixture/configuration runs in a **fresh child process** — also protecting
  against native segfaults taking down the whole run, and against fixture 30
  being measured on a heap warmed by fixtures 1-29.
- RSS is sampled across the **complete process tree** at **100 ms**, reported
  as **`peak_sampled_process_tree_rss_bytes`**, carrying its interval,
  its implementation string, and the caveat that a spike shorter than the
  interval can be missed.
- **Never described as an exact OS peak.**
- Unobservable tree → `available: false` with a reason. **Never 0** — 0 bytes is a
  measurement, "could not look" is not.
- Timeouts terminate the **whole tree**. Killing only the direct child would
  leave Tesseract running as a grandchild, still burning CPU while the next
  fixture is "measured" on a contended machine.

### Thresholds — `OWNER_INPUT_REQUIRED`

`thresholds.py` ships the complete shape with every value `None` and
`frozen: false`. `evaluate()` returns `evaluated: False, passed: None` — **never
`passed: True`** — until a human sets values and flips the flag. An unconfigured
gate that reports success is worse than no gate: it emits a green tick meaning
"no thresholds were set", which nobody reads that way.

A threshold chosen before any measurement is a threshold fitted to whatever the
first run produced. Order: measure → decide → freeze in a separate reviewed
commit → only then wire into CI.

---

## 5. Harness correctness tests — `HARNESS_TEST_ONLY`

`backend/tests/test_ocr_readiness_harness.py` — **44 passed, 0 failed** (~40 s).
No database, no network, no product code.

All fifteen required behaviours are covered:

| # | Behaviour | Covered by |
|---|---|---|
| 1 | Missing engine → `NOT_RUN_ENGINE_UNAVAILABLE` | `test_a_missing_engine_produces_…` |
| 2 | Missing language packs are **named** | `test_missing_language_packs_are_named` |
| 3 | Missing dataset → `NOT_RUN_FIXTURES_MISSING` | `test_a_missing_dataset_produces_…` |
| 4 | Malformed manifest fails closed | `test_a_malformed_manifest_…`, `…violating_the_schema_…` |
| 5 | Missing transcript fails closed | `test_a_missing_transcript_fails_closed` |
| 6 | SHA-256 mismatch fails closed | `test_a_sha256_mismatch_fails_closed` |
| 7 | Handwriting unsupported by manifest policy | two tests — schema layer **and** code layer |
| 8 | Synthetic data labelled harness-only | three tests, incl. engine-driven labelling |
| 9 | Nothing emitted as measured after a skip | `test_no_result_is_emitted_as_measured_…` |
| 10 | CER/WER correct on known strings | six metric tests |
| 11 | Critical-token matching deterministic | three tests, incl. the `PPC 3O2` near-miss |
| 12 | Language orders stay separate | two tests |
| 13 | Timeout and child termination | two tests |
| 14 | Memory metric carries method + interval | three tests |
| 15 | No fixture text / PII / private paths in reports | three tests |

Two things I want to be explicit about, because they are the tests that would
otherwise be worth nothing:

- **Test 15 uses a realistic payload.** A fixture containing
  *"Zubaida Bibi of 44 Mall Road holds CNIC 35202-1234567-8"* is run end-to-end,
  and the serialised report is asserted to contain none of it — nor the temp
  path, nor the manifest filename.
- **The central invariant was mutation-tested.** I reintroduced the exact defect
  the package exists to prevent (skipped runs emitting `aggregates:
  {character_error_rate: {rate: 0.0}}` and dropped the structural guard).
  **Four tests failed.** Restored and re-verified identical, 44/44 green. A guard
  nobody has seen fail is not yet a guard.

`HARNESS_TEST_ONLY_NOT_ACCURACY_EVIDENCE` — the passthrough engine returns the
fixture's own text and never looks at a pixel. **These numbers say nothing about
OCR quality.** The label is applied to the *whole* run, never per fixture, because
a partially-labelled run still has a readable aggregate.

---

## 6. NOT_MEASURED

Nothing below has a value, and none of it should be reported as zero:

- OCR character error rate — **NOT_MEASURED**
- OCR word error rate — **NOT_MEASURED**
- Critical-token exact match — **NOT_MEASURED**
- Extraction coverage on scans/photos — **NOT_MEASURED**
- Per-page and per-file wall-clock — **NOT_MEASURED**
- `peak_sampled_process_tree_rss_bytes` under OCR load — **NOT_MEASURED**
- Urdu Naskh vs Nastaliq difference — **NOT_MEASURED**
- `urd+eng` vs `eng+urd` difference — **NOT_MEASURED**

Reason for all of them: no engine (`NOT_RUN_ENGINE_UNAVAILABLE`) **and** no
fixtures (`NOT_RUN_FIXTURES_MISSING`).

---

## 7. OWNER_INPUT_REQUIRED

1. **De-identified fixtures.** 30–50 representative pages with hand-verified
   transcripts. The mix decides what the number means — my suggestion: ~40%
   Urdu scans, ~25% mixed-language, ~20% photographs, ~15% English. Include
   deliberately hard pages; a corpus of clean flatbed scans produces a flattering
   number that predicts nothing about a phone photo of an FIR.
2. **Authorisation to install Tesseract** + `eng`, `urd`, `osd` packs, and a
   decision on where: this Windows box, a Docker sidecar (CLI present, **daemon
   currently stopped**), or a managed service. A managed OCR service means
   evidence leaves your infrastructure — that is a client-confidentiality
   decision, not an engineering one.
3. **Transcription effort.** Hand-transcribing 30–50 pages of Urdu legal text is
   the real cost of this project, and it cannot be delegated to an OCR engine
   without destroying the ground truth.
4. **Retention decision.** §1.8: the 365-day policy exists and enforces nothing.
   OCR makes this sharper — extracted text is more sensitive than the scan,
   because it is searchable.
5. **Dependency decisions.** Pin `pypdf`; declare `python-docx` (§2).

---

## 8. PROPOSED_NOT_IMPLEMENTED — Stage 2 architecture

**No code was written for any of this.** Design only, for review.

### 8.1 Out of the request path

OCR must not run inside `convert_to_case` (§1.7). Proposed:

```
upload ──▶ evidence stored, status: pending_extraction
              │
              ▼
       extraction queue  (Redis Streams — already in the stack)
              │
              ▼
    OCR worker (separate process; own CPU budget, own timeout)
              │
              ▼
   evidence.extraction = { engine, version, config, text, confidence, status }
              │
              ▼
        conversion reads whatever is ready, and says what is not
```

Conversion never waits. An intake converted before extraction finishes reports
`pending` for that file — which the pipeline already models, since
`omitted_limit` and `unreadable` are existing statuses the prompt handles.

### 8.2 Pipeline per file

`pdfium` rasterise (300 dpi) → `osd` orientation detect → deskew → Tesseract
`urd+eng` → confidence capture. Rotation is the highest-value early step: a
sideways phone photo is the common real case, and recognition on an unrotated
page is near-worthless.

### 8.3 Provenance to add

Per §1.8, extraction records would carry `engine`, `engine_version`, `languages`,
`dpi`, `psm`, `oem`, `duration_ms`, `mean_confidence`. This is what makes a
result reproducible and what lets you find every case that relied on a version
later found broken.

### 8.4 Confidence is a routing signal, never a truth claim

Low confidence should route a file to "ask the client to confirm these details",
never to "the FIR says X, probably". A legal product that narrates a low-confidence
OCR guess as fact is worse than one that reads nothing — which is exactly why
§1.3's current honest-failure behaviour must be preserved through this change.

### 8.5 Hardening noted, not fixed

§1.4 (`.doc` accepted-unreadable) and §1.5 (ZIP-as-DOCX) are **reported, not
fixed**, per this task's constraints. Both should be resolved before an OCR
worker starts unpacking these files. Minimal fixes: validate the ZIP central
directory contains `[Content_Types].xml` before claiming DOCX; either reject
`.doc` at upload with a clear message or add an extractor for it.

---

## 9. Verification summary

| Check | Result |
|---|---|
| `pytest tests/test_ocr_readiness_harness.py` | **44 passed, 0 failed** |
| Mutation check on the core invariant | **4 tests failed as designed**, restored, re-verified |
| `python -m ocr_eval.probe` | exit 0, engine correctly reported unavailable |
| Part 1 claims re-confirmed by execution | ZIP→DOCX, `.doc`, image, scanned-PDF all reproduced |
| `git check-ignore` on fixtures dir | fixture content correctly ignored |
| Product code changed | **none** |
| Committed | **nothing** |

**The full backend suite was not run, deliberately.** Nothing under `app/` was
touched: this work adds `backend/ocr_eval/` (which imports no product code), one
test file, one schema, one report, and a `.gitignore` rule. Running 4 600 tests
to prove that an isolated new package did not affect them would not be evidence —
`ocr_eval` is not importable from `app/`, which is the property that matters, and
it is structural rather than something a test run demonstrates.

---

## 10. Stop point

This stage is complete. The next stage requires, in order:

1. **owner-provided de-identified fixtures** with hand-verified transcripts;
2. **authorisation to install and use an OCR engine**, and a decision on where it runs;
3. **review of the measured baseline** — before any threshold is chosen, and
   before any of it reaches the product.

Until (1) and (2) exist, the harness will keep returning
`NOT_RUN_ENGINE_UNAVAILABLE` / `NOT_RUN_FIXTURES_MISSING`, which is the correct
and intended answer — not a failure to be worked around.
