# Deployment Environment and System Brief

## System Brief: Intelligent Legal Assistance
Attorney.AI delivers highly accurate and intelligent legal assistance through a sophisticated **Retrieval-Augmented Generation (RAG)** pipeline. Unlike generic AI, this system orchestrates a multi-stage workflow:
1.  **Multilingual Intake**: Captures legal queries via high-fidelity audio (Faster-Whisper STT) or text in English and Urdu.
2.  **Contextual Analysis**: A LangGraph-based orchestration agent structures the query, extracting critical facts and legal categories.
3.  **Semantic Retrieval**: Queries are converted into 768-dimensional vectors (Multilingual-E5) to retrieve the most relevant Pakistani legal statutes and judicial precedents from a curated knowledge base.
4.  **Grounded Response**: The LLM (GPT-4o/Gemini) generates responses strictly grounded in the retrieved legal context, ensuring the advice is both legally sound and culturally relevant to the Pakistani judicial system.

---

## Deployment Environment

The Attorney.AI system is designed for a robust, scalable, and secure deployment to handle sensitive legal data and high-compute AI tasks.

### 1. Cloud Hosting and Infrastructure
*   **Provider**: AWS (Amazon Web Services) or a High-Performance Virtual Private Server (VPS) like DigitalOcean.
*   **Operating System**: Ubuntu 22.04 LTS (Linux).
*   **Compute Instance**: 
    - **Minimum**: 4 vCPUs, 8GB RAM (to handle local STT and Vector DB).
    - **Recommended**: AWS EC2 g4ad.xlarge (with GPU acceleration for Faster-Whisper and Embedding models).

### 2. Software Stack and Versions

#### **Backend (API Layer)**
*   **Framework**: FastAPI v0.115.5 (Python 3.10+)
*   **Server**: Uvicorn v0.32.1 (ASGI) / Gunicorn (Process Manager)
*   **Security**: 
    - **Encryption**: AES-256 Fernet (Cryptography v43.0.3) for CNIC encryption.
    - **Hashing**: Bcrypt v5.0.0 for password security.
    - **Auth**: JWT (jose v3.3.0) for stateless authentication.

#### **Frontend (UI Layer)**
*   **Framework**: Next.js v15.0.0 (React 18)
*   **Styling**: TailwindCSS v3.4.4
*   **Deployment**: Vercel (for serverless frontend) or PM2 (on VPS).

### 3. Database Layer
*   **Primary Database**: **MongoDB Atlas** (Cloud-hosted NoSQL)
    - Used for storing user profiles, case records, and chat history.
*   **Vector Database**: **ChromaDB v1.5.9** (Self-hosted)
    - Used for high-performance semantic search and lawyer-to-case matching.

### 4. AI & Orchestration
*   **STT Engine**: Faster-Whisper (Running locally on the server for data privacy).
*   **Orchestration**: LangGraph (for multi-agent AI workflows).
*   **LLM Providers**: Groq (Llama-3-70B) or Google Gemini 1.5 Flash (via API).
*   **Embeddings**: Multilingual-E5-base (768-dim) for multilingual support.

### 5. Server Configuration & Networking
*   **Reverse Proxy**: **Nginx** (Handles SSL termination and load balancing).
*   **SSL/TLS**: Let’s Encrypt (Automated certificate management).
*   **Process Management**: **PM2** (Handles auto-restart and logging for Node.js and Python processes).
*   **Containerization**: Docker & Docker-Compose (Optional, for simplified deployment of ChromaDB and the API).

### 6. Deployment Workflow (CI/CD)
*   **Version Control**: GitHub.
*   **Pipeline**: GitHub Actions for automated linting, testing, and deployment to the production server.
