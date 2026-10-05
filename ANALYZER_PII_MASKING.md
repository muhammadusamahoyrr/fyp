# Analyzer PII masking at the AI boundary — design (`pii-mask.1`)

Status: slice A (masking at the AI boundary) being implemented. Real documents
stay blocked: the synthetic-only gate and the `not_passed` evaluation status
are unchanged, and nothing here enables anything.

## Owner's rules (2026-10-04)

- Mask CNIC, phone, email, bank account / IBAN, personal names, addresses.
  Keep amounts, dates and clause numbers.
- When names or addresses cannot be identified with confidence, STOP the
  request and ask for manual confirmation; never send silently unmasked text.
- The scanner runs on the original frozen text. The AI gets stable tokens.
  Report evidence is rebuilt on the server from the original text.
- The token mapping is stored encrypted on the server. Raw values never
  appear in logs. Deleting the source purges the mapping.
- Offsets and party validation go through the token mapping. Tokens the
  model invents are rejected. Original names are never substituted into
  model explanations.
- Masking applies first at the AI boundary. A display toggle on the review
  screen comes later.

## Where it sits (current contracts)

There is one HTTP call (`ai_client.complete`) and two prompt builders:

| Engine | Stage | Builder | Sends |
|---|---|---|---|
| ai-report.1 | `ai_stage.run_ai_report` → `ai_report.generate` | `ai_report.build_messages` | every published sentence, `[sid\|cid] body` |
| ai-hypothesis.1 | `hypothesis_review_stage.run_hypothesis_review` | `review.build_messages` | ≤4 selected sentences per item |

Masking is inserted between "load the frozen text" and "build messages", in
both stages, ALWAYS (no switch). The line format `[sid|cid] body` and both
system prompts are UNCHANGED, so prompt versions and the frozen evaluation
records stay valid. Only the sentence bodies change (values become tokens).
The offline evaluation harnesses keep calling the builders without masking.
They run on synthetic text only and stay unmasked, as measured.

## `analyzer/pii_mask.py`

`prepare(text, sentences, send_ids, graph_rows) -> Masking`, which holds:

- `bodies[sid]`: the masked body of every sentence that will be sent;
- `tokens`: `{"[NAME_1]": {"kind", "value"}}` — the mapping, server-only;
- `uncertain`: `[{sentence_id, kind, reason}]` — ids and codes only, NO text;
- `counts` by kind.

**Tokens.** `[NAME_n]`, `[CNIC_n]`, `[PHONE_n]`, `[EMAIL_n]`, `[ACCOUNT_n]`,
`[ADDRESS_n]`. One token per normalised value per run, so the same person
gets the same token everywhere.

**Confident detection:**

- CNIC: 13 digits, dashed or not.
- Mobile: `03xx…` or `+92`/`0092`.
- Landline: only after a phone cue.
- Email.
- PK IBAN.
- Account number: 8–20 digits after an account cue.
- Personal names, from any of these:
  - a title (`Mr./Mrs./Ms./Dr./Haji/Ch./Malik/Syed/Mian/Begum`) + words;
  - kinship (`s/o`, `d/o`, `w/o`, `son of`…);
  - `I, <Name>,`;
  - a person-role label line (`Tenant: <Name>`);
  - a name directly before a designation (`<Name> (the "Landlord")`).
  - Every other exact occurrence of a confident name is masked too.
  - Firms (`Ltd`, `(Pvt)`, `Limited`, `Traders`, `M/s …`, …) are not
    personal names and stay.
- Addresses:
  - a premises chain (`House/Flat/Shop/Plot… No. 12, Street 4, Block C, Town`);
  - a residence chain after `resident of / r/o / residing at`.

**Uncertain, so STOP:**

- A side of `between X and Y` / `darmiyan X aur Y` with a capitalised
  non-generic, non-firm phrase not already masked.
- `Dear <Name>` without a title.
- A capitalised phrase after `signed by / witness / executed by / received by`.
- An address cue word with a digit still visible after masking.

