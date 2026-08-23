"""fit_conformal.py — fit the conformal threshold from labelled traffic.

Usage
-----
  # What the current labels support
  python scripts/fit_conformal.py --alpha 0.10

  # Include the class-conditional (Mondrian) split
  python scripts/fit_conformal.py --alpha 0.10 --by-case-type

  # Also report the selective-prediction metrics on the same set
  python scripts/fit_conformal.py --alpha 0.10 --metrics

This reads the AUTHORITATIVE labels (adjudicated, or agreed and merged — see
agreement.py), never the raw label documents, so a disputed turn cannot slip
into the calibration set under one annotator's verdict.

The threshold this prints is not installed anywhere by itself. Fitting is a
deliberate act: the guarantee it produces is only as good as the labels behind
it, and an automatically-refreshed guarantee nobody looked at is worse than
none.
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

from app.ai import conformal_state  # noqa: E402
from app.ai.conformal import (  # noqa: E402
    MIN_GROUP_CALIBRATION,
    CalibrationPoint,
    calibrate,
    calibrate_by_group,
    empirical_joint_error,
    operating_threshold,
)
from app.ai.harm import harm_ratio_for_threshold  # noqa: E402
from app.ai.selective_metrics import Turn, report  # noqa: E402
from app.ai.threshold_manager import get_generation_floor  # noqa: E402
from app.db.mongodb import close_db, connect_db  # noqa: E402
from app.services import labeling_service as ls  # noqa: E402


async def _points() -> tuple[list[CalibrationPoint], list[dict]]:
    pairs = await ls.export_calibration_pairs()
    prov_case = {}
    from app.db.collections import get_answer_provenance_col
    async for d in get_answer_provenance_col().find(
        {"request_id": {"$in": [p["request_id"] for p in pairs]}},
        {"request_id": 1, "case_type": 1, "_id": 0},
    ):
        prov_case[d["request_id"]] = d.get("case_type", "") or ""

    pts = [
        CalibrationPoint(
            confidence=float(p.get("relevance_score") or 0.0),
            correct=bool(p.get("correct")),
            group=prov_case.get(p["request_id"], ""),
        )
        for p in pairs
    ]
    return pts, pairs


async def _main(args: argparse.Namespace) -> None:
    await connect_db()
    try:
        pts, pairs = await _points()
        print(f"\n  calibration points: {len(pts)}")
        if not pts:
            print("\n  Nothing labelled yet. The conformal guarantee is "
                  "unavailable and the harm matrix governs alone.\n"
                  "  See ANNOTATION_PROTOCOL.md to start labelling.\n")
            return

        n_wrong = sum(1 for p in pts if not p.correct)
        print(f"  of which wrong     : {n_wrong}")
        if len(pts) < 100:
            print(f"\n  WARNING: {len(pts)} points is thin. At alpha={args.alpha} "
                  f"realised coverage fluctuates by roughly "
                  f"{(args.alpha * (1 - args.alpha) / len(pts)) ** 0.5:.1%}.")

        t = calibrate(pts, alpha=args.alpha)
        rho = harm_ratio_for_threshold(max(get_generation_floor(), 1e-6))
        op = operating_threshold(t, rho)

        print(f"\n  conformal threshold : {t.threshold:.4f}  "
              f"(alpha={args.alpha}, admits {t.admitted} of {t.n_wrong} wrong)")
        print(f"  harm threshold      : {op.harm:.4f}  (rho={rho:.2f})")
        print(f"  OPERATING POINT     : {op.threshold:.4f}  "
              f"— {op.binding} binds")
        if op.binding == "harm":
            print("    the conformal threshold is below the harm threshold and "
                  "is doing no work at this alpha")
        if t.trivial:
            print("    NOTE: this threshold refuses everything — the guarantee "
                  "is met vacuously")

        # In-sample only. Held-out verification is what the test suite does;
        # this is a sanity read, and saying so prevents it being quoted as
        # evidence the bound generalises.
        insample = empirical_joint_error(pts, t.threshold)
        print(f"\n  in-sample joint error: {insample:.4f} (target <= {args.alpha}) "
              "— IN-SAMPLE, not a held-out check")

        if args.by_case_type:
            groups = calibrate_by_group(pts, alpha=args.alpha)
            print(f"\n  class-conditional (min {MIN_GROUP_CALIBRATION} points):")
            for name, gt in sorted(groups.items()):
                if name == "__marginal__":
                    continue
                flag = "  <- fell back, too few points" if gt.fell_back else ""
                print(f"    {name or '(none)':<18} n={gt.n:<5} "
                      f"threshold={gt.threshold:.4f}{flag}")

        if args.metrics:
            turns = [
                Turn(confidence=float(p.get("relevance_score") or 0.0),
                     correct=bool(p.get("correct")),
                     abstained=not bool(p.get("answered")))
                for p in pairs
            ]
            answerable = [p.get("verdict") != "correct_refusal" for p in pairs]
            rep = report(turns, answerable)
            print("\n  SELECTIVE PREDICTION")
            for k in ("n_turns", "n_answered", "n_abstained", "aurc", "ece",
                      "refusal_precision", "refusal_recall", "accuracy"):
                print(f"    {k:<20} : {rep[k]}")
            for c in rep["caveats"]:
                print(f"    - {c}")

        if args.install:
            conformal_state.fit(pts, alpha=args.alpha)
            print("\n  installed into the running process only — this does not "
                  "persist across a restart.")
        print()
    finally:
        await close_db()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Fit the conformal threshold.")
    p.add_argument("--alpha", type=float, default=conformal_state.DEFAULT_ALPHA,
                   help="target joint answer-and-wrong probability")
    p.add_argument("--by-case-type", action="store_true",
                   help="also fit class-conditional (Mondrian) thresholds")
    p.add_argument("--metrics", action="store_true",
                   help="report selective-prediction metrics on the same set")
    p.add_argument("--install", action="store_true",
                   help="install into the current process (does not persist)")
    asyncio.run(_main(p.parse_args()))
