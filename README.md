# Enterprise Knowledge & Support Copilot

A full-stack, local RAG (Retrieval-Augmented Generation) copilot running entirely within a local Linux environment. It utilizes FastAPI, PostgreSQL with `pgvector`, Ollama for local LLM inference and embeddings, and an interactive Streamlit UI with conversational memory.

## Architecture & Tech Stack

* **Frontend**: Streamlit (Chat interface & document ingestion)
* **Backend API**: FastAPI (REST endpoints for RAG pipeline, ingestion, and memory-enabled chat)
* **Vector Database**: PostgreSQL with the `pgvector` extension
* **AI Engine**: Ollama running `llama3` (generation) and `nomic-embed-text` (embeddings)
* **Orchestration**: Docker Compose

---

## Project Structure

enterprise-copilot/
├── app/
│   ├── __init__.py
│   ├── database.py       # SQLAlchemy engine & session management
│   ├── frontend.py       # Streamlit chat interface
│   ├── ingest.py         # PDF parsing, chunking, and embedding logic
│   ├── main.py           # FastAPI application & routing endpoints
│   └── models.py         # SQLAlchemy ORM models (pgvector schema)
├── Dockerfile            # FastAPI container build configuration
├── docker-compose.yml    # Multi-container orchestration (Postgres, Ollama, API)
└── requirements.txt      # Python dependencies

---

## Prerequisites

Ensure you have the following installed on your machine:
* [Docker](https://docs.docker.com/get-docker/)
* [Docker Compose](https://docs.docker.com/compose/install/)

---

## Quick Start Guide

### 1. Clone the Repository
Clone the project repository to your local environment and navigate into the root directory:

```bash
cd enterprise-copilot
docker compose up --build -d
```

---

### 2. Access the application:
* **Streamlit UI**: http://localhost:8501
* **FastAPI Docs**: http://localhost:8000/docs