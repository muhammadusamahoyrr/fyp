"""Measure A1 against the D-lite set, and apply the pre-committed ship rule.

    python scripts/evaluate_a1.py

The headline number is PRECISION ON THE FLAG CLASS: of the pairs A1 calls
mismatched, how many really are. Recall is secondary — a missed misgrounding
leaves the status quo, a false accusation is a regression, and this subsystem
has already shipped one of those.

PRE-COMMITTED RULE, written before any number existed:

    precision >= 0.90   ship as an advisory flag, same tier as NOT_IN_CORPUS
    0.70 - 0.90         ship DEMOTED: "may not be on point", not a hard flag
    < 0.70              do not ship a verdict; report as a negative result

A borderline number is not rounded up, and where the confidence interval spans
a band boundary the report says so rather than picking the flattering side.

THE THRESHOLD IS FITTED ON THIS SET
-----------------------------------
48 pairs is too few to hold any out, so the operating threshold is chosen on the
same data it is scored on. Every precision figure below is therefore OPTIMISTIC
— an upper estimate of what a fresh set would show. This is stated in the output
as well as here, because a fitted number quoted without that caveat is the same
class of error as an unearned inter-annotator statistic.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.ai.mismatch_detection import score  # noqa: E402
from app.db.chroma import connect_chroma  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[1] / "tests" / "fixtures"
           / "citation_eval" / "dlite_v1.json")

MISGROUNDED = {"misgrounded_gross", "misgrounded_same_topic"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — correct at small n, unlike the normal approx,
    which produces impossible bounds outside [0,1] on sets this size."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def main() -> None:
    connect_chroma()
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pairs = data["pairs"]

    print("=" * 78)
    print("  A1 MISMATCH DETECTION — measured against dlite_v1")
    print("=" * 78)
    print(f"  fixture pairs                    : {len(pairs)}")
    print(f"  annotation                       : SINGLE (no agreement measured)")

    scored, skipped_gap, unassessable = [], [], []
    for p in pairs:
        if p.get("known_gap"):
            skipped_gap.append(p)
            continue
        s = score(p["assertion"], p["statute"], str(p["section"]))
        if not s.assessable:
            unassessable.append((p, s))
            continue
        scored.append((p, s.similarity))

    print(f"  excluded as known_gap            : {len(skipped_gap)}"
          f"   (test the omission parser, not A1)")
    print(f"  no stored text -> not assessable : {len(unassessable)}")
    print(f"  SCORED                           : {len(scored)}")

    by_label = defaultdict(list)
    for p, sim in scored:
        by_label[p["label"]].append(sim)

    print()
    print("  similarity by ground-truth label (higher = more on-topic)")
    print(f"    {'label':26s} {'n':>3s} {'min':>6s} {'mean':>6s} {'max':>6s}")
    for label in ("supported", "misgrounded_gross", "misgrounded_same_topic",
                  "repealed", "omitted", "fabricated"):
        v = by_label.get(label) or []
        if not v:
            continue
        print(f"    {label:26s} {len(v):3d} {min(v):6.3f} "
              f"{sum(v)/len(v):6.3f} {max(v):6.3f}")

    # ── threshold sweep ──────────────────────────────────────────────────────
    # "Flag" = similarity below threshold. Ground-truth positive = misgrounded.
    print()
    print("  THRESHOLD SWEEP — precision on the flag class")
    print(f"    {'thresh':>7s} {'flagged':>8s} {'correct':>8s} {'prec':>7s} "
          f"{'95% CI':>16s} {'recall':>7s}")
    n_mis = sum(1 for p, _ in scored if p["label"] in MISGROUNDED)
    rows = []
    for t in [i / 100 for i in range(70, 96)]:
        flagged = [(p, s) for p, s in scored if s < t]
        k = sum(1 for p, _ in flagged if p["label"] in MISGROUNDED)
        if not flagged:
            continue
        prec = k / len(flagged)
        lo, hi = wilson(k, len(flagged))
        rec = k / n_mis if n_mis else 0.0
        rows.append((t, len(flagged), k, prec, lo, hi, rec))
    for t, nf, k, prec, lo, hi, rec in rows:
        if abs(t * 100 - round(t * 100)) < 1e-9 and round(t * 100) % 1 == 0:
            print(f"    {t:7.2f} {nf:8d} {k:8d} {prec:7.3f} "
                  f"[{lo:.3f},{hi:.3f}] {rec:7.3f}")

    if not rows:
        print("\n  No threshold produces any flag. A1 cannot separate these.")
        return

    # Operating point: highest precision, ties broken by recall. Chosen ON this
    # data — see the module docstring.
    best = max(rows, key=lambda r: (r[3], r[6]))
    t, nf, k, prec, lo, hi, rec = best

    print()
    print("  " + "-" * 74)
    print("  OPERATING POINT (threshold fitted on this same set)")
    print("  " + "-" * 74)
    print(f"    threshold                      : similarity < {t:.2f}")
    print(f"    pairs flagged                  : {nf}")
    print(f"    of those, truly misgrounded    : {k}")
    print(f"    PRECISION ON THE FLAG CLASS    : {prec:.3f}")
    print(f"    95% CI (Wilson, n={nf})         : [{lo:.3f}, {hi:.3f}]")
    print(f"    recall of misgrounded pairs    : {rec:.3f}  ({k}/{n_mis})")

    # ── gross vs same-topic, scored separately ───────────────────────────────
    print()
    print("  " + "-" * 74)
    print("  GROSS vs SAME-TOPIC — do they behave differently?")
    print("  " + "-" * 74)
    for label in ("misgrounded_gross", "misgrounded_same_topic"):
        v = by_label.get(label) or []
        if not v:
            continue
        caught = sum(1 for x in v if x < t)
        lo2, hi2 = wilson(caught, len(v))
        print(f"    {label:26s} caught {caught}/{len(v)} "
              f"= {caught/len(v):.3f}  CI [{lo2:.3f},{hi2:.3f}]")
    sup = by_label.get("supported") or []
    if sup:
        fp = sum(1 for x in sup if x < t)
        print(f"    {'supported (false alarms)':26s} flagged {fp}/{len(sup)} "
              f"= {fp/len(sup):.3f}")

    # ── the pre-committed decision ───────────────────────────────────────────
    print()
    print("  " + "=" * 74)
    print("  DECISION (rule fixed before the number existed)")
    print("  " + "=" * 74)
    band = ("SHIP as advisory flag" if prec >= 0.90 else
            "SHIP DEMOTED — 'may not be on point'" if prec >= 0.70 else
            "DO NOT SHIP a verdict; report as a negative result")
    print(f"    point estimate {prec:.3f}  ->  {band}")
    crosses = [b for b in (0.70, 0.90) if lo < b < hi]
    if crosses:
        print(f"    BUT the 95% CI [{lo:.3f}, {hi:.3f}] spans "
              f"{', '.join(str(b) for b in crosses)}.")
        print("    The point estimate does not settle the band. Treat the")
        print("    LOWER bound as the decision input, not the point estimate:")
        low_band = ("advisory flag" if lo >= 0.90 else
                    "demoted" if lo >= 0.70 else "do not ship")
        print(f"    lower bound {lo:.3f} -> {low_band}")
    print()
    print("    Threshold was fitted on these 48 pairs with nothing held out, so")
    print("    this precision is an UPPER estimate of fresh-data performance.")

    # ── disagreements, concretely ────────────────────────────────────────────
    print()
    print("  " + "-" * 74)
    print("  DISAGREEMENTS — where the score and the label part company")
    print("  " + "-" * 74)
    misses = [(p, s) for p, s in scored
              if p["label"] in MISGROUNDED and s >= t]
    falses = [(p, s) for p, s in scored
              if p["label"] == "supported" and s < t]
    print(f"\n  MISSED misgroundings ({len(misses)}) — scored as on-topic:")
    for p, s in sorted(misses, key=lambda x: -x[1])[:6]:
        print(f"    {s:.3f}  [{p['label'].replace('misgrounded_','')}] "
              f"{p['statute']} s.{p['section']}")
        print(f"           claim   : {p['assertion'][:78]}")
        print(f"           actually: {p.get('real_heading','?')[:78]}")
    print(f"\n  FALSE ALARMS on supported pairs ({len(falses)}):")
    for p, s in sorted(falses, key=lambda x: x[1])[:6]:
        print(f"    {s:.3f}  {p['statute']} s.{p['section']}")
        print(f"           claim   : {p['assertion'][:78]}")

    if unassessable:
        print(f"\n  NOT ASSESSABLE ({len(unassessable)}) — no stored text:")
        for p, s in unassessable[:8]:
            print(f"    [{p['label']:22s}] {p['statute']} s.{p['section']}")
    print()


if __name__ == "__main__":
    main()
