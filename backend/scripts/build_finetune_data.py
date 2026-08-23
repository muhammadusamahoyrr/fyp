"""build_finetune_data.py — training data for retriever domain adaptation.

Diagnosis this addresses
------------------------
On 200 held-out constitutional questions the gold article is findable at dense
depth 50 for 89% of them, but reaches rank 1 for only 43.5%. That is a 45-point
RANKING gap, not a recall gap. A generic cross-encoder was measured twice and
made it worse, and sweeping the hybrid fusion weights produced no gain at any
setting. What remains untried is teaching the embedding model this domain.

Leakage is the thing to get right
---------------------------------
The split is by GOLD CHUNK GROUP, never by question. LEGAL-UQA generates several
questions per constitutional article, so splitting on questions would put one
question about Article 25 in train and another about Article 25 in test. The
model would have been trained to pull that exact chunk towards that exact
phrasing, and the test score would measure memorisation. Grouping first makes
the held-out articles genuinely unseen.

Hard negatives
--------------
Training on positives alone is known to give only marginal gains; the
improvement comes from negatives that the current model ranks ABOVE the right
answer. Those are free here — they are exactly the chunks retrieval puts first
today. Mining them from the deployed retriever means the model is trained on
its own confusions rather than on random passages, which are trivially
separable and teach nothing.

Guards:
  * a "negative" that is actually gold for this question is dropped;
  * a negative that is a heading stub is dropped — 27% of the corpus is under
    200 characters, and teaching the model to push away fragments it should
    never have indexed is wasted capacity;
  * questions with no mined negative still contribute as positive pairs.

Usage
-----
  python scripts/build_finetune_data.py --out data/finetune
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.ai.nodes.retrieval_node import _is_synthetic  # noqa: E402
from app.ai.pipelines.retriever import build_retriever  # noqa: E402
from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

COLLECTION = "constitutional_collection"
TEST_FRACTION = 0.20
SEED = 20260807

# Negatives shorter than this are heading stubs, not competing law.
MIN_NEGATIVE_CHARS = 200
# Per question. Gains plateau well above this; more would just slow CPU training.
MAX_NEGATIVES = 3


def _components(items: list[dict]) -> dict[int, list[dict]]:
    """Group questions into connected components over shared gold chunks.

    Grouping by the exact gold SET is not enough, and the leakage guard caught
    it: a question with gold {X, Y} and one with gold {Y, Z} get different set
    keys but share Y, so splitting on those keys still puts chunk Y in both
    halves. Two questions belong together if they share ANY gold chunk, and that
    relation is transitive — so the correct unit is the connected component of
    the question/chunk bipartite graph, found here with union-find.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Link every question to each of its gold chunks; components fall out.
    for i, it in enumerate(items):
        qkey = f"__q{i}"
        for c in it["relevant_chunks"]:
            union(qkey, c)

    groups: dict[str, list[dict]] = defaultdict(list)
    for i, it in enumerate(items):
        groups[find(f"__q{i}")].append(it)
    return {n: v for n, v in enumerate(groups.values())}


def main(out_dir: Path, eval_path: Path) -> int:
    connect_chroma()
    col = get_chroma().get_collection(COLLECTION)
    got = col.get(include=["documents"])
    text = {cid: (doc or "") for cid, doc in zip(got["ids"], got["documents"])}

    items = json.loads(eval_path.read_text(encoding="utf-8"))
    print(f"\n  questions: {len(items)}")

    # ── group into connected components, then split whole components ────────
    groups = _components(items)
    keys = sorted(groups)
    random.Random(SEED).shuffle(keys)

    # Split by QUESTION count rather than component count: components vary in
    # size, so taking 20% of components can yield far from 20% of questions.
    target = len(items) * TEST_FRACTION
    test_keys: set[int] = set()
    running = 0
    for k in keys:
        if running >= target:
            break
        test_keys.add(k)
        running += len(groups[k])
    train_keys = set(keys) - test_keys
    train = [it for k in train_keys for it in groups[k]]
    test = [it for k in test_keys for it in groups[k]]

    print(f"  connected components: {len(keys)}")
    print(f"  train: {len(train)} questions over {len(train_keys)} groups")
    print(f"  test : {len(test)} questions over {len(test_keys)} groups")

    # The guard that matters. If this ever trips, the measured gain is fiction.
    train_gold = {c for it in train for c in it["relevant_chunks"]}
    test_gold = {c for it in test for c in it["relevant_chunks"]}
    overlap = train_gold & test_gold
    if overlap:
        raise SystemExit(
            f"LEAKAGE: {len(overlap)} gold chunk(s) appear in both splits, "
            f"e.g. {sorted(overlap)[:3]} — the split is not group-clean"
        )
    print(f"  gold-chunk overlap between splits: 0  (train {len(train_gold)}, "
          f"test {len(test_gold)})")

    # ── mine hard negatives from the deployed retriever ─────────────────────
    print("\n  mining hard negatives from the current retriever…")
    retriever = build_retriever("constitutional", "federal")
    triplets, positives_only, no_text = [], 0, 0

    for n, it in enumerate(train, 1):
        if n % 100 == 0:
            print(f"    {n}/{len(train)}")
        gold = set(it["relevant_chunks"])
        pos_id = next((c for c in sorted(gold) if len(text.get(c, "")) >= MIN_NEGATIVE_CHARS),
                      None)
        if pos_id is None:
            no_text += 1
            continue

        try:
            docs = retriever.invoke(it["question"])
        except Exception:
            docs = []

        negatives = []
        for d in docs:
            meta = d.metadata or {}
            cid = meta.get("chunk_id", "")
            if _is_synthetic(meta) or cid in gold:
                continue
            body = text.get(cid, "")
            if len(body) < MIN_NEGATIVE_CHARS:
                continue
            negatives.append(body)
            if len(negatives) >= MAX_NEGATIVES:
                break

        if not negatives:
            positives_only += 1
            triplets.append({"query": it["question"], "positive": text[pos_id]})
            continue
        for neg in negatives:
            triplets.append({"query": it["question"],
                             "positive": text[pos_id], "negative": neg})

    print(f"\n  training examples : {len(triplets)}")
    print(f"    with a hard negative : {sum(1 for t in triplets if 'negative' in t)}")
    print(f"    positive-only        : {positives_only}")
    print(f"    dropped, no usable gold text: {no_text}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "train_triplets.json").write_text(
        json.dumps(triplets, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "test_questions.json").write_text(
        json.dumps(test, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "split_manifest.json").write_text(json.dumps({
        "seed": SEED,
        "test_fraction": TEST_FRACTION,
        "n_train_questions": len(train),
        "n_test_questions": len(test),
        "n_train_groups": len(train_keys),
        "n_test_groups": len(test_keys),
        "gold_overlap": 0,
        "grouped_by": "connected components over shared gold chunks",
    }, indent=2), encoding="utf-8")

    print(f"\n  wrote -> {out_dir}")
    print(f"\n  Next:\n    python scripts/finetune_retriever.py "
          f"--data {out_dir}\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build retriever fine-tuning data.")
    p.add_argument("--out", type=Path, default=Path("data/finetune"))
    p.add_argument("--eval", type=Path, default=Path("data/uqa_eval.json"))
    a = p.parse_args()
    raise SystemExit(main(a.out, a.eval))
