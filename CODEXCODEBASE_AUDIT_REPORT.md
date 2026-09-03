# Deep Read-Only Codebase Audit

## 1. Confirmed issues, prioritized

No Critical issue survived the second pass. All High findings below were rechecked against callers, middleware, configuration, and tests.

### 1. Password recovery UI never calls the working backend

- Severity: High
- Status: CONFIRMED
- Location: `frontend/src/app/(auth)/reset-password/page.jsx`, `ForgotPw`; `backend/app/utils/email.py`; `frontend/src/lib/api.js`
- Evidence: “Send Reset Link” only executes `setSub(1)`; “Set New Password” only executes `setSub(2)`. The page never reads the `token` query parameter or imports `authForgotPassword`/`authResetPassword`.
- Execution path investigated: Login routes to `/reset-password` → backend emails `/reset-password?token=...` → working API wrappers exist → neither is called by the page.
- Why genuine: The UI always reports success without sending an email or changing a password. Backend reset tests do not exercise this frontend.
- Recommended fix: Implement controlled email/password fields, call both API functions, read and validate the URL token, and show backend errors and expired-token states.

### 2. The multiplayer game uses a client-supplied guest identifier as authentication

- Severity: High
- Status: CONFIRMED
- Location: `dominations/server/src/rooms/GameRoom.ts`, `GameRoom.onJoin`; `dominations/server/src/services/AuthService.ts`, `getOrCreateGuestUser`; `dominations/client/src/services/NetworkService.ts`
- Evidence: The browser generates an identifier with `Math.random`, stores it in `localStorage`, and sends it as `odUserId`. `onJoin` trusts that value and loads the corresponding account. There is no `onAuth`. `onLeave` persists the resulting state to that user’s base.
- Execution path investigated: `server/index.ts` registers the public `game` room → client `joinOrCreate` supplies `odUserId` → `getOrCreateGuestUser` loads that identity → building/resource commands mutate state → `onLeave` saves it.
- Why genuine: Possession of another guest ID is sufficient to load and overwrite that user’s persisted base. Multiple rooms using the same ID also produce last-save-wins corruption.
- Recommended fix: Issue server-generated, cryptographically random session credentials; authenticate in `onAuth`; bind the authenticated subject to the loaded user; use versioned/conditional persistence.

### 3. AI usage limits advertised by subscriptions are not enforced

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/api/v1/routes/ai.py`, `ai_query`, `ai_research`, `ai_query_stream`, `ai_draft_stream`, `compare_models`; `backend/app/websockets/chat_socket.py`, `chat_endpoint`
- Evidence: These routes require authentication but have no limiter, quota, or subscription check. `QueryRequest` and `ResearchRequest` have no message/history length constraints. The WebSocket loop accepts repeated messages without application-level size, turn, token, or cost limits.
- Execution path investigated: Auth and voice routes use `@limiter`, confirming rate limiting exists elsewhere → all AI routes were checked for that dependency → subscription definitions advertise “5 AI chat queries / month” while the module says only cause-list watches are enforced.
- Why genuine: Free users can make unlimited AI requests, including provider fan-out, contradicting the product contract and allowing uncontrolled LLM cost and resource exhaustion.
- Recommended fix: Centralize per-user AI quotas and concurrency limits, enforce tier entitlements server-side, cap request/history sizes, and apply equivalent controls to HTTP, SSE, and WebSocket paths.

### 4. The lawyer case assistant bypasses the RAG and citation pipeline

- Severity: High
- Status: CONFIRMED
- Location: `frontend/src/components/lawyer/CasesPage.jsx`, `WorkspaceAI.send`; `backend/app/api/v1/routes/ai.py`, `ai_query_stream`
- Evidence: The UI offers prompts such as “Key legal sections” and “Recent precedents,” then calls `aiQueryStream`. That endpoint directly streams `llm.astream(_build_messages(...))`; it performs no retrieval, grounding, citation annotation, currency check, or claim verification.
- Execution path investigated: Case assistant → `api.js::aiQueryStream` → `/ai/query/stream` → raw provider stream. The separate `/ai/research` route does use LangGraph/RAG, but this component does not call it.
- Why genuine: A lawyer-facing feature explicitly asking for statutes and precedents returns unsupported model output with no provenance or citations.
- Recommended fix: Route substantive case-law questions through `/ai/research`, or add retrieval, structured citations, grounding, and provenance to the streaming path.

### 5. A known RAG failure mode remains open in the current decision path

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/ai/decision_engine.py`, `run_decision_engine`; `backend/app/ai/grounding.py`; `FAILURE_CASE_001.md`
- Evidence: `bm25_confidence == 0` makes BM25 “unavailable” rather than negative evidence, while `arbitrate` selects the maximum remaining confidence. The language-aware veto in `grounding.py` explicitly says it is not imported into the request path.
- Execution path investigated: Retrieval scores → decision engine → generation → hallucination judge → finalizer. `FAILURE_CASE_001.md` records an answer with BM25 `0.0`, relevance `0.2396`, a wrong PPC citation, `is_grounded=True`, and confidence `0.85`. The original triage corruption was fixed, but the negative-evidence and grounding defects remain open.
- Why genuine: The repository contains an observed, reproducible wrong-law answer and preserves the exact still-active logic that failed to reject weak evidence.
- Recommended fix: Validate the proposed language-aware negative-evidence veto on held-out multilingual data, then integrate it before generation/finalization. Do not apply a blanket BM25-zero veto to Urdu queries.

