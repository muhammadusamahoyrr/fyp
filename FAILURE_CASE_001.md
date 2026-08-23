# Failure Case 001 — a wrong statutory citation that passed every gate

A worked instance of the limitation the paper's threats table records as
"generation correctness is unmeasured". It is kept here because a failure that
lives only in a log cannot be cited, reproduced, or argued with.

**Cite as:** Failure Case 001, `request_id 37a76e77-2510-4095-9890-3c44606f089a`,
2026-08-23. Full provenance record: [`evidence/failure_case_001.json`](evidence/failure_case_001.json).

---

## 1. What was asked, and what came back

**Query (English, verbatim):**

> What is the punishment for theft under the Pakistan Penal Code?

**Answer (first 500 chars, as stored in `answer_preview`):**

> **Issue:**
> What is the legal procedure for prosecuting a case of official theft under the
> **Punjab Criminal Procedure Code** and Pakistan Penal Code?
>
> **Applicable Law:**
> - **PPC Section 382 — Theft**
> - CrPC 1898 Section 15
>
> **Legal Analysis:**
> The case of official theft would be prosecuted under Section 382 of the
> Pakistan Penal Code, which deals with theft. According to CrPC 1898 Section 15,
> the charge should include the date, place, and details of the theft…

### Four defects

| # | Defect | Correct position |
|---|---|---|
| 1 | Cites **PPC 382** as "Theft" | Theft is **PPC 379**. PPC 382 is theft *after preparation made for causing death, hurt or restraint* — a distinct aggravated offence with a different sentence. |
| 2 | Invents the "**Punjab Criminal Procedure Code**" | No such instrument. The CrPC 1898 is federal. The system's own retrieved chunks are tagged `province: federal`. |
| 3 | Answers a **different question** — procedure for prosecuting, not punishment | — |
| 4 | **Never states the punishment**, which is what was asked | PPC 379: imprisonment up to 3 years, or fine, or both. |

The system contradicts itself: its own deterministic bail checker returns
`PPC 379 · Theft · up to 3 years · Magistrate` for the same offence. The
rule-based component is right; the retrieval-augmented answer is wrong.

---

## 2. Telemetry — the signals were correct, the gates were not

```
is_grounded          : True
convergence_status   : converged
signals.confidence   : 0.85
signals.relevance_score : 0.2396
signals.bm25_confidence : 0.0
attempts             : {retrieval: 2, generation: 1, clarification_depth: 2}
cache_hit            : False
web_search_used      : False
embedding_model      : intfloat/multilingual-e5-base/v1
```

**A BM25 confidence of exactly 0.0 means no lexical overlap was found between
the query and any retrieved passage.** Relevance scored 0.2396. The pipeline
nevertheless reported 0.85 confidence, marked the answer grounded, declared
convergence, and shipped it.

This is the abstention finding reproduced end-to-end: the confidence signal does
not track answerability, so a threshold placed on it cannot separate the cases
where the system should decline.

---

## 3. Root cause — the query was corrupted before retrieval ran

This is not a generation failure that began at generation. The causal chain
starts two nodes earlier.

`triage_node` is specified as follows (its own prompt, verbatim):

```
normalized_query:
  If language is "roman_urdu": transliterate to standard Urdu script.
  If language is "ur": return as-is.
  If language is "en": return the original query unchanged.
```

It classified the query as `language: "en"` — correctly — and then emitted:

```
query            : What is the punishment for theft under the Pakistan Penal Code?
language         : en
normalized_query : ما سرکاری جرائم کے تحت سرکاری قانون میں سرکاری تھیف کی مجازیت کیا ہے؟
```

Roughly: *"What is the punishment for **official** theft under **official** law
under **official** offences?"*

Three separate faults in one field:

1. It **translated an English query into Urdu**, which its own contract forbids.
2. It **injected `سرکاری` ("official/government") three times** — a concept
   absent from the input. This is the origin of "official theft" in the answer.
3. It used **`تھیف`**, a transliteration of the English word "theft", rather
   than the Urdu word `چوری`. The output is not even well-formed Urdu.

### What that corruption then caused

Retrieval ran against the corrupted string and returned **18 statute chunks, not
one of them PPC 379**:

```
CrPC 1898 s.15  (×5)   CrPC 1898 s.3 (×2)   CrPC 1898 s.221, 234, 68, 367,
CrPC 1898 s.555, 108, 260, 235        PPC 1860 s.184, s.161, s.511
```

