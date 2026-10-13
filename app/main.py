import hashlib
import os
import time
from datetime import datetime
from typing import List, Literal
from uuid import UUID

import requests
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.database import get_db
from app.ingest import get_embedding, process_pdf
from app.models import Document, DocumentChunk
from app.seed import drop_seed, ensure_seed_document

app = FastAPI(title="Enterprise Knowledge & Support Copilot", version="2.0.0")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_GEN_URL = f"{OLLAMA_BASE_URL}/api/generate"
GEN_MODEL = os.getenv("GEN_MODEL", "llama3")
ENABLE_OLLAMA_PULL = os.getenv("ENABLE_OLLAMA_PULL", "false").lower() == "true"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.6-flash")
# A chain, not a single fallback. The whole gemini-3.6/3.7/3.8 flash family has
# been observed returning 503 UNAVAILABLE at the same moment, so a fallback that
# is a sibling alias of the primary buys nothing. gemini-3.5-flash is deprecated
# and redirects to 3.6 (response model_version confirms it) but is served from a
# different path that stayed healthy through that outage; gemini-3.1-flash-lite
# is slower but independent.
def _fallback_models() -> tuple[str, ...]:
    raw = os.getenv("GEMINI_CHAT_MODEL_FALLBACKS") or os.getenv(
        "GEMINI_CHAT_MODEL_FALLBACK", "gemini-flash-latest"
    )
    return tuple(m.strip() for m in raw.split(",") if m.strip())


GEMINI_CHAT_MODEL_FALLBACKS = _fallback_models()
GEMINI_MAX_ATTEMPTS = max(1, int(os.getenv("GEMINI_MAX_ATTEMPTS", "3")))
GEMINI_BACKOFF_SECONDS = float(os.getenv("GEMINI_BACKOFF_SECONDS", "1.5"))
# 429/500/502/503/504 are worth another attempt; 400/401/403 are not.
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


@app.middleware("http")
async def enforce_request_size(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/ingest/":
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_REQUEST_BYTES:
                    return Response(
                        content='{"detail":"Request body is too large"}',
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        media_type="application/json",
                    )
            except ValueError:
                return Response(
                    content='{"detail":"Invalid Content-Length header"}',
                    status_code=status.HTTP_400_BAD_REQUEST,
                    media_type="application/json",
                )
    return await call_next(request)


class ComponentStatus(BaseModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: ComponentStatus
    generator: ComponentStatus


@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health(response: Response, db: Session = Depends(get_db)):
    """Readiness probe that checks the dependencies, not just that the process booted.

    `/docs` answers for as long as uvicorn is alive, which is why a dead
    DATABASE_URL used to render as a healthy app: the Streamlit sidebar reported
    "API Gateway Online" while every database-backed endpoint returned 500.

    Callers must read the `status` field, not the HTTP code alone. A degraded
    service returns 503 so external probes fail loudly instead of silently.
    """
    try:
        db.execute(text("SELECT 1"))
        database = ComponentStatus(status="ok")
    except Exception as error:
        database = ComponentStatus(status="error", detail=type(error).__name__)

    generator_ready = bool(gemini_client) or ENABLE_OLLAMA_PULL
    generator = ComponentStatus(
        status="ok" if generator_ready else "error",
        detail=None if generator_ready else "neither GEMINI_API_KEY nor ENABLE_OLLAMA_PULL is set",
    )

    overall = "ok" if database.status == "ok" and generator.status == "ok" else "degraded"
    if overall != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status=overall, database=database, generator=generator)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)
    history: List[ChatMessage] = Field(default_factory=list)


class SearchResult(BaseModel):
    document_id: UUID
    source_filename: str
    chunk_index: int
    content: str
    similarity: float


class AskResponse(BaseModel):
    answer: str
    sources: List[SearchResult]


class DocumentResponse(BaseModel):
    id: UUID
    source_filename: str
    content_digest: str
    embedding_model: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ClearContextResponse(BaseModel):
    status: str
    documents_deleted: int


def query_ollama(prompt: str) -> str:
    payload = {
        "model": GEN_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    response = requests.post(OLLAMA_GEN_URL, json=payload, timeout=2)
    response.raise_for_status()
    return response.json().get("response", "").strip()


def query_gemini(prompt: str) -> str:
    """Generate with Gemini, retrying transient upstream failures.

    Gemini returns 503 UNAVAILABLE ("high demand") under load, and the SDK's
    own retries can all be exhausted inside a single request. Without a second
    attempt here a busy model takes the whole RAG pipeline down with it, which
    is how a demo fails in front of a customer. On the last attempt we switch to
    a fallback model rather than failing outright.
    """
    if not gemini_client:
        raise ValueError("GEMINI_API_KEY environment variable is not configured.")

    models = [GEMINI_CHAT_MODEL]
    models.extend(
        m for m in GEMINI_CHAT_MODEL_FALLBACKS if m and m != GEMINI_CHAT_MODEL
    )

    last_error: Exception | None = None

    for index, model in enumerate(models):
        for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
            try:
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                    ),
                )
                text = (response.text or "").strip()
                if text:
                    if index:
                        print(
                            f"[Gemini] primary {models[0]} unavailable after "
                            f"{GEMINI_MAX_ATTEMPTS} attempts; answered with {model}."
                        )
                    return text
                last_error = RuntimeError(f"{model} returned an empty response")
            except Exception as error:  # noqa: BLE001 - upstream raises SDK types
                last_error = error
                if not _is_transient(error):
                    raise
                if attempt < GEMINI_MAX_ATTEMPTS:
                    delay = GEMINI_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    print(
                        f"[Gemini] {model} attempt {attempt}/{GEMINI_MAX_ATTEMPTS} "
                        f"failed ({type(error).__name__}); retrying in {delay}s."
                    )
                    time.sleep(delay)
        if index + 1 < len(models):
            print(f"[Gemini] {model} exhausted; trying {models[index + 1]}.")

    assert last_error is not None
    raise last_error


