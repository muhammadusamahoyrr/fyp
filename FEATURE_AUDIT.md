# Attorney.AI — Feature Audit

> **Purpose:** An honest, code-verified audit of what the repository *actually* implements, measured against the two product brainstorm documents (`USER_FEATURES.md`, `LAWYER_FEATURES.md`).
> **Method:** Read of the backend (`backend/app`, 125 `.py` files) and frontend (`frontend/src`, 131 `.js/.jsx` files), API surface (`main.py`, `lib/api.js`), the LangGraph AI pipeline, `pdf_generator.py`, and every feature-bearing component.
> **Date:** 2026-07-04

---

## 0. The Headline Finding (read this first)

**The built product is not the product described in the brainstorm docs.**

`USER_FEATURES.md` (37 features) and `LAWYER_FEATURES.md` (22 features) are an *aspirational wishlist*. The actual codebase is a **solid, conventional legal-services platform + a genuinely sophisticated RAG chatbot** — a different, more traditional product than the 59 flagship "AI-native" features imagined in the docs.

So there are **two completion numbers**, and conflating them is the mistake to avoid:

| Framing | Completion |
|---|---|
| **The platform that actually exists** (auth, intake, chatbot, docs, lawyers, appointments, admin…) as a conventional MVP | **~65%** |
| **The 59 flagship features in the two brainstorm docs**, specifically | **~13%** |

The engineering effort is real and substantial. It has simply gone into a **standard platform**, while the *differentiating* features that the docs pitch (Legal GPS, Inheritance Calculator, FIR escalation, Case Law Oracle, AI Second Chair, WhatsApp Intelligence) are **almost entirely unbuilt.**

---

## 1. What Actually Exists (the real system, doc-independent)

These are **real, wired, working** subsystems found in the code — the true state of the product.

| Subsystem | Status | Key files |
|---|---|---|
| **Auth & roles** (JWT + refresh cookie, client/lawyer/admin, forgot/reset password) | ✅ Solid | `routes/auth.py`, `services/auth_service.py`, `core/security.py`, `context/AuthContext.jsx` |
| **Intake wizard** (multi-step, evidence upload, AI→case conversion, HITL clarify) | ✅ Solid | `routes/intake.py`, `services/intake_service.py`, `nodes/intake_node.py`, `ModIntake.jsx` |
| **RAG chatbot pipeline** (LangGraph: triage → classifier → retrieval → rerank → grade → generate → hallucination-check → clarify → finalize) | ✅ Sophisticated | `ai/graph/supervisor.py`, `ai/nodes/*`, `ai/pipelines/retriever.py`, `ai/pipelines/reranker.py`, `websockets/chat_socket.py` |
| **NLU intent engine** (embedding + scorer + router, format/affirm/stop/clarify) | ✅ Real | `ai/intent/*` |
| **Confidence score + citations** surfaced to UI | ✅ Real | `nodes/generation_node.py`, `nodes/hallucination_node.py`, `ModChatbot.jsx:569` |
| **Legal knowledge base** (PPC, CrPC, Limitation Act, Transfer of Property, MFLO, Qanun-e-Shahadat — chunked + embedded in ChromaDB) | ✅ Real | `backend/knowledge_base/processed/**`, `scripts/ingest_pakistan_laws.py` |
| **Document generation** (AI field extraction + 5 PDF templates) | ✅ Real, narrow | `routes/documents.py`, `services/pdf_generator.py`, `services/document_service.py`, `ModDocuments.jsx` |
| **Lawyer directory + AI matching** (embedding match + `match_reason` explanation) | ✅ Real | `routes/lawyers.py`, `services/lawyer_service.py`, `ai/lawyer_embeddings.py`, `ModLawyers.jsx` |
| **Appointments** (book/confirm/cancel/complete/no-show/availability) | ✅ Real | `routes/appointments.py`, `services/appointment_service.py` |
| **Agreements + e-signature** | ✅ Real | `routes/agreements.py`, `services/agreement_service.py`, `ModAgreements.jsx` |
| **Case management** (CRUD, hearings, milestones, timeline, tasks, messages) | ✅ Real | `routes/cases.py`, `repositories/case_repo.py`, `ModTracking.jsx` |
| **Admin panel** (analytics overview, KYC verification, user mgmt, case tracking, lawyer monitoring) | ✅ Real | `routes/admin.py`, `services/admin_service.py`, `components/admin/*` |
| **Voice transcription** (Whisper STT) | ✅ Real | `routes/voice.py`, `services/whisper_service.py` |
| **Notifications** (WebSocket) | ✅ Real | `routes/notifications.py`, `websockets/notification_socket.py` |
| **Courtroom 3D scene** (R3F/Three.js environment) | ⚠️ Real 3D, **scripted (no AI)** | `components/courtroom/*`, `store/courtroomStore.js` |

