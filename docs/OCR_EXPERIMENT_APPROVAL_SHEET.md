# OCR Experiment — Approval Sheet

**Milestone 1 only.** Authorises a measurement. Does **not** authorise integration,
rollout, or enabling OCR in the product. Full reasoning: `OCR_ENABLEMENT_PLAN.md`.

**Fields marked `__________` must be filled in before execution approval.**
No provider call may be made until every box in §6 is ticked.

---

## 1. Fixture matrix — public, non-sensitive documents only

No client evidence. No de-identified client evidence. No synthetic Urdu.
Each fixture records source URL, retrieval date, publishing authority.

| # | Slice | Source | Total pages | Held-out docs | Held-out pages | Critical-token examples |
|---|---|---|---|---|---|---|
| 1 | English, typeset | SC / HC English judgments, Pakistan Code | ≥ 8 | ≥ 2 | ≥ 4 | ≥ 12 |
| 2 | English, photographed | Public English notices, photographed | ≥ 8 | ≥ 2 | ≥ 4 | ≥ 12 |
| 3 | Urdu, typeset | Pakistan Code Urdu text | ≥ 8 | ≥ 2 | ≥ 4 | ≥ 12 |
| 4 | Urdu, scanned | Public scanned orders, cause lists | ≥ 8 | ≥ 2 | ≥ 4 | ≥ 12 |
| 5 | Urdu, photographed | Public notices / gazette, photographed | ≥ 8 | ≥ 2 | ≥ 4 | ≥ 12 |
| 6 | Mixed Urdu/English | Any public document with both scripts | ≥ 8 | ≥ 2 | ≥ 4 | ≥ 12 |
| | **Total** | | **≥ 48** | **≥ 12** | **≥ 24** | **≥ 72** |

**Split by document, never by page** — 70% tuning / 30% held-out. Held-out scored
**once**, after configuration is frozen.
**A slice below any minimum reports `NOT_EVALUATED`, which is not a pass.**

**Transcripts:** human, Urdu-fluent, never OCR or LLM. Held-out set
**double-transcribed** with disagreements resolved before scoring. Each critical
token annotated with its **field** and **occurrence index**.

---

## 2. Scoring formulas

Two separately named results. **Neither may be quoted as "the" accuracy.**

**`primary_end_to_end`** — the only figure judged against thresholds.
Denominator is every eligible reference page. A page that errors, times out, is
refused, or returns nothing is scored as **empty output**.

```
corpus_CER = Σ edit_distance(reference, hypothesis)  /  Σ len(reference_characters)
corpus_WER = Σ word_edits(reference, hypothesis)     /  Σ len(reference_words)
```

Summed edits over summed reference lengths — **never the mean of per-page
percentages**.

**`successful_pages_only`** — same formulas over pages that returned output.
**Diagnostic only.**

| Rule | Behaviour |
|---|---|
| Empty reference page | Excluded from CER/WER; reported as `empty_reference_pages` with a count of spurious characters produced |
| CER/WER > 1.0 | **Uncapped**, reported as measured. Capping would hide hallucination |
| Coverage | Pages producing any output, reported separately |
| Omission rate | Reference tokens absent from hypothesis, reported separately |

**`critical_token_presence`** — whole-identifier presence (existing metric).
**Demonstrated limitation:** `fine 1000 imprisonment 3 years` vs
`fine 3 imprisonment 1000 years` scores **1.0** while the meanings are swapped.
**It must never be presented as evidence that dates, amounts or section references
were correctly associated.**

**`critical_field_accuracy`** — token correct **and** in the correct field at the
correct occurrence index. This is what the threshold column below is judged on.
If not implemented, that column reports `NOT_EVALUATED`.

- [ ] Implement `critical_field_accuracy`, **or**
- [ ] Run presence-only and accept that field correctness cannot be claimed

---

## 3. Model and configuration

