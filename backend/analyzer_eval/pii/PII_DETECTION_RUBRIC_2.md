# PII masking detection evaluation — rubric 2 and thresholds (`pii-eval.2`)

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

## How it is scored (`pii-eval.2`)

- Text = the document without its marks.
- Gold spans = the marked spans, with exact offsets in that text.
- Every sentence the AI report would send is considered.

**Two modes, reported separately:**

- **auto** — masking as it runs with no human:
  - if anything is uncertain, the document is BLOCKED (nothing sent);
  - otherwise the request is sent to a fake provider that only captures it.
- **manual** — a reviewer decides every uncertain span by the gold labels:
  - a mention of a person who has a fuller mention elsewhere → "Same person
    as" that mention;
  - otherwise, overlapping a personal-detail mark → "Personal name" or
    "Address";
  - otherwise → "Not personal information";
  - then the document is re-masked and sent. A policy block (for example a
    script the masking does not support) is not lifted by a reviewer.

**Per gold personal-detail span:**

- **character coverage** = characters inside masked spans ÷ characters of
  the span. Fully masked = 1.0. Half a name is NOT a success.
- **detected** = fully masked.
- **detection miss** = not fully masked AND not overlapping any uncertain
  span.
- **transmission leak** = the span's text, or any word of it of 3 or more
  characters, or its digits for numbers, appears in the CAPTURED provider
  request.
  - A detection miss in a blocked document is NOT a leak: nothing was sent.
- **address character coverage** = character coverage over `ADDRESS` spans
  only, reported as its own metric.

**Per document:**

- **sent rate** = documents sent ÷ all documents, per mode. A pass that
  reaches zero leaks only by blocking almost every document is not useful.
- **block reasons** = why each blocked document was stopped, reported per
  reason.
- **unnecessary block** = blocked, and every uncertain span lies outside
  every personal-detail mark (only `NOT` marks or unmarked text).
- **false candidate** = an uncertain span overlapping no personal-detail mark.

**Meaning preserved (in documents actually sent):**

- **party consistency** (scored on PERSON-NAME REFERENCES):
  - every fully masked mention of one party entity carries the same token;
  - different entities carry different tokens;
  - a party's name that sits inside an `ADDRESS` mark and is masked as part
    of that address (for example a street or building named after the
    person) is a place reference, not a person-name reference: it is not
    counted as a second token for the person;
  - any other mention masked under a non-name token still counts.
- **party consistency, any token** = the `pii-eval.1` definition, where
  every token covering a party mention counts. Reported alongside, for
  comparison only.
- **deadline preservation** = every `DEADLINE` span reaches the request
  word for word.

**Request hygiene:** the captured request never contains a mark, an entity
id, a label or the rubric's words.

## Thresholds (frozen before the first scored run; developer-proposed, provisional)

| Metric | Threshold |
|---|---|
| transmission leaks, auto mode | 0 spans |
| transmission leaks, manual mode | 0 spans |
| character coverage, auto, all personal-detail spans (micro) | ≥ 0.95 |
| detected spans, auto (fully masked ÷ all) | ≥ 0.85 |
| detection misses, auto (÷ all spans) | ≤ 0.05 |
| unnecessary blocks (÷ documents) | ≤ 0.15 |
| false candidates (÷ all uncertain spans) | ≤ 0.30 |
| party consistency (person-name references), both modes | 1.0 |
| deadline preservation | 1.0 |
| request hygiene | 1.0 |
| sent rate, manual (lawyer-confirm) mode | ≥ 0.60 |
| sent rate, auto mode | reported only, no threshold |
| address character coverage, both modes | ≥ 0.95 |

The first launch mode is lawyer-confirm (manual): a person confirms every
uncertain span before anything is sent. Auto mode is measured and reported,
but its sent rate is not a gate (owner decision, 2026-10-04).

Status:
- `detection_passed` when every threshold holds;
- `not_passed` otherwise.

A developer-labelled set can never say more than `detection_passed`. It is
never a real-document or model-quality approval. The set is scored once;
the masking is not tuned against it, and its documents are not read for
tuning.
