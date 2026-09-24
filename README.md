# Enterprise Knowledge & Support Copilot

An enterprise-grade Retrieval-Augmented Generation (RAG) Copilot built with **FastAPI**, **Streamlit**, and **PostgreSQL / Supabase (`pgvector`)**. Designed for flexible hybrid operations, it features a dual-engine architecture supporting cloud-native LLM generation and vector embeddings via **Google Gemini** alongside a local, zero-cost execution mode using **Ollama**.

Production deployments leverage **Render** for cloud containerized application hosting and **Supabase** for managed vector database persistence with connection pooling.

---

## Key Features

* **Dual-Engine / Hybrid Local & Cloud Approach**: Controlled via the `ENABLE_OLLAMA_PULL` flag. When set to `true`, the system runs locally via Ollama; when set to `false`, it bypasses local model downloads and routes directly to Google Gemini cloud services.
* **Automated Fallback Architecture**: Seamlessly falls back to Google Gemini if local Ollama models are missing, slow, or unreachable—ensuring zero service interruption.
* **Vector Search with pgvector**: Utilizes cosine similarity over 768-dimensional embeddings stored directly in PostgreSQL / Supabase (`pgvector`).
* **Fast Ingestion Pipeline**: Ingests, chunks, and vectorizes PDF documents using `pypdf` with automated paragraph chunking.
* **Interactive Web Interface**: Sleek, modern dark-themed user interface built with Streamlit featuring chat history and PDF upload management.

---

## Architecture Overview

```text
               +----------------------------------+
               |       Streamlit Frontend         |
               |        (Port 8501)               |
               +----------------+-----------------+
                                |
                                v
               +----------------------------------+
               |       FastAPI Backend            |
               |        (Port 8000)               |
               +-------+------------------+-------+
                       |                  |
           +-----------+                  +-----------+
           | Ingestion & Query Vector Search          | LLM Synthesis
           v                                          v
+-----------------------+                  +-----------------------+
|  Embedding Pipeline   |                  |  Generation Pipeline  |
|                       |                  |                       |
|  1. Ollama (Local)    |                  |  1. Ollama (Local)    |
|     `nomic-embed-text`|                  |     `llama3`          |
|          OR           |                  |          OR           |
|  2. Google Gemini     |                  |  2. Google Gemini     |
|     `gemini-embedding`|                  |     `gemini-3.6-flash`|
|     (768 dimensions)  |                  |                       |
+-----------+-----------+                  +-----------------------+
            |
            v
+-----------------------------------------+
|     Supabase / PostgreSQL (pgvector)    |
|          768-dim Vector Store           |
+-----------------------------------------+
```

---

## Tech Stack

* **Frontend**: Streamlit
* **Backend API**: FastAPI, Uvicorn, Pydantic
* **Database & Vector Store**: PostgreSQL with `pgvector` extension (Supports local Postgres and cloud-managed **Supabase**)
* **Cloud Hosting & Infrastructure**: **Render** (Containerized Web Service) & **Supabase** (Managed Database & Session Pooler)
* **AI & LLM Services**:
  * **Cloud**: Google Gemini (`gemini-3.6-flash` for synthesis, `gemini-embedding-001` for 768-dim embeddings via `google-genai` SDK)
  * **Local**: Ollama (`llama3` for synthesis, `nomic-embed-text` for 768-dim embeddings)
* **Document Processing**: `pypdf`, SQLAlchemy

---

## Project Structure

```text
enterprise-copilot/
├── app/
│   ├── database.py       # SQLAlchemy engine & pooler connection management
│   ├── frontend.py       # Streamlit UI interface & chat workspace
│   ├── ingest.py         # PDF parsing, text chunking, and dual embedding logic
│   ├── main.py           # FastAPI backend with Gemini automated fallback logic
│   └── models.py         # SQLAlchemy ORM models (pgvector schema)
├── .env.example          # Environment variable template
├── .gitignore            # Git ignore rules
├── Dockerfile            # Multi-process container build (FastAPI + Streamlit + Ollama)
├── docker-compose.yml    # Multi-container orchestration (Postgres & Copilot App)
├── entrypoint.sh         # Container boot script for services & conditional model downloads
├── init_db.py            # Database schema & pgvector extension initializer
└── requirements.txt      # Python dependencies
```

