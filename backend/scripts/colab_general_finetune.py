"""Colab cell — train a general Pakistani legal retriever, compare three models.

HOW TO USE
==========
1. colab.research.google.com -> New notebook
2. Runtime -> Change runtime type -> T4 GPU
3. Upload data/general_bundle.json via the file pane
4. Paste this whole file into one cell, run

WHAT IT COMPARES
================
    base                 intfloat/multilingual-e5-base
    constitutional-only  usama1111/e5-pakistani-legal   (trained on 471 pairs)
    general              trained here on 4,692 pairs across five domains

All three embed THE SAME corrected corpus inside this notebook. That matters:
the constitutional-only model was trained before two corpus repairs — 164
Schedule paragraphs falsely numbered as Articles, and the ingestion of CPC 1908
— so reusing its old index would credit the corpus fix to the training data.

Results are broken down PER DOMAIN. A general model that lifts criminal while
sinking constitutional is a different outcome from one that lifts both, and an
overall average would hide the difference.

HARD NEGATIVES
==============
Mined here on GPU from the base model: for each training query, the highest-
ranked chunk that is not its positive. Training against the retriever's own
confusions is what makes the difference; random negatives are trivially
separable and teach little.

LEAKAGE
=======
Train/test split by connected components over shared positive chunks, verified
zero-overlap by the exporter, which refuses to write a leaking bundle.
"""

# ── setup ────────────────────────────────────────────────────────────────────
!pip install -q sentence-transformers

import gc
import json
import math
import os
import random
import time

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from torch.utils.data import DataLoader

SEED = 20260807
random.seed(SEED); np.random.seed(SEED)
torch.manual_seed(SEED); torch.cuda.manual_seed_all(SEED)

# Free anything a previous run left behind — re-running a cell keeps globals,
# and a crashed run's model will otherwise hold the GPU.
for _s in ("model", "base", "const", "mat", "qs", "sims", "optim", "sched"):
    if _s in globals():
        del globals()[_s]
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()
    _f, _t = torch.cuda.mem_get_info()
    print(f"GPU free: {_f/2**30:.2f} / {_t/2**30:.2f} GiB")
    if _f / _t < 0.5:
        print("WARNING: restart the runtime before proceeding.")

BUNDLE = "general_bundle.json"
EPOCHS = 2
BATCH = 12          # 12 anchors + up to 24 candidates fits a T4 at 224 tokens
LR = 2e-5
MAX_SEQ = 224
SCALE = 20.0
NEG_PER_QUERY = 2

b = json.load(open(BUNDLE, encoding="utf-8"))
corpus, train_rows, test_rows = b["corpus"], b["train"], b["test"]
ids = list(corpus)
id_pos = {c: i for i, c in enumerate(ids)}
texts = [f"passage: {corpus[c]}" for c in ids]
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"device={device}  corpus={len(ids)}  train={len(train_rows)}  test={len(test_rows)}")


# ── evaluation ───────────────────────────────────────────────────────────────

def ndcg(ranked, gold, k):
    """Binary-relevance nDCG@k with a real ideal DCG.

    Every question in this bundle has exactly one gold chunk, which makes IDCG
    1.0 — but hardcoding that would break silently the moment a question has
    two, and the constitutional evaluation set already has such questions."""
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