When anything is uncertain, the AI layer ends `unavailable` with reason
`pii_confirmation_required` and the uncertain list (ids and kinds only). The
run finishes `done` with the scanner/report intact (the existing pattern).
NOTHING is sent.

## Validation through the mapping

`ai_report.validate(..., masking=…)` and `review.validate(..., masking=…)`:

- The schema and length checks run on the model's output as received.
- Any token-shaped string not in the mapping drops that item with
  `invented_token`.
- The party check, deadline check, verbatim-copy check and echo guard
  compare against the original text through an UNMASKED VIEW of the model
  text. A party written `[NAME_1]` passes when NAME_1's value is named in
  the evidence.
- Stored items keep the model's text AS WRITTEN (tokens). Originals are
  never substituted into explanations.

Evidence offsets and hashes are already cut from the original text by the
server, so they are unchanged.

## Storage

- New blob purpose `pii_map` (`blob_store.PURPOSES`). Each blob gets its own
  AES-256-GCM envelope, as the text does.
- The JSON is `{masking_version, salt, tokens}`. The random salt means the
  unsalted `plaintext_sha256` in the header cannot be dictionary-matched.
- The map lives ONLY FOR ITS ATTEMPT (retention decision 2026-10-04):
  - it is written before the provider call, with its record in the
    attempt's transaction;
  - it is deleted in the transaction that publishes the outcome, and its
    file right after;
  - a crashed attempt's map is removed within 24 hours by the housekeeping
    sweep.
- The run summary records `pii: {masking_version, policy_sha256, counts,
  map_retention}`. It holds no values and no map id.
- Reports and evidence never need the map.
- Purge: `deletion.purge_source` removes every blob of the source.

## What masking changes about evaluation (owner's correction, 2026-10-04)

- Masking changes what the provider receives.
- The frozen benchmark records (`ai_evaluation_record.yaml`,
  `ai_hypothesis_evaluation_record.yaml`) measured UNMASKED input. They stay
  exactly as they are, as historical results. They do not prove the masked
  pipeline's accuracy.
- Every run records `pii: {masking_version, policy_sha256, ...}`.
  `policy_sha256` is the SHA-256 of `pii_mask.py` with line endings
  normalised, so any change to what is detected, kept or stopped is visible
  even under the same version.
- A masked run's evaluation carries `masked_input: not_yet_evaluated` and a
  note: on the report's AI layer, and on the drafting review's AI-signal
  summary. The scanner reads the original text and is unaffected.
- The UI never says "all personal data removed". It says that detected
  details were replaced, that some names or addresses may not have been
  detected, and that the AI's accuracy on masked input has not been
  evaluated.
- Detection completeness and live accuracy on masked input are pending. The
  fake-provider tests verify the boundary's behaviour, not completeness.
  The synthetic-only restriction is unchanged.

## Logs

Masking raises only fixed-vocabulary errors; no value, token map or
sentence text is logged. The existing logs carry codes only.

## Slice B — confirming uncertain names and addresses (built 2026-10-04)

The run's AI layer ends `unavailable: pii_confirmation_required`. The owner
lawyer then works through the review:

1. `GET /documents/analyses/runs/{id}/pii-confirmation` returns the
   uncertain spans as OFFSETS into the original text. The checks run on the
   original sentence with masked spans held at the same length, so the
   positions are exact. It also returns the text-version hash, the
   masking-policy hash and the run's state version.
2. The screen (`PiiConfirmation.jsx`) highlights each span in the original
   text. The lawyer marks each one "Personal name", "Address" or "Not
   personal information".
3. `POST` the same route with the hashes, state version and one decision per
   span. The server refuses the request when:
   - a hash changed (`confirmation_outdated`);
   - the state moved;
   - a span is unknown or decided twice;
   - a decision is invalid;
   - any span is left undecided.
   It then re-masks with the decisions and refuses again if anything is
   still uncertain. Otherwise, in ONE transaction, it:
   - stores the confirmation APPEND-ONLY in `analysis_pii_confirmations`
     (offsets, decisions, hashes, actor; never the words);
   - re-queues ONLY the blocked AI stage.
