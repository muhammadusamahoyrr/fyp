"""Private benchmark: legacy vs structured DOCX extraction on a local folder.

The folder (e.g. downloaded practitioner templates) stays OUTSIDE the
repository -- its copyright is unclear -- and this script never copies,
uploads or prints document text. It reports numbers only:

  * files read, and byte-identical duplicates removed by SHA-256 (a
    duplicate in a benchmark makes it look better than it is);
  * clauses found by the analyzer's segmentation, legacy text vs structured;
  * blocks with a Word numbering label, unresolved numbering, limitations;
  * the legacy contract: for a document with no Word numbering, the
    structured text must equal the legacy text, or differ ONLY by text the
    legacy extractor dropped (insertions) -- never by a change or a loss.

Read-only. Usage:
    python scripts/docx_structure_benchmark.py --dir <folder outside the repository>
Exit code 1 if any unnumbered document breaks the legacy contract.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.docx_structure import extract_docx_structured  # noqa: E402
from app.ai.extraction import extract_docx  # noqa: E402
from app.services.analyzer.segmentation import split_clauses  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", required=True, type=Path)
    args = parser.parse_args()

    files = sorted(p for p in args.dir.rglob("*.docx") if not p.name.startswith("~$"))
    unique, duplicates = {}, 0
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in unique:
            duplicates += 1
        else:
            unique[digest] = path

    totals, limitations = Counter(), Counter()
    contract = {"identical": 0, "superset": 0, "broken": 0}
    for path in unique.values():
        legacy, structured = extract_docx(path), extract_docx_structured(path)
        if structured.outcome != "succeeded":
            totals["structured_failed"] += 1
            continue
        totals["files"] += 1
        totals["clauses_legacy"] += len(split_clauses(legacy.text)) if legacy.text else 0
        totals["clauses_structured"] += len(split_clauses(structured.text)) if structured.text else 0
        totals["labelled_blocks"] += sum(1 for b in structured.blocks if (b["list"] or {}).get("label"))
        totals["unresolved_blocks"] += sum(1 for b in structured.blocks
                                           if b["list"] and not b["list"]["resolved"])
        limitations.update(structured.limitations)
        if any(b["list"] for b in structured.blocks):
            continue
        if legacy.text == structured.text:
            contract["identical"] += 1
            continue
        ops = {op[0] for op in difflib.SequenceMatcher(
            None, legacy.text, structured.text, autojunk=False).get_opcodes()}
        if ops <= {"equal", "insert"}:
            contract["superset"] += 1
        else:
            contract["broken"] += 1
            print(f"LEGACY CONTRACT BROKEN: {path.name}")

    print(f"docx files: {len(files)}  unique: {len(unique)}  duplicates removed: {duplicates}")
    for key in ("files", "structured_failed", "clauses_legacy", "clauses_structured",
                "labelled_blocks", "unresolved_blocks"):
        print(f"{key:20} {totals[key]}")
    print("unnumbered documents vs legacy:", contract)
    print("limitations:", dict(limitations.most_common()))
    return 1 if contract["broken"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
