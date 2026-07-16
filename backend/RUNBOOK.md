# Attorney.AI — Backend Runbook

Operational guide: how to run it, what it needs, what breaks, and how to tell.

---

## 1. What this service is

A FastAPI backend for Pakistani legal assistance. The AI side is a LangGraph
pipeline (12 nodes) that does RAG over statutes and case law, and — via a tool
layer — calls **deterministic legal engines** (bail eligibility, court fee,
inheritance shares) rather than letting the model guess at them.

That distinction matters operationally. If an answer about bail is wrong, the
question is not "was the model having a bad day" but **"did the tool actually
fire?"** — see §7.

---

## 2. Dependencies

| Component | Purpose | Required? |
|---|---|---|
| MongoDB | primary datastore + LangGraph conversation checkpoints | **yes** — app will not serve |
| ChromaDB | vector store: statutes, judgments, lawyer embeddings | **yes** for any legal answer |
| Redis | semantic cache, rate limits, WS pub/sub, citator streams | optional; degrades gracefully |
| ≥1 LLM provider | Gemini / Groq / OpenRouter / Ollama | **yes** — startup raises without one |

---

## 3. Configuration

All settings live in `app/core/config.py` (pydantic-settings, read from `.env`).
Names below are the env-var forms.

**Mandatory — no defaults, the app will not start without them:**

```
SECRET_KEY=...          # JWT signing
ENCRYPTION_KEY=...      # at-rest field encryption
```

**LLM — at least one key, or startup fails with "No language model is available":**

```
GEMINI_API_KEY=...      # tried FIRST (see _FALLBACK_ORDER)
GROQ_API_KEY=...
OPENROUTER_API_KEY=...
LLM_PROVIDER=groq       # set to "ollama" to prepend a local Ollama
```

**Data stores:**

```
MONGODB_URL=mongodb://localhost:27017
DB_NAME=attorney_ai
REDIS_URL=rediss://...  # Upstash in prod. Empty = cache/rate-limit disabled, app still runs.
```

Optional integrations (WhatsApp, SMTP, Safepay, cause-list polling) are in
`config.py` and all default to off/empty.

> **Secrets never go in the image or in git.** `.env` holds the Upstash token and
> payment keys. Inject them at runtime.

---

## 4. Running it

```bash
cd backend
python -m venv venv
venv/Scripts/pip install -r requirements.txt      # Linux/mac: venv/bin/pip

# ALWAYS use the venv's uvicorn — the system Python does not have the deps.
venv/Scripts/uvicorn app.main:app --reload --port 8000
```

Startup (`app/main.py` lifespan) connects Mongo, connects Chroma, and creates
indexes — including the unique indexes the conversation checkpointer relies on.

Health: `GET /` · API docs: `GET /docs` · OpenAPI: `GET /openapi.json`

---

## 5. Seeding the vector store

A fresh Chroma is **empty**, and an empty Chroma means every legal answer comes
back with no statute behind it (see §7.1). Ingest scripts live in `scripts/`:

```bash
venv/Scripts/python scripts/ingest_pakistan_laws.py     # statutes -> {criminal,civil,family}_collection
venv/Scripts/python scripts/ingest_lhc_judgments.py     # judgments_collection (case law / citator)
venv/Scripts/python scripts/build_law_graph.py          # statute cross-reference graph
venv/Scripts/python seed_lawyers.py                     # demo lawyers + embeddings (repo root, not scripts/)
```

Expected non-zero counts afterwards:

```python
from app.db.chroma import connect_chroma, get_collection
connect_chroma()
for c in ("criminal_collection", "civil_collection", "family_collection", "judgments_collection"):
    print(c, get_collection(c).count())
```

---

## 6. Tests

```bash
pytest -m "not integration"   # 100+ tests. Offline: no DB, no network, no LLM. ~10s.
pytest -m integration         # needs MongoDB (checkpointer + document ACL). ~40s.
pytest                        # everything
```

CI (`.github/workflows/tests.yml`) runs both, with a real `mongo:7` service —
the integration tests self-skip without Mongo, and silently skipping the
**security** tests (cross-user document access) is worse than not having them.

Markers: `integration` = needs Mongo. `llm` = calls a real provider (never in CI).

---

## 7. Troubleshooting

### 7.1 Answers come back with "no law sections provided"

Retrieval returned zero chunks. In order of likelihood:

1. **Chroma isn't connected.** `connect_chroma()` runs in the app lifespan, so this
   mostly bites in *scripts* that only call `connect_db()`. `retrieval_node` logs
   `retrieval: could not build retriever ... answering with NO statute context`.
2. **Chroma is empty** — run the ingest scripts (§5).
3. **Wrong `case_type` → wrong collection.** Check the triage node's classification.

