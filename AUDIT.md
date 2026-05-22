# Attorney.AI — Code Audit Report

**Date:** May 9, 2026
**Auditor:** Syed Ahmad Ali Naqvi
**Scope:** Full backend codebase — AI pipeline, services, repositories, models, security, WebSockets, API routes

---

## Summary

33 distinct issues identified across the AI pipeline, services layer, security, and data layer. The systemic themes are:

1. **Silent exception swallowing** — bare `except: pass` or `except: return default` with no logging throughout the codebase
2. **State fields defined but never wired** — `messages`, `specialization_embedding`, `matched_lawyers` in API responses, `gatekeeper_node`
3. **No ownership validation on WebSockets** — session hijacking is trivial
4. **Non-atomic MongoDB operations** — ratings, signatures, concurrent writes
5. **Fail-open instead of fail-closed** — hallucination check, relevance grading, and clarification all default to "success" on failure

---

## Severity Breakdown

| Severity | Count |
|----------|-------|
| CRITICAL | 7 |
| HIGH | 11 |
| MEDIUM | 15 |

---

## CRITICAL — Will cause wrong behavior or data loss

### 1. Conversation history is never read by any node

**Files:** `backend/app/ai/graph/state.py:46`, all files in `backend/app/ai/nodes/`
**Category:** Architecture

The `AgentState` defines a `messages` field with `Annotated[list[BaseMessage], operator.add]` for append-only history. `chat_socket.py` adds a `HumanMessage` for each turn, and `MemorySaver` is wired as the checkpointer in `supervisor.py:89`.

However, **not a single node reads `state["messages"]`**. Every node only reads `state["query"]` (the current turn's input). Grep for `messages` across all node files returns zero hits.

**Impact:**
- The chatbot has zero conversation context. Each message is treated in complete isolation.
- Multi-turn refinement, follow-ups, and context carryover are impossible.
- The HITL clarification flow is broken: if fact_gap_node asks "did you file an FIR?" and the user replies "no", the next graph invocation sees `query="no"` with no prior context. Triage classifies "no" as off-topic.
- The `MemorySaver` checkpointer is dead code.

**Fix:** At minimum, `triage_node`, `fact_gap_node`, and `generation_node` must read `state["messages"]` and include prior turns in their LLM context.

---

### 2. `intake_hallucination_node` returns `is_grounded=True` on exceptions

**File:** `backend/app/ai/nodes/intake_hallucination_node.py`
**Category:** Exception handling

When the grounding-check LLM call fails, the `except` block returns:
```python
except Exception:
    return {"is_grounded": True}
```

This is the exact opposite of fail-safe. Exceptions in validation are treated as successful validation.

**Impact:** Unverified legal recommendations (applicable laws, recommended actions, risk levels) pass through to users without any grounding check when the LLM is unavailable or errors out.

**Fix:** Return `{"is_grounded": False}` on exception. Add logging.

---

### 3. WebSocket session has no ownership check

**File:** `backend/app/websockets/chat_socket.py:98`
**Category:** Authorization

On reconnect, the existing session is loaded from MongoDB but **never validated** against the authenticated `user_id`:
```python
session = await chat_repo.find_by_session(session_id)
if not session:
    await chat_repo.insert({...})  # New session created with correct client_id
    session = {}
# BUG: No check that session["client_id"] == user_id for existing sessions
```

**Impact:** Any authenticated user who guesses or intercepts a `session_id` can:
- Read another user's chat history (via the session's cached state)
- Inject messages into their session
- Receive AI responses intended for another user

**Fix:**
```python
session = await chat_repo.find_by_session(session_id)
if session and session.get("client_id") != user_id:
    await websocket.close(code=4003)
    return
```

---

### 4. Lawyer matching KYC bypass in final fallback

**File:** `backend/app/services/lawyer_service.py`
**Category:** Security / Compliance

