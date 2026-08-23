# Annotation Protocol — Attorney.AI Evaluation Set

**Read this before labelling anything.** It takes about fifteen minutes and it is
what makes the resulting numbers publishable rather than anecdotal.

---

## 1. What you are doing, and why it matters

You are judging real recorded conversations with a Pakistani legal assistant.
For each turn you decide two things:

1. **Which retrieved law was actually relevant** to the question asked.
2. **Whether the system's response was the right one** — including whether
   refusing to answer was right.

You are *not* rewriting answers, and you are *not* judging whether the answer was
well written. You are judging whether it was **legally right** and whether the
evidence behind it was **legally on point**.

Two people label an overlapping subset independently, and we compute and publish
the agreement between them. That number is the reason anyone will believe the
rest. **Do not discuss individual turns with the other annotator while
labelling** — agreement between two people who conferred measures nothing.

---

## 2. Who should do this

Ideally a law graduate or practising advocate familiar with Pakistani statute.
At minimum, someone who did **not** build the system.

If the only available annotators are non-lawyers, that is still worth doing —
but it must be stated in the paper, and the claim weakens from "legally correct"
to "retrieval quality as judged by informed non-specialists." Say which it is.

---

## 3. Running the tool

```bash
cd backend

# See what's left
./venv/Scripts/python.exe scripts/label_provenance.py --stats

# Label a batch — ALWAYS pass your own name
./venv/Scripts/python.exe scripts/label_provenance.py --label --limit 25 \
    --labeler ayesha --top-k 5
```

`--labeler` is mandatory. An unattributed label cannot be checked for agreement.

`--top-k 5` means you judge the top 5 retrieved provisions. **Judge exactly that
many.** Anything deeper is recorded as *unjudged*, not as irrelevant, and metrics
are only reported to the depth everyone actually looked at. If you skip ahead or
stop early, say so in the notes.

---

## 4. Judging chunk relevance

For each retrieved provision, mark **relevant** or **not relevant**.

> **A provision is relevant if a lawyer answering this question would cite it.**

That is the whole test. Some consequences:

- **On the right topic is not enough.** A section about tenancy generally is not
  relevant to a question about *notice periods* unless it bears on notice.
- **Being the wrong instrument makes it irrelevant**, even if the words match.
  The Punjab Tenancy Act 1887 governs *agricultural* tenancy. On a question about
  a shop or a house, it is **not relevant**, however much it talks about tenants.
- **Partially relevant counts as relevant.** If a lawyer would cite it alongside
  something else, mark it relevant. Do not reserve the label for the single best
  provision.
- **Definitions and procedure count** when the question turns on them.

### Worked examples

| Question | Retrieved provision | Judgement | Why |
|---|---|---|---|
| "Can a tenant be evicted without notice in Punjab?" | Punjab Rented Premises Act 2009, s.12 | **Relevant** | Urban rental; governs eviction grounds |
| same | Punjab Tenancy Act 1887, s.45 | **Not relevant** | Agricultural tenancy — wrong instrument despite matching vocabulary |
| same | Punjab Rented Premises Act 2009, s.1 (short title) | **Not relevant** | Correct statute, but says nothing that answers the question |
| "What is the punishment for theft?" | PPC s.379 | **Relevant** | States the punishment |
| same | PPC s.378 (definition of theft) | **Relevant** | A lawyer would cite it to establish the offence |
| "How do I file an FIR if police refuse?" | CrPC s.154 | **Relevant** | Registration of information |
| same | CrPC s.156(3) | **Relevant** | The remedy when police decline — cite alongside |
| "Grounds for khula" | Family Courts Act 1964, s.10(5) | **Relevant** | Procedural route for dissolution |

If you cannot tell, mark **not relevant** and write why in the notes. A
conservative judgement is recoverable; a guess is not.

---

## 5. Judging the response — the four verdicts

Choose exactly one.

| Verdict | Use when |
|---|---|
| `correct` | The system answered, and the answer was legally right |
| `incorrect` | The system answered, and the answer was wrong or misleading |
| `correct_refusal` | The system declined, **and declining was right** |
| `wrong_refusal` | The system declined, **but it could have answered** |

**The two refusal verdicts are the point of this exercise.** Collapsing them
would make abstention look free. Judge them carefully.

### When is a refusal *correct*?

- The corpus genuinely cannot answer — a rate in force today, a court statistic,
  a personal record, a prediction of outcome.
- The question was not a legal question.
- The retrieved law genuinely did not bear on the question.

### When is a refusal *wrong*?

- The answer was plainly available in the retrieved provisions and the system
  declined anyway.

### Judging an answer `incorrect`

Mark `incorrect` if the answer:

- states the law wrongly,
- cites a provision that does not say what it is claimed to say,
- applies the wrong province's law, or
- answers a **different question** than the one asked.

An answer that is *correct but incomplete* is `correct`. Note the gap in the
notes rather than downgrading it — completeness is a separate axis and we are
not measuring it here.

**Being confident does not make it right, and hedging does not make it wrong.**
Judge the legal content.

---

## 6. Notes

Use the notes field whenever:

- you were unsure (say what tipped it),
- the question itself was ambiguous,
- the answer was right for a wrong reason,
- you departed from the depth you were assigned.

Notes are read during adjudication. A disagreement with reasons attached is
resolvable in a minute; one without takes ten.

---

## 7. What happens next

```bash
# Agreement between annotators
./venv/Scripts/python.exe scripts/agreement_report.py

# The queue of turns where you differed
./venv/Scripts/python.exe scripts/agreement_report.py --disagreements
```

**Expect moderate agreement.** Published legal-annotation work reports
Krippendorff's α around 0.65, and legal relevance is genuinely contestable.
α near 0.9 is more likely to mean the annotators were not independent than that
the task was easy — the tool says so explicitly.

Disagreements go to a third person (a senior annotator) who records an
**adjudication**, which supersedes both. Where no adjudication exists and the
verdicts differ, **the turn is excluded from the evaluation set and the exclusion
is counted and reported.** It is never resolved by preferring one annotator.

Where annotators agree on the verdict but differ on a chunk, the merge is
conservative: a chunk counts relevant only if **everyone** who judged it said so.
Inflating relevance inflates every retrieval metric.

---

## 8. How much is enough

| Purpose | Turns needed |
|---|---|
| Fit calibration (Platt / isotonic) | ~200 answered turns minimum |
| Stable risk–coverage curve | ~200, spread across confidence |
| Report α credibly | ≥50 turns double-labelled |
| Retrieval metrics per legal domain | ~30 per domain |

Double-label roughly **20–30%** of the set — enough for a credible α without
paying twice for everything.

Keep the unanswerable turns. They are scarce and they are exactly what an
abstention paper needs; discarding them because they feel like non-events is the
most common way this evaluation gets quietly ruined.

---

## 9. The honest caveat

If the annotators are the system's authors, this protocol does not fix the
problem — it documents it. The evaluation set becomes independent only when the
people judging it did not build the thing being judged. Everything else here is
necessary but not sufficient.