**Bottom line:** the "plumbing" of a legal platform is largely done. The *AI-native differentiation* the docs promise is not.

---

## 2. USER_FEATURES.md — Feature-by-Feature Audit

Legend: ✅ Implemented · 🟡 Partial · 🎭 Fake / UI-only · ❌ Missing

| # | Feature | Verdict | Completeness | Implementing files (or nearest infra) | What's missing |
|---|---------|:--:|:--:|---|---|
| 1 | Legal GPS (justice routing) | ❌ | 15% | `intake_node.py`/`classifier_node.py` classify case type; `lawyer_service.py` matches | No routing knowledge base (courts/tribunals/ombudsmen), no cost/time/success-rate routes, no "wrong forum" warnings |
| 2 | Legal Health Checkup | ❌ | 0% | — | Entire feature; no multi-section risk scan, no health score, no schemes JSON |
| 3 | Islamic Inheritance Calculator | ❌ | 0% | — | Faraid math engine, family-tree builder, settlement PDF. **Zero code.** |
| 4 | Salary Theft Calculator | ❌ | 0% | — | Gratuity/notice/EOBI math, demand letter. **Zero code.** |
| 5 | FIR Without the Police | ❌ | 0% | `pdf_generator.py` (has 5 templates, none FIR) | FIR / 154(3) / 22-A / IG-complaint templates + escalation logic |
| 6 | WhatsApp → Evidence Map | ❌ | 0% | — | `.txt` parser, evidence classification prompt, colour-coded cards |
| 7 | One-Click Lawyer Letter | 🟡 | 40% | `pdf_generator.legal_notice`, `document_service.extract_fields`, `ModDocuments.jsx` | Requires an existing case; no "one casual sentence → notice" fast path; not province-cited |
| 8 | "Is This a Scam?" Detector | ❌ | 0% | — | Fraud red-flag JSON, scoring, known-scam DB |
| 9 | AI Negotiation Ghostwriter | ❌ | 0% | WebSocket infra exists | Stateful negotiation strategist mode + UI |
| 10 | Government Form Autopilot | ❌ | 0% | — | Procedure knowledge base, form pre-fill |
| 11 | Emergency SOS Button | ❌ | 0% | — | Anonymous no-auth endpoint + triage card |
| 12 | Legal Countdown Clock | ❌ | 10% | Tasks have `due` dates (`cases.py`) | No deadline extraction from analysis, no countdown component |
| 13 | Witness Memory Vault | ❌ | 0% | — | Guided interview mode + statement PDF |
| 14 | Danger Atmosphere | ❌ | 0% | — | Severity keyword detection + background shift (triage has `urgency` only) |
| 15 | Document Scanning Beam | ❌ | 0% | — | Per-paragraph risk streaming + beam animation |
| 16 | Split-World Slider | ❌ | 0% | — | Original vs plain-Urdu compare slider |
| 17 | Risk Heat Map | ❌ | 0% | — | Page-thumbnail risk grid |
| 18 | Voice → Waveform → Document | 🟡 | 35% | `whisper_service.py`, `routes/voice.py`, mic buttons in UI | Voice→text works; no waveform viz, no 3-panel live doc build |
| 19 | Urgency Pulse Orb | ❌ | 0% | — | Dashboard orb animation |
| 20 | Pakistan Legal System Map | ❌ | 0% | — | SVG hierarchy + routing highlight |
| 21 | Community Legal Wall | ❌ | 0% | — | Anonymized live question feed |
| 22 | Real-Time Court Tracker | ❌ | 0% | — | Court-portal scraper + status card |
| 23 | Overseas Pakistani Legal Guardian | ❌ | 0% | — | Asset registry, monitoring jobs, POA template, alerts |
| 24 | **Confidence + Cited Sources Panel** | ✅ | 90% | `generation_node.py`, `hallucination_node.py`, `ModChatbot.jsx:569-571` | Renders confidence % + citations. Collapsible citation *panel* styling is minimal but data is real |
| 25 | Visible AI Thinking Chain | 🟡 | 20% | `chat_socket.py` sends one `{"type":"thinking"}` event; `ModChatbot` shows spinner | No per-node step chain ("Classifying… Searching 2,357 chunks…") |
| 26 | Urdu-First Legal Mode | 🟡 | 45% | `generation_node.py` `_SYSTEM_UR`, `language` in `AgentState`, intake `language` param | Backend Urdu generation is real; **PDF has no Urdu (Noto Nastaliq) font**; lawyer-side toggle is dead UI; toggle wiring incomplete |
| 27 | Predictive Case Outcome Engine | ❌ | 0% | — | Prediction endpoint + gauges (⚠️ also flagged high-risk in strategy review) |
| 28 | AI Arbitration Simulation Room | ❌ | 0% | — | No `arbitration_graph`, no Proponent/Respondent/Arbitrator nodes |
| 29 | Semantic Law Search (Perplexity-style) | 🟡 | 30% | RAG pipeline + `/ai/query` reusable | No dedicated `/search` endpoint/page, no structured article + follow-ups format |
| 30 | "What Happens If You Sign" Timelines | ❌ | 0% | — | Contract clause timelines |
| 31 | Rights Card Generator | ❌ | 0% | — | Rights JSON + html2canvas card + QR |
| 32 | Courtroom Practice Room | 🎭 | 25% | `components/courtroom/CourtroomSession.jsx` (hardcoded `JUDGE` dialogue array) | It's a **scripted 3D scene**, not an AI judge; no dynamic questions, no scoring, no AI at all |
| 33 | Family Settlement Generator | ❌ | 0% | `pdf_generator.py` (extensible) | `family_settlement` template + prompt + intake option |
| 34 | AI Empathy Layer | ❌ | 0% | `triage_node.py` (has `urgency`, **no `emotional_state`**) | Distress detection + warm-acknowledgment prompt |
| 35 | **Lawyer Match Explanation Card** | ✅ | 85% | `lawyer_service.match_lawyers_for_case` returns `match_reason`; `chat_socket.py:63`; `ModLawyers.jsx` | Explanation string is real; wording is generic rather than "because your case involves Khula under MFLO 1961" |
| 36 | Multimodal Document Scanner (photo→analysis) | ❌ | 0% | Text/PDF + voice only | No image-upload endpoint, no vision extraction |
| 37 | Provincial Legal Variance Engine | ❌ | 15% | `retriever.py` has province filtering | No parallel 4-province retrieval + variance comparison |

