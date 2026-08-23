# Labelling Plan — what to run, in what order, and what it will and will not buy

Companion to [ANNOTATION_PROTOCOL.md](ANNOTATION_PROTOCOL.md), which tells an
annotator *how* to judge. This tells the project *what is labellable today*.

Status as of 2026-08-23. Re-run `label_provenance.py --stats` before trusting
any number here.

---

## 1. The pool is smaller than the target, and not by a little

| | Turns |
|---|---|
| Provenance records | 63 |
| Labelable (answer turns; retrieval faults **and synthetic traffic** excluded) | 51 |
| **Judgeable today** | **37** |
| Unjudgeable — no retrieved chunk resolves in the current corpus | 14 |
| Human labels so far | 0 |
| Target for calibration + a stable risk–coverage curve | 200 |

Labelling every judgeable turn reaches **18.5%** of the target. The remaining
163 turns do not exist yet. They are produced by *using the system*, not by
labelling harder.

### What the pool excludes, and why

| Excluded | Reason |
|---|---|
| `turn_type` ≠ `answer` | A clarifying question or a gatekeeper block has no answer to judge. Audited, not labellable. |
| `arbitration.source == "error"` | A refusal caused by a retrieval fault is not an abstention decision — the system never saw the evidence. Labelling it would put an outage into the risk–coverage curve. |
| `is_synthetic == true` | Warmup, replay and demo traffic. Counted toward the threshold, never an evaluation question. |
| `is_baseline == true` (on labels, not turns) | Machine-authored judgements. Excluded from agreement, adjudication, the authoritative set and both exports. |

Each filter is `$ne: true` rather than `== false`, so records written before a
field existed are kept rather than silently vanishing from the pool.

### Why 14 turns are unjudgeable

The statute corpus was re-ingested on 2026-08-06 by the versioned
`ingest_statutes.py`, which assigns ids as `statutes_<slug>_<NNNN>`. The turns
recorded before that ran carry the old hash-suffixed scheme
(`crpc_1898_e9b4455e`). **82 of 180 pooled chunk ids no longer resolve.** The
text cannot be recovered by id, so relevance cannot be judged.

Two consequences worth stating plainly:

- Those 14 turns cannot be rescued by trying harder. A partial rescue via
  (statute, section) re-resolution is possible — the metadata survives — but the
  *ranking* those turns record came from the previous corpus and retriever, so
  even re-resolved they describe a system that no longer exists.
- The same is true, more weakly, of the 37 judgeable ones. They are honest
  evidence about the pipeline as it ran on 5–6 August. Treat them as a pilot,
  not as the benchmark.

**The benchmark should be built from traffic generated against the current
corpus.** That is the real prerequisite, and it is cheap: it needs the app used,
not annotators.

---

## 2. Order of work

**Step 1 — generate traffic (no annotator needed).** Run the backend and put
real questions through it until the labelable pool is comfortably past 200.
Every answered turn writes one provenance record. This is also what the
threshold warmup counts, so it discharges two prerequisites at once.

> **Marking synthetic traffic.** Warmup traffic and the labelling pool are the
> same records, so any query not asked by a real person must be marked at write
> time. Set `PROVENANCE_SYNTHETIC=1` on the **API server**, not on the client
> script — the server is the process that writes the record, and a seeding
> script only sends WebSocket frames. Run warmup as a dedicated server session:
>
> ```bash
> PROVENANCE_SYNTHETIC=1 ./venv/Scripts/uvicorn.exe app.main:app \
>     --host 127.0.0.1 --port 8000
> ```
>
> Everything that server records is marked, which is the intent — a warmup
> session is not serving real users.
>
> Records then carry `is_synthetic: true`. They are still written, still
> audited, and still counted toward the 1000-query warmup — they are simply
> never offered for labelling and can never enter the eval set or the
> calibration pairs. The default is `false`, so a driver that never heard of
> the flag produces *real* records; the opposite default would silently discard
> genuine traffic.
>
> The flag cannot be applied retroactively. Once real and synthetic turns are
> mixed with nothing to tell them apart, every turn in the pool inherits the
> doubt.

