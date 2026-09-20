# Intake Evidence: Extraction Hardening & OCR Plan

**Date:** 2026-09-12
**Companion to:** `OCR_READINESS_REPORT.md` (current-state audit + benchmark harness)
**Status:** plan only. Nothing in this document has been implemented.

**One-line summary:** the product's real defect is that **partially extracted
evidence is presented as fully read**. That is fixable with no OCR at all, and it
is Milestone 1. OCR is a separately measured addition, not a prerequisite.

---

## 1. Verified defect inventory

Every row was reproduced by executing the real functions. None is inferred from
reading alone.

| # | Defect | Evidence |
|---|---|---|
| 1 | **Partial PDF extraction reported as complete.** 3-page PDF, 1 typed cover + 2 scans → returns the cover text, `error: None`, status `readable` | reproduced |
| 2 | **Mixed page reported as read.** One page with a text header over a scanned body → `'IN THE COURT OF THE CIVIL JUDGE, LAHORE'` (39 chars), status `readable`; the body contributed nothing | reproduced |
| 3 | **Blank page is indistinguishable from a scan.** A genuinely empty page produces the same "no readable text layer" signal as an image-only page | reproduced |
| 4 | **DOCX tables dropped.** Agreement with amount + due date in a table → extractor returns only `'Agreement between the parties.'`; `PKR 4,500,000` and `12 March 2026` both absent, file marked `readable` | reproduced |
| 5 | **DOCX nested tables lost.** `.paragraphs` yields `['FIRST paragraph', 'LAST paragraph']`; a single-level cell walk yields `['OUTER cell\n']` — the nested cell is in neither | reproduced |
| 6 | **Arbitrary ZIP accepted as DOCX.** `PK\x03\x04` is ZIP magic; a plain zip is stored `.docx` and fails with a `KeyError` surfaced to the model as `"Could not read the file: …"` | reproduced |
| 7 | **`.doc` accepted but unreadable.** OLE2 magic is allow-listed; extractor refuses `.doc` | reproduced |
| 8 | **No extraction timeout, no page cap, shared thread pool.** `asyncio.to_thread` uses the default executor — `min(32, cpu+4)` = **12 workers on this 8-CPU box**, shared process-wide; conversion awaits it inline | verified |
| 9 | **Benchmark: token substring match.** `'379'` matches inside `'1379'` | reproduced |
| 10 | **Benchmark: page accounting.** Worker renders `max_pages` but reports the PDF's total and `ok=True`; `seconds_per_page` divides by the wrong denominator | reproduced |
| 11 | **Benchmark: unbounded render.** All selected pages rendered before OCR. One letter page at 300 dpi = **24 MB** uncompressed; the `max_pages=50` default implies a **~1.2 GB** ceiling from a 10 MB upload | computed |
| 12 | **Benchmark: thresholds never see metrics.** `evaluate({})` at both call sites; `slices` defined and never read | verified |

Defects 1–8 are in product code. Defects 9–12 are in the benchmark harness added
by the readiness task.

---

## 2. Review corrections — accepted

The following corrections to the previous draft are accepted and are reflected
throughout this plan.

**2.1 A warning does not eliminate the risk.** Disclosure must reach the
**generated analysis**, not only the upload screen. And user confirmation proves
identity of a file, never accuracy of text extracted from it. *Superseded: the
earlier framing that user confirmation makes OCR output safe.*

**2.2 Page-level reporting needs an explicit `uncertain` state.** Defects 2 and 3
above are the proof: a binary read/scan label per page reproduces the document-level
bug one level down. A page with text may still be mostly unread; a page without
text may simply be blank. PDFs carry no reliable semantic structure to tell these
apart. **Required vocabulary:** `text_found` · `no_text_found` ·
`partial_or_uncertain` — with no claim of scan detection.

**2.3 The Urdu spike is exploratory only.** It is retained, with its power stated
honestly: **it can produce a "stop" signal, never a "go" signal.** Five pages can
expose an obvious failure; they cannot establish Urdu support. The claim that
Tesseract's Urdu data is predominantly Naskh-trained is **unverified** and is
recorded here as an assumption to test, not a finding.

**2.4 Duplicate-work protection stays in Milestone 3.** *Superseded: the earlier
claim that "no retry means nothing to deduplicate."* That was wrong — double-clicks,
refreshes and network retries already exist in this product today, independent of
any retry feature. No queue platform is needed; an in-flight claim keyed on
`(file_id, content_hash)` is sufficient, and mirrors the existing
`intake_repo.claim_conversion` pattern already in the codebase.

