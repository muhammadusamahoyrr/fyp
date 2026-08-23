"""phase_a_hybrid_eval.py — does the tuned retriever help the SYSTEM, not just dense?

The gap this closes
-------------------
Colab measured the tuned model dense-only and found +16.5 Hit@1. Production does
not run dense-only: it fuses BM25 at 0.6 with dense at 0.4. The regressions in
the Colab run were exact-citation lookups ("What was omitted by S.R.O. No. 1278
(1) 85?", #1 -> miss), which is precisely the class BM25 rescues. So the
end-to-end effect could be larger than +16.5 or smaller, and promoting on the
dense-only number would be promoting on a measurement of a configuration nobody
runs.

Why both models are re-embedded here
------------------------------------
The production index was built with the base model at its default sequence
length of 512. The tuned model was trained and evaluated at 224. Comparing a
224-tuned index against a 512-base index would confound the fine-tuning with the
sequence length, and the confound points the wrong way — it would flatter
whichever setting happened to suit the corpus.

So both shadows are built here, in one process, at 224, from the same chunks.
The only difference between them is the weights.

Nothing is promoted. Production collections are read and never written.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from langchain.retrievers import EnsembleRetriever  # noqa: E402
from langchain_chroma import Chroma  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402

import app.ai.pipelines.retriever as R  # noqa: E402
from app.ai.nodes.retrieval_node import _is_synthetic  # noqa: E402
from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

SOURCE = "constitutional_collection"
BASE_MODEL = "intfloat/multilingual-e5-base"
TUNED_DIR = "models/e5-pakistani-legal"
MAX_SEQ = 224
BM25_WEIGHT = 0.6      # the deployed fusion


class _E5(Embeddings):
    """e5 prefixes, applied exactly as the production retriever applies them."""

    def __init__(self, model):
        self.model = model

    def embed_documents(self, texts):
        return self.model.encode(["passage: " + t for t in texts],
                                 batch_size=16, normalize_embeddings=True,
                                 show_progress_bar=False).tolist()

    def embed_query(self, text):
        return self.model.encode(["query: " + text], normalize_embeddings=True)[0].tolist()


def _ndcg(ranked, gold, k):
    dcg = sum(1 / math.log2(i + 1) for i, c in enumerate(ranked[:k], 1) if c in gold)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def _score(retriever, tests):
    agg = {"hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "mrr": 0.0,
           "ndcg@5": 0.0, "ndcg@10": 0.0}
    ranks = {}
    for it in tests:
        gold = set(it["relevant_chunks"])
        docs = retriever.invoke(it["question"])
        ids = [d.metadata.get("chunk_id", "") for d in docs
               if not _is_synthetic(d.metadata or {})]
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


def _build_shadow(client, name, model, ids, docs, metas):
    from sentence_transformers import SentenceTransformer  # noqa: F401

    t0 = time.time()
    vectors = model.encode(["passage: " + (d or "") for d in docs],
                           batch_size=16, normalize_embeddings=True,
                           show_progress_bar=True).tolist()
    try:
        client.delete_collection(name)
    except Exception:
        pass
    col = client.create_collection(name, metadata={"hnsw:space": "cosine"})
    for i in range(0, len(ids), 500):
        col.add(ids=ids[i:i+500], documents=docs[i:i+500],
                metadatas=metas[i:i+500], embeddings=vectors[i:i+500])
    print(f"    {name}: {col.count()} chunks in {(time.time()-t0)/60:.1f} min")
    return col


def main(a) -> int:
    from sentence_transformers import SentenceTransformer

    connect_chroma()
    client = get_chroma()
    tests = json.loads(Path(a.tests).read_text(encoding="utf-8"))
    print(f"\n  held-out questions: {len(tests)}")

    src = client.get_collection(SOURCE)
    got = src.get(include=["documents", "metadatas"])
    ids, docs, metas = got["ids"], got["documents"], got["metadatas"]
    print(f"  corpus chunks     : {len(ids)}")

    models = {}
    print("\n  building shadow indexes at max_seq=%d (both models)…" % MAX_SEQ)
    for label, path in (("base", BASE_MODEL), ("tuned", TUNED_DIR)):
        m = SentenceTransformer(path, device="cpu")
        m.max_seq_length = MAX_SEQ
        models[label] = m
        _build_shadow(client, f"phase_a_shadow_{label}", m, ids, docs, metas)

    where = {"$or": [{"province": {"$eq": "federal"}},
                     {"province": {"$eq": "federal"}}]}
    bm25 = R._FilteredBM25Retriever(bm25=R._bm25(SOURCE), province="federal")

    results = {}
    for label in ("base", "tuned"):
        store = Chroma(client=client, collection_name=f"phase_a_shadow_{label}",
                       embedding_function=_E5(models[label]))
        dense = store.as_retriever(search_kwargs={"k": R.FIRST_STAGE_K,
                                                  "filter": where})
        hybrid = EnsembleRetriever(retrievers=[bm25, dense],
                                   weights=[BM25_WEIGHT, round(1 - BM25_WEIGHT, 2)])
        print(f"\n  scoring {label} …")
        results[f"{label}_dense"], _ = _score(dense, tests)
        results[f"{label}_hybrid"], results[f"{label}_ranks"] = _score(hybrid, tests)

    keys = ("hit@1", "hit@3", "hit@5", "mrr", "ndcg@5", "ndcg@10")
    for mode in ("dense", "hybrid"):
        b, t = results[f"base_{mode}"], results[f"tuned_{mode}"]
        print(f"\n  {mode.upper()}  (BM25 {BM25_WEIGHT}/dense {round(1-BM25_WEIGHT,2)})"
              if mode == "hybrid" else f"\n  {mode.upper()}")
        print(f"  {'metric':<10}{'base':>10}{'tuned':>10}{'delta':>10}")
        print("  " + "-" * 40)
        for k in keys:
            print(f"  {k:<10}{b[k]:>10.4f}{t[k]:>10.4f}{t[k]-b[k]:>+10.4f}")

    # The decision this script exists to inform.
    hb, ht = results["base_hybrid"], results["tuned_hybrid"]
    d_hit1 = ht["hit@1"] - hb["hit@1"]
    d_mrr = ht["mrr"] - hb["mrr"]
    print("\n  " + "=" * 52)
    print(f"  HYBRID delta: Hit@1 {d_hit1:+.4f}   MRR {d_mrr:+.4f}")
    if d_hit1 > 0.02 and d_mrr > 0.02:
        print("  -> the tuned model helps the configuration production runs")
    elif d_hit1 < -0.02 or d_mrr < -0.02:
        print("  -> the tuned model HURTS in production configuration; the "
              "dense-only gain does not survive fusion")
    else:
        print("  -> within noise (baseline run-to-run variation was ~1.7 pts); "
              "not evidence for promotion")

    rb, rt = results["base_ranks"], results["tuned_ranks"]
    MISS = 10_000
    moves = [(q, rb[q], rt[q]) for q in rb]
    imp = [m for m in moves if (m[2] or MISS) < (m[1] or MISS)]
    wor = [m for m in moves if (m[2] or MISS) > (m[1] or MISS)]
    print(f"\n  hybrid per-query: improved {len(imp)}  worsened {len(wor)}  "
          f"unchanged {len(moves)-len(imp)-len(wor)}")
    fmt = lambda r: "miss" if r is None else f"#{r}"
    print("\n  worst hybrid regressions")
    for q, b_, t_ in sorted(wor, key=lambda m: (m[2] or MISS) - (m[1] or MISS),
                            reverse=True)[:5]:
        print(f"    {fmt(b_):>5} -> {fmt(t_):<5} {q[:66]}")

    Path(a.out).write_text(json.dumps(
        {k: v for k, v in results.items() if not k.endswith("_ranks")},
        indent=2), encoding="utf-8")
    print(f"\n  wrote {a.out}")
    print("  production collections were not modified.\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Phase A: hybrid evaluation.")
    p.add_argument("--tests", default="data/finetune/test_questions.json")
    p.add_argument("--out", default="data/phase_a_result.json")
    raise SystemExit(main(p.parse_args()))
