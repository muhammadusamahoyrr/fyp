# Document Analyzer — Research & Design Plan (v3.5)

**Date:** 2026-09-30 · **v3.4** incorporates six reviews (changelog in §12). **Implementation-ready for P1.**
**Status:** plan only. Nothing here is implemented.
**Scope:** the client-side Document Analyzer (`frontend/src/components/client/documents/DocsAnalyzer.jsx`). Today it runs a hard-coded sample and refuses real files.

**What this is:** an **evidence-grounded review assistant**, not a deterministic compliance verifier.
- Every finding is anchored to exact, server-derived spans of the user's own document.
- Legal checks come from a versioned, lawyer-signed playbook and report tri-state results.
- The LLM explains risk only. It never quotes, never cites law, and never decides that a clause is absent.
- We require lawyer review because the evidence does not support autonomous legal conclusions.

---

## 1. Research

### 1.1 Industry pattern

This section is *synthesised from public product descriptions* of Kira, Luminance, Spellbook, LegalFly and Harvey, not from vendor technical documentation.

| Stage | What it does |
|---|---|
| 1. Ingest + OCR | File → text, split into headings, sections and schedules |
| 2. Clause extraction & classification | Provisions are labelled even when untitled (Kira advertises 1,400+ clause models) |
| 3. Playbook comparison | Clauses are compared to a written standard: deviations, one-sided terms, absent provisions (Spellbook advertises 2,300+ contract-type playbooks) |
| 4. LLM contextual analysis | Explains why a clause matters, drafts a fix |
| 5. Report | Prioritised issues, each pointing to the triggering clause |
| 6. Human review | A lawyer accepts or rejects each item |

Two ideas we adopt:
- **Consensus** among models (Luminance describes a "panel of judges"). This is an optional later addition.
- **Traceability.** A finding that cannot be traced to a sentence cannot be supervised.

### 1.2 Evidence

- **ContractEval (2025),** 41 CUAD risk categories, 19 LLMs:
  - The GPT-4.1 family scored approximately **0.64 F1** (4.1 mini 0.644, 4.1 0.641). The best small open model, Qwen3-8B, scored ~0.53.
  - Some small models falsely answered "no related clause" 21–31% of the time (Qwen3-8B AWQ 30.6%, LLaMA-3.1-8B 21.4%).
  - Thinking mode and quantisation produced **mixed results and often reduced correctness**. Thinking raised Qwen3-8B slightly (0.530 → 0.540) and hurt several other variants.
  - → Absence claims are the weakest LLM output.
- **Stanford RegLab (2024):** RAG legal research tools still hallucinated on 17–33% of queries.
  - → Retrieval does not make legal claims safe, so human review stays mandatory.
- **Lost in the Middle (TACL 2024):** accuracy degrades for evidence placed mid-context.
  - → Review in small batches, with the batch size **measured**, not assumed.
- **CUAD (NeurIPS 2021):** 510 US commercial contracts.
  - → Used **only** to evaluate clause location. It is not a source of Pakistani legal requirements.

### 1.3 Reference product

pakistanlawbot.com publicly promises a "clause-by-clause review with risks flagged" and publishes no method.

---

## 2. Reuse map

| Need | Existing code | Verdict |
|---|---|---|
| Upload validation (magic bytes, refuses `.doc`/fake DOCX) | intake evidence upload (`routes/intake.py`) | Reuse after extracting a shared helper. Add DOCX bomb limits (§4.10) |
| Honest per-page extraction, DOCX tables | `app/ai/extraction.py` | Reuse |
| Killable child process with deadlines | `extraction_runner.py`, `extraction_worker.py` | Reuse |
| English OCR, output unconfirmed, Urdu refused | `ocr.py`, `ocr_routing.py` | Reuse. Unconfirmed OCR text never reaches a prompt |
| Citation existence + corpus density | `citation_verification.py`, `corpus_index.py` | Reuse only for "Source located in library" |
| Cleaning model output that doesn't fit the schema | `_coerce_model_fields` pattern | Reuse the pattern |
| Fenced promotion (owner + fence + live lease) | `revision_repo.promote` / `heartbeat` / `steal_expired` | **Reuse the pattern** for every stage commit (§5) |
| Original file storage | `artifact_store.py` handles revision PDFs only | **New** `analysis_file_store` |
| Job lease | `extraction_lease.py` is per-process, in memory | **New** durable Mongo lease |
| LLM calls | `app/ai/llm.py` falls back across providers | **New pinned client** that bypasses the chain (§7) |

## 3. Constraints

1. **The corpus has no contract/property statutes yet.** P2 ingests PRPA 2009, the Registration Act 1908 and the TPA 1882.
2. **CPC Order rules are mislabelled as sections,** so the analyzer never cites the CPC.
3. **No GPU,** so one pinned cloud provider is needed (§7).
4. **OCR is English-only and unconfirmed.** Urdu is refused in v1 and the screen says so.
5. **Async is for reliability:** reload, restart and cancel. It is not needed because of the proxy, whose timeout is now 180s.
6. **There is no case-law corpus,** so Precedents stays hidden.

---

## 4. Design

### 4.1 Who decides what

| Question | Decided by |
|---|---|
| Document type, province | rules propose, **user confirms** (per context version) |
| User's side, depth, focus | **user**, per run |
| Legally decisive key terms | candidates with evidence spans, **user confirms** (per context version) |
| Whether a legal requirement applies / whether required content is present | playbook rule → tri-state |
| Meaning for this user, suggested fix | LLM |
| Evidence text | LLM gives sentence IDs, the **server** derives the text |
| Final call on each finding | a lawyer, via review events (§6) |

### 4.2 Run state machine

