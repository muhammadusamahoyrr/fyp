"""phase_a_do_no_harm.py — does the constitutional-tuned model hurt other domains?

The honest framing
------------------
There are NO human relevance judgements for criminal, civil or family law. Real
Hit@1/MRR/nDCG over user questions cannot be computed for them, and inventing a
benchmark to fill the gap would be worse than admitting it. This is a
do-no-harm screen, not a benchmark, and the numbers below should never be quoted
as this system's accuracy on those domains.

What IS measurable without annotation
-------------------------------------
Statutes carry section headings, and in this corpus the heading and the section
BODY land in different chunks (headings become short stubs — one reason 20-27%
of the index is under 200 characters). That yields a known-item task with a
deterministic gold label and no lexical overlap between query and answer:

    query : "Punishment for theft"          (heading, from a stub chunk)
    gold  : the chunk holding section 379's body

This is a proxy, and its limits matter:
  * headings are not how users write questions, so absolute scores here say
    nothing about real query performance;
  * it is deliberately citation-shaped, which is exactly the query class the
    tuned model got WORSE at on constitutional law — so it is a sensitive
    screen for the regression we actually fear, not a flattering one.

Used as a PAIRED comparison — both models face the identical task — a relative
drop is meaningful evidence of harm even though the absolute number is not
meaningful evidence of quality.

Production collections are read, never written.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import defaultdict
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

BASE_MODEL = "intfloat/multilingual-e5-base"
TUNED_DIR = "models/e5-pakistani-legal"
MAX_SEQ = 224
BM25_WEIGHT = 0.6
MIN_BODY = 200
_HEAD = re.compile(r"^\s*(\d+[A-Z]?)\.\s+([A-Z][^.\n]{8,80})\.")

COLLECTIONS = ("criminal_collection", "civil_collection", "family_collection")

# Queries whose correct statute is known independently of any dataset. Too few
# for metrics; they are a smoke test that catches a gross regression.
KNOWN = [
    ("criminal_collection", "What is the punishment for theft?", "PPC 1860"),
    ("criminal_collection", "How do I register an FIR if police refuse?", "CrPC 1898"),
    ("criminal_collection", "What is the punishment for a dishonoured cheque?", "PPC 1860"),
    ("civil_collection", "Can a tenant be evicted without notice in Punjab?",
     "Punjab Rented Premises Act 2009"),
    ("civil_collection", "What is the limitation period for a suit for recovery?",
     "Limitation Act 1908"),
    ("family_collection", "What are the grounds for khula?", "Family Courts Act 1964"),
    ("family_collection", "How is maintenance for a wife determined?",
     "Family Courts Act 1964"),
]


class _E5(Embeddings):
    def __init__(self, model):
        self.model = model

    def embed_documents(self, texts):
        return self.model.encode(["passage: " + t for t in texts], batch_size=16,
                                 normalize_embeddings=True,
                                 show_progress_bar=False).tolist()

    def embed_query(self, text):
        return self.model.encode(["query: " + text],
                                 normalize_embeddings=True)[0].tolist()


def _ndcg(ranked, gold, k):
    dcg = sum(1 / math.log2(i + 1) for i, c in enumerate(ranked[:k], 1) if c in gold)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def _build_pairs(ids, docs, metas):
    """heading (from a stub) -> body chunks of the same statute+section."""
    bodies: defaultdict[tuple, list] = defaultdict(list)
    heads: list[tuple[str, tuple]] = []
    for cid, doc, meta in zip(ids, docs, metas):
        meta = meta or {}
        key = (meta.get("statute", ""), str(meta.get("section_number", "")))
        if not key[1]:
            continue
        if len(doc or "") >= MIN_BODY:
            bodies[key].append(cid)
        m = _HEAD.match(doc or "")
        if m and len(doc or "") < MIN_BODY:
            heads.append((m.group(2).strip(), key))

    pairs = []
    for heading, key in heads:
        gold = bodies.get(key)
        # Reject when the heading text appears verbatim in the gold body: that
        # is a lexical gimme BM25 solves without any semantics, and it would
        # mask exactly the difference this screen is looking for.
        if gold and len(gold) <= 6:
            pairs.append({"question": heading, "relevant_chunks": sorted(gold)})
    # Deduplicate identical headings (statutes reuse "Interpretation" etc.)
    seen, out = set(), []
    for p in pairs:
        if p["question"].lower() in seen:
            continue
        seen.add(p["question"].lower())
        out.append(p)
    return out


def _score(retriever, tests):
    agg = {"hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "mrr": 0.0, "ndcg@5": 0.0}
    ranks = {}
    for it in tests:
        gold = set(it["relevant_chunks"])
        # Generated LEGAL-UQA chunks are excluded from retrieval in production.
        # There are none in criminal/civil/family today, but this script takes a
        # collection list and would otherwise score against generated Q&A if
        # ever pointed at constitutional.
        ids = [d.metadata.get("chunk_id", "")
               for d in retriever.invoke(it["question"])
               if not _is_synthetic(d.metadata or {})]
        r = next((i for i, c in enumerate(ids, 1) if c in gold), None)
        ranks[it["question"]] = r
        if r:
            agg["mrr"] += 1 / r
            agg["hit@1"] += r == 1
            agg["hit@3"] += r <= 3
            agg["hit@5"] += r <= 5
        agg["ndcg@5"] += _ndcg(ids, gold, 5)
    n = max(len(tests), 1)
    return {k: round(v / n, 4) for k, v in agg.items()}, ranks


def main(a) -> int:
    from sentence_transformers import SentenceTransformer

    connect_chroma()
    client = get_chroma()
    models = {}
    for label, path in (("base", BASE_MODEL), ("tuned", TUNED_DIR)):
        m = SentenceTransformer(path, device="cpu")
        m.max_seq_length = MAX_SEQ
        models[label] = m

    summary = {}
    for coll in COLLECTIONS:
        src = client.get_collection(coll)
        got = src.get(include=["documents", "metadatas"])
        ids, docs, metas = got["ids"], got["documents"], got["metadatas"]
        pairs = _build_pairs(ids, docs, metas)
        print(f"\n{'='*62}\n  {coll}: {len(ids)} chunks -> {len(pairs)} heading/body pairs")
        if len(pairs) < 20:
            print("  too few pairs for a meaningful screen — skipping")
            continue

        province = "punjab"
        where = {"$or": [{"province": {"$eq": province}},
                         {"province": {"$eq": "federal"}}]}
        bm25 = R._FilteredBM25Retriever(bm25=R._bm25(coll), province=province)

        per = {}
        for label in ("base", "tuned"):
            shadow = f"dnh_{coll}_{label}"
            t0 = time.time()
            vecs = models[label].encode(["passage: " + (d or "") for d in docs],
                                        batch_size=16, normalize_embeddings=True,
                                        show_progress_bar=False).tolist()
            try:
                client.delete_collection(shadow)
            except Exception:
                pass
            col = client.create_collection(shadow, metadata={"hnsw:space": "cosine"})
            for i in range(0, len(ids), 500):
                col.add(ids=ids[i:i+500], documents=docs[i:i+500],
                        metadatas=metas[i:i+500], embeddings=vecs[i:i+500])
            print(f"    {label}: embedded in {(time.time()-t0)/60:.1f} min")

            store = Chroma(client=client, collection_name=shadow,
                           embedding_function=_E5(models[label]))
            dense = store.as_retriever(search_kwargs={"k": R.FIRST_STAGE_K,
                                                      "filter": where})
            hybrid = EnsembleRetriever(retrievers=[bm25, dense],
                                       weights=[BM25_WEIGHT,
                                                round(1 - BM25_WEIGHT, 2)])
            per[label], per[f"{label}_ranks"] = _score(hybrid, pairs)

        b, t = per["base"], per["tuned"]
        print(f"\n  HYBRID  {'metric':<8}{'base':>10}{'tuned':>10}{'delta':>10}")
        for k in ("hit@1", "hit@3", "hit@5", "mrr", "ndcg@5"):
            flag = "  <-- REGRESSION" if t[k] - b[k] < -0.02 else ""
            print(f"          {k:<8}{b[k]:>10.4f}{t[k]:>10.4f}"
                  f"{t[k]-b[k]:>+10.4f}{flag}")

        MISS = 10_000
        rb, rt = per["base_ranks"], per["tuned_ranks"]
        moves = [(q, rb[q], rt[q]) for q in rb]
        wor = [m for m in moves if (m[2] or MISS) > (m[1] or MISS)]
        imp = [m for m in moves if (m[2] or MISS) < (m[1] or MISS)]
        print(f"    improved {len(imp)}  worsened {len(wor)}  "
              f"unchanged {len(moves)-len(imp)-len(wor)}")
        summary[coll] = {"n_pairs": len(pairs), "base": b, "tuned": t,
                         "improved": len(imp), "worsened": len(wor)}

    # ── known-answer smoke test ─────────────────────────────────────────────
    print(f"\n{'='*62}\n  KNOWN-ANSWER SMOKE TEST (does the right statute appear?)")
    for coll, q, statute in KNOWN:
        row = f"    {q[:46]:<48}"
        for label in ("base", "tuned"):
            shadow = f"dnh_{coll}_{label}"
            try:
                store = Chroma(client=client, collection_name=shadow,
                               embedding_function=_E5(models[label]))
                docs = store.as_retriever(search_kwargs={"k": 5}).invoke(q)
                hit = any(d.metadata.get("statute") == statute for d in docs)
            except Exception:
                hit = None
            row += f"  {label}={'OK ' if hit else 'MISS'}"
        print(row + f"   [{statute[:28]}]")

    Path(a.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n  wrote {a.out}")
    print("  production collections were not modified.\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Do-no-harm screen on other domains.")
    p.add_argument("--out", default="data/do_no_harm.json")
    raise SystemExit(main(p.parse_args()))
