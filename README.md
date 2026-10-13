<p align="center">
  <img src="docs/screenshot.webp" alt="The copilot's chat interface, showing the welcome panel, starter questions, the seeded profile document and a healthy API Gateway" width="900">
</p>

# Enterprise Knowledge Copilot

A multi-tenant Retrieval-Augmented Generation (RAG) copilot that answers questions grounded in uploaded documents and returns the exact source chunks behind every claim.

**FastAPI** backend · **Streamlit** chat UI · **PostgreSQL / Supabase (`pgvector`)** vector store · **Google Gemini** for embeddings and generation, with an optional local **Ollama** path for development.

Every document, chunk and retrieval query is scoped to the signed-in account, so one visitor's uploads are invisible to another. That isolation is enforced in the API rather than in the interface, and it is covered by tests.

---

## Table of Contents

- [What it does](#what-it-does)
- [Multi-tenancy and identity](#multi-tenancy-and-identity)
- [Resilience](#resilience)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [OIDC setup](#oidc-setup)
- [Database setup](#database-setup)
- [Running locally](#running-locally)
- [API reference](#api-reference)
- [Operations](#operations)
- [Testing](#testing)

---

## What it does

A visitor signs in with Google and lands on a chat that already has something to ask about: a default profile document is ingested into **their own** workspace on first visit, through the same PDF pipeline a real upload uses. They can ask a question immediately, or upload their own PDF, which replaces the default and becomes the only thing the copilot will answer from.

Every answer comes back with the chunks it was built from, so any claim can be checked against its origin rather than taken on trust.

| Capability | Notes |
| :--- | :--- |
| Grounded answers | Top-k cosine retrieval, then generation constrained to the retrieved context |
| Source attribution | Each answer returns the exact chunks used, with relevance scores |
| Multi-tenant | Google OIDC sign-in; ownership derives from the token's `sub` claim and is scoped in SQL |
| Per-user upload | Bring your own PDF; ingest is idempotent per account, file digest and embedding model |
| Cascading delete | Deleting a document removes its chunks and vectors; another user's document returns `404` |
| Seeded default | A first-time visitor always has a real document to ask about |
| Health reporting | `GET /health` checks the database and generator, and returns `503` when either is down |

---

## Multi-tenancy and identity

The corpus is shared infrastructure, so identity sits in the data path rather than in the UI.

**Token verification** (`app/auth.py`) checks the OIDC bearer token against the provider's HTTPS JWKS endpoint, then validates `iss`, `aud`, `azp`, `exp`, `iat` and `sub`. Symmetric algorithms are excluded from the allowlist, so a token signed with a leaked public value cannot pass. `OIDC_ALGORITHMS` must cover what the provider actually publishes — CI checks this against the live JWKS, because an algorithm mismatch fails as an opaque `401` rather than an obvious configuration error.

**Ownership** comes from the immutable `sub` claim. No browser-supplied user identifier is trusted.

Every query is scoped by it:

```text
ingest    -> owner_id = claims["sub"]
search    -> WHERE Document.owner_id = <sub>  (via the chunk join)
ask       -> same
list      -> WHERE Document.owner_id = <sub>
delete    -> WHERE id = <id> AND owner_id = <sub>, else 404
```

Delete returns `404` rather than `403` so it cannot be used to probe for the existence of another user's document.

The cross-tenant isolation tests are the ones that matter most here, and they were previously gated behind `TEST_DATABASE_URL` and silently skipped. CI now runs them against a `pgvector` service container on every push.

---

## Resilience

The service is deployed on a free tier and depends on two things it does not control: an upstream model provider and a free-tier database. Both have failed for real.

**Generation** retries transient errors with exponential backoff, then walks a fallback chain of models:

```text
gemini-3.6-flash -> gemini-flash-latest -> gemini-3.5-flash -> gemini-3.1-flash-lite
```

A single fallback is not enough when an entire model family is degraded. The `3.6`/`3.7`/`3.8` flash family has been observed returning `503 UNAVAILABLE` simultaneously. Classification is by status code rather than exception name, because the SDK raises `ClientError` for a rate limit as readily as for a bad request, and a `400` is never worth retrying.

**Embeddings** get the same treatment. Ingest embeds one call per chunk in a tight loop, so a 12-chunk document makes 12 sequential upstream calls and any one of them hitting a rate limit would otherwise discard every chunk already embedded.

**Health reporting.** The first version of the health indicator probed `/docs`, which answers for as long as the process is alive and never touches the database. It reported "Online" through a dead database. `GET /health` now checks the database and the generator and returns `503` when either is down, and the UI distinguishes `Online` / `Degraded` / `Offline` by name.

---

## Architecture

```text
               +-----------------------------------+
               |        Streamlit Frontend         |
               |             (Port 8501)           |
               +-----------------+-----------------+
                                 |
                       OIDC ID token (Bearer)
                                 |
                                 v
               +-----------------------------------+
               |          FastAPI Backend          |
               |             (Port 8000)           |
               +---------+----------------+--------+
                         |                |
        +----------------+                +---------------+
        |                                 |               |
        v                                 v               v
 +------------------+          +------------------+  +------------------+
 | Embedding        |          | Retrieval        |  | Generation       |
 | Gemini           |          | pgvector,        |  | Gemini           |
 | gemini-embedding |          | cosine distance  |  | retry + fallback |
 | -001, 768-dim    |          | scoped by owner  |  | model chain      |
 | (or Ollama for   |          +--------+---------+  +------------------+
 |  local dev)      |                   |
 +--------+---------+                   |
          |                             |
          +--------------+--------------+
                         v
          +--------------------------------+
          |  Supabase / PostgreSQL         |
          |  pgvector, 768-dim vectors     |
          |  owner_id on every document    |
          +--------------------------------+
```

The container runs FastAPI, Streamlit and (optionally) Ollama as supervised processes. If either web service exits, the container exits rather than serving a UI wired to nothing.

---

## Tech stack

| Layer | Choice |
| :--- | :--- |
| Frontend | Streamlit, dark theme, chat history, upload and document management |
| Backend | FastAPI, Uvicorn, Pydantic v2 |
| Database | PostgreSQL with `pgvector`; Supabase managed in production |
| Migrations | Alembic |
| Identity | Google OIDC, JWT verification via `PyJWT` against the provider JWKS |
| Generation | Google Gemini, configurable model chain with retry |
| Embeddings | `gemini-embedding-001` at 768 dimensions |
| Local dev | Ollama (`llama3`, `nomic-embed-text`) behind `ENABLE_OLLAMA_PULL` |
| Documents | `pypdf`, SQLAlchemy 2.0 |
| Hosting | Render (container) + Supabase |
| CI | GitHub Actions |

> **Note on Ollama.** The local path is a development convenience, not a production fallback. Cloud deployments set `ENABLE_OLLAMA_PULL=false` and run Gemini only.

---

## Project structure

```text
enterprise-copilot/
├── app/
│   ├── auth.py              # OIDC verification and the current-user dependency
│   ├── database.py          # SQLAlchemy engine and session factory
│   ├── frontend.py          # Streamlit UI, chat loop, upload and document sidebar
│   ├── ingest.py            # PDF parsing, chunking, embedding with retry
│   ├── main.py              # FastAPI routes, health probe, generation fallback
│   ├── models.py            # Document and DocumentChunk, owner-scoped
│   └── seed.py              # default profile document, seeded per user
├── alembic/versions/        # ordered, reversible schema migrations
├── seed/
│   ├── profile-source.md    # source text for the seeded document
│   └── profile.pdf          # generated artefact, committed
├── scripts/
│   ├── build_seed_pdf.py    # renders profile-source.md, --check verifies freshness
│   ├── db_heartbeat.py      # database reachability probe for the keep-alive job
│   └── dev.sh               # start/stop/status for local development
├── tests/                   # 44 tests: auth, isolation, resilience, migration, seed
├── .github/workflows/
│   ├── ci.yml               # pgvector service container, runs the full suite
│   └── keep-supabase-awake.yml
├── docs/screenshot.webp
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh            # generates Streamlit auth config, migrates, supervises
└── requirements.txt
```

---

## Configuration

Copy `.env.example` to `.env` and fill it in. The file is commented throughout; the essentials:

| Variable | Purpose |
| :--- | :--- |
| `DATABASE_URL` | PostgreSQL or Supabase connection string. Use the **Transaction** pooler (`6543`) in production. |
| `GEMINI_API_KEY` | Required for cloud embeddings and generation. |
| `GEMINI_CHAT_MODEL` | Primary generation model. |
| `GEMINI_CHAT_MODEL_FALLBACKS` | Comma-separated chain, tried in order after the primary is exhausted. |
| `GEMINI_MAX_ATTEMPTS` / `GEMINI_BACKOFF_SECONDS` | Retry budget for generation. |
| `EMBED_MAX_ATTEMPTS` / `EMBED_BACKOFF_SECONDS` | Retry budget for embeddings. |
| `OIDC_ISSUER` | Exact issuer string; must match the provider's discovery document character for character. |
| `OIDC_AUDIENCE` | **Must equal** the OIDC `client_id`. |
| `OIDC_ALGORITHMS` | Asymmetric algorithms you permit. `RS256` for Google, `ES256` for Supabase Auth. |
| `ENABLE_OLLAMA_PULL` | `false` for cloud deployments. |
| `STREAMLIT_AUTH_*` | Container deploys only; see below. |
| `API_BASE_URL` | `http://localhost:8000` inside one container. HTTPS outside loopback. |
| `MAX_UPLOAD_BYTES`, `MAX_PDF_PAGES`, `MAX_CHUNKS_PER_DOCUMENT` | Ingest limits. |
| `ALLOW_LEGACY_CONTEXT_DELETE` | One-time guard for the legacy-chunk migration. Leave `false`. |

---

## OIDC setup

Register an OAuth client with your provider and add both redirect URIs:

```text
http://localhost:8501/oauth2callback
https://<your-deployment>/oauth2callback
```

### Locally

Create `.streamlit/secrets.toml` (gitignored):

```toml
[auth]
redirect_uri        = "http://localhost:8501/oauth2callback"
cookie_secret       = "<openssl rand -hex 32>"
client_id           = "<your-client-id>"
client_secret       = "<your-client-secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
expose_tokens       = "id"
```

`server_metadata_url` is required for **every** provider, the default one included, and Streamlit validates exactly these three keys. `expose_tokens` is what makes `st.user.tokens["id"]` available; Streamlit exposes no tokens without it, and the app cannot forward a token it was never given.

### In a container

Streamlit reads `[auth]` only from `secrets.toml`, which cannot ship in the image: it holds a client secret, it is gitignored, and `.dockerignore` excludes `.streamlit`. `entrypoint.sh` therefore generates it at boot from these variables, validates the required keys, and refuses to start on a misconfigured deployment:

```bash
STREAMLIT_AUTH_REDIRECT_URI
STREAMLIT_AUTH_CLIENT_ID
STREAMLIT_AUTH_CLIENT_SECRET
STREAMLIT_AUTH_COOKIE_SECRET
STREAMLIT_AUTH_SERVER_METADATA_URL
STREAMLIT_AUTH_EXPOSE_TOKENS
```

The cookie secret must be a fixed value. Regenerating it per boot would sign every visitor out on every deploy.

---

## Database setup

```bash
alembic upgrade head
```

`entrypoint.sh` runs this on every container start, so deploys migrate themselves.

Migrations are additive and reversible. The initial revision introduces user-owned documents; a later one adds `is_seed` so the seeded profile can be distinguished from a real upload. If legacy unowned chunks exist, the migration stops unless `ALLOW_LEGACY_CONTEXT_DELETE=true` is set explicitly, after a backup.

---

## Running locally

```bash
git clone https://github.com/akngngr/enterprise-copilot.git
cd enterprise-copilot

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # fill in DATABASE_URL, GEMINI_API_KEY, OIDC_*
# create .streamlit/secrets.toml as above

alembic upgrade head
./scripts/dev.sh start
```

`scripts/dev.sh` supervises both services and waits for real readiness:

```bash
./scripts/dev.sh start | stop | restart | status | logs
```

To use local Ollama instead of the cloud, set `ENABLE_OLLAMA_PULL=true` and have `llama3` and `nomic-embed-text` available.

**Docker Compose** runs the whole stack including a local `pgvector` Postgres:

```bash
docker compose up --build -d
```

---

## API reference

All data endpoints require `Authorization: Bearer <OIDC ID token>`. Ownership is derived only from the verified token subject.

| Method | Path | Description |
| :--- | :--- | :--- |
| `POST` | `/ingest/` | Upload and index a PDF as the authenticated user. Idempotent. |
| `GET` | `/documents/` | List the user's documents. Seeds the default profile if the account is empty. |
| `POST` | `/search/` | Cosine-similarity search over the user's chunks. |
| `POST` | `/ask/` | Retrieve context and return a grounded answer plus its sources. |
| `DELETE` | `/documents/{id}` | Delete one owned document and its vectors. `404` for another user's. |
| `DELETE` | `/documents/` | Delete every document owned by the user. |
| `GET` | `/health` | Database and generator reachability. `503` when degraded. |

`GET /health` is intentionally unauthenticated so an external probe can reach it.

<details>
<summary><code>POST /ask/</code> request and response</summary>

```json
// request
{
  "question": "What is the leave policy?",
  "history": [
    { "role": "user", "content": "Hello" },
    { "role": "assistant", "content": "Hi! How can I help?" }
  ]
}

// response
{
  "answer": "According to the employee handbook...",
  "sources": [
    {
      "document_id": "…",
      "source_filename": "handbook.pdf",
      "chunk_index": 12,
      "content": "…",
      "similarity": 0.81
    }
  ]
}
```

</details>

---

## Operations

**Keep-alive.** Free-tier Supabase projects pause after seven days without API activity, which takes the corpus offline. `.github/workflows/keep-supabase-awake.yml` resets that timer daily and connects to Postgres directly, because Render's free web service exposes only the Streamlit port — a probe against the application URL would receive `200 text/html` from the Streamlit shell and never reach the database.

Add `DATABASE_URL` as a repository secret under **Settings → Secrets and variables → Actions**.

**Seeded document.** Edit `seed/profile-source.md`, then:

```bash
python3 scripts/build_seed_pdf.py           # rebuild
python3 scripts/build_seed_pdf.py --check   # verify it matches the source
```

The generator is dependency-free and validates its output with the same strict reader the ingest path uses.

---

## Testing

```bash
pytest -q                                                   # no database required
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/copilot_test pytest -q
```

| Suite | Covers |
| :--- | :--- |
| `test_auth.py` | Token verification, audience, authorized party, HTTPS enforcement |
| `test_context_api.py` | **Cross-tenant isolation**, idempotent ingest, cascading delete |
| `test_migration.py` | Migrations are idempotent; the legacy-delete guard holds |
| `test_seed.py` | Seeding policy, per-user scoping, and that a failed seed never breaks a session |
| `test_gemini_resilience.py` | Retry, fallback chain, and that a `400` is not retried |
| `test_embedding_resilience.py` | The same for the per-chunk embedding loop |
| `test_health.py` | The health probe reports a dead database instead of `/docs` |

CI runs the full suite against a `pgvector` service container, checks `entrypoint.sh` syntax, and compares the provider's published JWKS algorithms against `OIDC_ALGORITHMS`.

---

## License

Built as a portfolio project. The code is available to read and learn from.