**Step 2 — two annotators, per the protocol.** Neither may be the person who
built the system. Each runs:

```bash
cd backend
./venv/Scripts/python.exe scripts/label_provenance.py --label \
    --limit 25 --labeler <their-own-name> --top-k 5
```

The queue is scoped per labeler, so both see the full pool and the overlap is
deliberate rather than accidental.

**Step 3 — overlap for agreement.** Protocol §8 asks for 20–30% double-labelled
and ≥50 turns double-labelled to report α credibly. At the current pool size
those two cannot both be satisfied: 50 double-labelled turns *is* the whole
pool plus more. Until the pool grows, **double-label everything** — at 37 turns
the second pass costs little and α computed on 37 is at least reportable, with
the n stated beside it.

**Step 4 — adjudicate.** `agreement_report.py --disagreements` lists the turns
where verdicts differ. A third person records an adjudication; unadjudicated
disagreements are excluded and counted, never resolved by preferring one
annotator.

**Step 5 — fit.** Only once labels exist:

```bash
./venv/Scripts/python.exe scripts/fit_conformal.py --alpha 0.10 --metrics
```

Until then it has nothing to fit, and the paper title stays **"Selective"**,
not "Calibrated".

---

## 3. The machine baseline, and what it is not

37 baseline labels exist under labeler `claude-baseline`, written by
`scripts/baseline_label.py`. They carry `is_baseline: true` and are excluded
from agreement, adjudication, the authoritative set, both exports, calibration
and the conformal threshold. Verified: with all 37 present, `authoritative_labels`
returns 0 and α is "not measurable yet".

They exist to exercise the labelling path end to end before two people spend
seventeen hours on it, and to give a machine-versus-human comparison once
humans exist (`baseline_label.py --compare`). **They are not evaluation data
and must never be reported as an eval set.** A judgement authored by the system
under evaluation fails protocol §2 on its face.

### What the baseline pass found

Of 37 turns: 4 correct, 17 incorrect, 15 correct refusals, 1 wrong refusal.
Read as a pilot, not as a score. Three patterns are worth an annotator's
attention because they will recur:

1. **Wrong-instrument retrieval dominates the civil failures.** Every "can a
   tenant be evicted without notice" turn retrieved the Punjab Tenancy Act 1887
   — *agricultural* tenancy — for what is an urban question governed by the
   Punjab Rented Premises Act 2009. This is the protocol's own worked example,
   occurring in live traffic.
2. **Correct answers with zero grounding.** One theft turn stated PPC 379/380/381
   correctly while nothing relevant was retrieved — the sections came from the
   model, not the corpus. Grounded-ness and correctness come apart, which is
   exactly what the abstention machinery is supposed to detect.
3. **Identical questions, opposite behaviour.** "How many cases were pending in
   the Lahore High Court in 2019?" was refused correctly on three turns (naming
   the limit, pointing to the Law and Justice Commission) and answered on a
   fourth with Article 203B on the *transfer* of pending cases — a lexical
   collision on "pending".

---

## 4. Two limitations the protocol does not currently mention

**Verdicts are judged on a truncated answer.** Provenance stores a SHA-256 plus
a scrubbed preview, never the full answer — deliberately, and correctly, for
privacy. But it means no annotator ever sees the whole response they are
grading. For chunk relevance this is irrelevant; for the four verdicts it is a
real limitation and belongs in the paper's threats table alongside the others.

**`arbitration.output` and the emitted text can disagree.** At least one turn
(`0492f559`) recorded `answer` while the text the user saw was a refusal in
substance. Anything that derives the answered/abstained split from
`arbitration.output` rather than from the human verdict will mis-split those
turns.