The last-resort fallback in `match_lawyers_for_case()` queries:
```python
all_lawyers = await user_repo.find_many(
    {"role": "lawyer", "is_active": True},  # NO KYC CHECK
    limit=top_n * 4,
)
```

This removes the `kyc_verified: True` filter entirely. Unverified lawyers (potentially fake profiles) can be matched to real clients seeking legal help.

The `"(unverified)"` string appended to `match_reason` is cosmetic — the frontend may not parse or display it.

**Impact:** Bypass of the KYC verification gate. Clients could be matched with unverified or fraudulent lawyer profiles.

**Fix:** Always enforce `kyc_verified: True`, or return an empty result set with a clear message rather than silently degrading.

---

### 5. Lawyer rating update is non-atomic (race condition)

**File:** `backend/app/services/lawyer_service.py`
**Category:** Data integrity

Rating recalculation is done in Python application code, not atomically in MongoDB:
```python
total = lp.get("total_reviews", 0)
current_avg = lp.get("rating", 0.0)
new_avg = round((current_avg * total + stars) / (total + 1), 2)
await user_repo.update_rating(lawyer_id, new_avg, total + 1)
```

**Impact:** Two concurrent reviews cause a lost-update:
1. T1 reads: rating=4.0, total=10
2. T2 reads: rating=4.0, total=10
3. T1 writes: new_avg=3.98, total=11
4. T2 writes: new_avg=4.09, total=11 (overwrites T1 — first review is lost)

**Fix:** Use MongoDB's aggregation pipeline update:
```python
await user_repo.col.update_one(
    {"_id": lawyer_id},
    [{"$set": {
        "lawyer_profile.rating": {
            "$divide": [
                {"$add": [
                    {"$multiply": ["$lawyer_profile.rating", "$lawyer_profile.total_reviews"]},
                    stars
                ]},
                {"$add": ["$lawyer_profile.total_reviews", 1]}
            ]
        },
        "lawyer_profile.total_reviews": {"$add": ["$lawyer_profile.total_reviews", 1]}
    }}]
)
```

---

### 6. Agreement signature field name mismatch

**Files:** `backend/app/services/agreement_service.py`, `backend/app/repositories/agreement_repo.py`
**Category:** Logic bug

`agreement_service.py` builds the signature dict as:
```python
{"method": method, "data": signature_data}
```

But `agreement_repo.update_party_signature()` reads:
```python
"parties.$.signature_method": signature["method"],
"parties.$.signature_data": signature["data"],
```

The dict key is `"data"` but the MongoDB update targets a field called `"signature_data"`. This mismatch means signatures may silently fail to persist or write to the wrong field.

**Fix:** Align the dict keys or the MongoDB field names.

---

### 7. LLM clarification failure silently returns `done: True`

**File:** `backend/app/services/intake_service.py:167-169`
**Category:** Exception handling / Reliability

If the LLM call in `get_clarification()` throws (API timeout, rate limit, model error):
```python
try:
    llm = get_llm()
    response = llm.invoke([...])
    text = response.content.strip()
except Exception:
    await intake_repo.save_clarification_qa(token, qa_list)
    return {"question": None, "done": True, "round": answered_rounds}
```

The exception is swallowed with no logging, and the function returns `done: True`, forcing the intake to proceed as if clarification succeeded.

**Impact:** Users are pushed into case conversion without gathering critical facts. No indication that the AI service failed.

**Fix:** Return `{"question": None, "done": False, "error": "AI service temporarily unavailable"}` and log the exception.

---

## HIGH — Significant quality or security degradation

### 8. BM25 has no province filter

**File:** `backend/app/ai/pipelines/retriever.py:59-83`
**Category:** Retrieval quality

`build_retriever()` applies a `where_filter` with province to the ChromaDB semantic retriever, but BM25 receives **no province filter**:
```python
bm25 = _bm25(collection_name)  # All 1,735+ chunks, no province filter

return EnsembleRetriever(
    retrievers=[bm25, semantic],
    weights=[0.6, 0.4],  # BM25 has 60% weight
)
```

