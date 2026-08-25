# Citation Verification — Session Report

**Attorney.AI** · Muhammad Usama (SP23-BCS-069), COMSATS
Commits `3da1650 → 11952b2 → b619818` · 25 August 2026
Test suite: **943 → 958 → 965** passing

Written for the FYP report. Every figure was measured against the live corpus at
the time stated; none is estimated. Where something is assumed rather than
verified it is listed in §5 rather than left inline.

---

## 1. Problem statement: three axes, not one

A legal AI that invents a citation is worse than one that says nothing. The
industry benchmark is not reassuring — the Stanford RegLab / *Journal of
Empirical Legal Studies* study measured purpose-built commercial tools with
proprietary citators behind them at **17% (Lexis+ AI)** and **33% (Westlaw
AI-Assisted Research)** hallucination, against a vendor claim of "100%
hallucination-free linked citations".

Their definition of hallucination includes **misgrounding**: citing a real,
correctly-formatted authority that does not support the proposition. That
distinction organises this entire subsystem into three independent questions:

| Axis | Question | Industry tool | Status here |
|---|---|---|---|
| **Existence** | Does this citation exist? | citator | ✅ shipped |
| **Currency** | Is it still good law? | citator (red flag) | ✅ shipped this session |
| **Support** | Does it say what you claim? | attribution / NLI | ❌ measured, not shipped |

The design commitment that runs through all three is that **"I cannot tell you"
is a first-class verdict**. A checker that answers "not found" for a provision it
never had any way to see is not checking anything — it is manufacturing false
accusations, and a lawyer burned by one will discount the flag that mattered.

Verdicts as they now stand:

```
VERIFIED        found in the corpus and still in force
NOT_IN_CORPUS   absent from a statute held densely enough for absence to mean
                something — the fabrication flag
OMITTED         the Act itself declares this section repealed        (NEW)
UNVERIFIABLE    we cannot speak to it either way
```

Even the gold standard supports keeping this advisory: **Shepard's misses 23% and
KeyCite 25%** of negative treatment, and the literature's own conclusion is that
relying on citator symbols alone is risky. Nothing here blocks a filing.

---

## 2. What shipped

### 2.1 Ceiling contamination fix

**Problem.** `highest` sets the density ratio, and density decides which statutes
may accuse a citation of being fabricated. A single stray section number wrecked
it.

**All 43 statutes were scanned**, not only the two already known:

| Statute | Ceiling | Ratio | Density |
|---|---|---|---|
| Christian Marriage Act 1872 | 347 → **88** | 0.23 → **0.91** | sparse → **DENSE** |
| Special Marriage Act 1872 | 261 → **29** | 0.11 → **0.93** | sparse → **DENSE** |

**2 of 43 affected.** Each by exactly one chunk — the Christian Marriage Act's
`s.347` is a page-number artifact whose text reads *"347. [Petition when Marriage
Registrar…] Omitted by the Federal…"*.

**The scan changed the algorithm.** A plain ratio-to-previous rule flagged eight
candidates, but **six were the rule's own artifact**: in a three-section act the
largest relative jump is `1 → 2`, a 2.0× ratio that a ratio-only rule ranks
alongside `88 → 347`. It would have discarded ss.2 and 3 from a three-section
statute and left one section standing.

**The density model therefore requires four guards, not one:**

| Guard | Value | Why it exists |
|---|---|---|
| ratio to previous | ≥ 3.0 | a doubling can be genuine renumbering |
| absolute gap | ≥ 20 | kills the `1 → 2` small-statute case |
| fraction discarded | ≤ 5% | removing a fifth is truncation, not outlier removal |
| minimum kept | ≥ 20 | below the dense floor, trimming has no upside |

The ratio floor was **initially set at 1.5 and raised to 3.0** when a test case of
30 sections plus one at s.61 was trimmed — an act that may genuinely run to s.61
with 31 sections missing, which would have been handed flagging rights it had not
earned. The two real instances sit at 3.9× and 9.0×, so they are unaffected.

