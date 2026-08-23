"""Colab cell — does the general model's gain survive a change of question style?

Why this is the decisive test
-----------------------------
The general model scored +26.5 Hit@1 over base. But it was trained on 4,692
pairs from abdullah693 and tested on 1,191 pairs from abdullah693: the split is
clean (no shared positives) yet train and test share a GENERATOR and a QUESTION
STYLE. That measurement is in-distribution.

There is direct evidence that style matters here. The constitutional-only model
scored +16.5 on LEGAL-UQA-style questions and only +5.3 on citation-style ones —
same model, same domain, a third of the gain. So +26.5 should be read as an
upper bound until it is checked against a different question style.

This cell does that check on LEGAL-UQA questions, which were written from
article text by a different generator for a different purpose.

The leakage that had to be filtered out first
---------------------------------------------
Of the 121 LEGAL-UQA questions held out for the constitutional fine-tune, 99 had
gold chunks that were ALSO training positives for the general model — different
questions, same target. That is target leakage, and testing on them would
measure recall of chunks the model was trained to surface.

The set below keeps only questions whose gold chunks were NEVER a general-train
positive and whose text never appeared in training: 128 questions, 59 distinct
gold chunks, drawn from the full 592-question LEGAL-UQA set.

HOW TO USE
==========
Run this AFTER colab_general_finetune.py in the same session — it reuses the
`model` still in memory. If the session was restarted, set GENERAL_REPO to your
uploaded model and it will load from the Hub instead.

Upload crossstyle_test.json alongside general_bundle.json.
"""

import gc
import json
import math

import torch
from sentence_transformers import SentenceTransformer

BUNDLE = "general_bundle.json"
CROSS = "crossstyle_test.json"
MAX_SEQ = 224

b = json.load(open(BUNDLE, encoding="utf-8"))
tests = json.load(open(CROSS, encoding="utf-8"))
corpus = b["corpus"]
ids = list(corpus)
texts = [f"passage: {corpus[c]}" for c in ids]
device = "cuda" if torch.cuda.is_available() else "cpu"

missing = {g for t in tests for g in t["relevant_chunks"]} - set(corpus)
if missing:
    raise SystemExit(f"{len(missing)} gold chunk(s) absent from the bundle corpus")
print(f"cross-style questions: {len(tests)}  corpus: {len(ids)}  device: {device}")


def ndcg(ranked, gold, k):
    dcg = sum(1 / math.log2(i + 1) for i, c in enumerate(ranked[:k], 1) if c in gold)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


# ── identity guard ───────────────────────────────────────────────────────────
# Two models reported under different labels must actually BE different. This
# check exists because usama1111/e5-pakistani-legal was overwritten mid-session:
# a run after that point would have loaded the general weights, labelled them
# "constitutional", and produced two identical columns. The numbers looked
# plausible enough that only a reader noticing suspiciously identical metrics
# caught it. A fingerprint comparison catches it before the table is printed.
_PROBE = ["query: What are the grounds for dissolution of marriage?",
          "query: What is the punishment for theft under the Penal Code?",
          "passage: Whoever commits theft shall be punished with imprisonment."]


def _fingerprint(m):
    import numpy as np
    v = m.encode(_PROBE, normalize_embeddings=True)
    return np.asarray(v, dtype="float64").round(5).tobytes()


def assert_distinct(models: dict):
    """models: {label: SentenceTransformer}. Raises if any two are identical."""
    import itertools
    fps = {k: _fingerprint(v) for k, v in models.items()}
    for a, b_ in itertools.combinations(fps, 2):
        if fps[a] == fps[b_]:
            raise SystemExit(
                f"IDENTITY CHECK FAILED: '{a}' and '{b_}' produce identical "
                "embeddings — they are the same weights under two labels. "
                "Most likely a Hub repo was overwritten; pin a revision."
            )
    print(f"  identity check passed: {', '.join(fps)} are distinct models")


