"""Generate the omitted-sections map from the statute source texts.

    python scripts/build_omission_map.py            # write the map
    python scripts/build_omission_map.py --dry-run  # report only

Reads knowledge_base/processed/text/**/*.txt, extracts each statute's own
declarations of repeal, and writes app/ai/data/statute_omissions.json keyed by
the canonical statute name the corpus index uses.

The file -> statute link comes from Chroma's own `source_file` metadata rather
than a hand-written table, so a re-ingest cannot silently desynchronise the two.

READ THE OUTPUT AS A LOWER BOUND. This recognises range and single-section
declarations, including the OCR corruption "Repeated" for "Repealed". It does
NOT recognise the footnote style the PPC uses ("The following was omitted by
A.O. 1961"), which annotates sub-sections rather than whole sections. A statute
reporting zero has not been shown to be free of repealed content.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.ai.statute_omissions import (  # noqa: E402
    held_back,
    parse_omissions,
    pending_verification,
)

ROOT = Path(__file__).resolve().parents[1]
TEXTS = ROOT / "knowledge_base" / "processed" / "text"
OUT = ROOT / "app" / "ai" / "data" / "statute_omissions.json"


def _statute_by_source_stem() -> dict[str, str]:
    """{source-file stem: canonical statute name}, straight from the corpus."""
    from app.db.chroma import connect_chroma, get_chroma
    from app.ai.corpus_index import _COLLECTIONS

    connect_chroma()
    client = get_chroma()
    mapping: dict[str, str] = {}
    for name in _COLLECTIONS:
        try:
            col = client.get_collection(name)
        except Exception:
            continue
        for md in col.get(include=["metadatas"])["metadatas"] or []:
            statute = (md.get("statute") or "").strip()
            src = (md.get("source_file") or "").strip()
            if statute and src:
                mapping[Path(src).stem.lower()] = statute
    return mapping


def main(dry_run: bool) -> None:
    by_stem = _statute_by_source_stem()
    print(f"source files known to the corpus : {len(by_stem)}")

    found: dict[str, set[int]] = defaultdict(set)
    unmapped: list[str] = []
    for f in sorted(TEXTS.rglob("*.txt")):
        statute = by_stem.get(f.stem.lower())
        omitted = parse_omissions(f.read_text(encoding="utf-8", errors="replace"))
        if not statute:
            if omitted:
                unmapped.append(f"{f.name} ({len(omitted)} omissions)")
            continue
        if omitted:
            found[statute] |= omitted

    # Applied HERE rather than by hand-editing the JSON, so re-running this
    # script cannot silently restore sections that were pulled on purpose.
    withheld: dict[str, list[int]] = {}
    for statute in list(found):
        held = held_back(statute)
        if held:
            hit = sorted(found[statute] & held)
            if hit:
                withheld[statute] = hit
                found[statute] -= held

    print(f"statutes with declared omissions : {len(found)}")
    if withheld:
        print()
        print("  HELD BACK pending the jurisdiction decision (see")
        print("  docs/CITATION_VERIFICATION_SESSION_REPORT.md):")
        for statute, ns in withheld.items():
            print(f"    {statute}: {ns}")
        print("  The bundled sources are Punjab-annotated; the federal")
        print("  consolidation shows these in force. Excluded, NOT reclassified.")
    print()
    for statute in sorted(found, key=lambda k: -len(found[k])):
        ns = sorted(found[statute])
        runs: list[list[int]] = [[ns[0]]]
        for n in ns[1:]:
            if n == runs[-1][-1] + 1:
                runs[-1].append(n)
            else:
                runs.append([n])          # a new list, not a cleared alias
        shown = ", ".join(f"{r[0]}-{r[-1]}" if len(r) > 1 else str(r[0])
                          for r in runs[:8])
        print(f"  {statute:38s} {len(ns):4d}  {shown}"
              f"{' ...' if len(runs) > 8 else ''}")

    if unmapped:
        print("\n  source files with omissions but no statute in the corpus:")
        for u in unmapped:
            print(f"    {u}")

    print()
    print("  A zero or absent statute means no RANGE/SINGLE declaration was")
    print("  found — not that the statute has none. The PPC's footnote style")
    print("  ('The following was omitted by A.O. 1961') is not parsed here.")

    if dry_run:
        print("\n--dry-run: nothing written")
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    held_out = {k: sorted(v) for k, v in
                ((s, held_back(s)) for s in sorted(set(found) | set(withheld)))
                if v}
    pending = {k: sorted(v) for k, v in
               ((s, pending_verification(s)) for s in sorted(found)) if v}
    OUT.write_text(json.dumps({
        "_note": ("Generated by scripts/build_omission_map.py from statute "
                  "source texts. Sections each Act declares omitted or "
                  "repealed. LOWER BOUND — footnote-style omissions (PPC) are "
                  "not parsed. Do not hand-edit; re-run the script."),
        "_held_pending_jurisdiction": {
            "reason": ("The bundled sources are Punjab-annotated and fold "
                       "provincial notifications into the text; the federal "
                       "consolidation at pakistancode.gov.pk shows these in "
                       "force. Excluded, NOT reclassified as in force. See "
                       "docs/CITATION_VERIFICATION_SESSION_REPORT.md."),
            "sections": held_out,
        },
        "_pending_verification": {
            "reason": ("Marked omitted by the federal consolidation but not by "
                       "this parser. NOT absorbed: adding them on one document "
                       "would repeat the edition mistake in reverse."),
            "sections": pending,
        },
        "statutes": {k: sorted(v) for k, v in sorted(found.items())},
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true")
    main(p.parse_args().dry_run)