**Safety property.** Outliers are trimmed from the *ceiling* but **kept in the
index**. A chunk labelled s.347 is still a chunk we hold, so citing it must
verify. Removing it from `sections` would convert a cosmetic density problem into
a false accusation. Verified live: `s.347` and `s.261` both return `VERIFIED`.

**Result: statutes able to flag 19 → 21.** Flag rate on recorded traffic
unchanged at 0.0%.

### 2.2 CrPC omission fix

**Diagnosis first.** Rather than assume "missing text" or "broken regex", all
four processing layers were traced:

```
raw/*.pdf  →  processed/text/*.txt  →  chunks/*.json  →  Chroma
```

- PDF → text ratio **0.96** — extraction lost nothing wholesale
- ss.206, 210, 220, 270, 300, 336, 450 are absent **from the PDF itself**
- their only occurrences are cross-references and Second Schedule table rows
  (`"270 dangerous to life"` is PPC 270 in CrPC's schedule of offences)

**The finding.** The source declares its own casualties, verbatim:

```
266--336. [Omitted].
```

Those 71 sections are the jury-trial provisions, abolished in Pakistan.
`SECTION_RE` consumes the first dash then requires whitespace, so the declaration
was invisible — and all 71 sections were counted individually against our
coverage. **Twelve such ranges exist in the CrPC alone.**

So the answer was **both** a source gap (correctly — the sections do not exist)
and a splitter blindness (to the *reason*).

| | Before | After |
|---|---:|---:|
| CrPC density | **0.77** (sparse, could not flag) | **0.998** (dense) |
| Sections correctly classified | — | **407 of 408 in force** |
| Sections excluded as repealed | 0 | **157** |
| Statutes able to flag | 21 | **22** |

Corpus-wide: **185 omitted sections** across 4 statutes (CrPC 157, Transfer of
Property 12, Police Act 12, Limitation Act 4).

**New `OMITTED` verdict**, checked **before** existence. A repealed section may
still have a shell chunk in the corpus; check order is the whole difference
between a warning and a dead provision in a live filing. It is a distinct verdict
because *a repealed citation is a worse error than a fabricated one* — the number
is real, the text once was, and only currency betrays it, so a lawyer skimming
the draft has nothing to notice.

**One fix was tested and deliberately rejected.** s.468 is a live section the
splitter drops because the source writes `468, Procedure on accused appearing…`
with a comma. Widening the heading pattern was measured over the whole document:
**4 matches, 1 genuine — 25% precision**. The false ones are not schedule rows
but line-wrapped prose ending in `<number>,`, and one is a statute *year*
(`1872, Section 91…`). A stricter rule separates them 1/1, but it is calibrated
on a single positive example, and changing the shared splitter would re-ingest
10,042 chunks across 43 statutes to recover **one section out of 408**. Not
shipped; the cost is recorded in a test.

### 2.3 Regression tests at each step

| Step | Suite | Added |
|---|---:|---|
| Ceiling fix | 918 → **943** | 12 ceiling + 25 omission tests |
| D-lite + suffix fix | → **958** | fixture validation, suffix regression |
| A1 | → **965** | cosine arithmetic, not-assessable semantics |

Every test pins a failure that actually occurred, including two the work itself
produced (§4.3).

---

## 3. What was measured and **not** shipped

### 3.1 A1 — mismatch detection

Built exactly as scoped: **multilingual-e5-base vectors already in Chroma, no new
model, no GPU, no new dependency.** The assertion is embedded with the `query:`
prefix, compared by cosine against the section's stored `passage:` vectors,
taking the maximum over chunks.

Evaluated against `dlite_v1.json`: 48 pairs, **4 excluded as `known_gap`** (they
test the omission parser, not A1), 13 unassessable (no stored text — 8 fabricated,
5 omitted), **31 scored**.

**Headline — precision on the flag class, at the best operating point
(similarity < 0.79):**

| | |
|---|---|
| pairs flagged | 5 |
| truly misgrounded | 5 |
| **precision** | **1.000** |
| **95% CI (Wilson, n=5)** | **[0.566, 1.000]** |
| recall | 0.294 (5/17) |
| false alarms on supported pairs | **0 / 11** |

**Decision: DO NOT SHIP.** The point estimate reads as a ship. It was not taken,
for three reasons:

1. The CI **spans both band boundaries** (0.70 and 0.90). It does not settle
   which band the result is in, and the pre-commitment says the **lower bound**
   governs: **0.566 < 0.70**.
2. The threshold was **fitted on the same 48 pairs** with nothing held out, so
   1.000 is an *upper* estimate of fresh-data performance.
3. n = 5 flagged is too small to carry a shipping decision whatever it says.

### 3.2 Gross vs same-topic — the result that matters more

| | caught | 95% CI |
|---|---|---|
| `misgrounded_gross` | **5 / 7 = 0.714** | [0.359, 0.918] |
| `misgrounded_same_topic` | **0 / 10 = 0.000** | [0.000, 0.278] |

Zero. Not weak — **no detections at all**, and no threshold can fix it, because
the distributions interleave:

| label | n | min | mean | max |
|---|---:|---:|---:|---:|
| supported | 11 | 0.848 | 0.890 | 0.940 |
| **misgrounded_same_topic** | 10 | **0.822** | **0.848** | **0.883** |
| misgrounded_gross | 7 | 0.745 | 0.786 | 0.867 |
| repealed | 3 | 0.793 | 0.801 | 0.816 |

The same-topic range **sits inside the supported range**. This is definitional,
not a tuning failure: cosine similarity measures topical closeness, and a
same-topic error is *by construction* topically close. **The signal and the error
mode are the same quantity.**

Concretely — *"bail in a bailable offence is granted as of right"* cited to
**CrPC s.497 (bail in NON-bailable offences)** scores **0.874**. Bailable vs
non-bailable is the entire legal distinction, and the two sentences score high
because they *are* about the same subject.

Even gross is unreliable: **CrPC s.15 ("Benches of Magistrates")** cited for the
punishment for theft scored **0.867 — above six same-topic pairs.**

### 3.3 A2 is foreclosed, not skipped

**A2 (entailment) was ruled out by a rule fixed before any data existed, not by a
judgement made after seeing the result.**

The pre-commitment, recorded in the plan before A1 was built, was:

> *"A2 does not start unless A1 clears 0.70 — if crude topical matching cannot
> separate these, entailment on the same data will not rescue it."*

A1's CI lower bound is **0.566**, which does not clear 0.70. **The rule decides
this; no discretion was exercised.** A2 was not attempted, not deprioritised, and
not skipped for time.

This matters for how the result should be read. The pre-registration exists so
that a favourable-looking point estimate (1.000) cannot be used to justify
continuing, and so that a decision to stop cannot be mistaken for a lack of
effort. Both directions were fixed in advance.

---

## 4. Open problems — updated status

### 4.1 Problem ① — existence ≠ relevance · **partially addressed, still open**

| | Status |
|---|---|
| Gross topic mismatch | Detectable at 0.714 recall, **but not shipped** — see §3.1 |
| Same-topic wrong section | **Undetectable by this approach.** 0/10, structurally |

A solution requires something this project has **not tested**:

- **Entailment (NLI)** over `(assertion, section text)` pairs, with verdicts
  `SUPPORTED / UNSUPPORTED / NOT_ASSESSABLE`. Foreclosed here by pre-commitment
  (§3.3), and independently risky: generic NLI is trained on short news and
  encyclopedia pairs and is weakest exactly where legal text lives — long
  clause-heavy sentences whose meaning inverts late (*"unless"*, *"subject to"*,
  *"save as provided"*). A cross-encoder was already tried and rejected once on
  this project for a related task.
- **A legal-domain-tuned model**, which would need domain training data this
  project does not have and no GPU to train on.

Neither has been evaluated here. **No claim is made about whether either would
work.**

### 4.2 Problems untouched this session

| # | Problem | Status |
|---|---|---|
| ② | No repeal awareness | **Now partly closed** — `OMITTED` covers range-declared repeals in 4 statutes. PPC's footnote style remains unparsed (§5). |
| ⑤ | Case law can never be flagged | **Untouched.** 502 LHC judgments cannot support any claim of absence. A fabricated case citation and a real one we do not hold are indistinguishable. Closing this needs a law-report corpus — a licensing question, not an engineering one. |
| ⑥ | Small statutes cannot flag even when complete | **Untouched, accepted.** The 20-section floor refuses MFLO at 13/13. The corpus cannot distinguish "complete at 13" from "truncated at 13". |
| ⑦ | Sample size | **Still small.** The 0.0% flag rate rests on 17 answers carrying parseable citations. Enough to show the checker is quiet; nowhere near enough to justify blocking a filing — which is why it is advisory. |
| ⑧ | Parser deliberately under-counts | **Untouched, by design.** A bare `PPC 302` with no section marker is not parsed, because that shape is also how a statute year is written. |
| — | s.468 comma gap | **Documented, not fixed** (§2.2). One live section of 408. |

### 4.3 Two errors this session produced and corrected

Recorded because a report that lists only successes is not a measurement.

**(a) A false claim I repeated across three modules and a published report.**
I stated many times that this system *"cited PPC 302 (murder) for a stamp-duty
question and for a tenancy question"*, calling both nonsense. **That was wrong.**
All seven recorded s.302 mentions read *"PPC Section 302 is **not applicable**
here as the provided sections are from the Transfer of Property Act 1882"* — the
model correctly **rejecting** the section. The grounding parser counted the
mention as a citation because it does not read negation. Corrected in
`citation_grounding.py` and the report script.

The genuine logged misgrounding is stronger evidence anyway: asked *"how many days
do I have to file an appeal"*, the system produced **"PPC Section 152 — Limitation
for appeals to the Court of a District Judge"**. PPC 152 is *"Assaulting or
obstructing public servant when suppressing riot"*. There is no limitation
provision in the Penal Code at all — **152, 155 and 156 are Articles of the
Limitation Act's First Schedule**, reattributed to the PPC. The same
two-numbering-spaces confusion that caused this project's own false-accusation
bug.

**(b) A false omission, caught by the eval fixture's ground-truth check.**
The Limitation Act was reporting **s.5 as repealed**, because

```
5.  Extension of period in certain cases.
5A. [Repealed]              ← (\d+)[A-Z]? captured "5", swallowing the suffix
```

Section 5 is the **condonation-of-delay** provision, pleaded in a large share of
civil appeals. Telling a lawyer it had been deleted is a false accusation, and a
more convincing one than a missing-section flag because it sounds authoritative.
The suffix is now captured and lettered repeals are skipped entirely. Verified at
the **shared parser level** and re-checked against PPC's lettered sections
(`216-B`, `310A`, `365B`, `371B`, `496A–C`): none carry omission declarations, so
PPC was never affected. Corpus-wide, **only the Limitation Act changed** (5
omissions → 4).

---

## 5. Assumed, not verified — consolidated

Everything across the session that rests on inference rather than measurement,
gathered in one place.

| # | Assumption | Risk if wrong | Where it bites |
|---|---|---|---|
| 1 | **Bundled statute PDFs are authoritative.** Omissions were read from the PDFs in `knowledge_base/`, **not cross-checked against the Punjab Gazette or official Gazette of Pakistan.** | A section wrongly marked repealed produces a false `OMITTED` — the most convincing kind of false accusation. | All 185 omitted sections |
| 2 | **`[Repeated]` is OCR for `[Repealed]`.** Corroborated — all 4 occurrences sit in repeal contexts, one reads *"[Repeated by the Federal Laws (Revision and Declaration) Act, XXVI of 1951]"*, and the instance in question sits directly beneath `3-24. [Repealed].` — but it is still an inference. | ss.26–27 wrongly marked repealed | CrPC ss.26–27 |
| 3 | **PPC's footnote-style omissions are unparsed.** PPC declares omissions as `"The following was omitted by A.O. 1961"` annotating sub-sections. The parser reads only range and single-line declarations. **A statute reporting zero omissions has not been shown to be free of repealed content.** | Repealed PPC sections verify cleanly | PPC entirely; 185 is a **lower bound** |
| 4 | **D-lite is SINGLE-ANNOTATED.** One annotator, no second pass. **No inter-annotator agreement was measured and none is claimed.** | Label noise is unquantified; every A1 figure inherits it | All of §3 |
| 5 | **A1's threshold is fitted on its own evaluation set.** 48 pairs is too few to hold any out. | Reported precision is optimistic | §3.1, stated in the tool output |
| 6 | **s.347 and s.261 are page-number noise, not real sections.** The chunk text supports it; the source PDFs were not opened to confirm. Affects only the ceiling — both still verify either way. | Two ceilings slightly wrong | §2.1 |
| 7 | **`_MAX_RANGE = 200` and the four trimming constants are judgement calls**, calibrated against 2 real instances (3.9×, 9.0×) and the widest real range (71). Conservative in the safe direction, but not derived. | Mis-set thresholds silence or over-flag statutes | §2.1, §2.2 |
| 8 | **Fabricated pairs in D-lite are synthetic**, as are 41 of 48 pairs overall; only 7 are drawn from logs. | Synthetic failures may be easier than real ones | §3 |

---

## 6. Change surface — confirmation

Verified by diffing `c6198de..b619818` over `backend/app` and `frontend/src`.

**User-facing verdict behaviour changed in exactly three ways, all previously
reviewed and approved:**

1. **New `OMITTED` verdict** — plus a `counts.omitted` field and the updated
   `limits` string, displayed in both the client and lawyer document panels.
2. **Density corrections** — Christian Marriage Act and Special Marriage Act
   (ceiling), and CrPC (omission-aware denominator). These three statutes gained
   the ability to return `NOT_IN_CORPUS`.
3. **Limitation Act s.5 corrected** from `OMITTED` back to `VERIFIED` — the
   suffix-bug fix in §4.3(b). *Not in the original scope list; surfaced here
   because it is a live verdict change.*

**No API schema changed in this range** (`backend/app/schemas/` untouched — the
`ReviewQueueItem` field was the prior step). **A1 is not wired in**: `app/`
contains no import of `mismatch_detection`, confirmed by grep. `citation_grounding.py`
changed only in docstring text.

---

## 7. One-paragraph summary for the report

> The system separates existence, currency, and support as three independent
> axes, and reports what it cannot check as a first-class verdict rather than
> folding it into a pass or a failure. Existence and currency ship: the corpus
> now measures coverage against sections still in force, which raised CrPC from
> 0.77 to 0.998 and let the second most cited criminal statute in the country
> flag a fabrication for the first time, and a distinct `OMITTED` verdict catches
> the citation a lawyer cannot catch by reading — a real section the legislature
> has deleted. Support does not ship: embedding similarity detects gross
> subject-matter mismatch at 0.714 recall but **zero** same-topic mismatch, and
> the distributions interleave, so this is a structural limit rather than an
> unturned threshold. The follow-on entailment work was foreclosed by a rule
> written before the data existed. None of the tools in the Stanford study
> publishes a false-accusation rate; this one does, and drove it from
> 100%-of-flags-wrong to zero.
