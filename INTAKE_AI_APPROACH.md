# Attorney.AI — AI Pipeline: Complete Approach, Flow & Viva Reference
> SP23-BCS-069 | Muhammad Usama | May 2026

---

## Quick Navigation (for viva)

| Topic | Section |
|-------|---------|
| Knowledge base ingestion pipeline | Part 1 |
| Why hybrid retrieval (BM25 + semantic) | Part 2 |
| Query expansion — how plain language becomes legal search | Part 2D |
| LangGraph — two graphs, AgentState | Part 3 |
| Intake flow (POST /convert) | Part 4 |
| Chat flow (WebSocket) | Part 5 |
| Node design decisions | Part 6 |
| LLM factory (Groq / Gemini / Ollama) | Part 7 |
| All key design decisions in one table | Part 8 |
| Challenges faced & how they were solved | Part 9 |
| File map | Part 10 |
| Anticipated viva questions + answers | Part 11 |

---

## Part 1 — Knowledge Base Pipeline (One-Time Setup)

Before any AI can run, Pakistani law PDFs must be ingested into ChromaDB. This is a **one-time offline process**.

### PDFs Used

| File | Collection |
|------|-----------|
| `PAKISTAN PENAL CODE.pdf` | `criminal_collection` |
| `Code_of_criminal_procedure_1898.pdf` | `criminal_collection` |
| `Police Law.pdf` | `criminal_collection` |
| `TRANSFER PROPERTY Act.pdf` | `civil_collection` |
| `2-limitation-act-1908-pdf.pdf` | `civil_collection` |
| `Muslim-Family-Laws-Ordinance-1961.pdf` | `family_collection` |
| `qanun-e-shahadat-order-1984.pdf` | `family_collection` |

### 4-Script Pipeline

```
raw PDFs
   ↓ pipeline/ingest.py    → pdfplumber extracts text page-by-page  → processed/text/
   ↓ pipeline/chunk.py     → legal-aware section splitting           → processed/chunks/
   ↓ pipeline/embed.py     → 768-dim multilingual vectors            → processed/embedded/
   ↓ pipeline/store.py     → upsert into ChromaDB collections        → backend/chroma_data/
```

#### Step 1 — ingest.py
- Tool: `pdfplumber` (handles scanned PDF layouts better than PyPDF2)
- Extracts text page-by-page, concatenates into one `.txt` per PDF
- Writes `processed/manifest.json` — a registry of all files used by subsequent steps

#### Step 2 — chunk.py
- **Section-aware splitting**: regex detects boundaries like `Section 302`, `S.302(a)`
- Keeps each legal section as one chunk — preserves clause hierarchy
- **Sliding window fallback**: 800 chars with 100-char overlap for oversized sections
- Each chunk carries metadata:

```python
{
  "chunk_id":       "ppc_1860_a3f9b2c1",   # unique ID for Chroma upsert
  "content":        "...",                  # full section text
  "section_number": "302",
  "statute":        "PPC 1860",
  "law_type":       "criminal",
  "province":       "federal",
  "source_file":    "PAKISTAN PENAL CODE.pdf",
}
```

#### Step 3 — embed.py
- Model: `intfloat/multilingual-e5-base` (768-dim, supports Urdu + English)
- Batch size: 64 chunks per inference call
- **Required prefix convention** (e5 model contract):
  - Documents: `"passage: " + chunk_text`
  - Queries:   `"query: " + query_text`
- Saves embeddings inline with chunk dicts to `processed/embedded/`

#### Step 4 — store.py
- Connects to `chromadb.PersistentClient` at `backend/chroma_data/`
- Creates 6 collections if not present (`hnsw:space: cosine` for cosine similarity)
- Upserts using `chunk_id` as document ID — safe to re-run (idempotent)
- Special mapping: both `supporting/` PDFs → `family_collection` (not `civil`)

**Final result:**

