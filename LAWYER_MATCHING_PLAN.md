# Attorney.AI — Lawyer Matching: Design Plan
> SP23-BCS-069 | Muhammad Usama | May 2026

---

## What We Are Building

When a client converts their intake to a case, the system automatically finds the top-N most relevant lawyers for that case. The client sees a ranked list on the `ModLawyers.jsx` page.

**Endpoint:** `GET /api/v1/lawyers/match?case_id=<id>`  
**Returns:** Ranked list of lawyers with match scores and reasons.

---

## Research Basis (Two Repos Studied)

### Repo 1 — EF_in_Legal_CQA-ECIR2022 (Arian Askari, ECIR 2022)

**Problem:** Expert Finding in Legal Community Q&A — given a legal question, rank the best lawyer/expert to answer it.

**Core algorithm — Two-Level Probabilistic Scoring:**

```
expert_score(query, lawyer) =
    ∏ [ λ × P(term | collection) + (1 - λ) × P(term | lawyer_answers) ]

where:
  λ (Dirichlet smoothing) = β / (β + doc_length)
  β = total_collection_terms / num_answers
```

Two scoring levels run in parallel:
- **Candidate-level**: scores the lawyer's ENTIRE body of work against the query
- **Document-level**: scores each individual answer, then aggregates

**What we take from this:**
- The two-level idea → we score lawyers at two levels: (1) specialization match, (2) case description semantic similarity
- Use collection statistics to smooth scores — lawyers with more cases should be compared fairly against those with fewer
- The expert profile = all their past cases aggregated, not just their bio

---

### Repo 2 — FreeLawProject/Inception

**Problem:** High-performance embedding service for legal documents.

**Key patterns:**
- **Prefix convention:** `"search_query: "` for queries, `"search_document: "` for documents
  - Mirrors our own `"query: "` / `"passage: "` pattern for E5 — same principle
- **Sentence-boundary chunking:** Split at sentence boundaries, not character limits — legal text has long sentences that must not be broken mid-clause
- **Batch API with validation gates:** Validate before embedding, reject malformed inputs early
- **Async executor:** Embedding inference is CPU-bound — run in `asyncio.get_running_loop().run_in_executor()` to not block FastAPI event loop

**What we take from this:**
- Build lawyer profiles as concatenated text chunks (bio + specializations + past case summaries) using sentence-aware chunking
- The same `"passage: "` prefix we already use for law text applies here too
- Run embedding inference in executor (non-blocking) — same pattern as our `retrieval_node` via LangGraph

---

## Our Existing Stack (What We Already Have)

| Component | Status | Relevant detail |
|-----------|--------|----------------|
| `intfloat/multilingual-e5-base` | Running | 768-dim, `passage:`/`query:` prefix, `@lru_cache` loaded |
| `chromadb.PersistentClient` | Running | `backend/chroma_data/`, `lawyers_collection` slot exists |
| `app/ai/pipelines/retriever.py` | Running | `E5Embeddings`, `_embeddings()` cached |
| `app/db/chroma.py` | Running | `get_chroma()`, `COLLECTIONS` list |
| `app/services/lawyer_service.py` | Stub | `match_lawyers_for_case()` has TODO |
| `app/repositories/lawyer_repo.py` | Built | MongoDB CRUD for lawyers |
| `app/models/lawyer.py` | Built | `Lawyer` document schema |
| Lawyer profile fields | Built | `specializations[]`, `province`, `rating`, `experience_years`, `availability`, `bio` |
| `lawyers_collection` in ChromaDB | Declared | In `COLLECTIONS` list — **not yet populated** |

---

## Architecture

```
[Lawyer signs up / updates profile]
          ↓
  embed_lawyer_profile()
    - builds profile text from bio + specializations + past case summaries
    - encodes with E5 ("passage: " prefix)
    - upserts into ChromaDB lawyers_collection
          ↓
  [stored: 768-dim vector per lawyer, metadata: lawyer_id, province, specializations, rating]

─────────────────────────────────────────────────────────────

[Client converts intake → case created]
          ↓
  match_lawyers_for_case(case_id)
    - loads case: case_type, province, description
    - embeds description with E5 ("query: " prefix)
    - Chroma similarity search in lawyers_collection (province filter)
    - returns top-20 candidate lawyers
          ↓
  score_and_rank(candidates, case)
    - applies multi-factor scoring formula
    - returns top-5 sorted by score
          ↓
  POST /lawyers/match → [{lawyer, score, match_reason}, ...]
```

---

## Multi-Factor Scoring Formula

