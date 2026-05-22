# Attorney.AI — Lawyer Dashboard Features
> Key ideas from product brainstorm. Each entry: what it does, why it is needed, how to build it simply.

---

## SECTION A — AI PRACTICE INTELLIGENCE

---

### 1. AI Second Chair
**What it does:**
Lawyer uploads opposing counsel's plaint or written statement. System returns a complete litigation strategy package: a plain-language case summary, the four weakest arguments in the opposing document with specific legal reasons, ten cross-examination questions for key witnesses (with what to do if they answer yes or no), and the top three Pakistani precedents that support the lawyer's position.

**Real need:**
This replaces what a junior lawyer does in two to three days — reading the file, finding weaknesses, preparing questions, researching precedents. Senior lawyers with no junior staff do all of this manually and it consumes most of their hearing preparation time.

**How possible:**
Document upload to existing text extraction pipeline. Three specialized LangGraph nodes run in sequence: a summarizer, a weakness detector (LLM with adversarial prompt — "you are opposing counsel, find every flaw"), and a cross-examination generator. Precedent search uses existing ChromaDB retrieval. All infrastructure already exists — new node prompts only.

---

### 2. Pakistan Case Law Oracle
**What it does:**
A dedicated legal research interface separate from the chatbot. Lawyer types a legal issue in plain language — English or Urdu. System returns: the controlling statutory authority, two to four supporting case precedents with relevance scores, a plain explanation of what the law means, and a pre-emptive counter-argument against cases opposing counsel is likely to cite.

**Real need:**
There is no Westlaw, no LexisNexis for Pakistan. Lawyers manually search through printed PLD volumes, call colleagues, or guess. A single precedent search that would take a lawyer four hours takes this system fifteen seconds. This is the most immediately valuable tool for any Pakistani legal professional.

**How possible:**
Existing ChromaDB with 2,357 law chunks already does retrieval. Add a dedicated research page UI (separate from chatbot — clean search bar, result cards with relevance bars). Expand knowledge base with Pakistani court decisions — PLD summaries available digitally. Add a distinction node that identifies cases opposing counsel might cite and argues why they do not apply. Mostly existing infrastructure with a new frontend page.

---

### 3. WhatsApp Case Intelligence
**What it does:**
Lawyer exports or pastes their WhatsApp conversation thread with a client. AI reads the entire thread — months of messages — and produces: a chronological case timeline extracted from the conversation, a list of pending actions the lawyer has not completed, documents mentioned but not confirmed received, and a fee tracker showing what was agreed, what was paid, and what is outstanding.

**Real need:**
Every Pakistani lawyer runs their entire practice on WhatsApp. When they need to reconstruct what happened in a case, they scroll through months of messages manually. This converts their existing chaotic communication into a structured case file automatically — working with how they actually operate rather than asking them to change.

**How possible:**
WhatsApp conversation export is a standard .txt file format. Parse it chronologically by timestamp. Long-context LLM call with structured extraction prompt: timeline, pending actions, document mentions, fee discussions. Render as four-section dashboard card. Input can be pasted text or file upload. No new backend infrastructure needed.

---

### 4. Hearing Preparation Package
**What it does:**
Forty-eight hours before any registered hearing, lawyer receives a notification and clicks Prepare. System generates a complete hearing brief: what happened at the last hearing, what arguments were made, what the judge directed, what must be done today, what opposing counsel will likely argue based on their written submissions, and what specific order language to request from the judge.

**Real need:**
Lawyers with forty or more active cases cannot remember the detailed status of every case when preparing for tomorrow's hearing. They spend two to three hours reconstructing context and preparing. This does it in ten minutes from stored case history.

**How possible:**
Case history stored in MongoDB from previous sessions. Scheduled notification job triggers forty-eight hours before hearing date. LLM prompt: given case history, generate a structured hearing brief with all required sections. Response rendered as a printable one-page document. Uses existing notification WebSocket and existing case data — new LLM prompt and new frontend component only.

---

### 5. Devil's Advocate — Brief Reviewer
**What it does:**
Before filing any legal document, lawyer pastes their draft plaint, application, or written arguments into the system. AI plays the role of opposing counsel and identifies: every weak argument, every outdated or misapplied citation, every logical gap, and every argument they failed to make that would have strengthened their position. Suggests specific fixes for critical issues.

