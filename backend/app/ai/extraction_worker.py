"""Child-process entry point for evidence extraction. JSON on stdin, JSON on stdout.

Imports ONLY `app.ai.extraction` and the standard library. That is a hard
constraint, not a style preference: `app.ai.tools` pulls in langchain and costs
~2.5 s to import, and `app.core.config` builds settings and database clients. A
worker that touched either would add seconds to every conversion and open
connections a short-lived extraction process has no business holding.

`app/__init__.py` and `app/ai/__init__.py` are both empty, which is what makes
`python -m app.ai.extraction_worker` cheap. If either ever gains an import, this
worker gets slower for reasons nobody will connect to this file.
"""
from __future__ import annotations

import json
import sys
import time


def _run(job: dict) -> dict:
    from app.ai.extraction import extract_file

    results = []
    deadline = job.get("deadline_monotonic")

    for item in job.get("files") or []:
        file_id = str(item.get("file_id") or "")

        # Checked per file so one slow document cannot consume the whole batch's
        # budget and leave later files looking as though they were read and
        # empty. They are reported as not attempted, which is a different thing.
        if deadline is not None and time.monotonic() >= deadline:
            results.append({
                "file_id": file_id,
                "result": {"outcome": "failed", "completeness": "none",
                           "error_code": "timeout", "limitations": [],
                           "pages_total": None, "pages_attempted": 0,
                           "pages_with_text": 0, "pages_failed": 0,
                           "pages_skipped": 0, "processing_coverage": None,
                           "text_yielding_page_ratio": None,
                           "extractor_version": None, "config_version": None,
                           "pages": []},
                "text": "",
            })
            continue

        started = time.perf_counter()
        extracted = extract_file(str(item.get("path") or ""))
        payload = extracted.as_dict()
        payload["duration_seconds"] = time.perf_counter() - started
        results.append({
            "file_id": file_id,
            "result": payload,
            # Text travels separately from the report so the report can be
            # logged, stored and shown without carrying document content.
            "text": extracted.text,
        })

    return {"ok": True, "results": results}


def main() -> int:
    try:
        job = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"ok": False, "error_code": "internal_error"}))
        return 0

    # Absolute deadline, computed in the child's own clock domain: the parent's
    # monotonic clock is not comparable across processes.
    budget = job.get("budget_seconds")
    if budget:
        job["deadline_monotonic"] = time.monotonic() + float(budget)

    try:
        print(json.dumps(_run(job)))
    except Exception:
        print(json.dumps({"ok": False, "error_code": "internal_error"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
