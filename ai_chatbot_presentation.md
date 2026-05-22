# AI Chatbot Module — Presentation Reference

## What It Does (One Line)
A real-time WebSocket-based legal AI chatbot grounded in Pakistani law (PPC, CrPC, MFLO, Constitution) that classifies intent, routes through a multi-node LangGraph pipeline, retrieves relevant statutes, generates cited answers, and escalates to lawyer matching when the AI reaches its limit.

---

## User Experience

- User opens Chat tab → WebSocket connects automatically
- Greeting shows user's real name + time-of-day (Good Morning / Afternoon / Evening)
- User types or speaks their legal question
- AI responds with: answer + law citations (e.g., "PPC §302") + confidence score
- If AI cannot answer confidently → shows matched lawyers with "Book Consultation" button
- History sidebar shows past queries for quick re-use
- Language toggle EN / UR sends messages in English or Urdu pipeline

---

## Frontend

**File:** `frontend/src/components/client/ModChatbot.jsx`

### WebSocket Connection
- Connects to `ws://localhost:8000/ws/chat/{session_id}?token={JWT}`
- Session ID: `crypto.randomUUID()` per component mount — unique conversation per tab
- Status indicator dot: 🟢 connected / 🟡 connecting / 🔴 disconnected

### Auto-Reconnect with Exponential Backoff
```
Disconnect → wait 1s → retry 1
Disconnect → wait 2s → retry 2
Disconnect → wait 4s → retry 3
Disconnect → wait 8s → retry 4
Disconnect → wait 16s → retry 5 (max)
```
- Retry count resets only after **10 seconds of stable connection** (not on `onopen` — that caused an infinite loop bug)
- `retryCount.current = 99` on unmount to stop the loop cleanly

### Voice + WebSocket Conflict Fix
**Problem:** Chrome drops WebSocket when `SpeechRecognition` grabs the microphone. This triggered the retry loop → infinite connect/disconnect cycle → input field frozen.

**Fix:**
- `listeningRef` (a ref, not state) mirrors `listening` state for use inside WS closures
- `onclose` checks `if (listeningRef.current) return` — no retry while mic is active
- `rec.onend` triggers a **single** clean reconnect after voice ends
- Input field is **never disabled** — only the Send button is gated on WS status