BM25 has 60% weight in the ensemble, so wrong-province statutes dominate the merged results.

**Impact:** A Punjab criminal case query receives Sindh-specific or Balochistan-specific law sections. Jurisdiction-specific legal advice is corrupted.

**Fix:** Post-filter BM25 results to only keep `doc.metadata.get("province") in (province, "federal")` before passing to EnsembleRetriever.

---

### 9. Retrieval grader fallback inflates scores

**File:** `backend/app/ai/nodes/retrieval_grader_node.py:56-59`
**Category:** Exception handling

When the LLM grading call fails:
```python
except Exception:
    graded = to_grade       # Keep ALL chunks (ungraded)
    score  = round(min(len(to_grade) / 10.0, 1.0), 3)  # 8 chunks = 0.8 score
```

The fallback scores based on chunk count, not quality. 8 irrelevant chunks produce a 0.8 score, which passes the 0.75 relevance threshold and proceeds to answer generation.

**Impact:** When the grading LLM fails, garbage retrieval results are passed to the generation node with an artificially high relevance score.

**Fix:** Fallback score should be `0.0` (fail closed), not a count-based proxy.

---

### 10. Generation confidence defaults to 0.7 on parse failure

**File:** `backend/app/ai/nodes/generation_node.py:107-115`
**Category:** LLM output handling

The prompt instructs the LLM to output confidence JSON on the last line. If parsing fails:
```python
confidence = 0.7  # Hardcoded fallback

try:
    last       = json.loads(lines[-1])
    confidence = float(last.get("confidence", 0.7))
except (json.JSONDecodeError, IndexError, ValueError):
    pass  # Falls through with 0.7
```

**Impact:** Any response where the LLM omits or malforms the JSON confidence line gets 0.7 — artificially high for a legal AI where the system couldn't even determine its own confidence.

**Fix:** Default to `0.3` or lower. Log parse failures.

---

### 11. `decode_token` returns `{}` instead of `None` on failure

**File:** `backend/app/core/security.py`
**Category:** Authentication

```python
def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return {}  # Truthy in Python!
```

`{}` is truthy in Python. Code like `if payload:` passes for invalid tokens. Current callers happen to check `payload.get("sub")`, but this is a latent auth bypass waiting for any future code that checks truthiness.

**Fix:** Return `None` on failure, or raise an exception.

---

### 12. Fire-and-forget tasks with no error tracking

**File:** `backend/app/services/intake_service.py:148-149, 162, 171`
**Category:** Reliability

```python
asyncio.create_task(_embed_case(case_id, description))
asyncio.create_task(_auto_match_lawyers(case_id))
```

Both background tasks have bare `except: pass` inside. If embedding or lawyer matching fails:
- Semantic lawyer matching silently falls back to the degraded path
- No admin notification, no retry mechanism, no logging
- The main flow completes successfully with no indication of failure

**Fix:** Add `task.add_done_callback()` for error logging. Or use a task queue with retry.

---

### 13. Dead WebSocket connections never cleaned up

**File:** `backend/app/websockets/manager.py`
**Category:** Resource leak

`send_to_user()` catches send exceptions with bare `except: pass` but never removes the dead connection from `_connections`:
```python
async def send_to_user(self, user_id: str, message: dict) -> None:
    for ws in self._connections.get(user_id, []):
        try:
            await ws.send_json(message)
        except Exception:
            pass  # Dead socket stays in the list
```

**Impact:** Dead sockets accumulate. All future sends to that user silently fail on every dead socket before (maybe) reaching a live one.

**Fix:** Remove dead connections on send failure:
```python
except Exception:
    self.disconnect(user_id, ws)
```

---

### 14. `gatekeeper_node.py` is dead code

**File:** `backend/app/ai/nodes/gatekeeper_node.py`
**Category:** Code quality

