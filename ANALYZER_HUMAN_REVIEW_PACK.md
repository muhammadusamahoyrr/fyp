# Document Analyzer — what only people can decide (prepared 2026-10-05)

This pack PREPARES human review. **None of it has happened.** No coding session can supply
it:

- no label set or legal pack is marked `lawyer_reviewed`;
- no playbook approval is recorded;
- real-document AI stays disabled (`analyzer_ai_synthetic_only`).

It has three parts:

1. a usability trial of the People panel with a real lawyer;
2. the exact items a qualified lawyer must approve;
3. the consent and retention choices the owner must make.

---

## Part 1 — People panel usability trial (synthetic documents only)

**Why.** The production-pipeline gate (pii-eval-7) passed only because the SIMULATED
reviewer:

- marked 186 of 404 details that masking missed;
- made 248 identity decisions;
- confirmed 115 people.

Whether a real lawyer catches those is unknown, and it is the deciding question for safety.

**Setup**

- Run on a local or staging build in synthetic-only mode with a fake provider, or with AI
  off. The review screen works without sending anything.
- 3–5 practising lawyers, one at a time. Use no real client material.
- Load the five trial documents below as uploads. Do not tell the lawyer the traps.
- The facilitator records times and outcomes on the score sheet and does not help.

**Instructions to read to the lawyer (verbatim):**

> "This screen shows what would be sent to an AI tool. Personal details must not be sent.
> Compare each original sentence with the masked version. Decide every highlighted item,
> mark anything personal that was missed by selecting it in the original text, check in
> the People panel that each person is one person and that no two people share a token,
> confirm each person, and approve only when you are satisfied. Think aloud."

### Trial documents and their traps (facilitator only)

| # | Synthetic document (short) | Trap | What a correct review does |
|---|---|---|---|
| T1 | Tenancy: "Landlord: Saima Rauf. Tenant: Junaid Akram. The keys were handed over in the presence of Bushra Javed." | **Missed name**: "Bushra Javed" is not detected; the People panel cannot list it | Selects "Bushra Javed" in the original and marks it a personal name |
| T2 | NDA: "Discloser: Usman Farooq. Witness: Usman Farooq (no relation to the Discloser)." | **Mistaken merge**: two people with one name get one token by default | Marks the witness mention "A different person" |
| T3 | Employment: "Employee: Sara Malik. Sara Malik, professionally known as Sara Noor, will deliver the designs." | **Split identity**: "Sara" is flagged as a short form and "Noor" as a possible continuation; deciding each as a plain name gives one person two tokens | Links both "Same person as" Sara Malik's token |
| T4 | Tenancy: "Landlord: Kashif Raza. The rent is received by Muhammad\nKashif Raza every month." | **Half-masked name**: only "Kashif Raza" is masked; "Muhammad" is flagged `name_continues` | Decides the flag: same person as Kashif Raza's token |
| T5 | Tenancy: "Quote reference 4455667788 when paying the rent of Rs. 40,000 within 30 days." | **Guard stop**: the final check stops the request and highlights the number | Uses "Select to mark" and marks it (account/number), then approves |

### Score sheet (one row per lawyer per document)

| Lawyer | Doc | Trap caught? (Y/N) | Wrong action? (e.g. linked two different people, marked a deadline) | Time to first approval attempt (min:s) | Time spent in the People panel (min:s) | People confirmations clicked | Approved a request that still held personal data? (Y/N) | Lawyer's comment |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

### Pass criteria (to be agreed by the owner BEFORE the trial)

The suggested starting point is below. These are not decided, and must not be adjusted
after seeing results.

- **Leaked details:** every lawyer approves no request holding a personal detail (T1–T5).
- **Missed names (T1):** caught by ≥ 4 of 5 lawyers. Any miss is a release blocker unless
  the screen is changed and re-trialled.
- **Merge and split (T2, T3):** fixed by ≥ 4 of 5 lawyers.
- **Time:** median under 5 minutes per document in the trial set. Report the actual
  distribution either way.

Afterwards, record:

- the raw sheet;
- any screen change made because of it;
- whether to re-trial.

---

## Part 2 — Items needing a qualified lawyer's approval

**Who approves.** The approval must come from a qualified lawyer, not from a developer or
an AI session.

**How it is recorded.** The app already has the recording workflow:

- `POST /documents/analyses/reviewer-qualifications` records a reviewer's qualification;
- `POST /documents/analyses/playbooks/{pack_id}/approvals` records a pack approval, bound
  to its content hash;
- `GET /documents/analyses/approval-audit` lists approvals.

**Nothing is recorded today.**

### Legal playbook packs (`app/services/analyzer/playbooks/`)

Hashes are `playbook_engine.content_hash`, with CRLF normalised.

| Pack | Version | Content hash | State |
|---|---|---|---|
| general | 1 | `dd20e66a41e719799145793cd77917e68ad004c1086d62f89b6e99eb89dfff02` | unapproved draft |
| tenancy_punjab | 1 | `e7f3e6070c3cf1ea6238353ce5d750e53e1fb924ff05fb61fe5923acf3bd8d43` | unapproved draft |
| employment | 1 | `e6098da15f225aca605a4be9338b8987e6a72c055bfe2553770faa62ef0b3d5c` | unapproved draft |
| nda | 1 | `c45eea0ee73e6cc508026932035e9bf342e4e1d15d133ba323439eb0ca2713be` | unapproved draft |

An approval binds to the hash. Any edit to a pack voids it.

### Drafting-question scanner

