"""Score PII masking DETECTION (pii-eval.1 rubric 1 / pii-eval.2 rubric 2).

    python scripts/analyzer_pii_eval.py --dataset pii-eval-1 --freeze        # BEFORE any scoring
    python scripts/analyzer_pii_eval.py --dataset pii-eval-1 --write-record  # the single scored run

Two pipelines, fixed per set (`pii_evaluation.pipeline_for`):
  * `production-rules-only` (pii-eval-7 on): EXACTLY what the app runs -- no
    locator, decisions through the real API validation, the request built by
    the stage's own function (`pii_pipeline.compose`). The freeze pins the
    masking policy, the production request code and the evaluated settings;
  * rules + local locator (pii-eval-2..6, owner choice 2026-10-04): the
    locator (`LOCATOR` below) run OFFLINE (`--locator-home <ML>`). This is
    NOT the production pipeline; those records stay labelled as they are.
Scoring refuses if anything pinned changed since the freeze.

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
from app.services.analyzer import ai_client, pii_confirmation, pii_mask, pii_pipeline  # noqa: E402
from app.services.analyzer import pii_evaluation as ev  # noqa: E402

#: The locator setup a rubric-2 set is scored with -- pinned by the freeze.
LOCATOR = {"model": "urchade/gliner_multi-v2.1", "revision": "443d26d654e0324125a96bebd8e796c14ff2efe6",
           "tokenizer_variant": "as_loaded", "cut_off": 0.3,
           "labels": {"person": "personal_name", "address": "address", "location": "address"}}
LOCATOR_MANIFEST = ev.ROOT / "locator" / "gliner_multi-v2.1.manifest.json"


#: The production code that builds the request besides the masking policy
#: (pii_mask + pii_layers, pinned by POLICY_SHA256).
PRODUCTION_CODE = ("app/services/analyzer/pii_pipeline.py", "app/services/analyzer/pii_confirmation.py",
                   "app/services/analyzer/ai_report.py", "app/services/analyzer/segmentation.py",
                   "app/services/analyzer/injection.py")
#: The settings the production pipeline is evaluated under (pinned by the freeze).
PRODUCTION_SETTINGS = {"analyzer_pii_review_required": True, "analyzer_ai_synthetic_only": True}


def production_code_sha256() -> str:
    backend = Path(__file__).resolve().parents[1]
    blob = b""
    for rel in PRODUCTION_CODE:
        blob += (backend / rel).read_bytes().replace(b"\r\n", b"\n") + b"\n--\n"
    return hashlib.sha256(blob).hexdigest()


def _pipeline(name: str) -> dict | None:
    if ev.pipeline_for(name) == pii_pipeline.PIPELINE:
        return {"pipeline": pii_pipeline.PIPELINE, "rules": pii_mask.MASKING_VERSION,
                "review": pii_confirmation.REVIEW_VERSION, "locator": None}
    return {"rules": pii_mask.MASKING_VERSION, "locator": LOCATOR} if ev.rubric_path(name) != ev.RUBRIC_PATH else None


def _production(name: str) -> bool:
    return ev.pipeline_for(name) == pii_pipeline.PIPELINE


def harness_sha256() -> str:
    """SHA-256 over the code that SCORES a set (the evaluation harness, this
    script and the locator runner). Pinned by the freeze, so a set frozen on
    uncommitted code is still scored by exactly the code it was frozen with."""
    here = Path(__file__).resolve()
    blob = b""
    for source in (Path(ev.__file__), here, here.parent / "pii_locator" / "gliner_locate.py"):
        blob += source.read_bytes().replace(b"\r\n", b"\n") + b"\n--\n"
    return hashlib.sha256(blob).hexdigest()


#: Every file that decides what is masked or how a set is scored. A gate is
#: frozen only when all of them are COMMITTED and unchanged, so the run can be
#: reproduced from the recorded commit (pii-eval-5's freeze could not be).
PIPELINE_FILES = ("app/services/analyzer/pii_mask.py", "app/services/analyzer/pii_layers.py",
                  "app/services/analyzer/pii_evaluation.py", "scripts/analyzer_pii_eval.py",
                  "scripts/pii_locator/gliner_locate.py", "analyzer_eval/pii/locator/gliner_multi-v2.1.manifest.json",
                  *PRODUCTION_CODE)


def _source_state() -> tuple[str, list[str]]:
    """(HEAD commit, pipeline files with uncommitted changes)."""
    import subprocess
    backend = Path(__file__).resolve().parents[1]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=backend, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *PIPELINE_FILES], cwd=backend,
                           capture_output=True, text=True).stdout.split("\n")
    return head, [line for line in dirty if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _file_hashes(manifest: dict) -> dict:
    return {f"{r['repo']}/{f['name']}": f["sha256"] for r in manifest["repos"] for f in r["files"]}


def _locate(dataset, home: Path) -> dict[str, list[dict]]:
    """Run the pinned locator OFFLINE on the plain texts; its spans are detections."""
    import subprocess
    local = json.loads((home / "gliner_multi-v2.1.manifest.json").read_text(encoding="utf-8"))
    if _file_hashes(local) != _file_hashes(json.loads(LOCATOR_MANIFEST.read_text(encoding="utf-8"))):
        raise SystemExit("refused: the local locator files do not match the committed manifest")
    work = home / "gate"
    work.mkdir(exist_ok=True)
    texts = work / f"{dataset.name}.texts.json"
    texts.write_text(json.dumps([{"id": d.id, "text": d.text} for d in dataset.documents], ensure_ascii=False),
                     encoding="utf-8")
    out = work / f"{dataset.name}.located.json"
    try:
        subprocess.run([str(home / "venv-gliner" / "Scripts" / "python.exe"),
                        str(Path(__file__).resolve().parent / "pii_locator" / "gliner_locate.py"), str(home),
                        str(texts), str(out), LOCATOR["tokenizer_variant"]], check=True)
    finally:
        texts.unlink()                               # the plain texts are not kept outside the repository
    located = json.loads(out.read_text(encoding="utf-8"))
    if (located["model"], located["revision"], located["tokenizer_variant"]) != \
            (LOCATOR["model"], LOCATOR["revision"], LOCATOR["tokenizer_variant"]):
        raise SystemExit("refused: the locator output is not from the pinned setup")
    return {doc_id: [{"start": e["start"], "end": e["end"], "decision": LOCATOR["labels"][e["label"]]}
                     for e in v["entities"] if e["score"] >= LOCATOR["cut_off"] and e["label"] in LOCATOR["labels"]]
            for doc_id, v in located["documents"].items()}

#: In-process only: makes the AI layer "ready" so the real client builds and
#: posts the request -- to a fake transport. The key is not a real key.
FAKE_PROVIDER = {"analyzer_ai": True, "analyzer_ai_provider": "groq", "analyzer_ai_model": "openai/gpt-oss-120b",
                 "analyzer_ai_model_allowlist": "openai/gpt-oss-120b", "analyzer_ai_policy_id": "AAI-AI-TEST-001",
                 "analyzer_ai_zdr_status": "verified", "analyzer_ai_zdr_verified_on": "2026-09-30",
                 "analyzer_ai_zdr_evidence": "fake provider for pii-eval (no network)",
                 "analyzer_ai_synthetic_only": True, "groq_api_key": "fake-key-not-real"}


def _rubric_sha(name: str) -> str:
    return hashlib.sha256(ev.rubric_path(name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


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
    parser.add_argument("--locator-home", type=Path, help="the isolated locator directory (rubric-2 sets)")
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
        head, dirty = _source_state()
        if _pipeline(dataset.name) is not None and dirty:
            print(f"refused: commit the pipeline files before freezing a gate set: {dirty}", file=sys.stderr)
            return 2
        lines = [f"# {args.dataset} freeze manifest -- written BEFORE the first scored run.",
                 "# Scored once; the masking is not tuned against this set.",
                 f"frozen_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
                 f"dataset_sha256: {dataset.sha256}", f"documents: {len(dataset.documents)}",
                 f"personal_spans: {cov['personal_spans']}", f"rubric_sha256: {_rubric_sha(dataset.name)}",
                 f"eval_version: {ev.EVAL_VERSION}", f"masking_version: {pii_mask.MASKING_VERSION}",
                 f"policy_sha256_at_freeze: {pii_mask.POLICY_SHA256}",
                 f"pipeline_json: '{json.dumps(_pipeline(dataset.name), sort_keys=True)}'",
                 f"harness_sha256: {harness_sha256()}",
                 f"source_commit: {head}",
                 f"locator_manifest_sha256: {_sha(LOCATOR_MANIFEST)}",
                 *([f"production_code_sha256: {production_code_sha256()}",
                    f"settings_json: '{json.dumps(PRODUCTION_SETTINGS, sort_keys=True)}'"]
                   if _production(dataset.name) else []),
                 f"author: independent fresh session, given only {ev.rubric_path(dataset.name).name}", "files:"]
        lines += [f"  {p.name}: {hashlib.sha256(p.read_bytes()).hexdigest()}"
                  for p in sorted((ev.ROOT / args.dataset).glob("*.yaml"))]
        frozen_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print("\n".join(lines))
        return 0

    manifest = yaml.safe_load(frozen_path.read_text(encoding="utf-8")) if frozen_path.exists() else None
    if not manifest or manifest.get("dataset_sha256") != dataset.sha256 or manifest.get("rubric_sha256") != _rubric_sha(dataset.name):
        print("refused: the set must be frozen (same dataset and rubric hash) before scoring", file=sys.stderr)
        return 2
    pipeline = _pipeline(dataset.name)
    extra = None
    if pipeline is not None:
        if manifest.get("pipeline_json") != json.dumps(pipeline, sort_keys=True) \
                or manifest.get("policy_sha256_at_freeze") != pii_mask.POLICY_SHA256 \
                or ("harness_sha256" in manifest and manifest["harness_sha256"] != harness_sha256()):
            print("refused: the pipeline or masking policy changed since the freeze", file=sys.stderr)
            return 2
        if "source_commit" in manifest:
            head, dirty = _source_state()
            if dirty or _sha(LOCATOR_MANIFEST) != manifest.get("locator_manifest_sha256"):
                print(f"refused: pipeline files changed since the freeze: {dirty}", file=sys.stderr)
                return 2
        if _production(dataset.name):
            pinned = (manifest.get("production_code_sha256"), manifest.get("settings_json"))
            if pinned != (production_code_sha256(), json.dumps(PRODUCTION_SETTINGS, sort_keys=True)):
                print("refused: the production request code or settings changed since the freeze", file=sys.stderr)
                return 2
            if args.locator_home:
                print("refused: the production-rules-only pipeline runs no locator", file=sys.stderr)
                return 2
        else:
            if not args.locator_home:
                print("refused: a rubric-2 set is scored with the pinned locator (--locator-home)", file=sys.stderr)
                return 2
            extra = _locate(dataset, args.locator_home.resolve())

    for name, value in FAKE_PROVIDER.items():
        setattr(settings, name, value)
    # The test-only checklist record (tests/fixtures/ai_policies): an id that can
    # never be mistaken for a real verification, exactly as the test suite uses.
    from app.services.analyzer import ai_records
    ai_records.POLICY_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ai_policies"
    for name, value in PRODUCTION_SETTINGS.items() if _production(dataset.name) else ():
        setattr(settings, name, value)
    result = ev.evaluate(dataset, capturing_send(), extra_by_doc=extra, modes=ev.modes_for(dataset.name),
                         pipeline=ev.pipeline_for(dataset.name))
    result["pipeline"] = pipeline
    result["frozen_before_run"] = True
    for mode in ev.modes_for(dataset.name):
        s = result[mode]
        print(f"{mode:6s} docs={s['documents']} sent={s['sent']} blocked={s['blocked']} spans={s['personal_spans']} "
              f"coverage={s['character_coverage']} detected={s['detected_rate']} miss={s['miss_rate']} "
              f"leaks={s['leaks']} unnecessary_blocks={s['unnecessary_blocks']} "
              f"false_cand={s['false_candidate_rate']} party={s['party_consistency']} "
              f"deadlines={s['deadline_preservation']} hygiene={s['request_hygiene']} "
              f"sent_rate={s.get('sent_rate')} party_any={s.get('party_consistency_any_token')} "
              f"address_cov={s.get('address_character_coverage')} by_reason={s.get('blocked_by_reason')}")
    print("gate:", result["gate"]["status"], {k: v for k, v in result["gate"]["checks"].items() if not v})

    results_dir = ev.ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    out = results_dir / f"{date.today().isoformat()}_{args.dataset}_{dataset.sha256[:12]}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("results:", out)
    if args.write_record:
        if ev.DATASET_ROLES.get(args.dataset) == "development":
            print("refused: a development set never writes a gate record", file=sys.stderr)
            return 2
        record_path = ev.record_path(args.dataset)
        if record_path.exists():
            print("refused: a kept detection record is never overwritten", file=sys.stderr)
            return 2
        record = {k: result[k] for k in ("eval_version", "dataset", "dataset_sha256", "masking_version",
                                         "policy_sha256", "rubric_sha256", "coverage", "auto", "manual", "gate",
                                         "frozen_before_run", "pipeline")}
        if "review" in result:
            record["review"] = result["review"]
        record["label_review"] = "developer_only"
        record["approval"] = ("Detection only, on synthetic developer-labelled documents. Not a real-document "
                              "or model-quality approval.")
        record["created"] = date.today().isoformat()
        record_path.write_text(f"# Kept PII detection result ({ev.EVAL_VERSION}, {args.dataset}). Never overwritten.\n"
                                  + yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000),
                                  encoding="utf-8", newline="\n")
        print("record:", record_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