| Collection | Chunks |
|------------|--------|
| `criminal_collection` | 1,735 |
| `civil_collection` | 396 |
| `family_collection` | 226 |
| **Total** | **2,357** |

---

## Part 2 — Hybrid Retrieval System

When a query arrives, **two retrieval methods run in parallel** and are merged.

### A. Why Hybrid (BM25 + Semantic)?

| Query Type | BM25 (keyword) | Semantic (vector) | Winner |
|-----------|---------------|-------------------|--------|
| `"Section 302 PPC"` | ✅ exact statute match | ❌ may miss exact ref | BM25 |
| `"my landlord beat me"` | ❌ no keyword overlap with law text | ✅ finds assault sections by meaning | Semantic |
| `"FIR kaise darj karein"` (Urdu) | ❌ | ✅ multilingual embeddings | Semantic |
| **Both combined** | **best of both worlds** | | |

Pakistani law is **statute-reference-heavy** (`PPC S.302`, `CrPC 497`) → BM25 is essential.  
User queries are in **plain language** → semantic is also essential.  
Solution: **EnsembleRetriever** with weighted rank fusion.

### B. EnsembleRetriever — Weights

```python
EnsembleRetriever(
    retrievers=[bm25_retriever, chroma_retriever],
    weights=[0.6, 0.4]   # BM25 heavier — statute refs are keyword matches
)
```

Weight source: `nilsjennissen/langgraph` recommendation for legal text retrieval.

### C. BM25 Retriever

```python
@lru_cache(maxsize=6)
def _bm25(collection_name: str) -> BM25Retriever:
    col = get_chroma().get_collection(collection_name)
    result = col.get(include=["documents", "metadatas"])
    docs = [Document(page_content=text, metadata=meta) for ...]
    return BM25Retriever.from_documents(docs, preprocess_func=word_tokenize, k=10)
```

- Loads all chunks from ChromaDB into memory as LangChain Documents
- `@lru_cache(maxsize=6)` — BM25 index is expensive to build, built once per collection then reused

### D. Query Expansion (Chat Only) — Critical for Plain-Language Queries

**Problem discovered in production:** User types `"My landlord beat me up"` but PPC uses `"criminal force"`, `"assault"`, `"causing grievous hurt"`. BM25 finds zero keyword matches.

**Solution:** `retrieval_node` rewrites the query into legal terminology before BM25 search:

```python
_REWRITE_PROMPT = """Rewrite the following user query into a concise legal search query
using formal Pakistani legal terminology (PPC, CrPC, statute names, section topics).
Output ONLY the rewritten query."""

def _expand_query(query: str) -> str:
    rewritten = llm.invoke([system_prompt, user_query]).content.strip()
    return f"{query} {rewritten}"   # original + expanded = better recall from both retrievers
```

**Example:**
- Input:  `"My landlord beat me up"`
- Expanded: `"My landlord beat me up PPC assault causing hurt criminal force grievous hurt section"`
- Result: BM25 now finds PPC Section 325 (causing grievous hurt), Section 335

### E. Semantic (Chroma) Retriever

```python
store = Chroma(client=get_chroma(), collection_name=..., embedding_function=E5Embeddings())
retriever = store.as_retriever(search_kwargs={"k": 10, "filter": province_filter})
```

Province filter (ready for v2 provincial law expansion):
```python
{"$or": [{"province": {"$eq": case_province}}, {"province": {"$eq": "federal"}}]}
```

### F. E5 Embedding Class

```python
class E5Embeddings(HuggingFaceEmbeddings):
    def embed_documents(self, texts):
        return super().embed_documents(["passage: " + t for t in texts])
    def embed_query(self, text):
        return super().embed_query("query: " + text)

@lru_cache(maxsize=1)
def _embeddings() -> E5Embeddings:
    return E5Embeddings(model_name="intfloat/multilingual-e5-base", ...)
```

`@lru_cache(maxsize=1)` — model is 1.1 GB, loaded once on first request and reused for the lifetime of the server process.

---

## Part 3 — LangGraph AI Pipeline