---

## Prerequisites & Stack

* **Python**: 3.10+
* **Database**: PostgreSQL with `pgvector` extension enabled (or a managed **Supabase** instance)
* **Google Gemini API**: Active `GEMINI_API_KEY` for cloud inference and embedding fallback
* **Docker & Docker Compose** (Optional, for containerized execution)
* **Ollama** (Optional, for local runner with `llama3` and `nomic-embed-text`)

---

## Environment Variables

Configure these environment variables in your `.env` file or cloud dashboard:

| Variable | Default / Example | Purpose |
| :--- | :--- | :--- |
| `PORT` | `8501` | Entrypoint port for Streamlit. |
| `DATABASE_URL` | `postgresql://postgres:password@host:5432/postgres` | Connection string to PostgreSQL or Supabase with `pgvector` enabled. |
| `ENABLE_OLLAMA_PULL` | `false` | Set to `false` for cloud-native Gemini RAG; set to `true` to pull and run local Ollama models. |
| `GEMINI_API_KEY` | `AIzaSy...` | API key required for Google Gemini generation & embedding. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Base URL for the local Ollama instance (if enabled). |
| `GEN_MODEL` | `llama3` | Generation model name for Ollama inference. |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model name for local Ollama embeddings. |
| `API_BASE_URL` | `http://localhost:8000` | FastAPI gateway URL used by the Streamlit frontend. |

---

## Database Setup

Run the following SQL migration on your PostgreSQL or Supabase database:

```sql
-- Enable the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create table for storing chunked document embeddings
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    source_filename VARCHAR(255) NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(768),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

> **Note**: If you previously used an embedding model with a different dimensionality, truncate or recreate the table:
> ```sql
> TRUNCATE TABLE document_chunks;
> ```

Alternatively, initialize tables directly via Python:

```bash
python init_db.py
```

---

## Local Installation & Setup

### Option 1: Running with Python Virtual Environment

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/akngngr/enterprise-copilot.git
   cd enterprise-copilot
   ```

2. **Create and Activate a Virtual Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your DATABASE_URL and GEMINI_API_KEY
   ```

5. **Start the FastAPI Backend:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. **Start the Streamlit Frontend:**
   ```bash
   streamlit run app/frontend.py --server.port 8501
   ```

---

### Option 2: Running with Docker Compose

You can build and start the entire stack (including local Postgres with `pgvector`) in one step:

```bash
docker compose up --build -d
```

Access the services:
* **Streamlit UI**: [http://localhost:8501](http://localhost:8501)
* **FastAPI Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## API Endpoints

### `POST /ingest/`
* **Description**: Uploads and processes a PDF file, splits it into paragraph chunks, generates 768-dimensional embeddings, and stores the chunks in PostgreSQL / Supabase.
* **Payload**: `multipart/form-data` with `file` (`.pdf`).
* **Response**: `{"status": "success", "filename": "sample.pdf", "message": "..."}`

### `POST /search/`
* **Description**: Vectorizes a search string and queries the database for the top matching document chunks using cosine distance.
* **Parameters**: `query` (string), `limit` (integer, default `3`).
* **Response**: List of document chunks with `source_filename`, `chunk_index`, `content`, and `similarity`.

### `POST /ask/`
* **Description**: Complete RAG endpoint. Retrieves top relevant chunks for the user prompt, constructs conversational context, and returns a grounded answer generated by the active LLM (Ollama or Gemini fallback).
* **Payload**:
  ```json
  {
    "question": "What is the policy for leave?",
    "history": [
      {"role": "user", "content": "Hello"},
      {"role": "assistant", "content": "Hi! How can I help you today?"}
    ]
  }
  ```
* **Response**:
  ```json
  {
    "answer": "According to the employee handbook...",
    "sources": [...]
  }
  ```