def _is_transient(error: Exception) -> bool:
    """Transient = worth retrying. Auth and prompt errors are not."""
    status = getattr(error, "code", None)
    if status is None:
        status = getattr(getattr(error, "status_code", None), "__int__", lambda: None)()
    if status is not None:
        try:
            return int(status) in TRANSIENT_STATUS_CODES
        except (TypeError, ValueError):
            pass
    name = type(error).__name__
    return name in {"ServerError", "ServiceUnavailable", "RateLimitError", "ResourceExhausted"}


def find_user_chunks(
    db: Session,
    owner_id: str,
    embedding_model: str,
    query_vector: list,
    limit: int,
) -> list:
    distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
    return (
        db.query(DocumentChunk, distance)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(
            Document.owner_id == owner_id,
            Document.embedding_model == embedding_model,
        )
        .order_by(distance)
        .limit(limit)
        .all()
    )


def to_search_result(chunk: DocumentChunk, distance: float) -> SearchResult:
    return SearchResult(
        document_id=chunk.document_id,
        source_filename=chunk.source_filename,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        similarity=float(1 - distance),
    )


@app.post("/ingest/", response_model=DocumentResponse)
def ingest_document(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # A real upload supersedes the seeded default: drop the seed so the
    # visitor's own document is the only thing the copilot will answer from.
    # Without this, /ask/ would blend their PDF with a stranger's profile.
    drop_seed(db, user.id)
    original_filename = os.path.basename((file.filename or "").replace("\\", "/"))
    if not original_filename or not original_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    file_bytes = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"PDF exceeds the {MAX_UPLOAD_BYTES} byte upload limit",
        )
    if not file_bytes:
        raise HTTPException(status_code=400, detail="The uploaded PDF is empty")

    try:
        document = process_pdf(
            file_bytes=file_bytes,
            original_filename=original_filename,
            owner_id=user.id,
            content_digest=hashlib.sha256(file_bytes).hexdigest(),
            db=db,
        )
        return DocumentResponse.model_validate(document)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        # Log the real cause. Without this the response is a bare "Document
        # ingestion failed": a transient upstream 503 and a schema bug look
        # identical from outside, and ingest was previously the one endpoint
        # that swallowed its cause.
        print(f"[ingest] {original_filename!r} failed: {type(error).__name__}: {error}")
        raise HTTPException(status_code=500, detail="Document ingestion failed") from error


@app.post("/search/", response_model=List[SearchResult])
def search_documents(
    query: str = Query(min_length=1, max_length=20_000),
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(default=3, ge=1, le=20),
    db: Session = Depends(get_db),
):
    try:
        query_vector, embedding_model = get_embedding(query)
        results = find_user_chunks(
            db,
            user.id,
            embedding_model,
            query_vector,
            limit,
        )
        return [to_search_result(chunk, distance) for chunk, distance in results]
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Document search failed",
        ) from error


@app.get("/documents/", response_model=List[DocumentResponse])
def list_documents(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # The sidebar loads this on every page render, so it is the natural place to
    # make sure a first-time visitor has something to ask a question about.
    ensure_seed_document(db, user.id)

    documents = (
        db.query(Document)
        .filter(Document.owner_id == user.id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [DocumentResponse.model_validate(document) for document in documents]


@app.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = db.execute(
        delete(Document).where(
            Document.id == document_id,
            Document.owner_id == user.id,
        )
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Document not found")
    db.commit()


@app.delete("/documents/", response_model=ClearContextResponse)
def clear_context(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = db.execute(delete(Document).where(Document.owner_id == user.id))
    db.commit()
    return ClearContextResponse(
        status="success",
        documents_deleted=int(result.rowcount or 0),
    )


@app.post("/ask/", response_model=AskResponse)
def ask_copilot(
    payload: AskRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        question = payload.question
        query_vector, embedding_model = get_embedding(question)
        results = find_user_chunks(
            db,
            user.id,
            embedding_model,
            query_vector,
            3,
        )

        if not results:
            return AskResponse(
                answer="I couldn't find any relevant documents to answer your question.",
                sources=[],
            )

        sources = [to_search_result(chunk, distance) for chunk, distance in results]
        context_text = "".join(f"\n---\n{chunk.content}" for chunk, _ in results)
        history_text = "".join(
            f"{'User' if message.role == 'user' else 'Assistant'}: {message.content}\n"
            for message in payload.history[-4:]
        )
        prompt = f"""You are an enterprise knowledge and support copilot. Answer the user's question accurately using ONLY the provided context below. If you cannot find the answer in the context, state that you don't know.

Context:
{context_text}

Conversation History:
{history_text if history_text else 'No prior conversation.'}

User Question: {question}
Answer:"""

        if ENABLE_OLLAMA_PULL:
            try:
                answer_text = query_ollama(prompt)
            except Exception as ollama_error:
                print(
                    f"[Fallback Triggered] Local Ollama failed ({ollama_error}). "
                    "Switching to Gemini API..."
                )
                answer_text = query_gemini(prompt)
        else:
            answer_text = query_gemini(prompt)

        return AskResponse(answer=answer_text, sources=sources)
    except HTTPException:
        raise
    except Exception as error:
        # Log the real cause. Without this the response is a bare
        # "RAG pipeline failed" and the cause is invisible: a transient upstream
        # 503 and a real bug look identical from the outside.
        print(f"[RAG] ask failed: {type(error).__name__}: {error}")
        raise HTTPException(status_code=500, detail="RAG pipeline failed") from error
