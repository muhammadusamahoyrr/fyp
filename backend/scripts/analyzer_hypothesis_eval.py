"""Run the ai-hypothesis.1 evaluation (ANALYZER_HYPOTHESES_PLAN.md §7).

    python scripts/analyzer_hypothesis_eval.py                      # scanner-only on calib-1, offline
    python scripts/analyzer_hypothesis_eval.py --write-record       # ...and freeze the record
    AAI_LIVE_TESTS=1 python scripts/analyzer_hypothesis_eval.py --ai live --model openai/gpt-oss-120b

Scanner-only runs never touch the network. A live AI run is opt-in
(AAI_LIVE_TESTS=1), needs the analyzer AI layer READY (pinned, allowlisted
model; verified ZDR; synthetic-only), and calls one model with no fallback.
Results go to analyzer_eval/hypotheses/results/. The holdout stays sealed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from app.services.analyzer.hypotheses import evaluation as ev  # noqa: E402

RESULTS = ev.ROOT / "results"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default="calib-1")
    parser.add_argument("--ai", choices=("none", "live"), default="none")
    parser.add_argument("--model", default=None)
    parser.add_argument("--write-record", action="store_true")
    args = parser.parse_args()

    responder, ai_meta = None, None
    if args.ai == "live":
        from app.core.config import settings
        from app.services.analyzer import ai_config
        from app.services.analyzer import evaluation as v1_eval
        if os.environ.get("AAI_LIVE_TESTS") != "1":
            print("refused: a live run needs AAI_LIVE_TESTS=1", file=sys.stderr)
            return 2
        if not settings.analyzer_ai or ai_config.problems(settings):
            print("refused: the analyzer AI layer is not ready (pin, allowlist, ZDR, policy)", file=sys.stderr)
            return 2
        model = args.model or settings.analyzer_ai_model
        responder = v1_eval.live_responder(model)
        ai_meta = {"evaluated": True, "provider": "groq", "model": model}

    dataset = ev.load_dataset(args.dataset)
    result = asyncio.run(ev.evaluate(dataset, responder=responder))
    result["v1_regression"] = ev.v1_regression()

    RESULTS.mkdir(parents=True, exist_ok=True)
    tag = (ai_meta or {}).get("model", "scanner-only").replace("/", "_")
    out = RESULTS / f"{date.today().isoformat()}_{args.dataset}_{tag}_{dataset.sha256[:12]}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    s = result["scanner_only"]
    print(f"{args.dataset}: {result['documents']} documents  scanner-only  precision={s['attention_precision']} "
          f"recall={s['attention_recall']}  evidence_validity={s['evidence_validity']}  "
          f"status={result['gate']['status']}")
    for w in result["weak_questions"]:
        print(f"  weak: {w['question_id']:26s} fails={','.join(w['fails'])} precision={w['precision']} "
              f"recall={w['recall']} (flagged {w['flagged']}, gold {w['gold_attention']})")
    print(f"results: {out}")

    if args.write_record:
        if args.dataset != "calib-1":
            print("refused: the record is written from calib-1 only (the holdout stays sealed)", file=sys.stderr)
            return 2
        if ai_meta:
            ai_meta = {**ai_meta, **result["ai_review"],
                       "scanner_plus_ai_advisory": result["scanner_plus_ai_advisory"]}
        record = ev.build_record(result, ai=ai_meta)
        record["v1_regression"] = result["v1_regression"]
        ev.check_record(record)
        header = ("# Frozen evaluation record for the ai-hypothesis.1 engine (ANALYZER_HYPOTHESES_PLAN.md §7).\n"
                  "# Written by scripts/analyzer_hypothesis_eval.py --write-record; changes only by a reviewed\n"
                  "# commit. Developer-labelled: the most it can say is engineering_passed. It is NOT a legal or\n"
                  "# production approval. The ai-report.1 record (ai_evaluation_record.yaml) is separate and\n"
                  "# unchanged.\n")
        ev.RECORD_PATH.write_text(header + yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000),
                                  encoding="utf-8", newline="\n")
        print(f"record: {ev.RECORD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
