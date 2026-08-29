# Handoff — citation verification & document drafting

**Read this before touching the module.** It is the working memory a fresh
session would otherwise spend hours re-deriving: what is done, what is
deliberately *not* done, the traps in this codebase, and the rules this module is
built on.

The formal write-up is `CITATION_VERIFICATION_SESSION_REPORT.md` (§A is a
current-state index). This file is the engineering companion to it.

Last updated: **25 August 2026** · branch `feat/selective-abstention-and-audit-trail`
· HEAD `1cbfdf2` · pushed to `github.com/muhammadusamahoyrr/fyp`
· **1,232 tests collected · 1,231 passed · 1 skipped · 0 failed**

---

## 1. What this module is

Two things that share a spine:

**Citation verification** — for any drafted text, check every authority it cites
against the corpus. Four verdicts:

```
VERIFIED        in the corpus and still in force
NOT_IN_CORPUS   absent from a statute we hold densely enough for absence to
                mean something — the fabrication flag
OMITTED         the Act itself declares this section repealed
UNVERIFIABLE    we cannot speak to it either way
```

**Document drafting** — the client fills a template and a lawyer reviews it.
Templates are deterministic Python builders; the LLM fills fields, it never
writes the document.

### Key files

| Path | Role |
|---|---|
| `app/ai/citation_verification.py` | parser + verdicts |
| `app/ai/corpus_index.py` | coverage/density model, ceiling trimming |
| `app/ai/statute_omissions.py` | repeal records; generated map |
| `app/ai/data/statute_omissions.json` | **generated** — do not hand-edit |
| `scripts/build_omission_map.py` | regenerates the above |
| `app/services/pleading_rules.py` | statutory particulars per template |
| `app/services/pdf_generator.py` | one builder per template + `_GENERATORS` |
| `app/services/document_service.py` | generation, verification record, review |
| `app/core/claims.py` | the scope statement shipped to both UIs |
| `app/services/succession_route.py` | forum advisor (guidance, not a document) |
| `app/ai/mismatch_detection.py` | **A1 — measured, not wired in** |

---

## 2. The rules this module is built on

Break these and the module stops being worth having.

1. **"I cannot tell you" is a first-class verdict.** Most tools collapse
   *unverifiable* into *not found*. That is the failure this design exists to
   avoid. A false accusation about a real provision teaches a lawyer to ignore
   every flag.
2. **Never false-accuse.** Where a choice exists, under-count. A missed
   fabrication leaves the status quo; a false flag is a regression.
3. **Advisory, never blocking.** Even Shepard's misses 23% of negative treatment.
   Nothing here stops a filing.
4. **Fail open, but never fail silent.** `ran: false` must never read as a pass.
   Every fail-open path says so explicitly.
5. **Draft from the statute, never from a court's or a commercial site's PDF.**
   LHC asserts copyright; IHC disclaims official use. Statutory requirements are
   law and carry no such restriction. Provenance goes in the code and is
   asserted by a test.
6. **Pre-register thresholds before measuring.** A1's ship/no-ship bands were
   fixed before any number existed — which is the only reason a 1.000 point
   estimate could honestly be refused.
7. **A 0% rate is meaningless without a positive control.** A broken detector and
   a working one score identically on clean data. Report both or neither.

### The scope we claim (adopted formally — report §0)

We do **not** claim a generated document is correct or complete. Only:
citations are checked for existence and, where checked, currency; where a
statute enumerates contents we draft the whole instrument; where contents are
delegated elsewhere we generate only the grounded part and **disclose the gap**;
and a lawyer reviews before filing.

---

## 3. Traps in this codebase

Each of these cost real time. Do not re-learn them.

### 3.1 Two numbering spaces flattened into one — happened **three times**

The single most recurrent bug class here.

| Case | Symptom |
|---|---|
| Limitation Act **Articles** vs sections | "Article 151" looked up among 32 sections → real provision reported fabricated. **100% of flags were this.** |
| CrPC **Schedule II rows** vs sections | table row numbers read as section declarations |
| CPC **Order rules** vs sections | 94 of 165 numbers collide, one carrying 132 provisions — **still open, problem ⑨** |

