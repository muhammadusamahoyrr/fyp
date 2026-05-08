                ┌────────────────────────────┐
                │      USER LEGAL QUERY      │
                └─────────────┬──────────────┘
                              │
                              ▼

┌──────────────────────────────────────────────────────────────┐
│ 1. TRIAGE & PLANNER NODE                                    │
│--------------------------------------------------------------│
│ Responsibilities:                                            │
│ • detect language (EN / UR / Roman Urdu)                     │
│ • normalize Urdu/Roman Urdu → standard Urdu                  │
│ • legal vs off-topic classification                          │
│ • initial case-type classification                           │
│ • case_type_confidence scoring                               │
│ • complexity estimation (simple / complex)                   │
│ • detect urgency/risk level                                  │
│ • initialize convergence controller state                    │
│ • initialize retry counters                                  │
│ • build execution plan                                       │
│                                                              │
│ Outputs:                                                     │
│ • language                                                   │
│ • normalized_query                                           │
│ • is_legal                                                   │
│ • case_type                                                  │
│ • case_type_confidence                                       │
│ • complexity                                                 │
│ • planner_route                                              │
└─────────────┬────────────────────────────────────────────────┘
              │
              ├──────────── off-topic ───────────► FINALIZER
              │
              ▼

     ┌───────────────────────────────┐
     │ COMPLEXITY ROUTER EDGE        │
     └─────────────┬─────────────────┘
                   │
         SIMPLE    │    COMPLEX
         FAST PATH │    REASONING PATH
                   │
                   ▼

       ┌───────────────────────────────┐
       │ 2. CONTEXTUAL CLARIFIER NODE  │
       │  (fact_gap_node)              │
       │-------------------------------│
       │ Responsibilities:             │
       │ • detect missing legal facts  │
       │ • use case-type templates     │
       │ • conversation-aware analysis │
       │ • determine answerability     │
       │ • ask targeted questions      │
       │ • evaluate new fact gain      │
       │ • re-classify case type       │
       │   after clarification         │
       │ • convergence monitoring      │
       │                               │
       │ Missing Fact Examples:        │
       │ Criminal:                     │
       │ • injury severity             │
       │ • FIR filed?                  │
       │ • witnesses?                  │
       │                               │
       │ Family:                       │
       │ • marriage status             │
       │ • children involved?          │
       │                               │
       │ Civil:                        │
       │ • written contract?           │
       │ • ownership proof?            │
       │                               │
       │ Outputs:                      │
       │ • needs_clarification         │
       │ • clarification_question      │
       │ • extracted_facts             │
       │ • fact_delta_score            │
       └─────────────┬─────────────────┘
                     │
                     │ insufficient facts
                     ▼

       ┌───────────────────────────────┐
       │ USER CLARIFICATION LOOP       │
       │-------------------------------│
       │ • Flutter UI prompt           │
       │ • collect structured answers  │
       │ • append to conversation      │
       │ • increment clarification     │
       │   attempts                    │
       │ • compare new facts gained    │
       └─────────────┬─────────────────┘
                     │
                     │ convergence?
                     │
                     ├── no new facts
                     │   OR max attempts
                     │         ▼
                     │      HITL
                     │
                     └──── back to
                           CONTEXTUAL
                           CLARIFIER



 SIMPLE PATH ───────────────────────────────────────┐
                                                    │
                                                    ▼

┌──────────────────────────────────────────────────────────────┐
│ 3. HYBRID RETRIEVER NODE                                    │
│--------------------------------------------------------------│
│ Responsibilities:                                            │
│ • BM25 retrieval                                              │
│ • semantic vector retrieval                                   │
│ • multilingual E5 retrieval                                   │
│ • lightweight legal graph expansion                           │
│ • statute/entity linking                                      │
│ • province-aware filtering                                    │
│ • query rewriting                                             │
│ • retrieve prior similar cases                                │
│ • hybrid weighted fusion                                      │
│ • retrieval telemetry tracking                                │
│                                                               │
│ Retrieval Stack:                                              │
│ • BM25 (0.6)                                                  │
│ • Chroma semantic (0.4)                                       │
│ • legal synonym expansion                                     │
│ • statute alias mapping                                       │
│                                                               │
│ Outputs:                                                      │
│ • retrieved_chunks                                            │
│ • retrieval_metadata                                          │
│ • relevance_score                                             │
│ • rewritten_query                                             │
└─────────────┬────────────────────────────────────────────────┘
              ▼

┌──────────────────────────────────────────────────────────────┐
│ 4. RETRIEVAL GRADER NODE (CRAG)                              │
│--------------------------------------------------------------│
│ Responsibilities:                                            │
│ • relevance scoring                                           │
│ • retrieval quality evaluation                                │
│ • answerability checking                                      │
│ • ambiguity detection                                         │
│ • chunk diversity scoring                                     │
│ • convergence monitoring                                      │
│ • compare retrieval improvement                               │
│                                                               │
│ Convergence Controller:                                       │
│ stop retrieval loop if:                                       │
│ • relevance improvement < ε                                   │
│ • same chunks repeatedly returned                             │
│ • rewritten query adds no value                               │
│ • retrieval plateau detected                                  │
│                                                               │
│ Outputs:                                                      │
│ • retrieval_quality                                           │
│ • should_retry_retrieval                                      │
│ • convergence_status                                          │
└─────────────┬────────────────────────────────────────────────┘
              │
              │ low relevance
              ▼