### User-side tally
- ✅ Implemented: **2** (#24, #35)
- 🟡 Partial: **4** (#7, #18, #26, #29) + weak partials (#25) ≈ 5
- 🎭 Fake/UI-only: **1** (#32)
- ❌ Missing: **29**

---

## 3. LAWYER_FEATURES.md — Feature-by-Feature Audit

| # | Feature | Verdict | Completeness | Implementing files (or nearest infra) | What's missing |
|---|---------|:--:|:--:|---|---|
| 1 | AI Second Chair | ❌ | 5% | Lawyer `AILegalPage.jsx` is a generic chatbot | No opposing-doc upload, weakness detector, cross-exam generator, precedent pack |
| 2 | Pakistan Case Law Oracle | 🟡 | 25% | RAG + ChromaDB exist; but lawyer chat uses **non-RAG** `/ai/query` (`AILegalPage.jsx:7,92`) | No dedicated research page, no precedent cards/relevance bars, no case-law corpus (only statutes), no distinguishing node |
| 3 | WhatsApp Case Intelligence | ❌ | 0% | — | `.txt` thread parser, timeline/pending/fee extraction |
| 4 | Hearing Preparation Package | ❌ | 5% | Case history in Mongo; notification infra exists | No 48h trigger, no hearing-brief generation |
| 5 | Devil's Advocate Reviewer | ❌ | 0% | — | Adversarial brief-review prompt + citation validation |
| 6 | Automatic Fee Note Generator | ❌ | 0% | — | Activity logging middleware + fee-note aggregation |
| 7 | Document Drafting Canvas | 🟡 | 30% | `DocAutomationPage.jsx` (template gallery + `generateDocument`) | No split-screen live-building canvas; template list shows many types but backend supports only 5 PDFs |
| 8 | Live Contract Redlining | ❌ | 0% | — | Redline diff engine + progressive markup UI |
| 9 | War Room Dashboard | 🟡 | 40% | `DashboardPage.jsx` (real `listCases`, metrics) | Not the dark urgency-glow "war room"; urgency-tier borders/pulse not implemented |
| 10 | Hearing Timeline — Gantt | ❌ | 0% | Appointments/hearings data exists | No Gantt component, no conflict detection |
| 11 | Case Pipeline — Kanban | ❌ | 0% | `case_stage` not in schema | Kanban DnD board |
| 12 | AI Next Action Feed | ❌ | 0% | — | Hourly job + action_feed collection + feed UI |
| 13 | Win Rate Analytics | ❌ | 5% | Admin has generic analytics; not lawyer-scoped | Radar/bar charts, win-rate by case type |
| 14 | Urdu-First Legal Mode (lawyer) | 🟡 | 20% | Backend Urdu infra shared (`generation_node`) | Lawyer toggle (`AILegalPage.jsx:380` EN/UR) is **dead UI** — `lang` never sent; lawyer chat isn't even on the RAG path |
| 15 | AI Legal Memo Generator | ❌ | 0% | — | `/cases/{id}/memo` endpoint + memo template |
| 16 | Multimodal Scanner (lawyer) | ❌ | 0% | — | Vision extraction + auto-attach to case |
| 17 | Opposing Counsel Intelligence | ❌ | 0% | — | Advocate scraper + profile synthesis |
| 18 | Multi-Court Brief Formatter | ❌ | 0% | `pdf_generator` fixed A4 format | Court formatting-rules JSON + reformatter |
| 19 | Legal Argument Structure Visualizer | ❌ | 0% | IRAC used in prompts | No IRAC→JSON extraction, no tree UI |
| 20 | Provincial Variance Research Tool | ❌ | 15% | `retriever.py` province filtering | Parallel 4-collection query + comparison table |
| 21 | Human-in-the-Loop Quality Engine | ❌ | 0% | — | Rating buttons, `response_ratings` collection, re-ranking loop |
| 22 | Legal Reasoning Trace (XAI) | ❌ | 5% | `AgentState` carries scores internally | No `reasoning_trace`, not surfaced to lawyer UI |

### Lawyer-side tally
- ✅ Implemented: **0**
- 🟡 Partial: **4** (#2, #7, #9, #14)
- 🎭 Fake/UI-only: dead toggle (#14), template gallery over-promises (#7)
- ❌ Missing: **18**

> **Critical caveat on the lawyer dashboard:** `components/lawyer/data.js` contains **Indian mock data** — "Rajesh Singh", `₹` amounts, "High Court Mumbai", "Sessions Court" — copied from an Indian legal-UI template. Most pages (`CasesPage`, `DashboardPage`, `AppointmentsPage`, `ClientsPage`) have since been wired to the **real Pakistani backend API**, but **`CommunicationsPage.jsx` is still 100% mock**, and `DocumentsPage.jsx` mixes real API with `seedDocs`. This is a demo-integrity and credibility risk for FYP evaluation.

---

## 4. Consolidated Answers to Your Six Questions

### 4.1 Implemented Features (real, working end-to-end)
1. **AI Confidence + Citations** (User #24) — confidence % and law citations rendered in chat.
2. **Lawyer Match Explanation** (User #35) — embedding match + `match_reason` string.
3. *(Platform, not in docs)* RAG legal chatbot, Intake wizard, Case management, Document generation (5 templates), Lawyer directory, Appointments, Agreements/e-sign, Admin panel, Voice transcription, Auth/roles.

### 4.2 Partially Implemented Features
| Feature | Have | Missing |
|---|---|---|
| One-Click Lawyer Letter (U#7) | notice template + AI extract | fast "one sentence" path, province citations |
| Voice → Document (U#18) | Whisper STT | waveform, 3-panel live build |
| Urdu-First Mode (U#26 / L#14) | Urdu generation prompt + `language` field | Urdu PDF font, working toggles, lawyer RAG path |
| Semantic Law Search (U#29) | RAG pipeline | dedicated search page + structured format |
| Case Law Oracle (L#2) | ChromaDB retrieval | research UI, case-law corpus, precedent cards |
| Document Drafting Canvas (L#7) | template gallery + generate | live split-screen canvas; only 5 backend templates |
| War Room Dashboard (L#9) | real case dashboard + metrics | urgency-glow war-room styling |
| Visible Thinking Chain (U#25) | single "thinking" event | per-node step chain |

### 4.3 Fake / UI-Only Features
- **Courtroom Practice Room (U#32)** — a real 3D scene, but the judge is a **hardcoded dialogue array**; no AI, no scoring.
- **Lawyer EN/UR toggle (L#14)** — button toggles local state, value **never reaches the backend**.
- **Lawyer Document-template gallery (L#7)** — lists many document types; backend `pdf_generator` only supports **5** (`legal_notice`, `plaint_civil`, `written_statement`, `nda`, `rental_agreement`).
- **Lawyer `CommunicationsPage`** — entirely `data.js` mock (Indian names/₹).
- **`DocumentsPage` seed docs** — mixes `seedDocs` mock with real API.

### 4.4 Missing Features (high-value, zero/near-zero code)
**Flagship, strategically important, unbuilt:** Legal GPS (U#1), Islamic Inheritance Calculator (U#3), Salary Theft Calculator (U#4), FIR Without the Police (U#5), Overseas Legal Guardian (U#23), Family Settlement Generator (U#33), Multimodal Photo Scanner (U#36), Government Form Autopilot (U#10); AI Second Chair (L#1), Hearing Prep Package (L#4), Fee Note Generator (L#6), AI Legal Memo (L#15), Human-in-the-Loop Quality (L#21).
**Everything else in §2/§3 marked ❌.**

### 4.5 Overall Project Completion Percentage

| Scope | Implemented | Partial (½) | Weighted | % |
|---|---|---|---|---|
| **USER_FEATURES.md** (37) | 2 | 5 | 4.5 | **~12%** |
| **LAWYER_FEATURES.md** (22) | 0 | 4 | 2.0 | **~9%** |
| **Both docs combined** (59) | 2 | 9 | 6.5 | **~11%** |
| **Conventional-platform MVP** (auth/intake/chat/docs/lawyers/appts/admin/voice) | — | — | — | **~65%** |

> **The number that matters for your FYP narrative:** you have a **~65% conventional legal-platform MVP** and a **~11% realization of the differentiating feature vision.** Both are true; state both.

---

## 5. Recommended Build Order for FYP Submission

Optimized for **maximum demonstrable, defensible value per day**, reusing the strong infra you already have (RAG, ChromaDB, `pdf_generator`, WebSocket, intake). Deterministic features first — they are cheap, verifiable, and impossible to accuse of "hallucinating."

### Tier 0 — Integrity fixes (½–1 day, do before anything)
1. **Purge Indian mock data** from `data.js`; wire `CommunicationsPage`/`DocumentsPage` to real API or clearly label as demo. *(Credibility risk if a judge spots "High Court Mumbai / ₹".)*
2. **Make the lawyer AI chat use the RAG graph** (or relabel it), and **make the EN/UR toggle actually send `language`.**

### Tier 1 — Deterministic flagships (highest impact ÷ effort) — ~1 week
3. **Islamic Inheritance Calculator (U#3)** — pure Faraid math + settlement PDF via existing `pdf_generator`. No LLM risk. *Demo gold.*
4. **Salary Theft Calculator (U#4)** — gratuity/notice/EOBI math + demand letter (reuse `legal_notice`).
5. **FIR Without the Police (U#5)** — 4 new PDF templates + AI extraction from intake. Reuses everything.
6. **One-Click Lawyer Letter (U#7)** — add the "one sentence → notice" fast path on top of existing extract/generate.

### Tier 2 — AI features that reuse the RAG pipeline — ~1 week
7. **Confidence + Citations panel polish (U#24)** — already 90%; finish the collapsible source panel for a strong demo beat.
8. **Semantic Law Search page (U#29)** — new `/search` endpoint + page over the existing RAG. Cheap, impressive.
9. **Case Law Oracle (L#2)** — same search UI for lawyers; the single most useful B2B tool.
10. **AI Second Chair (L#1)** — adversarial doc-analysis nodes over ChromaDB. *Most dramatic judge demo.*

### Tier 3 — Depth + differentiation — ~1 week
11. **Urdu-First end-to-end (U#26/L#14)** — add Noto Nastaliq to `pdf_generator`, finish toggles. Huge market-fit story.
12. **Family Settlement Generator (U#33)** — one template + prompt; pairs with the inheritance calculator.
13. **AI Empathy Layer (U#34)** — 3-hour change to `triage_node` + `generation_node`; big perceived-quality lift.
14. **Legal GPS v1 (U#1)** — even a 20-court routing JSON turns your existing classifier into the north-star feature.

### Tier 4 — Demo-polish (only if time remains)
15. **Visible Thinking Chain (U#25)** — per-node WebSocket events; proves architectural depth to technical judges.
16. **Multimodal Photo Scanner (U#36)** — Claude/GPT-4V vision endpoint into the existing analysis path.

**Explicitly DO NOT build for FYP:** Predictive Outcome Engine (U#27 — liability/accuracy risk), Court Tracker / Opposing Counsel (scraper fragility), and the Section-C visual theatre (Danger Atmosphere, Scanning Beam, Urgency Orb, Heat Map) — they consume days and add no defensible substance.

### Suggested 4-minute demo script (achievable after Tier 1–2)
1. Intake a case in plain Urdu → RAG chatbot answers with **confidence % + citations**.
2. **Inheritance Calculator** → exact rupee shares + settlement PDF (deterministic, verifiable).
3. **FIR Without the Police** → four escalation documents generated at once.
4. **Case Law Oracle** → lawyer types an issue → cited statutory answer in seconds.
5. Close on the Urdu toggle + the "built for Pakistani law, in English and Urdu" line.

---

## 6. Appendix — Evidence Notes

- **RAG is genuinely multi-node**, not a ChatGPT wrapper: `ai/graph/supervisor.py` + `ai/nodes/{triage,classifier,retrieval,retrieval_grader,generation,hallucination,clarification,fact_gap,finalizer}_node.py`.
- **Confidence** is model-emitted JSON parsed in `generation_node.py:136`; **citations** built from reranked chunks (`generation_node.py:144`); both rendered at `ModChatbot.jsx:569`.
- **Doc generation** dispatch: `pdf_generator.py:296` `_GENERATORS` → exactly 5 templates.
- **Lawyer chat** calls `aiQueryStream` → `/ai/query/stream` (`routes/ai.py:53`), a plain LLM call **outside** the RAG graph — so no citations/confidence/Urdu path for lawyers.
- **Courtroom** dialogue is static: `CourtroomSession.jsx` `courtroomDialogue` array (`JUDGE`/`COUNSEL` lines).
- **Mock data**: `components/lawyer/data.js` — `casesData`, `seedCases`, `aptDataInitial`, `qData`, `tasksData`, `hearingsData` (all Indian-context).
- **Voice** STT is real: `whisper_service.py` (140 lines) + `routes/voice.py`.
- **Knowledge base** is Pakistani statutes only (no case-law/PLD corpus yet): `backend/knowledge_base/processed/chunks/**`.
</content>
</invoke>
