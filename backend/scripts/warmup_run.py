"""warmup_run.py — drive the threshold warmup, priced and stoppable.

Usage
-----
  # Confirm the gates without spending anything
  python scripts/warmup_run.py --preflight

  # The 21-query seed set, to confirm a clean run first
  python scripts/warmup_run.py --target 21

  # The full warmup
  python scripts/warmup_run.py --target 1000

Why this exists rather than looping seed_traffic
------------------------------------------------
seed_traffic.py drives 21 queries and registers a throwaway account per run, so
reaching 1000 would mean ~48 runs and ~48 accounts, with no cost visibility and
no way to stop when the balance runs dry. This reuses that module's query set
and its WebSocket turn driver — the traffic is identical — and adds the three
things a long run needs: a preflight gate, per-increment pricing, and a hard
stop.

The three rules it enforces
---------------------------
1. **Refuses to start without credit.** A run that begins on an empty balance
   burns the free allowance on 402s and reports nothing useful.
2. **Stops dead on a 402.** It does not retry, does not fall back to another
   provider, and does not carry on hoping. Retrying into a wall turns one clear
   failure into a hundred confusing ones.
3. **Projects the balance every increment.** If spend per query says the credit
   will not carry to the target, it says so at the first increment that shows
   it, not at the end.

The counter it reports is the REDIS-VISIBLE warmup total, which moves in steps
of threshold_manager._FLUSH_EVERY (25). A count that lags the queries sent is
batching, not loss — and since the shutdown flush landed, a gracefully stopped
server writes its remainder out too. Never stop a warmup server with taskkill
/F: no shutdown code runs and the buffered remainder is lost.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.ai import threshold_manager as tm  # noqa: E402
from scripts.seed_traffic import QUERIES, _auth, _one_turn  # noqa: E402

_CREDITS_URL = "https://openrouter.ai/api/v1/credits"
REPORT_EVERY = 25


# ── Money ────────────────────────────────────────────────────────────────────

async def credit_state() -> tuple[float, float]:
    """(remaining, total_usage) in USD. Raises if the endpoint is unreadable —
    a run must not start on a guess about the balance."""
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is not set")
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(_CREDITS_URL, headers={"Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        raise SystemExit(f"credits endpoint returned {r.status_code}: {r.text[:200]}")
    d = r.json().get("data", {}) or {}
    total = float(d.get("total_credits", 0) or 0)
    used  = float(d.get("total_usage", 0) or 0)
    return total - used, used


async def warmup_count() -> int:
    await tm.refresh()
    return tm._state.total_query_count


# ── Reporting ────────────────────────────────────────────────────────────────

def project(sent: int, target: int, spent: float, remaining: float) -> dict:
    """Will the balance carry to `target`? Pure, so the arithmetic is testable.

    `short` is how many queries beyond the balance the target sits. `shortfall`
    is what that costs in USD. Both are 0 when the run is affordable.
    """
    per_query = (spent / sent) if sent else 0.0
    to_go     = max(target - sent, 0)
    if per_query <= 0:
        return {"per_query": 0.0, "affordable": None, "to_go": to_go,
                "short": 0, "cost_to_finish": 0.0, "shortfall": 0.0}
    affordable     = int(remaining / per_query)
    cost_to_finish = to_go * per_query
    short          = max(to_go - affordable, 0)
    return {
        "per_query":      per_query,
        "affordable":     affordable,
        "to_go":          to_go,
        "short":          short,
        "cost_to_finish": cost_to_finish,
        "shortfall":      max(cost_to_finish - remaining, 0.0),
    }


def _report(sent: int, target: int, counter: int, spent: float,
            remaining: float, elapsed: float) -> None:
    p = project(sent, target, spent, remaining)
    per_query = p["per_query"]
    print(f"\n  ── {sent}/{target} sent | warmup counter {counter}/{tm.WARMUP_QUERY_COUNT} "
          f"(Redis-visible) | {elapsed / 60:.1f} min")
    print(f"     spend {spent:.4f} USD  =  {per_query:.4f}/query  |  "
          f"remaining {remaining:.4f}")

    if per_query <= 0:
        return
    affordable = p["affordable"]
    to_go      = p["to_go"]
    if p["short"]:
        short = p["short"]
        print(f"\n  *** DRAIN WARNING: at {per_query:.4f}/query the balance covers "
              f"~{affordable} more queries, {short} short of {target}. ***")
        print(f"      Est. cost to finish: {p['cost_to_finish']:.2f} USD "
              f"({p['shortfall']:.2f} more than the balance).")
        # The fast tier is the 8B model; the main tier is 70B. Public list
        # pricing puts the 8B roughly an order of magnitude below the 70B, so
        # moving the non-generation calls (gatekeeper, triage, grading) to it
        # is the available lever. Reported as a range, not a promise: the exact
        # saving depends on how many calls per turn each tier serves.
        print(f"      Routing more of the pipeline to the 8B fast tier would "
              f"stretch the remaining balance to roughly "
              f"{int(affordable * 3)}-{int(affordable * 8)} queries "
              f"(3-8x, tier price ratio); measure before relying on it.")


# ── Run ──────────────────────────────────────────────────────────────────────

async def run(args) -> None:
    # --free: the provider does not bill (Groq/Gemini free tier, local Ollama),
    # so there is no balance to read and no reason to gate on one. The limit
    # there is throughput and rate limits, not money, so the increment report
    # switches to queries/minute and consecutive-failure tracking.
    if args.free:
        return await run_free(args)

    remaining, usage_start = await credit_state()
    counter_start = await warmup_count()

    print("=" * 74)
    print("  WARMUP PREFLIGHT")
    print("=" * 74)
    print(f"  openrouter remaining : {remaining:.4f} USD")
    print(f"  warmup counter       : {counter_start}/{tm.WARMUP_QUERY_COUNT} (Redis-visible)")
    print(f"  flush interval       : every {tm._FLUSH_EVERY} queries")
    print(f"  target this run      : {args.target} queries")

    if remaining <= 0:
        print("\n  HOLDING: openrouter balance is zero or negative.")
        print("  Add credit, then re-run. Nothing was sent.\n")
        return
    if args.preflight:
        print("\n  Preflight only — nothing sent.\n")
        return

    api     = f"{args.base_url.rstrip('/')}/api/v1"
    ws_base = args.base_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/")

    started = time.monotonic()
    sent = ok = 0
    kinds: dict[str, int] = {}
    failures: list[str] = []

    async with httpx.AsyncClient(timeout=60) as http:
        token = await _auth(http, api, args.email, args.password)

        while sent < args.target:
            kind, content, meta = QUERIES[sent % len(QUERIES)]
            sent += 1
            try:
                msg   = await _one_turn(http, api, ws_base, token, content,
                                        meta, args.timeout)
                mtype = msg.get("type", "?")
                kinds[mtype] = kinds.get(mtype, 0) + 1
                if mtype != "error":
                    ok += 1
                else:
                    body = (msg.get("content") or "")[:120]
                    failures.append(f"[{sent}] {kind}: {body}")
            except Exception as exc:
                failures.append(f"[{sent}] {kind}: {type(exc).__name__}: {exc}")

            if sent % REPORT_EVERY == 0 or sent == args.target:
                remaining, usage_now = await credit_state()
                spent   = usage_now - usage_start
                counter = await warmup_count()
                _report(sent, args.target, counter, spent, remaining,
                        time.monotonic() - started)

                # Rule 2: stop dead rather than retrying into a wall.
                if remaining <= 0:
                    print("\n  *** STOPPING: balance exhausted mid-run. ***")
                    print("  Nothing further sent. Top up and re-run; the warmup "
                          "counter is cumulative, so progress is not lost.\n")
                    break

    elapsed = time.monotonic() - started
    remaining, usage_now = await credit_state()
    spent = usage_now - usage_start
    counter = await warmup_count()

    print("\n" + "=" * 74)
    print("  SUMMARY")
    print("=" * 74)
    print(f"  sent            : {sent}    clean: {ok}    failed: {sent - ok}")
    print(f"  by outcome      : {kinds}")
    print(f"  spend           : {spent:.4f} USD"
          + (f"  ({spent / sent:.4f}/query)" if sent else ""))
    print(f"  remaining       : {remaining:.4f} USD")
    print(f"  warmup counter  : {counter_start} -> {counter} "
          f"/ {tm.WARMUP_QUERY_COUNT} (Redis-visible)")
    print(f"  elapsed         : {elapsed / 60:.1f} min")
    if failures:
        print(f"\n  first failures ({len(failures)} total):")
        for line in failures[:10]:
            print(f"    ! {line}")
    print("\n  Stop the server with Ctrl+C / SIGTERM so the buffered remainder "
          "flushes.\n  NEVER taskkill /F — the remainder is lost.\n")


async def run_free(args) -> None:
    """Warmup against a non-billing provider.

    Money is not the constraint here, so nothing is gated on a balance. What
    does go wrong is rate limiting: a free tier that starts refusing produces a
    long run of fast failures that looks like progress in the counter but adds
    no usable traffic. So this tracks CONSECUTIVE failures and stops rather than
    hammering a provider that has already said no -- the same rule as the paid
    path, for the same reason.
    """
    counter_start = await warmup_count()
    print("=" * 74)
    print("  WARMUP (free provider — no billing)")
    print("=" * 74)
    print(f"  warmup counter  : {counter_start}/{tm.WARMUP_QUERY_COUNT} (Redis-visible)")
    print(f"  target this run : {args.target} queries")
    if args.preflight:
        print("\n  Preflight only — nothing sent.\n")
        return

    api     = f"{args.base_url.rstrip('/')}/api/v1"
    ws_base = args.base_url.replace("http://", "ws://").replace("https://", "wss://").rstrip("/")

    started = time.monotonic()
    sent = ok = 0
    consecutive_failures = 0
    kinds: dict[str, int] = {}
    failures: list[str] = []

    async with httpx.AsyncClient(timeout=60) as http:
        token = await _auth(http, api, args.email, args.password)

        while sent < args.target:
            kind, content, meta = QUERIES[sent % len(QUERIES)]
            sent += 1
            try:
                msg   = await _one_turn(http, api, ws_base, token, content,
                                        meta, args.timeout)
                mtype = msg.get("type", "?")
                kinds[mtype] = kinds.get(mtype, 0) + 1
                if mtype != "error":
                    ok += 1
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    failures.append(f"[{sent}] {kind}: {(msg.get('content') or '')[:120]}")
            except Exception as exc:
                consecutive_failures += 1
                failures.append(f"[{sent}] {kind}: {type(exc).__name__}: {exc}")

            if consecutive_failures >= args.max_consecutive_failures:
                print(f"\n  *** STOPPING: {consecutive_failures} failures in a row. ***")
                print("  A free tier that has started refusing will keep "
                      "refusing; hammering it turns one clear failure into "
                      "hundreds. Last few:")
                for line in failures[-3:]:
                    print(f"    ! {line}")
                break

            if sent % REPORT_EVERY == 0 or sent == args.target:
                elapsed = time.monotonic() - started
                counter = await warmup_count()
                rate    = sent / (elapsed / 60) if elapsed else 0
                left    = (args.target - sent) / rate if rate else 0
                print(f"\n  ── {sent}/{args.target} sent | clean {ok} | "
                      f"warmup counter {counter}/{tm.WARMUP_QUERY_COUNT} "
                      f"(Redis-visible)")
                print(f"     {elapsed / 60:.1f} min elapsed | {rate:.1f} queries/min | "
                      f"~{left:.0f} min to target")

    elapsed = time.monotonic() - started
    counter = await warmup_count()
    print("\n" + "=" * 74)
    print("  SUMMARY")
    print("=" * 74)
    print(f"  sent           : {sent}    clean: {ok}    failed: {sent - ok}")
    print(f"  by outcome     : {kinds}")
    print(f"  warmup counter : {counter_start} -> {counter} / {tm.WARMUP_QUERY_COUNT}")
    print(f"  elapsed        : {elapsed / 60:.1f} min")
    if failures:
        print(f"\n  first failures ({len(failures)} total):")
        for line in failures[:10]:
            print(f"    ! {line}")
    print("\n  Stop the server with `python scripts/serve.py stop` so the "
          "buffered remainder flushes.\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Drive threshold warmup with cost control.")
    p.add_argument("--target",    type=int, default=1000, help="queries to send")
    p.add_argument("--preflight", action="store_true", help="check gates, send nothing")
    p.add_argument("--base-url",  default="http://127.0.0.1:8000")
    p.add_argument("--email",     default="")
    p.add_argument("--password",  default="")
    p.add_argument("--timeout",   type=int, default=180)
    p.add_argument("--free", action="store_true",
                   help="provider does not bill (Groq/Gemini free tier, Ollama): "
                        "skip balance gating, watch throughput and rate limits")
    p.add_argument("--max-consecutive-failures", type=int, default=5,
                   help="stop after this many failures in a row (--free)")
    asyncio.run(run(p.parse_args()))
