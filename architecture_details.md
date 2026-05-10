# 3.1 System Architecture Overview

This section describes the conceptual architecture of the Attorney.AI platform, illustrating the major components, their responsibilities, and how data flows across the system.

## Conceptual Modules

### 1. Frontend (Web/Mobile App)
- **Responsibility**: Provides role-specific user interfaces for Clients, Lawyers, and Administrators. It manages client-side state, form submissions, and real-time WebSocket connections for the AI chat interface.
- **Technologies**: Next.js 15 (App Router), React, Tailwind CSS.
- **Communication**: Communicates with the backend via RESTful HTTP requests for standard data operations and WebSockets for streaming AI responses and real-time notifications.

### 2. Backend Services/API
- **Responsibility**: Acts as the core orchestrator. It exposes RESTful endpoints, handles WebSocket connections, and houses the LangGraph AI pipeline (retrieval, grading, synthesis, hallucination checking).
- **Technologies**: FastAPI (Python), Uvicorn, LangGraph, Langchain.
- **Communication**: Receives requests from the frontend, queries the database layers, and calls external LLM APIs to process generative tasks.

### 3. Database Layer
- **Responsibility**: Persists all application state and high-dimensional vector data for semantic legal search.
- **Technologies**: 
  - **MongoDB (Motor)**: Stores relational/document data (users, cases, intakes, agreements, chat sessions, audit logs).
  - **ChromaDB**: Acts as the vector database storing chunked legal statutes and judgments with province/court metadata for the Hybrid Retriever.

### 4. Authentication and Authorization Services
- **Responsibility**: Secures the application by verifying user identities and enforcing strict role-based permissions (Client vs. Lawyer vs. Admin).
- **Technologies**: JWT (JSON Web Tokens) stored in secure httpOnly cookies, bcrypt (password hashing), FastAPI dependencies (`get_current_user`, `role_required`).

### 5. Admin Panel
- **Responsibility**: Provides oversight and moderation capabilities. Used for approving Lawyer KYC verifications, tracking case progress, and monitoring overall platform analytics.
- **Technologies**: Integrated into the Next.js Frontend (`/admin` route group) and powered by specific backend endpoints (`/api/v1/admin`).

### 6. External APIs / Integrations
- **Responsibility**: Provides the core generative intelligence for the legal RAG pipeline.
- **Technologies**: External LLM Providers (Gemini 2.0 Flash / Groq for production, Ollama for local development).

### 7. Security Services
- **Responsibility**: Protects the system from abuse, unauthorized access, and data breaches.
- **Mechanisms**: 
  - **Role-Based Access Control (RBAC)**: Enforced via backend middleware.
  - **Rate Limiting**: `slowapi` restricts brute-force attacks on auth endpoints and limits WebSocket message frequency.
  - **Data Encryption**: Sensitive PII (like CNIC numbers) is encrypted at rest using AES-256.
  - **Output Sanitization**: The Finalizer AI node scrubs PII and masks hidden prompts before sending responses to the client.

## Data and Control Flow
1. **User Request**: The user interacts with the Next.js Frontend (e.g., submitting a legal query via WebSocket).
2. **API/WebSocket Gateway**: FastAPI receives the request and validates the JWT via the Auth Service.
3. **Business/AI Logic**: The request is routed to the AI Pipeline (LangGraph). The AI queries ChromaDB for relevant legal contexts and MongoDB for session history.
4. **External Processing**: The backend securely communicates with External LLM APIs to synthesize a grounded legal response.
5. **Response**: The graded, finalized response streams back to the Frontend via WebSocket.

---

# 3.3 Architecture Style / Pattern

## Selected Pattern: Layered Client-Server Architecture

The Attorney.AI system fundamentally follows a **Client-Server** macro-architecture, combined with a strict **Layered Architecture** within the backend.

### Justification for this Style
1. **Separation of Concerns**: A decoupled Client-Server model allows the Next.js frontend to focus purely on UX, App Routing, and role-based views (`(client)`, `lawyer`, `admin`), while the FastAPI backend handles computationally heavy AI orchestration and legal retrieval independently.
2. **Maintainability & Scalability**: The internal Layered Architecture of the backend prevents business logic from bleeding into API routing. This makes it easy to swap out the underlying database or change the LLM provider without rewriting API endpoints.
3. **Security**: Keeping the AI pipeline and database access strictly on the server layer ensures that proprietary legal datasets, API keys, and prompt logic are never exposed to the client.

## Component Mapping & Interactions

The backend is strictly decomposed into the following logical layers to map to this architectural style:

1. **Presentation / API Layer (`app/api/v1/routes/`)**: 
   - Defines endpoints (e.g., `/api/v1/cases`, `/ws/chat`). 
   - Responsible for HTTP validation, routing, JWT parsing, and returning JSON responses.
2. **Service Layer (`app/services/` & `app/ai/`)**: 
   - Contains the core business logic.
   - Orchestrates the LangGraph AI pipeline, generates legal documents via `docxtpl`, and calculates lawyer-matching algorithms.
3. **Data Access Layer / Repositories (`app/repositories/`)**: 
   - The *only* layer allowed to interact with MongoDB. 
   - Abstracts database queries into reusable Python functions (e.g., `user_repo.py`), completely isolating the Service layer from Motor/PyMongo syntax.
4. **Database Layer (`MongoDB` & `ChromaDB`)**: 
   - Persists the actual structured data and vector embeddings.

### Interaction Flow Example (Creating a Case)
1. **Frontend** POSTs case data to the **API Layer** (`/api/v1/cases`).
2. The **API Layer** validates the payload schema and calls the `create_case` method in the **Service Layer** (`case_service.py`).
3. The **Service Layer** calculates embeddings for lawyer matching and calls the **Repository Layer** (`case_repo.py`).
4. The **Repository Layer** inserts the document into the **Database Layer** (MongoDB) and returns the generated MongoDB ObjectID.
5. The response bubbles back up through the layers to the Frontend.