**Before trusting any section number, ask what else is numbered that way.**

### 3.2 Pydantic response models are allowlists

An undeclared key is dropped **silently**. This has bitten three times:
`POAOut.verify_url`, `DocumentOut.compliance`, `ReviewQueueItem`. Add a field to
a stored record → declare it in *every* response model that carries it, and test
serialization.

### 3.3 `_has()` in `pleading_rules` is ANY, not ALL

Fine for a clause with one companion field, wrong for one naming five. Use
`also_all` where the clause enumerates several particulars in a breath.

### 3.4 Backend files are CRLF

Writing LF rewrites every line of the file. If you script an edit, preserve
`newline="\r\n"` and byte-compare afterwards.

### 3.5 The rate-limit test uses **live Redis**

`test_healthy_storage_still_limits` counts against Upstash with a real 1-minute
window. Run the suite twice inside a minute and it fails for reasons unrelated to
your change. Not a flake in the code — a test-isolation defect. Confirm by
running that file alone.

### 3.6 Environment

- Run the backend with **`backend/venv/Scripts/uvicorn.exe`**, not system Python.
- **Single pytest process** — the suite shares a live Mongo.
- `get_index()` needs **`connect_chroma()`** first, or it raises.
- Caches are global: `get_index(refresh=True)` and `set_omissions(None)` after
  changing corpus data.
- **`backend/knowledge_base/` is gitignored** — ingested source PDFs are not in
  the repo. Ingests are reproducible from `ingest_statutes.py` + the source URL.
- Heredocs in this shell mangle `\n` / `\r\n` escapes. Write a scratchpad `.py`
  file instead of inlining multi-line Python.

### 3.7 `build_omission_map.py` reads `processed/text/`

The PDF ingest path does **not** populate it. A statute ingested straight from
PDF (e.g. Succession Act 1925) is therefore absent from the omission map, so a
future repeal of its sections would not be detected. Point-in-time only.

---

## 4. What is shipped

| | Where |
|---|---|
| Four-verdict verification, 0.0% flag rate, 9/9 positive controls | §1–2 |
| Coverage/density model — a statute must *earn* the right to flag (23 of 44 do) | §2.1 |
| `OMITTED` verdict with instrument, date, jurisdiction per section | §2.2, §6a |
| Order/Rule citations surface as `UNVERIFIABLE` instead of vanishing | §4.2a |
| Scope statement on both client and lawyer panels | §0 |
| **Guardianship petition** — full instrument from GWA 1890 s.10(a)–(l) | — |
| **Succession route advisor** — NADRA vs court, guidance not a filing | §6b |
| **Wakalatnama checklist** — only what Order III r.4 prescribes, gap disclosed | — |
| Client document-type mappings fixed; fabricated lawyer panel replaced | — |

Corpus: **44 statutes · 3,490 sections · 23 dense · 182 excluded as repealed.**

---

## 5. What is left

### 5.1 Code

| Pri | Item | Effort | Notes |
|---|---|---|---|
| **1** | **⑨ CPC data fix** | M–L | Re-ingest CPC with `order`/`rule` split from `section_number`. Parser is patched; data is not. `CPC s.45` currently verifies against whatever rule occupies 45. **Do not "fix" by demoting CPC from dense — density gates `NOT_IN_CORPUS`, not `VERIFIED`. That is theatre and is recorded as rejected.** |
| **2** | Verification on the other 7 document paths | S | Only `/documents/generate` checks citations. `generate_standalone` has 7 callers. *Another session began this — check before starting.* Watch the allowlist trap (3.2): the record will be stored and invisible unless response models declare it. |
| **3** | **Affidavits** | M | Every competitor offers them; we have none. Biggest user-visible gap, and no delegation problem in the way. |
| **4** | Family-law templates (khula, dissolution) | M | Highest-volume litigation in Pakistan. Nothing built. |
| **5** | Wire the 14 unreachable backend templates into the client picker | S | Lawyer's 14 template names are prompt labels only — not connected to real builders. |
| — | ① Existence ≠ relevance | Large | See 5.3. |
| — | s.468 comma gap | XS | One live CrPC section the splitter drops. Costed; not worth a re-ingest alone — fold into ⑨. |

