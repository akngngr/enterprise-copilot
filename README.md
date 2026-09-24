# Enterprise Knowledge & Support Copilot

A full-stack, zero-cost, enterprise-grade RAG (Retrieval-Augmented Generation) copilot designed for both local development and cloud deployment (e.g., Render). Features a resilient dual-engine generation pipeline (Local Ollama primary with automated Google Gemini API fallback) and a unified vector storage layer on managed Supabase PostgreSQL.

## Architecture & Tech Stack

* **Frontend**: Streamlit (Chat interface & PDF document ingestion)
* **Backend API**: FastAPI (REST endpoints for RAG search, ingestion, and conversational memory)
* **Vector Database**: Managed Supabase PostgreSQL with `pgvector` extension (IPv4 Session Pooler enabled)
* **AI Generation Engines**: 
  * **Primary**: Ollama (`llama3`) for zero-cost local inference
  * **Fallback**: Google Gemini API (`google-genai` SDK using `gemini-3.6-flash` / `gemini-2.5-flash`) when Ollama is unreachable
* **Embeddings**: `nomic-embed-text` via Ollama / HuggingFace
* **Orchestration**: Docker & Docker Compose

---

## Project Structure

```text
enterprise-copilot/
├── app/
│   ├── __init__.py
│   ├── database.py       # SQLAlchemy engine & pooler connection management
│   ├── frontend.py       # Streamlit UI interface
│   ├── ingest.py         # PDF parsing, text chunking, and vector embedding logic
│   ├── main.py           # FastAPI backend with Gemini automated fallback logic
│   └── models.py         # SQLAlchemy ORM models (pgvector schema)
├── .env.example          # Environment variable template
├── .gitignore            # Ignores secrets, caches, and virtual environments
├── Dockerfile            # Multi-process container build (FastAPI + Streamlit + Ollama)
├── docker-compose.yml    # Multi-container orchestration (Postgres & Copilot App)
├── init_db.py            # Database schema & pgvector extension initializer
└── requirements.txt      # Python dependencies (includes google-genai, sqlalchemy, etc.)
```

---

## Prerequisites

Ensure you have the following installed on your machine:
* [Docker](https://docs.docker.com/get-docker/)
* [Docker Compose](https://docs.docker.com/compose/install/)

---

### Environment Configuration
Create a .env file in the root directory:

```bash
# Database Settings (Supabase Session Pooler URL)
DATABASE_URL=postgresql://postgres.your_ref:your_password@aws-0-region.pooler.supabase.com:5432/postgres

# Primary Engine Settings
OLLAMA_BASE_URL=http://localhost:11434
GEN_MODEL=llama3

# Gemini API Fallback
GEMINI_API_KEY=your_gemini_api_key_here
```
---

## Quick Start Guide

### 1. Clone the Repository
Clone the project repository to your local environment and navigate into the root directory.

```bash
git clone https://github.com/akngngr/enterprise-copilot.git
cd enterprise-copilot
```

Run the complete stack using Docker Compose:

```bash
# Export your Gemini key to the shell session
export GEMINI_API_KEY="your_actual_gemini_api_key"

# Build and start services
docker compose up --build -d
```

---

### 2. Access the application:
* **Streamlit UI**: http://localhost:8501
* **FastAPI Docs**: http://localhost:8000/docs

---

## Dual Engine Resilience Strategy

* Local Mode: The application first attempts inference using the local Ollama instance (llama3).
* Cloud Fallback: If Ollama times out or is unavailable (such as in serverless or lightweight cloud host environments like Render), the engine automatically reroutes query context to the Google Gemini API without service interruption or application failure.