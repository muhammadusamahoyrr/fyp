"""Colab cell script — fine-tune the retriever on a free T4.

HOW TO USE
==========
1. Open https://colab.research.google.com  ->  New notebook
2. Runtime -> Change runtime type -> T4 GPU   (this is the whole point)
3. Upload data/colab_bundle.json via the file pane on the left
4. Paste this entire file into one cell and run it

Runtime: about 2-4 minutes on a T4, against 72 minutes on this project's CPU.

WHAT IT DOES
============
Trains e5-base on the mined triplets, re-embeds the corpus with both the base
and tuned models, and evaluates BOTH on the held-out questions inside the same
notebook. The baseline is recomputed here rather than compared against a
locally-measured number, so environment differences cannot masquerade as a gain.

Nothing is downloaded unless it wins. The results file is a few kilobytes; the
model is ~1.1 GB and is only worth fetching if the numbers justify it.

THE SPLIT
=========
Test questions come from connected components of the question/gold-chunk graph
whose chunks appear nowhere in training. The exporter re-checks this and refuses
to write a leaking bundle.
"""

# ── setup ────────────────────────────────────────────────────────────────────
# Colab ships torch but not sentence-transformers. Left uncommented so the cell
# is paste-and-run; it is a no-op if already present.
!pip install -q sentence-transformers

import json
import math
import os
import random
import time

# Must be set before torch initialises its allocator. Reduces fragmentation,
# which the OOM message itself recommends.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from torch.utils.data import DataLoader

# Determinism. Without this, DataLoader shuffling and weight initialisation
# differ per run, so two people following these instructions get two different
# models and cannot check each other's numbers. Evaluation is already
# deterministic given a model; training was not.
SEED = 20260807
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)
torch.cuda.manual_seed_all(SEED)

# ── free anything a previous run in this kernel left on the GPU ──────────────
# Re-running a Colab cell keeps globals, so a crashed run's model, optimizer and
# embedding matrices stay referenced and the GPU starts nearly full. That is how
# a baseline pass that had already succeeded went on to fail while asking for
# 2 MiB. Dropping the known names and collecting makes the cell safe to re-run
# without restarting the runtime.
import gc

for _stale in ("model", "base", "mat", "qs", "sims", "optim", "sched",
               "a", "c", "loss", "top", "tuned"):
    if _stale in globals():
        del globals()[_stale]
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()
    _free, _total = torch.cuda.mem_get_info()
    print(f"GPU free: {_free/2**30:.2f} / {_total/2**30:.2f} GiB")
    if _free / _total < 0.5:
        print("WARNING: less than half the GPU is free even after cleanup. "
              "Runtime -> Restart session, then run this cell again.")

BUNDLE = "colab_bundle.json"
EPOCHS = 2          # cheap on a GPU; 1 was a CPU compromise
# Each step encodes BATCH anchors plus up to 2*BATCH candidates (positives +
# hard negatives). At BATCH=32 / MAX_SEQ=256 that is ~96 sequences of stored
# activations through 12 layers, which overflowed a 14.5 GB T4. 12 leaves
# comfortable headroom while keeping enough in-batch negatives to train well.
# If you still see OOM, drop to 8 — nothing else needs changing.
BATCH = 12
LR = 2e-5
MAX_SEQ = 224
SCALE = 20.0
MAX_PER_QUERY = 3   # keep all mined negatives; step count is not a constraint now

bundle = json.load(open(BUNDLE, encoding="utf-8"))
corpus = bundle["corpus"]
tests = bundle["test_questions"]
triplets = bundle["train_triplets"]

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"device: {device}")
if device == "cpu":
    print("WARNING: no GPU. Runtime -> Change runtime type -> T4 GPU, "
          "or this will take as long as it did locally.")

if MAX_PER_QUERY:
    seen, kept = {}, []
    for t in triplets:
        n = seen.get(t["query"], 0)
        if n < MAX_PER_QUERY:
            kept.append(t)
            seen[t["query"]] = n + 1
    triplets = kept