The file defines a `gatekeeper_node` function that duplicates `triage_node`'s off-topic detection. It is importable but **never added to either graph** in `supervisor.py`.

**Fix:** Delete the file.

---

### 15. `fact_delta` semantic mismatch

**Files:** `backend/app/ai/nodes/fact_gap_node.py:66`, `backend/app/ai/graph/edges.py`
**Category:** State logic

The state comment says `fact_delta` is "new facts discovered since the last fact_gap check" (a delta), but the code sets it to `len(known_facts)` (an absolute count) or `0`:
```python
return {
    "fact_delta": len(known_facts),  # Not a delta — it's a total count
    ...
}
```

Edge routing logic in `edges.py` checks `fact_delta == 0` to decide on retries, assuming it's a delta. The mismatch can cause incorrect convergence decisions.

**Fix:** Either rename the field to `fact_count` and update edge logic, or compute an actual delta.

---

### 16. CNIC encryption key can't be rotated

**File:** `backend/app/core/security.py`
**Category:** Encryption / Secrets management

```python
def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.encryption_key.encode())
    return _fernet
```

The Fernet key is cached globally with no versioning. If the key is rotated in environment variables, all previously encrypted CNIC values become permanently unrecoverable.

**Fix:** Implement key versioning — store a key ID alongside encrypted values, support decryption with old keys during migration.

---

### 17. Password reset token relies only on MongoDB TTL

**File:** `backend/app/db/indexes.py`, `backend/app/services/auth_service.py`
**Category:** Security

Password reset tokens have a 1-hour TTL index in MongoDB, but the application code does `find_one` without checking the token's creation timestamp. It trusts that MongoDB's background TTL thread has already deleted expired tokens.

**Impact:** MongoDB's TTL thread runs every 60 seconds by default. Under load, cleanup can be delayed further. During that window, expired tokens remain valid.

**Fix:** Add an application-level expiry check:
```python
if token_doc["created_at"] + timedelta(hours=1) < datetime.utcnow():
    raise AppValidationError("Reset token expired")
```

---

### 18. Query expansion is unvalidated

**File:** `backend/app/ai/nodes/retrieval_node.py:43-56`
**Category:** Retrieval quality

`_expand_query()` appends an LLM-rewritten query without validating the output:
```python
try:
    rewritten = result.content.strip()
    return f"{query} {rewritten}"
except Exception:
    return query
```

If the LLM hallucinates statute names that don't exist in the corpus (e.g., "PPC Section 99"), BM25 wastes capacity searching for non-existent terms, diluting the original query's signal.

**Fix:** Only append the rewrite if it contains at least one recognized statute keyword (`PPC`, `CrPC`, `MFLO`, etc.), otherwise use the original.

---

## MEDIUM — Incorrect behavior in edge cases

### 19. Content truncation too aggressive

**Files:** `backend/app/ai/nodes/retrieval_grader_node.py:34` (300 chars), `backend/app/ai/nodes/generation_node.py:75` (400 chars)
**Category:** Retrieval / generation quality

Pakistani legal sections (PPC, CrPC) are dense. A single section like PPC 302 with punishment scales, exceptions, and conditions easily runs 600+ words. Truncating at 300 chars for grading means the grader often sees an incomplete section and marks it irrelevant.

**Fix:** Grade with 500+ chars; generate with 600-800 chars.

---

### 20. Default case_type is `"criminal"` instead of something neutral

**File:** `backend/app/websockets/chat_socket.py:40`
**Category:** Configuration bias

```python
case_type = data.get("case_type") or session.get("case_type") or "criminal"
```

Ambiguous queries default to criminal law, biasing retrieval toward PPC when the user's issue might be civil, family, or constitutional.

**Fix:** Default to `"civil"` (the broadest category) or use `"unknown"` and let triage decide.

---

### 21. Intake steps not validated for sequential order

**File:** `backend/app/services/intake_service.py`
**Category:** Logic bug