**Real need:**
Every lawyer has filed something with a flaw that opposing counsel immediately exploited in court. Having a senior colleague review drafts before filing is standard practice — but junior lawyers have no senior colleague, and senior lawyers have no time. This is that review, available instantly before every filing.

**How possible:**
Document analysis with adversarial LLM prompt: "You are opposing senior counsel with thirty years experience. Find every weakness in this brief. Be specific. Cite Pakistani law." Cross-reference citations against existing ChromaDB to validate that cited cases say what the lawyer claims. Output rendered as a prioritized list of issues with severity levels and suggested fixes.

---

### 6. Automatic Fee Note Generator
**What it does:**
Every action performed in the lawyer dashboard is silently logged with a timestamp and estimated time — document opened, research query run, AI feature used, hearing brief generated, client message sent. At month end, one click generates a professional fee note for any client: itemized list of services with dates, hours, amounts, and balance outstanding.

**Real need:**
Pakistani lawyers lose approximately thirty percent of their billable work because they do not track time systematically. They write fee notes from memory and undercharge by default. A lawyer earning Rs. 100,000 per month is typically doing Rs. 130,000 of work. This feature recovers that gap automatically.

**How possible:**
Activity logging middleware — every dashboard action writes to a MongoDB activity_log collection with timestamp, case_id, action_type, estimated_duration. Fee rate is set per case by the lawyer in case settings. Month-end aggregation groups activities by case and client. LLM formats them as a professional fee note with appropriate descriptions. WhatsApp share uses Web Share API.

---

## SECTION B — DOCUMENT TOOLS

---

### 7. Document Drafting Canvas
**What it does:**
The screen splits permanently into two equal halves. Left half: conversation with AI where lawyer describes what they need in plain language. Right half: a formal legal document building itself in real time as the AI responds — with proper headings, section numbers, legal citations, and Pakistani court formatting. Lawyer can click any paragraph on the right to edit it directly.

**Real need:**
This is the feature that Harvey AI built its entire business on. Pakistani lawyers currently start every document from a blank page or from an old document they find in their files. This generates a court-ready first draft in minutes, in the correct format for Pakistani courts, from a plain-language description.

**How possible:**
Left panel: existing chatbot WebSocket. Right panel: new DocumentCanvas component that receives streaming text and renders it as a formatted document rather than a chat bubble. Auto-formatting applies heading styles and section numbering via regex as text streams in. Split-pane layout is a CSS grid. New system prompt instructs AI to output in Pakistani court document format specifically.

---

### 8. Live Contract Redlining
**What it does:**
Lawyer uploads opposing counsel's draft contract. The document appears on screen unedited. Then the AI begins marking it up visually in real time: problem text strikes through in red, replacement language materializes in green above the strikethrough, and comment bubbles appear in the margin explaining why each change is needed and what law requires it. Changes appear one by one — not all at once.

**Real need:**
Contract review and redlining is one of the most time-consuming tasks in legal practice. A junior lawyer takes a full day to mark up a complex contract. Watching an AI do this visually in minutes — producing output that looks exactly like a manually redlined document — is the clearest demonstration of professional-grade AI assistance.

**How possible:**
Document text extracted with paragraph positions. AI returns each change as structured JSON: original text, replacement text, reason, severity. Frontend applies changes progressively with a 300ms delay between each — strikethrough via CSS text-decoration, green text via fade-in animation, comment bubbles via absolute-positioned tooltips. The deliberate pacing makes it feel alive rather than an instant data dump.

---

## SECTION C — DASHBOARD & VISUALIZATION

---

### 9. War Room Dashboard
**What it does:**
A dark-themed main dashboard showing every active case as a card with a colored glowing left border — red for urgent (hearing tomorrow, not prepared), amber for needs attention, green for on track. Three metric pills at the top show total active cases, total billed this month, and hearings this week. Everything visible without clicking into any individual case.

**Real need:**
Pakistani lawyers open WhatsApp every morning to figure out what needs their attention that day. This replaces that with a professional command center view — every case, every urgency level, every pending action visible in one glance.

