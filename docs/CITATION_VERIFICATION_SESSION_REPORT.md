# Citation Verification — Session Report

**Attorney.AI** · Muhammad Usama (SP23-BCS-069), COMSATS
Commits `3da1650 → 11952b2 → b619818` · 25 August 2026
Test suite: **943 → 958 → 965 → 970 → 993** passing

Written for the FYP report. Every figure was measured against the live corpus at
the time stated; none is estimated. Where something is assumed rather than
verified it is listed in §5 rather than left inline.

---

## 0. Scope and Claims

**Adopted as formal scope for all current and future document types.** This is
the complete set of claims this system makes about a generated document. Nothing
outside it is claimed, and the boundaries are as load-bearing as the capability.

> **We do not claim that any generated document is correct or complete.**
>
> We claim only the following four things.
>
> **1. Citations are checked.** Every citation in a generated document is checked
> against the corpus — confirmed to exist, and, where checked, confirmed to still
> be in force.
>
> **2. Where a statute defines the content, we draft the whole instrument.**
> Where a document's required contents are fully enumerated by statute — as with
> the Guardians and Wards Act 1890 s.10, or the Succession Act 1925 s.372 — the
> full instrument is drafted from that statute.
>
> **3. Where content is delegated elsewhere, we generate only the grounded part
> and say what is missing.** Where the contents are delegated to rules or to an
> authority we do not hold — the Wakalatnama to the High Court Rules and Orders,
> the succession certificate form to NADRA under s.7 of the Punjab Act 2021 — we
> generate only the verifiably grounded portion and disclose the gap explicitly.
> We do not invent the missing part, and we do not copy-fill it from any external
> source however official it appears.
>
> **4. A lawyer reviews before filing.** Every client-generated document routes
> to a lawyer for review before filing. That review step is mandatory, and it —
> not the generator — is the safety net.

### Why claim 3 is the one that costs something

It is the claim that makes us ship less. Two of the three document types attempted
in this work hit it: the succession certificate form is prescribed by NADRA under
s.7 of the Punjab Act, and the Wakalatnama's contents come from High Court Rules
and Orders. In both cases a plausible document could have been produced by copying
a published form — and in both cases the published forms carry either an explicit
copyright assertion (LHC) or a disclaimer against official use (IHC).

Filling those gaps would have produced something that looked more finished and was
less true. The pattern is worth stating plainly, because it is a property of the
domain rather than of this project:

> **Pakistani court forms are largely prescribed by High Court Rules and Orders,
> or delegated to an authority — not enumerated in statutes.** Drafting from the
> statute works where the statute lists the particulars, and reaches a ceiling
> where it does not.

### Why claim 4 is not a hedge

Claim 1 is narrower than it sounds. A verified citation is a citation that
*exists* — not one that supports the proposition it is cited for. §3 of this
report measures that gap directly and does not close it. So the lawyer's review
is not a legal disclaimer bolted on at the end; it is the control that covers what
the automated checks structurally cannot.

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

### 4.2a Problem ⑨ — CPC Order rules collide with body sections · **TRACKED, OPEN**