```
queued_extract → extracting → needs_ocr_confirmation* → queued_segmentation → segmenting
  → needs_document_confirmation → queued_terms → extracting_terms → needs_terms_confirmation
  → queued_analysis → analyzing → done
Any state → failed | cancelled | superseded
```
`*` only when a page used OCR. Otherwise extracting goes straight to queued_segmentation.

**Rules:**
- `queued_*` states are claimable by workers. Active states (`extracting`, `segmenting`, …) hold a lease. `needs_*` states are human pauses.
- **Entering a `needs_*` state releases the lease** (`lease_owner = null`) and increments `state_version`. A worker never holds a lease while waiting for a person.
- Confirmation endpoints are CAS updates on `{run_id, status: needs_X, state_version: expected}`. On success they write the confirmation and move the run to the next `queued_*` state in the same update.
- A second confirmation with a stale `state_version` gets 409.
- **A non-tenancy document skips the terms steps.** Confirming `document_type: other` moves the run from `needs_document_confirmation` straight to `queued_analysis`: there are no decisive terms to confirm for it, and no playbook applies to it in this version. *(Implemented in slice 3.)*
- **Re-analysis with a new side, depth or focus** creates a new run starting at `queued_analysis` on the same confirmed context version. It does not repeat extraction or confirmations.
- **An OCR correction** creates a new **text version**. **A correction of type, province or terms** creates a new **context version** on the same text (the text did not change). Either way, runs on the old version get lifecycle metadata `superseded_at`. **Their generated payload is never modified**: superseded is a label on the run, not an edit of its findings.

### 4.3 Canonical text, storage, anchoring

The canonical text is stored in separate collections from day one, so no single Mongo document approaches the 16 MB limit.

```
analysis_text_versions   _id, source_id, version, text_hash, char_count, blob_key (text file, encrypted at rest),
                         origin (native|ocr_confirmed), created_at                      # IMMUTABLE text only
analysis_context_versions _id, text_version_id, version, jurisdiction, document_type,
                         confirmed_key_terms {term: {value, sentence_ids}}, confirmed_at {document, terms}
analysis_runs            ..., context_version_id, side, depth, focus                     # per run
analysis_text_pages      text_version_id, page, start, end, coverage (text_found|no_text_found|partial_or_uncertain), ocr
analysis_clauses         text_version_id, clause_id, number, heading, start, end
analysis_sentences       text_version_id, sentence_id, clause_id, start, end, page_spans [{page, start, end}]
```

- The canonical text itself is a **blob** in `analysis_file_store`. Mongo holds only offsets and maps.
- A sentence that crosses a PDF page boundary has **multiple `page_spans`**.
- **Evidence** is `(text_version_id, sentence_ids)`. The server derives `text[start:end]` and stores it with its offsets and `evidence_hash`. The model never produces quote text.
- **Highlighting (v1) happens in a canonical-text viewer.** Offsets cannot reliably highlight the original PDF without word bounding boxes, and the UI must not pretend they can.
- **Segmentation is deterministic:** numbering patterns, with paragraphs as the fallback.

### 4.4 Key terms

- Candidates come from regex and the LLM. Each carries sentence IDs, or it is dropped and counted.
- Values are normalised by code.
- **Decisive terms** (term length, year-to-year, rent period, province) are confirmed by the user on the `needs_terms_confirmation` screen, each shown next to its evidence sentence.
- Confirmed terms are stored on the **context version** (§4.3), not on the text or the source.

### 4.5 Playbook: versioned, safe DSL, tri-state

- The playbook is one YAML per (type, jurisdiction).
- It carries its **content hash**, version and `sign_off {reviewer_user_id (authenticated account), role, date, approved_hash}`.
- An unsigned playbook runs in tests only.
- **Conditions use a declarative DSL** (`eq ne gt lt in all any not exists`) over confirmed context. **Operands are typed:** `{field: jurisdiction}` or `{value: punjab}`, never a bare string whose meaning is guessed.
  - At load, the playbook is parsed into a validated AST. Load fails on: an unknown operator, a wrong arity (`eq/gt/lt/ne` take 2, `not` 1, `all/any` ≥ 1), a field not in the declared context schema, or a literal whose type doesn't match the field (e.g. `gt` on a string).
  - No `eval`.
  - The draft rules below are shown in short form for readability; the real files use the typed form, e.g. `eq: [{field: jurisdiction}, {value: punjab}]`.

**Output model: check outcomes are separate from risk findings.**

```
kind          legal_check | model_risk | reminder
check_result  present | not_located | unable_to_determine | not_applicable | null   (legal_check only)
severity      high | medium | low | null
```

| check_result | UI wording |
|---|---|
| `present` | "Found" + highlighted text |
| `not_located` | **"Not located automatically"**. "Missing" appears only after a lawyer confirms it (§6) |
| `unable_to_determine` | "Could not check" + reason |
| `not_applicable` | collapsed |

- A `reminder` is a statement that cannot be checked from the document. Example: "The Act requires presentation to the Rent Registrar. Check whether this was done." It never shows as found or not found.
- Locating content for `present` uses headings and keywords first, then an LLM locator that must return sentence IDs. A locator "no" becomes `not_located`.

**Draft rules (for the lawyer to correct):**