**How possible:**
Cards pull from existing MongoDB case data. Urgency score is calculated from days to next hearing versus preparation status and pending task count. Border color and glow intensity derived from urgency tier. CSS box-shadow animation creates the pulse effect for critical cases. Metric pills use existing aggregation queries. Entirely frontend work on existing data.

---

### 10. Hearing Timeline — Gantt View
**What it does:**
A horizontal timeline spanning the next thirty days. Every upcoming court hearing across all cases appears as a colored bar on the timeline. Bar color indicates preparation status: red for unprepared, amber for partial, green for ready. When two hearings fall on the same day a yellow conflict warning pulses between them. Hovering any bar shows a floating card with case details and what is required.

**Real need:**
A lawyer with forty cases has court appearances spread across multiple courts every week. Tracking this in a paper diary means conflicts are missed, preparation happens the night before, and the full picture is never visible at once. A visual timeline makes the entire month's court schedule visible in one view.

**How possible:**
Data comes from existing appointments and cases endpoints — already fetched by CaseContext. Timeline is a Gantt-style component buildable with react-calendar-timeline library or custom SVG. Each bar is a case appointment. Conflict detection checks for date overlaps across cases and adds a CSS striped warning animation. Two days of frontend work.

---

### 11. Case Pipeline — Kanban Board
**What it does:**
All active cases arranged as draggable cards across columns representing legal stages: Intake, Research, Filed, Discovery, Hearing, Judgment, Closed. Each column shows the number of cases and total fees at the bottom. Cards are color-coded by case type. Dragging a card between columns updates the case stage. Hovering a card shows the next required action.

**Real need:**
A law practice is a pipeline. Cases move from stage to stage over months or years. Visualizing this as a Kanban board lets lawyers see where work is accumulating, which stages are bottlenecks, and how their overall practice is distributed — visibility that a handwritten diary or case list completely lacks.

**How possible:**
Standard Kanban DnD library (react-beautiful-dnd or dnd-kit — both well-documented npm packages). Columns map to case_stage field added to MongoDB case schema. Drag handler calls existing PATCH case endpoint to update stage. Column totals computed by MongoDB aggregation. Card colors set by CSS based on case type field. Three days of frontend work.

---

### 12. AI Next Action Feed
**What it does:**
A vertical feed — like a social media timeline — where every card is an AI-generated action item across all active cases. Cards are sorted by urgency. Each card shows: case name, what needs to be done, why it is urgent, and one or two action buttons that open the relevant AI tool directly. New cards appear at the top as situations develop throughout the day.

**Real need:**
Lawyers should not have to check every case individually to discover what needs attention. This feed surfaces the most critical action across all cases proactively — the system notices the problem before the lawyer does and brings it forward.

**How possible:**
Scheduled background job runs every hour. For each active case, checks: days until hearing versus preparation status, pending documents not received, unanswered client messages, opposing documents filed but not analyzed, overdue fees. Each trigger creates an action_feed document in MongoDB. Frontend renders as a real-time feed via existing WebSocket notification infrastructure. New UI component on top of existing systems.

---

## SECTION D — ANALYTICS & BUSINESS INTELLIGENCE

---

### 13. Win Rate Analytics Dashboard
**What it does:**
A dedicated analytics page with three visualizations. A radar chart showing win rate across five case types (criminal, civil, family, corporate, constitutional) as a filled polygon — with a second translucent polygon showing benchmark averages for comparison. A bar chart showing monthly case outcomes — won, settled, lost, ongoing — as a twelve-month trend. Three metric cards at the top showing overall win rate, average case duration, and total fees recovered this year.

**Real need:**
Pakistani lawyers have never seen their own performance as data. They do not know their actual win rate. They do not know which case types they are strongest in. They do not know if their average case duration is improving or worsening. This analytics page tells them things about their own practice they have never known.

**How possible:**
Data exists in MongoDB case collection — case type, outcome (won/lost/settled), duration, fees. Win rate calculation: won cases divided by closed cases, grouped by case type for the radar chart. Charts use Recharts or Chart.js — both free npm libraries requiring approximately fifteen to twenty lines of configuration each. Benchmark values set manually to reasonable estimates. Two days of frontend work on existing data.