### 6. Fee webhook settlement can become permanently stranded

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/services/payment_service.py`, `_settle`
- Evidence: Fee settlement inserts the unique webhook event and only afterwards marks the payment paid. Unlike subscription settlement, these writes are not transactional.
- Execution path investigated: Verified provider webhook → payment lookup → `_settle` → event insert → payment update → notifications. If the payment update fails after the event insert, provider redelivery hits `DuplicateKeyError` and returns `{"deduped": true}` before retrying the payment transition.
- Why genuine: A captured payment can remain pending permanently after a single inter-write database failure.
- Recommended fix: Put event insertion and conditional payment transition in one MongoDB transaction, following `_settle_subscription_txn`; keep notifications post-commit.

### 7. Concurrent checkout creation can create multiple provider orders

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/services/payment_service.py`, `create_checkout`; `backend/app/db/indexes.py`
- Evidence: The function reads an eligible payment, calls the provider, then unconditionally writes the returned `provider_ref`. No atomic state claim or idempotency key protects provider creation. There is no unique `provider_ref` index.
- Execution path investigated: Two payer requests can both read `CREATED/PENDING` → each invokes Safepay `/order/v1/init` → each gets a different tracker → the last Mongo update overwrites the first.
- Why genuine: Multiple payable orders can exist for one internal payment, while webhook resolution recognizes only the tracker stored last.
- Recommended fix: Atomically claim checkout creation, reuse existing pending checkout details, pass a stable provider idempotency key, and make `provider_ref` unique and indexed.

### 8. Production payment return handling is absent and the UI reports premature success

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/services/payments/safepay.py`, `SafepayProvider.create_checkout`; `frontend/src/components/lawyer/SettingsPage.jsx`, `doSubscribe`
- Evidence: Safepay redirects to `/pay/return/{payment_id}`, but no such Next.js route exists. For live checkout, the UI opens a new tab, immediately refreshes the still-pending subscription, and always shows “Plan activated.”
- Execution path investigated: Subscribe → payment creation → Safepay checkout URL → missing frontend return route. Mock settlement is handled separately and does not repair the live path.
- Why genuine: A live customer returns to a 404 and receives a success message before webhook settlement has activated the plan.
- Recommended fix: Add the return route, poll or fetch payment status there, communicate success back to the original page, and only show activation after paid status is confirmed.

### 9. Cancelling a subscription removes paid access immediately despite promising period-end access

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/services/subscription_service.py`, `get_tier`, `cancel`
- Evidence: `cancel` sets status to `CANCELLED`, while `get_tier` grants paid access only for `ACTIVE` or `TRIALING`. Both the notification and frontend state that access continues until `current_period_end`.
- Execution path investigated: `/billing/subscription/cancel` → `cancel` writes `CANCELLED` → feature gates call `is_paid/get_tier` → user is downgraded to free immediately.
- Why genuine: The implementation contradicts the response and billing promise.
- Recommended fix: Record `cancel_at_period_end` while retaining active status, or treat `CANCELLED` with a future period end as paid until expiry.