### Two Graphs

| Graph | Endpoint | Flow |
|-------|----------|------|
| `intake_graph` | `POST /intake/{token}/convert` | retrieval → intake_node → END |
| `chat_graph` | `WS /ws/chat/{session_id}` | gatekeeper → retrieval → [clarification \| generation → hallucination] → END |

Both graphs share the same `retrieval_node` and the same `AgentState`.

### AgentState — Shared State TypedDict

```python
class AgentState(TypedDict):
    query: str                    # incident_description (intake) or user message (chat)
    session_id: str               # intake token or WebSocket session ID
    case_id: str | None
    case_type: str                # civil | criminal | family | constitutional
    province: str                 # punjab | sindh | kpk | balochistan | federal
    language: str                 # en | ur
    needs_clarification: bool
    clarification_question: str
    retrieved_chunks: list[dict]
    reranked_chunks: list[dict]
    relevance_score: float        # < 0.75 triggers clarification branch
    answer: str
    citations: list[dict]
    confidence: float             # LLM self-reported 0.0–1.0
    is_grounded: bool
    messages: Annotated[list[BaseMessage], operator.add]  # append-only reducer
```

The `messages` field uses `operator.add` as a LangGraph reducer — each new invocation appends to the history rather than replacing it. This gives the chat graph persistent memory across messages.

---

## Part 4 — Intake Graph (convert_to_case flow)

### Trigger Point

```
Client completes 5-step intake form
         ↓
POST /intake/{token}/convert
         ↓
intake_service.convert_to_case()
         ↓
Creates Case in MongoDB  →  _run_intake_ai()  →  saves ai_structured_case
```

### _run_intake_ai() — Lazy Import + Fallback

```python
async def _run_intake_ai(query, case_type, province, session_id, case_id):
    from app.ai.graph.supervisor import intake_graph   # lazy: avoids circular imports

    state = { "query": query, "case_type": case_type, ... }

    try:
        result = await intake_graph.ainvoke(state)
        return json.loads(result["answer"])
    except Exception:
        return {                                         # case creation never fails
            "summary": "AI structuring unavailable — case created successfully.",
            "applicable_laws": [],
            "recommended_actions": ["Consult a qualified Pakistani lawyer."],
            "risk_level": "medium",
        }
```

### Graph Flow

```
incident_description (plain text from Step 3)
        ↓
  retrieval_node
    - query expansion: "landlord beat me" → "landlord beat me PPC assault causing hurt"
    - BM25 (k=10) + Chroma semantic (k=10) run in parallel
    - EnsembleRetriever merges with weights [0.6, 0.4]
    - returns up to 20 merged chunks
        ↓
  intake_node
    - formats top-6 chunks as context (statute + content[:400])
    - LLM with structured output → IntakeOutput Pydantic model
    - returns JSON string in state["answer"]
        ↓
  END → json.loads(result["answer"]) → saved to MongoDB
```

### intake_node — Structured LLM Output

```python
class IntakeOutput(BaseModel):
    summary: str
    applicable_laws: list[str]
    recommended_actions: list[str]
    risk_level: str   # "low" | "medium" | "high"

llm = get_llm().with_structured_output(IntakeOutput)
result: IntakeOutput = llm.invoke([system_prompt, user_prompt])
```

Using `.with_structured_output()` forces the LLM to return valid JSON matching the schema — no parsing guesswork.

### Actual Output (verified, running system)

```json
{
  "summary": "The landlord physically assaulted the client, hitting them with his fist
              and threatening to kill them if they did not leave the property, resulting
              in injuries on the face and arms. The client is in Punjab — criminal case.",
  "applicable_laws": [
    "PPC Section 324 — Voluntarily causing hurt by dangerous weapons or means",
    "PPC Section 506 — Punishment for criminal intimidation"
  ],
  "recommended_actions": [
    "File a First Information Report (FIR) with the police",
    "Seek medical attention and preserve evidence of injuries",
    "Consider obtaining a restraining order against the landlord"
  ],
  "risk_level": "high"
}
```