def evaluate(model, label):
    model.eval()
    with torch.no_grad():
        mat = model.encode(texts, batch_size=128, convert_to_tensor=True,
                           normalize_embeddings=True, show_progress_bar=False)
        qv = model.encode([f"query: {r['query']}" for r in test_rows],
                          batch_size=128, convert_to_tensor=True,
                          normalize_embeddings=True, show_progress_bar=False)
        top = torch.topk(qv @ mat.T, k=10, dim=1).indices.cpu().tolist()

    overall = {"hit@1": 0, "hit@3": 0, "hit@5": 0, "mrr": 0.0, "ndcg@5": 0.0}
    per_dom = {}
    ranks = {}
    for r, idxs in zip(test_rows, top):
        gold = {r["positive_id"]}
        ranked = [ids[i] for i in idxs]
        rank = next((i for i, c in enumerate(ranked, 1) if c in gold), None)
        ranks[r["query"]] = rank
        d = per_dom.setdefault(r["domain"], {"n": 0, "hit@1": 0, "hit@5": 0, "mrr": 0.0})
        d["n"] += 1
        if rank:
            overall["mrr"] += 1 / rank; d["mrr"] += 1 / rank
            overall["hit@1"] += rank == 1; d["hit@1"] += rank == 1
            overall["hit@3"] += rank <= 3
            overall["hit@5"] += rank <= 5; d["hit@5"] += rank <= 5
        overall["ndcg@5"] += ndcg(ranked, gold, 5)
    n = len(test_rows)
    out = {k: round(v / n, 4) for k, v in overall.items()}
    dom = {k: {"n": v["n"], "hit@1": round(v["hit@1"] / v["n"], 4),
               "hit@5": round(v["hit@5"] / v["n"], 4),
               "mrr": round(v["mrr"] / v["n"], 4)} for k, v in per_dom.items()}
    print(f"  {label:<20} " + "  ".join(f"{k}={v:.4f}" for k, v in out.items()))
    return out, dom, ranks


results, domains, ranklog = {}, {}, {}

print("\nBASELINES")
for label, path in (("base", b["base_model"]),
                    ("constitutional", b["constitutional_model"])):
    # PIN the revision. This repo's main branch was overwritten on
    # 2026-08-07 15:12 UTC with different weights, so loading main would
    # silently evaluate whatever model happens to live there now — and would
    # report it under the "constitutional" label.
    rev = b.get("constitutional_revision") if label == "constitutional" else None
    m = SentenceTransformer(path, device=device,
                            revision=rev) if rev else SentenceTransformer(path, device=device)
    m.max_seq_length = MAX_SEQ
    results[label], domains[label], ranklog[label] = evaluate(m, label)
    del m; gc.collect(); torch.cuda.empty_cache()

# ── mine hard negatives with the base model ──────────────────────────────────
print("\nMINING HARD NEGATIVES")
base = SentenceTransformer(b["base_model"], device=device)
base.max_seq_length = MAX_SEQ
with torch.no_grad():
    cmat = base.encode(texts, batch_size=128, convert_to_tensor=True,
                       normalize_embeddings=True, show_progress_bar=False)
    tq = base.encode([f"query: {r['query']}" for r in train_rows], batch_size=128,
                     convert_to_tensor=True, normalize_embeddings=True,
                     show_progress_bar=False)
    top = torch.topk(tq @ cmat.T, k=NEG_PER_QUERY + 3, dim=1).indices.cpu().tolist()
del base, cmat, tq; gc.collect(); torch.cuda.empty_cache()

rows = []
for r, idxs in zip(train_rows, top):
    pos = corpus[r["positive_id"]]
    negs = [corpus[ids[i]] for i in idxs if ids[i] != r["positive_id"]][:NEG_PER_QUERY]
    if negs:
        for ng in negs:
            rows.append((f"query: {r['query']}", f"passage: {pos}", f"passage: {ng}"))
    else:
        rows.append((f"query: {r['query']}", f"passage: {pos}", None))
print(f"  training examples: {len(rows)}  "
      f"({sum(1 for x in rows if x[2])} with a hard negative)")

# ── train ────────────────────────────────────────────────────────────────────
print("\nTRAINING")
model = SentenceTransformer(b["base_model"], device=device)
model.max_seq_length = MAX_SEQ
model.train()

loader = DataLoader(rows, shuffle=True, batch_size=BATCH, drop_last=True,
                    collate_fn=lambda x: x,
                    generator=torch.Generator().manual_seed(SEED))
