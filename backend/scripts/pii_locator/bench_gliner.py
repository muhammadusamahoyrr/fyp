"""DEVELOPMENT benchmark of the PII locator (gliner_multi-v2.1) on pii-eval-1.

    venv/Scripts/python.exe scripts/pii_locator/bench_gliner.py <ML>

pii-eval-1 is a DEVELOPMENT set (its failed 194-leak baseline stays kept in
pii_detection_record.yaml). This is not a gate and selects nothing.

1. Export the PLAIN texts (marks stripped -- the locator never sees labels).
2. Run the locator OFFLINE in the isolated environment (gliner_locate.py).
3. The locator alone: per-kind recall and character coverage against the
   gold NAME / ADDRESS spans, Urdu-script names apart, look-alike (NOT) hits.
4. The pipeline: masker + locator spans, scored by the frozen harness --
   leaks are measured on the request the fake provider actually captured.
   No live call; no network.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.analyzer import ai_records, pii_mask  # noqa: E402
from app.services.analyzer import pii_evaluation as ev  # noqa: E402

ML = Path(sys.argv[1]).resolve()
VARIANT = sys.argv[2] if len(sys.argv) > 2 else "as_loaded"
ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
CUTS = (0.3, 0.5, 0.7)
VARIANTS = {"person+address": {"person": "personal_name", "address": "address"},
            "person+address+location": {"person": "personal_name", "address": "address", "location": "address"}}


def coverage_of(gold, spans):
    covered = sum(max(0, min(b, gold.end) - max(a, gold.start)) for a, b in spans)
    return min(covered, gold.end - gold.start)


def locator_alone(dataset, located, cut):
    rows = []
    for d in dataset.documents:
        ents = [e for e in located[d.id]["entities"] if e["score"] >= cut]
        person = [(e["start"], e["end"]) for e in ents if e["label"] == "person"]
        place = [(e["start"], e["end"]) for e in ents if e["label"] in ("address", "location")]
        for g in d.spans:
            text = d.text[g.start:g.end]
            if g.kind == "NAME":
                rows.append(("NAME_urdu" if ARABIC.search(text) else "NAME", g.end - g.start, coverage_of(g, person)))
            elif g.kind == "ADDRESS":
                rows.append(("ADDRESS", g.end - g.start, coverage_of(g, place)))
            elif g.kind == "NOT":
                hit = any(a < g.end and g.start < b for a, b in person + place)
                rows.append(("NOT_hit", 1, 1 if hit else 0))
    out = {}
    for kind in ("NAME", "NAME_urdu", "ADDRESS"):
        sel = [r for r in rows if r[0] == kind]
        out[kind] = {"spans": len(sel), "fully_found": sum(c == s for _, s, c in sel),
                     "char_coverage": round(sum(c for *_, c in sel) / max(1, sum(s for _, s, _ in sel)), 4)}
    nots = [r for r in rows if r[0] == "NOT_hit"]
    out["lookalikes_hit"] = {"spans": len(nots), "hit": sum(c for *_, c in nots)}
    return out


def main() -> int:
    dataset = ev.load_dataset("pii-eval-1")
    assert ev.DATASET_ROLES.get("pii-eval-1") == "development"
    inputs = ML / "inputs"
    inputs.mkdir(exist_ok=True)
    texts = [{"id": d.id, "text": d.text} for d in dataset.documents]
    assert not any("[[" in t["text"] for t in texts), "marks must be stripped before the locator sees anything"
    (inputs / "pii-eval-1.texts.json").write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    located_path = ML / "outputs" / f"pii-eval-1.gliner.{VARIANT}.json"
    located_path.parent.mkdir(exist_ok=True)
    subprocess.run([str(ML / "venv-gliner" / "Scripts" / "python.exe"),
                    str(Path(__file__).resolve().parent / "gliner_locate.py"), str(ML),
                    str(inputs / "pii-eval-1.texts.json"), str(located_path), VARIANT], check=True)
    located = json.loads(located_path.read_text(encoding="utf-8"))
    docs = located["documents"]

    from scripts.analyzer_pii_eval import FAKE_PROVIDER, capturing_send  # in-process fake provider only
    for name, value in FAKE_PROVIDER.items():
        setattr(settings, name, value)
    ai_records.POLICY_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ai_policies"
    send = capturing_send()

    ms = sorted(v["ms"] for v in docs.values())
    report = {"date": date.today().isoformat(), "dataset": "pii-eval-1", "role": "development",
              "dataset_sha256": dataset.sha256, "masking_policy_sha256": pii_mask.POLICY_SHA256,
              "model": located["model"], "revision": located["revision"], "tokenizer_variant": VARIANT,
              "cpu": {"load_seconds": located["load_seconds"], "total_seconds": located["total_seconds"],
                      "peak_rss_mb": located["peak_rss_mb"], "doc_ms_median": ms[len(ms) // 2],
                      "doc_ms_p95": ms[int(len(ms) * 0.95) - 1], "doc_ms_max": ms[-1],
                      "chars_total": sum(v["chars"] for v in docs.values()),
                      "chunks_total": sum(v["chunks"] for v in docs.values())},
              "locator_alone": {}, "pipeline": {}}
    for cut in CUTS:
        report["locator_alone"][str(cut)] = locator_alone(dataset, docs, cut)
        for variant, mapping in VARIANTS.items():
            extra = {doc_id: [{"start": e["start"], "end": e["end"], "decision": mapping[e["label"]]}
                              for e in v["entities"] if e["score"] >= cut and e["label"] in mapping]
                     for doc_id, v in docs.items()}
            result = ev.evaluate(dataset, send, extra_by_doc=extra)
            report["pipeline"][f"{variant}@{cut}"] = {m: {k: result[m][k] for k in (
                "sent", "blocked", "sent_rate", "blocked_by_reason", "personal_spans", "character_coverage", "detected_rate", "miss_rate", "leaks",
                "unnecessary_blocks", "false_candidate_rate", "party_consistency", "party_scored_documents", "deadline_preservation",
                "request_hygiene", "by_kind")} for m in ("auto", "manual")}
    out = ev.ROOT / "results" / f"{date.today().isoformat()}_pii-eval-1_DEV_gliner_multi-v2.1_{VARIANT}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"cpu": report["cpu"], "locator_alone": report["locator_alone"]}, indent=1))
    for key, val in report["pipeline"].items():
        a = val["auto"]
        print(f"{key:32s} auto: sent={a['sent']} blocked={a['blocked']} coverage={a['character_coverage']} "
              f"detected={a['detected_rate']} leaks={a['leaks']} names_leaked={a['by_kind']['NAME']['leaked']} "
              f"party={a['party_consistency']} deadlines={a['deadline_preservation']} | manual leaks={val['manual']['leaks']}")
    print("results:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