Adapted from EF_in_Legal_CQA two-level scoring and the existing formula from PROGRESS_30.md:

```python
final_score = (
    semantic_similarity(case_emb, lawyer_emb) * 0.50   # Level 1: semantic fit
  + specialization_boost(lawyer, case_type)             * 0.20   # Level 2: explicit domain claim
  + (lawyer.rating / 5.0)                              * 0.15   # reputation signal
  + (1.0 if lawyer.availability else 0.0)              * 0.10   # practical filter
  + min(lawyer.experience_years / 20.0, 1.0)           * 0.05   # experience cap at 20 years
)
```

### Semantic Similarity (0.50 weight)
- Cosine similarity between `embed_query(case_description)` and `embed_passage(lawyer_profile)`
- Returned directly by Chroma's similarity search (`distance` field, converted: `1 - distance`)

### Specialization Boost (0.20 weight)
Inspired by EF_in_Legal_CQA candidate-level scoring — explicit domain claim is a strong prior:

```python
def specialization_boost(lawyer: dict, case_type: str) -> float:
    specs = [s.lower() for s in lawyer.get("specializations", [])]
    if case_type in specs:
        return 1.0       # exact match
    related = {
        "criminal": ["penal", "defense", "criminal law", "fir"],
        "civil":    ["property", "contract", "civil litigation"],
        "family":   ["divorce", "custody", "marriage", "inheritance"],
    }
    if any(r in " ".join(specs) for r in related.get(case_type, [])):
        return 0.5       # partial match
    return 0.0
```

### Dirichlet Smoothing (from EF_in_Legal_CQA) — Applied to Experience
Lawyers with few cases shouldn't be penalized vs. those with many. Smoothed experience:

```python
def smoothed_experience(lawyer: dict, avg_years: float = 8.0) -> float:
    years = lawyer.get("experience_years", 0)
    # Dirichlet: blend individual with collection mean
    beta = avg_years
    smoothed = (years + beta) / (years + 2 * beta) if years > 0 else 0.5
    return smoothed
```

*(Optional — use only if beta-testing shows raw years unfairly ranks new lawyers.)*

---

## Profile Text Construction (from Inception pattern)

The lawyer's ChromaDB document is a structured text blob, not just a bio. Inspired by Inception's document chunking:

```python
def build_profile_text(lawyer: dict, recent_cases: list[dict]) -> str:
    parts = []

    # Identity + domain
    parts.append(f"Legal professional specializing in {', '.join(lawyer.get('specializations', []))}.")
    parts.append(f"Province: {lawyer.get('province', 'federal')}.")
    parts.append(f"Experience: {lawyer.get('experience_years', 0)} years.")

    # Bio (free text — most semantically rich)
    if lawyer.get("bio"):
        parts.append(lawyer["bio"])

    # Past case summaries (EF_in_Legal_CQA: expert score = aggregated past answers)
    if recent_cases:
        summaries = [c.get("description", "")[:150] for c in recent_cases[:5] if c.get("description")]
        if summaries:
            parts.append("Past cases handled: " + " | ".join(summaries))

    return " ".join(parts)
```

This means a lawyer who has handled 5 criminal assault cases will have "assault", "criminal", "FIR", "PPC" naturally embedded in their profile — giving them high semantic similarity for new assault queries, even without explicit keyword tagging.

---

## Files to Create / Modify

### New Files

```
backend/app/ai/
└── lawyer_embeddings.py        ← profile building + embed + upsert into Chroma
```

### Modified Files

```
backend/app/services/
└── lawyer_service.py           ← implement match_lawyers_for_case() (currently TODO stub)

backend/app/api/v1/routes/
└── lawyers.py                  ← add GET /match endpoint + POST /embed (admin trigger)

backend/app/db/
└── chroma.py                   ← already has "lawyers_collection" in COLLECTIONS list
```

---

## Implementation Steps

### Step 1 — `lawyer_embeddings.py`

