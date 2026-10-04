# PII masking detection evaluation — rubric 3 and thresholds (`pii-eval.3`)

This rubric is for whoever writes and labels a PII detection evaluation set
for the analyzer's masking (ANALYZER_PII_MASKING.md). The author
reads ONLY this file. They do not look at the masking code, any other dataset
or any result.

A pass here means only that the masker's DETECTION met these thresholds on
synthetic, developer-labelled documents. It is NOT approval for real
documents, and it says nothing about AI model quality.

## The documents

- **Synthetic only.** Invent every person, company, address, CNIC, phone,
  email and account. Use Pakistani context, but no real person or real
  company.
- **Kinds of document:** tenancy agreements, NDAs, employment letters and
  agreements, and short letters. Vary length and layout: formal deeds,
  label-style term sheets ("Tenant: …"), letters, bulleted points, and
  TABLES (pipe `|` or tab separated rows).
- **Every document must contain at least one personal detail.**
- **Across the set, include all of these:**
  - repeated names, with the same person mentioned several times;
  - ALIASES of the same person: full name, "Mr. Raza", the first name
    alone, "the said Kashif";
  - Urdu-script and Roman-Urdu names alongside English-style names;
  - OCR-style errors: `Kash1f Raza`, `CNlC 35202-l234567-1`,
    `0300-12345 67`, broken line wraps inside a name or an address;
  - OVERLAPPING details, for example an address that contains a person's
    name ("House of Kashif Raza, Street 4, Lahore");
  - names WITHOUT a title, a designation or a label;
  - things that LOOK like names but are not personal information: company
    names, shop names, places, cities, roles, document titles, project
    names.
- **Deadlines and periods** whose meaning must survive masking: "within 30
  days of the invoice", "by 5 June 2026", "eleven months from 1 July
  2026".

## Inline marks

Mark spans in the text with double square brackets:

    [[KIND:entity|the exact text as it appears]]

`KIND` is one of:

| KIND | Meaning |
|---|---|
| `NAME` | a person's name (any form: full, partial, alias, misspelled, Urdu script) |
| `CNIC` | a CNIC / NIC number, any formatting, including OCR damage |
| `PHONE` | a phone or mobile number |
| `EMAIL` | an email address |
| `ACCOUNT` | a bank account number or IBAN |
| `ADDRESS` | a residential or premises address, from house/plot/flat number to town or city |
| `NOT` | looks like a name or an address but is NOT personal information (a company, shop, place, role, title, project) |
| `DEADLINE` | a deadline or period whose words must reach the AI unchanged |

- `entity` is a short id. All mentions of the SAME person share one id
  (`p1`), including aliases and misspellings, and different people get
  different ids. Other kinds use any unique id (`c1`, `a1`, `n1`, `d1`).
- Overlap: a NAME may sit INSIDE an ADDRESS, one level deep:
  `[[ADDRESS:a1|House of [[NAME:p1|Kashif Raza]], Street 4, Lahore]]`.
- Mark the EXACT characters only. Titles ("Mr.", "Dr."), honorifics and
  surrounding punctuation are not part of a NAME.
- The text without the marks must read as a normal document.

## File format

One or more YAML files in `analyzer_eval/pii/<set name>/`:

```yaml
dataset: <set name>
label_review: developer_only
documents:
- id: <unique id>
  document_type: tenancy | nda | employment | letter
  features: [repeated_names, aliases, urdu_script, roman_urdu, ocr_errors, table, overlap, untitled_names, lookalikes, deadlines]
  parties: [p1, p2]        # entity ids of the people who are parties
  text: |
    <the document, with inline marks>
```

`features` lists what the document exercises, for the coverage check.

**Coverage** (over the whole set):
- at least 40 documents;
- at least 6 documents for each feature;
- at least 150 marked personal details in total.

## How it is scored (`pii-eval.3`)

Scored exactly as rubric 2, under the pinned pipeline (rules plus the local
locator), with a third mode:

- **auto**: no human. A document is blocked if anything is uncertain.
- **manual (flag-only)**: a reviewer decides only the spans masking flagged.
- **review (lawyer-confirm, the launch mode)**: the reviewer decides every
  flagged span AND marks every personal detail masking missed, as offsets
  in the original. A person's other mention is linked to their fullest
  masked mention. The request is then rebuilt, the leak checks run, and it
  is sent.
  - The simulated reviewer catches everything, so this mode tests the
    MECHANISM: marked details are masked, never sent, and keep one token
    per person.
  - It does NOT show that a real lawyer would catch every missed detail.
    That needs a separate usability trial with a lawyer.
  - **reviewer_marked** reports how many details were left for the lawyer
    to catch by hand.

Every metric of rubric 2 is reported for all three modes: sent rate, block
reasons, party consistency (person-name references, plus the any-token
definition), address coverage, and so on.

## Thresholds (owner-approved 2026-10-04; frozen before the first scored run)

The gate is the review (lawyer-confirm) mode only:

| Metric, review mode | Threshold |
|---|---|
| transmission leaks | 0 spans |
| overall character coverage | ≥ 0.99 |
| address character coverage | ≥ 0.95 |
| party consistency (person-name references) | 1.00 |
| deadline preservation | 1.00 |
| documents sent (sent rate) | ≥ 0.60 |

Report-only, not gated:

- the auto and flag-only (manual) results;
- request hygiene;
- `reviewer_marked`: the share left to the lawyer.

`detection_passed` here is a SYNTHETIC ENGINEERING GATE of the masking
mechanism when every missed detail is marked. It is never lawyer
validation, a real-document approval or production approval. The set is
scored once; the masking is not tuned against it, and its documents are not
read for tuning.