| Item | Hash | State |
|---|---|---|
| Catalogue `drafting-hypotheses.v1` | `8594d27a6a8ca6183d85168fa0003bef54031d108726cd896afd4194a68690b4` | developer draft |
| `LABELLING_RUBRIC.v2.md` | `d36d8b54270097523ca60089d77bc877485cf6463c157f17ed2a74f6aaf70341` | developer draft |
| `LABELLING_RUBRIC.md` (v1) | `3167da70401065e82f4818d296ddfeb10c0c97f1e1c6d39e51fb4da1fc45338e` | superseded, kept |
| validation-2 labels (gate, spent) | `4ce03c06c882fce39674090570d83f2e9bb657934bc7e947502c49e530764d8c` | `developer_only` |
| validation-1 labels (development) | `f0246a6a37a43e8735fa40581e48dbdc27a959ca059faad7487be37384fd7b49` | `developer_only` |
| calib-1 labels (development) | `51ec7731b7b8e38c891cfded0ee682d44aebbe2470c7255f21ee06b03a22cebe` | `developer_only` |

Disputed labels the lawyer should rule on before validation-3 is authored (see
`ANALYZER_SCANNER_VALIDATION_3_PLAN.md`):

- **`premises_description`.** Is "his flat in Clifton, Karachi" / "the shop in the Anwar
  Market" identified (the catalogue says location counts) or ambiguous (the labels say so)?
- **`undefined_terms`.** Must "the Effective Date" and "the Purpose" be defined? Are
  "Gross Remuneration" and "the Company Rules" undefined terms?
- **`conflicting_values`.**
  - Is "dated 1 June … executed on 15 June" a conflict?
  - Is "12 days annual leave; also 10 days annual leave" one sentence giving two
    conflicting values?

### PII masking evaluation

| Item | Hash | State |
|---|---|---|
| `PII_DETECTION_RUBRIC_3.md` (owner-approved gate rubric) | `1ec2dd48162d50b987468f021729c21f56d81e8840c8e519cb688d10352a0a16` | owner-approved thresholds; labelling not lawyer-reviewed |
| pii-eval-7 labels (gate, spent; detection_passed) | `66f4de019ed61577bb532e92f96e13e02dfe7477321a63fb899aa8cd9719a52c` | `developer_only` |
| pii-eval-1 labels (development) | `2cdd9ecbe939b02069bf85784dc87583949eaf3772ef710fa7ac86ffdefe44af` | `developer_only` |
| identity-dev-2 labels (development) | `db346e4709fc1ad31c0b637dc6ae3c01cabd6a5bd47caf0ed72b5b38cb968acc` | `developer_only` |

What a reviewer should check in the PII labels:

- what counts as a personal detail in Pakistani legal documents (titles, clan names,
  kinship);
- whether business names built from personal names are personal.

---

## Part 3 — Owner decisions: real-client consent and retention

**Current state (code, synthetic only):**

- **Sources:** expire 7 days after creation; an expiry or an immediate delete purges
  everything, including receipts and PII review records.
- **PII map:** deleted when its AI attempt finishes; crash leftovers are swept after 24 h.
- **Review requests:** a 30-day retention.

These were synthetic-demo choices. **None is a decision for real client documents.**

| # | Decision | Options | Recommendation | Consequences |
|---|---|---|---|---|
| D1 | Send real-client text to a cloud model at all? | (a) never — AI stays synthetic-only; (b) only after the gates below; (c) only a local model | **(b)**, and not before: a gate result for the CURRENT masking policy (pii-mask.8 has none), the Part 1 trial passed, Part 2 approvals recorded, and written provider evidence of zero data retention and processing region | (a) the AI report never reaches real use. (b) needs every listed item. (c) needs hardware this project does not have (no GPU; a 7B model runs at about 4 tokens/s on CPU) |
| D2 | Client consent model | (a) lawyer attestation only; (b) per-engagement written consent; (c) per-document consent recorded in the app, revocable | **(c)** for any AI processing, plus the existing lawyer attestation | (c) needs a consent record (who, when, what, withdrawal), and the stage must refuse without it. (a) puts all responsibility on the lawyer with no client choice |
| D3 | Retention of original upload, extracted text and analysis | a fixed maximum (e.g. 30 / 90 days), or for the life of the engagement; immediate delete on request in every case | **Owner to choose a fixed maximum**, with delete-on-request kept | The period must have a stated legal basis, which the owner and a lawyer confirm. The code supports expiry and purge already, so only the value changes |
| D4 | Do processing receipts and PII review records outlive deletion? | (a) purge with the source (current); (b) keep a hash-only accountability record for N months | **(b), hash-only**: ids, fingerprints, decisions as offsets, no text | (b) keeps proof of what was sent and approved without keeping content. (a) loses the audit trail at deletion |
| D5 | Re-gate pii-mask.8 | (a) commission a fresh independent gate set for pii-mask.8; (b) accept pii-mask.7's result | **(a)** before D1(b) | One more synthetic set, frozen and scored once, with no tuning against it |
| D6 | The GLiNER locator in production | (a) no (current; the gate scored rules-only); (b) add it, which needs its own gate on that pipeline | **(a) for now** | Rules-only leaves more for the lawyer to mark (186 of 404 on pii-eval-7). (b) means model hosting and a new evaluation |
| D7 | Conversation module retention period (P2.5) | a period | **Owner to choose** | Blocks the P2.5 slice |

Until D1–D5 are decided and recorded, the app stays as it is:

- synthetic documents only;
- lawyer-only access;
- mandatory review;
- no real-document AI.
