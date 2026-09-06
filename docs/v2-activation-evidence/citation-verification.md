# Citation verification of the 19 migrated revisions — 2026-09-06

Read-only throughout. Mongo was opened with a `read`-only credential, asserted
before the first query; ChromaDB was opened on a **byte-verified copy** of the
corpus, so the knowledge base itself was never opened by the verification run.
Nothing was written back to Mongo or to the corpus, and the stored
`verification` records on the 19 revisions are unchanged. `DOCUMENTS_V2`
remains `False`.

The run executes the pipeline's own process —
`document_service._verification_record` → `citation_verification.verify_text` —
against each revision's stored `body_text`.

Documents are identified by template only. Their identifiers are production
data and are deliberately not recorded here.

## Result

The first run exposed two defects in the citation parser. Both have since been
fixed (below). Results before and after that fix:

| Outcome | before fix | **after fix** |
|---|---:|---:|
| verified-clean — every citation resolves in the corpus | 4 | **4** |
| partial — ran, no flags, but a citation the corpus cannot check | 1 | **2** |
| **FAILED** — a citation absent or repealed | 0 | **0** |
| ran / no citation found | 13 | **12** |
| verification unavailable — could not run | 1 | **1** |
| *tripwire: zero-citation results contradicted by the document's own text* | *1* | ***0*** |

**No migrated revision cites a provision that the corpus holds densely and does
not contain.** That is the strongest statement this run supports, and it is
narrower than "the citations are sound" — see *Limits* below.

## Why the stored records said `ran: false`

Two causes, not one:

| Reason | n |
|---|---:|
| `ChromaDB client not initialized — call connect_chroma() first` | 18 |
| `urdu_corpus_unsupported` | 1 |

Only the first 18 were re-runnable. The Urdu revision is **unverifiable by
design**: `extraction_profile.verifiable()` is False for the `urdu` profile
because the English corpus cannot match it. Connecting Chroma does not and never
will change that revision's status.

## The corpus that was connected

```
civil_collection            4,648      constitutional_collection   1,736
criminal_collection         3,306      judgments_collection       23,978
family_collection             989      lawyers_collection             20
statutes_collection             0
TOTAL                      34,677 chunks
corpus index: 44 statutes, 3,491 sections, 23 dense enough to flag
```

Store integrity confirmed afterwards by reading both stores read-only: the real
store and the working copy each hold 16 collections, 63,920 embeddings and
515,018 metadata rows. Identical.

## Controls — and the first pair were invalid

A clean verdict is worthless if the checker cannot flag anything, so both
directions are exercised before any result is trusted. The harness aborts rather
than reporting if either control fails.

**The first control was discarded as vacuous.** It probed `section 999999`,
which the parser drops as implausible *before* verification — so it measured the
parser's sanity filter rather than the verifier, and would have reported a
broken checker as working. The valid negative control is a plausible number
inside a statute's own range that the corpus does not hold:

| Control | Probe | Result |
|---|---|---|
| negative | `CPC 1908` s.109 — a real gap in coverage | `NOT_IN_CORPUS` — flags correctly |
| positive | `CPC 1908` s.75 — held | `VERIFIED` |

## Two parser defects, found and fixed

A tripwire re-scanned every zero-citation revision for citation-like wording and
found that **9 of the 13 named an authority the checker had not seen**. Probing
the parser directly established two independent defects, both of which turned a
real citation into "nothing to check" — the most dangerous output this module
can produce, because absence from the report reads as approval.

### Defect 1 — a citation to a statute outside the corpus was dropped

`_NAMED_ACT` already existed to catch exactly this, but was compiled **without
`re.I`**, so only a capitalised `Section` matched. Legal prose overwhelmingly
writes it lowercase, so the citation was dropped entirely:

```
under section 302 of the PPC 1860                                -> 1  VERIFIED
under section 20 of the Prevention of Electronic Crimes Act 2016 -> 0  (none)
under section 17 of the Registration Act, 1908                   -> 0  (none)
```

One migrated `fia_cybercrime` complaint cites **"sections 20 and 24 PECA"** and
was recorded as citing no authority whatsoever. PECA 2016 is not among the 44
statutes held — nor are the Registration Act 1908, Payment of Wages Act 1936,
Factories Act 1934, Electronic Transactions Ordinance 2002 or the Overseas
Pakistanis' Property Act 2024, all of which the migrated drafts rely on.

**Fix.** The case-insensitivity is scoped to the marker alone — `(?i:{_MARKER})`
— because a blanket `re.I` would stop the statute-name group's `[A-Z]` from
requiring Capitalised Words and let ordinary prose such as "of the act" become a
citation. A test pins that distinction. A small `_UNHELD_ABBREV` map was added
for acronyms (PECA, ETO, ATA, CNSA, NAO) that the named-act pattern cannot see
because no "... Act 2016" is spelled out.

The verdict for these is **UNVERIFIABLE, never `NOT_IN_CORPUS`.** Absence from
a statute we do not hold is not evidence of fabrication, and `NOT_IN_CORPUS` is
the fabrication flag. A test asserts `is_flag is False` for them.

### Defect 2 — plural section lists were dropped or half-parsed

Every pattern anchored a *single* number directly against the statute name:

```
under section 302 of the PPC 1860                  -> 1   [302]
under sections 302 and 324 of the PPC 1860         -> 0   []        both lost
under sections 302, 324 and 337 of the PPC 1860    -> 0   []        all three lost
under section 302 and section 324 of the PPC 1860  -> 1   [324]     302 silently lost
u/s 302 PPC                                        -> 0   []
```

