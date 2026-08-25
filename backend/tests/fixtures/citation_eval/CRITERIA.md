# D-lite evaluation set — pre-registered labelling criteria

**Written before any pair was selected or labelled.** The point of pre-registration
is that the boundary between categories cannot drift to fit the examples. If a
later pair does not fit these rules cleanly, the resolution is recorded in
`UNCERTAIN.md` — the rules are not edited to accommodate it.

This set exists to decide one thing: whether A1 (embedding-based mismatch
detection) is precise enough to ship. A set skewed toward easy examples produces
an inflated precision number and a wrong ship decision, so the composition rules
below are as important as the labels.

---

## Categories

| label | meaning |
|---|---|
| `supported` | The cited section exists, is in force, and genuinely supports the assertion. |
| `misgrounded_gross` | The section exists and is in force, but concerns an unrelated area of law. |
| `misgrounded_same_topic` | The section exists and is in force, is in the same subject area as the correct provision, but is the wrong one. |
| `fabricated` | The section number does not exist in the statute. |
| `repealed` | The section existed and has been repealed, marked inline in the source (`[Rep. by ...]`). |
| `omitted` | The section falls inside a range the Act declares omitted (e.g. CrPC ss.266–336). |

`repealed` and `omitted` are kept separate because the corpus records them
differently: omissions are declared as ranges the parser reads, repeals appear as
inline footnotes it does not. Merging them would hide a known detection gap.

---

## The gross / same-topic boundary

This is the distinction most likely to drift, so it is fixed by a mechanical
test applied in order. **Stop at the first rule that matches.**

1. **Different statute** covering a different area of law → `misgrounded_gross`.
   (e.g. a Transfer of Property section cited for a criminal sentence)

2. **Same statute, different Chapter, and the two subjects share no legal
   domain** → `misgrounded_gross`.
   (e.g. PPC 302, murder — Chapter XVI — cited for stamp duty)

3. **Same statute, same Chapter** → `misgrounded_same_topic`.
   (e.g. PPC 378 theft cited where PPC 390 robbery is meant — both Chapter XVII)

4. **Same statute, different Chapter, but the subjects are recognisably related**
   (same procedural stage, same offence family, same remedy type)
   → `misgrounded_same_topic`.

### Tie-break rule

**Any pair that is genuinely arguable is labelled `misgrounded_same_topic`.**

This is deliberately biased against the easy class. Same-topic errors are the
harder detection problem, so mislabelling one as gross would inflate A1's
apparent precision — the exact failure this set exists to prevent. Erring toward
the harder label can only understate performance.

### Operational test

- **Gross**: reading only the section *heading* and the assertion is enough to
  see they are unrelated.
- **Same-topic**: distinguishing them requires reading the section *text*. The
  error is one of degree, aggravation, actor, or procedural stage — not subject.

---

## Composition rules

- **40–60 pairs total.**
- **No category may exceed 30%** of the set. `fabricated` is trivial to
  synthesise and would otherwise dominate for no reason other than that it is
  cheap.
- **Within `misgrounded`, same-topic must be at least 40%** of the misgrounded
  pairs. Gross-only would make the set too easy.
- **Real over synthetic wherever possible.** Misgrounded examples recorded in
  this system's own logs are preferred to invented ones; where a pair is
  synthesised, `source` says so.
- **At least 2 PPC-sourced repealed/omitted pairs**, flagged `known_gap: true`
  (see below).

---

## Known gaps

PPC records omissions as footnotes (`"The following was omitted by A.O. 1961"`)
annotating sub-sections, not as the range declarations the parser reads. A PPC
repealed/omitted pair is therefore expected to be **missed** by the current
verifier.

Such pairs carry `known_gap: true` and a `known_gap_reason`. They are scored
separately and must never be counted as verifier failures — they are a measured
limit of the omission parser, recorded so the limit stays visible.

---

## Annotation method

**SINGLE-ANNOTATED.** Every pair was labelled once, by me, against the rules
above. **No second annotator. No inter-annotator agreement was measured, and none
is claimed.** Any agreement statistic quoted for this set would be fabricated.

This is a real limitation on the strength of any conclusion drawn from it. It is
acceptable for a go/no-go signal on A1, where the alternative is deciding with no
measurement at all, and it is **not** acceptable as a published evaluation
result. A second annotator over the same fixture is the upgrade path; the file
format already permits multiple label columns.

---

## Ground-truth verification

Every `supported`, `misgrounded_*`, `repealed` and `omitted` pair cites a section
whose **existence and status were checked against the corpus** at build time, not
assumed. Every `fabricated` pair was checked to confirm the section is genuinely
absent. The build script fails if any of these checks disagree with the label.
