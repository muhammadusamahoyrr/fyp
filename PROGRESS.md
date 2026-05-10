PHASE 1 — CODE AUDIT (Check Every File You Just Generated)
For each file, check:

Any silent failures (bare except, missing null checks, unhandled edge cases)
Pydantic v2 violations (field validators, model_config vs Config class)
LangGraph v1.0 breaking changes (interrupt() usage, state updates, conditional edges)
lru_cache misuse (mutable arguments, stale cache across requests)
Any place that could return wrong case_type silently
Any node that could crash the entire graph instead of gracefully degrading

Report as:
FILE: filename.py
ISSUE: what is wrong
SEVERITY: critical / high / medium / low
FIX: exact code fix

PHASE 2 — PIPELINE FLOW AUDIT
Trace these 5 real user scenarios through the entire graph and identify where each one breaks or gives wrong output:

"mujhe police ne mara" (Roman Urdu, criminal, no province mentioned)
"My landlord won't return my deposit" (civil, ambiguous province)
"need briefly" (follow-up formatting instruction, not a new query)
"My brother stole my father's property after he died" (ambiguous — criminal AND civil overlap)
Empty message or gibberish: "asdfgh"

For each scenario show:
SCENARIO: [query]
EXPECTED FLOW: node1 → node2 → node3
ACTUAL FLOW: node1 → node2 → [BREAKS HERE]
ROOT CAUSE: why
FIX: what to change

PHASE 3 — PAKISTANI LEGAL EDGE CASES
Check if the pipeline correctly handles these Pakistan-specific situations that generic RAG systems miss:

Urdu statute names — e.g. user writes "دفعہ 302" instead of "PPC 302" — does BM25 match it?
Roman Urdu legal terms — "qatal", "chor", "talaq", "kiraya" — are these in keyword maps?
Province inference — user says "Lahore" or "Karachi" — does province get set correctly?
Overlapping jurisdiction — Federal law vs Punjab law on same topic — does retrieval cover both?
FIR vs Civil suit same incident — e.g. bounced cheque (both PPC 489-F and civil recovery) — does hybrid retrieval trigger?
Missing statutes — if a query needs a statute not in ChromaDB — does system say so or hallucinate?

For each: HANDLED / NOT HANDLED / PARTIALLY HANDLED + fix if needed.

PHASE 4 — PRODUCTION READINESS CHECKLIST
Check these production concerns and give status + fix for any that are missing:

 WebSocket disconnects mid-generation — does graph state get saved or lost?
 Concurrent users — does lru_cache on BM25 cause race conditions?
 ChromaDB collection missing — does system crash or degrade gracefully?
 LLM API timeout / rate limit — does graph retry or crash?
 JWT expiry mid-conversation — is session state preserved?
 Very long user message (5000+ chars) — does triage/classifier handle it?
 User sends same query 10 times — does caching work correctly?
 Answer with 0 retrieved chunks — does grader catch it or LLM hallucinate?

Report as:
CHECK: item
STATUS: pass / fail / partial
RISK: what happens if ignored
FIX: exact solution

FINAL OUTPUT:
After all 4 phases, give me:

A priority-ordered fix list (critical fixes first)
Any files that need to be regenerated completely
3 things my pipeline does well that I should NOT change
The single biggest architectural risk remaining after all fixes