"""Child-process entry point for evidence extraction. JSON on stdin, JSON on stdout.

Imports ONLY `app.ai.extraction`, `app.ai.ocr`, `app.ai.ocr_routing` and the
standard library. That is a hard constraint, not a style preference:
`app.ai.tools` pulls in langchain and costs ~2.5 s to import, and
`app.core.config` builds settings and database clients. A worker that touched
either would add seconds to every conversion and open connections a short-lived
extraction process has no business holding. The two OCR modules import stdlib
only (Pillow is imported lazily, inside the one function that needs it), so they
cost nothing when OCR is off.

WHY OCR RUNS HERE AND NOT IN THE SERVICE

This process is already the isolation boundary: the parent gives it a per-file
and a whole-batch deadline and kills its entire process TREE on timeout. The
OCR engine is spawned from here, so it is a grandchild of the API process and
is covered by that same tree kill. Running OCR anywhere else would mean either
a second queue with its own timeout story, or an engine the existing cleanup
cannot reach.

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

    ocr_request = job.get("ocr") or {}

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
        entry = {
            "file_id": file_id,
            "result": payload,
            # Text travels separately from the report so the report can be
            # logged, stored and shown without carrying document content.
            "text": extracted.text,
        }
        if ocr_request.get("enabled"):
            entry["ocr"] = _ocr(item, extracted, ocr_request, deadline)
        results.append(entry)

    return {"ok": True, "results": results}


def _ocr(item: dict, extracted, request: dict, deadline) -> dict:
    """Read the pages that yielded nothing. Never raises.

    The routing decision is made from what extraction ALREADY found, so a page
    with a text layer is never re-read, and a legacy Urdu page is refused
    outright rather than handed to an English engine.
    """
    from app.ai import ocr as O
    from app.ai import ocr_routing

    content_type = str(item.get("content_type") or "")
    path = str(item.get("path") or "")

    if content_type.lower() in O.SUPPORTED_IMAGE_TYPES:
        plan = ocr_routing.plan_for_image(content_type)
    else:
        plan = ocr_routing.plan_for_result(extracted)

    out = {"plan": plan.as_dict(), "pages": [], "texts": {}}
    if plan.document_refusal or not plan.needs_ocr:
        return out

    engine = O.detect_engine()
    if engine is None:
        out["pages"].append({"page_number": 0,
                             "status": O.OCR_ENGINE_UNAVAILABLE,
                             "error_code": O.OCR_ENGINE_UNAVAILABLE})
        return out

    for number in plan.pages:
        # The batch deadline is checked between pages as well as inside the
        # engine call: twenty pages at twenty seconds each would otherwise
        # outlive the budget the parent granted the whole file.
        if deadline is not None and time.monotonic() >= deadline:
            out["pages"].append({"page_number": number,
                                 "status": O.OCR_TIMEOUT,
                                 "error_code": O.OCR_TIMEOUT})
            continue

        remaining = O.PER_PAGE_TIMEOUT_SECONDS
        if deadline is not None:
            remaining = min(remaining, max(0.1, deadline - time.monotonic()))

        data = (O.read_source_bytes(path)
                if content_type.lower() in O.SUPPORTED_IMAGE_TYPES
                else O.page_image_bytes(path, number))
        page = O.ocr_image_bytes(data or b"", page_number=number,
                                 engine=engine, timeout=remaining)
        out["pages"].append(page.as_dict())
        if page.text:
            out["texts"][str(number)] = page.text
    return out


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