| Field | Value |
|---|---|
| Provider | Google Gemini API |
| Model id | `__________` *(confirm against live model list at approval)* |
| Temperature | `0` |
| Max output tokens | `__________` |
| Prompt | one fixed string, recorded verbatim in the report |
| Render DPI | `300` |
| Image format | PNG, one page per call |
| Retries | ≤ 2, exponential backoff, **counted against budget** |
| Concurrency | ≤ 2 calls in flight |
| Harness version | `1.1.0` *(bumped: new engine + new metric)* |

**Service terms confirmed before approval:**

- [ ] Tier used does **not** train on submitted content
- [ ] Data-retention period acceptable: `__________`
- [ ] Processing region acceptable: `__________`

---

## 4. Acceptance thresholds

Registered **before any measurement**. Applied to `primary_end_to_end`.

| Slice | CER | WER | `critical_field_accuracy` |
|---|---|---|---|
| English, typeset | ≤ 0.02 | ≤ 0.05 | ≥ 0.99 |
| English, photographed | ≤ 0.05 | ≤ 0.12 | ≥ 0.97 |
| Urdu, typeset | ≤ 0.10 | ≤ 0.25 | ≥ 0.95 |
| Urdu, scanned | ≤ 0.15 | ≤ 0.35 | ≥ 0.90 |
| Urdu, photographed | ≤ 0.20 | ≤ 0.45 | ≥ 0.85 |
| Mixed Urdu/English | ≤ 0.15 | ≤ 0.35 | ≥ 0.90 |

**These numbers are proposals, not derived from any measurement of this system.**
Their stated rationale — that a reviewer could correct output faster than retyping —
is **untested**.

- [ ] Measure correction-vs-retyping time and set thresholds from it, **or**
- [ ] Keep these numbers and record the rationale as **ASSUMPTION (untested)**

**Failing the thresholds is an acceptable outcome and ends the plan at Milestone 1.**

---

## 5. Budget

```
total_cost = Σ over every call ISSUED — including retries, concurrent calls,
             and calls whose response was discarded —
             of (input_tokens × input_rate) + (output_tokens × output_rate)
```

| Field | Value |
|---|---|
| Input price / 1M tokens | `__________` |
| Output price / 1M tokens | `__________` |
| **Approved ceiling (USD)** | `__________` |

**Enforcement, in the runner:**

1. **Pre-flight reservation** before dispatch — worst-case cost of the call plus its
   permitted retries. Taken before dispatch so two concurrent calls cannot both pass
   a check the budget covers once.
2. **Unknown-cost rule.** A call that times out or returns no usage metadata was
   likely billed. Its reservation is **held, not released**. Missing usage is never
   treated as zero.
3. Two figures, **never summed into one headline**:
   - `confirmed_cost` — from reported usage
   - `unknown_exposure` — worst case for unreconciled calls, still reserved
4. Ceiling enforced against **`confirmed_cost + unknown_exposure`**.
5. Run **stops** at the ceiling, reporting `BUDGET_EXHAUSTED` and the pages not
   attempted. It does not silently truncate the fixture set.
6. Report states approved ceiling, `confirmed_cost`, `unknown_exposure`, calls
   issued, and unreconciled call count. A run ending with non-zero
   `unknown_exposure` is reported as **estimated, not final**.

No cost-per-page estimate is given: it would require a token count this plan has
not measured.

---

## 6. Approval

Milestone 1 execution requires **all** of the following.

- [ ] **#1 — Fixtures** (§1) — public only, all six slices meeting minimums
- [ ] **#2 — Thresholds** (§4) — fixed before any measurement
- [ ] **#3 — Threshold rationale** (§4) — measured, or labelled ASSUMPTION
- [ ] **#4 — Field-accuracy metric** (§2) — implemented, or presence-only accepted
- [ ] **#5 — Model, configuration, service terms** (§3) — all blanks filled
- [ ] **#6 — Budget** (§5) — prices and ceiling filled, enforcement in place
- [ ] **#7 — Authorisation to run**, accepting that failure ends the plan

**Signed:** `__________`  **Date:** `__________`

**Not authorised by this sheet:** product integration (#8), review-to-analysis
workflow choice (#9), rollout (#10), enabling `ocr_enabled` (#11).
**Product OCR remains disabled.**