```python
from app.ai.pipelines.retriever import _embeddings
from app.db.chroma import get_chroma
from app.repositories.lawyer_repo import LawyerRepository
from app.repositories.case_repo import CaseRepository  # for recent cases

LAWYERS_COLLECTION = "lawyers_collection"

def build_profile_text(lawyer: dict, recent_cases: list) -> str:
    """Construct rich profile text from lawyer doc + case history."""
    ...  # as described above

async def embed_lawyer(lawyer_id: str) -> bool:
    """Embed one lawyer's profile and upsert into ChromaDB."""
    lawyer = await LawyerRepository().find_by_id(lawyer_id)
    recent_cases = await CaseRepository().find_by_lawyer(lawyer_id, limit=5)

    profile_text = build_profile_text(lawyer, recent_cases)
    emb_model = _embeddings()                          # cached, no reload
    vector = emb_model.embed_documents([profile_text])[0]   # "passage: " prefix applied

    col = get_chroma().get_or_create_collection(
        LAWYERS_COLLECTION, metadata={"hnsw:space": "cosine"}
    )
    col.upsert(
        ids=[lawyer_id],
        embeddings=[vector],
        documents=[profile_text],
        metadatas=[{
            "lawyer_id":        lawyer_id,
            "province":         lawyer.get("province", "federal"),
            "specializations":  ",".join(lawyer.get("specializations", [])),
            "rating":           lawyer.get("rating", 0.0),
            "experience_years": lawyer.get("experience_years", 0),
            "availability":     lawyer.get("availability", False),
        }],
    )
    return True

async def embed_all_lawyers() -> int:
    """Batch embed all lawyers. Called once on setup or admin trigger."""
    lawyers = await LawyerRepository().find_all_active()
    for lawyer in lawyers:
        await embed_lawyer(str(lawyer["_id"]))
    return len(lawyers)
```

### Step 2 — `lawyer_service.py` — implement `match_lawyers_for_case()`

```python
async def match_lawyers_for_case(case_id: str, top_n: int = 5) -> list[dict]:
    case = await CaseRepository().find_by_id(case_id)
    case_type = case.get("case_type", "civil")
    province  = case.get("province", "federal")
    query     = case.get("description", "")

    # 1. Embed case description (query prefix)
    emb_model = _embeddings()
    query_vec = emb_model.embed_query(query)   # "query: " prefix applied

    # 2. Semantic search with province filter
    col = get_chroma().get_collection("lawyers_collection")
    results = col.query(
        query_embeddings=[query_vec],
        n_results=20,
        where={"$or": [
            {"province": {"$eq": province}},
            {"province": {"$eq": "federal"}},
        ]},
        include=["metadatas", "distances", "documents"],
    )

    # 3. Multi-factor scoring
    candidates = []
    for i, lawyer_id in enumerate(results["ids"][0]):
        meta     = results["metadatas"][0][i]
        distance = results["distances"][0][i]
        semantic_score = max(0.0, 1.0 - distance)   # cosine: distance 0=identical

        lawyer_doc = await LawyerRepository().find_by_id(lawyer_id)
        if not lawyer_doc:
            continue

        score = (
            semantic_score                                              * 0.50
          + specialization_boost(lawyer_doc, case_type)                * 0.20
          + (lawyer_doc.get("rating", 0.0) / 5.0)                     * 0.15
          + (1.0 if lawyer_doc.get("availability") else 0.0)           * 0.10
          + min(lawyer_doc.get("experience_years", 0) / 20.0, 1.0)    * 0.05
        )

        candidates.append({
            "lawyer":        lawyer_doc,
            "score":         round(score, 4),
            "semantic":      round(semantic_score, 4),
            "match_reason":  _build_reason(lawyer_doc, case_type, semantic_score),
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_n]
```

### Step 3 — `lawyers.py` (routes) — new endpoints

```python
# Match lawyers for a case
GET /api/v1/lawyers/match?case_id=<id>&top_n=5

# Admin: re-embed a single lawyer (called after profile update)
POST /api/v1/lawyers/{lawyer_id}/embed

# Admin: re-embed ALL lawyers (one-time setup or bulk refresh)
POST /api/v1/admin/lawyers/embed-all
```

---

## When Embedding is Triggered

| Event | Trigger | Action |
|-------|---------|--------|
| Lawyer registers + KYC approved | `auth_service.approve_kyc()` | `await embed_lawyer(lawyer_id)` |
| Lawyer updates profile/bio/specializations | `PUT /lawyers/{id}/profile` | `await embed_lawyer(lawyer_id)` |
| Lawyer closes a case | `case_service.close_case()` | `await embed_lawyer(lawyer_id)` (profile richer) |
| Initial setup | Admin POST `/admin/lawyers/embed-all` | `await embed_all_lawyers()` |

---

## Chroma Metadata Schema (lawyers_collection)

```python
{
    "lawyer_id":        "abc123",
    "province":         "punjab",            # for province filter
    "specializations":  "criminal,family",   # comma-joined for Chroma metadata
    "rating":           4.2,
    "experience_years": 8,
    "availability":     True,
}
```

ChromaDB metadata must be `str | int | float | bool` — no lists. Specializations stored as comma-joined string, split on retrieval.

---

## Match Reason String (UX)

