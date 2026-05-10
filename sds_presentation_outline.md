# SDS and 40% Implementation Presentation Outline: Attorney.AI

## Slide 1: Title Slide
*   **Project Title**: Attorney.AI – Agentic Legal Assistance & Smart Matching System
*   **Team Members**: Muhammad Usama (ID: [Your ID]) & Team
*   **Supervisor Name**: [Supervisor Name]
*   **Department / University**: Department of Computer Science, [University Name]
*   **Date**: May 2026

---

## Slide 2: System Introduction
*   **Purpose**: Attorney.AI leverages Agentic AI to simplify the complex Pakistani legal landscape, converting layman queries into structured legal cases and matching them with verified experts.
*   **Target Users**: 
    *   **Clients**: Seeking affordable, immediate legal guidance.
    *   **Lawyers**: Looking for high-quality, pre-screened case leads.
    *   **Admins**: Ensuring system integrity through KYC and moderation.
*   **Key Features**:
    *   **Bilingual Voice Intake**: Real-time transcription via Faster-Whisper.
    *   **Agentic RAG Pipeline**: Context-aware law retrieval and fact-gap analysis.
    *   **Dynamic Lawyer Ranking**: Multi-factor scoring engine (Semantic + Metadata).
    *   **Smart Agreement Lifecycle**: Automated drafting and E-Sign support.

---

## Slide 3: System Modules
*   **Agentic Intake Module**: Uses **LangGraph** to manage multi-round clarification loops and extract structured facts (Step 1-5).
*   **Matching Engine**: A hybrid service combining **ChromaDB** vector similarity with metadata filters (Province, Case Type, Rating).
*   **Admin Workflow (KYC)**: Secure verification portal for lawyer credentials and document auditing.
*   **Case Management**: Real-time case tracking, document storage, and appointment orchestration.

---

## Slide 4: Design Methodology
*   **Design Approach**: Object-Oriented Design (OOD) with **Service-Repository Pattern**.
*   **Justification**:
    *   **Encapsulation**: AI logic is decoupled from HTTP handlers via specialized services (`IntakeService`, `MatchService`).
    *   **Consistency**: Shared schemas across Frontend (TypeScript/JS) and Backend (Pydantic) ensure data integrity.
    *   **Scalability**: Micro-service ready structure for independent AI model scaling.

---

## Slide 5: Architecture
### 5.1 Conceptual View (Agentic RAG)
*   The system employs an **"Agentic" RAG** approach. Unlike standard RAG, our agent evaluates the quality of retrieved laws and asks clarifying questions if user input is ambiguous.
*   **Context**: Client -> Next.js -> FastAPI -> LangGraph Agent -> ChromaDB/Legal DB -> Matched Lawyer.

### 5.2 Architecture Mechanisms
*   **Architecture Pattern**: **3-Tier Architecture** (Decoupled).
    *   **Frontend**: Next.js 15 (App Router) for Server-Side Rendering (SSR) and speed.
    *   **Backend**: FastAPI for asynchronous, non-blocking AI orchestration.
    *   **Data Tier**: MongoDB Atlas (Metadata) + ChromaDB (Vector) + GridFS (Docs).
*   **Justification**: Separates concerns between user interaction, heavy AI processing, and complex legal data storage.

---

## Slide 6: Key Design Diagrams
*   **Use Case Diagram**: Highlights "AI Clarification" and "Automated Case Conversion" as core innovations.
*   **Class Diagram**: Showcases the `LawyerProfile` booster logic and `IntakeSession` state management.
*   **Activity Diagram**: Visualizes the **Fact-Gap Analysis Loop** where AI decides between "Asking a Question" or "Concluding Intake."
*   **State Diagram**: Traces `IntakeSession` states: `Entering` -> `Validating` -> `Clarifying` -> `Converted`.

---

## Slide 7: Data Design
*   **Hybrid Storage**:
    *   **NoSQL (MongoDB)**: Scalable storage for polymorphic case data and user roles.
    *   **Vector DB (ChromaDB)**: 768-dimensional embeddings of lawyer bios and legal statutes.
*   **Security Layers**: 
    *   **Field-Level Encryption**: CNICs encrypted using AES-256 (Fernet).
    *   **Identity**: Role-Based Access Control (RBAC) with JWT-based sessions.

---

## Slide 8: Implementation Status (40% Complete)
### 8.1 Overview of Progress
*   **Backend**: 60% Complete (Core API, AI Integration, Matching Algorithm, Auth).
*   **Frontend**: 30% Complete (Authentication UI, Intake Wizard, Admin Dashboard).
*   **Contributions**:
    *   **Usama**: Backend Architecture, LangGraph Design, & Vector Search.
    *   **Team**: Frontend Component Library, UI/UX, & Documentation.

### 8.2 Key Algorithms Implemented
*   **Fact-Gap Analysis**: AI compares user input against domain templates (Criminal/Civil) to find missing variables.
*   **Hybrid Matching Logic**: 
    ```python
    Score = (Semantic_Sim * 0.5) + (Spec_Boost * 0.2) + (Rating_Norm * 0.15) + (Avail_Bonus * 0.15)
    ```
*   **Voice-to-Text**: Local inference using `Faster-Whisper` for low-latency Urdu/English transcription.

### 8.3 Integrated APIs & Models
*   **Models**: Llama-3 (via Groq), GPT-4o-mini (Reasoning), Multilingual-E5 (Embeddings).
*   **Infrastructure**: MongoDB Atlas, ChromaDB, FastAPI, Next.js 15.

---

## Slide 9: Testing Strategy
### 9.1 Techniques
*   **Unit Testing**: Isolated testing of **Lawyer Scoring Boosters** and **CNIC Validators**.
*   **Integration Testing**: Validating the end-to-end `Voice Input -> Case Creation` flow.
*   **System Testing**: Testing the system under **Rate-Limit** conditions (using SlowAPI).

### 9.2 Critical Test Cases
*   **Matching Accuracy**: Ensuring a "Family Law" query prioritizes lawyers with "Family" specializations.
*   **Clarification Loop**: Testing if AI correctly exits the loop after 4 rounds or if facts are sufficient.
*   **Security**: Verifying that unauthorized users cannot access `Admin` or `Lawyer` protected routes.

---

## Slide 10: Conclusion & Roadmap
*   **Successes**: Successfully implemented an autonomous AI intake agent that understands Pakistani legal context.
*   **Next Steps (60% Remaining)**:
    *   Implementing Real-time Chat (WebSockets).
    *   Finalizing the Agreement E-Signing module.
    *   Launching the automated Appointment Scheduler.

---

## Slide 11: Q&A Slide
*   **Thank You for Your Attention!**
*   *Questions, Feedback, and Discussion.*