---

## SECTION E — ADVANCED AI TOOLS

---

### 14. Urdu-First Legal Mode for Lawyers
**What it does:**
A toggle in the lawyer dashboard switches all AI output to formal legal Urdu — research results, drafted documents, case analysis, hearing briefs, and generated notices. All Pakistani court document formats are preserved. The lawyer can work entirely in Urdu, produce Urdu-language client documents, and draft submissions for Urdu-medium courts without any manual translation.

**Real need:**
A significant portion of Pakistani court proceedings, especially in lower courts and family courts, are conducted in Urdu. Lawyers drafting Urdu submissions currently do it manually. Clients who are not comfortable in English cannot read the documents their own lawyer produces. This closes both gaps simultaneously.

**How possible:**
Same implementation as client-side Urdu mode. Language preference stored per lawyer account. Passed through all LLM calls as a system prompt directive. pdf_generator extended with Noto Nastaliq Urdu font. The AI already handles legal Urdu natively — this is purely a prompt and rendering change.

---

### 15. AI Legal Memo Generator
**What it does:**
Lawyer opens a case, clicks "Generate Legal Memo," and describes the legal issue. AI produces a full formal legal memorandum: case background, legal issues identified, analysis of applicable Pakistani law, conclusion, and strategic recommendation — formatted as an official internal memo ready for editing and client delivery. Like Notion AI but for Pakistani legal memoranda.

**Real need:**
Legal memos are one of the most time-consuming deliverables in legal practice — typically two to four hours of writing after two hours of research. They are also the primary way lawyers communicate complex analysis to clients and colleagues. This feature compresses the entire process to fifteen minutes.

**How possible:**
New endpoint POST /cases/{case_id}/memo. Retrieves case facts, conversation history, and relevant laws from ChromaDB. Long-form generation prompt with IRAC structure (already used in generation_node). Returns formatted markdown rendered in the lawyer dashboard with an inline editor. Export to PDF via existing pdf_generator with a new memo template. One new endpoint, one new template, one new frontend component.

---

### 16. Multimodal Document Scanner for Lawyers
**What it does:**
Lawyer uploads a photo of any physical legal document — a handwritten court order, a physical property deed, an old registered agreement, a signed vakalatnama. AI reads the image, extracts all text, identifies the document type, and produces a structured analysis: parties, key clauses, legal validity assessment, and any missing required elements. Saves the extracted text to the case file automatically.

**Real need:**
Law offices in Pakistan are full of physical documents — decades of paper files that have never been digitized. Lawyers spend hours manually transcribing text from old documents to use in current cases. A photo-to-analysis pipeline converts any physical document to a searchable, analyzable digital record in under 30 seconds.

**How possible:**
Same implementation as client-side multimodal scanner — Claude Vision or GPT-4V via OpenRouter (already configured). Lawyer version adds: automatic attachment to selected case in the database, text saved as a searchable document record, structured extraction of legal parties and key dates. New upload button in lawyer document management page.

---

### 17. Opposing Counsel Intelligence
**What it does:**
Before any hearing against a known opposing advocate, lawyer enters their name. System aggregates publicly available information: court records showing cases they have argued, their typical legal arguments by case type, cases they have won and lost, known procedural strategies, and which courts they appear in most. Produces a one-page opponent profile.

**Real need:**
Experienced lawyers know the habits and weaknesses of advocates they face regularly. Junior lawyers and those new to a court have no such intelligence. Knowing that a specific opposing counsel always delays by requesting adjournments, or always leads with a limitation argument, lets the lawyer prepare specific counter-strategies before the first hearing.

**How possible:**
Pakistan's court portals publish advocate names in case records — this is public data. Build a scraper that indexes advocate appearances by name from public court databases. Store as a simple collection in MongoDB. LLM synthesizes patterns: most common argument types, adjournment frequency, typical case duration, known wins and losses. Profile page rendered as a structured card in the lawyer dashboard. This requires the court tracker scraper as a foundation.

---