4. The stage uses the latest confirmation made against the CURRENT text hash
   and masking-policy hash:
   - "Personal name" and "Address" spans are masked, and a confirmed name
     is masked wherever else it appears;
   - "Not personal information" leaves the words.
   A confirmation made under another text or policy is ignored, so the
   layer is blocked again and the screen says the earlier confirmation no
   longer applies.
5. The stage then runs the normal attempt → outcome path, so every provider
   attempt is in the processing receipt. The run summary records
   `confirmed_spans` (a count).

The ownership, synthetic-only and `not_passed` restrictions are unchanged. A
confirmation decides only the highlighted spans. It is not "all PII removed",
and not an accuracy approval (the server's notice says so).

## Next

- C: a masking DETECTION evaluation on synthetic documents, measuring:
  - personal details missed;
  - unnecessary blocking;
  - whether party and deadline meaning are preserved.
- Then a live benchmark of the masked model.
- D: the masked display toggle on the review screen (lower priority).
- None of these enables real documents.

## Detection v2 (`pii-mask.2`) — design, revised after pii-eval-1 (2026-10-04)

**Evidence.** pii-eval-1 (frozen, independent) FAILED:
- 194 details leaked in auto mode;
- names fully masked 43 / 241, character coverage 0.36.

Regex plus "confirm what was noticed" cannot stop what is never noticed:
untitled names, names in tables, Urdu-script names and OCR-damaged names. A
capitalised-name block alone would also miss Urdu script (no case) and OCR
damage. So detection becomes LAYERED and fails closed.

| Layer | What it does | Closes |
|---|---|---|
| L0 scope gate | Text the detector does not support (Arabic or Urdu script when the entity model cannot read it, too much OCR damage, an unknown script) **blocks the whole AI request** | unsupported text silently sent |
| L1 format normalisation | CNIC, phone and account read through OCR confusables (`l/I→1`, `O→0`, stray spaces and line breaks inside digit groups) and table cells; one normalised value is one token | `CNlC 35202-l234567-1`, `0300-12345 67` |
| L2 structure | label lines and TABLES: a column headed Name, Tenant, Witness or CNIC makes every cell in that column a value of that kind | names and numbers in tables |
| L3 local multilingual entity detector | a local transformer model (CPU, no network at run time) tags PERSON and LOCATION. High confidence → mask. Middle band → uncertain (confirmation). ORG → kept (not personal) | untitled names, aliases in prose, Roman-Urdu names |
| L4 alias handling (owner's correction) | a partial or variant mention of a masked name ("Raza", "Kashif", "Kash1f Raza") is MASKED, with its own token and marked uncertain. It is LINKED to a party's token only by an explicit definition in the document (`Kashif Raza (hereinafter "Raza")`) or by a reviewer's confirmation, never automatically: two people can share a surname | partial names leaking; wrong merging of two people |
| L5 OCR uncertainty | a sentence with OCR-noise signals (letter-digit mixes inside words, broken words) that still holds unmasked proper-noun tokens → uncertain | damaged names slipping through |
| L6 leak guard (last, independent of L3) | checks the FINAL request with methods DIFFERENT from the entity model, because a second pass of the same detector misses what the first missed. PATTERNS: digit runs ≥ 7 after OCR-confusable normalisation, emails, CNIC- and IBAN-like shapes, any Arabic-script letter. LAYOUT: unmasked values on person-label lines (`Name:`, `Tenant:`, `Witness:`), in table columns with person headers, after `s/o` / `d/o` / `w/o`, `Mr.` / `Mrs.` / `Dr.`, and on signature lines. Any hit → block the request | anything the layers above missed |

Urdu-script text stays BLOCKED (L0) unless Urdu detection is demonstrated
on the evaluation, whatever a model card claims.

The L3 candidates, with sizes, licences, revisions and dependencies, are
listed in ANALYZER_PII_MODEL_SHORTLIST.md (shortlist only, nothing
downloaded or selected).

Unchanged:
- "confident or stop": uncertain spans go to the confirmation screen, and a
  block sends nothing;
- tokens are never substituted back into model text;
- the receipt records the masker version and policy hash;
- synthetic-only.

**The L3 model is an owner decision** (a new download, several hundred MB;
`transformers` and `torch` CPU are already installed):

- Candidates: a multilingual token-classification NER model (XLM-R based),
  or a PII-specialised multilingual model.
- Selection criteria:
  - licence allows commercial use;
  - runs offline on CPU within the latency budget;
  - covers English and Roman Urdu;
  - says honestly whether it reads Urdu script. If it does not, L0 blocks
    Urdu-script text.
- The model id and its weights hash are pinned, and are part of the policy
  hash.

**Evaluation plan.**

- pii-eval-1:
  - its failed baseline stays kept (7424f38);
  - it is marked a DEVELOPMENT set from the first tuning change;
  - it is used to build v2.
- The next gate is a FRESH independent **pii-eval-2**:
  - same rubric and thresholds, frozen before its single scored run;
  - no tuning after it is seen.
- Detection passing is still not a real-document approval. The live
  masked-model benchmark waits until detection passes.

## Slice B v2 — the lawyer reviews the exact request (lawyer-confirm mode, 2026-10-04)

**Owner decision.** The first launch mode is lawyer-confirm. pii-eval-2,
scored once, did NOT pass: with flag-only review there were 16 leaks, all
names that detection missed without flagging, so a lawyer never saw them.
The review therefore covers the whole request, not only flagged spans.

**The rule.** `settings.analyzer_pii_review_required` is on by default. No
analyzer AI request leaves the server until the owner lawyer has attested
the EXACT final request.

**The flow** (`services/analyzer/pii_confirmation.py`):

1. **View** — `GET /runs/{id}/pii-confirmation`:
   - every sent sentence, ORIGINAL beside MASKED;
   - flagged spans, as offsets;
   - the masked-name tokens, for "same person as";
   - the exact request and its SHA-256, once nothing is uncertain;
   - the leak-check codes.
2. **Mark** — the lawyer:
   - decides every flagged span: personal name, address, not personal, or
     same person as a masked name;
   - marks any MISSED detail by selecting it in the original: personal
     name, address, CNIC, phone, email or account.
   - `not personal` can only clear a flag; it never unmasks a detection.
   - A `same person` target must be a masked name.
3. **Preview** — `POST /runs/{id}/pii-confirmation/preview`. The server
   re-masks and returns the exact request, its hash and the leak checks.
   It stores nothing and sends nothing.
4. **Attest and submit** — `POST /runs/{id}/pii-confirmation` with
   `preview_sha256` and `attested: true`. The server rebuilds the request
   and refuses unless all of these hold:
   - its hash equals the attested one;
   - nothing is uncertain;
   - the leak checks are clean;
   - the text and masking-policy hashes match.

   Then, in one transaction, the review is stored (append-only) and the
   blocked stage is re-queued.
5. **Send** — the stage rebuilds the request. It sends only if
   `request_digest(messages)` equals the attested `preview_sha256`;
   otherwise it stops with `pii_review_outdated` and nothing leaves. So a
   changed text, policy, prompt or decision invalidates the review.
6. **Last check** — inside `ai_client.complete`, immediately before the
   HTTP call (`expected_sha256`), the client re-hashes the messages against
   the recorded request and re-runs the leak check. If either fails, it
   raises (`request_changed` / `pii_leak_guard`) and no request is made.

A detail the lawyer marks once is masked wherever the same value appears,
under one token, whatever its kind.

**What is stored:** offsets, decisions, origin (flagged or added), hashes,
the attestation statement, the actor and the time. Never the words. A
marked detail is masked like any other: its value exists only in the
encrypted per-attempt map and never reaches the provider. The receipt's
attempt entry records the review id and the attested hash.

**What it is not:**

- not a statement that all personal information was removed;
- not an accuracy approval;
- not proof that a lawyer will catch every missed detail. That needs a
  separate usability trial with a lawyer on synthetic documents.
- It does not lift Urdu script (a policy block), the synthetic-only gate or
  the `not_passed` evaluations. Real documents stay blocked.

**Evaluation.** The harness adds a `review` mode, which rubric 3 will use:

- A simulated reviewer marks every missed gold detail. This tests the
  MECHANISM: marked details are masked, never sent, and keep one token per
  person.
- It does not test a real lawyer's reliability.
- It reports `reviewer_marked`: how many details were left for the lawyer
  to catch by hand.

**Not yet built:** the GLiNER locator is part of the evaluated pipeline,
but the running server has no locator yet. At runtime it is rules plus the
lawyer's review. Wiring the locator in as a local service is a separate
step.

## pii-eval-3 party-consistency failure — investigated on development data only (2026-10-04)

pii-eval-3, scored once (b907a96), failed only on party consistency in
review mode (0.775). Its documents were not read. The investigation used
pii-eval-1, which did not reproduce the failure, plus new synthetic cases
written for the purpose.

The only lead taken from pii-eval-3 was its author's report, not its
documents: honorifics (Syed, Chaudhry, Haji, Mian, Rana, Colonel, Engr)
were kept outside the name labels. Two causes were reproduced on own cases:

1. **Masker:** a "same person" link into PART of a longer masked name took
   a new token. Example: the alias "Raza" linked to "Ali Raza", which is
   inside the masked "Syed Ali Raza". Linking keyed the token by the
   target's own text, so "ali raza" and "syed ali raza" got two tokens.

   Fix: a link resolves to the token of the masked name that CONTAINS the
   target. Links are resolved after every other token is known, chains
   included. The owner's rule still holds: Syed, Malik, Rana and Chaudhry
   are not stripped from token keys, so different people are not merged.
2. **Review screen and simulated reviewer:** a MISSED mention the lawyer
   marked (e.g. a spelling variant "Shaukat Ali" of "Shoukat Ali") could
   not be tied to the person. The screen offered no "same person as" for
   added marks, so it got its own token.

   Fix: the screen now offers "Same person as [token]" on a marked name.
   The simulated reviewer links a missed mention to the person's fullest
   mention, masked already or marked earlier in the same pass.

After both fixes:
- the reproduced cases, and further own cases (Engr, Colonel/sahib, Mian,
  Rana, initials, Mohammad/Muhammad), keep one token per person;
- pii-eval-1 is unchanged in all three modes (review mode: 0 leaks,
  coverage 1.0, party consistency 1.0).

These are development results only. The next gate is a fresh, independent
pii-eval-4 under rubric 3, scored once.

## `pii-mask.3` — deadlines exact, typed repeats, exact identity links (2026-10-04, UNCOMMITTED, for review)

pii-eval-4 failed on review-mode deadlines (0.971) and party consistency
(0.868). Neither pii-eval-3 nor pii-eval-4 was opened. Causes were
established on pii-eval-1 (development) and on new synthetic regression
fixtures.

### Causes found

**Deadlines** — reproduced with new fixtures (pii-eval-1 alone did not show
it):

1. **Name-part expansion masked deadline words.** Every standalone word of a
   masked full name was masked everywhere. A person named "Ramzan Ali" or
   "Eid Muhammad" turned "the month of Ramzan" and "after Eid" into tokens.
2. **Address chains grew over the next date or period.** For example,
   "…, Lahore, 15 June 2026" and "…, Rawalpindi, 11 months lease".
3. **Number repeats were not the stated cause.** A marked number did not
   reach "45 days" in the probes, but they found something worse: a
   reviewer mark shorter than 3 characters was silently dropped, so a
   confirmed detail stayed visible.

**Party consistency** — reproduced on pii-eval-1, rules-only review mode:

1. **An address chain absorbed the next person's name.** In
   "…, Islamabad Rubina Bibi ko…", one address "part" may hold 5
   capitalised words. The party then sat under an ADDRESS token.
2. **A single-word name the reviewer marked lost to a derived address
   span.** The mark was dropped, and a link pointing at it was then
   invalid.
3. **The simulated reviewer:**
   - linked mentions to each other (A→B and B→A, also across rounds);
   - linked to a target only *inside* a masked name;
   - re-used targets that a later mark covered.

   The old masker quietly turned such links into new tokens.
4. **Not reproduced:** about 30 further naming patterns (honorifics,
   initials, transliterations, shared surnames, possessives, word order,
   case) kept one token. Other causes may remain in the spent sets.

### Policy changes (`pii-mask.3`)

The version string and the policy hash change, so every earlier review
approval is stale.

- **Protected expressions** (`pii_layers.protected_spans`): dates, periods
  ("45 days", "eleven (11) months"), amounts ("Rs. 85,000", "85,000/-")
  and festival/month deadlines ("after Eid", "the month of Ramzan").
  - A mask that would change one is **not applied**; the span becomes
    uncertain (`protected_overlap`). Only a reviewer's "not personal"
    sends it, unchanged.
  - A reviewer's own mark inside one is a conflict (`protected_conflict`,
    kind `CONFLICT`). No decision lifts it; only changing the mark does.
    Fail closed.
- **Address boundaries:** an address never runs into a later date, period
  or amount; its end is moved to before it. A capitalised word plus a
  female name suffix (Bibi, Begum, Khatoon, Bano, Mai) is a person's name,
  so an address chain is split around it.
- **Explicit decisions:** a reviewer's mark is placed first, exactly as
  marked, and is never dropped for being short.
- **Typed repeats:** a marked or located value is repeated only by typed,
  canonical identity: digits for numbers, OCR confusables read, a whole
  word sequence for text. It is repeated only when its canonical form has
  at least 5 characters. A shorter repeat is uncertain
  (`repeat_unconfirmed`), never masked blindly.
- **Firm names:** a name part is not expanded into a firm's name
  ("Mehmood Traders (Pvt) Ltd").
- **Identity links:** a "same person" link must target EXACTLY a masked
  name. A partial target, a non-name, itself or a cycle of links is a
  conflict (`link_invalid`): blocked, never guessed. Links resolve after
  every other token, so chains share one token. People are never merged on
  a shared surname, title, role or approximate spelling: a variant only
  flags.

### Development diagnostic (pii-eval-1 only; NOT a gate)

Review mode, rules-only and rules + GLiNER:
- 0 leaks, coverage 1.0, address coverage 1.0;
- party consistency 1.0, deadlines 1.0;
- 36/48 sent: 11 blocked by the Urdu policy, 1 by the leak guard.

These are optimistic: the fixes were found on this data. pii-eval-5 is
NOT created or scored; the next step waits for the owner's review.

## `pii-mask.4` — audit fixes (2026-10-04, UNCOMMITTED, for review)

An audit of the full data path, written test-first in
`tests/test_analyzer_pii_invariants.py`. The path runs: text →
detection → lawyer marks and links → masking → preview → approval hashes →
final guard → provider → receipt.

**Reproduced and fixed**

1. **The policy hash covered `pii_mask.py` only.** Detection and the
   protected-expression rules live in `pii_layers.py`, so a change there
   left old approvals valid. The hash now covers both files; the version is
   `pii-mask.4`, and every earlier approval is stale.
2. **Deadline wordings outside the pattern list were unprotected**, and a
   name part that is a temporal word was masked silently. For a person
   "Juma Khan", "every Juma" became "every [NAME_3]". Fixes:
   - New protected wordings: end/start/expiry of the quarter, month, year,
     term or lease; fortnights; weekday deadlines (English and Urdu: Juma,
     Peer, …); the next working day.
   - A fail-closed net: a DERIVED mask that is one temporal word (a month,
     weekday, festival or time unit) is never applied silently. It is held
     back (`protected_overlap`) for the lawyer, even outside every listed
     wording.
3. **Screen and server offsets disagree outside the BMP.** The screen
   counts UTF-16 units, the server code points; after one emoji every
   highlight and mark shifts. Such a text is now not reviewable
   (`unsupported_characters`), so nothing is sent.
4. **No re-check of the approval just before the HTTP call.** The stage
   now hands the provider client a re-check that runs immediately before
   the request. It re-reads the text version's hash, the masking policy
   hash and the latest approval. Any change raises `approval_changed`, and
   nothing is sent. This is in addition to the fingerprint and leak checks
   that already ran there.

**Audited and found to hold already** (pinned by tests):
- typed repeats of a personal number with one token, dates and amounts kept;
- a one-word reviewer mark inside an address chain survives;
- links to a target a later mark covers, or to an address token, block;
- the approved preview equals the request on the wire, byte for byte;
- no names in logs, receipts, review records or error responses.

**Not reproduced / remaining hypotheses**: other wording patterns in the
spent sets cannot be checked without opening them.

pii-eval-5 is scored under the approved rubric 3 gate (`RUBRIC_BY_DATASET`);
pii-eval-4 is marked spent.

## Evaluating what production runs: `production-rules-only` (2026-10-05)

**The gap.** pii-eval-2 through -6 were scored with the rules PLUS the local
GLiNER locator. Production never runs the locator: `ai_stage` calls
`pii_mask.prepare` with no detections. None of those scores validates the
production pipeline. Their records stay as recorded, labelled as rules +
locator.

**One path.** `pii_pipeline.compose(text, sentences, scan_ids, decisions)`
does all of the following:

- selects the sent sentences;
- masks them with the lawyer's decisions;
- builds the exact messages;
- runs the final leak check;
- returns the digest.

These callers all use it:

- production `ai_stage` (the AI report);
- the lawyer's preview in `pii_confirmation` (AI report engine);
- the evaluation's `production-rules-only` pipeline.

The drafting-question review builds its own messages from the same masking.
It is not covered by this evaluation pipeline.

**The evaluation pipeline** (`score_document(..., pipeline="production-rules-only")`,
harness pii-eval.2.3):

- No locator; locator spans are refused.
- Every simulated decision passes the real API validation
  (`pii_confirmation._validated`). A decision the API would refuse blocks the
  document as `api_rejected:<code>` and is never sent.
- The request comes from `compose`. A difference from the simulation's
  masking is an error.

**Parity tests** (`tests/test_analyzer_pii_production_parity.py`):

- On both identity development sets, the evaluated request equals
  `compose`'s, document for document.
- The historical path and the production path agree on development data.
- End to end, one synthetic document with one set of decisions goes through
  the real upload -> text confirmation -> review -> stage path with a fake
  provider. The captured wire request is byte for byte the evaluation's
  request.

**What parity does NOT cover:**

- PDF layout blocks. Production segments with the extracted pages and blocks;
  the evaluation segments plain text. Synthetic sets are plain text, which
  matches production only when extraction adds no blocks.
- The drafting-question engine.
- A real lawyer's behaviour, which is simulated.

**Development-only results** (masking pii-mask.7, harness pii-eval.2.3,
review mode, production pipeline):

| Set | Sent | Leaks | Coverage | Party / person consistency | Deadlines | Blocked |
|---|---|---|---|---|---|---|
| identity-dev | 12/12 | 0 | 1.0 | 1.0 / 1.0 | 1.0 | none |
| identity-dev-2 | 28/28 | 0 | 1.0 | 1.0 / 1.0 | 1.0 | none |
| pii-eval-1 | 37/48 | 0 | 1.0 | 1.0 / 1.0 | 1.0 | 11 Urdu-script (policy) |

Reviewer work on these sets (review mode):

| Set | Marked missed details | Identity decisions | People confirmed |
|---|---|---|---|
| identity-dev | 13 | 42 | 22 |
| identity-dev-2 | 88 | 253 | 116 |
| pii-eval-1 | 145 | 232 | 94 |

Flag-only (manual) mode is report-only: it leaks (2 / 24 / 57), which is why
the review is mandatory.

**Failures this measurement reproduced, fixed test-first (pii-mask.7):**

- **Duplicate flags.** One span flagged twice (two layers, one reason) made
  the simulated reviewer submit two decisions, which the API refuses. Now it
  is one candidate and one decision.
- **Guard false positive on tables.** A table row of masked cells collapsed
  onto one line ("101 |   |   |   102") read as a long number, because `|`
  stands for an OCR "1". A bar with whitespace on both sides now ends a
  number.

**Pinned for the next gate** (`scripts/analyzer_pii_eval.py`, pipeline
`production-rules-only` for pii-eval-7):

- masking policy, from pii-mask.7 on;
- production request code (`production_code_sha256` over `pii_pipeline`,
  `pii_confirmation`, `ai_report`, `segmentation`, `injection`);
- evaluated settings (`analyzer_pii_review_required` and
  `analyzer_ai_synthetic_only` true);
- harness hash and source commit.

A gate freeze refuses uncommitted pipeline files. Scoring refuses any change
since the freeze, and refuses a locator.

### The gate scored with the production pipeline: pii-eval-7 (2026-10-05)

pii-eval-7 was the first gate scored with `production-rules-only` (`98a7e6d`). A fresh
author wrote it from the unchanged rubric 3; it has 48 documents and 402 details. It was
frozen on `582eac7` with these pins:

- policy pii-mask.7 `339cc2f3…`;
- production code `d1768c0b…`;
- harness `583996cd…`;
- the evaluated settings.

It was scored once, offline, with a fake provider.

**Result: `detection_passed`.** In review mode:

| Measure | Result |
|---|---|
| leaks | 0 |
| coverage | 1.0 |
| address coverage | 1.0 |
| party consistency | 1.0 |
| person consistency | 1.0 |
| deadlines | 1.0 |
| sent | 0.75 (12 Urdu-script documents blocked by policy) |

The report-only modes show why the review is mandatory:

- **auto:** coverage 0.64, 31 leaks;
- **flag-only:** 59 leaks.

The flag-only report also had 2 documents with `api_rejected:overlapping_spans`. This may
mean two partially overlapping flags exist that a lawyer could not both decide. Review mode
was unaffected, and the sealed documents cannot be read to confirm it, so it is an OPEN
risk.

**Reviewer work.** The simulated reviewer:

- marked 186 of 404 details itself, because masking missed them;
- made 248 identity decisions;
- confirmed 115 people.

Before review, 1 masked span held two people.

**What the result does and does not mean:**

- It shows the review MECHANISM can reach zero leaks when the reviewer catches what
  masking misses.
- It does not show a real lawyer will catch 186 missed details; that needs the
  usability trial.
- It is a synthetic engineering result, not permission to process real documents.

**Changed since the gate: pii-mask.8 (NOT gated).** The end-to-end lawyer-flow test found
two defects after the gate. Both are fixed test-first:

1. **Repeats masked word by word.** People from a two-column label row ("Landlord: A
   Tenant: B") were masked word by word where they were repeated: 7 tokens for 2 people.
   The repeat search used the raw label value; it now uses the cleaned names.
2. **Currency and calendar words flagged.** "Rs" and month names after a name were
   flagged as `name_continues`.

The current policy is pii-mask.8 (`327d8e37…`). pii-eval-7 describes pii-mask.7, so
pii-mask.8 has no gate result of its own. Per the evaluation rules, a further gate set
was NOT generated after this pass. Re-gating pii-mask.8 needs a fresh independent set,
and that is the owner's call.
