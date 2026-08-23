"""export_colab_bundle.py — everything Colab needs, in one file.

Why offload
-----------
This machine is CPU-only with 15.8 GB of RAM. Fine-tuning e5-base held 9.2 GB
and was killed by memory pressure twice, at 45% and 18% of an epoch. A free
Colab T4 does the same work in a couple of minutes.

What goes in the bundle
-----------------------
Training triplets, the held-out test questions, and the corpus text keyed by
chunk id. The corpus is included so the ENTIRE experiment — train, re-embed,
evaluate baseline vs tuned — runs in Colab. That matters for two reasons:

  * nothing has to come back except a small results file, unless the model
    actually wins. The e5-base weights are ~1.1 GB and there is no reason to
    download them to find out they did not help.
  * the baseline is recomputed in the same notebook, on the same questions,
    with the same code. Comparing a Colab-trained model against a
    locally-measured baseline would let environment differences masquerade as
    a gain.

Only chunk ids and text are exported. No user data, no provenance records, no
queries from real traffic — the questions are LEGAL-UQA's, which are public.

Usage
-----
  python scripts/export_colab_bundle.py --out data/colab_bundle.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

COLLECTION = "constitutional_collection"
SYNTHETIC_PREFIX = "legal_uqa_qa_"


def main(data_dir: Path, out: Path) -> int:
    connect_chroma()
    col = get_chroma().get_collection(COLLECTION)
    got = col.get(include=["documents", "metadatas"])

    # Generated QA pairs are excluded from retrieval in production; including
    # them here would let the notebook measure something the system never does,
    # and they contain each test question verbatim.
    corpus = {
        cid: (doc or "")
        for cid, doc in zip(got["ids"], got["documents"])
        if not cid.startswith(SYNTHETIC_PREFIX)
    }
    skipped = len(got["ids"]) - len(corpus)

    train = json.loads((data_dir / "train_triplets.json").read_text(encoding="utf-8"))
    test = json.loads((data_dir / "test_questions.json").read_text(encoding="utf-8"))
    manifest = json.loads((data_dir / "split_manifest.json").read_text(encoding="utf-8"))

    # Re-assert the property the whole experiment rests on. If this bundle
    # leaked, every number the notebook prints would be inflated.
    train_q = {t["query"] for t in train}
    test_q = {t["question"] for t in test}
    if train_q & test_q:
        raise SystemExit(
            f"LEAKAGE: {len(train_q & test_q)} question(s) in both splits"
        )
    gold_test = {c for t in test for c in t["relevant_chunks"]}
    missing = [c for c in gold_test if c not in corpus]
    if missing:
        raise SystemExit(
            f"{len(missing)} gold chunk(s) are not in the exported corpus, "
            f"e.g. {missing[:3]} — the notebook could never find them"
        )

    bundle = {
        "base_model": "intfloat/multilingual-e5-base",
        "manifest": manifest,
        "train_triplets": train,
        "test_questions": test,
        "corpus": corpus,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")

    mb = out.stat().st_size / 1e6
    print(f"\n  corpus chunks     : {len(corpus)}  ({skipped} generated, excluded)")
    print(f"  train triplets    : {len(train)}")
    print(f"  test questions    : {len(test)}")
    print(f"  gold chunks (test): {len(gold_test)}  — all present in corpus")
    print(f"  question overlap  : 0")
    print(f"\n  wrote {out}  ({mb:.1f} MB)")
    print("\n  Upload this file to Colab and run scripts/colab_finetune.ipynb\n")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Export a self-contained Colab bundle.")
    p.add_argument("--data", type=Path, default=Path("data/finetune"))
    p.add_argument("--out", type=Path, default=Path("data/colab_bundle.json"))
    a = p.parse_args()
    raise SystemExit(main(a.data, a.out))
