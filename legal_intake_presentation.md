# Legal Intake Module — Presentation Reference

## What It Does (One Line)
A 5-step AI-guided intake form that collects the user's legal problem, classifies it using keyword + LLM classification (English AND Urdu), asks smart follow-up questions, then structures the case into a MongoDB document ready for lawyer matching and AI analysis.

---

## User Flow (5 Steps)

| Step | What User Does | What System Does |
|---|---|---|
| 1 | Selects Role (Plaintiff / Defendant) + Province | Saved to backend `step1` |
| 2 | Describes the legal issue (text or voice) | `quickClassify()` runs live → auto-selects case type as user types |
| 3 | Answers AI follow-up questions (up to 4 rounds) | Multi-round LLM clarification using domain-specific templates |
| 4 | Confirms / changes case type category | AI has already corrected type via `_ai_classify_case_type()` |
| 5 | Views AI-structured case summary | LangGraph `intake_graph` retrieves laws + generates structured JSON |

---

## Frontend

**File:** `frontend/src/components/client/ModIntake.jsx`

### Live Case Type Classification (`quickClassify`)
- Runs entirely in the browser — no API call needed
- Mirrors the Python keyword classifier on the backend
- Fires on every keystroke in the description textarea and on voice transcript submit
- Supports **English**, **Romanized Urdu** (khula, talaq, talaaq, nikaah), and **Urdu script** (خلع، طلاق، نکاح)
- Score threshold: 0.15 to trigger a suggestion

```js
// Example: user types "I want to file for khula in Lahore"
quickClassify("I want to file for khula in Lahore") → "family"
// Sets caseTypeInput = "family" instantly, before any backend call
```

### Voice Input
- Uses browser `MediaRecorder` API to record audio
- Sends audio blob to `POST /voice/transcribe` (backend Whisper/Groq)
- Transcript appears in editable text area
- `quickClassify` also runs on the transcript when submitted

### Evidence Upload
- File input accepts PDF, Word, JPG, PNG, GIF, WebP (max 10 MB each)
- Uploads via `POST /intake/{token}/evidence` during Step 2
- Files stored at `backend/uploads/evidence/{token}/`

### Export (Step 5)
- **Download PDF** — builds full HTML in JS, opens new window, calls `window.print()`
- **Email Summary** — opens `mailto:` with case summary in body
- Both include: Case ID, type, province, role, AI summary, applicable laws, recommended actions, risk level

---

## Backend

### Session Management
**File:** `backend/app/services/intake_service.py`

Every intake creates a session token in MongoDB:
```
POST /intake/start           → { session_token }
POST /intake/{token}/step/{n} → save each step incrementally
POST /intake/{token}/clarify  → multi-round AI questions
POST /intake/{token}/convert  → finalize → create case document
```

Token stored in `localStorage` so the user can resume if they close the tab.

### AI Case Type Verification (`_ai_classify_case_type`)
Even if the user selects the wrong category, the backend verifies it:

1. **Keyword scorer** (`_score_query`) — checks description against regex signal tables
2. If confidence ≥ 0.30 → use keyword result directly (fast, no LLM cost)
3. If confidence < 0.30 → **LLM fallback** using Gemini Flash
4. LLM system prompt explicitly lists English + Urdu script + Romanized Urdu terms
5. Returns `{ ai_case_type, user_case_type, type_was_corrected }`
6. Frontend shows toast: "Case type updated: Civil → Family"

**Why this matters:** Wrong case type → wrong lawyer matching → wrong AI retrieval collection.

### Multi-Round Clarification (`get_clarification`)
**File:** `backend/app/services/intake_service.py`

- Up to 4 rounds of AI-generated questions
- Each round the LLM receives: description + domain template + previous Q&A
- Domain templates are case-type specific:

| Case Type | Template Focus |
|---|---|
| Family | MFLO registration, children, Mehr amount, divorce/custody/maintenance |
| Criminal | FIR filed, injuries, witnesses, date/location of incident |
| Civil | Written contract, ownership proof, disputed amount, legal notice sent |
| Constitutional | Which fundamental right, which government authority, prior writ petition |