`u/s 302 PPC` is the ordinary shorthand in Pakistani pleadings — how the charge
is written on the face of an FIR — and matched no pattern at all. The fourth row
is the worst: it returns a confident single verified result while discarding the
other citation, so the record reads "1 verified, 0 problems" for a draft
carrying an unchecked provision. **Dropping one member of a list is worse than
dropping all of them, because the output looks complete.**

**Fix.** `_SECTION_LIST` captures the whole run and `add_list()` splits it into
one citation per member. A repeated capture group cannot be used: Python keeps
only its final match, which is precisely how the earlier members disappeared.
`u/s` was added to the marker. The separator admits only a comma, "and" or "&",
optionally followed by a repeated marker, so intervening prose cannot
manufacture a phantom citation — pinned by a test.

### Effect on the migrated estate

The `fia_cybercrime` complaint now reports

```
UNVERIFIABLE | Prevention of Electronic Crimes Act 2016 s.20
UNVERIFIABLE | Prevention of Electronic Crimes Act 2016 s.24
```

instead of "no citations found". The tripwire count fell from 1 to 0.

**Neither defect was introduced by the migration.** Both are in the citation
checker and affected V1 generation identically.

## Regression tests

`backend/tests/test_citation_verification.py`, +160 lines, **0 removed**. No
existing test was changed or weakened.

| | |
|---|---|
| New test functions | **14** (27 instances after parametrisation) |
| Suite before | 177 passed |
| Suite after | **204 passed** |
| Wider sweep (`-k "citation or corpus or citator or statute or verif or grounding"`) | **521 passed, 1 skipped** |

**Proof the tests are real.** The original parser was restored from git and the
new tests re-run against it: **22 of the 27 instances fail.** The 5 that pass in
both directions are deliberate guard tests pinning behaviour that must *not*
change — capitalised `Section`, statute-name case sensitivity, the phantom-
citation guard, the statute-year guard, and single-section parsing.

Added:

```
test_a_statute_we_do_not_hold_is_surfaced_not_dropped        (5 params)
test_an_unheld_statute_is_never_accused_of_fabrication
test_lowercase_section_is_not_a_reason_to_miss_a_citation
test_the_statute_name_is_still_case_sensitive
test_a_comma_before_the_year_does_not_split_one_statute_in_two
test_an_acronym_for_an_unheld_statute_is_seen                (3 params)
test_the_peca_citation_that_started_this
test_every_section_in_a_list_is_captured                     (8 params)
test_no_member_of_a_list_is_silently_discarded
test_a_list_member_that_is_absent_is_still_flagged
test_a_lettered_section_survives_a_list
test_prose_after_a_number_does_not_become_a_phantom_citation
test_a_statute_year_is_never_read_as_a_list_member
test_single_section_parsing_is_unchanged
```

## Limits — what this run does NOT establish

That the 19 documents' citations are sound. In particular:

* **12 revisions had no citation checked at all.** Those name a statute without
  a section number ("under the Registration Act, 1908"); an existence-checker
  has no provision to check. Widening the parser to bare statute names is a
  separate design decision and was not taken.
* The Urdu revision is permanently outside what this corpus can check.
* Even `VERIFIED` is existence-only. The module says so itself: *"A real,
  in-force provision cited for something it does not say still reads as
  VERIFIED."* Repeal detection is a stated lower bound, and case law can never
  be marked absent because the corpus is far too narrow for absence to mean
  anything.

**Only the four verified-clean revisions carry positive verification evidence.**
The remaining 15 should be treated as unverified pending a lawyer's review.

## The results were persisted — 2026-09-06

*Superseded: this section previously read "the stored records still say
`ran: false`; updating them is a write, and was not authorised."*

Authorised and written. One field, `verification`, on the 19 revisions carrying
the migration id. Nothing else.

| | |
|---|---|
| Written | **19** · already identical 0 · skipped 0 |
| Gate | the same two controls as the read-only harness — nothing is written unless the checker demonstrably flags an absent section and verifies a held one |
| Undo | every prior value dumped to `v2-verification-before-<stamp>.json` **before** the first write |
| Concurrency | compare-and-set on `(_id, migration_id)`; a revision that moved underneath would be skipped and reported, never overwritten |

Stored state, re-read independently under a `read`-only credential rather than
trusting the writer's own read-back — **19 checks, all pass**:

```
verification.ran == True  : 18 of 19
verification.ran == False :  1 of 19   (the Urdu pleading, by design)
buckets as stored: clean 4 · partial 2 · FAILED 0 · no-citations 12 · unavailable 1
```

Also confirmed: every record carries `ran`, `checked_at`, `summary`, the
disclosure `scope` and the `corpus` it was checked against; every revision still
matches the approved plan exactly; every document still points at its planned
revision; no extra or orphan revisions; no document gained a `verification`
field; counts unchanged at 19 and 19.

**One correction worth recording.** The first version of that confirmation
compared each revision against the pre-migration backup and reported 19
failures. The check was wrong, not the data: the backup was taken *before* the
migration, when `document_revisions` held **0 rows**, so every revision is
legitimately absent from it. The meaningful baseline is the approved plan plus
the migration's own invariants, and against that everything holds.

`checked_at` is the date of this check, not of the documents' generation. These
are legacy PDFs checked at migration time, and the timestamp says so.

## Scope of this work

`apply()` not re-run; no indexes created or dropped; no artifacts, PDFs or
notifications touched; no credentials changed; nothing deleted; `DOCUMENTS_V2`
still `False`. The only production write was the `verification` field described
above.
