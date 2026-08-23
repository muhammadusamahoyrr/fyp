"""agreement_report.py — inter-annotator agreement, disagreements, adjudication.

Usage
-----
  # Krippendorff's alpha over chunk relevance and answer verdicts
  python scripts/agreement_report.py

  # Turns where annotators differ and no adjudication exists
  python scripts/agreement_report.py --disagreements

  # Record a tie-breaking judgement (supersedes both annotators)
  python scripts/agreement_report.py --adjudicate <request_id> \
      --labeler senior --verdict correct --relevant c1,c2

  # What the metrics harness would actually consume
  python scripts/agreement_report.py --resolved

See ANNOTATION_PROTOCOL.md for what the numbers mean and why a very high alpha
on legal relevance is a warning rather than a success.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.services import agreement, labeling_service  # noqa: E402


def _fmt(value) -> str:
    return "not measurable yet" if value is None else f"{value:+.4f}"


async def _report() -> None:
    rep = await agreement.agreement_report()
    print("\n  INTER-ANNOTATOR AGREEMENT")
    print("  " + "=" * 62)
    print(f"  annotators                 : {', '.join(rep['annotators']) or 'none'}")
    print(f"  turns labelled             : {rep['turns_total']}")
    print(f"  double-labelled            : {rep['turns_double_labelled']} "
          f"({rep['double_labelled_pct']}%)")
    print(f"  chunk units judged twice   : {rep['chunk_units_judged_twice']}")
    print()
    print(f"  alpha, chunk relevance     : {_fmt(rep['alpha_chunk_relevance'])}")
    print(f"    {rep['interpretation_chunk']}")
    print(f"  alpha, answer verdict      : {_fmt(rep['alpha_answer_verdict'])}")
    print(f"    {rep['interpretation_verdict']}")

    if rep["turns_double_labelled"] < 50:
        print(f"\n  NOTE: {rep['turns_double_labelled']} double-labelled turns is "
              "below the ~50 needed to report alpha credibly.")
    print()


async def _disagreements(limit: int) -> None:
    rows = await agreement.disagreements()
    print(f"\n  UNRESOLVED DISAGREEMENTS: {len(rows)}")
    print("  " + "=" * 62)
    if not rows:
        print("  None. Either the annotators agreed, or nothing is "
              "double-labelled yet — check the report above.\n")
        return
    for d in rows[:limit]:
        kind = "VERDICT" if d["verdict_conflict"] else "chunks "
        print(f"  [{kind}] {d['request_id']}")
        if d["verdict_conflict"]:
            print(f"            {' vs '.join(d['verdicts'])}  "
                  f"({', '.join(d['annotators'])})")
        if d["chunk_conflicts"]:
            print(f"            {len(d['chunk_conflicts'])} disputed chunk(s): "
                  f"{', '.join(d['chunk_conflicts'][:4])}"
                  f"{' ...' if len(d['chunk_conflicts']) > 4 else ''}")
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more")
    print("\n  Resolve with --adjudicate <request_id> --labeler <name> "
          "--verdict <v> --relevant <ids>\n")


async def _resolved() -> None:
    chosen, summary = await agreement.authoritative_labels()
    print("\n  AUTHORITATIVE LABEL SET")
    print("  " + "=" * 62)
    for k, v in summary.items():
        if k == "excluded_request_ids":
            continue
        print(f"  {k:<24} : {v}")
    if summary["excluded_request_ids"]:
        print(f"  excluded (unresolved)    : "
              f"{', '.join(summary['excluded_request_ids'][:5])}"
              f"{' ...' if len(summary['excluded_request_ids']) > 5 else ''}")
    if summary["singly_labelled"]:
        print(f"\n  NOTE: {summary['singly_labelled']} turns carry a single "
              "judgement and therefore no agreement evidence.")
    print()


async def _adjudicate(request_id: str, labeler: str, verdict: str,
                      relevant: str) -> None:
    by_request = await agreement._labels_by_request()
    existing = by_request.get(request_id)
    if not existing:
        raise SystemExit(f"no labels exist for {request_id!r}")

    # Judge every chunk either annotator saw, so the adjudication is complete
    # rather than partial — a chunk omitted here would be unjudged, not
    # irrelevant, and would silently shrink the pooling depth.
    all_chunks: set[str] = set()
    depth = 0
    for lab in existing:
        all_chunks |= set((lab.get("chunk_labels") or {}).keys())
        depth = max(depth, lab.get("labeled_depth", 0) or 0)

    marked = {c.strip() for c in relevant.split(",") if c.strip()}
    unknown = marked - all_chunks
    if unknown:
        raise SystemExit(
            f"these chunk ids were not retrieved for this turn: {sorted(unknown)}"
        )

    doc = await labeling_service.save_label(
        request_id=request_id,
        chunk_labels={c: (c in marked) for c in sorted(all_chunks)},
        answer_verdict=verdict,
        labeler=labeler,
        notes="adjudication",
        labeled_depth=depth,
        is_adjudication=True,
    )
    print(f"\n  adjudicated {request_id}: verdict={verdict}, "
          f"{len(doc['relevant_chunks'])}/{len(all_chunks)} chunks relevant\n")


async def _main(args: argparse.Namespace) -> None:
    await connect_db()
    try:
        if args.adjudicate:
            if not (args.labeler and args.verdict):
                raise SystemExit("--adjudicate requires --labeler and --verdict")
            await _adjudicate(args.adjudicate, args.labeler, args.verdict,
                              args.relevant or "")
        elif args.disagreements:
            await _disagreements(args.limit)
        elif args.resolved:
            await _resolved()
        else:
            await _report()
    finally:
        await close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Inter-annotator agreement and adjudication.")
    parser.add_argument("--disagreements", action="store_true",
                        help="list unresolved disagreements")
    parser.add_argument("--resolved", action="store_true",
                        help="summarise the authoritative label set")
    parser.add_argument("--adjudicate", metavar="REQUEST_ID",
                        help="record a tie-breaking judgement")
    parser.add_argument("--labeler", help="adjudicator name")
    parser.add_argument("--verdict", choices=labeling_service.VERDICTS,
                        help="adjudicated verdict")
    parser.add_argument("--relevant", default="",
                        help="comma-separated chunk ids judged relevant")
    parser.add_argument("--limit", type=int, default=20)
    asyncio.run(_main(parser.parse_args()))
