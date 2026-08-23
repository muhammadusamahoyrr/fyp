"""build_general_bundle.py — one bundle for the three-way model comparison.

Goal
----
Train a single general Pakistani legal embedding model on all verified pairs
(constitutional, criminal, evidence, civil, family) and compare three models on
the same held-out questions:

    1. base                — intfloat/multilingual-e5-base
    2. constitutional-only — usama1111/e5-pakistani-legal
    3. general             — trained in the notebook from this bundle

Why all three, and why the shadow indexes are rebuilt in Colab
--------------------------------------------------------------
The constitutional-only model was trained BEFORE two corpus repairs landed: 164
Schedule paragraphs falsely numbered as Articles, and the ingestion of CPC 1908.
Comparing it against a general model on the corrected corpus, using its old
index, would attribute the corpus repair to the training data. So all three
models embed the same corrected chunks inside the notebook, and the only thing
differing is the weights.

Leakage
-------
Split by connected components over shared positive chunks, not by question.
Several questions cite the same section, so a question-level split would put one
question about PPC s.302 in train and another in test, and the score would
measure memorisation. Components are then assigned to train/test greedily per
DOMAIN, so every domain has held-out coverage rather than whichever domains
happened to fall in the test half.

Hard negatives are NOT mined here. Doing it locally would mean 5,883 CPU
retrievals; the notebook mines them on GPU from the base model in seconds.

Usage
-----
  python scripts/build_general_bundle.py --out data/general_bundle.json
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

COLLECTIONS = ("constitutional_collection", "criminal_collection",
               "civil_collection", "family_collection")
SYNTHETIC_PREFIX = "legal_uqa_qa_"
TEST_FRACTION = 0.20
SEED = 20260807


def _components(pairs):
    """Group pairs sharing a positive chunk. Transitive, so union-find."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, p in enumerate(pairs):
        union(f"__q{i}", p["positive_id"])

    groups = collections.defaultdict(list)
    for i, p in enumerate(pairs):
        groups[find(f"__q{i}")].append(p)
    return list(groups.values())


def main(a) -> int:
    pairs = json.loads(Path(a.pairs).read_text(encoding="utf-8"))
    print(f"\n  verified pairs: {len(pairs)}")

    connect_chroma()
    client = get_chroma()
    corpus = {}
    for coll in COLLECTIONS:
        try:
            g = client.get_collection(coll).get(include=["documents"])
        except Exception:
            continue
        for cid, doc in zip(g["ids"], g["documents"]):
            # Generated QA pairs are excluded from retrieval in production and
            # must not appear as candidates here either.
            if not cid.startswith(SYNTHETIC_PREFIX):
                corpus[cid] = doc or ""
    print(f"  corpus chunks : {len(corpus)}")

    missing = [p for p in pairs if p["positive_id"] not in corpus]
    if missing:
        print(f"  dropping {len(missing)} pair(s) whose positive is not in the corpus")
        pairs = [p for p in pairs if p["positive_id"] in corpus]

    # ── split components per domain ─────────────────────────────────────────
    comps = _components(pairs)
    rng = random.Random(SEED)
    rng.shuffle(comps)

    by_domain_target = collections.Counter(p["domain"] for p in pairs)
    for d in by_domain_target:
        by_domain_target[d] = by_domain_target[d] * TEST_FRACTION

    test_running = collections.Counter()
    train, test = [], []
    for comp in comps:
        # A component's domain is its majority domain.
        dom = collections.Counter(p["domain"] for p in comp).most_common(1)[0][0]
        if test_running[dom] < by_domain_target[dom]:
            test.extend(comp)
            test_running[dom] += len(comp)
        else:
            train.extend(comp)

    train_pos = {p["positive_id"] for p in train}
    test_pos = {p["positive_id"] for p in test}
    overlap = train_pos & test_pos
    if overlap:
        raise SystemExit(
            f"LEAKAGE: {len(overlap)} positive chunk(s) in both splits, "
            f"e.g. {sorted(overlap)[:3]}"
        )

    print(f"\n  components    : {len(comps)}")
    print(f"  train / test  : {len(train)} / {len(test)}")
    print(f"  positive-chunk overlap: 0")
    print(f"\n  {'domain':<18}{'train':>8}{'test':>8}")
    dt = collections.Counter(p["domain"] for p in train)
    ds = collections.Counter(p["domain"] for p in test)
    for d in sorted(set(dt) | set(ds)):
        print(f"  {d:<18}{dt[d]:>8}{ds[d]:>8}")
    urdu = sum(1 for p in test if p.get("urdu_query"))
    print(f"\n  test questions with an Urdu query: {urdu} "
          f"({100*urdu/max(len(test),1):.0f}%)")

    bundle = {
        "base_model": "intfloat/multilingual-e5-base",
        "constitutional_model": "usama1111/e5-pakistani-legal",
        "seed": SEED,
        "train": [{"query": p["query"], "positive_id": p["positive_id"],
                   "domain": p["domain"]} for p in train],
        "test": [{"query": p["query"], "positive_id": p["positive_id"],
                  "domain": p["domain"], "urdu_query": p.get("urdu_query", False)}
                 for p in test],
        "corpus": corpus,
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    print(f"\n  wrote {out}  ({out.stat().st_size/1e6:.1f} MB)")
    print("\n  Upload to Colab and run scripts/colab_general_finetune.py\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Bundle for the general model.")
    p.add_argument("--pairs", default="data/citation_train/verified_pairs.json")
    p.add_argument("--out", type=Path, default=Path("data/general_bundle.json"))
    raise SystemExit(main(p.parse_args()))