### 10. Appointment overlap protection does not close the concurrent interval race

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/services/appointment_service.py`, `book_appointment`; `backend/app/repositories/appointment_repo.py`, `has_conflict`; `backend/app/db/indexes.py`
- Evidence: Overlap detection is a read before insert. The unique index protects only identical `(lawyer_id, scheduled_at)` values and only while status is `PENDING`.
- Execution path investigated: Concurrent 10:00–11:00 and 10:30–11:30 bookings both see no conflict; their different start times do not collide with the unique index; both insert.
- Why genuine: The system can double-book a lawyer for overlapping consultations.
- Recommended fix: Reserve normalized slots transactionally, use a dedicated slot collection with unique lawyer/slot keys, or serialize booking per lawyer.

### 11. Intake conversion can create duplicate cases

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/services/intake_service.py`, `convert_to_case`
- Evidence: It reads `completed`, creates a case, performs AI work, and marks the intake completed only at the end. Neither intake update nor case insertion conditionally claims the conversion.
- Execution path investigated: Two concurrent conversions can both read `completed=False` → both create cases → both run AI → last `mark_completed` wins. There is no unique `cases.intake_id` index.
- Why genuine: Duplicate case records and duplicated AI/provider cost are possible from a retry or double submission.
- Recommended fix: Atomically transition the intake to a `converting` state, make `intake_id` unique, and make retries return the existing case.