### 18. Multi-Court Brief Formatter
**What it does:**
Lawyer drafts a document. Before downloading, they select the target court: Supreme Court of Pakistan, Lahore High Court, Sindh High Court, District Court Lahore, Family Court etc. The system automatically reformats the document to meet that court's specific requirements — correct margins, font size, heading styles, citation format, party designation format, and filing checklist.

**Real need:**
Every Pakistani court has different formatting requirements. A brief formatted for the Supreme Court will be rejected by the Lahore High Court. A document formatted for civil court has wrong heading structure for family court. Lawyers waste hours manually reformatting the same document for different courts and still sometimes get it wrong.

**How possible:**
Build a court formatting rules JSON file — one entry per court with its specific requirements (margins, fonts, citation style, heading format). When lawyer selects target court, the formatter applies those rules to the document text programmatically. Most formatting rules are pure text transformations (regex + CSS). Citation format adjustment uses LLM for complex cases. PDF output via pdf_generator with court-specific configuration.

---

### 19. Legal Argument Structure Visualizer
**What it does:**
After the AI analyzes any case or generates any legal argument, a "View Argument Map" button appears. Clicking it renders the argument as an interactive tree: the main claim at the top, supporting laws branching below it, their application to the case facts as leaves, and the conclusion at the bottom. Each node is expandable. Counter-arguments the AI considered appear in a separate color.

**Real need:**
Legal arguments have logical structure — claim, rule, application, conclusion (IRAC) — but they are usually presented as dense paragraphs. Visualizing this structure helps lawyers verify the logic is sound, helps junior lawyers learn how arguments are constructed, and helps clients understand what their lawyer is actually arguing on their behalf.

**How possible:**
Generation node already uses IRAC structure in its prompts. Add a post-processing step that extracts the argument components as JSON: {claim, rules: [], application, conclusion, counter_arguments: []}. Frontend renders as a collapsible tree using react-d3-tree or a simple nested div structure with CSS connecting lines. Expandable nodes show full text on click. One new API response field + one new frontend component.

---

### 20. Provincial Legal Variance Research Tool
**What it does:**
In the lawyer's research interface, a "Check Provincial Variance" button runs the current research query against all four provincial law collections simultaneously. Returns a side-by-side comparison table showing how the answer differs between Punjab, Sindh, KPK, and Balochistan. Flags cases where a lawyer practicing in multiple provinces needs to apply different law for the same type of case.

**Real need:**
Lawyers handling cases in multiple provinces, or advising clients who operate nationally, need to know where the law differs. A lawyer who gives Punjab Tenancy Act advice to a client whose property is in Sindh has given wrong advice. The variance tool makes cross-provincial legal differences visible in the same research workflow.

**How possible:**
Runs four parallel retrieval queries — one per provincial ChromaDB collection. Passes results to Gemini Flash for comparison: "Summarize how the law on this issue differs across these four provinces." Returns a structured comparison. Frontend renders as a four-column table. Uses existing ChromaDB province filtering already implemented in retriever.py. Adds a button to existing research UI.

---

### 21. Human-in-the-Loop Quality Engine
**What it does:**
Every AI response in the lawyer dashboard has a thumbs-up / thumbs-down rating button. Lawyers can optionally add a text correction: "The correct section is 420, not 302." Ratings and corrections are stored. Admin dashboard shows quality trends by case type, time period, and node. Corrections feed into retrieval re-ranking weights — chunks from sources that consistently produced high-rated answers get higher priority in future retrievals.

**Real need:**
A system that does not learn from use is replaced the moment a competitor emerges. A system with a feedback loop compounds over time. Lawyer corrections are the highest-quality legal feedback possible — a licensed professional is verifying AI output. Over months this creates a measurable improvement in response quality that no competitor can quickly replicate.

**How possible:**
New MongoDB collection response_ratings: session_id, message_id, rating (1–5), correction text, rated_by, timestamp, chunks_used. Thumbs up/down added below every AI message in lawyer chat interface. Admin analytics page: average rating by case type and date using MongoDB aggregation. Re-ranking weight adjustment: a background job periodically updates chunk metadata in ChromaDB based on rating patterns. The feedback collection is one day of work. The re-ranking integration is an additional two days.