---

## Part 5 — Chat Graph (WebSocket flow)

### WebSocket Endpoint

```
WS /ws/chat/{session_id}?token=<JWT>
```

Authentication: JWT passed as a query parameter (WebSocket headers are not browser-standard). The server decodes it immediately and closes with code 4001 if invalid.

### chat_socket.py — Core Loop

```python
from app.ai.graph.supervisor import chat_graph   # lazy import

graph_config = {"configurable": {"thread_id": session_id}}  # MemorySaver key

while True:
    data = await websocket.receive_json()
    query = data.get("content", "").strip()

    await websocket.send_json({"type": "thinking"})        # typing indicator

    state = _build_state(query, session_id, session, data)
    result = await chat_graph.ainvoke(state, config=graph_config)

    if result.get("needs_clarification"):
        await websocket.send_json({
            "type": "clarification",
            "question": result["clarification_question"],
        })
    else:
        await websocket.send_json({
            "type": "final",
            "content": result["answer"],
            "citations": result["citations"],
            "confidence": result["confidence"],
        })
```

### MemorySaver — Conversation History

`chat_graph` is compiled with `checkpointer=MemorySaver()`. On every `ainvoke` call:
- LangGraph loads the checkpoint for `thread_id = session_id`
- `messages` field (reducer: `operator.add`) → new HumanMessage is **appended** to history
- All other fields (query, answer, chunks, etc.) are **replaced** by the new invocation's values
- After completion → checkpoint saved back

This gives each WebSocket session persistent, multi-turn conversation memory — the LLM sees the full prior exchange as context.

### Full Chat Graph Flow

```
User message (WebSocket JSON)
        ↓
  [WebSocket handler] → save to MongoDB, send {"type": "thinking"}
        ↓
  gatekeeper_node
    - LLM classifies query: "legal" or "off_topic"
    - off_topic → sets answer = canned response → END (skips retrieval)
    - legal → {}  (no state change, continues)
        ↓
  [edge: route_after_gatekeeper]
    - state["answer"] non-empty → "END"   (gatekeeper already handled it)
    - state["answer"] empty    → "retrieval_node"
        ↓
  retrieval_node
    - _expand_query(): LLM rewrites plain language to legal terms
    - BM25 + Chroma hybrid → up to 20 merged chunks
    - relevance_score = min(len(docs) / 10.0, 1.0)
        ↓
  [edge: route_after_retrieval]
    - relevance_score < 0.75  → clarification_node → END
    - relevance_score >= 0.75 → generation_node
        ↓
  generation_node
    - Selects SYSTEM_PROMPT_EN or SYSTEM_PROMPT_UR based on state["language"]
    - Formats top-8 chunks as numbered context (statute name + content[:400])
    - LLM generates answer using ONLY provided sections
    - Extracts {"confidence": 0.85} from last line → strips it from visible answer
    - Appends legal disclaimer
        ↓
  hallucination_node
    - Early exit if answer or chunks are empty → caution + confidence 0.35
    - LLM checks: are the major claims in the answer supported by the chunks?
    - Not grounded → appends caution note, sets confidence = 0.35 (answer kept)
    - Grounded → is_grounded = True (answer unchanged)
        ↓
  END → WebSocket sends final/clarification response → saved to MongoDB
```

### WebSocket Message Protocol

| Type | Direction | Payload |
|------|-----------|---------|
| `{"type": "thinking"}` | Server → Client | AI is processing (show spinner) |
| `{"type": "final", "content": "...", "citations": [...], "confidence": 0.85}` | Server → Client | Normal grounded answer |
| `{"type": "clarification", "question": "..."}` | Server → Client | Query too vague |
| `{"type": "error", "content": "..."}` | Server → Client | AI service failed |

### Actual Output (verified, running system)

