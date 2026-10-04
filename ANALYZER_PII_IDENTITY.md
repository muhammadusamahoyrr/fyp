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
