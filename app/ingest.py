import io
import math
import os
import requests
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

# Initialize Gemini Client if API key is present
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def get_gemini_embedding(text: str) -> list:
    """Generates 768-dim embeddings using Gemini API (gemini-embedding-001)."""
    if not gemini_client:
        raise ValueError("GEMINI_API_KEY environment variable is not configured.")
    
    # Notice: model="gemini-embedding-001" and output_dimensionality=768
    response = gemini_client.models.embed_content(
        model=GEMINI_EMBEDDING_MODEL,
        contents=text,
        config=EmbedContentConfig(
            output_dimensionality=768
        )
    )
    
    if hasattr(response, "embedding") and hasattr(response.embedding, "values"):
        return validate_embedding(list(response.embedding.values))
    if hasattr(response, "embeddings") and len(response.embeddings) > 0:
        return validate_embedding(list(response.embeddings[0].values))

    raise ValueError("Failed to retrieve valid embedding values from Gemini API.")


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