**Query:** `"My landlord beat me up. What can I do under Pakistani law?"`
```json
{
  "type": "final",
  "content": "Under Pakistani law, if your landlord beat you up, you can file a complaint
              for causing grievous hurt, punishable under Section 325 of the Pakistan Penal
              Code. You can also refer to Section 335 if there was provocation involved...\n\n
              ---\n*This information is for general guidance only...*",
  "citations": [
    {"statute": "CrPC 1898", "section": "524", "source": "Code_of_criminal_procedure_1898.pdf"},
    ...
  ],
  "confidence": 0.85
}
```

**Query:** `"What is Section 506 of PPC?"`
```json
{
  "type": "final",
  "content": "Section 506 of the Pakistan Penal Code deals with criminal intimidation,
              except when the offence is punishable with imprisonment for seven years...",
  "confidence": 0.85
}
```

---

## Part 6 — Node Design Decisions

### Why 5 nodes, not more?

**Original plan:** `grader_node` + `hallucination_node` as separate nodes.  
**Final design:** Merged into one approach:

| What | Where | Why |
|------|-------|-----|
| Relevance check | `route_after_retrieval` edge function | It's a routing decision, not a transformation — edges are the right place |
| Grounding check | `hallucination_node` | It IS a transformation: it can modify the answer |

**Node count:** 6 nodes across both graphs:
- `gatekeeper_node` (chat only)
- `retrieval_node` (shared)
- `clarification_node` (chat only)
- `generation_node` (chat only)
- `hallucination_node` (chat only)
- `intake_node` (intake only)

### Hallucination Node — Graceful Degradation

**Original design:** Replace answer with refusal template if not grounded.  
**Problem:** The LLM sometimes cites a valid section whose number appears in the chunk content but not in the metadata label. Hard refusal made the chat useless.  
**Final design:** Degrade gracefully:

```python
if not result.is_grounded:
    caution = "\n\n> **Caution:** Some information may not be fully supported
                by the retrieved law sections. Please verify with a qualified lawyer."
    return {"is_grounded": False, "answer": state["answer"] + caution, "confidence": 0.35}
```

The answer is kept but flagged. Users see the information with a lower confidence score.

### Language-Aware Generation

**Problem discovered in production:** Groq `llama-3.3-70b` responded in Urdu for English queries when given Pakistani legal context, because the model "detected" Pakistani context and switched languages. The hallucination node (English-only prompt) then marked Urdu answers as ungrounded.

**Fix:** Two system prompts, selected by `state["language"]`:

```python
system_prompt = SYSTEM_PROMPT_UR if state.get("language") == "ur" else SYSTEM_PROMPT_EN
```

`SYSTEM_PROMPT_EN` explicitly says "Respond in English." `SYSTEM_PROMPT_UR` says "اردو میں جواب دیں۔"

---

## Part 7 — LLM Factory

```python
def get_llm():
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",        # free tier, fast
            google_api_key=settings.gemini_api_key,
            temperature=0.1,
        )
    if provider == "ollama":
        return ChatOllama(model="llama3.1", temperature=0.1)   # fully local, free

    if provider == "groq":
        return ChatGroq(
            model="llama-3.3-70b-versatile", # free tier cloud inference
            api_key=settings.groq_api_key,
            temperature=0.1,
        )
```

Switch by setting `LLM_PROVIDER=gemini|ollama|groq` in `.env`.

**Note:** `llama-3.1-70b-versatile` was decommissioned by Groq in 2026. Current model is `llama-3.3-70b-versatile`.

**Temperature = 0.1** across all providers: legal answers must be deterministic and factual — creativity is undesirable.

---