### 12. Agreement signing and declining are not concurrency-safe

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/services/agreement_service.py`, `submit_signature`, `decline_agreement`; `backend/app/repositories/agreement_repo.py`
- Evidence: Terminal status and existing-signature checks use a prior read. Signature update, audit append, derived classification, and agreement status are separate ID-only writes. Decline similarly appends an audit row before separately changing status.
- Execution path investigated: Concurrent sign/sign requests can both pass “not signed” and append duplicate audit entries. Concurrent final-signature/decline requests can produce contradictory agreement status and audit history depending on write order.
- Why genuine: The agreement’s legally significant state and audit history can contradict each other.
- Recommended fix: Use conditional updates containing expected status and unsigned-party predicates, then transactionally commit signature/audit/status changes.

### 13. The documented corpus setup invokes an ingestion path known to corrupt classification and jurisdiction metadata

- Severity: High
- Status: CONFIRMED
- Location: `README.md`; `backend/scripts/ingest_pakistan_laws.py`, `_classify`, `_make_chunks`; `backend/scripts/ingest_statutes.py`
- Evidence: The setup guide runs `ingest_pakistan_laws.py`, which classifies solely from filename keywords and tags every chunk `province="federal"`. The replacement `ingest_statutes.py` documents actual historical misfiling caused by that approach and provides an explicit registry and provincial metadata.
- Execution path investigated: New installation → README command → dataset filename classification → Chroma metadata → retriever’s `(requested province OR federal)` filter. Mislabelled provincial law becomes retrievable nationwide.
- Why genuine: The official installation instructions reproduce the metadata condition that the replacement script was written to correct.
- Recommended fix: Remove the legacy command, establish one canonical manifest-driven ingestion pipeline, and rebuild/validate the corpus before deployment.

### 14. Web search snippets are admitted as legal evidence without source retrieval or authority validation

- Severity: High
- Status: CONFIRMED
- Location: `backend/app/ai/nodes/retrieval_node.py`, `_web_search`, `retrieval_node`; `backend/app/ai/nodes/generation_node.py`
- Evidence: DuckDuckGo title/body snippets become chunks with `law_type="web"` and `province="federal"`, then are appended to retrieval results. Generation formats them as numbered “Web Source” evidence.
- Execution path investigated: Client web-search toggle → DDG snippet search → snippet becomes a chunk → grader/generation/grounding treat it as evidence. The target page is not fetched; publisher, date, jurisdiction, amendment status, and exact context are not validated.
- Why genuine: Search-engine snippets can directly support a user-facing legal proposition despite not being authoritative source text.
- Recommended fix: Fetch the target, restrict or rank authoritative legal domains, retain publication/date/jurisdiction metadata, verify quoted context, and distinguish web material from statutory evidence in grounding.

### 15. Draft-stream citation verification is calculated but discarded by every frontend consumer

- Severity: Medium
- Status: CONFIRMED
- Location: `backend/app/api/v1/routes/ai.py`, `ai_draft_stream.token_generator`; `frontend/src/lib/api.js`, `_consumeSSE`
- Evidence: Backend emits `{"verification": ...}` before `[DONE]`. `_consumeSSE` forwards only `parsed.content`; verification events are ignored. `test_draft_stream_verification.py` explicitly pins this behavior.
- Execution path investigated: Lawyer drafts → tokens enter editor → post-stream verification runs → SSE parser discards verdict → document UI applies draft without showing findings.
- Why genuine: The only citation check on the streaming draft path has no user-visible effect.
- Recommended fix: Give the SSE client an event callback or structured completion result and display/block on `not_in_corpus`, repealed, or verification-failed states according to product policy.

### 16. Any authenticated role can create a “client” case that it then cannot use correctly

- Severity: Medium
- Status: CONFIRMED
- Location: `backend/app/api/v1/routes/cases.py`, `create_case`; `backend/app/services/case_service.py`, `create_case`
- Evidence: The route uses `get_current_user`, not `require_client`, and always writes the caller as `client_id`. A lawyer-created record has no `lawyer_id`; lawyer list/access logic searches assigned `lawyer_id`.
- Execution path investigated: Authenticated lawyer/admin → POST `/cases` → stored as client → subsequent lawyer list/get authorization does not treat that record as assigned.
- Why genuine: The API permits a state inconsistent with its own authorization model.
- Recommended fix: Restrict the route to clients, or define an explicit admin/lawyer case-creation workflow with a real client ID and authorization checks.

### 17. Appointment state transitions use stale reads and unconditional writes

- Severity: Medium
- Status: CONFIRMED
- Location: `backend/app/services/appointment_service.py`, `confirm_appointment`, `cancel_appointment`, `complete_appointment`, `mark_no_show`; `backend/app/repositories/appointment_repo.py`, `update_status`
- Evidence: Each service reads and validates status, then `update_status` filters only by `_id`. Notifications are emitted based on the stale snapshot.
- Execution path investigated: Concurrent confirm/cancel or complete/cancel calls can both pass their checks and overwrite each other, while each sends a notification claiming success.
- Why genuine: Persisted status and notifications can disagree.
- Recommended fix: Put the expected source statuses in the update filter and treat `modified_count == 0` as a conflict; use transactions when state changes and notifications must be coordinated.

### 18. Naive appointment timestamps can fail during validation

- Severity: Medium
- Status: CONFIRMED
- Location: `backend/app/schemas/appointment.py`, `BookAppointmentRequest.must_be_future`
- Evidence: Pydantic accepts timezone-naive datetimes, but the validator compares them directly with timezone-aware `datetime.now(timezone.utc)`. Python raises `TypeError` for that comparison.
- Execution path investigated: POST appointment with `scheduled_at: "2026-10-01T10:00:00"` → Pydantic parses a naive datetime → validator performs naive/aware comparison before route execution.
- Why genuine: A syntactically valid ISO datetime can produce an internal validation failure rather than a controlled 422 or normalized UTC booking.
- Recommended fix: Require an offset explicitly or attach a documented timezone before comparison and storage.

### 19. Reset tokens are stored in plaintext

- Severity: Medium
- Status: CONFIRMED
- Location: `backend/app/services/auth_service.py`, `forgot_password`, `reset_password`; `backend/app/db/indexes.py`
- Evidence: The exact bearer token emailed to the user is stored and queried in the `password_reset` collection.
- Execution path investigated: Forgot password → random token insertion → email link → exact-token lookup → password replacement.
- Why genuine: Read access to this collection provides immediately usable account-takeover tokens for their one-hour lifetime.
- Recommended fix: Store only a keyed hash or SHA-256 digest of a sufficiently random token and compare by digest; keep single-use and TTL behavior.

### 20. Password-reset responses reveal account existence during SMTP failure

- Severity: Medium
- Status: CONFIRMED
- Location: `backend/app/services/auth_service.py`, `forgot_password`
- Evidence: Unknown email returns normally. A real email raises `ServiceUnavailableError` if SMTP fails.
- Execution path investigated: `/auth/forgot-password`, rate-limited to three/minute → unknown account gets normal success → registered account during an SMTP outage gets 503.
- Why genuine: The differing response exposes whether an address is registered precisely during mail-service failure.
- Recommended fix: Return the same external response for both cases and record delivery failure internally; optionally queue delivery and expose only a generic status.

### 21. Retrieval performs expensive synchronous work on the async request loop

- Severity: Medium
- Status: CONFIRMED
- Location: `backend/app/ai/nodes/retrieval_node.py`, `retrieval_node`; `backend/app/ai/pipelines/retriever.py`, `_bm25`
- Evidence: The async node calls `build_retriever`, `retriever.invoke`, and `_graph_hop2` synchronously. The first BM25 construction loads every document and metadata record from a collection and tokenizes the entire corpus.
- Execution path investigated: HTTP research or WebSocket chat → LangGraph retrieval node on event loop → synchronous Chroma/BM25/embedding operations. The draft route uses `asyncio.to_thread`, showing the main path lacks the same protection.
- Why genuine: First-use corpus loading and each synchronous retrieval can stall unrelated async requests handled by that worker.
- Recommended fix: Build/warm retrievers outside the request loop and execute blocking Chroma/BM25 calls in a bounded worker pool.

### 22. Provincial BM25 filtering occurs after top-k selection

- Severity: Medium
- Status: CONFIRMED
- Location: `backend/app/ai/pipelines/retriever.py`, `_FilteredBM25Retriever._get_relevant_documents`
- Evidence: Global BM25 returns only its top ten, then the wrapper removes other provinces. Semantic retrieval applies the jurisdiction filter before its top-k search.
- Execution path investigated: Mixed-province collection → global lexical ranking → top ten → jurisdiction filter → ensemble. Valid Punjab/federal matches below global rank ten are never considered.
- Why genuine: Other provinces can consume the candidate budget and reduce or empty lexical recall for the requested jurisdiction.
- Recommended fix: Maintain jurisdiction-specific BM25 indexes or retrieve a larger measured pool and filter before final top-k ranking.

### 23. Hearing edits and deletions in the lawyer UI are local-only

- Severity: Medium
- Status: CONFIRMED
- Location: `frontend/src/components/lawyer/CasesPage.jsx`, `HearingsTab.save`, `remove`
- Evidence: The code comments that edits are local-only; only new hearings call `apiAddHearing`. `remove` only updates React state. The backend provides add and outcome routes but no edit/delete route.
- Execution path investigated: Lawyer edits or removes hearing → local state and success toast → page reload/list refresh restores the database version.
- Why genuine: The UI tells the lawyer the change succeeded even though it is not persisted.
- Recommended fix: Add authorized edit/delete endpoints and call them before changing local state, or disable/remove the controls.

### 24. Appointment listing performs up to two serial user queries per item

- Severity: Low
- Status: CONFIRMED
- Location: `backend/app/services/appointment_service.py`, `list_appointments`, `_names`
- Evidence: For each appointment, `_names` sequentially queries the client and lawyer. A 50-item page can issue 100 user lookups after the appointment query.
- Execution path investigated: GET appointment list → paginated query → loop → two `find_by_id` calls per item.
- Why genuine: Latency and database load grow linearly with page size.
- Recommended fix: Collect unique user IDs, fetch them with one `$in` query, and enrich from a map as `case_service.list_cases` already does.

## 2. Possible risks requiring further verification

### P1. Conversation-dependent answers may enter the cross-user result cache

- Severity: High
- Status: POSSIBLE
- Location: `backend/app/ai/nodes/cache_node.py`, `is_personalised`; `backend/app/ai/cache.py`, `_make_key`
- Evidence: The cache key contains only current query, case type, and province. `is_personalised` checks clarification count and `case_id`, not message history. Triage and generation both consume conversation history.
- Execution path investigated: WebSocket/HTTP history → triage/generation context → cache write keyed only by current query. Tests cover clarification and case-bound turns, not ordinary history-influenced turns.
- Why not confirmed: Follow-up intent detection may exclude many such turns, but it does not prove all history-dependent prompts are excluded.
- Recommended verification/fix: Add adversarial two-user cache tests; include a history/context digest in the key or skip result caching whenever prior messages can influence the answer.

### P2. The hallucination judge permits internally contradictory verdicts

- Severity: High
- Status: POSSIBLE
- Location: `backend/app/ai/nodes/hallucination_node.py`, `hallucination_node`
- Evidence: If the model returns `is_grounded=True`, the node accepts it even if parsed claim results contain `unsupported`, `partial`, or `unassessed`.
- Execution path investigated: Structured LLM response → `parse_claim_support` → unconditional true branch. Tests validate parsing but do not assert that unsupported claims veto global groundedness.
- Why not confirmed: No stored example of this exact inconsistent structured output was found.
- Recommended verification/fix: Add an invariant test and deterministically derive or constrain global groundedness from claim verdicts.

### P3. Court-Urdu translation integrity is prompt-only

- Severity: High
- Status: POSSIBLE
- Location: `backend/app/api/v1/routes/ai.py`, `ai_pleading_urdu_stream`
- Evidence: The prompt says not to alter names, figures, dates, or citations, but output is streamed without post-translation comparison or citation verification.
- Execution path investigated: English pleading → LLM translation stream → frontend inserts output → optional PDF generation accepts supplied Urdu text.
- Why not confirmed: No failing translation fixture or production example was present.
- Recommended verification/fix: Build bilingual invariant tests and deterministically compare numerals, names, dates, section references, and party identifiers before accepting output.

### P4. Repeal/current-law coverage may be insufficient for a current-law product

- Severity: High
- Status: POSSIBLE
- Location: `backend/app/ai/nodes/finalizer_node.py`; `backend/app/ai/statute_omissions.py`
- Evidence: The code states repeal data covers only four of 43 statutes. Uncovered provisions are correctly labeled `unknown`, not `in_force`.
- Execution path investigated: Generated citations → deterministic currency application → UI receives `repealed` or `unknown`.
- Why not confirmed: The system does not falsely claim unknown provisions are current; actual harm depends on whether consumers understand and honor `unknown`.
- Recommended verification/fix: Conduct an authoritative corpus currency audit and add effective/repeal/amendment dates and source authority to ingestion metadata.

### P5. Graph hop-2 can bypass jurisdiction filtering

- Severity: Medium
- Status: POSSIBLE
- Location: `backend/app/ai/nodes/retrieval_node.py`, `_graph_hop2`
- Evidence: Exact referenced chunk IDs are fetched directly from the case-type collection, then passed to `_docs_to_chunks`; no province constraint is applied at lookup.
- Execution path investigated: Hop-1 cross-reference → graph IDs → direct Chroma `get` → merged retrieval.
- Why not confirmed: No concrete cross-province edge in the current graph data was established read-only.
- Recommended verification/fix: Audit graph edges by jurisdiction and enforce province/federal eligibility on resolved targets.

### P6. Admin appointment access may exceed intended policy

- Severity: Medium
- Status: POSSIBLE
- Location: `backend/app/services/appointment_service.py`, `cancel_appointment`, `get_appointment`
- Evidence: Ownership checks apply only when role is exactly `client` or `lawyer`; admins fall through. The routes document access for the appointment’s client or lawyer.
- Execution path investigated: Admin access token → generic `get_current_user` dependency → service fallthrough. Elsewhere, admin access is often explicit.
- Why not confirmed: The repository does not define whether admins are intended superusers for appointments.
- Recommended verification/fix: Document the policy; either explicitly authorize and audit admins or reject every role not belonging to the appointment.

### P7. Oversized multipart requests can create avoidable memory pressure

- Severity: Medium
- Status: POSSIBLE
- Location: `backend/app/utils/file_handler.py`, `save_upload`; `backend/app/services/intake_service.py`, `upload_evidence`; `backend/app/api/v1/routes/voice.py`, `transcribe_audio`
- Evidence: Each calls `await file.read()` before checking the ten-megabyte limit. No application body-size middleware is configured.
- Execution path investigated: Multipart parser/spooled upload → full content materialized as bytes → size check.
- Why not confirmed: A deployment proxy may enforce a body limit outside this repository.
- Recommended verification/fix: Verify ingress configuration, enforce request limits at proxy and ASGI layers, and read bounded chunks.

### P8. Battle rooms trust attacker, defender, and troop options

- Severity: Medium
- Status: POSSIBLE
- Location: `dominations/server/src/rooms/BattleRoom.ts`, `BattleRoom.onCreate`
- Evidence: Room options choose both user IDs and troop inventory; no authenticated identity or stored troop ownership is checked.
- Execution path investigated: Direct `joinOrCreate("battle", options)` → arbitrary attacker/defender records loaded → server simulation. Rewards are currently commented out.
- Why not confirmed: The current implementation does not persist loot or battle results, limiting present impact.
- Recommended verification/fix: Bind attacker to authenticated identity, load troops server-side, authorize defender selection, and complete persistence only after those checks.

## 3. Top 10 remaining improvements

1. Replace the game’s client-supplied identity with real server-authenticated sessions and conditional persistence.
2. Complete and test the password-reset frontend end to end.
3. Add centralized AI quotas, rate limits, payload limits, and per-user concurrency controls.
4. Move the case workspace assistant onto the grounded RAG path.
5. Validate and integrate a multilingual-safe negative-evidence/grounding veto.
6. Make fee settlement and checkout creation transactional and idempotent.
7. Complete live payment return/status handling and period-end subscription cancellation.
8. Add atomic state transitions for appointments, intake conversion, and agreements.
9. Replace the legacy documented ingestion command and rebuild the corpus from an authoritative jurisdiction-aware manifest.
10. Stop treating raw web snippets as statutory evidence and surface draft verification results to users.

## 4. Missing tests

The backend has substantial tests, but the frontend has no test files and no `test` script. Test sources were reviewed but not executed because the audit was strictly read-only and multiple suites create MongoDB rows, files, caches, or build artifacts.

Highest-priority missing coverage:

1. Frontend password-reset flow: email submission, token parsing, password validation, expired token, backend errors, and success only after API completion.
2. AI quota/rate tests across `/query`, `/research`, all SSE routes, comparison, and WebSocket chat.
3. Case assistant integration test proving legal questions use RAG and return citations/grounding.
4. Fee-settlement fault-injection test between event insertion and payment transition.
5. Concurrent checkout test proving one provider order and stable `provider_ref`.
6. Live payment return-page and delayed-webhook UI tests.
7. Subscription cancellation test proving paid access remains until `current_period_end`.
8. Concurrent overlapping appointment bookings with different start times.
9. Concurrent appointment state-transition tests.
10. Naive and offset-aware appointment datetime API tests.
11. Concurrent intake-conversion/idempotency test with a unique `intake_id`.
12. Agreement sign/sign and sign/decline race tests with audit-log invariants.
13. End-to-end draft-stream test verifying the frontend receives and displays the verification event.
14. Cache isolation tests using identical current queries with different prior conversation histories.
15. Grounding invariant test where `is_grounded=True` conflicts with an unsupported claim.
16. Current failure-case regression tests covering zero lexical support without relying on the previously fixed triage corruption.
17. Web-search evidence tests for domain authority, source fetching, date, jurisdiction, and citation status.
18. Corpus-ingestion validation tests for collection assignment, province, source authority, version/effective dates, and repealed provisions.
19. BM25 jurisdiction-recall tests where out-of-province documents occupy the global top ten.
20. Game-room authentication, duplicate-session, ownership, battle-option authorization, and last-write-wins persistence tests.
21. Frontend hearing edit/delete persistence tests.
22. Role-authorization tests for case creation and explicit admin appointment policy.

---

Audit scope: frontend, FastAPI backend, MongoDB persistence and indexes, authentication, payments, WebSockets, LangGraph/RAG, citation and currency handling, ingestion scripts, tests, and the separate `dominations` application. The audit was performed without implementing fixes.