Almost entirely procedural CrPC sections. The three PPC hits (184, 161, 511)
concern obstruction, bribery and attempts — none is theft. The corrupted query
asked about "official" matters, so the retriever obligingly found provisions
about public servants.

**The chain:**

```
triage violates its own contract   ->  query becomes "official theft"
  -> retrieval searches the wrong concept
  -> 0.0 BM25, 0.2396 relevance     (the signals are CORRECT here)
  -> gates ignore both signals      -> is_grounded=True, confidence 0.85
  -> generation cites PPC 382 and invents a provincial CrPC
  -> hallucination check (140.8s) passes it
  -> finalizer ships it
```

---

## 4. Why the model is not the explanation

This run used `qwen2.5:7b` on CPU — a small model, and a weak one. That is worth
recording, and it is **not exculpatory**. Three of the five failure points are
pipeline properties that hold regardless of which model is plugged in:

| Failure point | Model-dependent? |
|---|---|
| Triage emitted output violating its own contract | Partly — but **nothing validated it**. `language == "en"` implies `normalized_query == query`, a one-line string equality check that does not exist. An unvalidated LLM output flows straight into retrieval **and into the cache key** (`sha256(normalized_query + case_type + province)`), so a corrupted normalization also poisons cache lookups. |
| Retrieval returned nothing relevant | No — it faithfully retrieved for the query it was given. |
| `bm25_confidence == 0.0` did not trigger abstention | **No.** This is pipeline logic. Zero lexical overlap is the strongest available evidence that retrieval has failed, and it is not acted on. |
| `is_grounded = True` over that evidence | **No.** The grounding check does not discriminate on evidence this weak, which means it is not measuring what its name claims. |
| The specific wording (382 vs 379) | Yes. A stronger model would likely cite 379 — *given a correct query*. |

A larger model would probably have produced a better answer here. It would not
have fixed the missing post-condition on triage, the unheeded 0.0 BM25, or a
grounding check that returns True over passages with no lexical overlap with the
question. Those defects would simply have stayed hidden behind a better answer.

---

## 5. What this is evidence for

1. **The paper's "generation correctness is unmeasured" limitation is load-
   bearing, not boilerplate.** Here is one measured instance, and it passed
   every automated gate the system has.
2. **Selective abstention needs a calibrated signal.** The existing confidence
   score reported 0.85 on an answer with zero lexical grounding. Conformal
   abstention is intended to replace exactly this, and it **cannot be fitted
   without labels** — which is why the labelling effort, not the threshold
   warmup, is the critical path.
3. **Single-turn evaluation is insufficient.** Every node reported success. The
   failure is only visible by reading the answer against the law. That is what
   the two-annotator protocol is for.

## 6. Remediation status

| Defect | Status |
|---|---|
| No post-condition on triage's `en` contract | **Fixed** 2026-08-23 (`a3cb25b`). `_enforce_en_invariant` repairs to the original query, logs at ERROR, and flags the record. Repairs rather than raises: the contract names the correct value, so failing the turn would deny a user an answer over a fault we can fix exactly. |
| Contaminated turns reaching annotators | **Fixed.** `invariant_violation` rides into provenance and the labelling pool excludes it. |
| Corrupted cache keys | **None existed.** Checked both the corrupted and correct keys for this turn, and the whole `aicache:*` namespace — 0 entries. Nothing to purge. |
| `bm25_confidence == 0.0` does not trigger abstention | **Open.** |
| `is_grounded` returns True over zero-overlap passages | **Open.** |

**Pool audit (`scripts/audit_triage_invariant.py`, 2026-08-23):** 128 provenance
records, 57 en-language, **1 violation** — this turn. It is `is_synthetic: true`,
so it was already outside the labelling pool; it is now flagged explicitly rather
than excluded incidentally. **No annotator ever saw it.**

The two open items are the ones that let a wrong answer through *after* the query
corruption. Fixing normalization removes this instance; it does not restore the
gates that failed to catch it, and any future retrieval failure would pass the
same way.

## 7. Reproducing

```bash
python scripts/serve.py start --local-only     # OLLAMA_MODEL=qwen2.5:7b
python scripts/seed_traffic.py --limit 1 --timeout 1500
python scripts/serve.py stop
```

Expect ≈15.7 minutes on CPU. The record is written to `answer_provenance` and is
marked `is_synthetic: true`, so it is excluded from the labelling pool by design.
Generation is stochastic; the specific wrong section may differ between runs.
The stored record in `evidence/` is the authoritative artefact for citation.