```yaml
- id: prpa_s5_rent_registrar
  kind: reminder                          # independent of duration; not a presence check
  authority: {statute: "Punjab Rented Premises Act 2009", section: "5"}
  applies_if: {all: [{eq: [jurisdiction, punjab]}, {eq: [document_type, tenancy]}]}

- id: prpa_s6_contents                    # one legal_check per item (a)–(g)
  kind: legal_check
  authority: {statute: "Punjab Rented Premises Act 2009", section: "6"}
  note: 'Section says "as far as possible" — advisory severity.'

- id: registration_s17_lease              # three limbs, each its own legal_check
  kind: legal_check
  authority: [{statute: "Registration Act 1908", section: "17(1)(d)"},
              {statute: "Transfer of Property Act 1882", section: "107"}]
  limbs:
    - {id: year_to_year,     applies_if: {eq: [tenancy_year_to_year, true]}}
    - {id: term_over_1_year, applies_if: {gt: [term_months, 12]}}
    - {id: yearly_rent,      applies_if: {eq: [rent_period, yearly]}}
  pending_lawyer_input: "applicable provincial exemptions/amendments"
```

### 4.5a Playbook framework and scope (P2A / P2B)

The analyzer is not limited to tenancies. Every analysis runs through one
**playbook engine**, and every result says which kind of review produced it.

**Packs.** A pack is a versioned YAML file of checks:

| Pack | Kind | Runs when | Approval needed |
|---|---|---|---|
| `general` | general checks | every document | none: it makes no legal claim |
| `tenancy_punjab` | legal checks + reminders | confirmed `tenancy` + `punjab` | **signed hash**, lawyer qualified in Punjab tenancy law |
| `nda` | legal checks | confirmed `nda` | signed hash, relevant lawyer |
| `employment` | legal checks | confirmed `employment` | signed hash, relevant lawyer |

**Scope labels, on every result:**

| Label | Meaning |
|---|---|
| `General document review` | A drafting-completeness check (are parties named, is there a date, a signature block, a termination clause...). Not a legal requirement and never phrased as one. |
| `Legal playbook applied` | The result of an APPROVED legal pack's rule. |
| `Applicability requires lawyer review` | Always shown with a legal result: the rule was applied mechanically to confirmed terms. |

**Approval is bound to a qualification, not just to "a verified lawyer"
(P2B).** Each legal pack names its `required_qualification`
(`pk.punjab.tenancy`, `pk.contract.nda`, `pk.employment`). An admin grants a
qualification to a verified lawyer with a stated basis
(`analysis_reviewer_qualifications`); only a holder of the pack's exact
qualification can approve it, and only as themselves. Revoking a
qualification deactivates the approvals its holder gave under it. Every
grant, revocation and approval writes an append-only row in
`analysis_approval_audit` in the same transaction as the change.
Endpoints: `GET /playbooks`, `GET /playbooks/{id}` (the exact text and hash
to review), `POST /playbooks/{id}/approvals`, `POST
/playbook-approvals/{id}/revoke`, `POST /reviewer-qualifications`, `POST
/reviewer-qualifications/{id}/revoke`, `GET /approval-audit`.

**Approval is data, not a flag.** `analysis_playbook_approvals` holds
`{pack_id, version, content_hash, qualification, reviewer_user_id, reviewer_role, approved_at, active}`.
A legal pack runs only if an approval exists for its **exact** content
hash; editing a single character of the pack changes the hash and
withdraws it. An applicable but unapproved pack is reported as
**"not applied — awaiting lawyer approval"**, never silently skipped and
never run.

**Unsupported documents** get the general pack only, labelled
`General document review`.

**Phases.**
- **P2A:** the engine (typed DSL with three-valued logic, so a missing term
  yields `unable_to_determine`; YAML loader with schema validation and a
  content hash; locators that return sentence ids; findings stored as run
  outputs keyed `(run_id, stage, fence, ordinal)`), the `general` pack, the
  approvals mechanism, the analysis stage that takes `queued_analysis` to
  `done`, and a report endpoint with server-cut evidence.
- **P2B:** the `tenancy_punjab`, `nda` and `employment` packs as content.
  They can be built and tested in code, but **not merged or released, nor
  shown as legally approved**, until a qualified lawyer approves each signed
  hash.