- LLM asked to identify ONE most critical missing fact per round
- Responds "DONE" if all key facts are already present
- After 4 answered rounds → forced proceed (user never gets stuck)
- All Q&A appended to case description before AI analysis (richer context)

---

## AI Pipeline — Intake Graph

**File:** `backend/app/ai/graph/supervisor.py` → `intake_graph`

Triggered by `POST /intake/{token}/convert` after all steps saved.

```
Description + Q&A
      ↓
retrieval_node   → fetches relevant law chunks from ChromaDB (BM25 + semantic)
      ↓
grader_node      → scores chunk relevance, filters noise
      ↓
intake_node      → LLM generates structured JSON:
                    { summary, applicable_laws[], recommended_actions[], risk_level }
      ↓
intake_hallucination_node → verifies answer is grounded in retrieved chunks
      ↓
finalizer        → returns structured JSON to intake_service
```

Output stored in MongoDB `intake.ai_structured_case` and synced to the case document.

### After Conversion (Non-blocking background tasks)
1. **P1 — Case embedding**: `multilingual-e5` embeds the description → stored as 768-dim vector for semantic lawyer matching
2. **P5 — Auto-match**: top 5 lawyers pre-matched and cached on the case document

---

## Classifier — Urdu Support (Fixed This Session)

**File:** `backend/app/ai/nodes/classifier_node.py`

Before fix: only ASCII/English keywords. Urdu users got classified as "civil" (default fallback).

After fix — three layers of detection:

```python
# English + Romanized Urdu
r'\b(divorce|talaq|talaaq|khula|khulaah|nikah|nikaah|shadi|shaadi|
     custody|hizanat|maintenance|nafaqa|mehr|mehar|inheritance|wirsa)\b'

# Urdu script (Unicode)
r'(خلع|طلاق|نکاح|شادی|حضانت|نفقہ|مہر|وراثت|خاندان|گھریلو)'

# Family relations
r'\b(wife|husband|biwi|shohar|shauhar|child|bachha|susral|sasural)\b'
```

Same pattern applied to criminal signals (قتل، چوری، ڈکیتی).

---

## Data Flow Summary

```
User types description (Urdu or English)
        ↓
quickClassify() [browser JS] → caseTypeInput updated live
        ↓
handleStep2Continue() → saves description + effectiveCaseType to backend
        ↓
get_clarification() [backend] → AI asks 1-4 targeted questions
        ↓
convert_to_case() [backend]:
    _ai_classify_case_type() → verifies/corrects case type
    intake_graph.ainvoke()   → retrieval + AI structuring
    _embed_case()            → background vector embedding
    _auto_match_lawyers()    → background lawyer pre-matching
        ↓
Frontend Step 4/5: shows AI summary, applicable laws, recommended actions
```

---

## Key Design Decisions & Why

| Decision | Reason |
|---|---|
| Incremental step saving (not one big submit) | User can close tab and resume — token in localStorage |
| Client-side `quickClassify` before backend call | Instant feedback, case type correct from the first API call — wrong type = wrong clarification template |
| Keyword classifier first, LLM fallback only when confidence < 0.30 | Speed + cost: keyword is free and instant; LLM only fires for ambiguous cases |
| Q&A appended to description BEFORE classification | Richer context for retrieval; but classification runs on BASE description only to avoid question text polluting the scores |
| Province from Step 1, not inferred | User explicitly selects — more reliable than geo-inference for legal jurisdiction |
| Non-blocking background tasks for embedding + matching | User sees result immediately; matching runs in background (asyncio.create_task) |

---

## Common Questions & Answers

**Q: What happens if the user describes their issue in Urdu?**
A: Three layers catch it — Urdu script Unicode regex on the frontend (`quickClassify`) and backend classifier, plus an LLM fallback with a system prompt that explicitly handles Urdu, Romanized Urdu, and English.