### 5.2 Needs a human, not code

- **Gazette check** — 182 sections marked repealed were read from bundled PDFs,
  never Gazette-verified. **Highest-value item on this list**: everything else is
  an honestly-disclosed gap, this one is a claim that could be *wrong*, and a
  false `OMITTED` is the exact failure the module exists to prevent.
- **Second annotator** for `tests/fixtures/citation_eval/dlite_v1.json` — it is
  single-annotated, so no agreement statistic may be claimed. The format already
  allows a second label column.
- **ss.407 / 438** — Punjab-only 1996 notification, unconfirmed either way. Needs
  a Punjab source publishing current text.

### 5.3 Structural — do not "fix" casually

- **Case law can never be flagged.** 502 LHC judgments cannot support a claim of
  absence. Needs a law-report corpus; that is a licensing question.
- **A2 / entailment is foreclosed**, not pending. The pre-committed rule was
  "A2 does not start unless A1 clears 0.70". A1's CI lower bound was 0.566. If
  you want to revisit it, revisit the *rule* explicitly and say so — do not just
  start building.
- **n = 17.** The 0.0% flag rate rests on seventeen answers carrying parseable
  citations. Enough to show the checker is quiet; nowhere near enough to justify
  blocking. Grow this before anyone argues for a hard gate.
- **Existence ≠ relevance.** A real section cited for something it does not say
  reads as `VERIFIED`. A1 (embeddings) was measured: 0.714 on gross mismatch,
  **0/10 on same-topic** — the distributions interleave, so this is structural,
  not a threshold. `app/ai/mismatch_detection.py` is kept, unwired, with the
  measurement in §3.

---

## 6. State of the working tree

At handoff, **a second session was editing the same tree** and had ~14 modified
files uncommitted, including `corpus_index.py`, `graph/state.py`, four graph
nodes and `chat_socket.py`.

- `backend/app/services/document_service.py.backup-<ts>` is a safety copy of
  their uncommitted `generate_standalone` change. **Delete it once they commit.**
- If their work is still uncommitted, do not reconstruct shared files to split
  commits without checking mtimes first. That was done once here safely — backup,
  build states by *removal* never re-typing, byte-compare on restore — but it is
  only safe while the other side is quiet.

---

## 7. Corrections made — do not reintroduce

Recorded because each was believed and repeated before being caught.

- **"PPC 302 was cited for a stamp-duty question."** False. All seven recorded
  s.302 mentions read *"PPC Section 302 is **not applicable** here"* — the model
  correctly rejecting it. The grounding parser counted a mention as a citation
  because it does not read negation. The real logged misgrounding is *"PPC
  Section 152 — Limitation for appeals"*: PPC 152 is a riot offence.
- **"No judgment in the corpus has a real citation."** Misleading. They are
  *unreported* judgments; they carry 2,951 real outbound citations.
- **ss.407/438 dated "1975".** `1-8/75` is the notification's file number; the
  date is **21 March 1996**.
- **Limitation Act s.5 marked repealed.** `5A. [Repealed]` matched `(\d+)[A-Z]?`
  and condemned s.5 — the condonation-of-delay provision. Lettered sections are
  now skipped entirely.
- **CrPC s.14 marked omitted.** A schedule table *row number*, not a section.
  Permanently excluded as a parser artifact.

---

## 8. Where to start next session

1. Read §A of `CITATION_VERIFICATION_SESSION_REPORT.md` for current numbers.
2. Check whether the other session committed; delete the backup if so.
3. Run the suite once (**single process**) and confirm 1,231 passing.
4. Pick from §5.1. If the goal is credibility for the write-up, do the **Gazette
   check** (§5.2) instead — it is the only outstanding item that could make an
   existing claim wrong rather than merely incomplete.