**Authority library (added after P2B).** Citations do NOT come from the
chat corpus, whose section labels are unreliable (TPA s.107's only "107"
chunk is a footnote; the Registration and Contract Acts are absent).
`backend/app/services/analyzer/authority_library.yaml` holds the exact text
of every cited provision, cut by explicit headings from pinned official PDFs
(Punjab Code; Pakistan Code) by `scripts/build_analyzer_authorities.py`,
which refuses if a file's SHA-256 changes. Rules:
- a legal pack whose citation does not resolve does not load;
- an approval binds the pack hash AND `authorities_hash` (the cited
  provisions' text hashes); a change to either stops the pack, and a
  re-approval supersedes the stale one in the same, audited transaction;
- each finding stores the resolved source (publisher, URL, file hash, pages,
  text hash) at analysis time, so a report keeps saying what was applied;
- the reviewer reads the cited official text via `GET /playbooks/{id}`
  (`cited_provisions`); the live drift check is the opt-in `network` test.

### 4.6 LLM explanation layer

- **Input:** clause batches (the size is measured), the run's user side, and sentences with their IDs.
- **Document text is untrusted data:**
  - It goes in a delimited data block.
  - The system prompt says to ignore instructions inside the document.
  - The output is schema-validated.
- **Output per item:** `clause_id`, `sentence_ids[]`, `issue`, `severity`, `why_it_matters`, `suggested_fix`. There are **no quote or citation fields**. An item whose free text contains a citation, or that references unknown IDs, is dropped and counted.
- **Citation detector** (so the drop rule is testable): reuse the statute-citation parser already used by `citation_verification`, plus these patterns, case-insensitive:
  - `\b(s|sec|section|art|article|order|rule)\.?\s*\d+[A-Z]?(\(\d+\))*`
  - `\b\d{4}\s+(SCMR|PLD|CLC|YLR|MLD|PCrLJ)\b` (case reporters)
  - `\bAct,?\s+\d{4}\b` and `\bOrdinance,?\s+\d{4}\b`

  A fixture set of positive and negative strings is the test.
- It produces `kind: model_risk` findings, merged per clause with legal checks.

### 4.7 Honest source labels

- `Source located in library`
- `Source not available in library`
- `Currency checked as of <date>`, only from the playbook sign-off
- `Applicability requires lawyer review`, **always** on legal checks

### 4.8 Upload limits (per format)

| Format | Limits |
|---|---|
| PDF | ≤ 10 MB, ≤ 40 pages |
| DOCX | ≤ 10 MB compressed. **ZIP bomb guard:** total uncompressed ≤ 50 MB, per-entry ≤ 20 MB, compression ratio ≤ 100:1, ≤ 1,000 entries. `word/document.xml` ≤ 5 M chars. ≤ 200 tables. Nesting depth bounded |
| Image (JPG/PNG) | ≤ 10 MB, ≤ 25 MP, OCR path only |
| `.doc`, others | **refused** with a clear message |
| All formats | canonical text ≤ 300,000 characters. Over that → refused, "document too long for this version" |

The frontend's advertised formats and limits must match this table exactly (P-1 removes the current "DOC · photo · 50 MB" copy until P1 lands).

---

## 5. Execution semantics (durable Mongo worker)

**Jobs are at-least-once.** A lease does not give exactly-once execution. A worker can finish an expensive LLM call after its lease was stolen. So **results are published only through a fenced commit**. A stale worker may waste work but can never publish.

**Every stage commit is a Mongo transaction.** One update cannot filter two collections, so the source check and the run commit share a transaction:

```
with session.start_transaction():
    src = sources.find_one_and_update({_id: source_id, deleted_at: null, generation: g},
                                      {$inc: {commit_seq: 1}})                      # a WRITE; else abort
    run = runs.find_one_and_update(
        {_id: run_id, status: <expected active state>, lease_owner: me, fence: my_fence,
         lease_expires_at: {$gt: now}, cancel_requested: {$ne: true}},
        {$set: {status: <next state>, output_fence: my_fence, ...}, $inc: {state_version: 1}})   # else abort
    # publish output pointers (clause/sentence/finding set ids) in the same transaction
```

- **Deletion takes part in the same conflict domain.** MongoDB detects only *write-write* conflicts; a transaction that merely reads the source would not conflict with a delete. So the commit **writes** the source (`$inc commit_seq`, guarded on `deleted_at: null` + `generation`), and deletion writes it too (`deleted_at`, `$inc generation`). The two cannot both commit. Whichever comes second gets a WriteConflict or a non-matching filter; the commit retry then sees the deleted source and aborts for good. **A late save is therefore guaranteed to fail**, not just hidden.
- **Requirement:** a replica set in development and CI. The local test Mongo is standalone today (the engagement/fee tests already fail for this reason). P1 sets up a single-node replica set; the analyzer refuses to start without transaction support, like the existing agreement transitions.
- **Stage outputs have a business identity, not a worker identity.** They are written before the commit, then made visible by the commit:
  - An output *set* is identified by **`(text_version_id, stage, fence)`** for text-version outputs (the page map, written once per text version: each extraction attempt mints a fresh text-version id), or **`(run_id, stage, fence)`** for run outputs (clauses, sentences, key-term candidates, findings). *Implementation note (slice 3): clauses and sentences are keyed by RUN, not text version, because fences are per run -- two runs segmenting one text version would otherwise collide on `(text_version_id, stage, fence)`. Each row also stores its `text_version_id`.*
  - An output set has many rows, so **each row adds a deterministic `ordinal`** (its 0-based position in the stage's output order: page number, clause order, sentence order, finding order).
  - The **unique index** is on `(text_version_id, stage, fence, ordinal)` or `(run_id, stage, fence, ordinal)`. A retried write of the same row under the same fence is idempotent (upsert on the full key). A different fence can never overwrite it.
  - Readers fetch a stage's rows by **`(text_version_id, stage, published_fence)`** (text-version outputs) or **`(run_id, stage, published_fence)`** (run outputs), sorted by `ordinal`. Here `published_fence` is read from the owning text version or run.
  - The committing transaction publishes `published: {stage: fence}` on the text version or run. **Readers only read rows whose fence equals the published fence.** Rows from losing fences are swept.
- **Claim queued work:** `find_one_and_update({status: {$in: QUEUED_STATES}, lease_owner: null})` sets the owner, `lease_expires_at`, `$inc fence`, and moves the run to its active state.
- **Reclaim expired work (startup and periodic):** `find_one_and_update({status: {$in: ACTIVE_STATES}, lease_expires_at: {$lt: now}})` sets a new owner and lease and `$inc fence`. The old owner's commit then fails the fence check.
- `$in` with a compound index `(status, lease_expires_at)`. No regex status queries.
- **Heartbeat** every 30s (`lease_owner + fence` match). A failed heartbeat means the worker aborts.
- **Cancel:** sets `cancel_requested`. The worker checks between stages and on heartbeat. The fenced commit refuses once it is set, and the run is set to `cancelled`.
- **Not `FastAPI BackgroundTasks`.**

---

## 6. Deletion, reviews and lawyer sharing

### 6.1 Generated payload is immutable, and reviews are events

- A `done` run's generated payload (its findings) is never mutated.
- Lawyer decisions are **append-only** `analysis_review_events {finding_id, run_id, share_id, reviewer_id, decision: accepted|rejected|missing_confirmed, note, at}`.
- A materialised `analysis_review_state {finding_id → latest decision}` is maintained for display, and can always be rebuilt from the events.

### 6.2 Lawyer sharing (explicit, per run)

```
POST /documents/analyses/runs/{run_id}/share   {lawyer_id, note}   Idempotency-Key
```

- Allowed only for `done` runs owned by the caller, and only for a lawyer who exists and is verified.
- It creates `analysis_shares {run_id, text_version_id, playbook_hash, finding_ids[] (frozen), lawyer_id, owner_id, status: active|revoked, created_at}`.
- **A lawyer can read exactly the frozen share:** that run, that text version and those findings. Nothing document-wide, and no later runs.
- The review endpoint requires an active share. Every event records its `share_id`.
- `DELETE /shares/{id}` (owner) revokes it. **Source deletion revokes all shares.**
- **If this isn't ready for the demo, lawyer review is deferred entirely.** In that case the "Send to a lawyer" UI stays hidden, and there is no fallback to broader permissions.

### 6.3 Deletion that a running worker cannot undo

**The tombstone and the outbox row are written in one transaction.** If they were separate writes, a crash between them would leave a deleted source whose files are never removed.

`DELETE /documents/analyses/{source_id}`:

```
with session.start_transaction():
    r = sources.update_one({_id: source_id, owner_id: me, deleted_at: null},
                           {$set: {deleted_at: now}, $inc: {generation: 1}})
    if r.matched_count == 0:
        abort_transaction()                                                   # → 404 (not found / not owner / already deleted)
                                                                              #   checked BEFORE the outbox write, so no orphan purge row
    deletion_outbox.update_one({source_id, operation: "purge"},
                               {$setOnInsert: {created_at: now, attempts: 0, next_at: now}},
                               upsert: true)                                  # unique (source_id, operation)
```

- **Enforcement is immediate, without waiting for the fan-out:**
  - **Every read endpoint** (owner routes, share routes, run/report fetches, file downloads) first checks `source.deleted_at == null`. Otherwise it returns 404.
  - **Every worker commit** fails, because the commit transaction writes the source guarded on `deleted_at: null` + `generation` (§5).
  - So from the instant the transaction commits, every **new** read returns 404 and nothing can be published. (A response that was already being sent before the commit cannot be recalled; deletion governs what happens after it, not what was read before it.)
- **The outbox worker then fans out, idempotently and resumably:**
  1. Mark all runs of the source `cancel_requested` (and `cancelled` if not active).
  2. Revoke all shares.
  3. Wait until no run of the source holds a live lease (retry with backoff).
  4. Delete blobs, text versions, context versions, pages, clauses, sentences, runs, findings, review events/state and shares.
  5. Set `done_at`.

  Each step can be repeated safely after a crash.
- The **expiry sweep** (7 days) runs **the same transaction** (tombstone + outbox row). A TTL index alone would leave files on disk.

### 6.4 File encryption at rest (`analysis_file_store`)

The same envelope covers original uploads and canonical-text blobs.

- **Algorithm:** AES-256-GCM (`cryptography`'s `AESGCM`), for both content encryption and data-key wrapping.
- **Keys:**
  - **One fresh 32-byte data key (DEK) per blob**, used for exactly one encryption. So a content nonce can never repeat under a DEK.
  - Master keys come from one setting, `ANALYZER_KEKS="id:base64,id:base64"` (a single field, because pydantic settings cannot load dynamically named variables from `.env`). **At startup each is decoded and must be exactly 32 bytes**, ids must be unique, and `ANALYZER_KEK_ACTIVE` must name one of them, or the analyzer is not ready. `ANALYZER_KEK_ACTIVE` names the one used for new blobs.
- **Two separate 96-bit random nonces:**
  - `content_nonce` for the blob;
  - `wrap_nonce` for wrapping the DEK.

  They are never shared or derived from each other.
- **Tags:** `AESGCM.encrypt` returns ciphertext with the 16-byte tag **appended**. The blob file therefore holds `ciphertext || tag`, and `wrapped_dek` holds `wrapped || tag`. There is no separate tag field.
- **AAD, which binds context so a blob or key cannot be swapped between records:**
  - Content AAD = canonical JSON of `{format: 1, blob_id, source_id, purpose: "original"|"canonical_text", mime}`.
  - Wrap AAD = canonical JSON of `{format: 1, blob_id, source_id, purpose, kek_id}`.

  Changing any of these header fields makes decryption fail.
- **Header location:** it is stored in Mongo on an `analysis_blobs` record `{_id: blob_id, source_id, purpose, mime, format, alg, kek_id, wrap_nonce, wrapped_dek, content_nonce, size, plaintext_sha256}`. The disk holds only `ciphertext || tag`.
  - `plaintext_sha256` is for idempotency (`analysis_sources.file.sha256`).
  - Because it could reveal whether two users uploaded the same file, it is never exposed across owners.
- **Integrity:** a GCM failure on the DEK or the content is an error that returns no bytes, never a partial read.
- **Re-wrap (rotation):** unwrap the DEK with the old KEK, then wrap it with the new KEK and a **new `wrap_nonce`**. The header is replaced **atomically** with one conditional update: `{_id, kek_id: old, wrap_nonce: old}` → `{kek_id: new, wrap_nonce: new, wrapped_dek: new}`. Content is never re-encrypted. A lost race is simply retried.
  - Old KEKs stay configured until no blob references them.
  - With a 7-day retention, rotation can also just wait for expiry.

---

## 7. Cloud AI policy (demo)

- **Synthetic documents only for the demo.** "Anonymised" real documents can still leak names, addresses or account numbers without local redaction, which we don't have.
- **Enforced, not just stated:**
  - **UI:** before a file can be chosen, the user must tick an unticked-by-default checkbox, next to a visible warning: *"Demo only — do not upload real client or confidential documents. I confirm this document is synthetic (made up for testing)."* The upload control stays disabled until it is ticked.
  - **Backend:** `POST /documents/analyses` requires the **headers** `X-Synthetic-Data-Attested: true` (exactly) and `X-Synthetic-Attestation-Version: <known version>`. Anything else gets **422 `synthetic_attestation_required`**. Headers, not form fields, so the check (and the Idempotency-Key format check) runs **before the multipart body is parsed**: a refused request's file is never parsed, received into memory or spooled to a temporary file. A form field claiming the attestation does not count.
  - **Record:** the source stores `attestation {synthetic: true, attested_by: user_id, attested_at, ui_text_version}`. `ui_text_version` identifies the exact warning wording the user saw.
  - The attestation is part of the idempotency fingerprint. It is not a substitute for the demo's other safeguards (ZDR, retention, deletion).
- **Pinned client:** the analyzer uses a separate client that **never goes through `llm.py`'s fallback chain**.
  - Backend config holds an **allowlist** of `(provider, model)`.
  - **At startup, if `DOC_ANALYZER` is on and the pinned configuration is missing or not allowlisted, the analyzer refuses to start.**
- **Groq direct, with ZDR enabled.** Recording `zdr: true` proves nothing. Instead:
  - An **operator checklist** (ZDR enabled in the Groq console, who checked it, and when) is kept with the deployment notes.
  - Each run records `provider`, `model`, `provider_policy_version` (the checklist entry id) and the date.
- Provider health checks use **synthetic text only**.
- If the provider fails, the run fails with "try again later". It never reroutes.

---

## 8. API (`/documents/analyses`, flag `DOC_ANALYZER`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/documents/analyses` | multipart upload + run options; headers `X-Synthetic-Data-Attested: true`, `X-Synthetic-Attestation-Version` (§7) and `Idempotency-Key` (8-200 of `[A-Za-z0-9._:-]`), all checked before the body is parsed → **202** `{source_id, run_id}` |
| GET | `/documents/analyses` | history |
| GET | `/documents/analyses/{source_id}` | source, text versions, runs |
| GET | `/documents/analyses/runs/{run_id}` | status, `state_version`, progress, report (polled) |
| POST | `/documents/analyses/runs/{run_id}/ocr-text` | CAS on `needs_ocr_confirmation` + `state_version` → new text version |
| POST | `/documents/analyses/runs/{run_id}/document` | CAS on `needs_document_confirmation`: jurisdiction, type → new context version |
| POST | `/documents/analyses/runs/{run_id}/terms` | CAS on `needs_terms_confirmation`: decisive terms → new context version |
| POST | `/documents/analyses/{source_id}/runs` | re-analysis (side, depth, focus) → new run |
| POST | `/documents/analyses/runs/{run_id}/cancel` | cancel |
| POST | `/documents/analyses/runs/{run_id}/share` | share a frozen run with one lawyer (§6.2) |
| DELETE | `/documents/analyses/shares/{share_id}` | revoke a share |
| POST | `/documents/analyses/shares/{share_id}/review-events` | lawyer decision (active share only) |
| DELETE | `/documents/analyses/{source_id}` | delete (§6.3) |

Every route checks the owner or an active share. **No usage quota.** Technical bounds only: §4.8 and per-stage timeouts, plus:

- **Idempotent create with a request fingerprint.** Store `sha256(file sha256 + canonical JSON of options)` with the key, unique on `(owner_id, key)`. The same key with a different file or options → **409 `idempotency_mismatch`**. The same key with the same request → the original `{source_id, run_id}`.
- **One active run per source,** enforced by a unique partial index on `source_id` where `status ∈ QUEUED ∪ ACTIVE ∪ PAUSED`. A second start → 409 `run_in_progress`.
- **Deletion outbox rows** are unique on `(source_id, operation)`, so a repeated delete or expiry sweep enqueues once.

## 9. Frontend

- **Upload** matches the §4.8 formats and limits exactly, and is disabled until the synthetic-data confirmation (§7) is ticked. The warning stays visible next to it.
- **Progress** is polled. There are three pause screens: OCR text, document (type/province), and decisive terms, each with its evidence.
- **Tabs:** Summary, Risks (`model_risk`), Checks (`legal_check` + `reminder`, with tri-state wording), Key terms, Document (canonical-text viewer with highlights).
  - Precedents is hidden.
  - Ask is hidden until P5.
- **Report header:**
  - pages read / total, OCR used or not;
  - playbook version and sign-off;
  - provider and model;
  - "Review assistant, not legal advice".
- **Share with a lawyer** appears only when §6.2 is live.

---

## 10. Evaluation and phases

**Evaluation (P4, before Ask):**
- **Data:** 10–15 *synthetic* Punjab tenancy agreements, with lawyer-annotated expected results per rule.
- **Metrics:**
  - per-rule precision/recall;
  - false `not_located` rate;
  - span validity (100%, regression test);
  - model-risk precision;
  - dropped-item counts;
  - latency p50/p95.
- **Recovery test:** kill the worker mid-LLM-call, then check the stale worker cannot publish and the reclaimed run completes once.
- **Race tests:**
  - delete during `analyzing` → no derived data survives;
  - cancel during a stage;
  - a double confirmation with a stale `state_version` → 409.
- **Unit tests:**
  - every rule and registration limb;
  - the DSL rejecting unknown operators;
  - sentence → multi-page spans;
  - DOCX bomb fixtures;
  - prompt-injection fixtures;
  - share scoping (a lawyer can't read another run).

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **P-1 · Honesty fix** (frontend only) | See the scope below | Tests assert none of the removed claims/actions return |
| **P0 · Decisions & contracts** | Approve the retention policy. Pin provider + model, operator ZDR checklist. Write the deletion contract and the state machine as specs. Prepare the synthetic doc set | Signed-off decisions; specs reviewed |
| **P1 · Read and map** | File store, durable worker (§5), extraction, OCR confirmation, text versions, segmentation with page spans, document + terms confirmation, history, cancel, **deletion + outbox implemented and tested** | Restart/recovery, delete-race and cancel tests green; DOCX bomb refused; Urdu refused honestly; owner isolation |
| **P2A · Playbook engine + general review** | Engine, `general` pack, approvals by exact hash, analysis stage (`queued_analysis` → `done`), report with scope labels (§4.5a) | DSL/locator/stage tests; an unapproved legal pack is reported, never run |
| **P2B · Legal packs** | `tenancy_punjab` (ingest PRPA 2009, Registration Act 1908, TPA 1882), `nda`, `employment` | Lawyer-approved signed hashes before merge/release |
| ~~P2 · Punjab tenancy playbook~~ (superseded by P2A/P2B) | Ingest PRPA 2009, Registration Act 1908, TPA 1882. DSL. `legal_check` + `reminder` with evidence. Sign-off by an authenticated reviewer | Rule/limb tests; signed hash matches |
| **P3 · AI explanation** | Batched `model_risk` via sentence IDs, server spans, no citations, merge | Span validity 100%; injection fixtures pass |
| **P3b · Lawyer sharing** (optional for the demo) | §6.2 shares + review events | Share-scope tests |
| **P4 · Evaluation** | §10 metrics; tune batch size | Numbers per rule |
| **P5 · Ask the document** | Retrieval over this document only, sentence-ID answers, "not found in this document", general law → Legal Research | Anchoring metrics hold |
| **P6 · NDA, employment** | Separate signed playbooks | As for P2–P4 |

**P-1 scope,** frontend only, verified against the current `DocsAnalyzer.jsx`:
1. A persistent banner: **"Fictional demonstration — no uploaded document was analysed."**
2. Replace every `cite` ("… · verified") with **"Illustrative only — legal source not checked."**
3. Rename "Missing" (the tab, its count, the compliance tone and the completion text) to **"Not located in this fictional sample"** / "Illustrative checks".
4. Hide Precedents.
5. Hide both Ask surfaces (the dashboard tab and the upload-screen input) until P5.
6. Hide the dead "Fix in a new draft", "Send to lawyer", "Resources" and "Adding another document" controls.
7. Show only the one working sample (the shop tenancy). Remove the two sample cards that can't run.
8. Replace the file picker and its "PDF · DOCX · DOC · photo · 50 MB" copy with **"Real document upload is not available yet."**
9. Remove the false promise "Private to you, never used for training … send the result to a lawyer in one click."
10. Add tests asserting that none of the above claims or actions can return.

Deferred:
- the Contract Act, Stamp Act and Specific Relief Act;
- Urdu;
- other provinces;
- precedents;
- quotas;
- consensus scoring.

---

## 11. Decisions

**Confirmed by the user, 2026-09-30:**

| Decision | Confirmed |
|---|---|
| Usage quota | None for the demo |
| Cloud AI | Groq direct, pinned model, verified zero-data-retention (operator checklist), no fallback, **synthetic documents only** |
| First type | Punjab tenancy agreement |
| Retention | 7 days + immediate delete (atomic tombstone + outbox, §6.3) |
| Lawyer sharing | Deferred from the first demo; the button stays hidden |

**Release gate (not blocking P1):** the P2 tenancy playbook **must not be merged or released** until a lawyer qualified in Punjab tenancy law approves the signed playbook hash, recorded as an authenticated user. A supervisor's academic approval is not a substitute unless the supervisor is so qualified. The reviewer does not need to be named before P1 starts.

## 12. Changelog

**2026-10-01 (after P2B):**
- Authority library from official sources (§4.5a). Verifying the Punjab
  Rented Premises Act against Punjab Code corrected two errors in the
  secondary copy first quoted (s.6(1)(d) "of rent", s.6(1)(f) "; and").
- Approvals also bind the cited text (`authorities_hash`).
- The test suite is held to loopback; `llm`/`network` tests run only with
  `AAI_LIVE_TESTS=1` (manual `live` CI job). The earlier "Groq network flake"
  was a localhost stub that never read the request body (Windows RST race),
  not a provider call.

**v3.3 → v3.4 (sixth review):**
- The reader query is explicit: `(text_version_id | run_id, stage, published_fence)`.
- "Synthetic documents only" is **enforced**:
  - a UI confirmation plus warning;
  - a required backend attestation (422 otherwise, before the file is read; moved to headers in the P1 follow-up so it is checked before the body is parsed);
  - the attestation (user, time, wording version) is recorded on the source.
- Commit plan: P1 slice 1 is split into four commits (config/collections/indexes → encrypted blob store → validated/idempotent upload + lifecycle → atomic deletion + purge outbox).

**v3.2 → v3.3 (fifth review):**
- Output rows add a deterministic `ordinal`, so the unique key is `(…, stage, fence, ordinal)`. A unique key without it would have allowed only one row per output set.
- Deletion aborts the transaction when the source update matches 0 documents, **before** the outbox write.
- Decisions confirmed. The P2 merge/release is gated on a qualified lawyer's approval of the signed playbook hash.

**v3.1 → v3.2 (fourth review):**
- **Atomic deletion:** the tombstone, the generation bump and the outbox row are now one transaction. Every new read checks `deleted_at` and returns 404 from the commit on. The fan-out (cancel runs, revoke shares, wait for leases, delete) is an idempotent, resumable outbox job. The expiry sweep uses the same transaction.
- **Output identity:** outputs are keyed `(run_id, stage, fence)` / `(text_version_id, stage, fence)` with unique indexes. The published fence is the visibility rule. (v3.1 wrongly said `(owner id, fence)`.)
- **Encryption envelope:**
  - separate content and wrap nonces;
  - AAD binds blob id, source, purpose, MIME and format (and `kek_id` for the wrap);
  - the tag is appended to the ciphertext;
  - KEKs are validated as exactly 32 bytes at startup;
  - the header is stored in Mongo, and a re-wrap uses a new nonce with an atomic conditional header replacement.
- The stale changelog line about confirmations now points to context versions.
- The decisions table records the reviews' recommendations. Legal sign-off must come from a qualified lawyer.
- P-1 follow-up (implemented): the greeting lines no longer promise insights "from your file", and "Analyze Document" became "Open fictional analysis". A test forbids both from returning.

**v3 → v3.1 (third review):**
- The stage commit is now a **Mongo transaction** covering a guarded *write* to the source (so it conflicts with deletion; Mongo detects only write-write conflicts), the run commit and output publication. A late save after deletion is guaranteed to fail. Replica set required in dev/CI.
- The claim uses `$in QUEUED_STATES`. A separate **reclaim** handles expired `ACTIVE_STATES`. No regex status query; compound index.
- **Text version vs context version:** OCR creates a text version. Type, province and terms create a context version on the same text. Runs reference the context version.
- DSL operands are **typed** (`{field}` / `{value}`), with arity, field and type validation at load.
- Additions:
  - idempotency request fingerprint → 409 `idempotency_mismatch`;
  - unique active run per source;
  - outbox unique `(source_id, operation)`;
  - encryption format (AES-256-GCM, wrapped data keys, `kek_id`, rotation);
  - a defined citation detector;
  - completed payloads stay immutable under `superseded_at`.
- Recommended: defer lawyer sharing from the first demo.

**v2 → v3 (second review):**
- An explicit run state machine with human pauses that release the lease, a `state_version` CAS, and re-analysis starting at `queued_analysis`.
- At-least-once semantics are stated. Every stage commit is fenced (owner, fence, live lease, expected state, not cancelled, source generation), following `revision_repo.promote`.
- **Delete-vs-worker race closed:** a source generation bump, cancel of runs, share revocation, and an outbox that rechecks live leases.
- Confirmations moved: jurisdiction, type and key terms went on the text version, and side, depth and focus on the run. *(Superseded in v3.1: type, jurisdiction and terms live on a **context version**; see §4.3.)*
- Run payload is immutable. Lawyer decisions are **append-only review events** plus a materialised state.
- An explicit **per-run lawyer share** freezes the run, text version, playbook hash and finding set. Or the feature is deferred with the UI hidden.
- `kind` (legal_check / model_risk / reminder) is separated from `check_result`. The Rent Registrar rule is a `reminder`.
- Separate collections for text versions, pages, clauses and sentences from day one. The text is a blob.
- Sentences carry `page_spans`. v1 highlights in a canonical-text viewer, not on the PDF.
- Per-format limits with DOCX ZIP-bomb guards and a canonical character cap. The frontend copy must match.
- Research wording: GPT-4.1 family ≈ 0.64; thinking/quantisation "mixed, often reduced"; the vendor section is labelled a synthesis. "Every vendor states …" was removed.
- Provider: an allowlist, a pinned client outside the fallback chain, startup refusal, an operator ZDR checklist, synthetic-only demo data.
- The P0/P1 contradiction was fixed: P0 approves and specifies, P1 implements deletion.
- P-1 was widened to 10 items (adding the false privacy/one-click promise found at `DocsAnalyzer.jsx:870`).

**v1 → v2 (first review):**
- tri-state checks;
- sentence-ID anchoring;
- three-limb registration rule;
- honest source labels;
- stale proxy/WS facts corrected;
- reuse corrected (`artifact_store`, `extraction_lease`);
- immutable runs, cancellation, deletion outbox, safe DSL, prompt-injection handling, pinned provider;
- narrowed ingestion;
- evaluation before Ask.

---

## Sources

- ContractEval (2025): https://arxiv.org/html/2508.03080
- CUAD (NeurIPS 2021): https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/file/6ea9ab1baa0efb9e19094440c317e21b-Paper-round1.pdf
- Stanford RegLab, *Hallucination-Free?* (2024): https://law.stanford.edu/wp-content/uploads/2024/05/Legal_RAG_Hallucinations.pdf
- Lost in the Middle (TACL 2024): https://aclanthology.org/2024.tacl-1.9/
- Tool descriptions: https://www.legalfly.com/post/best-ai-contract-review-software, https://conga.com/resources/blog/ai-contract-review-software, https://thelegalprompts.com/blog/ai-contract-review-tools-how-they-work
- Punjab Rented Premises Act 2009: https://punjablaws.gov.pk/laws/498.html
- Transfer of Property Act 1882 (Pakistan Code): https://pakistancode.gov.pk/pdffiles/administrator77923ce792b475e339e1f46ba0442da3.pdf
- Groq data retention / ZDR: https://console.groq.com/docs/your-data
- OpenRouter guardrails: https://openrouter.ai/docs/guides/features/guardrails/overview
- Pakistan LawBot analyzer: https://pakistanlawbot.com/document-analyzer
- Internal: `EXTRACTION_AND_OCR_PLAN.md`, `app/ai/extraction.py`, `app/ai/ocr.py`, `app/ai/extraction_lease.py`, `app/services/artifact_store.py`, `app/repositories/revision_repo.py`, `frontend/next.config.js`, `frontend/src/components/client/documents/DocsAnalyzer.jsx`
