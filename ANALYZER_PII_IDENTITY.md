# Analyzer PII masking — the identity contract (2026-10-04, draft for review)

Written BEFORE the code changes that implement it. It covers what a token
stands for, what may make two mentions "the same person", and what blocks
sending.

## Concepts

| Concept | Meaning | Where it lives |
|---|---|---|
| **mention** | One span `[start, end)` of the ORIGINAL text that refers to a person (or holds another personal detail). | offsets, never words |
| **person identity** | The person that one or more REVIEWED mentions refer to. An identity is established only by (a) the document's own definition (`Kashif Raza (hereinafter "Raza")`), (b) the narrow auto-link rule for a defined party, or (c) an explicit reviewer decision. | an internal identity key per mention |
| **normalised spelling** | Case, spacing and courtesy titles ignored (`name_key`). Useful to FIND mentions and to PROPOSE that they belong together. Never, on its own, proof of identity. | `_norm` / `pii_layers.name_key` |
| **token** | The provider-facing replacement (`[NAME_3]`). One token per reviewed identity; for other kinds, one token per typed value. | issued in text order |

## Required properties

1. All reviewed references to one person receive one token.
2. Different reviewed people receive different tokens, including people with
   identical names.
3. Equal spelling, a shared surname, title or role ALONE never establishes
   identity. A shared spelling is only a proposal, which the lawyer
   confirms by approving the exact request (with its people shown) or
   overrides.
4. Explicit definitions and reviewer-confirmed links can establish identity.
5. An unresolved or conflicting identity decision blocks sending. That
   covers:
   - an invalid link;
   - a cycle;
   - the same spelling designated as two different parties, until a person
     decides.
6. Dates, deadlines, amounts and original evidence stay intact.

## Where the implementation violated it (before this change)

| # | Violation | Kind | Function |
|---|---|---|---|
| V1 | The token key was `(kind, normalised spelling)`. Two people with the same name always shared one token, and nothing let a reviewer separate them. | masking algorithm | `pii_mask.prepare` → `token_for` |
| V2 | The same spelling designated as two parties ("Landlord: Usman Farooq … Tenant: Usman Farooq") was sent with one token and no flag. `party_roles` dropped the conflict silently. | masking algorithm | `pii_layers.party_roles`, `prepare` |
| V3 | The screen offered "Same person as" only on FLAGGED rows and on names the lawyer ADDED. Two already-masked, unflagged mentions of one person (e.g. a name and a professional name) could not be linked, and no mention could be marked as a different person. | UI/API limitation | `PiiConfirmation.jsx`; the API had no `different_person` decision |
| V4 | The simulated reviewer reconciled only flagged and missed spans. Fully masked mentions were never checked against the gold identity, and the loop stopped when there was nothing new to flag or mark. | simulated-reviewer error | `pii_evaluation._missed`, `_review`, `score_document` |
| V5 | Party consistency counted only mentions FULLY covered by a masked span. A party mention left partly or wholly unmasked silently did not count against consistency (the leak metric catches only words of 3+ characters). | scoring error (too lenient) | `pii_evaluation.score_document` |

V5 makes the metric STRICTER, never more lenient. The harness version
changes (`pii-eval.2.1`); frozen results stay as recorded and are not
directly comparable with scores made under the new harness.

## The representation (minimal change)

Inside `prepare`, every masked NAME mention gets an IDENTITY KEY:

- `("spelling", name_key)`: the default PROPOSAL, from the normalised
  spelling (or from an explicit definition or the narrow auto-link, which
  map an alias to the defined full name's spelling);
- `("mention", start, end)`: a mention the reviewer marked
  `different_person`, which becomes a person of its own;
- a reviewer `same_person` link: the source takes the identity key of its
  target mention (exact masked NAME span; chains resolved; invalid targets
  and cycles block).

Tokens are issued per identity key, in text order, so the result does not
depend on the order of the decisions. Other kinds keep one token per typed
value. The encrypted map still holds token → original value (the first
mention's text).

**Older review records:** they never contain `different_person`, so they
keep their meaning. They are stale anyway, because the masking-policy hash
changes with this code, so no old approval can send.

## Who decides, and how the decision is made visible

- **The screen:** a "People" panel lists every masked person token with
  ALL its mentions in the original text. For each mention the lawyer can
  keep it, mark it `different_person`, or link it `same_person` to another
  token. The preview is rebuilt, and the approval covers the exact request,
  so the identity partition is part of what is approved.
- **The simulated reviewer:** it may use gold entity ids ONLY to choose its
  decisions. It reconciles the whole partition for every labelled person,
  not only flagged or missed spans, and records how many identity decisions
  it issued. Its decisions use only what the API and screen can express:
  exact spans, `same_person`, `different_person`.
- **Production** never sees gold labels.

## Implemented (UNCOMMITTED, for review)

- **Masker** (`pii_mask.prepare`):
  - person tokens are issued per identity key, not per spelling;
  - `different_person` makes a mention a person of its own;
  - `same_person` takes its exact target's identity, with chains resolved
    independent of decision order;
  - contradicting decisions on one mention, invalid targets and cycles are
    `link_invalid` and block;
  - the same spelling designated as two parties is flagged
    `identity_ambiguous` until decided; a link's target counts as decided.
- **API** (`pii_confirmation`):
  - `different_person` is accepted on any span;
  - the preview returns `people`: every masked person mention with its
    token, as offsets;
  - the attestation now names the identity check.
- **Screen:** a "People in this request" panel lists every token and all
  its mentions. Each mention can be kept, marked "A different person", or
  linked "Same person as" another token. This works for names that were
  never flagged.
- **Simulated reviewer** (`_identity`, `_simulate`):
  - in review mode it reconciles every labelled person: one representative
    decided `different_person`, every other mention linked to it;
  - it runs until its decisions are stable and reports
    `identity_decisions`;
  - its decisions pass the real API validation (parity test).
- **Metric** (harness `pii-eval.2.1`): a party mention that is not a place
  reference and is not fully masked now FAILS party consistency, instead
  of dropping out of the score.

### A fail-open defect found while testing (production, fixed)

`Tenant: Usman Farooq. Rent is Rs. 50,000 …` was sent with the tenant's
name UNMASKED, unless the final layout check happened to catch it. Three
causes combined:

1. The name label's value ran past the sentence end.
2. That over-long span overlapped the protected amount, so pii-mask.3 held
   it back.
3. The held-back flag was emitted only in a sentence that contained the
   WHOLE span. Crossing a sentence edge, it was neither masked nor flagged.

Fixes:
- name label values end at the sentence;
- labels after a heading on the same line are read by their last
  sentence;
- every flag is raised in every sentence it touches, clipped to it;
- a `pii_leak_guard` stop is now reviewable, so the lawyer can mark what
  the check saw instead of being stuck.

### Compatibility

- **Policy and approvals:** the masking-policy hash changes (pii_mask.py and
  pii_layers.py), so every earlier approval is stale. Stored review records
  never contain `different_person` and keep their meaning.
- **Harness:** pii-eval.2 → pii-eval.2.1. The frozen pii-eval-3/4/5 records
  stay as recorded and are not directly comparable with new scores. The
  stricter consistency metric is lower where party mentions were missed;
  report-only auto and flag-only scores on pii-eval-1 fall sharply for that
  reason.

### Development-only results

- **identity-dev** (12 inspectable structural fixtures): review mode is
  consistent, leak-free and deadline-exact for all 12, both as found and
  with every name pre-detected.
- **pii-eval-1:** review mode 36/48 sent, 0 leaks, coverage 1.0, party
  consistency 1.0, deadlines 1.0, both rules-only and with GLiNER.

Neither result is a gate.

### Limitations

- **Auto mode** (review off; tests and report-only) sends spelling
  proposals unreviewed. Two people with one name and no designated roles
  (id-11) share a token there. Production cannot send without review,
  because `analyzer_pii_review_required` defaults to on.
- **The simulator is not a lawyer.** Whether a lawyer actually uses the
  People panel correctly needs the usability trial.
- **`identity_ambiguous` is best-effort.** It needs the document to
  designate roles; otherwise only the lawyer's review separates two people
  with one name.

## Independent review of the identity fix (2026-10-04)

**Feature flags.** Real-document AI was already blocked twice:
`ai_config.problems()` disables the AI layer unless synthetic-only is set,
and both stages refuse a source not attested as synthetic. But
`analyzer_pii_review_required` alone could switch the lawyer's review off.
`review_required()` now ignores that flag unless the configuration is
synthetic-only AND the source is synthetic: no flag change can let a real
document bypass the review.

**Findings, each with a test** (`tests/test_analyzer_pii_identity.py`
unless noted):

| # | Invariant | Status | Test |
|---|---|---|---|
| 1 | Same name, separated by a reviewer | held | `test_a_reviewer_can_separate_two_people_with_the_same_name`, `test_two_people_with_one_name_are_separated_through_the_review_api` |
| 2 | Two unflagged masked names linked by a reviewer | held (now also through the API) | `test_two_unflagged_masked_names_are_linked_through_the_api` |
| 3 | No merge by surname, title, role or proximity | held | `test_three_parties_sharing_a_surname…`, `test_title_role_or_proximity_never_merge_people` |
| 4 | Every masked mention reviewable | held | `test_the_preview_lists_every_masked_person_mention_as_offsets`, People panel DOM test |
| 5 | Invalid, cycle, stale, contradiction or hash change block | held | `test_self_links_cycles_and_conflicts_block`, `test_a_stale_identity_target…`, invariants file (`approval_changed`) |
| 6 | Partial party mention stays in the denominator | held; the test was made unconditional | `test_a_party_mention_left_unmasked_is_not_a_consistent_party` |
| 7 | Cross-sentence span never unmasked and unflagged | held | `test_a_held_back_span_crossing_sentences_is_flagged_never_dropped` |
| 8 | Leak-check stop opens a usable review | held (now end to end) | `test_a_leak_check_stop_opens_a_usable_review` |
| 9 | Wire request = approved preview = receipt hash | held | `test_the_wire_request_has_the_attested_fingerprint` (confirmation) |
| 10 | Deadlines, evidence and scanner intact | held | `test_deadlines_reach_the_provider_exactly_as_written`, `test_scanner_results_and_evidence_are_untouched_by_the_review` (confirmation) |
| 11 | No raw names in logs, receipts, records or errors | held | invariants file; receipt tests (now hex-safe) |
| — | Feature flag cannot bypass review | **FIXED** (failed before) | `test_review_cannot_be_switched_off_outside_a_synthetic_only_configuration` |
| — | Simulator parity and gold isolation | held | `test_every_simulated_decision_on_the_identity_set_passes_the_real_api`, `test_gold_labels_never_reach_production_masking` |

## Identity path audit after pii-eval-6 (2026-10-05)

pii-eval-6 scored review-mode party consistency 0.973: one of 37 sent
documents failed. pii-eval-3..6 are spent and were NOT opened. Aggregate
metrics cannot say which cause produced that one failure, and nothing below
claims to. The diagnosis used only development data: identity-dev,
pii-eval-1, hand-written probes, and a NEW fresh-author set,
`identity-dev-2` (`analyzer_eval/pii/identity-dev-2/AUTHORED.txt`).

### The path, and the failure classes tested

detection -> masking proposal -> People panel decision -> API validation
(`_validated`) -> identity key -> token -> approved preview (hash) -> provider
request -> scoring.

| Class | Result | Where | Test (`tests/test_analyzer_pii_identity_path.py` unless noted) |
|---|---|---|---|
| Two people merged into one token | **REPRODUCED, fixed** | masking: a name value ran across a column gap into a second person on the same line ("Landlord: A    Tenant: B"; a row of signatures, where "Sheikh" read as a title) | `test_two_labelled_people_on_one_line_…`, `test_a_row_of_signatures_…` |
| …and accepted as one person in review | **REPRODUCED, fixed** | simulated reviewer: a masked span holding two people was taken as one person's mention and never split | `test_the_simulated_reviewer_splits_a_masked_span_that_holds_two_people` |
| One person split into two tokens | not reproduced in review mode | spelling proposal; the review links the mentions (identity-dev-2: no split after review) | existing identity tests; dev-set test |
| A mention under an ADDRESS token instead of a NAME | not reproduced as a failure | a full name inside an address keeps its own token; a place reference is scored as one | existing `test_a_name_inside_an_address_…` |
| An initial or honorific treated inconsistently with the full name | not reproduced in review mode | the reviewer links initials and title-less forms; "A.R." / "Sr." break sentences (see below) | probes; dev-set test |
| A review decision lost or changed in a preview rebuild | not reproduced | every identity partition gives its own request digest, so an approval binds it | `test_every_identity_partition_gives_a_different_request_digest` |
| A simulated decision the real UI cannot express | not reproduced | every simulated decision on all three development sets passes `_validated` | `test_every_simulated_review_decision_on_the_development_sets_…` |
| **A link the UI offers but the masker refuses** | **REPRODUCED, fixed** | API/masker: a name crossing a sentence ("A.R. Khan (CNIC …)") is shown as one piece per sentence; the API accepted a link to a piece, the masker blocked it as `link_invalid`, and the lawyer could not lift it | `test_a_link_to_any_offered_piece_of_a_name_crossing_sentences_is_resolved` |
| Incomplete mentions excluded from scoring | **REPRODUCED, fixed (scorer)** | a gold mention crossing a sentence edge dropped out of EVERY metric and out of the simulated review | `test_a_gold_mention_crossing_a_sentence_boundary_is_scored` |
| A party merged with a non-party, unscored | **REPRODUCED, fixed (scorer, report-only metric)** | party consistency never looked at non-parties | `test_a_party_merged_with_a_non_party_is_a_person_inconsistency` |
| An ambiguous identity sent without a decision | not reproduced | `identity_ambiguous` blocks; contradictions, cycles and invalid links block | existing identity tests |

### A fail-open defect found on the way (production masking, fixed)

`Tenant: Kashif\nRaza.` masked only "Kashif". The label value stops at the
line break, which is also a sentence edge, so "Raza" was SENT UNMASKED AND
UNFLAGGED, and the final leak check did not catch it. `Owner: Imran Sr. Khan.`
behaved the same way, because the segmenter reads "Sr." as a full stop. The
scorer could not see either case (see the class above).

`pii_layers.name_continuations` now flags the capitalised start of the next
sentence (`name_continues`). It fires only when:

- a masked name ends its sentence and the next sentence opens with a short
  capitalised fragment; or
- the name ends in an abbreviation ("Sr.", "R.", "A.R.").

The lawyer then decides. On the three development sets it fired once, on a
real name, with no false flags.

### Fixes (the smallest change per cause)

| Fix | Layer | Version |
|---|---|---|
| A column gap (a tab, or 3+ spaces) separates two values and never joins two words of one name (`pii_layers.clean_locator_name`). Two spaces still join ("Kashif  Raza", an OCR variant). | production masking | pii-mask.5 → .6 |
| The `name_continues` flag (above). | production masking | pii-mask.5 → .6 |
| A link to a sentence piece of a name resolves to the whole name (`pii_mask.prepare`, `whole_of`). | production masking | pii-mask.5 → .6 |
| Explicit confirmation of every person group (below). | API + screen | pii-review.2 |
| The harness: gold spans scored per sentence piece; `person_consistency` (report-only); `merged_spans` (first pass, before review); review-effort counters; `review_converged`; the reviewer splits a span holding two people. | harness | pii-eval.2.2 → .3 |

**Hashes.** pii-mask.5 and pii-eval.2.2 were intermediate states that were
never committed. They were folded into the versions committed with the name
boundaries below:

- policy pii-mask.6: `5221868f0c49e1e23c669c964f67f74aa817d64837e9a4cdeb9717295b07b20d`
  (pii-mask.4 was `5e257d3b…`). Every earlier approval is stale.
- harness pii-eval.2.3: `36dfb8d6fe0cd78b17e3c88b68ae6ee8cc63486befd09b7c801e82f3ef5e5dba`
  (pii-eval.2.1 was `d0a0fbd6…`).

The frozen records of pii-eval-1..6 are unchanged. They are NOT directly
comparable with new scores, for two reasons:

- the piece-wise scorer counts mentions that pii-eval.2.1 silently dropped;
- the simulated reviewer now repairs merged spans.

That repair is why `merged_spans` is reported separately: a production merge
stays visible even when the reviewer fixes it.

### No implicit keep: every person is confirmed

Before this change, a mention left "as shown" in the People panel was an
implicit keep. The request digest did bind the identity partition, but a
lawyer could approve an unnoticed split or merge without ever looking at that
person.

The new flow:

- **The preview** returns `people_groups`: each token with every mention as
  offsets, and a `key` naming the token and those exact mentions.
- **The screen** shows one checkbox per person: "All N mentions are one
  person, and no other mention in this request is [NAME_k]". The checkbox is
  disabled on a stale preview, and Approve stays disabled until every person
  is confirmed.
- **The server** refuses with `people_unconfirmed` unless
  `people_confirmed` equals the current groups exactly. Missing, extra and
  out-of-date groups are all refused.
- **Storage:** the confirmation keeps the keys (offsets, no words) and
  `review_version: pii-review.2`.
- **Older approvals:** one written under an earlier review version is
  ignored (`applicable`), so the stage stops at `pii_review_required`.

**Review cost on synthetic development documents** (sent documents, review
mode):

| Set | Sent docs | Person confirmations added (one per group) | Masked person mentions | Simulated identity decisions |
|---|---|---|---|---|
| identity-dev | 12 | 22 (1.8 per doc) | 42 | 42 |
| identity-dev-2 | 26 | 109 (4.2 per doc) | 243 | 253 |
| pii-eval-1 | 36 | 92 (2.6 per doc) | 187 | 232 |

That is one checkbox per person, about half the clicks of confirming each
mention. These are synthetic counts. They say nothing about a real lawyer's
time or accuracy; that needs the usability trial.

### Development-only results (NOT a gate)

Rules-only masking (the production pipeline), fake capture, no network.

| Set, review mode | Before (HEAD 75c3f57) | After |
|---|---|---|
| identity-dev-2: party consistency | 0.8846 (3 of 26 sent failed, all two-people-in-one-span) | 1.0 |
| identity-dev-2: person consistency | not measured | 1.0 |
| identity-dev-2: leaks / deadlines / sent | 0 / 1.0 / 26 | 0 / 1.0 / 26 |
| identity-dev, pii-eval-1: party consistency | 1.0, 1.0 | 1.0, 1.0 (person 1.0, 1.0) |

### Name boundaries and the final guard (pii-mask.6)

Each case below failed a test first (`tests/test_analyzer_pii_boundaries.py`).
Every one was sent unmasked and unflagged before the fix, or stopped with
nothing the lawyer could act on. A genuine uncertainty now STOPS the request
with an action the lawyer can take. Nothing guesses who a person is.

| Case | Before | Now |
|---|---|---|
| Only the SECOND part of a name masked ("received by Muhammad\nKashif Raza") | "Muhammad" sent | `name_continues`: the capitalised word right before a masked name (same line or the line above), or right after it on the same line, is flagged. Role, function, title, lead and firm words are skipped. |
| A person in a column row who was never detected ("Omar Sheikh   [NAME_1]   [NAME_2]   Tariq Mehmood") | sent | `row_name_unrecognised`: every unmasked capitalised cell in a row that holds a masked name is flagged |
| A title word used as a surname ("paid to Omar Sheikh") | never detected | `title_as_surname`: a given name followed by Sheikh, Malik, Syed, Rana, Chaudhry, Qazi, Mian, Hafiz or Butt is flagged |
| A guard false positive: "son of Late [NAME_1]"; a label holding only a title ("To: Prof.", cut by the segmenter) | request blocked, nothing to repair | The honorific before a masked name is not a hit; a title-only value is no name |
| Any remaining guard stop | a CODE only | The preview returns `guard_spans`: each hit placed in the original as offsets. The screen highlights it and offers "Select to mark", and masking it clears the stop. A hit that cannot be placed is said so. Whether to stop is still decided by `leak_guard` alone, unchanged. |

On the three development sets, the new flags fired 32 times, all on
labelled personal details. Before the lead-word, honorific and firm lists
were completed (if/agar/surety, Syeda, "Centre"), 5 of 37 flags were false.
Review mode now sends all 28 identity-dev-2 documents (26 before), with 0
leaks and party and person consistency of 1.0. Flag-only (manual) leaks fell
from 46 to 24 (identity-dev-2) and from 80 to 57 (pii-eval-1); that mode is
report-only. The simulated reviewer repairs a placed guard hit as the screen
allows, counted as `guard_repairs` (harness pii-eval.2.3).

### Not resolved here, and not covered

- **The evaluated pipeline is not the production pipeline.** pii-eval-2..6
  were scored with rules plus the local GLiNER locator (`extra`). Production
  calls `pii_mask.prepare` WITHOUT a locator. Wiring a model into production
  is an owner decision, and no gate result yet describes what production
  runs.
- **Detection misses that touch nothing masked.** A name with no masked
  neighbour, no cue, and no row or label is still not detected. Only the
  lawyer can mark it, by selecting it in the original text (the People
  panel lists masked people only). This is why the review is mandatory.
- **Identity across documents.** Out of scope: tokens are per request.
- **The simulator is not a lawyer.** Whether lawyers confirm people
  correctly needs the usability trial.
