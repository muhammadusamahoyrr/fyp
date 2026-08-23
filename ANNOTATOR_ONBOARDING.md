# Annotator onboarding — recruiting two people and getting the first batch judged

Operational companion to [ANNOTATION_PROTOCOL.md](ANNOTATION_PROTOCOL.md) (how
to judge) and [LABELLING_PLAN.md](LABELLING_PLAN.md) (what is labellable). This
one covers only: **who to ask, what to send them, and how they start.**

Labelling is now the project's critical path — see LABELLING_PLAN §0 and
[FAILURE_CASE_001.md](FAILURE_CASE_001.md) for why.

---

## 1. Who you need

**Two annotators, working independently.** Ideally law graduates or practising
advocates familiar with Pakistani statute. Non-lawyers are still worth having if
that is what is available — the protocol says to record the fact rather than
pretend otherwise, because it changes how the agreement figure should be read.

**A third person for adjudication.** Only needed once disagreements exist, so
recruitment can wait until after the first batch. It must not be either of the
first two.

### The one disqualifying criterion

**Neither annotator may be an author of the system.** This is not a formality.
The evaluation set exists to test whether the system's answers are correct; if
the people who built it also decide what "correct" means, the agreement number
measures shared assumptions rather than accuracy. ANNOTATION_PROTOCOL.md §
"Independence" states this directly: if the annotators are the system's authors,
the protocol documents the problem rather than fixing it.

That rules out the project author, and it rules out an AI assistant working on
this codebase. There is no version of this step that can be automated away.

### Where to look

- Final-year LLB / LLM students — this is legitimate, citable research work.
- Junior advocates in Lahore district courts; the task is short and remote.
- A law faculty member who can nominate two students and act as adjudicator.

### What to offer honestly

- **Effort:** ~51 turns per annotator for batch 1. At the default `--top-k 5`,
  budget roughly **2–4 hours**, not a full day.
- **Credit:** annotators are named in the paper's acknowledgements, and the
  agreement statistic is published whatever it turns out to be.
- **What they are NOT signing up for:** they are not being asked to endorse the
  system or to certify legal advice. They are judging recorded outputs.

---

## 2. What to send them

A short brief, which can be pasted directly:

> We have built an AI legal assistant for Pakistani law and need to measure how
> often its answers are actually right. You would review ~51 recorded
> question-and-answer turns and judge each one against four verdicts: correct,
> incorrect, correct refusal, or wrong refusal.
>
> Two people do this separately and we compare, so please **do not discuss
> individual turns** with the other reviewer while labelling — the whole point
> is to see where independent readers disagree.
>
> It takes about 2–4 hours. You will be named in the acknowledgements of the
> resulting paper. You are judging recorded output, not endorsing the system,
> and we publish the agreement figure whether it is flattering or not.

Then send them, in this order:

1. **[ANNOTATION_PROTOCOL.md](ANNOTATION_PROTOCOL.md)** — the four verdicts and
   what each means. This is the only document they must read in full.
2. Their **labeller name** (see below) — it must be distinct per annotator, and
   they should use the same one every session.
3. The command in §3.

---

## 3. How an annotator starts

```bash
cd backend
python scripts/label_provenance.py --stats                 # see the pool
python scripts/label_provenance.py --label --labeler asma  # start labelling
```

`--labeler` is **mandatory in practice**: it is what makes agreement computable
at all, and it scopes the queue so the second annotator is not told the turns
are already done. Use a short, stable identifier — a first name is fine.

Progress is saved per turn, so the session can be stopped and resumed. To judge
more or fewer retrieved chunks per turn, pass `--top-k` (default 5; `0` judges
all ~20 and costs roughly three times the effort for metrics beyond k≤5).

### After both have finished batch 1

```bash
python scripts/label_provenance.py --stats                 # coverage
python scripts/agreement_report.py                         # Krippendorff's alpha
```

Read the agreement figure before doing anything else with the labels. The
protocol warns that **α near 0.9 more likely means the annotators were not
independent** than that the task was easy — so a suspiciously high number is a
reason to check how they worked, not to celebrate.

Disagreements go to the third person, who records an adjudicated verdict. A
disputed turn is never resolved by preferring one annotator, and the dispute
itself is counted and reported.

---

## 4. What batch 1 does and does not achieve

| | Turns |
|---|---|
| Labelable pool today | 51 |
| Of those, judgeable against the current corpus | 37 |
| Target for calibration + a stable risk–coverage curve | 200 |

Batch 1 reaches roughly **18.5%** of the target. **The remaining ~163 turns do
not exist yet.** They are produced by people using the system, not by labelling
harder — and warmup traffic cannot supply them, because it is written with
`is_synthetic: true` and gated out of the pool by design.

So the two tracks to run in parallel are:

1. **Get batch 1 judged** — that is this document.
2. **Generate real traffic** — a soft launch, demo sessions, anything where
   genuine users ask genuine questions. That is what grows the pool toward 200.

Coverage should be re-checked with `--stats` after each batch rather than
estimated.
