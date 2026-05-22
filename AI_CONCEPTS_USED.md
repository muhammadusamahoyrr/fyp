# Backend AI Flow & Concepts - Attorney AI

This document outlines the backend AI architecture and the specific AI concepts utilized in the Attorney AI chatbot, based on the implementation in the `backend/app/ai` and `backend/app/websockets` modules.

## 1. Entry Point: WebSocket & Intent Classification
**Location**: `backend/app/websockets/chat_socket.py`
The chatbot communicates with the frontend via WebSockets. When a user sends a message, it doesn't immediately hit the heavy AI graph. 
- **NLU Intent Classification**: The system first uses a fast Natural Language Understanding (NLU) classifier (`intent_classify`) to determine the user's intent. 
- **Short-Circuit Routing**: If the intent is simple (e.g., `format_brief`, `affirm`, `stop`), it bypasses the complex LangGraph execution and responds immediately. This saves LLM costs and reduces latency.

## 2. Core Orchestration: LangGraph State Machine
**Location**: `backend/app/ai/graph/supervisor.py` & `backend/app/ai/graph/state.py`
The primary AI flow is managed by **LangGraph**, which defines a stateful, cyclical graph of AI agents (nodes). The system maintains a global `AgentState` containing the query, conversational history, retrieval scores, and convergence attempts.

### The 9-Node Graph Architecture:
1. **Classifier Node (`classifier_node`)**: A fast, keyword-based pass (no LLM cost) to identify the legal domain.
2. **Triage Node (`triage_node`)**: Acts as a gatekeeper. It checks if the query is off-topic (gibberish), if it's missing critical information, or if it's ready for processing.
3. **Clarification Node (`clarification_node`)**: Uses LangGraph's `interrupt()` feature to pause the graph execution and ask the user for missing details (Human-in-the-loop).
4. **Fact Gap Node (`fact_gap_node`)**: Analyzes the known facts versus the missing facts required to answer the legal query.
5. **Retrieval Node (`retrieval_node`)**: The RAG (Retrieval-Augmented Generation) engine that fetches relevant legal statutes and precedents from the vector database.
6. **Retrieval Grader Node (`retrieval_grader_node`)**: Evaluates the retrieved documents. If the relevance is poor and the retry budget allows, it loops back to the Retrieval Node.
7. **Generation Node (`generation_node`)**: Synthesizes the final answer using the retrieved context.
8. **Hallucination Node (`hallucination_node`)**: A self-reflection node that checks if the generated answer is firmly grounded in the retrieved facts. If it hallucinates, it loops back to Generation.
9. **Finalizer Node (`finalizer_node`)**: Packages the output, citations, and confidence scores for the user.

## 3. Key AI Concepts Utilized

### A. Agentic Orchestration (LangGraph)
The system moves beyond simple sequential chains to an agentic state machine. It uses conditional edges (`route_after_grader`, `route_after_hallucination`) to create loops, allowing the AI to retry tasks if quality thresholds aren't met.

### B. Retrieval-Augmented Generation (RAG)
The core knowledge mechanism. Instead of relying purely on the LLM's internal knowledge, it fetches real legal documents (statutes, case law) to anchor the response.

### C. Self-Reflection & Evaluation (Graders)
The AI grades its own work:
- **Retrieval Grader**: Prevents garbage-in, garbage-out by verifying context quality.
- **Hallucination Grader**: Ensures the LLM doesn't invent legal facts, forcing it to rewrite if it strays from the provided text.

### D. Human-in-the-Loop (HITL)
Using LangGraph's `interrupt()`, the AI can dynamically pause its backend processing, send a clarification question to the user, wait for the response, and then resume the graph exactly where it left off.

### E. Hybrid Search & Reranking
The `AgentState` reveals fields like `bm25_confidence`, `signal_variance`, and `reranked_chunks`. This indicates the system uses a combination of dense vector embeddings (semantic search) and sparse retrieval (BM25 keyword search), followed by a reranker to optimize context relevance.

### F. Multi-Tiered Routing
By combining a lightweight NLU classifier before the graph, and a fast heuristic classifier as the first node of the graph, the system optimizes latency and cost, reserving the heavy LLM generation strictly for complex reasoning tasks.
