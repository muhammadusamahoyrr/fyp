"""finetune_retriever.py — domain-adapt the embedding model, measured safely.

Why
---
Measured on 200 held-out constitutional questions: the gold article is findable
at dense depth 50 for 89% of them but reaches rank 1 for 43.5%. A 45-point
RANKING gap. A generic cross-encoder was tried twice and made it worse; sweeping
the hybrid fusion weights gained nothing at any setting. The remaining
hypothesis is that a general-purpose multilingual embedding model does not know
Pakistani statutory language, which is what fine-tuning addresses.

Safety properties, because this touches the thing the whole system reads from
-----------------------------------------------------------------------------
  * The production collection is NEVER written to. Re-embedded vectors go to a
    separate shadow collection, and the two are compared on held-out questions.
  * Nothing is promoted automatically. This script reports; a human decides.
  * The test questions are from components whose gold chunks appear nowhere in
    training (verified by build_finetune_data.py, which refuses to write a
    leaking split).
  * The baseline is measured in the same process, on the same questions, with
    the same retrieval code — so the comparison cannot drift.

CPU notes
---------
No GPU here (torch 2.11.0+cpu, 4 threads), so this uses the older fit() API to
avoid pulling in accelerate/datasets, a short max_seq_length, and a small batch.
Expect tens of minutes, not hours.

Usage
-----
  python scripts/finetune_retriever.py --data data/finetune --epochs 2
  python scripts/finetune_retriever.py --data data/finetune --evaluate-only
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_MODEL = "intfloat/multilingual-e5-base"
SOURCE_COLLECTION = "constitutional_collection"
SHADOW_COLLECTION = "constitutional_finetuned_shadow"
DEFAULT_OUT = Path("models/e5-pakistani-legal")

# Sized for a 15.8 GB machine. At max_seq=256 and batch=16 this process held
# 9.2 GB and was killed twice by memory pressure at ~45% of an epoch. Activation
# memory scales roughly with batch x sequence length, so both came down.
# The median chunk is ~420 characters (~110 tokens), so 160 still covers most
# passages without truncation.
MAX_SEQ = 160
BATCH = 6
LR = 2e-5

# Keep only the strongest hard negative per question by default. Three
# negatives tripled the step count for a marginal signal gain, and step count
# is what exposes the run to being killed.
MAX_PER_QUERY = 1

# A kill at 45% previously lost everything, because the model was saved only at
# the end. Checkpoint often enough that a kill costs minutes, not an hour.
CHECKPOINT_EVERY = 20


def train(data_dir: Path, out_dir: Path, epochs: int,
          max_per_query: int = MAX_PER_QUERY) -> Path:
    """Train with an explicit loop rather than SentenceTransformer.fit().

    fit() in sentence-transformers 3.0.1 delegates to a trainer whose
    compute_loss() signature is incompatible with the installed transformers
    4.57 (it is passed num_items_in_batch and rejects it). Upgrading
    sentence-transformers would touch the library the LIVE retriever encodes
    with, so the safer fix is to not use fit(): MultipleNegativesRankingLoss is
    an in-batch softmax over cosine similarities, and writing it here changes no
    dependency and no inference path.

    Pooling and tokenisation go through the model's own methods, so the training
    objective is computed over exactly the representation inference produces.
    """
    import torch
    from sentence_transformers import SentenceTransformer
    from torch.utils.data import DataLoader

    triplets = json.loads((data_dir / "train_triplets.json").read_text(encoding="utf-8"))

    # Keep only the first N examples per question. Mining emitted negatives in
    # retrieval order, so the first is the wrong chunk the retriever ranks
    # highest — the hardest and most informative one. Three per question tripled
    # the step count, and step count is what exposed the run to being killed.
    if max_per_query:
        seen: dict[str, int] = {}
        kept = []
        for t in triplets:
            n = seen.get(t["query"], 0)
            if n < max_per_query:
                kept.append(t)
                seen[t["query"]] = n + 1
        print(f"\n  triplets {len(triplets)} -> {len(kept)} "
              f"(max {max_per_query} per question)")
        triplets = kept

    print(f"  training examples : {len(triplets)}")
    print(f"  base model        : {BASE_MODEL}")
    print(f"  epochs={epochs} batch={BATCH} lr={LR} max_seq={MAX_SEQ}")

    model = SentenceTransformer(BASE_MODEL, device="cpu")
    model.max_seq_length = MAX_SEQ
    model.train()

    # e5 requires these prefixes. Training without them would optimise a
    # representation the retriever never uses at query time.
    rows = [
        (f"query: {t['query']}", f"passage: {t['positive']}",
         f"passage: {t['negative']}" if t.get("negative") else None)
        for t in triplets
    ]

    def collate(batch):
        return batch

    loader = DataLoader(rows, shuffle=True, batch_size=BATCH, drop_last=True,
                        collate_fn=collate)
    optim = torch.optim.AdamW(model.parameters(), lr=LR)
    total_steps = len(loader) * epochs
    warmup = max(1, int(total_steps * 0.1))
    sched = torch.optim.lr_scheduler.LambdaLR(
        optim,
        lambda s: s / warmup if s < warmup
        else max(0.0, (total_steps - s) / max(1, total_steps - warmup)),
    )
    scale = 20.0   # the standard MNRL temperature

    def encode(texts):
        # tokenize() returns non-tensor entries on newer sentence-transformers
        # (crashes with: 'str' object has no attribute 'to'). batch_to_device
        # moves only tensors and is stable across versions.
        feats = model.tokenize(texts)
        try:
            from sentence_transformers.util import batch_to_device
            feats = batch_to_device(feats, model.device)
        except Exception:
            feats = {k: (v.to(model.device) if hasattr(v, "to") else v)
                     for k, v in feats.items()}
        return model(feats)["sentence_embedding"]

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    step = 0
    for epoch in range(epochs):
        running = 0.0
        for batch in loader:
            anchors = [b[0] for b in batch]
            # Candidates are every positive, then every explicit hard negative.
            # Row i's target is column i; the rest of the batch supplies in-batch
            # negatives for free, which is what makes MNRL efficient.
            candidates = [b[1] for b in batch] + [b[2] for b in batch if b[2]]

            a = torch.nn.functional.normalize(encode(anchors), dim=-1)
            c = torch.nn.functional.normalize(encode(candidates), dim=-1)
            scores = a @ c.T * scale
            labels = torch.arange(len(anchors), device=scores.device)
            loss = torch.nn.functional.cross_entropy(scores, labels)

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            sched.step()
            optim.zero_grad()

            running += loss.item()
            step += 1

            if step % CHECKPOINT_EVERY == 0:
                model.eval()
                model.save(str(out_dir))
                model.train()
                print(f"    checkpoint saved at step {step}", flush=True)

            if step % 10 == 0:
                print(f"    epoch {epoch+1}/{epochs}  step {step}/{total_steps}  "
                      f"loss {running / 10:.4f}  "
                      f"({(time.time()-t0)/60:.1f} min)", flush=True)
                running = 0.0

    model.eval()
    model.save(str(out_dir))
    print(f"\n  trained in {(time.time()-t0)/60:.1f} min -> {out_dir}")
    return out_dir


def build_shadow(model_dir: Path) -> int:
    """Re-embed the corpus with the tuned model into a SEPARATE collection."""
    from sentence_transformers import SentenceTransformer

    from app.db.chroma import connect_chroma, get_chroma

    connect_chroma()
    client = get_chroma()
    src = client.get_collection(SOURCE_COLLECTION)
    got = src.get(include=["documents", "metadatas"])
    ids, docs, metas = got["ids"], got["documents"], got["metadatas"]
    print(f"\n  re-embedding {len(ids)} chunks with the tuned model…")

    model = SentenceTransformer(str(model_dir), device="cpu")
    model.max_seq_length = MAX_SEQ

    t0 = time.time()
    vectors = model.encode([f"passage: {d or ''}" for d in docs],
                           batch_size=32, show_progress_bar=True,
                           normalize_embeddings=True).tolist()
    print(f"  embedded in {(time.time()-t0)/60:.1f} min")

    try:
        client.delete_collection(SHADOW_COLLECTION)
    except Exception:
        pass
    shadow = client.create_collection(SHADOW_COLLECTION,
                                      metadata={"hnsw:space": "cosine"})
    for i in range(0, len(ids), 500):
        shadow.add(ids=ids[i:i+500], documents=docs[i:i+500],
                   metadatas=metas[i:i+500], embeddings=vectors[i:i+500])
    print(f"  shadow collection: {shadow.count()} chunks")
    return shadow.count()


def evaluate(model_dir: Path, data_dir: Path) -> dict:
    """Baseline vs tuned, same questions, same code path, same process."""
    from sentence_transformers import SentenceTransformer

    from app.ai.nodes.retrieval_node import _is_synthetic
    from app.db.chroma import connect_chroma, get_chroma

    connect_chroma()
    client = get_chroma()
    tests = json.loads((data_dir / "test_questions.json").read_text(encoding="utf-8"))
    print(f"\n  held-out questions: {len(tests)}")

    import math

    def _ndcg(ids: list[str], gold: set[str], k: int) -> float:
        """Binary-relevance nDCG@k. Ideal DCG is over min(|gold|, k) hits, so a
        question with one gold chunk is not penalised for the other k-1 slots."""
        dcg = sum(1.0 / math.log2(i + 1)
                  for i, c in enumerate(ids[:k], 1) if c in gold)
        ideal = sum(1.0 / math.log2(i + 1)
                    for i in range(1, min(len(gold), k) + 1))
        return dcg / ideal if ideal else 0.0

    def metrics(collection, model):
        col = client.get_collection(collection)
        agg = {"hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "mrr": 0.0,
               "ndcg@5": 0.0, "ndcg@10": 0.0}
        ranks: dict[str, int | None] = {}
        for it in tests:
            gold = set(it["relevant_chunks"])
            vec = model.encode([f"query: {it['question']}"],
                               normalize_embeddings=True)[0].tolist()
            res = col.query(query_embeddings=[vec], n_results=10,
                            include=["metadatas"])
            ids = [m.get("chunk_id", "") for m in (res.get("metadatas") or [[]])[0]
                   if not _is_synthetic(m or {})]
            r = next((i for i, c in enumerate(ids, 1) if c in gold), None)
            ranks[it["question"]] = r
            if r:
                agg["mrr"] += 1 / r
                agg["hit@1"] += r == 1
                agg["hit@3"] += r <= 3
                agg["hit@5"] += r <= 5
            agg["ndcg@5"] += _ndcg(ids, gold, 5)
            agg["ndcg@10"] += _ndcg(ids, gold, 10)
        n = len(tests)
        return {k: round(v / n, 4) for k, v in agg.items()}, ranks

    base = SentenceTransformer(BASE_MODEL, device="cpu")
    base.max_seq_length = MAX_SEQ
    print("  measuring baseline (dense-only, production vectors)…")
    before, rank_before = metrics(SOURCE_COLLECTION, base)

    tuned = SentenceTransformer(str(model_dir), device="cpu")
    tuned.max_seq_length = MAX_SEQ
    print("  measuring tuned (dense-only, shadow vectors)…")
    after, rank_after = metrics(SHADOW_COLLECTION, tuned)

    print(f"\n  {'metric':<10} {'baseline':>10} {'tuned':>10} {'delta':>10}")
    print("  " + "-" * 44)
    for k in ("hit@1", "hit@3", "hit@5", "mrr", "ndcg@5", "ndcg@10"):
        print(f"  {k:<10} {before[k]:>10.4f} {after[k]:>10.4f} "
              f"{after[k]-before[k]:>+10.4f}")

    # Per-query movement. An aggregate can improve while the system gets worse
    # on the queries that matter, so the individual moves are reported too.
    MISS = 10_000
    moves = [(q, rank_before[q], rank_after[q]) for q in rank_before]
    improved = sorted([m for m in moves if (m[2] or MISS) < (m[1] or MISS)],
                      key=lambda m: (m[1] or MISS) - (m[2] or MISS), reverse=True)
    worsened = sorted([m for m in moves if (m[2] or MISS) > (m[1] or MISS)],
                      key=lambda m: (m[2] or MISS) - (m[1] or MISS), reverse=True)
    still_missing = [m for m in moves if m[2] is None]

    def _fmt(r):
        return "miss" if r is None else f"#{r}"

    print(f"\n  improved: {len(improved)}   worsened: {len(worsened)}   "
          f"unchanged: {len(moves)-len(improved)-len(worsened)}")

    print("\n  BIGGEST IMPROVEMENTS")
    for q, b, a in improved[:6]:
        print(f"    {_fmt(b):>5} -> {_fmt(a):<5} {q[:70]}")
    if not improved:
        print("    (none)")

    print("\n  BIGGEST REGRESSIONS")
    for q, b, a in worsened[:6]:
        print(f"    {_fmt(b):>5} -> {_fmt(a):<5} {q[:70]}")
    if not worsened:
        print("    (none)")

    print(f"\n  STILL NOT FOUND IN TOP 10 ({len(still_missing)})")
    for q, b, a in still_missing[:6]:
        print(f"    was {_fmt(b):<5} {q[:74]}")

    print("\n  NOTE: dense-only comparison, isolating the embedding change.")
    print("  The deployed system fuses BM25 0.6 / dense 0.4, so an end-to-end")
    print("  gain will differ and must be measured separately before promoting.")
    return {
        "baseline": before, "tuned": after,
        "n_improved": len(improved), "n_worsened": len(worsened),
        "improved": [{"q": q, "before": b, "after": a} for q, b, a in improved[:20]],
        "worsened": [{"q": q, "before": b, "after": a} for q, b, a in worsened[:20]],
        "still_missing": [q for q, _, _ in still_missing],
    }


def main(a: argparse.Namespace) -> int:
    out = Path(a.out)
    if not a.evaluate_only:
        train(Path(a.data), out, a.epochs, a.max_per_query)
        build_shadow(out)
    if not out.exists():
        raise SystemExit(f"no model at {out} — train first")
    result = evaluate(out, Path(a.data))
    (Path(a.data) / "finetune_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print("\n  Nothing was promoted. The production collection is unchanged.\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Fine-tune and evaluate the retriever.")
    p.add_argument("--data", default="data/finetune")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--max-per-query", type=int, default=MAX_PER_QUERY,
                   help="hard negatives kept per question (0 = all)")
    p.add_argument("--evaluate-only", action="store_true")
    raise SystemExit(main(p.parse_args()))