**Q: What if the AI picks the wrong case type?**
A: User sees the AI's suggestion on Step 4 and can manually override by clicking any category card. The final selection is what gets saved.

**Q: What if the LLM is down during clarification?**
A: The `get_clarification` function has a try/except — if the LLM fails, it returns `{ done: True }` immediately. The user proceeds to conversion without being stuck in a loop.

**Q: How many clarification questions does the AI ask?**
A: Up to 4 rounds. After each answer the LLM decides if more facts are needed. If all key facts are present it responds "DONE" and the user proceeds. Maximum 4 to avoid overwhelming the user.

**Q: Where are the laws stored?**
A: ChromaDB vector database with 2,357 chunks across 3 collections: criminal (PPC, CrPC), civil (Transfer of Property Act), family (Muslim Family Laws Ordinance 1961, Qanun-e-Shahadat).

**Q: What is the risk level in the AI output?**
A: low / medium / high / urgent — determined by the LLM based on the case description, applicable laws, and urgency selected by the user.

---

## Detailed Intake Logic

This is the actual control flow of the legal intake module, from the browser to the AI pipeline and back into the saved case document.

At a high level, the intake flow has 3 layers:

- Frontend capture and local case-type guess
- Backend intake validation and clarification
- Retrieval-grounded AI analysis and post-processing

### 1. Intake session starts

When the client begins intake, the backend creates a new intake record with a unique session token.

- `POST /intake/start` creates the session.
- The intake document stores `step1` through `step5`, `clarification_qa`, and an `ai_structured_case` placeholder.
- The token is kept on the frontend so the user can continue later without losing progress.

### 2. Step 1: role and province

The first screen collects the user's role and province.

- Role is used for the UI and context.
- Province is important for jurisdiction and later province-aware retrieval.
- This step is saved immediately with `PATCH /intake/{token}/step/1`.

The province choice is not decorative. It is passed into the AI state so retrieval can be filtered and the final answer can reflect the correct legal jurisdiction.

### 3. Step 2: user describes the issue

This is the most important input in the whole flow.

The user can enter the description in three ways:

- Typed English
- Romanized Urdu
- Urdu script
- Voice input, which is transcribed first and then inserted into the same description field

The frontend runs a lightweight browser-side classifier called `quickClassify()` while the user types. This is not an LLM call. It is a regex-based heuristic that tries to guess the case type instantly so the UI can prefill the category before the backend receives the request.

That means the user sees immediate feedback, but the backend still validates the case type later, so the browser guess is only a fast first pass.

The reason this matters is simple: the wrong case type changes the legal template, the clarification questions, the retrieval collection, and eventually the final summary.

### 4. Voice input path

If the user speaks instead of typing, the flow is:

1. The browser records audio with `MediaRecorder`.
2. The audio is converted to a WAV blob in the frontend.
3. The blob is sent to `POST /voice/transcribe`.
4. The backend uses `faster-whisper` to produce the transcript.
5. The transcript is copied into the intake description field.
6. `quickClassify()` runs again on the transcript so the case type is still detected early.

So voice is not a separate AI pipeline. It is just a transcription pre-step before the same intake logic continues.

### 5. Step 2 save and Step 3 clarification

When the user continues, the frontend saves two things:

- The case type and urgency in step 2
- The incident description in step 3

After that, the frontend immediately asks the backend for the first clarification question with `POST /intake/{token}/clarify`.

The clarification logic is intentionally conservative:

- The service inspects the description and chooses the most likely case type.
- It then uses a domain-specific template for criminal, family, civil, or constitutional matters.
- The LLM asks only one missing fact at a time.
- The flow stops once enough information is available or after the maximum number of rounds.

Important note: the current service code allows up to 4 clarification rounds, even though one route docstring still says 2. The service logic is the real behavior.

In the actual service implementation, the question selection is driven by the case type and the current Q&A history. The service builds a prompt that includes:

- The inferred case type
- The province
- The user's description
- All previous clarification questions and answers
- A domain template for the current legal area

