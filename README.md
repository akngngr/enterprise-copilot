# Enterprise Knowledge & Support Copilot

An enterprise-grade Retrieval-Augmented Generation (RAG) Copilot built with **FastAPI**, **Streamlit**, and **PostgreSQL / Supabase (`pgvector`)**. Designed for flexible hybrid operations, it features a dual-engine architecture supporting cloud-native LLM generation and vector embeddings via **Google Gemini** alongside a local, zero-cost execution mode using **Ollama**.

Production deployments leverage **Render** for cloud containerized application hosting and **Supabase** for managed vector database persistence with connection pooling.

---

## Key Features

* **Dual-Engine / Hybrid Local & Cloud Approach**: Controlled via the `ENABLE_OLLAMA_PULL` flag. When set to `true`, the system runs locally via Ollama; when set to `false`, it bypasses local model downloads and routes directly to Google Gemini cloud services.
* **Automated Fallback Architecture**: Seamlessly falls back to Google Gemini if local Ollama models are missing, slow, or unreachable—ensuring zero service interruption.
* **Vector Search with pgvector**: Utilizes cosine similarity over 768-dimensional embeddings stored directly in PostgreSQL / Supabase (`pgvector`).
* **Fast Ingestion Pipeline**: Ingests, chunks, and vectorizes PDF documents using `pypdf` with automated paragraph chunking.
* **Private User Context**: Validates OIDC bearer tokens, scopes every ingestion and retrieval query to the token subject, and supports permanent per-user context deletion.
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
├── alembic/              # Database migrations
├── app/
│   ├── auth.py           # OIDC token validation and current-user dependency
│   ├── database.py       # SQLAlchemy engine & pooler connection management
│   ├── frontend.py       # Streamlit UI interface & chat workspace
│   ├── ingest.py         # PDF parsing, text chunking, and dual embedding logic
│   ├── main.py           # FastAPI backend with user-scoped RAG operations
│   └── models.py         # User-owned documents and pgvector chunks
├── tests/                # Authentication, isolation, deletion, and migration tests
├── .env.example          # Environment variable template
├── .gitignore            # Git ignore rules
├── Dockerfile            # Multi-process container build (FastAPI + Streamlit + Ollama)
├── docker-compose.yml    # Multi-container orchestration (Postgres & Copilot App)
├── entrypoint.sh         # Container boot script for services & conditional model downloads
├── init_db.py            # Alembic migration runner
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
| `OIDC_ISSUER` | `https://identity.example.com` | Exact issuer expected in verified ID tokens. Required. |
| `OIDC_AUDIENCE` | `your-streamlit-client-id` | Exact ID-token audience; must match the Streamlit OIDC client ID. Required. |
| `OIDC_JWKS_URL` | Provider JWKS URL | Optional; discovered from the issuer when omitted. |
| `OIDC_ALGORITHMS` | `RS256` | Comma-separated asymmetric signing algorithms allowed by the API. |
| `MAX_UPLOAD_BYTES` | `26214400` | Maximum accepted PDF size in bytes. |
| `MAX_PDF_PAGES` | `500` | Maximum pages parsed from one PDF. |
| `MAX_CHUNKS_PER_DOCUMENT` | `10000` | Maximum generated chunks per PDF. |
| `ALLOW_LEGACY_CONTEXT_DELETE` | `false` | Must be set to `true` only after backing up legacy unowned chunks. |
| `POSTGRES_PASSWORD` | URL-safe local password | Password used by the Docker Compose PostgreSQL service. |

---

## OIDC Configuration

Create `.streamlit/secrets.toml` with the OIDC client registered for the Streamlit redirect URL:

```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "replace-with-a-long-random-secret"
client_id = "your-streamlit-client-id"
client_secret = "your-streamlit-client-secret"
server_metadata_url = "https://identity.example.com/.well-known/openid-configuration"
expose_tokens = "id"
```

Set `OIDC_ISSUER` and `OIDC_AUDIENCE` in the API environment. `OIDC_AUDIENCE` must equal the `client_id` above because the API validates the forwarded ID token. The API checks the signature, expiry, issuer, exact audience, authorized party, and required claims through the provider's HTTPS JWKS endpoint. The immutable `sub` claim becomes the document owner, so browser-provided user IDs are never trusted. `API_BASE_URL` must also use HTTPS outside loopback development.

---

## Database Setup

Apply the schema migration before starting the services:

```bash
alembic upgrade head
```

Alternatively, run:

```bash
python init_db.py
```

The first migration adds user-owned `documents`, links `document_chunks` with `ON DELETE CASCADE`, and isolates embeddings by model. If legacy chunks exist, the migration stops unless `ALLOW_LEGACY_CONTEXT_DELETE=true` is explicitly set. After backing up the source PDFs, rerun `alembic upgrade head` with that one-time flag to remove the unowned legacy rows. They cannot be safely assigned or exposed to a user.

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

4. **Configure the API and Streamlit OIDC client:**
   ```bash
   cp .env.example .env
   ```
   Set the database, Gemini, and OIDC values in `.env`, then create `.streamlit/secrets.toml` as shown above.

5. **Apply Database Migrations:**
   ```bash
   alembic upgrade head
   ```

6. **Start the FastAPI Backend:**
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

7. **Start the Streamlit Frontend:**
   ```bash
   streamlit run app/frontend.py --server.port 8501
   ```

---

### Option 2: Running with Docker Compose

You can build and start the entire stack (including local Postgres with `pgvector`) in one step. `POSTGRES_PASSWORD`, `OIDC_ISSUER`, and `OIDC_AUDIENCE` are required, and `.streamlit/secrets.toml` must exist for the runtime-only secret mount:

```bash
docker compose up --build -d
```

Access the services:
* **Streamlit UI**: [http://localhost:8501](http://localhost:8501)
* **FastAPI Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## API Endpoints

All data endpoints require `Authorization: Bearer <OIDC ID token>`. The API derives ownership only from the verified token subject.

### `POST /ingest/`
* **Description**: Uploads and processes a PDF file, then stores an idempotent, user-owned document and its chunks.
* **Payload**: `multipart/form-data` with `file` (`.pdf`).
* **Response**: Document metadata including `id`, `source_filename`, `content_digest`, `embedding_model`, and `created_at`.

### `GET /documents/`
* **Description**: Lists only the authenticated user's saved documents.

### `DELETE /documents/{document_id}`
* **Description**: Permanently deletes one owned document and cascades deletion to all chunks and vectors. Another user's document returns `404`.

### `DELETE /documents/`
* **Description**: Permanently deletes all documents and vectors owned by the authenticated user.

### `POST /search/`
* **Description**: Vectorizes a search string and queries only the authenticated user's chunks using cosine distance.
* **Parameters**: `query` (string), `limit` (integer, default `3`, maximum `20`).
* **Response**: List of document chunks with `document_id`, `source_filename`, `chunk_index`, `content`, and `similarity`.

### `POST /ask/`
* **Description**: Complete RAG endpoint. Retrieves only the authenticated user's top relevant chunks, constructs conversational context, and returns a grounded answer generated by the active LLM.
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

"Clear Chat" in Streamlit only removes conversation messages. "Clear Saved Context" calls `DELETE /documents/` and permanently removes the user's indexed documents and vectors from PostgreSQL.

---

## Tests

Authentication tests run without external services. Database tests require an empty PostgreSQL database with `pgvector` and use only the database named by `TEST_DATABASE_URL`:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/copilot_test_db pytest -q
```