**2.5 Process startup time is user-visible latency, not a measurement bug.**
*Superseded: the earlier framing that spawn time should be excluded.* Correct
treatment is decomposition — report **end-to-end**, **render** and **OCR** time
separately, with **pages processed** as the denominator.

**2.6 A dirty worktree is not proof of concurrent editing, and no cleanup is
required.** *Superseded: the earlier recommendation to consolidate the repo before
starting.* Recorded evidence, for the file only: files already read in-session
changed underneath the session (`confirm_case` gained a parameter; `intake_repo`
gained methods), with mtimes as corroboration. **Operational rule adopted:
inventory existing changes and preserve them. Do not commit, reset or clean.**

---

## 3. The three milestones

| Milestone | Deliverable | Completion requirement |
|---|---|---|
| **1. Safe, honest existing extraction** | Upload validation, DOCX tables, bounded native extraction, partial-result reporting | Omitted content cannot silently appear fully analysed |
| **2. Trustworthy OCR evaluation** | Corrected harness, feasibility spike, representative benchmark | Results support precisely defined language/document categories |
| **3. Optional OCR integration** | Local worker, review flow, persistent status, disabled feature flag | Safe cancellation, authorization, refresh and failure behaviour verified |

Milestone 1 delivers user value on its own, needs no OCR engine, and makes no
provider calls. **Milestones 2 and 3 are optional continuations, not commitments.**

---

## 4. Milestone 1 — scope

### 4.1 Inspect first

Inventory current changes and every caller of the shared document reader
(`document_tools._read_file` / `_extract_text_sync`). Preserve unrelated edits.
Do not infer concurrent editing from timestamps; do not commit, reset or clean.

### 4.2 Implement

1. **Structured extraction result**, backward compatible, shared by intake and
   the document tools. Three *independent* axes, never collapsed:
   - processing **outcome** (succeeded / failed / refused)
   - extraction **completeness** (complete / partial / uncertain / none)
   - **prompt truncation** (whether the analysis saw all extracted text)

   These are orthogonal: text can extract completely and still be truncated out
   of the prompt, and that is a different disclosure.

2. **PDF page accounting.** Record `pages_total` (where obtainable),
   `pages_attempted`, `pages_with_text`, `pages_failed`, `pages_skipped`.
   **Non-empty text must not imply complete extraction.** Use
   `partial_or_uncertain` for mixed content; claim no scan detection (§2.2).

3. **DOCX paragraphs *and* tables, in document order.** Note the trap, verified
   in §1: `.paragraphs` excludes tables *and loses order* — document order is not
   recoverable from `.paragraphs` + `.tables` and requires walking the body XML
   children. Recursion into nested tables is required (they are lost otherwise);
   the duplication hazard belongs to the *fix*, so nested and merged tables need
   explicit tests that values appear exactly once. Disclose unsupported content
   (headers, footnotes, text boxes) rather than implying full coverage.

4. **Bounded DOCX package validation** before parsing: inspect the ZIP central
   directory, require a real Word package structure, constrain entry count,
   expanded bytes and compression ratio, reject suspicious entries. Do not
   extract to disk; do not follow external resources.

5. **`.doc` guidance.** Clear message asking for DOCX/PDF. **Existing stored
   evidence and its download access are preserved** — never silently discarded.

6. **Bound native extraction.** Concrete, tested limits on pages, archive
   expansion, time and concurrency. A timeout around `asyncio.to_thread` is
   **insufficient** — it abandons the wait while the work continues. Use a
   killable subprocess where necessary and verify cleanup. Concurrency note from
   §1: the default pool is **12 workers, shared process-wide**, so extraction
   needs its own bound or it starves unrelated `to_thread` callers.

7. **Stable, safe error codes** replacing raw parser exceptions. No document
   content, filesystem paths or secrets in exposed errors.

8. **Carry limitations end to end** — API responses, restored intake state, UI,
   and **analysis input**. Distinguish extraction truncation from prompt-budget
   omission. Verify what provenance actually persists.

   *Head start:* the channel already exists. `AgentState.intake_evidence_status`
   and `analysis["evidence_extraction"]` already carry per-file status through
   the graph and into provenance. The work is making it **page-level** and making
   the **prompt** consume it — not building a new pathway.

### 4.3 Acceptance tests

Typed cover + scanned pages · readable header + scanned body · blank pages ·
DOCX table amounts/dates · nested and merged tables (no duplication) · forged
DOCX ZIPs · malformed and encrypted files · page and time limits · prompt
truncation · refresh restoration · cross-user access · **and unchanged behaviour
for ordinary readable files**.

