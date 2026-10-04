"""Score PII masking DETECTION (`pii-eval.1`, analyzer_eval/pii/PII_DETECTION_RUBRIC.md).

    python scripts/analyzer_pii_eval.py --dataset pii-eval-1 --freeze        # BEFORE any scoring
    python scripts/analyzer_pii_eval.py --dataset pii-eval-1 --write-record  # the single scored run

NEVER a live call: every request goes through the real provider client
(ai_client.complete) with a FAKE transport that only captures the HTTP body,
under in-process dummy settings (no real key). Scoring is refused unless the
set's FROZEN.txt names this exact dataset hash and rubric hash. A kept result
is never overwritten.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import yaml  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.analyzer import ai_client, pii_mask  # noqa: E402
from app.services.analyzer import pii_evaluation as ev  # noqa: E402

#: In-process only: makes the AI layer "ready" so the real client builds and
#: posts the request -- to a fake transport. The key is not a real key.
FAKE_PROVIDER = {"analyzer_ai": True, "analyzer_ai_provider": "groq", "analyzer_ai_model": "openai/gpt-oss-120b",
                 "analyzer_ai_model_allowlist": "openai/gpt-oss-120b", "analyzer_ai_policy_id": "AAI-AI-TEST-001",
                 "analyzer_ai_zdr_status": "verified", "analyzer_ai_zdr_verified_on": "2026-09-30",
                 "analyzer_ai_zdr_evidence": "fake provider for pii-eval (no network)",
                 "analyzer_ai_synthetic_only": True, "groq_api_key": "fake-key-not-real"}


def _rubric_sha() -> str:
    return hashlib.sha256(ev.RUBRIC_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def capturing_send():
    """send(messages) -> the user content of the request the provider RECEIVED."""
    def send(messages):
        captured = {}

        async def respond(request):
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"model": captured["body"]["model"], "usage": {},
                                             "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})

        async def call():
            await ai_client.complete(messages, transport=httpx.MockTransport(respond))

        asyncio.run(call())
        return captured["body"]["messages"][1]["content"]
    return send


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default="pii-eval-1")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--write-record", action="store_true")
    args = parser.parse_args()

    dataset = ev.load_dataset(args.dataset)
    cov = ev.coverage(dataset)
    frozen_path = ev.ROOT / args.dataset / "FROZEN.txt"
    if args.freeze:
        if frozen_path.exists():
            print("refused: already frozen; a frozen set is never re-frozen", file=sys.stderr)
            return 2
        if not cov["met"]:
            print(f"refused: coverage not met {cov}", file=sys.stderr)
            return 2
        lines = ["# pii-eval-1 freeze manifest -- written BEFORE the first scored run.",
                 "# Scored once; the masking is not tuned against this set.",
                 f"frozen_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
                 f"dataset_sha256: {dataset.sha256}", f"documents: {len(dataset.documents)}",
                 f"personal_spans: {cov['personal_spans']}", f"rubric_sha256: {_rubric_sha()}",
                 f"eval_version: {ev.EVAL_VERSION}", f"masking_version: {pii_mask.MASKING_VERSION}",
                 f"policy_sha256_at_freeze: {pii_mask.POLICY_SHA256}",
                 "author: independent fresh session, given only PII_DETECTION_RUBRIC.md", "files:"]
        lines += [f"  {p.name}: {hashlib.sha256(p.read_bytes()).hexdigest()}"
                  for p in sorted((ev.ROOT / args.dataset).glob("*.yaml"))]
        frozen_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print("\n".join(lines))
        return 0

    manifest = yaml.safe_load(frozen_path.read_text(encoding="utf-8")) if frozen_path.exists() else None
    if not manifest or manifest.get("dataset_sha256") != dataset.sha256 or manifest.get("rubric_sha256") != _rubric_sha():
        print("refused: the set must be frozen (same dataset and rubric hash) before scoring", file=sys.stderr)
        return 2

    for name, value in FAKE_PROVIDER.items():
        setattr(settings, name, value)
    # The test-only checklist record (tests/fixtures/ai_policies): an id that can
    # never be mistaken for a real verification, exactly as the test suite uses.
    from app.services.analyzer import ai_records
    ai_records.POLICY_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ai_policies"
    result = ev.evaluate(dataset, capturing_send())
    result["frozen_before_run"] = True
    for mode in ("auto", "manual"):
        s = result[mode]
        print(f"{mode:6s} docs={s['documents']} sent={s['sent']} blocked={s['blocked']} spans={s['personal_spans']} "
              f"coverage={s['character_coverage']} detected={s['detected_rate']} miss={s['miss_rate']} "
              f"leaks={s['leaks']} unnecessary_blocks={s['unnecessary_blocks']} "
              f"false_cand={s['false_candidate_rate']} party={s['party_consistency']} "
              f"deadlines={s['deadline_preservation']} hygiene={s['request_hygiene']}")
    print("gate:", result["gate"]["status"], {k: v for k, v in result["gate"]["checks"].items() if not v})

    results_dir = ev.ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    out = results_dir / f"{date.today().isoformat()}_{args.dataset}_{dataset.sha256[:12]}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("results:", out)
    if args.write_record:
        if ev.RECORD_PATH.exists():
            print("refused: a kept detection record is never overwritten", file=sys.stderr)
            return 2
        record = {k: result[k] for k in ("eval_version", "dataset", "dataset_sha256", "masking_version",
                                         "policy_sha256", "rubric_sha256", "coverage", "auto", "manual", "gate",
                                         "frozen_before_run")}
        record["label_review"] = "developer_only"
        record["approval"] = ("Detection only, on synthetic developer-labelled documents. Not a real-document "
                              "or model-quality approval.")
        record["created"] = date.today().isoformat()
        ev.RECORD_PATH.write_text("# Kept PII detection result (pii-eval.1). Never overwritten.\n"
                                  + yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000),
                                  encoding="utf-8", newline="\n")
        print("record:", ev.RECORD_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
