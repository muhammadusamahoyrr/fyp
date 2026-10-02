"""Private benchmark: analyzer segmentation on a local folder of DOCX files.

The folder stays OUTSIDE the repository (copyright unclear); this prints
numbers only, never document text. Byte-identical duplicates are removed by
SHA-256 first. Three readings of each file are compared:

  legacy      extract_docx() text, segmented as text only (the old analyzer path)
  text-only   structured canonical text, segmented without its blocks
  structured  structured canonical text + its blocks (Word headings, labels)

Reported: clauses, clauses by source, heading units, form-field units, files
that fell back to paragraphs (no structure found), and offset soundness.

Read-only. Usage:
    python scripts/analyzer_segmentation_benchmark.py --dir <folder outside the repository>
Exit code 1 if any unit's offsets fall outside its clause or overlap.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.docx_structure import extract_docx_structured  # noqa: E402
from app.ai.extraction import extract_docx  # noqa: E402
from app.services.analyzer import segmentation as seg  # noqa: E402


def sound(text, clauses, sentences) -> bool:
    by = {c.clause_id: c for c in clauses}
    last = -1
    for s in sentences:
        c = by[s.clause_id]
        if not (c.start <= s.start < s.end <= c.end) or s.start <= last:
            return False
        last = s.end - 1
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", required=True, type=Path)
    args = parser.parse_args()

    unique = {}
    for path in sorted(args.dir.rglob("*.docx")):
        if path.name.startswith("~$"):
            continue
        unique.setdefault(hashlib.sha256(path.read_bytes()).hexdigest(), path)

    totals = {k: Counter() for k in ("legacy", "text-only", "structured")}
    unsound = 0
    for path in unique.values():
        structured = extract_docx_structured(path)
        if structured.outcome != "succeeded" or not structured.text:
            continue
        legacy_text = extract_docx(path).text
        readings = {"legacy": (legacy_text, None), "text-only": (structured.text, None),
                    "structured": (structured.text, structured.blocks)}
        for name, (text, blocks) in readings.items():
            if not text:
                continue
            clauses, sentences = seg.segment(text, [], blocks)
            report = seg.summary(clauses, sentences)
            t = totals[name]
            t["files"] += 1
            t["clauses"] += len(clauses)
            t.update({f"source:{k}": v for k, v in report["clause_sources"].items()})
            t["heading units"] += report["headings"]
            t["form-field units"] += report["form_fields"]
            t["files with no structure"] += bool(report["limitations"])
            if name == "structured" and not sound(text, clauses, sentences):
                unsound += 1

    print(f"unique docx files: {len(unique)}")
    keys = sorted({k for t in totals.values() for k in t})
    print(f"{'':28}" + "".join(f"{n:>12}" for n in totals))
    for k in keys:
        print(f"{k:28}" + "".join(f"{totals[n][k]:>12}" for n in totals))
    print(f"structured files with unsound offsets: {unsound}")
    return 1 if unsound else 0


if __name__ == "__main__":
    raise SystemExit(main())
