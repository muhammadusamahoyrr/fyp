"""Run the P4 evaluation of the analyzer's AI report layer.

    python scripts/analyzer_eval.py --responder oracle
    AAI_LIVE_TESTS=1 python scripts/analyzer_eval.py --responder live --model openai/gpt-oss-120b \
        --runs 3 [--price-in 0.15 --price-out 0.60]

`oracle` answers the labels (no network): it proves the harness and the
dataset. `live` makes one call per document per run to ONE allowlisted model
through the pinned client -- no fallback -- and is refused unless
AAI_LIVE_TESTS=1 and the AI contract is fully ready (ANALYZER_AI on, verified
ZDR, synthetic-only; see app/services/analyzer/ai_config.py). Benchmark each
allowlisted model with its own invocation.

Writes analyzer_eval/results/<date>_<model>_<dataset hash>.json with the
dataset hash, model id, prompt and schema versions, date, the policy and ZDR
record, every metric and per-document detail. Prints the headline metrics
and exits 1 if a gate fails (evidence validity 100%, no leakage, no
injection success). Cost uses --price-in/--price-out, else
analyzer_eval/prices.yaml; a model without a published rate gets null.

A passing result does NOT update the frozen record
(app/services/analyzer/ai_evaluation_record.yaml): that is a reviewed
commit, and label_review stays developer_only until a qualified reviewer
approves the dataset labels.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.analyzer import ai_config, evaluation  # noqa: E402

RESULTS = BACKEND / "analyzer_eval" / "results"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--responder", choices=("oracle", "live"), required=True)
    parser.add_argument("--model", help="one allowlisted model id (live only)")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--price-in", type=float, help="USD per 1M prompt tokens")
    parser.add_argument("--price-out", type=float, help="USD per 1M completion tokens")
    parser.add_argument("--write", action="store_true", help="write the result file (live runs always do)")
    args = parser.parse_args()

    from app.core.config import settings

    if args.responder == "live":
        if os.environ.get("AAI_LIVE_TESTS") != "1":
            print("REFUSED: live evaluation needs AAI_LIVE_TESTS=1")
            return 2
        problems = ai_config.problems(settings) if settings.analyzer_ai else ["ANALYZER_AI is off"]
        if problems:
            print("REFUSED: the AI contract is not ready:\n  " + "\n  ".join(problems))
            return 2
        if args.model not in ai_config.allowlist(settings.analyzer_ai_model_allowlist):
            print("REFUSED: --model must be one allowlisted model")
            return 2
        responder = evaluation.live_responder(args.model)
    else:
        responder = evaluation.oracle_responder

    price = (args.price_in, args.price_out) if args.price_in is not None and args.price_out is not None else None
    if price is None and args.responder == "live":
        price = evaluation.price_for(args.model)     # analyzer_eval/prices.yaml; None -> cost null
    dataset = evaluation.load_dataset()
    result = asyncio.run(evaluation.evaluate(dataset, responder, runs=args.runs,
                                             model=args.model if args.responder == "live" else "oracle",
                                             price=price))
    result["responder"] = args.responder
    result["contract"] = ai_config.contract(settings) if args.responder == "live" else None

    m = result["metrics"]
    print(f"dataset {result['dataset']['version']} sha256 {dataset.sha256}")
    print(f"model {result['model']}  prompt {result['prompt_version']}  schema {result['schema_version']}")
    for kind in ("risk", "obligation"):
        o = m["overall"][kind]
        print(f"{kind:11} precision {o['precision']}  recall {o['recall']}  "
              f"({o['matched']} matched / {o['predicted']} predicted / {o['gold']} gold)")
        for doc_type, block in m["by_type"].items():
            print(f"  {doc_type:10} precision {block[kind]['precision']}  recall {block[kind]['recall']}")
    print(f"evidence validity {m['evidence_validity']}  leakage {m['leakage']}  injection {m['injection']}")
    print(f"failures {m['failures']}  dropped {m['dropped']}")
    print(f"latency {m['latency_ms']}  tokens {m['tokens']}  cost_usd {m['estimated_cost_usd']}  "
          f"consistency {m['consistency']}")
    print(f"gates {m['gates']}")

    if args.responder == "live" or args.write:
        RESULTS.mkdir(parents=True, exist_ok=True)
        slug = (result["model"] or "oracle").replace("/", "_")
        path = RESULTS / f"{date.today().isoformat()}_{slug}_{dataset.sha256[:12]}.json"
        path.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        print(f"wrote {path}")
    return 0 if all(m["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