The model is asked to return only one question or the word `DONE`. That keeps the interaction focused and prevents the user from being overloaded with a long interview.

### 6. Step 4 and step 5 data collection

The later steps gather extra context such as:

- Evidence availability
- Evidence description and uploads
- Desired outcome

This data is not just cosmetic. It improves the final AI summary and the case record that lawyers later see.

The evidence upload step also saves files in the backend so they can be attached to the intake session. Those files are not directly used by the summary generator in the current flow, but they are preserved for the case file and future review.

### 7. Convert to case

When the intake is complete, the user hits conversion.

`POST /intake/{token}/convert` does the following:

1. Verifies that all intake steps are present.
2. Reads the saved province, case type, description, and clarification Q&A.
3. Runs a backend case-type verification step.
4. Creates the case document.
5. Launches background AI jobs for embedding and lawyer matching.
6. Runs the intake AI graph to generate the structured legal summary.

The important detail here is that conversion is not just a save operation. It is the point where the intake becomes a real case object and the system produces the first AI-backed legal analysis.

### 8. Why the description is classified twice

The intake module classifies the case twice on purpose.

First classification:

- Happens early in the UI with `quickClassify()`.
- Gives the user instant feedback.
- Helps prefill the category before saving step 2.

Second classification:

- Happens in the backend inside `_ai_classify_case_type()`.
- Uses keyword scoring first.
- Falls back to an LLM only if the keyword signal is weak.
- Can correct the user's selected category.

This double-check matters because the wrong case type would send the user through the wrong clarification template and the wrong legal retrieval collection.

It also helps with auditability. The case document can keep both values, so later you can see whether the user selected the wrong category or whether the system corrected it.

### 9. What the intake graph actually does

The backend `intake_graph` is smaller than the chat graph, but it is still multi-stage.

1. `retrieval_node` searches the legal knowledge base using the query, province, and case type.
2. `retrieval_grader_node` scores the retrieved chunks and decides whether the results are good enough.
3. If the score is too weak, the graph can retry retrieval once instead of immediately generating an answer.
4. `intake_node` sends the query and retrieved law context to the LLM and asks for a structured legal analysis.
5. `intake_hallucination_node` checks whether the recommended actions are grounded in the retrieved sections.

That means the system does not blindly generate a legal answer. It first searches, then filters, then generates, then validates.

### 10. What the intake node returns

The intake node uses a structured output model, so the result has a fixed shape.

- `summary`: one paragraph explaining the user's legal position
- `applicable_laws`: relevant Pakistani statutes or sections
- `recommended_actions`: practical next steps for the client
- `risk_level`: low, medium, or high

The node also serializes the result to JSON before storing it in the intake record. That makes the output easy to reuse in the frontend, in the case document, and in later lawyer-facing features.

### 11. Why hallucination checking is needed

The grounding step is there because even a good LLM can suggest actions that are too generic or too confident.

The grounding node:

- Compares the recommended actions with the retrieved chunks
- Decides whether the actions are supported by the law text
- Marks the answer as grounded or not grounded
- Adds a caution to the summary if support is weak

If grounding is weak, the system does not throw the answer away. It keeps the answer, but adds a warning so the client is not misled into thinking the output is a final legal opinion.

---

## AI Technologies Used

Here is the exact AI stack used in the intake flow.

### 1. Browser-side keyword classifier

Used in the frontend `quickClassify()` function.

- Runs locally in the browser.
- No network request.
- Uses regex rules for English, Romanized Urdu, and Urdu script.
- Purpose: instant feedback only.

This is not a neural model. It is a lightweight heuristic layer.

### 2. Backend keyword scoring

Used in `backend/app/ai/nodes/classifier_node.py` and in intake service classification.

- Same idea as the browser classifier, but with broader signal tables.
- Detects family, criminal, civil, and constitutional terms.
- Also supports Urdu script and Romanized Urdu.
- Used as the first and cheapest AI decision layer.

### 3. LLM fallback for ambiguous cases