## Part 8 — Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Embedding model | `intfloat/multilingual-e5-base` (768-dim) | Supports Urdu + English; outperforms MiniLM on legal text |
| Prefix convention | `"passage: "` for docs, `"query: "` for queries | Required by e5 model contract — without it, retrieval quality drops significantly |
| BM25 weight | 0.6 | Pakistani law heavy with exact statute refs (`PPC S.302`) |
| Semantic weight | 0.4 | Plain-language queries need semantic match |
| Query expansion | LLM rewrites plain query to legal terms before BM25 | BM25 fails on everyday language like "beat me up" — must use legal vocab |
| Chunking strategy | Section-aware regex + sliding window fallback | Preserves legal clause integrity; never splits `Section 302(a)` mid-clause |
| Relevance threshold | 0.75 (min 8 of 10 docs returned) | Below this, query is too vague for reliable generation |
| Language selection | `state["language"]` → two separate system prompts | LLM would auto-switch to Urdu for Pakistani context even with English queries |
| Hallucination response | Degrade (caution + 0.35 confidence) not refuse | Hard refusal breaks chat UX; user still sees information with appropriate warning |
| Error fallback | Safe fallback dict if AI fails | Case creation (intake) never blocked by LLM failures |
| Lazy import of graphs | Inside `_run_intake_ai()` and `chat_socket.py` | Avoids circular imports; delays 1.1 GB model load until first actual request |
| `@lru_cache` on BM25 + embeddings | `maxsize=6` (BM25) and `maxsize=1` (embeddings) | BM25 index rebuild and model load are expensive — do once per server lifetime |
| `family_collection` | Separate from `civil_collection` | Muslim Family Law and Qanun-e-Shahadat are distinct legal domains |
| MemorySaver thread_id | `session_id` from WebSocket URL | One persistent conversation memory per WebSocket session |
| ChromaDB path | `pathlib.Path(__file__).parents[2] / "chroma_data"` | `parents[2]` from `app/db/chroma.py` = `backend/` — one level up from app/ |

---

## Part 9 — Challenges & Solutions

These came up during actual implementation and testing. Expect questions about them.

### Challenge 1: BM25 returns procedural sections for plain-language queries

**What happened:** Query `"My landlord beat me up"` returned CrPC warrant forms (Section 524) instead of PPC assault sections (Section 325, 335).

**Root cause:** BM25 keyword matching requires the query words to appear in the document. "Beat" does not appear in PPC. The semantic retriever (0.4 weight) was overridden by BM25 (0.6 weight).

**Solution:** LLM query expansion before BM25 — rewrite `"My landlord beat me up"` → `"PPC assault causing grievous hurt criminal force section"` so BM25 finds the right sections.

### Challenge 2: LLM responded in Urdu for English queries

**What happened:** Groq `llama-3.3-70b` saw Pakistani legal context in the chunks and switched to Urdu even when the user wrote in English. The hallucination checker (English-only) then marked every Urdu answer as ungrounded.

**Root cause:** No explicit language instruction in the generation prompt.

**Solution:** Two system prompts (`SYSTEM_PROMPT_EN`, `SYSTEM_PROMPT_UR`) selected by `state["language"]`. `SYSTEM_PROMPT_EN` explicitly says "Respond in English."

### Challenge 3: Hallucination node rejected all answers

**What happened:** `is_grounded = False` on every answer, serving only the refusal template.

**Root cause (combined):** (a) Urdu answers — English hallucination checker couldn't verify them. (b) Chunk metadata had wrong section numbers (chunker assigned `section_number=165` to a chunk whose content contains Section 351 text). Generation LLM cited Section 351 from content; hallucination LLM compared against metadata label "165" — mismatch.

**Solution:** (a) Fix language issue (Challenge 2). (b) Remove misleading metadata section numbers from the context format — show only content and statute name; let both LLMs read section numbers from text directly. (c) Change hard refusal to graceful degradation.

### Challenge 4: Wrong ChromaDB path

**What happened:** Server connected to `attorney-ai/chroma_data/` (empty) instead of `attorney-ai/backend/chroma_data/` (2,357 chunks). BM25 failed with `ValueError: not enough values to unpack`.

**Root cause:** `pathlib.Path(__file__).parents[3]` in `chroma.py` — `parents[3]` from `app/db/chroma.py` is the repo root, not `backend/`.

