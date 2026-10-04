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

- New blob purpose `pii_map` (`blob_store.PURPOSES`), AES-256-GCM envelope
  per blob, as for the text.
- JSON `{masking_version, salt, tokens}`. The random salt means the
  unsalted `plaintext_sha256` in the header cannot be dictionary-matched.
- The header is inserted in the stage's commit transaction (`inside`).
- The summary records `pii: {masking_version, map_blob_id, counts}` — no
  values.
- Purge: `deletion.purge_source` already removes every blob of the source.

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

## Next (not in this slice)

- B: a confirmation step for uncertain items (endpoint + screen), after
  which the AI stage may run.
- C: the masked display toggle on the review screen.
- Neither enables real documents.