### Voice Input
- Uses browser `SpeechRecognition` / `webkitSpeechRecognition` API (built-in, no API key)
- Language: `en-US` when EN mode, `ur-PK` when UR mode selected
- Transcript appends to the input field (doesn't replace — user can speak multiple times)
- Pulsing border on mic button while listening
- Falls back to toast: "Voice input not supported" on Safari

### Web Search Toggle
- Pill button in toolbar — highlights when active
- Sends `web_search: true` with the WebSocket message payload
- Backend can route to a web-augmented pipeline when this flag is set

### Message Types Received from Backend
| Type | UI Action |
|---|---|
| `thinking` | Shows 3-dot typing animation |
| `final` | Renders AI answer + law citation badges + confidence % |
| `clarification` | Renders question with "Clarification needed" label + matched lawyer cards |
| `error` | Shows error message with red error icon |

---

## Backend — WebSocket Handler

**File:** `backend/app/websockets/chat_socket.py`

### Connection Lifecycle
```python
1. Token validated (JWT decode) — close 4001 if invalid
2. websocket.accept()
3. Session found or created in MongoDB
4. while True: receive_json() → process → send_json()
5. WebSocketDisconnect → clean exit
```

### Per-Message Processing
```
User message received
        ↓
Persist user message to MongoDB
        ↓
Send { type: "thinking" } → shows typing dots in UI
        ↓
Check for pending HITL interrupt (graph paused mid-flow)
    YES → resume graph with Command(resume=answer)
    NO  → run NLU intent classification
        ↓
Route by intent (see below)
        ↓
Send { type: "final" | "clarification" | "error" }
        ↓
Persist AI response to MongoDB
```

---

## NLU Intent Classification Pipeline

**Package:** `backend/app/ai/intent/` (9 files)

Runs on **every** user message before the graph. Classifies into 7 intents:

| Intent | Example | Action |
|---|---|---|
| `new_query` | "What is Section 302?" | Full LangGraph pipeline |
| `format_brief` | "Summarize that" / "Give me a shorter answer" | Reformats previous AI response — no graph call |
| `format_detail` | "Explain in more detail" | Graph with `followup_intent = "deepen"` |
| `affirm` | "OK", "I understand", "Thanks" | Canned response, no graph |
| `stop` | "End chat", "Bye", "Stop" | Canned response, no graph |
| `clarify` | Follow-up to AI's clarification question | Resumes interrupted graph |
| `unknown` | Gibberish, off-topic | Full graph (triage node handles) |

### How Classification Works (3-layer)
1. **Command check** — 40+ regex patterns for format/affirm/stop (instant, free)
2. **Embedding similarity** — `fastembed BAAI/bge-small-en-v1.5` cosine score vs intent centroids
3. **LLM confirmation** — only when embedding confidence is MEDIUM (0.60–0.85)

**Confidence levels:**
- HIGH (≥0.85 + margin ≥0.08) → take action directly
- MEDIUM (≥0.60) → confirm with LLM
- LOW (<0.60) → keyword check → LLM → fallback to `new_query`

**Performance:** Regex check is ~0ms. Embedding check is ~5-10ms (ONNX model cached). LLM only called for ~20% of messages.

---

## AI Pipeline — Chat Graph

**File:** `backend/app/ai/graph/supervisor.py` → `chat_graph`

```
User query
    ↓
classifier_node    → keyword scoring → case_type, province inference
    ↓
triage_node        → LLM: language detection, complexity (simple/complex/urgent),
                     gibberish guard, off-topic detection
    ↓
[clarification_node] → if needs_clarification: ask user, pause graph (HITL interrupt)
    ↓
fact_gap_node      → checks if enough facts for a legal answer
    ↓
retrieval_node     → BM25 + semantic search on ChromaDB collections
    ↓
grader_node        → scores relevance of each retrieved chunk (0.0-1.0)
    ↓
generation_node    → Groq Llama-3.3-70B generates answer with citations
    ↓
hallucination_node → verifies answer is grounded in retrieved chunks
                     degrades confidence if hallucination detected
    ↓
finalizer_node     → packages response: answer + citations + confidence + convergence_status
```

### Convergence Status
| Status | Meaning | UI Response |
|---|---|---|
| `converged` | Answer grounded, confidence ≥ threshold | Normal answer shown |
| `pending` | First attempt, still processing | Thinking indicator |
| `max_attempts` | Tried 3× but still low confidence | Shows matched lawyers + "AI reached its limit" |

### HITL Interrupt (Human-in-the-Loop)
When the AI needs more information mid-pipeline:
1. Graph **pauses** at `clarification_node` using LangGraph interrupt mechanism
2. Question sent to frontend as `{ type: "clarification", question: "..." }`
3. User answers in the chat
4. Next message resumes the graph with `Command(resume=user_answer)`
5. Graph continues from where it paused

---

## Knowledge Base

| Collection | Contents | Chunks |
|---|---|---|
| `criminal_collection` | Pakistan Penal Code (PPC), Code of Criminal Procedure (CrPC), Police Rules | 1,735 |
| `civil_collection` | Transfer of Property Act, Limitation Act | 396 |
| `family_collection` | Muslim Family Laws Ordinance 1961 (MFLO), Qanun-e-Shahadat | 226 |

**Retrieval strategy:**
- BM25 (keyword) + semantic (multilingual-e5 embeddings) hybrid search
- Collection selected based on `classifier_node` case type
- If case type ambiguous → HYBRID mode searches all collections
- Top-k chunks reranked by relevance score before generation

---

## Lawyer Escalation

When the AI reaches `convergence_status = max_attempts`:
1. Backend calls `match_lawyers_for_case(case_id, top_n=3)` — semantic matching
2. Returns matched lawyer cards inside the chat message
3. "Book Consultation →" button routes to `/lawyers` page (Lawyer Matching module)

```json
{
  "type": "final",
  "content": "Based on your situation...",
  "suggest_lawyer": true,
  "matched_lawyers": [
    { "full_name": "...", "province": "Punjab", "match_score": 0.87, "specializations": ["Family Law"] }
  ]
}
```

---

## LLM Configuration

**File:** `backend/app/ai/llm.py`

| Role | Model | When Used |
|---|---|---|
| Fast LLM | Gemini Flash (free tier via `GEMINI_API_KEY`) | Intent classification, triage, reformatting |
| Slow LLM | Groq `llama-3.3-70b-versatile` | Generation, hallucination check, structured output |
| Fallback | Groq 70B (if no Gemini key) | Fast LLM fallback |

Temperature: 0.1 across all nodes (low creativity, high factual accuracy).

---

## Session Persistence

- Each chat session stored in MongoDB `chat_sessions` collection
- `last_ai_content` reloaded from MongoDB on reconnect → format/reformat shortcuts work even after refresh
- Session ID in URL: `?session_id=UUID` — same conversation resumes on page reload

---

## Data Flow Summary

```
User message (text or voice)
        ↓
WebSocket → chat_socket.py
        ↓
NLU Intent Classifier (regex → embedding → LLM)
        ↓
    ┌───────────────────────────────────┐
    │ Intent shortcuts:                 │
    │  format_brief → _reformat()      │
    │  affirm/stop  → canned response  │
    └───────────────────────────────────┘
        ↓ (new_query / unknown)
LangGraph chat_graph:
    classifier → triage → [clarification] → fact_gap
        → retrieval (ChromaDB) → grader → generation
        → hallucination check → finalizer
        ↓
WebSocket response: { type, content, citations, confidence }
        ↓
Frontend renders: message + citation badges + confidence %
             OR: matched lawyer cards + Book button
```

---

## Key Design Decisions & Why

| Decision | Reason |
|---|---|
| WebSocket (not REST polling) | Real-time streaming response; "thinking" indicator possible; no repeated HTTP overhead |
| NLU shortcuts before graph | Saves ~3-5 seconds and LLM cost for simple follow-ups (affirm, format, stop) |
| Separate fast + slow LLM | Fast LLM for cheap classification tasks; slow (70B) only for legal reasoning and generation |
| HITL interrupt for clarification | LangGraph pauses mid-flow; user provides context; graph resumes — not a new query |
| `listeningRef` (not state) in WS closure | State is stale in closures; ref always has current value — prevents voice breaking WS |
| `retryCount` reset after 10s stable | Resetting on `onopen` caused infinite loop — must confirm stability first |
| Confidence score shown to user | Transparency; warns user when AI is less certain → should consult a lawyer |

---

## Common Questions & Answers

**Q: How does the chatbot know about Pakistani law?**
A: 2,357 chunks from official statutes (PPC, CrPC, MFLO, Transfer of Property Act) stored in ChromaDB. Every answer is retrieved from these documents — not from the LLM's training data alone.

**Q: Can it understand Urdu?**
A: Yes. The triage node detects language (`en`/`ur`). Retrieval uses multilingual-e5 embeddings that support Urdu. The generation prompt is language-aware. Voice input uses `ur-PK` locale for the Speech Recognition API.

**Q: What if the AI gives wrong legal advice?**
A: Every response includes a disclaimer: "Informational only — not legal advice. Verify with a qualified Pakistani lawyer." The confidence score also signals when the AI is uncertain.

**Q: What is the "convergence status"?**
A: After each generation attempt, a hallucination node checks if the answer is grounded in the retrieved law chunks. If it fails twice (max_attempts), the system stops trying and suggests a real lawyer instead.

**Q: How does the voice input work?**
A: It uses the browser's built-in Web Speech API — no external service or API key needed. The browser transcribes audio locally and returns text, which is placed in the input field.

**Q: What does the web search toggle do?**
A: When enabled, it sends `web_search: true` with the message. This flag is available for the backend to route through a web-augmented pipeline (e.g., search recent case law online). The UI is fully wired; the backend pipeline extension is the next step.
