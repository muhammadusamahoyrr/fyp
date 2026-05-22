# Backend AI Deep Dive - Attorney AI

This document provides a highly detailed technical breakdown of the Attorney AI backend architecture, orchestration logic, and the advanced AI concepts that power the legal chatbot.

---

## 1. Multi-Stage Pipeline Architecture
The system uses a "Fast-Path/Slow-Path" architecture to optimize for cost, latency, and accuracy, backed by a production-grade resilience layer.

### A. The "Fast-Path" (Intent Classification)
Before the heavy LangGraph orchestration starts, `backend/app/websockets/chat_socket.py` performs a lightweight NLU pass:
- **Intent Detection:** Recognizes simple actions like `affirm` (yes/ok), `stop`, or `format_brief` (summarize the previous answer).
- **Shortcut Routing:** If a simple intent is detected, it responds with a "Canned Response" or uses a fast LLM call for formatting, bypassing the 9-node graph entirely.

### B. Resilience & Integrity (`llm_circuit.py`)
To handle production failures, the system implements:
- **LLM Circuit Breaker:** Detects API failures (5 errors in 60s) and enters an `OPEN` state, fast-failing subsequent requests to prevent cascading latency.
- **WAL (Write-Ahead Log):** Ensures data integrity. It writes a log entry *before* any database write, allowing for atomic operations and robust session cancellations.

### B. The "Slow-Path" (LangGraph Orchestration)
If the query is a new legal question, it enters the **9-node State Machine** defined in `backend/app/ai/graph/supervisor.py`.

---

## 2. Phase 1: Zero-LLM Fast Triage (`classifier_node.py`)
To minimize LLM tokens, the first node is a regex-based classifier.

- **Signal Tables:** Uses pre-compiled regex patterns to score the query across four domains:
  - **Criminal:** (FIR, murder, theft, PPC 302, CrPC, etc.)
  - **Civil:** (Property, tenant, rent, mortgage, CPC, etc.)
  - **Family:** (Divorce, talaq, nikaah, custody, dower, etc.)
  - **Constitutional:** (Fundamental rights, Supreme Court, writ, etc.)
- **Bilingual Support:** Includes signals for both **English** and **Urdu (Native Script)** (e.g., قتل, طلاق, وراثت).
- **Province Inference:** Automatically maps major city names (Lahore -> Punjab, Karachi -> Sindh) to the correct jurisdiction without an LLM.
- **Routing Decision:** 
  - Confidence > 0.85: Go straight to retrieval.
  - Confidence < 0.15: Set `HYBRID` routing mode to search all law collections.

---

## 3. Phase 2: Intelligent Triage & Intent Detection (`triage_node.py`)
If the regex pass is ambiguous, an LLM (Gemini Flash or Groq 70B) performs a deeper analysis.

- **Gibberish Filter:** Uses word density checks to catch random character input.
- **Structured Triage:** Categorizes the query into `legal`, `off_topic`, or `gibberish`.
- **Transliteration:** If the user writes in **Roman Urdu** (Urdu words in English letters), the LLM normalizes it into standard Urdu script for better retrieval.
- **Urgency & Complexity:** Assigns scores (Critical/High/Low) and (Simple/Complex) to help the finalizer prioritize steps.

---

## 4. Phase 3: Advanced Legal RAG (`retrieval_node.py`)
Attorney AI uses a "Two-Hop" retrieval strategy to ensure maximum legal context.

- **Query Normalization:** Automatically corrects user confusion between Indian and Pakistani laws (e.g., "Section 302 IPC" is corrected to "Section 302 PPC").
- **Hop 1 (Semantic Search):** The LLM rewrites the user's natural language into formal legal terminology (e.g., "someone hit my car" -> "rash driving, property damage, section 279 PPC").
- **Hop 2 (Cross-Reference Search):** The system parses the results of Hop 1 for statute citations (e.g., "See CrPC 154") and automatically performs a second search for those specific sections.
- **Reciprocal Rank Fusion (RRF):** Merges results from all hops, deduplicating chunks while boosting documents that appear in multiple search passes.

---

## 5. Phase 4: IRAC Generation (`generation_node.py`)
The response follows the standard legal **IRAC** (Issue, Rule, Application, Conclusion) framework.

- **Structure:**
  - **Issue:** The core legal question.
  - **Applicable Law:** Specific sections cited from the context.
  - **Legal Analysis:** Applying the law to the user's facts.
  - **Conclusion & Recommended Actions:** Clear next steps for the user.
- **Grounding Constraints:** The system is strictly instructed to cite ONLY sections provided in the context to prevent legal hallucinations.
- **Confidence Scoring:** The LLM outputs a self-assessment score at the end of the response.

---

## 6. Phase 5: Self-Correction & Convergence
The graph contains feedback loops to ensure quality:

- **Retrieval Grader:** Evaluates if the retrieved chunks are actually relevant to the query. If score < 0.5, it triggers a retry with "Known Facts" added to the query.
- **Hallucination Grader:** Compares the generated answer against the source chunks. If the answer contains information not found in the source, it flags it for regeneration.
- **State Persistence:** Uses LangGraph's `MemorySaver` to track the `retrieval_attempts` and `generation_attempts`, preventing infinite loops.