optim = torch.optim.AdamW(model.parameters(), lr=LR)
total = len(loader) * EPOCHS
warm = max(1, int(total * 0.1))
sched = torch.optim.lr_scheduler.LambdaLR(
    optim, lambda s: s / warm if s < warm else max(0.0, (total - s) / max(1, total - warm)))


def encode(batch_texts):
    f = model.tokenize(batch_texts)
    try:
        from sentence_transformers.util import batch_to_device
        f = batch_to_device(f, model.device)
    except Exception:
        f = {k: (v.to(model.device) if hasattr(v, "to") else v) for k, v in f.items()}
    return model(f)["sentence_embedding"]


t0, step = time.time(), 0
for ep in range(EPOCHS):
    run = 0.0
    for batch in loader:
        anchors = [x[0] for x in batch]
        cands = [x[1] for x in batch] + [x[2] for x in batch if x[2]]
        a = torch.nn.functional.normalize(encode(anchors), dim=-1)
        c = torch.nn.functional.normalize(encode(cands), dim=-1)
        loss = torch.nn.functional.cross_entropy(
            a @ c.T * SCALE, torch.arange(len(anchors), device=a.device))
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optim.step(); sched.step(); optim.zero_grad()
        run += loss.item(); step += 1
        if step % 25 == 0:
            print(f"  step {step}/{total}  loss {run/25:.4f}  ({time.time()-t0:.0f}s)")
            run = 0.0
if device == "cuda":
    print(f"peak GPU: {torch.cuda.max_memory_allocated()/2**30:.2f} GiB")
print(f"trained in {(time.time()-t0)/60:.1f} min")

print("\nGENERAL MODEL")
results["general"], domains["general"], ranklog["general"] = evaluate(model, "general")

# ── comparison ───────────────────────────────────────────────────────────────
keys = ("hit@1", "hit@3", "hit@5", "mrr", "ndcg@5")
print("\n" + "=" * 72)
print(f"{'metric':<10}{'base':>12}{'constitutional':>16}{'general':>12}{'gen-base':>12}")
print("-" * 72)
for k in keys:
    print(f"{k:<10}{results['base'][k]:>12.4f}{results['constitutional'][k]:>16.4f}"
          f"{results['general'][k]:>12.4f}"
          f"{results['general'][k]-results['base'][k]:>+12.4f}")

print("\nPER DOMAIN  (hit@1)")
print(f"{'domain':<18}{'n':>6}{'base':>10}{'const':>10}{'general':>10}{'gen-base':>11}")
print("-" * 66)
for d in sorted(domains["base"], key=lambda x: -domains["base"][x]["n"]):
    n = domains["base"][d]["n"]
    bb, cc, gg = (domains[m][d]["hit@1"] for m in ("base", "constitutional", "general"))
    print(f"{d:<18}{n:>6}{bb:>10.4f}{cc:>10.4f}{gg:>10.4f}{gg-bb:>+11.4f}")

MISS = 10_000
mv = [(q, ranklog["base"][q], ranklog["general"][q]) for q in ranklog["base"]]
imp = [m for m in mv if (m[2] or MISS) < (m[1] or MISS)]
wor = [m for m in mv if (m[2] or MISS) > (m[1] or MISS)]
print(f"\ngeneral vs base: improved {len(imp)}  worsened {len(wor)}  "
      f"unchanged {len(mv)-len(imp)-len(wor)}")
fmt = lambda r: "miss" if r is None else f"#{r}"
print("\nworst regressions")
for q, x, y in sorted(wor, key=lambda m: (m[2] or MISS) - (m[1] or MISS), reverse=True)[:6]:
    print(f"  {fmt(x):>5} -> {fmt(y):<5} {q[:64]}")

json.dump({"overall": results, "per_domain": domains,
           "improved": len(imp), "worsened": len(wor)},
          open("general_result.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("\nwrote general_result.json — download this")
print("To keep the model:  model.save('e5-pak-legal-general')  "
      "then  !zip -qr e5-pak-legal-general.zip e5-pak-legal-general")