> This used to fail **silently**: the retriever exception was swallowed and the
> user just got an answer with no law in it, indistinguishable from "no law found".
> It now logs loudly and still fails open.

### 7.2 Requests are slow (30–60s)

Almost always the LLM provider, not the graph. Every request logs a trace summary:

```
chat trace {'total_ms': 39039, 'llm_calls': 8, 'tokens_in': 6613,
            'tool_calls': ['check_bail_eligibility'],
            'errors': ['llm:llama-3.3-70b-versatile']}
```

- `errors` containing a model name = **that provider failed and we failed over**.
  A recurring Groq entry means its **daily token cap** is exhausted: small prompts
  still succeed (~200ms), real ~6.5k-token prompts 429 and fall through to
  OpenRouter, which is slow and highly variable (7–37s).
- Fix: add capacity. `GEMINI_API_KEY` is tried **first** and `gemini-2.0-flash`
  serves *both* the fast and main tiers, which bypasses the dead-Groq →
  slow-OpenRouter path entirely.

Per-node timings are logged as `node.end name=... ms=...` — that tells you whether
the cost is triage, retrieval, tools, or generation.

### 7.3 "No language model is available right now"

No provider could be built: every key is missing or the SDK is absent. Set at least
one of `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY`.

### 7.4 Conversations reset / a clarification is asked twice

The checkpointer (`app/ai/graph/checkpointer.py`, Mongo-backed) persists graph
state, *including a `clarification_node` interrupt waiting on the user's reply*.
If conversations are being lost:

- Confirm the unique indexes exist on `lg_checkpoints` / `lg_checkpoint_writes`
  (created by `create_all_indexes()` at startup). Without them, concurrent workers
  can write duplicate checkpoints and "latest" becomes ambiguous.
- Confirm you are not back on `MemorySaver` (RAM-only — does not survive a restart
  or a second uvicorn worker).

### 7.5 A bail / court-fee / inheritance answer looks wrong

Check whether the **tool actually fired** — the trace's `tool_calls` will be empty
if it did not, meaning the model answered from statute text instead of the engine.

- The tool step is gated by a keyword prefilter (`app/ai/tools/__init__.py:
  should_offer_tools`) to avoid paying for it on every turn. A miss means a query
  phrased unusually never reached the engine. The gate is tuned to **over**-fire:
  a false positive costs one model call, a false negative costs correctness.
- If `find_offence_sections` returns `ambiguous: true`, the words the user used map
  to several offences ("fraud" → s.420 / s.406 / s.468). That is intentional — the
  user is asked which section is on their FIR rather than being given a guess.

> Why this matters: `POST /api/v1/ai/compare` routes one query to every provider.
> Asked whether theft under s.379 PPC is bailable, **the raw 70B models answer
> "bailable" — which is wrong.** The bail engine has it right. The tool layer is
> not decoration; it is the thing standing between a user and a confident,
> plausible, wrong answer.

---

## 8. Diagnostics

**Multi-model comparison** — one query, every configured provider, side by side
with latency, tokens, and errors. Lawyer-only.

```bash
curl -X POST localhost:8000/api/v1/ai/compare \
  -H "Authorization: Bearer <lawyer-token>" -H "Content-Type: application/json" \
  -d '{"query":"Is theft under s.379 PPC bailable?","tier":"main"}'
```

Use it to answer "is Groq rate-limited right now?" and "do the models disagree?"
in one shot. Providers run concurrently, so wall-clock is the slowest model.

**Tracing** — `app/ai/tracing.py`. Every graph turn emits per-node, per-LLM and
per-tool spans with timings and token counts, plus one `chat trace {...}` summary
line. Traces stay on your own infrastructure (client legal data must not leave it),
which is why this is not LangSmith.

---

## 9. Known operational gotchas

- **Groq's daily token cap** is the current latency bottleneck (§7.2).
- **`province` defaults to `punjab`** on `POST /calculators/court-fee` when omitted.
  Rates are identical across provinces today, so the number is right — but the
  `legal_basis` will cite the Punjab Finance Acts regardless.
- **No OCR.** A scanned/photographed FIR has no text layer; `read_document` reports
  that rather than inventing contents.
- **Upstash Redis has a ~500k command/month cap.** Do not run the citator stream
  workers continuously against it.
- **The langchain stack is pinned** (`langchain==0.3.30`, `langgraph==1.0.1`).
  Upgrading langgraph pulls langchain 1.x, which **removes `langchain.retrievers`**
  and breaks `app/ai/pipelines/retriever.py` (EnsembleRetriever). This is why the
  Mongo checkpointer is hand-written instead of using `langgraph-checkpoint-mongodb`.
