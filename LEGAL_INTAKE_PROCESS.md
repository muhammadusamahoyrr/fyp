# Legal Intake Backend AI Process - Attorney AI

This document details the specialized AI pipeline used for the **Legal Intake** process, which converts unstructured user queries into formal, structured case analyses.

---

## 1. Process Overview
The Legal Intake process is implemented as a dedicated **StateGraph** in the backend. Unlike the general chat flow, the intake pipeline is optimized for **accuracy**, **grounding**, and **structured data extraction**.

### The Intake Graph Architecture (By the Numbers):
- **Total LangGraph Nodes:** 4
- **Total AI Logic Steps:** 5 (including conditional routing)
- **Standard LLM Calls:** 4 calls per session
- **Maximum LLM Calls:** 6 calls (in case of retrieval retry)

### The Intake Graph Flow:
`Retrieval` → `Quality Grading` → `Structured Extraction` → `Grounding Validation` → `Final Case Analysis`

---

## 2. Phase 1: High-Precision Retrieval
The process begins with the `retrieval_node`, using the same **Two-Hop strategy** as the main chatbot:
1.  **Semantic Search:** Rewriting the user's issue into formal Pakistani legal terminology.
2.  **Citation Search:** Automatically fetching statutes mentioned in cross-references within the first set of results.

---

## 3. Phase 2: The Quality Gate (`retrieval_grader_node`)
Before proceeding to analysis, the system evaluates the "Search Quality":
- **Relevance Score:** If the relevance of retrieved laws is below **0.4**, the system automatically triggers a **Retry**.
- **Expansion:** During the retry, the system weaves "Known Facts" extracted during the conversation into the search query to force better context matching.

---

## 4. Phase 3: Structured Case Extraction (`intake_node`)
Once high-quality context is obtained, the `intake_node` uses a specialized LLM prompt to transform the data into a formal legal document.

### Output Schema (JSON):
- **Summary:** A one-paragraph executive summary of the legal situation.
- **Applicable Laws:** A specific list of Pakistani statutes (e.g., "PPC Section 302 — Punishment for murder").
- **Recommended Actions:** A list of 3-5 practical, immediate steps the client should take (e.g., "File an FIR at the local police station," "Send a legal notice via registered post").
- **Risk Level:** A categorized assessment (`low`, `medium`, `high`).

---

## 5. Phase 4: The Grounding Guard (`intake_hallucination_node`)
To ensure the advice is legally sound, a dedicated **Grounding Guard** performs a final audit of the recommended actions.

- **Action Verification:** The LLM independently verifies every recommended action against the specific text of the retrieved law chunks.
- **Safety Disclaimer:** If the guard identifies an action that isn't explicitly supported by the retrieved law, it does NOT delete the action. Instead, it automatically appends a **Legal Caution** to the summary:
  > *"Note: some recommended actions could not be fully verified against the retrieved law sections — please confirm with a qualified Pakistani lawyer."*

---

## 6. Service-Layer Intelligence (Beyond the Graph)
The Legal Intake process includes several advanced features implemented in the service layer (`intake_service.py`):

### A. Automatic Case Type Correction
The system does not blindly trust the user's selection. During conversion, the AI performs a **Double-Classification Pass**:
1. It uses a fast keyword classifier to guess the case type.
2. If the description is ambiguous, it uses a high-reasoning LLM pass.
If the user selected "Civil" but the AI detects "Criminal," it **automatically corrects** the case type to ensure the correct laws are retrieved and the right lawyers are matched.

### B. Parallel Background Processing
To ensure a fast user experience, the system triggers two "non-blocking" background tasks immediately upon case creation:
- **Semantic Embedding (P1):** Generates a 768-dimensional vector of the case description using the `multilingual-e5-base` model.
- **Auto-Lawyer Matching (P5):** Automatically runs the matching algorithm to find the **top 5 lawyers** in the background, so the list is ready the moment the user opens their dashboard.

### C. Multi-Round AI Clarification
The intake includes a specialized "Clarification Engine" that can run for up to **4 rounds** of interactive Q&A. It identifies the "most critical missing fact" for a specific domain (Criminal, Family, etc.) and asks the user in their own language (English/Urdu) before the final analysis is even started.

---

## 6. Presentation Highlights (Key Selling Points)
For your presentation, you can emphasize these unique architectural benefits:
- **Zero-Tolerance for Hallucination:** The double-check between the `intake_node` and `intake_hallucination_node` ensures recommendations are rooted in actual statutes.
- **Standardized Output:** Every intake produces a consistent, professional report that can be used by both the user and a potential lawyer.
- **Automated Risk Assessment:** The system proactively flags the "Risk Level," helping users understand the severity of their legal position instantly.
- **Bilingual Grounding:** The system correctly maps Roman Urdu descriptions to formal Urdu/English statutes during the extraction phase.