print(f"corpus {len(corpus)} | train {len(triplets)} | test {len(tests)}")

chunk_ids = list(corpus)
chunk_texts = [f"passage: {corpus[c]}" for c in chunk_ids]


# ── metrics ──────────────────────────────────────────────────────────────────

def ndcg(ranked, gold, k):
    dcg = sum(1 / math.log2(i + 1) for i, c in enumerate(ranked[:k], 1) if c in gold)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def evaluate(model, label):
    model.eval()
    with torch.no_grad():
        mat = model.encode(chunk_texts, batch_size=128, convert_to_tensor=True,
                           normalize_embeddings=True, show_progress_bar=False)
        qs = model.encode([f"query: {t['question']}" for t in tests],
                          batch_size=128, convert_to_tensor=True,
                          normalize_embeddings=True, show_progress_bar=False)
        sims = qs @ mat.T
        top = torch.topk(sims, k=10, dim=1).indices.cpu().tolist()

    agg = {"hit@1": 0, "hit@3": 0, "hit@5": 0, "mrr": 0.0,
           "ndcg@5": 0.0, "ndcg@10": 0.0}
    ranks = {}
    for t, idxs in zip(tests, top):
        gold = set(t["relevant_chunks"])
        ranked = [chunk_ids[i] for i in idxs]
        r = next((i for i, c in enumerate(ranked, 1) if c in gold), None)
        ranks[t["question"]] = r
        if r:
            agg["mrr"] += 1 / r
            agg["hit@1"] += r == 1
            agg["hit@3"] += r <= 3
            agg["hit@5"] += r <= 5
        agg["ndcg@5"] += ndcg(ranked, gold, 5)
        agg["ndcg@10"] += ndcg(ranked, gold, 10)
    n = len(tests)
    out = {k: round(v / n, 4) for k, v in agg.items()}
    print(f"  {label:<10} " + "  ".join(f"{k}={v:.4f}" for k, v in out.items()))
    return out, ranks


# ── baseline, measured here ──────────────────────────────────────────────────
print("\nBASELINE")
base = SentenceTransformer(bundle["base_model"], device=device)
base.max_seq_length = MAX_SEQ
before, rank_before = evaluate(base, "base")

# ── train ────────────────────────────────────────────────────────────────────
# Release the baseline BEFORE loading the training copy. `before` and
# `rank_before` are plain Python values, so nothing needed later is lost — but
# leaving the model resident costs ~0.5 GB of weights plus its cached
# activations on a GPU that had none to spare. This was the main cause of the
# first OOM, not the batch size.
del base
if device == "cuda":
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

print("\nTRAINING")
model = SentenceTransformer(bundle["base_model"], device=device)
model.max_seq_length = MAX_SEQ
model.train()

rows = [(f"query: {t['query']}", f"passage: {t['positive']}",
         f"passage: {t['negative']}" if t.get("negative") else None)
        for t in triplets]
loader = DataLoader(rows, shuffle=True, batch_size=BATCH, drop_last=True,
                    collate_fn=lambda b: b,
                    generator=torch.Generator().manual_seed(SEED))
optim = torch.optim.AdamW(model.parameters(), lr=LR)
total = len(loader) * EPOCHS
warm = max(1, int(total * 0.1))
sched = torch.optim.lr_scheduler.LambdaLR(
    optim, lambda s: s / warm if s < warm else max(0.0, (total - s) / max(1, total - warm)))


def encode(texts):
    # tokenize() returns non-tensor entries on newer sentence-transformers
    # (strings such as prompt metadata), so moving every value with .to()
    # crashes with: AttributeError: 'str' object has no attribute 'to'.
    # batch_to_device moves only tensors and is stable across versions; the
    # fallback keeps this working if the helper is ever moved.
    f = model.tokenize(texts)
    try:
        from sentence_transformers.util import batch_to_device
        f = batch_to_device(f, model.device)
    except Exception:
        f = {k: (v.to(model.device) if hasattr(v, "to") else v)
             for k, v in f.items()}
    return model(f)["sentence_embedding"]