---

### 22. Legal Reasoning Trace (XAI Layer)
**What it does:**
Every AI response in the lawyer dashboard has a collapsible "How I reasoned this" section. Expanding it shows a step-by-step trace: which nodes ran, what each node found, which chunks were retrieved and why they scored highest, confidence at each stage, and what alternative answers were considered and rejected. Lawyers can verify the reasoning chain before relying on the output.

**Real need:**
Lawyers are professionally liable for the advice they give. Before relying on AI-generated content in court or in client advice, a lawyer needs to understand where the answer came from and whether the reasoning is sound. Explainability is not optional in high-stakes professional contexts — it is a basic requirement for any tool a lawyer will actually use.

**How possible:**
Add a reasoning_trace list to AgentState. Each node appends a ReasoningStep dataclass before processing: {node_name, action_description, top_evidence_excerpts, confidence, decision}. Generation node includes the full trace in its response payload. Frontend renders as a stepper component — each step expandable, showing evidence excerpts and confidence score. The trace appears collapsed by default and is expanded on demand.

---

## PRIORITY BUILD ORDER

| Priority | Feature | Estimated Days | Key Reason |
|---|---|---|---|
| 1 | Document Drafting Canvas | 3 | Signature feature — Harvey AI for Pakistan |
| 2 | AI Second Chair | 3 | Most dramatic demo for judges |
| 3 | War Room Dashboard | 2 | First thing lawyer sees every day |
| 4 | AI Next Action Feed | 2 | Makes system feel proactive and intelligent |
| 5 | Case Law Oracle | 2 | Most immediately useful for daily practice |
| 6 | WhatsApp Intelligence | 2 | Uniquely Pakistani — no global competitor |
| 7 | Hearing Timeline Gantt | 2 | Solves the diary problem visually |
| 8 | Live Contract Redlining | 3 | Most visually dramatic feature |
| 9 | Case Pipeline Kanban | 3 | Full practice visibility |
| 10 | Hearing Prep Package | 2 | Saves 2-3 hours per hearing |
| 11 | Devil's Advocate Reviewer | 2 | Prevents professional embarrassment |
| 12 | Win Rate Analytics | 2 | Business intelligence no Pakistani tool has |
| 13 | Fee Note Generator | 2 | Recovers lost revenue automatically |
| 14 | Urdu-First Legal Mode | 1 | Urdu court submissions and client documents |
| 15 | AI Legal Memo Generator | 2 | Compresses 4 hours of writing to 15 minutes |
| 16 | Multimodal Document Scanner | 2 | Digitize physical legal files instantly |
| 17 | Opposing Counsel Intelligence | 3 | Strategic preparation before any hearing |
| 18 | Multi-Court Brief Formatter | 2 | Eliminates court-specific reformatting errors |
| 19 | Legal Argument Structure Visualizer | 2 | Verify argument logic before filing |
| 20 | Provincial Variance Research Tool | 1 | Multi-province legal practice support |
| 21 | Human-in-the-Loop Quality Engine | 3 | Data flywheel — system improves with use |
| 22 | Legal Reasoning Trace (XAI) | 2 | Professional accountability and trust |

**Total: approximately 45 days for complete professional lawyer dashboard.**

---

## THE DEMO SEQUENCE FOR JUDGES (4 Minutes)

1. Open War Room Dashboard — every case visible, red cards pulsing for urgent items
2. Upload opposing plaint → AI Second Chair returns weaknesses and cross-examination questions in 90 seconds
3. Type legal research query → Case Law Oracle returns controlling authority and precedents in 15 seconds
4. Open Document Drafting Canvas → describe case in plain language → legal document builds itself on the right in real time
5. Upload opposing contract → Live Redlining → red strikethroughs and green replacements appear one by one
6. Click Analytics → Win Rate radar chart animates in showing performance across all case types

**The closing line:**
"Harvey AI charges US law firms $2,000 per month for features like this. Pakistani lawyers have had nothing. Attorney.AI is the first professional-grade legal AI built specifically for Pakistan — in English and Urdu, for Pakistani courts, Pakistani law, and how Pakistani lawyers actually work."