Run focused backend/frontend tests, affected shared-reader tests, the intake
journey, the frontend build, and the full regression suites, using the existing
isolated test resources (`_isolate_test_database`, `_isolate_upload_root`).
Report exact results and any skipped checks.

### 4.4 Constraints

No provider calls · no OCR installation or integration · no production-data
changes · no corpus changes · no unrelated features · no commits. **No mandatory
OCR-confirmation workflow in this milestone.** Stop after the implementation
report and state remaining limitations.

---

## 5. Additions beyond the review

Three items not covered by any prior draft.

### 5.1 Past analyses are already affected — identify them *(highest value)*

Milestone 1 fixes the future. It says nothing about cases **already decided on
partially-extracted evidence and labelled `readable`.** For a legal product that
is the more uncomfortable half.

These are identifiable without guesswork: intakes holding PDF or DOCX evidence
whose recorded `evidence_extraction` status is `readable`. Re-running the new
page-aware extractor over stored files tells you which produced partial results.

Proposed: a **read-only census** at the end of Milestone 1 — count and list
affected cases, change nothing. Whether to notify anyone is the owner's call, and
it cannot be made without the number. **This is a read-only report, not a
migration.**

### 5.2 Benchmark metric naming

`extraction_coverage` measures output **length ratio**, not content completeness —
its own docstring said so while its name did not. Rename to
`output_length_ratio`, and add a genuinely distinct
`page_coverage = pages_with_text / pages_total`. The second metric is the one
that would have caught defect 1 in production.

### 5.3 Keep failure rates beside accuracy — including in Milestone 1

Accuracy over successfully-processed pages is not reliability. A configuration
that fails 40% of files and reads the rest perfectly is not a good configuration.
This applies to the plain extractor too, not only to OCR.

---

## 6. Milestone 2 — sequencing note

Fix the harness (defects 9–12) **before** collecting acceptance numbers, then:

1. **Feasibility spike** — engine installed, ~5 throwaway pages, no transcripts.
   Stop-signal only (§2.3).
2. **Then** transcription. Hand-transcribing 30–50 pages of Urdu legal text is
   the single largest cost in this project and must not be spent before the spike.
3. Keep deterministic metric tests in CI; run real accuracy checks in a
   controlled environment with **fixed engine and language-data versions**, and
   report **sample size and uncertainty**.
4. Small datasets do **not** justify abandoning acceptance criteria — they
   justify stating confidence honestly and choosing where the criterion is
   enforced.
5. Report **English, Urdu and mixed separately**. Compare language-order
   configurations rather than assuming order is irrelevant.
6. If Urdu quality is inadequate, keep the category **explicitly unsupported**.
   Do not lower the standard to enable it.

---

## 7. Milestone 3 — integration shape

One bounded local worker. Not a microservice.

- Killable subprocess, timeout, resource limits, verified cleanup.
- Jobs bound to the authorised evidence file **and its content hash**.
- Duplicate-request protection (§2.4).
- No publishing results after the file is deleted or replaced.
- Original file always preserved.
- Page-level status plus engine and configuration recorded.
- UI states: *Processing* · *Partially read* · *Could not read*.
- No silent analysis of incomplete evidence — retry, replace, or continue with
  the omissions **stated in the analysis** (§2.1).

Four things kept distinct in storage and in the UI:

| Machine-extracted text | User corrections | Content included in analysis | Content omitted or awaiting review |
|---|---|---|---|

A confirmation binds to the **exact file and extraction version**. Replacing
either invalidates it.

**OCR confidence must never become legal-answer confidence.**

---

## 8. Owner decisions still required

1. **Fixture set** — 30–50 de-identified pages with hand-verified transcripts,
   and who transcribes them.
2. **Engine authorisation and location** — local install, Docker sidecar (CLI
   present, daemon currently stopped), or managed service. A managed service
   means evidence leaves your infrastructure: a confidentiality decision.
3. **Retention** — `retention.py` declares 365 days for intake evidence and is
   **plan-only, with no delete path**. OCR sharpens this: extracted text is more
   sensitive than the scan because it is searchable.
4. **Dependencies** — pin `pypdf`; declare `python-docx` (imported by
   `document_tools`, currently only a transitive dependency of `docxtpl`).
5. **§5.1 census** — whether to run it, and what to do with the result.

---

## 9. Out of scope

OCR installation · OCR integration · provider calls · production-data changes ·
corpus, retrieval, prompt, cache, model, migration or DOCUMENTS_V2 changes ·
commits · any mandatory confirmation workflow in Milestone 1.
