import io
import math
import os
import requests
import time
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from google import genai
from google.genai.types import EmbedContentConfig

from app.models import Document, DocumentChunk

# Environment variables & configurations
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_URL = f"{OLLAMA_BASE_URL}/api/embeddings"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "500"))
MAX_CHUNKS_PER_DOCUMENT = int(os.getenv("MAX_CHUNKS_PER_DOCUMENT", "10000"))

ENABLE_OLLAMA_PULL = os.getenv("ENABLE_OLLAMA_PULL", "false").lower() == "true"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMBED_MAX_ATTEMPTS = max(1, int(os.getenv("EMBED_MAX_ATTEMPTS", "3")))
EMBED_BACKOFF_SECONDS = float(os.getenv("EMBED_BACKOFF_SECONDS", "1.5"))
# 429/500/502/503/504 are worth another attempt; 400/401/403 are not.
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def is_transient(error: Exception) -> bool:
    """Transient = worth retrying. Auth and prompt errors are not.

    Keyed on the status code rather than the exception name: the Gemini SDK
    raises ClientError for a rate limit as readily as for a bad request, and
    treating a 429 as fatal is what makes ingest fail under load.
    """
    status = getattr(error, "code", None)
    if status is None:
        status = getattr(error, "status_code", None)
    if status is not None:
        try:
            return int(status) in TRANSIENT_STATUS_CODES
        except (TypeError, ValueError):
            pass
    return type(error).__name__ in {
        "ServerError",
        "ServiceUnavailable",
        "RateLimitError",
        "ResourceExhausted",
    }

# Initialize Gemini Client if API key is present
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def get_gemini_embedding(text: str) -> list:
    """Generates 768-dim embeddings using Gemini API (gemini-embedding-001).

    Retries transient upstream failures. Ingest embeds one call per chunk in a
    tight loop, so a document of any length multiplies the chance of hitting a
    rate limit or a 503 partway through - and a failure at chunk 11 of 12 throws
    away the whole document. Generation got this treatment already; embeddings
    did not, and that asymmetry is what made ingest the fragile endpoint.
    """
    if not gemini_client:
        raise ValueError("GEMINI_API_KEY environment variable is not configured.")

    last_error: Exception | None = None
    for attempt in range(1, EMBED_MAX_ATTEMPTS + 1):
        try:
            # model="gemini-embedding-001" with output_dimensionality=768
            response = gemini_client.models.embed_content(
                model=GEMINI_EMBEDDING_MODEL,
                contents=text,
                config=EmbedContentConfig(output_dimensionality=768),
            )

            if hasattr(response, "embedding") and hasattr(response.embedding, "values"):
                return validate_embedding(list(response.embedding.values))
            if hasattr(response, "embeddings") and len(response.embeddings) > 0:
                return validate_embedding(list(response.embeddings[0].values))

            raise ValueError("Failed to retrieve valid embedding values from Gemini API.")
        except Exception as error:  # noqa: BLE001 - upstream raises SDK types
            last_error = error
            if not is_transient(error):
                raise
            if attempt < EMBED_MAX_ATTEMPTS:
                delay = EMBED_BACKOFF_SECONDS * (2 ** (attempt - 1))
                print(
                    f"[Embedding] attempt {attempt}/{EMBED_MAX_ATTEMPTS} failed "
                    f"({type(error).__name__}); retrying in {delay}s."
                )
                time.sleep(delay)

    assert last_error is not None
    raise last_error


def validate_embedding(vector) -> list:
    if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"Embedding must contain {EMBEDDING_DIMENSIONS} values")
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
        raise ValueError("Embedding values must be finite numbers")
    return [float(value) for value in vector]


def get_embedding(text: str) -> tuple[list, str]:
    if ENABLE_OLLAMA_PULL:
        try:
            payload = {
                "model": EMBEDDING_MODEL,
                "prompt": text,
            }
            response = requests.post(OLLAMA_EMBED_URL, json=payload, timeout=3)
            if response.status_code == 200:
                vector = validate_embedding(response.json().get("embedding"))
                return vector, f"ollama:{EMBEDDING_MODEL}"
        except (AttributeError, requests.RequestException, TypeError, ValueError) as error:
            print(
                f"[Embedding Fallback] Ollama unavailable or invalid ({error}). "
                "Switching to Gemini API..."
            )

    return get_gemini_embedding(text), f"gemini:{GEMINI_EMBEDDING_MODEL}"


def get_local_embedding(text: str) -> list:
    return get_embedding(text)[0]


def chunk_text(text: str, max_chars: int = 500) -> list:
    if not text:
        return []
    
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(para) > max_chars:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
                current_chunk = ""
            for i in range(0, len(para), max_chars):
                chunks.append(para[i:i + max_chars].strip())
        elif len(current_chunk) + len(para) < max_chars:
            current_chunk += ("\n\n" if current_chunk else "") + para
        else:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            current_chunk = para
            
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
        
    return [c for c in chunks if c]


def process_pdf(
    file_bytes: bytes,
    original_filename: str,
    owner_id: str,
    content_digest: str,
    db: Session,
    is_seed: bool = False,
) -> Document:
    print(f"Processing '{original_filename}'...")
    reader = PdfReader(io.BytesIO(file_bytes), strict=True)
    if len(reader.pages) > MAX_PDF_PAGES:
        raise ValueError(f"The PDF exceeds the {MAX_PDF_PAGES} page limit")

    full_text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            full_text += extracted.strip() + "\n\n"

    raw_chunks = chunk_text(full_text)
    if not raw_chunks:
        raise ValueError("The PDF does not contain extractable text")
    if len(raw_chunks) > MAX_CHUNKS_PER_DOCUMENT:
        raise ValueError(
            f"The PDF exceeds the {MAX_CHUNKS_PER_DOCUMENT} chunk limit"
        )

    print(f"Split into {len(raw_chunks)} chunks. Generating embeddings...")
    embedding_results = [get_embedding(text_chunk) for text_chunk in raw_chunks]
    embedding_models = {model for _, model in embedding_results}
    if len(embedding_models) != 1:
        raise RuntimeError("Embedding backend changed during document ingestion")
    embedding_model = embedding_models.pop()
    vectors = [vector for vector, _ in embedding_results]

    existing_document = db.scalar(
        select(Document).where(
            Document.owner_id == owner_id,
            Document.content_digest == content_digest,
            Document.embedding_model == embedding_model,
        )
    )
    if existing_document:
        return existing_document

    document = Document(
        owner_id=owner_id,
        source_filename=original_filename,
        content_digest=content_digest,
        embedding_model=embedding_model,
        is_seed=is_seed,
    )
    db.add(document)

    try:
        db.flush()
        for index, (text_chunk, vector) in enumerate(zip(raw_chunks, vectors)):
            db.add(
                DocumentChunk(
                    document_id=document.id,
                    source_filename=original_filename,
                    chunk_index=index,
                    content=text_chunk,
                    embedding=vector,
                )
            )
        db.commit()
        db.refresh(document)
    except IntegrityError:
        db.rollback()
        existing_document = db.scalar(
            select(Document).where(
                Document.owner_id == owner_id,
                Document.content_digest == content_digest,
                Document.embedding_model == embedding_model,
            )
        )
        if existing_document:
            return existing_document
        raise
    except Exception:
        db.rollback()
        raise

    print(f"Successfully stored {len(raw_chunks)} chunks for '{original_filename}' in PostgreSQL!")
    return document
