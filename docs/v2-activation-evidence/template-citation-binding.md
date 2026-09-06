# Template citation binding — 2026-09-06

Code, templates, tests and this document only. No production data was read or
written, no migration re-run, no verification records re-persisted,
`DOCUMENTS_V2` unchanged and still `False`.

## Why

Citation verification of the migrated estate found two parser defects. Fixing
them exposed a third, and the third is the one that matters: **our own
generators were printing citations our own checker could not read.** A citation
the parser cannot see is reported as *"no citations found"* — indistinguishable
in the output from a clean bill of health.

Every citation test until now fed the parser strings a human had written *for
the parser*. Nobody had asked what the templates actually put on the page. So
the question was asked from the producing side: generate every template, read
what it emitted, compare against what the checker sees.

## What the survey found

21 drafting templates, each rendered and re-read.

| | before | after |
|---|---:|---:|
| Templates whose citation the parser **cannot see** | **2** | **0** |
| Templates whose citations the parser reads | 7 | **9** |
| Templates citing at Act level only (no provision named) | 4 | 4 |
| Templates naming no authority at all | 8 | 8 |

### Defect A — `fia_cybercrime`, a gloss list

```
sections 20 — offences against dignity, 21 — offences against modesty,
and 24 — cyberstalking
```

The glosses sit *between* the section numbers and break the list apart. Parsed
to **nothing**. A complaint rested entirely on PECA and was recorded as citing
no authority whatsoever.

The same template had a second path — an intake field, `offence_sections` —
which arrived as "sections 20 and 24 PECA" and parsed fine. **One template, two
citation shapes, one of them invisible.**

### Defect B — `wakalatnama_checklist`, an anaphoric statute

```
an application under section 144 or section 152 of the Code
```

Two problems, and each alone loses the citation:

* `or` was not in the section-list separator, which admitted only `,`, `and`
  and `&`. Both members dropped.
* `"of the Code"` refers back to the Code of Civil Procedure named earlier in
  the sheet. That is ordinary good drafting and completely opaque to a checker
  with no anaphora.

## The fix — producer-side, not parser-side

The tempting response is to teach the parser to read gloss lists. That is an
arms race against our own drafting: every new flourish becomes the next blind
spot, found — if ever — by someone auditing a migration months later.

**New: `app/services/citation_format.py`.** Generators ask for a citation and
get back the one form the parser is tested against.

```
cite("PECA, 2016", ["20", "21", "24"])
    -> "sections 20, 21 and 24 of the PECA, 2016"

cite_with_glosses("PECA, 2016", [("20", "dignity"), ("21", "modesty")])
    -> "sections 20 and 21 of the PECA, 2016 (20: dignity; 21: modesty)"
```

Glosses are useful to a reader and are kept — they just move *after* the
citation, where they cannot interrupt the list. `cite()` **raises** on an empty
section list rather than emitting a bare Act name, so the formatter cannot be
used to reintroduce the gap it closes.

| Change | Where |
|---|---|
| `fia_cybercrime` default offences become structured `(section, gloss)` pairs, rendered canonically | `pdf_generator.py` |
| `fia_cybercrime` intake field `offence_sections` is normalised **when it reads as a section list**, and printed verbatim otherwise | `pdf_generator.py` |
| `wakalatnama_checklist` names the Code of Civil Procedure 1908 in full | `pdf_generator.py` |
| `_SECTION_SEP` accepts `or` as well as `and` / `,` / `&` | `citation_verification.py` |

### One correction, caught by an existing test

The first version of the wakalatnama fix rendered `cite(CPC, ["144", "152"])`,
producing *"sections 144 **and** 152"*. `test_duration_and_what_counts_as_
proceedings_are_stated` failed, and it was right to: **Rule 4(3) lists
alternatives.** Rewriting its "or" to "and" would have misstated the provision
to suit the parser.

Rule 4(3)'s own wording is now preserved verbatim — `"section 144 or section
152 of the Code of Civil Procedure 1908"` — and the parser learned `or` instead.
Only the anaphora was changed. An existing test caught a legal-meaning error
that no citation test would have.

## The binding test

`tests/test_template_citation_binding.py` — **23 test functions, 483
instances** (396 passed, 85 skipped, 2 xfailed). Every template is rendered
across seven field variants, because one sample dict reaches only one side of
every `if`. A variant is skipped where that template prints no provision, which
is why the skip count is high and is not a gap.

Three assertions per template/variant:

1. **Every provision the page prints is one the parser read.** Not "some
   citation parsed" — a *partial* miss is the more dangerous shape, because the
   report looks populated while a citation is missing from it.
2. **No template emits a citation that flags.** Our own generator must never
   assert a provision that reads as fabricated or repealed.
3. **Every parsed citation resolves to a named statute** — what `"of the Code"`
   failed.

Plus a **static guard** that reads every string literal in `pdf_generator.py`
via `ast` and requires any hand-written citation to parse. The rendered tests
only cover branches the sample fields reach; this one covers a citation added to
a branch nobody exercises.

### Why it does not assert `VERIFIED`

A template may legitimately cite a statute this corpus does not hold — PECA is
real law and is not among the 44. The honest verdict there is `UNVERIFIABLE`,
and demanding `VERIFIED` would pressure someone into deleting a correct citation
or whitelisting a statute we cannot check. What must never happen is a citation
that is **invisible** or that **flags**.

### A bare Act is not a citation