`save_step()` validates required fields per step but does not enforce that steps are completed sequentially. A user can POST step 5 before step 1 and the system accepts it.

**Fix:** Validate `step == current_step + 1` or `step <= current_step + 1`.

---

### 22. `case_embedding` never generated for API-created cases

**File:** `backend/app/services/case_service.py`
**Category:** Missing feature

```python
"case_embedding": None,  # TODO: AI -- embed case description at creation
```

Cases created directly via the API (not through intake) never get an embedding. Semantic lawyer matching falls back to the degraded non-semantic path for these cases.

---

### 23. `specialization_embedding` on LawyerProfile is never populated

**File:** `backend/app/models/user.py:19`
**Category:** Dead code

`specialization_embedding: list[float] | None = None` is defined in the model but no service ever writes to it. Orphaned field.

---

### 24. `matched_lawyers` on CaseDocument stored but not exposed via API

**Files:** `backend/app/services/intake_service.py`, `backend/app/schemas/case.py`
**Category:** Dead code

`matched_lawyers` is computed and cached on the case document during intake conversion, but `CaseResponse` does not include the field. The frontend can never access it.

---

### 25. Agreement concurrent signing race condition

**File:** `backend/app/services/agreement_service.py`
**Category:** Data integrity

Two parties signing simultaneously can both pass the "already signed?" check, then both call `update_party_signature()`. The second write overwrites the first.

**Fix:** Use MongoDB's `$cond` or findAndModify with a filter that includes `parties.$.signed: false`.

---

### 26. Missing `updated_at` on document/notification/chat inserts

**Files:** `backend/app/services/document_service.py`, `backend/app/services/notification_service.py`, `backend/app/repositories/chat_repo.py`
**Category:** Data integrity

Multiple services create MongoDB documents without setting `updated_at`, despite the model defining the field. Queries sorting or filtering by `updated_at` will miss these documents.

---

### 27. Follow-up questions are vague (two sub-issues)

**Files:** `backend/app/ai/nodes/fact_gap_node.py`, `backend/app/services/intake_service.py`
**Category:** AI quality

**27a. `fact_gap_node` bypasses after just 1 attempt:**
```python
if complexity == "simple" or len(known_facts) >= 2 or attempts >= 1:
    return {"needs_clarification": False}
```
After one single question, the chat graph never asks again — even if the user's reply was "I don't know."

**27b. Prompts don't instruct the LLM to analyze the user's description:**
Both `_SYSTEM_TEMPLATE` and `_CLARIFY_SYSTEM` tell the LLM to pick from a template list but never say "read the description, identify what the user already told you, then ask about the most critical fact that's MISSING." No few-shot examples are provided. The result is generic template echoes like "Have you filed an FIR?" instead of description-grounded questions.

---

### 28. 8-word heuristic bypasses legally thin queries

**File:** `backend/app/ai/nodes/fact_gap_node.py:71-78`
**Category:** Logic bug

```python
has_description = len((state.get("query") or "").split()) >= 8

if (has_province or has_case_type) and has_description:
    return {"needs_clarification": False}
```

"My neighbor hit me last week in Lahore" is 9 words with province known — bypasses clarification entirely. No FIR status, no injury details, no relationship info gathered.

---

### 29. Case status never transitions

**File:** `backend/app/services/case_service.py`
**Category:** Missing business logic

No service function validates or drives case status transitions. Cases created as `OPEN` stay `OPEN` forever. There is no state machine, no allowed-transitions map, no status lifecycle.

---

### 30. Intake step validation accepts empty strings

**File:** `backend/app/services/intake_service.py`
**Category:** Input validation

```python
missing = [f for f in required if not data.get(f)]
```

`not ""` is `True`, so this catches empty strings. But `not data.get(f)` also catches `0` and `False`. More importantly, whitespace-only strings like `"   "` pass validation.

**Fix:**
```python
missing = [f for f in required if not str(data.get(f, "")).strip()]
```

