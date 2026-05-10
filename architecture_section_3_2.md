### 3.2.1 Technologies and Services

**Table 3.1 Technologies, Components, and Security Mechanisms Used in the System Architecture**

| Component | Description | Technology Used | Security Mechanism |
| :--- | :--- | :--- | :--- |
| **Client Layer (Frontend)** | Responsive user interfaces providing distinct access points for the Client Portal, Lawyer Dashboard, and Administrative Panel. | Next.js 15, React 18.2, Tailwind CSS 3.4 | Enforced HTTPS (TLS), secure `HttpOnly` cookies, CSRF protection, and client-side JWT expiration handling. |
| **API Gateway** | Centralized entry point managing inbound requests, routing REST APIs, and maintaining WebSocket connections for real-time chat. | FastAPI 0.115, Uvicorn 0.32, WebSockets 16.0, SlowAPI | Rate Limiting (SlowAPI) to mitigate DDoS attacks, strict CORS policies, Pydantic schema validation, and Centralized JWT Verification. |
| **Business Service Layer** | Core application logic encapsulating User Authentication, Case Intake workflows, and the Lawyer Matching Engine. | Python 3, Pydantic 2.10, Bcrypt 5.0, Python-JOSE | Role-Based Access Control (RBAC) ensuring strict method-level privilege separation (Client vs. Lawyer vs. Admin). |
| **AI Orchestration** | Orchestrates stateful conversational agents, multi-step legal reasoning pipelines, and context-aware external tool execution. | LangGraph, LangChain, SentenceTransformers, Faster-Whisper | Pre-processing PII (Personally Identifiable Information) scrubbing and robust prompt injection prevention mechanisms. |
| **Primary Database** | Highly available NoSQL document database storing user profiles, active case records, and immutable system audit logs. | MongoDB, Motor 3.6 (Async PyMongo) | Database encryption at rest, secure internal network isolation, and append-only database policies for audit logs. |
| **Vector Store** | Stores high-dimensional document embeddings to enable Semantic Legal Search and Retrieval-Augmented Generation (RAG). | ChromaDB 1.5.9, pdfplumber | Strict internal network isolation and tenant-based metadata filtering to prevent cross-user data exposure. |
| **External APIs** | Cloud-based Large Language Models (LLMs) for complex natural language processing and external utilities for automated email delivery. | Google Gemini API, Groq API, AioSMTP (Async SendGrid) | Secure `.env` secret management, TLS encrypted transit, and utilization of zero-data-retention enterprise API endpoints. |