**Formally tracked, same tier as the Gazette check (§5 #1) and the D-lite
second-annotator pass (§5 #4).** Not merely noted in a session log.

The CPC's First Schedule holds **Orders I–LI**, each restarting its rule
numbering, and **Appendices A–H** restarting again. All of it was ingested into
the same `section_number` field as the 158 body sections:

```
CPC 1908 chunks              : 1,967
distinct section_numbers     :   165
COLLIDING numbers            :    94   (57%)
max provisions on one number :   132
```

`CPC 1908 s.1` stores **Order VII Rule 1** (*"Particulars to be contained in
plaint"*), not the true s.1. `CPC 1908 s.3` stores **Order III Rules 3–4**.
`s.2`, `s.4`, `s.5` do hold the true body sections.

**Why it matters: false assurance, not false accusation.** Order rules occupy
most numbers 1–132, so a citation to a CPC section that does not exist — or has
been repealed — verifies against whichever Order rule shares its number:

```
CPC s.45   -> VERIFIED        CPC s.130  -> NOT_IN_CORPUS
CPC s.100  -> VERIFIED        CPC s.900  -> NOT_IN_CORPUS
```

**Only nine numbers in 1–158 are genuinely empty: 109, 110, 114, 125, 126, 130,
154, 155, 156.** Everything else is occupied by something, so CPC can almost
never return `NOT_IN_CORPUS` in that band. That is the evidence for why this is
worth fixing: the statute is marked DENSE and therefore permitted to flag, while
57% of its section space cannot be resolved to one provision.

**Partly mitigated (Fix 1, shipped).** `Order N Rule M` is now parsed as a
distinct citation type and returned `UNVERIFIABLE` with a stated reason.
Previously such citations matched no pattern at all and vanished from the report
while the summary still said everything checked out — the same silent-omission
failure fixed earlier for unrecognised statutes. Variants handled: `Order III
Rule 4`, `O.III r.4`, `Order III, Rule 4`, `Order 21 Rule 11`, with and without a
trailing Code name.

**Not fixed (Fix 2, open).** Re-ingest the CPC with `order` and `rule` metadata
separated from `section_number`. Effort **M–L**: ~1,967 chunks re-embedded plus
an ingest-script change. Until then a bare CPC section citation in the 1–132
band carries false assurance.

**Explicitly rejected: demoting CPC from dense.** It looks like a cheap interim
fix and is theatre — density gates `NOT_IN_CORPUS`, not `VERIFIED`, so it would
not touch the false-assurance path at all. Recorded so it is not reached for
later.

Diagnosis shared with the Limitation Act Articles bug (§2) and the CrPC
Schedule-II rows: a second numbering space flattened into the first. The cure
differs — there the second space was *absent* and could be routed to
`UNVERIFIABLE`; here it is *present and colliding*, so the parser fix alone
cannot clean the section space.

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
| 1 | ~~**Bundled statute PDFs are authoritative.**~~ **PARTLY RESOLVED — see §6a.** Spot-checked against the official federal consolidation: 7 of 10 checks matched and ss.266–336 confirmed verbatim, but 9 CrPC sections were found to reflect Punjab-only amendments and have been pulled. The remaining 148 CrPC entries plus 28 in three other statutes are still **not** individually Gazette-checked. | A section wrongly marked repealed produces a false `OMITTED` — the most convincing kind of false accusation. | 176 omitted sections (was 185) |
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

## 6a. Post-session finding: jurisdiction/edition mismatch in the CrPC omission map

**Resolved: 6 restored with cited instruments · 1 permanently excluded as a
parser artifact · 2 still genuinely open.** Test suite 970 → **993**.

Assumption #1 in §5 — *"bundled statute PDFs are authoritative, not
Gazette-checked"* — was spot-checked against the **official federal
consolidation at pakistancode.gov.pk** (last amended 2017-02-16, 319 pp). The
site is reachable; the check was performed, not deferred.

### The headline claim holds

The official text reads, verbatim:

```
266­336. [Omitted.]
CHAPTER XXIII[Omitted.]
```

**Seven of ten spot-checks matched**, including every claim the CrPC density fix
depends on: ss.266–336 (with s.270 and s.300 inside it), ss.26–27, ss.206–220
(via `CHAPTER XVIII[Omitted.]`), ss.251–259, ss.443–463, and ss.154/497 confirmed
in force. It also confirmed **s.468 is a live section** — vindicating the
decision in §2.2 to record it as an extraction gap rather than an omission.

> A methodological note worth keeping: the first pass reported *everything* as a
> mismatch. That was my regex, not the map — the official PDF contains **zero
> ASCII hyphens**, using soft hyphens (`\xad`) throughout. Caught and corrected
> before reporting. The same failure mode as the Article/Section bug in §2 and
> the PPC-302 claim in §4.3: a tooling artifact that looks like a finding.

### The mismatch: two editions, not one parser bug

Nine sections disagreed, and the cause is not parsing:

```
bundled:   10.  [Omitted by the Ordinance XXXVII of 2001 dt. 13-8-2001.]
official:  10.  District Magistrate.

bundled:   407. [Omitted by Item No. 140 of Punjab Notification SO(J-II) 1-8/75]
official:  407. Appeal from sentence of Magistrate of the second or third class.
```

**The bundled PDFs are a Punjab-annotated edition**, folding provincial
notifications and the 2001 devolution ordinance into the text; the federal
consolidation does not. ss.10/11/13 concern the office of District Magistrate,
abolished by the 2001 devolution and partially restored since; ss.407/438 were
omitted by **Punjab notification only**.

So whether a citation to s.10 is dead depends on **jurisdiction and date** — which
an unqualified `OMITTED` verdict cannot express. Asserting it is a false
accusation of exactly the kind this subsystem exists to prevent.

### Action taken, and then resolved

The nine were first pulled wholesale pending a jurisdiction decision. Tracing
each one to its instrument then showed that **jurisdiction was not the deciding
factor after all** — the nine were three different problems wearing one label.

| Outcome | Sections | Instrument | Basis |
|---|---|---|---|
| **RESTORED** | 10, 11, 13 | Ordinance XXXVII of 2001, 13-08-2001 | Confirmed: the Ordinance abolished the Executive Magistracy. Punjab resolved to revive the magistracy in 2022 but it was a **proposal only**; Punjab Amendment Act X of 2024 — the most recent amendment to the Code — touches **only s.144**. |
| **RESTORED** | 562, 563, 564 | Probation of Offenders Ordinance XLV of 1960, s.16 | Confirmed independently: s.16 repeals ss.380, 562, 563 and 564 of the Code. **Federal**, so it holds whichever edition governs. |
| **EXCLUDED PERMANENTLY** | 14 | — | **Not an omission.** See below. |
| **STILL HELD** | 407, 438 | Punjab Notification SO(J-II) 1-8/75, 21-03-1996 | Genuinely unconfirmed by any independent source. |

> **A correction to my own earlier report:** I dated ss.407/438 to *1975*. Wrong —
> `1-8/75` is the notification's **file number**; the date is **21 March 1996**.

**s.14 is a live section, and was never a jurisdiction question.** The parser read
it as repealed from a **schedule table row**:

```
... Section 407.  13. Power to sell property alleged ... Section 524.
    14. Repealed.
```

`14.` there is a **row number** in a table of powers, not a section of the Code —
while s.14 itself is *"Special Judicial and Executive Magistrates"*, with
operative text in the same document. Identical failure to the Limitation Act
`5A. [Repealed]` case in §4.3(b): a numbered line that is not a section
declaration. It is excluded permanently rather than fixed in the regex, because
at that point in the text a table row and a section heading are genuinely
indistinguishable by shape.

**ss.407 and 438 were the only two of the nine that were ever Punjab-specific.**
Which reframes what remains: this is a **data-completeness gap, not a
jurisdiction ambiguity**. The question is no longer *which edition governs* but
whether anyone has published the current state of those two sections at all.

### The finding that outlived the jurisdiction question

**ss.562–564 were repealed by a FEDERAL ordinance in 1960, and
pakistancode.gov.pk still prints all three with live headings and no repeal
marker.** The site does mark repeals elsewhere (`111. [Repealed.]`), so this is
an omission in the official consolidation itself.

So the working assumption behind the whole spot-check — that one source could
settle it — was wrong in both directions. **No single source is complete.** The
bundled edition was right about ss.562–564 where the federal portal was stale;
the federal portal was right about s.14 where our parser was wrong.

### Data model: from a boolean to a citation

That is what forced the schema change. A bare `omitted: true` cannot distinguish
a federal repeal from a provincial notification from a parser artifact, and it
cannot tell a lawyer the one thing that lets them check the answer: **which
instrument, and when.** Each entry now carries:

```json
"10": { "status": "omitted",
        "instrument": "Ordinance XXXVII of 2001",
        "date": "2001-08-13",
        "jurisdiction": "federal" }
```

**Existing callers were not rewritten.** Density, `is_omitted`, and the verifier's
branch all still read the same `frozenset[int]`, derived from the richer records
at load time — so enriching the data could not break them. A v1 flat-list file
still loads, so an older generated file degrades rather than silently disabling
omission awareness. Both properties are tested.

**What the lawyer now sees** — no UI file changed, because both panels already
render the verdict's detail text:

> *"CrPC 1898 s.10 was omitted by Ordinance XXXVII of 2001 dated 2001-08-13. It
> cannot be relied on…"*

instead of a bare *"has been REPEALED"*. A provincial instrument is labelled
`(punjab only)`, which is the difference between a fact and a half-truth for a
lawyer filing elsewhere. The 148 entries with no traced instrument keep the
generic wording — **a missing citation never demotes the verdict**, or enriching
the data would have quietly disabled most of the map.

### Effect on CrPC density

| | Original | After the pull | After resolution |
|---|---:|---:|---:|
| Sections in map | 157 | 148 | **154** |
| Sections in force | 408 | 417 | 411 |
| Held of those | 407 | 416 | 410 |
| **Ratio** | 0.997549 | 0.997602 | **0.997567** |
| Dense | ✅ | ✅ | ✅ |
| Statutes able to flag | 22 | 22 | **22** |

Materially unchanged throughout. **The headline CrPC finding never depended on
the nine** — it rests on ss.266–336, confirmed verbatim against the official
text.

### Three open questions — answered

Reproduced verbatim from when they were raised, with what the currency check
settled:

> 1. **Which edition governs** for your users — federal consolidation, or
>    Punjab-annotated? Attorney.AI is Punjab-focused, so the bundled edition may
>    actually be the *right* one for your audience.
> 2. **Are ss.10, 11, 13, 14 currently in force in Punjab?** The 2001 ordinance
>    omitted them; the federal code still lists them.
> 3. **Should `OMITTED` carry jurisdiction and date**, rather than being
>    unqualified?

**(1)** Punjab-applicable — federal base plus provincial amendments, since users
file in Punjab courts. But adopting that answer does **not** validate the bundled
PDF, and the ss.562–564 finding shows the federal portal is not a safe default
either. Both sources are partial.
**(2)** ss.10, 11 and 13 are omitted, confirmed, nothing later reviving them.
s.14 was a parser artifact and is in force.
**(3)** **Yes — implemented above.** This turned out to be the load-bearing
question: the other two could not be answered *at all* without per-section
instrument data.

### Still open

**ss.407 and 438 only.** Punjab-specific, 1996, unconfirmed either way. This is
now a data-completeness gap rather than a jurisdiction ambiguity, and closing it
needs a Punjab source that publishes the current text — not a decision.

---

## 6b. Succession routing: point-in-time verification, not continuous currency

**Succession Act 1925 ingested** from pakistancode.gov.pk — 133 pages, 635
chunks, **388 of 392 sections, ratio 0.9898, DENSE**. Zero ceiling outliers, zero
extraction artifacts; 4 genuine gaps (ss.50, 57, 116, 117). Corpus: 43 → 44
statutes, 3,101 → 3,490 sections, 22 → 23 dense.

It was ingested for one reason: **s.5(b) of the Punjab LAS Act 2021 refers
contested succession cases to the Succession Act 1925**, so without holding the
1925 Act a citation to s.372 could not be checked at all.

### What was verified, and when

ss.**370** and **372** were checked against the official consolidation's own
amendment footnotes:

| Section | Amendments | Outcome |
|---|---|---|
| s.370 | A.O. 1949, F.A.O. 1975, A.O. 1937 — terminology substitutions | CONFIRMED CURRENT |
| s.372 | A.O. 1961 Art.2 & Sch. (w.e.f. 23-03-1956, inserted sub-s.(3)); A.O. 1937 | CONFIRMED CURRENT |

The Punjab Act does **not** amend the 1925 Act: s.12 is an overriding clause, and
s.14 repeals only its own predecessor Ordinance (VIII of 2021). Separately, the
2021 Act was itself amended in 2025 (LXII of 2025), which **inserted "[or a civil
court]" into s.3** — the text the advisor quotes — and omitted s.10.

### ⚠️ The limitation this rests on

**This is POINT-IN-TIME verification, not continuous currency checking.**

`build_omission_map.py` reads `knowledge_base/processed/text/`, which the PDF
ingest path does **not** populate. So the Succession Act 1925 is absent from the
omission map, and a future repeal of s.370 or s.372 **would not be detected
automatically** — the advisor would keep citing them.

Same shape as the CrPC omission-map gap in §6a: the coverage is sound, the
repeal-awareness is not wired. Full integration is separate future work. Until
then the guidance rests on a check made on 25 August 2026, recorded here and in
`app/api/v1/routes/disputes.py`.

### What shipped instead of a form

**No court petition was built.** s.7 of the Punjab Act leaves the form to NADRA,
so drafting one would invent paperwork the statute does not ask for. The feature
is a **route advisor** returning guidance, not a document — no PDF, no
`doc_id`, flagged `is_guidance_not_a_filing`. Every provision it cites goes
through the same citation verifier as a drafted document, and fails open with
`ran: false` rather than withholding the advice.

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