**Fix:** Changed to `parents[2]` which resolves to `backend/`.

### Challenge 5: LangChain 1.x breaking import changes

**What happened:** `from langchain.schema import Document` and `from langchain.retrievers import EnsembleRetriever` both raised `ModuleNotFoundError` after installing the latest LangChain.

**Root cause:** LangChain 1.x restructured packages — moved classes to sub-packages.

**Fixes:**
```python
# Old                                      # New
from langchain.schema import Document      → from langchain_core.documents import Document
from langchain.retrievers import ...       → from langchain_classic.retrievers.ensemble import EnsembleRetriever
```

### Challenge 6: Groq model decommissioned

**What happened:** `llama-3.1-70b-versatile` returned HTTP 400 — "model decommissioned."

**Fix:** Updated to `llama-3.3-70b-versatile` in `llm.py`.

### Challenge 7: Server running wrong Python (no venv)

**What happened:** `start.ps1` activated the venv but ran `uvicorn` from the global PATH (system Python 3.14, no AI packages). Every `/convert` call returned 500 `No module named 'langgraph'`.

**Root cause:** PowerShell `Activate.ps1` + subsequent command in a script doesn't reliably propagate the venv activation.

**Fix:**
```powershell
# Old (unreliable)
& "$PSScriptRoot\venv\Scripts\Activate.ps1"
uvicorn app.main:app --reload --port 8000

# New (explicit venv path)
& "$PSScriptRoot\venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000
```

---

## Part 10 — File Map

```
backend/
├── chroma_data/                        ← ChromaDB persistent storage (2,357 chunks)
├── knowledge_base/
│   ├── raw/
│   │   ├── criminal/                   ← PPC, CrPC, Police Law PDFs
│   │   ├── civil/                      ← Transfer Property Act, Limitation Act PDFs
│   │   └── supporting/                 ← Muslim Family Law, Qanun-e-Shahadat PDFs
│   ├── processed/
│   │   ├── text/                       ← ingest.py output (.txt per PDF)
│   │   ├── chunks/                     ← chunk.py output (.json per PDF)
│   │   └── embedded/                   ← embed.py output (chunks + 768-dim vectors)
│   └── pipeline/
│       ├── ingest.py                   ← pdfplumber extraction
│       ├── chunk.py                    ← section-aware splitting
│       ├── embed.py                    ← multilingual-e5-base encoding
│       └── store.py                    ← ChromaDB upsert
└── app/
    ├── db/
    │   └── chroma.py                   ← PersistentClient singleton + get_chroma()
    ├── ai/
    │   ├── llm.py                      ← LLM factory (gemini|groq|ollama)
    │   ├── graph/
    │   │   ├── state.py                ← AgentState TypedDict (shared by both graphs)
    │   │   ├── edges.py                ← route_after_gatekeeper, route_after_retrieval
    │   │   └── supervisor.py           ← chat_graph + intake_graph singletons
    │   ├── nodes/
    │   │   ├── gatekeeper_node.py      ← legal vs off_topic classifier
    │   │   ├── retrieval_node.py       ← query expansion + BM25 + Chroma hybrid
    │   │   ├── clarification_node.py   ← generates one clarifying question
    │   │   ├── generation_node.py      ← answer with citations + disclaimer
    │   │   ├── hallucination_node.py   ← grounding check + graceful degradation
    │   │   └── intake_node.py          ← structured case analysis (Pydantic output)
    │   └── pipelines/
    │       ├── retriever.py            ← E5Embeddings + _bm25 + build_retriever
    │       └── reranker.py             ← RRF class (Reciprocal Rank Fusion)
    ├── services/
    │   └── intake_service.py           ← _run_intake_ai() wired into convert_to_case()
    └── websockets/
        └── chat_socket.py              ← WS /ws/chat/{session_id} + chat_graph wired
```

---

## Part 11 — Anticipated Viva Questions & Answers