┌──────────────────────────────────────────────────────────────┐
│ RETRIEVAL REFINEMENT LOOP                                    │
│--------------------------------------------------------------│
│ Responsibilities:                                            │
│ • rewrite query using legal terminology                       │
│ • broaden/narrow search                                       │
│ • statute synonym expansion                                   │
│ • increase semantic weight                                    │
│ • retry retrieval                                             │
│ • adaptive search strategy                                    │
│                                                               │
│ Dynamic Loop Exit:                                            │
│ • retrieval convergence reached                               │
│ • no score improvement                                        │
│ • retrieval_attempts exceeded                                 │
└─────────────┬────────────────────────────────────────────────┘
              │
              └────────────── back to NODE 3



 acceptable retrieval
              ▼

┌──────────────────────────────────────────────────────────────┐
│ 5. SYNTHESIS GENERATOR NODE                                  │
│--------------------------------------------------------------│
│ Responsibilities:                                            │
│ • grounded legal reasoning                                    │
│ • IRAC-style generation                                       │
│ • bilingual answer generation                                 │
│ • citation extraction                                         │
│ • procedural guidance generation                              │
│ • confidence scoring                                          │
│ • structured legal explanation                                │
│ • context compression                                         │
│                                                               │
│ Output Structure:                                             │
│ • Overall conclusion                                          │
│ • Applicable laws                                              │
│ • Legal reasoning                                              │
│ • Recommended actions                                          │
│ • Risks / limitations                                          │
│                                                               │
│ Outputs:                                                      │
│ • draft_answer                                                │
│ • confidence                                                   │
│ • cited_sections                                               │
└─────────────┬────────────────────────────────────────────────┘
              ▼

┌──────────────────────────────────────────────────────────────┐
│ 6. HALLUCINATION GUARD NODE                                  │
│--------------------------------------------------------------│
│ Responsibilities:                                            │
│ • NLI-based grounding verification                            │
│ • sentence-level validation                                   │
│ • unsupported-claim detection                                 │
│ • citation verification                                       │
│ • contradiction detection                                     │
│ • hallucination risk scoring                                  │
│ • convergence monitoring                                      │
│                                                               │
│ Convergence Controller:                                       │
│ stop regeneration if:                                         │
│ • hallucination score not improving                           │
│ • same unsupported claims recur                               │
│ • confidence drops repeatedly                                 │
│                                                               │
│ Outputs:                                                      │
│ • is_grounded                                                 │
│ • hallucination_score                                         │
│ • unsupported_claims                                          │
│ • regeneration_needed                                         │
└─────────────┬────────────────────────────────────────────────┘
              │
              │ unsupported claims
              ▼

┌──────────────────────────────────────────────────────────────┐
│ GENERATION REFINEMENT LOOP                                   │
│--------------------------------------------------------------│
│ Responsibilities:                                            │
│ • regenerate with stricter grounding                          │
│ • reduce noisy context                                        │
│ • use top-ranked chunks only                                  │
│ • remove unsupported statements                               │
│ • lower creativity/temperature                                │
│ • retry generation                                            │
│                                                               │
│ Dynamic Loop Exit:                                            │
│ • hallucination convergence                                   │
│ • no grounding improvement                                    │
│ • generation_attempts exceeded                                │
└─────────────┬────────────────────────────────────────────────┘
              │
              └────────────── back to NODE 5



 grounded answer
              ▼

┌──────────────────────────────────────────────────────────────┐
│ 7. FINALIZER & AUDITOR NODE                                  │
│--------------------------------------------------------------│
│ Responsibilities:                                            │
│ • attach citations                                            │
│ • hyperlink statute references                                │
│ • confidence formatting                                       │
│ • legal disclaimer                                            │
│ • prompt leakage removal                                      │
│ • PII scrubbing                                               │
│ • CNIC masking                                                │
│ • phone number masking                                        │
│ • Flutter-ready response formatting                           │
│ • markdown cleanup                                            │
│ • audit metadata logging                                      │
│                                                               │
│ Security Layer:                                               │
│ • remove hidden prompts                                       │
│ • redact sensitive identifiers                                │
│ • sanitize unsafe output                                      │
│                                                               │
│ Final Output:                                                 │
│ • clean_answer                                                │
│ • citations                                                   │
│ • confidence                                                  │
│ • disclaimer                                                  │
└─────────────┬────────────────────────────────────────────────┘
              ▼

┌──────────────────────────────────────────────────────────────┐
│ HUMAN-IN-THE-LOOP BREAKPOINT                                 │
│--------------------------------------------------------------│
│ Triggered when:                                               │
│ • retrieval convergence fails                                 │
│ • hallucination convergence fails                             │
│ • clarification adds no new facts                             │
│ • confidence too low                                          │
│ • contradictory legal evidence                                │
│                                                               │
│ Response:                                                     │
│ "Unable to confidently verify this legal scenario.            │
│ Would you like to:                                            │
│ • refine your query                                           │
│ • provide more details                                        │
│ • connect with a lawyer?"                                     │
└─────────────┬────────────────────────────────────────────────┘
              ▼

        ┌──────────────────────────┐
        │   FINAL LEGAL ANSWER     │
        └──────────────────────────┘ 


Flag 1 — Simple path missing fact_gap
Your diagram shows Simple path skips directly to retrieval. But a simple query can still have missing facts.
Fix: Simple path = skip clarification loop BUT still run fact_gap check once (no loop, just single check). 
Flag 2 — NLI-based grounding = separate model
You have "NLI-based grounding verification" in hallucination node. Real NLI needs cross-encoder/nli-deberta-v3 — another 400MB model.
For FYP = LLM-based grounding check is fine. In report write: "NLI-based verification planned as future enhancement."

Flag 3 — Legal graph expansion not built yet
"Lightweight legal graph expansion" in retrieval node — you don't have a knowledge graph. Remove from v1 or mark as future.