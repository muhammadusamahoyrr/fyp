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
