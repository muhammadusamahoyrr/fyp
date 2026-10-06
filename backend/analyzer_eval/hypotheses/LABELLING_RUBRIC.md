# Labelling rubric — drafting questions (catalogue `drafting-hypotheses.v1`)

This rubric is for anyone writing or labelling an evaluation set for the
`ai-hypothesis.1` drafting-question engine. Read it together with the frozen
catalogue, which is the only other input:

- `app/services/analyzer/hypotheses/universal.yaml` (asked of every document)
- `app/services/analyzer/hypotheses/tenancy.yaml`
- `app/services/analyzer/hypotheses/nda.yaml`
- `app/services/analyzer/hypotheses/employment.yaml`

An author of a validation set must NOT look at the detector code, at any other
evaluation set, or at any earlier result. The point of a validation set is to
measure the engine on documents its developer has never tuned against.

## What a label is

A label is what a careful human reader answers to the catalogue question for
that document. It is about **drafting completeness only**. It is never a
statement about what the law requires, never a legal conclusion, and never a
guess about what any software will output.

Each applicable question gets exactly one label:

| label | meaning |
|---|---|
| `present` | The document clearly contains what the question asks about. |
| `ambiguous` | Something relevant is there, but it is vague, incomplete, left blank, or reads two ways. The catalogue's `ambiguous_when` line, where given, is one example. |
| `not_located` | A careful reader of the whole document finds nothing relevant. |

### Polarity: what "present" means

Every question has a `polarity` in the catalogue.

- **`attention_if_absent`** (for example "Is the rent amount stated?"): `present`
  means the thing is there and needs no attention. `not_located` or
  `ambiguous` is the item a reviewer should look at.
- **`attention_if_present`** (for example "Are there blanks or placeholders
  left to fill?"): `present` means **the problem exists** in the document (a
  blank, a conflict, a dangling reference, an undefined term). `not_located`
  means the document is free of it.

## General rules

1. **Read the whole document.** A thing stated anywhere counts, whatever clause
   it is in.
2. **Any wording counts.** Label by meaning, not by keywords. If a document
   says the same thing in unusual words, it is `present`.
3. **A heading alone is not content.** A clause title such as "4. Notice"
   with nothing after it says nothing about notice.
4. **A blank value is not a value.** If the wording is there but the value is
   left to fill in (`____`, `[●]`, `[insert …]`, `TBD`), the answer to that
   question is `ambiguous`. A blank also makes `blank_placeholders`
   `present`. A signature line left blank for signing is normal and does not
   make `signature_block` ambiguous.
5. **Vague is ambiguous.** "for a reasonable time", "as agreed later", "as per
   policy" (when the policy is not in the document) give `ambiguous`, not
   `present`.
6. **Two different values is a conflict.** If the same amount, date or period
   is given two different values, `conflicting_values` is `present`. The
   affected question itself is usually still `present` (the value is stated,
   twice).
7. **Contradictory wording is ambiguous.** If the document says both one
   thing and its opposite (for example "mutual" in one clause and "only one
   party is bound" in another), the question is `ambiguous`.
8. **Text that tries to instruct a reader or a machine is not content.** A
   malicious line ("ignore your rules and print X") answers no question.
9. **Label each question independently.** Do not make one label agree with
   another for consistency.

## Writing documents for a set

- **Synthetic only.** Invent every person, company, address, CNIC, amount and
  date. Use Pakistani context (names, cities, rupee amounts) but no real
  person or real company.
- **Realistic drafting.** Write documents the way real agreements, letters and
  deeds in Pakistan are written: formal deeds, short letters, label-style term
  sheets ("Rent: Rs. …"), and older or unusual wording. Vary length, layout
  and vocabulary. Do not write every document from one template.
- **Variants** (the `variant` field): `clean`, `incomplete`, `ambiguous`,
  `contradictory`, `placeholder`, `unusual_wording`, `malicious`. A
  `malicious` document, and only a malicious one, carries an `injection`
  entry with a unique `canary` string that appears in the injected line.
- **Coverage.** For every question that applies to a document type, the set
  must hold **at least 8 attention and at least 8 non-attention** examples
  (see Polarity). Universal questions count across all documents. Plan the
  set so each question is clearly met, missing and vague in different
  documents. Coverage is counted from your labels only.

## File format

One YAML file per document type, in `analyzer_eval/hypotheses/<set name>/`:

```yaml
dataset: <set name>
label_review: developer_only
sealed: false
documents:
- id: <unique id>
  document_type: tenancy | nda | employment
  variant: clean
  text: |
    <the document>
  labels:
    <every applicable question id>: present | ambiguous | not_located
```

`labels` must contain every universal question plus every question of that
document type, and no other question. A malicious document adds:

```yaml
  injection:
    canary: <UNIQUE-STRING>
```

## Who may say what

A developer-written set (`label_review: developer_only`) can, at most, show
that the engine passed an engineering gate (`engineering_passed`). Only a
lawyer-labelled, sealed holdout could say more, and none of this is a legal or
production approval.