---

### 31. Error responses leak internal details

**File:** `backend/app/api/v1/routes/voice.py`
**Category:** Security

```python
raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")
```

The raw exception message from `faster-whisper` is returned to the client. This could leak file paths, library versions, or stack trace fragments.

**Fix:** Log the exception server-side, return a generic message to the client.

---

### 32. Temp file leak in document generation

**File:** `backend/app/services/document_service.py`
**Category:** Resource leak

If `subprocess.run` (LibreOffice conversion) throws an exception, `output_docx.unlink()` is never reached. Temp files accumulate on disk.

**Fix:** Wrap in `try/finally`:
```python
try:
    await asyncio.to_thread(subprocess.run, [...])
finally:
    output_docx.unlink(missing_ok=True)
```

---

### 33. Admin endpoint defined twice

**File:** `backend/app/api/v1/routes/admin.py`
**Category:** Code quality

`POST /lawyers/embed-all` is defined twice with the same function name. FastAPI silently registers only the second definition. The first function becomes unreachable dead code.

---

## RAG-Specific Issues (Detailed)

These overlap with issues above but provide additional RAG-focused detail.

### R1. BM25 corpus is frozen at startup

**File:** `backend/app/ai/pipelines/retriever.py:48-56`

`_bm25()` is `@lru_cache(maxsize=6)`. The BM25 index is built once on first call and cached for the process lifetime. If new chunks are added to ChromaDB, BM25 won't reflect them until the server is restarted.

### R2. `clarification_node.py` asks redundant meta-questions

**File:** `backend/app/ai/nodes/clarification_node.py`

This node is triggered when `relevance_score < 0.75` (poor retrieval). Its prompt asks about province, case_type, and civil-vs-criminal distinction — but triage_node already sets these fields. When they're already known, this node asks redundant questions, wasting a clarification round.

### R3. No constitutional collection exists

The `CASE_TYPE_TO_COLLECTION` map in `retriever.py` maps `"constitutional"` to `"constitutional_collection"`, but the knowledge base pipeline only ingests criminal, civil, and family law PDFs. Constitutional queries will hit an empty or non-existent collection.

---

## Follow-Up Question Issues (Detailed)

### F1. No few-shot examples in clarification prompts

Neither `_CLARIFY_SYSTEM` (intake) nor `_SYSTEM_TEMPLATE` (chat) includes a single example of a good, specific question vs a bad, generic one. For a task where specificity is the main goal, this is the highest-leverage fix available — pure prompt engineering, zero code changes.

**Bad (current behavior):** "Have you filed an FIR (First Information Report)?"
**Good (desired behavior):** "You mentioned your landlord beat you — did you sustain visible injuries, and if so, did you get a medical examination? A medical report is key evidence for charges under PPC Section 325."

### F2. Intake clarification loop has no cap on unanswered questions

**File:** `backend/app/services/intake_service.py`

`_MAX_CLARIFY_ROUNDS = 4` counts only ANSWERED rounds. A user could spam the endpoint with blank answers, accumulating unlimited unanswered questions in `qa_list`. Each LLM call generates a new question that is appended but never answered.

---

## Recommended Fix Priority

| Priority | Issues | Effort | Impact |
|----------|--------|--------|--------|
| P0 — Fix immediately | #3 (WebSocket auth), #2 (hallucination fail-open), #4 (KYC bypass) | Low | Security |
| P1 — Fix this sprint | #1 (messages), #7 (clarification fail), #5 (rating race), #8 (BM25 province) | Medium | Core functionality |
| P2 — Fix next sprint | #6 (signature mismatch), #9 (grader fallback), #10 (confidence default), #11 (decode_token) | Low-Medium | Correctness |
| P3 — Backlog | #12-18 (error tracking, dead code, key rotation, TTL) | Medium | Reliability |
| P4 — Nice to have | #19-33 (truncation, defaults, validation, dead fields) | Low | Polish |