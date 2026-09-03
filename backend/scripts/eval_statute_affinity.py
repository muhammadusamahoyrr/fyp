"""eval_statute_affinity.py — does named-statute affinity get PPC 379 to generation?

Cache isolation
---------------
Production Redis is NEVER read or written. cache.get_result is forced to miss and
cache.set_result to a no-op before the graph is imported, so every trial is a
genuine uncached run and no probe answer can leak into the live cache. (An earlier
session did seed production Redis to exercise this path; it must not recur.)

Why both conditions come from one run
-------------------------------------
Affinity is a deterministic reordering of the candidate list, so the counterfactual
"rank without affinity" is exactly the position in the list handed TO it. Recording
both sides of the same call gives a paired comparison and halves the LLM spend,
which matters at ~100 s per trial.

Retrieval is nondeterministic across live runs (confidence 0.42 vs 0.85 on identical
queries has been observed), so single runs prove nothing — hence 10 trials and a
distribution rather than a before/after pair. Only runs whose signal_origin is
"measured" are counted; cached_source / cached_legacy / unmeasured are excluded.

Usage:  python scripts/eval_statute_affinity.py [--trials 10] [--out results.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(level=logging.ERROR)

TARGET_CHUNK = "statutes_ppc_1860_0598"          # PPC 379, "Punishment for theft"
QUERY = "What is the punishment for theft under the Pakistan Penal Code?"
MULTI_QUERY = "Compare the Pakistan Penal Code and the Code of Criminal Procedure on theft"


def _rank(seq, pred):
    for i, item in enumerate(seq, 1):
        if pred(item):
            return i
    return None


def _is_target(c):
    if isinstance(c, dict):
        return c.get("chunk_id") == TARGET_CHUNK
    return (getattr(c, "metadata", {}) or {}).get("chunk_id") == TARGET_CHUNK


def _isolate_checkpointer():
    """Swap MongoDBSaver for an in-memory saver BEFORE the graph is built.

    supervisor.py compiles chat_graph at import time with MongoDBSaver(), so an
    earlier run of this harness wrote LangGraph checkpoints straight into the
    production `attorney_ai` database — 1,988 documents across lg_checkpoints
    and lg_checkpoint_writes under thread ids beginning "affinity-eval-".
    Evaluation must leave no trace in production state; patching the name in the
    checkpointer module before supervisor is first imported is what achieves
    that, because the import binds whatever is there at that moment.
    """
    from langgraph.checkpoint.memory import MemorySaver

    import app.ai.graph.checkpointer as cp
    cp.MongoDBSaver = MemorySaver          # type: ignore[assignment]
    assert "app.ai.graph.supervisor" not in sys.modules, (
        "supervisor already imported — the checkpointer patch would be too late")


async def _isolate_side_effects():
    """Force cache misses, drop cache writes, and silence Redis observers."""
    from app.ai import cache

    async def _miss(*a, **k):
        return None

    async def _noop(*a, **k):
        return None

    cache.get_result = _miss          # type: ignore[assignment]
    cache.set_result = _noop          # type: ignore[assignment]
    cache.get_chunks = _miss          # type: ignore[assignment]
    cache.set_chunks = _noop          # type: ignore[assignment]

    # threshold_manager.record_query and calibration.record_score_for_drift both
    # write to Redis on every graded turn. They are observability, not part of
    # the ranking behaviour under test, and a measurement run must not move the
    # thresholds that govern production answers.
    import app.ai.nodes.retrieval_grader_node as grader
    grader.record_query = _noop            # type: ignore[assignment]
    grader.record_score_for_drift = _noop  # type: ignore[assignment]


def _instrument(record: dict):
    """Wrap apply_affinity at the retrieval_node call site to capture both orders."""
    import app.ai.nodes.retrieval_node as rn
    from app.ai.pipelines import statute_affinity as sa

    real = sa.apply_affinity

    def wrapper(chunks, query):
        before = list(chunks)
        out, named = real(chunks, query)
        record["named"] = named
        record["rank_pre_affinity"] = _rank(before, _is_target)
        record["rank_post_affinity"] = _rank(out, _is_target)
        record["n_candidates"] = len(before)
        record["top8_statutes_pre"] = [
            (c.get("statute"), c.get("section_number")) for c in before[:8]]
        record["top8_statutes_post"] = [
            (c.get("statute"), c.get("section_number")) for c in out[:8]]
        return out, named

    rn.apply_affinity = wrapper        # type: ignore[assignment]
    return real


async def one_trial(n: int, query: str) -> dict:
    from app.ai.graph.supervisor import chat_graph
    from app.websockets.chat_socket import _build_state

    rec: dict = {"trial": n, "query": query}
    _instrument(rec)

    tid = f"affinity-eval-{int(time.time()*1000)}-{n}"
    cfg = {"configurable": {"thread_id": tid}}
    st = _build_state(query, tid, {}, {"language": "en", "province": "punjab"},
                      history=[], user_id="affinity-eval", user_role="client")
    t0 = time.time()
    await chat_graph.ainvoke(st, config=cfg)
    v = (await chat_graph.aget_state(config=cfg)).values

    rec["seconds"] = round(time.time() - t0, 1)
    rec["signal_origin"] = v.get("signal_origin")
    rec["cache_hit"] = bool(v.get("cache_hit"))
    rec["relevance_score"] = v.get("relevance_score")
    rec["bm25_confidence"] = v.get("bm25_confidence")
    rec["arbitration_source"] = v.get("arbitration_source")
    rec["confidence"] = v.get("confidence")

    rec["rank_after_grading"] = _rank(v.get("reranked_chunks") or [], _is_target)
    evidence = v.get("generation_evidence") or []
    rec["rank_generation_evidence"] = _rank(evidence, _is_target)
    rec["in_generation_evidence"] = rec["rank_generation_evidence"] is not None

    answer = v.get("answer") or ""
    rec["answer_len"] = len(answer)
    low = answer.lower()
    # PPC 379: "imprisonment of either description for a term which may extend
    # to three years, or with fine, or with both". A loose check ("three years"
    # AND "fine") passes on an answer that merely gestures at the provision, so
    # all four elements are required separately and recorded individually — a
    # partial pass must be visible in the data, not rounded up to success.
    elements = {
        "imprisonment": "imprisonment" in low,
        "three_years":  ("three years" in low or "3 years" in low),
        "fine":         "fine" in low,
        "or_both":      ("or both" in low or "or with both" in low),
    }
    rec["punishment_elements"] = elements
    rec["states_punishment"] = all(elements.values())
    rec["cites_382"] = "382" in answer

    cits = [c for c in (v.get("citations") or []) if c.get("type") != "judgment"]
    rec["citations"] = [(c.get("statute"), str(c.get("section")), c.get("status"))
                        for c in cits]
    # "matched" means the citation resolved against a chunk actually present in
    # this answer's evidence. A CrPC provision that merely mentions "379" would
    # surface the number without the provision, so the evidence membership is
    # asserted separately rather than inferred from the citation alone.
    rec["ppc379_matched"] = any(
        str(c.get("section")) == "379" and "PPC" in str(c.get("statute"))
        and c.get("status") == "matched" for c in cits)
    # build_generation_evidence emits "section", NOT "section_number" — the key
    # is renamed when a retrieval chunk becomes an evidence item. Reading the
    # chunk-side name here returned None for every item and reported 0/10 while
    # the chunk_id rank simultaneously found PPC 379 at rank 1-6 in all ten
    # trials. Two measurements of the same fact disagreeing is the signal that
    # one of them is wrong; it was this one.
    rec["ppc379_in_evidence"] = any(
        str(e.get("section")) == "379" and "PPC" in str(e.get("statute", ""))
        for e in evidence if isinstance(e, dict))
    rec["accepted"] = (rec["states_punishment"] and rec["ppc379_matched"]
                       and rec["ppc379_in_evidence"] and not rec["cites_382"])
    rec["statutes_in_evidence"] = sorted({
        (e.get("statute") or "") for e in evidence if isinstance(e, dict)})
    return rec


async def main(trials: int, out_path: str | None, delay: float, max_attempts: int):
    from app.db.chroma import connect_chroma
    from app.db.mongodb import connect_db

    # Best-effort, not required. The checkpointer is in-memory, so the graph no
    # longer needs Mongo for this harness — and a transient DNS failure resolving
    # the Atlas SRV record killed a run before trial 1, which is an absurd way to
    # lose a 25-minute measurement. Chroma IS required: it holds the corpus.
    try:
        await connect_db()
    except Exception as exc:
        print(f"  (Mongo unavailable — continuing without it: {type(exc).__name__})")
    connect_chroma()
    _isolate_checkpointer()
    await _isolate_side_effects()

    # Run until `trials` MEASURED results exist, bounded by max_attempts.
    #
    # A provider failure is not a measurement, so it must not consume one of the
    # ten. Earlier runs conflated the two and reported "3/10 trials" when what
    # had actually happened was seven refused requests. The attempt bound is the
    # quota guard: without it a rate-limited provider turns a retry loop into an
    # unbounded spend, and with it the run stops and reports BLOCKED instead.
    rows = []
    measured_count = 0
    attempt = 0
    while measured_count < trials and attempt < max_attempts:
        attempt += 1
        if attempt > 1 and delay:
            await asyncio.sleep(delay)
        try:
            r = await one_trial(attempt, QUERY)
        except Exception as exc:
            r = {"trial": attempt, "query": QUERY,
                 "error": f"{type(exc).__name__}: {exc}"[:200],
                 "signal_origin": None, "cache_hit": False}
            print(f"  attempt {attempt:2d}  ERROR  {r['error'][:100]}")
        rows.append(r)
        if r.get("error"):
            continue
        if r.get("signal_origin") != "measured" or r.get("cache_hit"):
            print(f"  attempt {attempt:2d}  DISCARDED origin={r.get('signal_origin')!r}")
            continue
        measured_count += 1
        print(f"  MEASURED {measured_count:2d}/{trials} (attempt {attempt:2d})  {r['seconds']:5.1f}s  "
              f"pre={r['rank_pre_affinity']} post={r['rank_post_affinity']} "
              f"graded={r['rank_after_grading']} evid={r['rank_generation_evidence']} "
              f"punish={r['states_punishment']} 382={r['cites_382']}")

    # Persist the trial rows BEFORE the control runs. An earlier run lost ten
    # trials' worth of data because the control raised on an exhausted provider
    # and took the whole process down before anything was written. Measurement
    # data that exists must survive a later step failing.
    def _save(rows_, multi_):
        if out_path:
            Path(out_path).write_text(
                json.dumps({"trials": rows_, "multi": multi_}, indent=1), encoding="utf-8")
            print(f"\n  written: {out_path}")

    _save(rows, None)

    print("\n  multi-statute control (must keep BOTH statutes):")
    if delay:
        await asyncio.sleep(delay)
    try:
        multi = await one_trial(0, MULTI_QUERY)
        print(f"    named={multi['named']!r}  statutes in evidence={multi['statutes_in_evidence']}")
    except Exception as exc:
        multi = {"error": f"{type(exc).__name__}: {exc}"[:200], "named": "n/a",
                 "statutes_in_evidence": []}
        print(f"    CONTROL FAILED: {multi['error'][:110]}")

    _save(rows, multi)
    report(rows, multi, required=trials)
    # (the JSON is written by _save() above, before and after the control)


def report(rows: list[dict], multi: dict, required: int = 10):
    errored = [r for r in rows if r.get("error")]
    measured = [r for r in rows if r.get("signal_origin") == "measured"
                and not r.get("cache_hit")]
    print(f"\n{'='*74}\nMEASURED TRIALS: {len(measured)} of {len(rows)} attempts "
          f"({len(errored)} provider failures; cached/unmeasured excluded)")
    # `required`, never a literal 10. A hardcoded threshold printed BLOCKED over a
    # successful one-trial verification run — a false failure verdict, which is
    # exactly the class of defect this harness exists to catch rather than emit.
    if len(measured) < required:
        print(f"\n  *** BLOCKED — {len(measured)} measured trials of {required} required, "
              f"after {len(rows)} attempts ({len(errored)} provider failures). ***")
    if not measured:
        print("  no measured trials — nothing to report")
        return

    def stat(key):
        vals = [r[key] for r in measured if r.get(key) is not None]
        if not vals:
            return "n/a"
        return f"min {min(vals)} / med {statistics.median(vals):.0f} / max {max(vals)}"

    print(f"\n  PPC 379 rank, raw candidates (pre-affinity) : {stat('rank_pre_affinity')}")
    print(f"  PPC 379 rank, after affinity                : {stat('rank_post_affinity')}")
    print(f"  PPC 379 rank, after grading                 : {stat('rank_after_grading')}")
    print(f"  PPC 379 rank, generation evidence           : {stat('rank_generation_evidence')}")

    n = len(measured)
    top8_pre = sum(1 for r in measured
                   if r.get("rank_pre_affinity") and r["rank_pre_affinity"] <= 8)
    top8_post = sum(1 for r in measured
                    if r.get("rank_post_affinity") and r["rank_post_affinity"] <= 8)
    in_ev = sum(1 for r in measured if r["in_generation_evidence"])
    print(f"\n  top-8 inclusion, pre-affinity   : {top8_pre}/{n}")
    print(f"  top-8 inclusion, post-affinity  : {top8_post}/{n}")
    # The bar scales with the run: 90% of what was required, not a literal 9/10.
    threshold = max(1, int(round(required * 0.9)))
    print(f"  reached generation evidence     : {in_ev}/{n}   "
          f"(acceptance: >= {threshold}/{required})")
    print(f"  PPC 379 in generation evidence  : {sum(1 for r in measured if r['ppc379_in_evidence'])}/{n}")
    print(f"  answer states the punishment    : {sum(1 for r in measured if r['states_punishment'])}/{n}")
    for el in ("imprisonment", "three_years", "fine", "or_both"):
        print(f"      element {el:14}: {sum(1 for r in measured if r['punishment_elements'][el])}/{n}")
    print(f"  FULLY ACCEPTED trials           : {sum(1 for r in measured if r['accepted'])}/{n}")
    print(f"  PPC 379 a matched citation      : {sum(1 for r in measured if r['ppc379_matched'])}/{n}")
    print(f"  answer mentions 382             : {sum(1 for r in measured if r['cites_382'])}/{n}   (want 0)")

    rel = [r["relevance_score"] for r in measured if r.get("relevance_score") is not None]
    bm = [r["bm25_confidence"] for r in measured if r.get("bm25_confidence") is not None]
    if rel:
        print(f"\n  relevance_score : min {min(rel):.4f} / med {statistics.median(rel):.4f} / max {max(rel):.4f}")
    if bm:
        print(f"  bm25_confidence : min {min(bm):.4f} / med {statistics.median(bm):.4f} / max {max(bm):.4f}")
    srcs: dict = {}
    for r in measured:
        srcs[r["arbitration_source"]] = srcs.get(r["arbitration_source"], 0) + 1
    print(f"  arbitration_source distribution: {srcs}")

    print(f"\n  MULTI-STATUTE CONTROL: named={multi['named']!r} (must be None), "
          f"statutes in evidence={len(multi['statutes_in_evidence'])}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--trials", type=int, default=10)
    p.add_argument("--out", default=None)
    p.add_argument("--max-attempts", type=int, default=15,
                   help="hard ceiling on attempts; guards quota when a provider is failing")
    p.add_argument("--delay", type=float, default=20.0,
                   help="seconds between trials; paces around provider rate limits")
    a = p.parse_args()
    asyncio.run(main(a.trials, a.out, a.delay, a.max_attempts))