---

## 7. Phase 6: Human-in-the-Loop (HITL)
When the system lacks data to answer, it uses stateful interrupts.

- **Clarification Node:** If information is missing, the graph calls `interrupt()`.
- **Execution Pause:** The backend sends the question to the frontend and stops execution.
- **Stateful Resume:** When the user replies, the `chat_socket` resumes the graph exactly at the `fact_gap_node`, keeping all previous context and retrieval data intact.

---

## 8. Advanced Engineering & AI Monitoring

### A. Additive Three-Signal Scoring (`scoring.py`)
Instead of relying on a single retrieval score, the system calculates a weighted confidence for every chunk:
1. **Keyword Signal (40%):** Density of Pakistani legal terms (PPC, FIR, etc.).
2. **Embedding Signal (35%):** Semantic similarity from the vector database.
3. **LLM Signal (25%):** Direct relevance grade from a fast LLM pass.
- **Variance Penalty:** If these three signals disagree significantly, a penalty is applied to the final score to ensure precision over recall.

### B. Statistical Calibration (`calibration.py`)
To ensure scores are meaningful, raw outputs are passed through calibration models:
- **Platt Scaling:** Maps LLM outputs to probability space.
- **Isotonic Regression:** Corrects BM25 keyword search scores.
- **PSI (Population Stability Index):** Monitors for **Data Drift**. If the statistical distribution of user queries shifts (e.g., a sudden surge in new terminology), the system flags a warning for recalibration.

### C. Adaptive Threshold Management (`threshold_manager.py`)
Thresholds (like the minimum score to show a result) are not hard-coded:
- **Percentile-Based:** Thresholds are derived from the rolling p10/p25/p90 percentiles of historical data.
- **Warmup Period:** The system uses "Seed" values for the first 1000 queries before switching to data-driven adaptive thresholds.
- **Coverage Ratio:** Automatically adjusts weights based on the ratio of labeled to unlabeled query data.

### D. Semantic Cache Validation (`cache.py`)
A two-stage caching system ensures users get fast answers without stale data:
- **Version Tagging:** Every cache entry is tagged with the **Embedding Model Version**, **Chunking Strategy**, and **Collection Hash**.
- **Instant Invalidation:** If even one new statute is ingested into a collection, the collection hash changes, instantly invalidating all related cache entries without waiting for a TTL.

---

## 9. Strategic Decision Making & Domain Expertise

### A. Utility-Based Arbitration (`decision_engine.py`)
Instead of a simple "if/else" logic, the system uses a **Decision Engine** to select the optimal path:
- **Action Utility:** For every query, the system calculates the "Utility" of three potential actions: `answer`, `refuse`, or `defer` (retry/ask for info).
- **The Formula:** `Utility = Calibrated Confidence / Cost Weight`. By assigning different "costs" to errors (refusing a valid question vs answering a wrong one), the AI can make a strategic choice that minimizes legal risk.
- **Binary Convergence:** After two consecutive attempts to "defer" (clarify), the system enters "Binary Mode," forcing itself to either answer or refuse to prevent the user from getting stuck in an infinite loop.

### B. Domain-Specific Fact Mapping (`fact_gap_node.py`)
The AI contains specialized templates for Pakistani legal domains that guide its intake process:
- **Criminal:** Prioritizes FIR status, nature of harm, and relationship of parties.
- **Family:** Prioritizes marriage registration under the *Muslim Family Laws Ordinance 1961*, children's ages, and *Mehr* (dower) details.
- **Civil:** Prioritizes contract registration and limitation periods.
- **Constitutional:** Prioritizes specific Fundamental Rights violations and government authority identification.

### C. Structural Integrity Guards
To ensure the high quality of legal advice, the system implements a strict **Minimum Information Floor**. It will automatically pause the search process if the user's query lacks:
1. A identified **Province**.
2. A high-confidence **Case Type**.
3. A meaningful **Description** (at least 12 words).
4. At least two concrete **Factual Statements**.
This ensures that "Retrieved-Augmented Generation" (RAG) always has high-quality input, preventing vague or generic legal advice.

---

## 10. Lawyer Matching Engine (`lawyer_service.py`)

### A. Multi-Factor Match Scoring
When the AI reaches its limit and suggests a lawyer, it uses a weighted scoring algorithm to find the best professional for your specific case:
- **Semantic Profile Match (50%):** Vector similarity between your case description and the lawyer's past experience.
- **Domain Specialization Boost (20%):** A strategic boost if the lawyer is an expert in your specific case type (e.g., Family, Criminal).
- **Client Rating (15%):** Weighted score based on verified user reviews.
- **Availability (10%):** Prioritizes lawyers who are currently online/available.
- **Experience Depth (5%):** Seniority-based boost for lawyers with over 5-20 years of experience.

### B. Smart Geocoding & Visual Jitter
To ensure a high-quality Map View on the frontend:
- **Province Fallback:** If a lawyer has not set a precise GPS location, the system automatically geocodes them to the center of their province.
- **Deterministic Jitter:** To prevent multiple lawyers from appearing as a single dot on the map, the system applies a **Mathematical Jitter** (offset) based on their unique User ID. This ensures every lawyer is individually visible while still correctly located in their province.