def evaluate(m, label):
    m.eval()
    with torch.no_grad():
        mat = m.encode(texts, batch_size=128, convert_to_tensor=True,
                       normalize_embeddings=True, show_progress_bar=False)
        qv = m.encode([f"query: {t['question']}" for t in tests], batch_size=128,
                      convert_to_tensor=True, normalize_embeddings=True,
                      show_progress_bar=False)
        top = torch.topk(qv @ mat.T, k=10, dim=1).indices.cpu().tolist()
    agg = {"hit@1": 0, "hit@3": 0, "hit@5": 0, "mrr": 0.0, "ndcg@5": 0.0}
    ranks = {}
    for t, idxs in zip(tests, top):
        gold = set(t["relevant_chunks"])
        ranked = [ids[i] for i in idxs]
        r = next((i for i, c in enumerate(ranked, 1) if c in gold), None)
        ranks[t["question"]] = r
        if r:
            agg["mrr"] += 1 / r
            agg["hit@1"] += r == 1
            agg["hit@3"] += r <= 3
            agg["hit@5"] += r <= 5
        agg["ndcg@5"] += ndcg(ranked, gold, 5)
    n = len(tests)
    out = {k: round(v / n, 4) for k, v in agg.items()}
    print(f"  {label:<20} " + "  ".join(f"{k}={v:.4f}" for k, v in out.items()))
    return out, ranks


res, rk = {}, {}

# All three loaded from PINNED REVISIONS. Repo names are not stable identities
# here: usama1111/e5-pakistani-legal main was overwritten mid-session, and a run
# after that point would have loaded the general weights under the
# "constitutional" label and printed two matching columns. Commits do not move.
SPECS = [
    ("base",           b["base_model"],            None,                        None),
    ("constitutional", b["constitutional_model"],  b.get("constitutional_revision"),
                                                   b.get("constitutional_weights_sha256")),
    ("general",        b["general_model"],         b.get("general_revision"),
                                                   b.get("general_weights_sha256")),
]

loaded = {}
for label, repo, rev, want_sha in SPECS:
    if rev:
        from huggingface_hub import HfApi
        i = HfApi().model_info(repo, revision=rev, files_metadata=True)
        got = getattr(getattr({s.rfilename: s for s in i.siblings}
                              .get("model.safetensors"), "lfs", None), "sha256", "")
        if want_sha and got != want_sha:
            raise SystemExit(f"{label}: weights {got[:16]} != pinned {want_sha[:16]}")
        print(f"  {label:<16} {repo}@{rev[:8]}  weights {got[:16]} verified")
        m = SentenceTransformer(repo, device=device, revision=rev)
    else:
        print(f"  {label:<16} {repo}")
        m = SentenceTransformer(repo, device=device)
    m.max_seq_length = MAX_SEQ
    loaded[label] = m

# No numbers are printed until the three are proven to be different models.
assert_distinct(loaded)

for label in ("base", "constitutional", "general"):
    res[label], rk[label] = evaluate(loaded[label], label)
    if label != "general":
        del loaded[label]
        gc.collect(); torch.cuda.empty_cache()
gen = loaded["general"]


print("\n" + "=" * 74)
print("CROSS-STYLE (LEGAL-UQA questions, no shared gold with general training)")
print(f"{'metric':<10}{'base':>12}{'constitutional':>16}{'general':>12}{'gen-base':>12}")
print("-" * 74)
for k in ("hit@1", "hit@3", "hit@5", "mrr", "ndcg@5"):
    print(f"{k:<10}{res['base'][k]:>12.4f}{res['constitutional'][k]:>16.4f}"
          f"{res['general'][k]:>12.4f}{res['general'][k]-res['base'][k]:>+12.4f}")

MISS = 10_000
mv = [(q, rk["base"][q], rk["general"][q]) for q in rk["base"]]
imp = [m for m in mv if (m[2] or MISS) < (m[1] or MISS)]
wor = [m for m in mv if (m[2] or MISS) > (m[1] or MISS)]
print(f"\nimproved {len(imp)}  worsened {len(wor)}  "
      f"unchanged {len(mv)-len(imp)-len(wor)}")

d = res["general"]["hit@1"] - res["base"]["hit@1"]
print(f"\nIn-distribution gain was +0.2653 Hit@1. Cross-style gain is {d:+.4f}.")
if d >= 0.15:
    print("-> the gain transfers across question style; +26.5 is broadly credible")
elif d >= 0.05:
    print("-> the gain transfers PARTIALLY; quote the cross-style number, not +26.5")
else:
    print("-> the gain is style-bound and does not generalise; do not quote +26.5")

fmt = lambda r: "miss" if r is None else f"#{r}"
print("\nworst cross-style regressions")
for q, x, y in sorted(wor, key=lambda m: (m[2] or MISS) - (m[1] or MISS),
                      reverse=True)[:6]:
    print(f"  {fmt(x):>5} -> {fmt(y):<5} {q[:66]}")

json.dump(res, open("crossstyle_result.json", "w", encoding="utf-8"), indent=2)
print("\nwrote crossstyle_result.json")