When the keyword score is not strong enough, the backend calls an LLM.

- `get_llm()` is the main model selector.
- `get_fast_llm()` is used for quicker tasks.
- The system can use Groq or Gemini Flash depending on configuration.
- The code is designed to keep working even if one provider is unavailable.

In this project, the LLM is used for:

- Clarification question generation
- Case type fallback classification
- Final structured intake summary

The project uses two practical LLM modes:

- A faster model for classification and short control tasks
- A fuller model for longer legal generation tasks

That split keeps the common path cheap while still allowing a richer answer when the system reaches the generation stage.

### 4. Faster-Whisper for voice transcription

Used at `POST /voice/transcribe`.

- Converts speech to text.
- Lets users speak their legal issue instead of typing.
- Supports the same downstream intake flow after transcription.

### 5. LangGraph for the intake AI pipeline

The intake summary is not generated in one raw prompt. It is orchestrated as a graph.

For intake, the graph is:

- `retrieval_node`
- `retrieval_grader_node`
- `intake_node`
- `intake_hallucination_node`

This means the system first finds relevant legal material, checks if it is relevant enough, generates the answer, and then validates grounding before returning the result.

The reason for using LangGraph instead of a single prompt is control. A graph makes it possible to:

- Retry retrieval when the first search is weak
- Separate scoring from generation
- Add validation after generation
- Keep state across steps in a predictable way

### 6. ChromaDB for legal retrieval

The AI does not answer from memory alone.

- ChromaDB stores the legal text chunks.
- The intake pipeline retrieves relevant statutes before generation.
- This reduces hallucination and improves legal accuracy.

The stored chunks are legal passages, not raw whole books. That helps the model work with smaller, more relevant pieces of law instead of a huge document blob.

### 7. BM25 + semantic retrieval

The retriever combines two search styles:

- BM25 keyword retrieval for exact statutory wording and section references
- Semantic retrieval for meaning-based matches

This hybrid setup is important in legal work because users often describe issues in plain language while the law is written in formal statutory language.

BM25 is useful when the user mentions exact legal words like `FIR`, `PPC 302`, or `maintenance`. Semantic search is useful when the user describes the facts in natural language like "my husband threw me out" or "the landlord is threatening eviction".

Using both gives the best chance of finding the right law section the first time.

### 8. multilingual-e5 embeddings

The semantic side uses `intfloat/multilingual-e5-base`.

- Supports English and Urdu better than a monolingual model.
- Used for legal chunk embeddings.
- Also used later for case embedding so lawyer matching can use semantic similarity.

This model choice matters because the intake flow has to work in English, Urdu script, and Romanized Urdu. A multilingual embedding model gives the semantic retriever a much better chance of aligning user language with legal text.

### 9. Structured JSON output

The final intake answer is not free-form chat text.

The AI returns structured fields such as:

- Summary
- Applicable laws
- Recommended actions
- Risk level

That structure makes the result easier to save, display, and reuse for lawyer matching.

It also makes downstream automation easier because the frontend can render each field separately instead of trying to parse a free-form paragraph.

---

## What Runs Where

| Layer | Runs Where | Purpose |
|---|---|---|
| `quickClassify()` | Browser | Instant category guess while typing |
| `MediaRecorder` + transcript submission | Browser | Collect voice input |
| `faster-whisper` | Backend | Speech-to-text |
| `_score_query()` | Backend | Fast legal category scoring |
| LLM fallback | Backend | Resolve ambiguous classification or ask clarification questions |
| `intake_graph` | Backend | Retrieval + grounded intake summary |
| `multilingual-e5` | Backend | Semantic embeddings for legal chunks and cases |
| ChromaDB | Backend storage | Legal text retrieval |
| Background `asyncio.create_task()` jobs | Backend | Case embedding and lawyer matching without blocking the user |

The intake flow also benefits from this separation because the user gets the case created immediately, while heavier semantic work continues in the background.

---

## Why This Flow Is Designed This Way

