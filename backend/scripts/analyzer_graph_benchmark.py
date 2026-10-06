"""Private benchmark: definitions / cross-reference graph on a local DOCX folder.

The folder stays OUTSIDE the repository (copyright unclear); this prints
numbers only, never document text. Byte-identical duplicates are removed by
SHA-256 first. Each file goes through the structured extractor, the
segmentation and doc_graph.build, exactly as the stage runs them.

Reported: definitions by kind and form, ambiguous definitions, term uses by
status, references by kind and status, schedules located, possible undefined
terms, the slowest file, and anchor soundness: every row's span lies inside
the sentence and clause it names, and every target id exists.

Read-only. Usage:
    python scripts/analyzer_graph_benchmark.py --dir <folder outside the repository>
Exit code 1 if any anchor or target is unsound.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.docx_structure import extract_docx_structured  # noqa: E402
from app.services.analyzer import doc_graph, segmentation as seg  # noqa: E402


def unsound_rows(clauses, sentences, blocks, rows) -> int:
    by_sentence = {s.sentence_id: s for s in sentences}
    by_clause = {c.clause_id: c for c in clauses}
    block_ids = {b["block_id"] for b in blocks or []}
    definitions = {r["definition_id"] for r in rows if r["type"] == doc_graph.ROW_DEFINITION}
    bad = 0

    def anchored(a) -> bool:
        s = by_sentence.get(a["sentence_id"])
        c = by_clause.get(a["clause_id"])
        return (s is not None and c is not None and s.clause_id == c.clause_id
                and s.start <= a["start"] < a["end"] <= s.end
                and (a["block_id"] is None or a["block_id"] in block_ids))

    for r in rows:
        anchors = r.get("occurrences") or [r]
        ok = all(anchored(a) for a in anchors)
        for t in r.get("targets", []):
            if t["kind"] == "definition":
                ok &= t["definition_id"] in definitions
            else:
                ok &= t["clause_id"] in by_clause and (t["sentence_id"] in by_sentence)
        bad += not ok
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", required=True, type=Path)
    args = parser.parse_args()

    unique = {}
    for path in sorted(args.dir.rglob("*.docx")):
        if path.name.startswith("~$"):
            continue
        unique.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), path)

    totals, unsound, slowest = Counter(), 0, 0.0
    for path in unique.values():
        structured = extract_docx_structured(path)
        if structured.outcome != "succeeded" or not structured.text:
            continue
        text, blocks = structured.text, structured.blocks
        clauses, sentences = seg.segment(text, [], blocks)
        began = time.perf_counter()
        rows, summary = doc_graph.build(text, clauses, sentences, blocks, [])
        slowest = max(slowest, time.perf_counter() - began)
        totals["files"] += 1
        totals["files with any definition"] += bool(summary["definitions"])
        totals["files with any reference"] += bool(sum(summary["references"].values()))
        totals["ambiguous definitions"] += summary["ambiguous_definitions"]
        totals["schedules located"] += summary["schedules_located"]
        totals["empty form fields"] += seg.summary(clauses, sentences)["empty_form_fields"]
        for r in rows:
            if r["type"] == doc_graph.ROW_DEFINITION:
                totals[f"definition kind:{r['kind']}"] += 1
                totals[f"definition form:{r['form']}"] += 1
            elif r["type"] == doc_graph.ROW_TERM_USE:
                totals[f"term use:{r['status']}"] += 1
            elif r["type"] == doc_graph.ROW_REFERENCE:
                totals[f"reference {r['ref_kind']}:{r['status']}"] += 1
            else:
                totals["possible undefined terms"] += 1
        unsound += unsound_rows(clauses, sentences, blocks, rows)

    print(f"unique docx files: {len(unique)}")
    for k in sorted(totals):
        print(f"{k:44}{totals[k]:>8}")
    print(f"slowest graph build (s): {slowest:.3f}")
    print(f"rows with unsound anchors or targets: {unsound}")
    return 1 if unsound else 0


if __name__ == "__main__":
    raise SystemExit(main())