**Q: Why LangGraph instead of a simple sequential LLM call?**  
A: LangGraph gives us conditional routing (gatekeeper can short-circuit, retrieval can branch to clarification), persistent state across WebSocket messages (MemorySaver), and a clear separation of concerns per node. A sequential call would require nested if/else and manual state passing. LangGraph also makes the pipeline diagram match the actual code — each box in the diagram is literally a Python function.

**Q: What is RAG and why do you need it here?**  
A: Retrieval-Augmented Generation — instead of asking the LLM to recall Pakistani law from training data (which may be wrong, outdated, or US/Indian law), we retrieve the actual statute text from our knowledge base and give it to the LLM as context. The LLM then generates an answer grounded in the retrieved text, not memory. This is critical for legal accuracy.

**Q: Why BM25 at all? Why not just use vector search?**  
A: Pakistani legal queries frequently use exact statute references like `"PPC Section 302"` or `"CrPC 497"`. Vector embeddings are good at semantic similarity but poor at exact keyword matching — a query for "PPC 302" might get a semantically similar but wrong section. BM25 matches the exact terms. The hybrid combines both strengths.

**Q: What happens if the LLM makes up a law that doesn't exist?**  
A: The hallucination node checks whether the major claims in the answer are supported by the retrieved chunks. If not, it appends a caution warning and lowers the confidence score to 0.35. The legal disclaimer is also appended to every answer regardless.

**Q: Why multilingual-e5-base specifically?**  
A: It's a 768-dimensional model trained on multilingual data including Arabic script languages. It natively handles Urdu + English in the same embedding space — so a user asking in Urdu gets the same results as asking in English. The `passage:`/`query:` prefix convention is a requirement of the e5 model architecture for asymmetric retrieval.

**Q: How does conversation history work in the chat?**  
A: LangGraph's `MemorySaver` checkpointer stores the full `AgentState` after each graph run, keyed by `thread_id = session_id`. The `messages` field uses an `operator.add` reducer so new messages are appended, not replaced. Each new user message calls `ainvoke` with the same `thread_id`, and LangGraph restores the checkpoint + appends the new message. The LLM receives the full conversation history as `messages` context.

**Q: Why is the confidence score extracted from the last line of the LLM output?**  
A: We can't use a structured output wrapper for generation (it breaks free-form text). Instead, the system prompt instructs the LLM to append `{"confidence": 0.85}` as the very last line. The code splits on newlines, tries to parse the last line as JSON, extracts the confidence value, and strips that line from the displayed answer.

**Q: Why not use a single collection for all laws?**  
A: Separate collections (`criminal`, `civil`, `family`) allow us to scope retrieval to the user's case type. A criminal query only searches `criminal_collection` — avoiding noise from family law sections appearing in assault case results. The `case_type` from the intake form maps directly to the collection.

**Q: What if the AI service is down?**  
A: The intake graph wraps `ainvoke` in a `try/except`. If anything fails — LLM timeout, ChromaDB unreachable, JSON parse error — the case is still created in MongoDB with a safe fallback `ai_structured_case`. The case is never lost due to an AI failure.

**Q: How did you handle Urdu queries?**  
A: The `intfloat/multilingual-e5-base` model handles Urdu natively — Urdu queries are embedded in the same 768-dim space as English. The generation node selects `SYSTEM_PROMPT_UR` when `state["language"] == "ur"` and responds in Urdu. The hallucination node's updated prompt explicitly handles multi-language answers.

---

## Part 12 — Reference Repos Used

| Repo | What we used |
|------|-------------|
| `GiovanniPasq/agentic-rag-for-dummies` | Node structure, conditional edge pattern, clarification branch design |
| `sougaaat/RAG-based-Legal-Assistant` | BM25 retriever setup, RRF reranker class (directly sourced), routing concept |
| `nilsjennissen/langgraph` | BM25/semantic weight recommendation (0.6/0.4) for statute-heavy text |

---

*Attorney.AI | SP23-BCS-069 | Muhammad Usama | May 2026*