Pinned explicitly: `"registered under the Registration Act, 1908"` parses to
nothing and yields no verdict. An existence checker verifies (statute, section)
pairs; an Act name alone has no provision to check and must never be counted —
least of all as `VERIFIED` — merely because the Act is real.

The hermetic fixture corpus means these run in CI with no ChromaDB.

## Two legal regressions, caught at the release gate

The first version of the `fia_cybercrime` fix made the document more
machine-readable and, in doing so, made it say something else. Neither was
caught by any test; both were found reviewing the diff as a gate. They are
recorded because they are the characteristic failure of citation work.

### 1 — the hedge was dropped

```
was:      offences under the Prevention of Electronic Crimes Act, 2016
          (such as sections 20 - ..., 21 - ..., and 24 - ...)

became:   offences under sections 20, 21 and 24 of the
          Prevention of Electronic Crimes Act, 2016
```

`such as` marked those sections as **illustrative**. Without it the complaint
**asserts** that the conduct constitutes three named offences — a claim a
generated form cannot support, and one the rest of the document is careful not
to make (the DRAFT banner, the generation-scope notice).

Restored, and the short form is now defined before use — `("PECA")` — which is
ordinary legal drafting and happens to parse.

### 2 — unreadable intake was replaced by the default sections

A complainant who described their offences in words got a document alleging
offences under sections 20, 21 and 24 — provisions they never named, with
nothing to indicate the substitution. The old code printed their words.

Now: if `offence_sections` reads as a section list it is cited canonically;
otherwise it is printed **verbatim**. That document then carries no checkable
citation, which is true, rather than a citation nobody chose.

### The sharp edge of fixing 2

The obvious implementation — scrape digits from the field — turns
*"he sent 500 messages"* into **section 500 of PECA**. A fabricated citation is
worse than an unverifiable one; it is exactly what the verifier exists to
prevent, arriving from our own generator rather than a model.

So `citation_format.section_list()` returns `None` unless the field says it is
one: either it carries a section marker (`s.20`, `sections 20 and 24`), or it
contains nothing but numbers, separators and statute short forms (`20, 24`).

### Two more caught while fixing those

* An `esc()` call was added at the interpolation, but that `P()` is not
  `raw=True` and escapes internally — it would have **double-escaped** the
  complainant's own words. Removed, and pinned by a test asserting
  `<b>bold</b>` reaches the page as literal text.
* The "acronym takes no article" rule was too broad and silently changed
  `"of the PPC 1860"` to `"of PPC 1860"`. **An earlier test caught it.** The
  rule was narrowed to bare short forms; the older assertion was left alone.

### Behaviour, as rendered

| `offence_sections` | Output |
|---|---|
| *(absent)* | `under the Prevention of Electronic Crimes Act, 2016 ("PECA"), such as sections 20, 21 and 24 of PECA (…)` |
| `"sections 20 and 24 PECA"` | `under sections 20 and 24 of the Prevention of Electronic Crimes Act, 2016` |
| `"20, 24"` | same |
| `"harassment and stalking"` | `…, including harassment and stalking` — no default sections |
| `"he sent 500 messages"` | `…, including he sent 500 messages` — no s.500 |

## Test counts

| | before | after |
|---|---:|---:|
| `test_citation_verification.py` | 81 | **89** (+8: `or` lists, anaphora, gloss form) |
| `test_template_citation_binding.py` | — | **483** (new, 23 functions) |
| Full backend suite | 3,747 passed | **4,151 passed** |
| Pre-existing failures (uncommitted auth work) | 13 | 13 — unchanged |

The binding suite grew by 18 tests after the gate review, covering the two
regressions above, the `section_list` gate, and markup escaping.

**Proof against the old behaviour**, twice over:

* Templates and the `or` separator reverted to the committed state — **15
  instances fail**, across `fia_cybercrime` (4 variants),
  `wakalatnama_checklist` (6 variants), the three named-defect tests, the
  `or`-list test and the static guard.
* Both gate regressions reintroduced (hedge dropped, defaults substituted) —
  **6 instances fail**: the illustration test, all three verbatim cases, the
  s.500 fabrication test and the markup-escaping test.

Restored in both cases, all pass.

`uploads/docs` delta across the full suite: **0**.

## Remaining gaps — not fixed, and why

**Four templates cite at Act level only.** They name a statute without a
provision, so there is nothing an existence checker can check:

| Template | Names |
|---|---|
| `labour_demand` | Payment of Wages Act 1936; Factories Act 1934 |
| `power_of_attorney` | Registration Act 1908 |
| `rental_agreement` | Rent Restriction Ordinance |
| `wasiyyat_nama` | Electronic Transactions Ordinance 2002; Muslim Personal Law (Shariat) Application Act 1962 |

This is a **drafting** question, not a parser one, and it was left alone
deliberately — changing which provision a pleading relies on is a legal
decision, not a refactor. It is worth taking: a Pakistani court expects *"under
section 17 of the Registration Act, 1908"*, not *"under the Registration Act,
1908"*. Doing so would both improve the documents and bring them inside what
verification can speak to — and only then does ingesting those statutes pay off.

**Eight templates name no authority at all** (`legal_notice`, `nda`,
`plaint_civil`, `written_statement`, `dispute_petition`, `poa_revocation`,
`lawyer_draft`, `urdu_pleading`). Correct for several of them — an NDA is a
contract, not a pleading.

**The gloss-list prose form remains unreadable**, by decision rather than
oversight, and is pinned by a test that says so. The fix is on the producing
side; the parser is not taught to read prose between list members.