The intake flow is built in layers so the system stays fast and usable:

- Cheap checks happen first.
- Expensive model calls happen only when needed.
- The browser gives instant feedback.
- The backend still re-validates everything for safety.
- Retrieval is used before generation so the output is grounded in actual legal sources.
- Background tasks keep the user from waiting for non-essential work.

In short, the system is trying to balance three things:

- Speed for the user
- Accuracy for legal classification
- Grounded AI output with citations and legal context

For a legal product, that balance is important because a fast but ungrounded answer is worse than a slightly slower answer that is tied to actual statutes and case context.

---

## One-Line Flow Summary

Browser input or voice transcript → local category guess → save intake steps → AI clarification if needed → backend case-type verification → retrieval-based intake summary → case embedding and lawyer matching in the background.

---

## Implemented Details Not Previously Documented

The following behaviors are implemented in code but were not explicitly listed earlier in this document. They are included here with the files that implement them so you can review the exact code paths.

- **Auth required for intake and voice endpoints:** intake and voice routes require authenticated users (client role). See `backend/app/api/v1/routes/intake.py` and `backend/app/dependencies.py`.
- **Transcription rate limit & upload size enforcement:** `/voice/transcribe` enforces a 10 MB maximum and a rate limit. See `backend/app/api/v1/routes/voice.py`.
- **Evidence storage and metadata:** evidence files are saved to `uploads/evidence/{token}/` and metadata is pushed to the intake document (`evidence_files`). See `backend/app/services/intake_service.py` and `backend/app/repositories/intake_repo.py`.
- **Step validation and current_step advancement:** `save_step()` enforces required fields per step and `update_step()` uses a `$max` update so `current_step` never moves backward. See `backend/app/services/intake_service.py` and `backend/app/repositories/intake_repo.py`.
- **Clarification prompt composition:** clarification prompts include inferred case type, province, description, and previous Q&A and use domain templates; the LLM returns one question or `DONE`. See `backend/app/services/intake_service.py`.
- **Retrieval retry budget (intake-specific):** the intake graph uses a tighter retrieval retry budget and a relevance threshold before retrying (see intake edge routing constants). See `backend/app/ai/graph/edges.py`.
- **Retrieval grader LLM step:** a fast LLM grades which retrieved chunks are relevant; failure falls back to a conservative low-relevance result. See `backend/app/ai/nodes/retrieval_grader_node.py`.
- **Decision engine arbitration & BM25 confidence cap:** the arbitration logic selects among LLM, cache, and BM25 evidence and caps BM25 confidence to avoid overweighting keyword matches. See `backend/app/ai/decision_engine.py`.
- **Grounding check appends caution:** if `intake_hallucination_node` finds recommended actions are not well-supported by retrieved chunks, it appends a caution to the `summary` rather than discarding results. See `backend/app/ai/nodes/intake_hallucination_node.py`.
- **Structured, typed intake output:** `intake_node` returns a Pydantic-validated JSON shape (`summary`, `applicable_laws`, `recommended_actions`, `risk_level`). See `backend/app/ai/nodes/intake_node.py`.
- **Embeddings prefix convention and background tasks:** `multilingual-e5` embeddings use `passage:`/`query:` prefixes; embedding and lawyer-matching are run as non-blocking background `asyncio.create_task()` jobs. See `backend/app/ai/pipelines/retriever.py` and `backend/app/services/intake_service.py`.
- **Frontend autosave and resume token:** the frontend stores the intake token in `localStorage` under `aai-intake-token`, resumes sessions on mount, and shows a local autosave toast. See `frontend/src/components/client/ModIntake.jsx`.
- **Whisper service singleton and warmup:** `whisper_service` is a process-wide singleton (`faster-whisper`) that is warmed up at startup; transcription uses an internal lock to serialise heavy CPU work. See `backend/app/services/whisper_service.py` and `backend/app/main.py`.

If you want, I can move these bullets into the top section of this presentation or turn them into linked subsections with code excerpts. Tell me which format you prefer.