t0, step = time.time(), 0
for ep in range(EPOCHS):
    run = 0.0
    for batch in loader:
        anchors = [b[0] for b in batch]
        cands = [b[1] for b in batch] + [b[2] for b in batch if b[2]]
        a = torch.nn.functional.normalize(encode(anchors), dim=-1)
        c = torch.nn.functional.normalize(encode(cands), dim=-1)
        loss = torch.nn.functional.cross_entropy(
            a @ c.T * SCALE, torch.arange(len(anchors), device=a.device))
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optim.step(); sched.step(); optim.zero_grad()
        run += loss.item(); step += 1
        if step % 10 == 0:
            print(f"  step {step}/{total}  loss {run/10:.4f}  "
                  f"({time.time()-t0:.0f}s)")
            run = 0.0
if device == "cuda":
    print(f"peak GPU memory: {torch.cuda.max_memory_allocated()/2**30:.2f} GiB "
          f"of {torch.cuda.get_device_properties(0).total_memory/2**30:.2f} GiB")
print(f"trained in {(time.time()-t0)/60:.1f} min")

# ── tuned ────────────────────────────────────────────────────────────────────
print("\nTUNED")
after, rank_after = evaluate(model, "tuned")

# ── comparison ───────────────────────────────────────────────────────────────
print("\n" + "=" * 58)
print(f"{'metric':<10}{'baseline':>12}{'tuned':>12}{'delta':>12}")
print("-" * 58)
for k in ("hit@1", "hit@3", "hit@5", "mrr", "ndcg@5", "ndcg@10"):
    print(f"{k:<10}{before[k]:>12.4f}{after[k]:>12.4f}{after[k]-before[k]:>+12.4f}")

MISS = 10_000
moves = [(q, rank_before[q], rank_after[q]) for q in rank_before]
improved = sorted([m for m in moves if (m[2] or MISS) < (m[1] or MISS)],
                  key=lambda m: (m[1] or MISS) - (m[2] or MISS), reverse=True)
worsened = sorted([m for m in moves if (m[2] or MISS) > (m[1] or MISS)],
                  key=lambda m: (m[2] or MISS) - (m[1] or MISS), reverse=True)
missing = [m for m in moves if m[2] is None]
fmt = lambda r: "miss" if r is None else f"#{r}"

print(f"\nimproved {len(improved)}  worsened {len(worsened)}  "
      f"unchanged {len(moves)-len(improved)-len(worsened)}")

print("\nBIGGEST IMPROVEMENTS")
for q, b, a in improved[:8]:
    print(f"  {fmt(b):>5} -> {fmt(a):<5} {q[:68]}")
print("\nBIGGEST REGRESSIONS")
for q, b, a in worsened[:8]:
    print(f"  {fmt(b):>5} -> {fmt(a):<5} {q[:68]}")
print(f"\nSTILL NOT IN TOP 10 ({len(missing)})")
for q, b, a in missing[:8]:
    print(f"  was {fmt(b):<5} {q[:70]}")

json.dump({"baseline": before, "tuned": after,
           "improved": [{"q": q, "before": b, "after": a} for q, b, a in improved],
           "worsened": [{"q": q, "before": b, "after": a} for q, b, a in worsened],
           "still_missing": [q for q, _, _ in missing]},
          open("finetune_result.json", "w", encoding="utf-8"), indent=2,
          ensure_ascii=False)
print("\nwrote finetune_result.json  — download this")

# Only worth ~1.1 GB if it won. Uncomment to save the model:
# model.save("e5-pakistani-legal")
# !zip -qr e5-pakistani-legal.zip e5-pakistani-legal
print("\nTo keep the model, uncomment the save lines at the bottom and re-run "
      "that cell.")
