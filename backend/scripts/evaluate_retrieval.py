"""
evaluate_retrieval.py — Hit@K, MRR, and nDCG evaluation against LEGAL-UQA pairs.

Usage:
    python scripts/evaluate_retrieval.py --dataset path/to/legal_uqa.json --k 1 3 5

Dataset format (JSON list):
    [
        {
            "question": "Can a tenant be evicted without notice in Punjab?",
            "answer":   "Under the Punjab Rented Premises Act ...",
            "case_type": "civil",
            "province":  "punjab",
            "relevant_chunks": ["chunk_id_1", "chunk_id_2"]  # optional ground truth
        },
        ...
    ]

Output:
    - Per case_type + province breakdown
    - Overall Hit@1, Hit@3, Hit@5, MRR, nDCG@5
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

# ── Path setup ────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.ai.pipelines.retriever import build_retriever  # noqa: E402


# ── Metric functions ──────────────────────────────────────────────────────────

def hit_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """1.0 if any relevant doc appears in top-k retrieved, else 0.0"""
    return 1.0 if any(r in relevant_ids for r in retrieved_ids[:k]) else 0.0


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """1/rank of the first relevant document (0 if none found)."""
    for i, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_ids:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at k."""
    def dcg(ids: list[str], k: int) -> float:
        score = 0.0
        for i, rid in enumerate(ids[:k], start=1):
            rel = 1.0 if rid in relevant_ids else 0.0
            score += rel / math.log2(i + 1)
        return score

    actual_dcg  = dcg(retrieved_ids, k)
    # Ideal: put all relevant docs first
    ideal_order = list(relevant_ids)[:k]
    ideal_dcg   = dcg(ideal_order + [""] * k, k)  # pad with irrelevant

    return actual_dcg / ideal_dcg if ideal_dcg > 0 else 0.0


# ── Evaluation runner ─────────────────────────────────────────────────────────

def evaluate(dataset: list[dict], ks: list[int]) -> dict[str, Any]:
    results_by_group: dict[str, list[dict]] = {}

    for i, item in enumerate(dataset):
        question      = item["question"]
        case_type     = item.get("case_type", "unknown")
        province      = item.get("province",  "federal")
        relevant_ids  = set(item.get("relevant_chunks", []))

        # If no explicit relevant_chunks, use content-based matching
        use_content_match = len(relevant_ids) == 0
        reference_answer  = item.get("answer", "")

        try:
            retriever = build_retriever(case_type, province)
            docs      = retriever.invoke(question)
        except Exception as e:
            print(f"  ⚠ Item {i} retrieval failed: {e}")
            continue

        retrieved_ids = [
            doc.metadata.get("chunk_id", f"__pos_{j}")
            for j, doc in enumerate(docs)
        ]

        if use_content_match:
            # Fallback: check if any retrieved chunk content overlaps with the reference answer
            # (rough proxy when chunk_ids are not in the dataset)
            relevant_ids = set()
            answer_words = set(reference_answer.lower().split()[:30])
            for j, doc in enumerate(docs):
                doc_words = set(doc.page_content.lower().split()[:50])
                if len(answer_words & doc_words) >= 5:   # at least 5 words overlap
                    relevant_ids.add(retrieved_ids[j])

        if not relevant_ids:
            continue  # skip items we can't score

        metrics = {
            "mrr": reciprocal_rank(retrieved_ids, relevant_ids),
            **{f"hit@{k}": hit_at_k(retrieved_ids, relevant_ids, k) for k in ks},
            **{f"ndcg@{k}": ndcg_at_k(retrieved_ids, relevant_ids, k) for k in ks},
        }

        group_key = f"{case_type}|{province}"
        results_by_group.setdefault(group_key, []).append(metrics)

        if (i + 1) % 50 == 0:
            print(f"  Evaluated {i + 1}/{len(dataset)} items...")

    # ── Aggregate ─────────────────────────────────────────────────────────────
    summary: dict[str, Any] = {}
    all_metrics: list[dict] = []

    for group, items in sorted(results_by_group.items()):
        n       = len(items)
        avg     = {k: sum(m[k] for m in items) / n for k in items[0]}
        summary[group] = {"n": n, **avg}
        all_metrics.extend(items)

    if all_metrics:
        n_total   = len(all_metrics)
        aggregate = {k: sum(m[k] for m in all_metrics) / n_total for k in all_metrics[0]}
        summary["OVERALL"] = {"n": n_total, **aggregate}

    return summary


def _print_report(summary: dict, ks: list[int]) -> None:
    width = 80
    print("\n" + "=" * width)
    print("  ATTORNEY.AI RETRIEVAL EVALUATION REPORT")
    print("=" * width)

    header_cols = ["Group", "N", "MRR"] + [f"H@{k}" for k in ks] + [f"nDCG@{k}" for k in ks]
    print(f"{'Group':<30} {'N':>5}  {'MRR':>6}  " + "  ".join(f"H@{k}".rjust(6) for k in ks) + "  " + "  ".join(f"nD@{k}".rjust(6) for k in ks))
    print("-" * width)

    for group, stats in summary.items():
        n   = stats["n"]
        mrr = stats.get("mrr", 0.0)
        hits  = [stats.get(f"hit@{k}", 0.0) for k in ks]
        ndcgs = [stats.get(f"ndcg@{k}", 0.0) for k in ks]

        marker = " ←" if group == "OVERALL" else ""
        row    = f"{group:<30} {n:>5}  {mrr:>6.3f}  "
        row   += "  ".join(f"{h:>6.3f}" for h in hits)
        row   += "  " + "  ".join(f"{d:>6.3f}" for d in ndcgs)
        row   += marker
        print(row)

    print("=" * width)

    # Highlight worst performers
    group_stats = {k: v for k, v in summary.items() if k != "OVERALL"}
    if group_stats:
        worst = min(group_stats, key=lambda k: group_stats[k].get("mrr", 1.0))
        print(f"\n⚠ Worst performing group: {worst}  (MRR={group_stats[worst].get('mrr', 0):.3f})")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Attorney.AI retrieval pipeline.")
    parser.add_argument("--dataset", required=True, help="Path to LEGAL-UQA JSON file")
    parser.add_argument("--k",       nargs="+", type=int, default=[1, 3, 5], help="K values for Hit@K and nDCG@K")
    parser.add_argument("--output",  default=None, help="Optional: save summary JSON to file")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"❌ Dataset not found: {dataset_path}")
        sys.exit(1)

    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)

    print(f"📂 Loaded {len(dataset)} Q&A pairs from {dataset_path}")
    print(f"📊 Evaluating with k={args.k}...\n")

    summary = evaluate(dataset, args.k)
    _print_report(summary, args.k)

    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        print(f"\n💾 Summary saved to: {out_path}")