```python
def _build_reason(lawyer: dict, case_type: str, semantic: float) -> str:
    specs = lawyer.get("specializations", [])
    exp   = lawyer.get("experience_years", 0)
    parts = []

    if case_type in [s.lower() for s in specs]:
        parts.append(f"specializes in {case_type} law")
    if semantic > 0.75:
        parts.append("strong case description match")
    elif semantic > 0.5:
        parts.append("relevant experience")
    if exp >= 10:
        parts.append(f"{exp} years experience")

    return ", ".join(parts) if parts else "general legal practice"
```

Example: `"specializes in criminal law, strong case description match, 12 years experience"`

---

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Embedding model | Same E5 (`intfloat/multilingual-e5-base`) | Reuse cached `_embeddings()` — no extra model memory |
| Profile text | bio + specializations + past case summaries | From EF_in_Legal_CQA: expert score = aggregated past work, not just bio |
| Scoring weights | 0.50 semantic / 0.20 specialization / 0.15 rating / 0.10 availability / 0.05 experience | Semantic dominates but explicit domain claim and real-world signals matter |
| Specialization boost | Separate from semantic (not embedded as text) | Explicit claim (0.20) should reward lawyers who list criminal even if bio doesn't say much |
| Province filter | At Chroma query time (`where` clause) | Same pattern as law retrieval — filter first, rank second |
| Re-embed on profile update | Yes, async after response | Profile changes meaning; stale vectors give wrong matches |
| ChromaDB collection | `lawyers_collection` | Already declared in `COLLECTIONS` list in `chroma.py` |
| Batch size | No batching needed for lawyers | Pakistan bar has ~50K lawyers; v1 expected: few hundred. Single-item upsert is fine |
| Async embedding | `run_in_executor` for batch | Inspired by Inception — CPU-bound inference blocks event loop |

---

## Viva Questions — Lawyer Matching

**Q: Why use embeddings for lawyer matching instead of keyword search on specializations?**  
A: Keyword search only matches if the lawyer explicitly lists "criminal" in their profile. A lawyer who has handled 10 assault cases but lists "litigation" won't appear. Embeddings capture that their profile text contains assault/FIR/PPC references from past case summaries, giving high semantic similarity for new assault queries without requiring exact keyword labels.

**Q: What is the EF_in_Legal_CQA paper and how did it influence your design?**  
A: It's an ECIR 2022 paper on Expert Finding in Legal Community Q&A. It uses probabilistic language models at two levels — candidate-level (whole profile) and document-level (per answer). We adapted this as: (1) semantic similarity on the whole profile vector (analogous to candidate-level) plus (2) explicit specialization boost (analogous to domain-specific term weighting). The Dirichlet smoothing idea — blending individual scores with collection averages — informs how we handle lawyers with sparse profiles.

**Q: Why the 0.50 weight on semantic similarity?**  
A: It's the most informative signal — it captures the actual meaning of both the case and the lawyer's experience. The specialization boost (0.20) handles the explicit domain claim which is high-precision but low-recall. Rating (0.15) is a real-world quality signal. Availability (0.10) is a practical filter — a perfect match who is unavailable is useless. Experience (0.05) has diminishing returns, hence low weight and 20-year cap.

**Q: How does a lawyer's past cases affect their embedding?**  
A: `build_profile_text()` includes summaries of the lawyer's last 5 cases. If they handled assault and FIR cases, those terms appear in their profile text. When the profile is embedded with `"passage: "` prefix, those legal concepts become part of the 768-dim vector. A new assault case query then has high cosine similarity because both vectors encode the same legal domain.

**Q: What happens if no lawyers are embedded yet?**  
A: The `lawyers_collection` query returns empty results. `match_lawyers_for_case()` returns an empty list. The route returns `[]` and the frontend shows "No matched lawyers yet." Admin triggers `POST /admin/lawyers/embed-all` to populate the collection.

---

## Reference

| Source | Concept Used |
|--------|-------------|
| Askari et al., ECIR 2022 — EF_in_Legal_CQA | Two-level scoring (candidate + document), Dirichlet smoothing, expert profile = aggregated past work |
| FreeLawProject/Inception | Profile text chunking strategy, `"search_document:"` prefix pattern (≈ our `"passage:"`), async executor for non-blocking inference |
| Our existing `retriever.py` | Reused `_embeddings()` + `E5Embeddings` — no new model, no new memory |
| Our existing `chroma.py` | Reused `get_chroma()` + `lawyers_collection` already declared |

---

*Attorney.AI | SP23-BCS-069 | Muhammad Usama | May 2026*
