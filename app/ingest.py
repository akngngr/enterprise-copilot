import os
import requests
from pypdf import PdfReader
from sqlalchemy.orm import Session
from google import genai
from google.genai.types import EmbedContentConfig

from app.database import SessionLocal
from app.models import DocumentChunk

# Environment variables & configurations
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_URL = f"{OLLAMA_BASE_URL}/api/embeddings"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

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
        model="gemini-embedding-001",
        contents=text,
        config=EmbedContentConfig(
            output_dimensionality=768
        )
    )
    
    # Handle response structure cleanly from google-genai SDK
    if hasattr(response, "embedding") and hasattr(response.embedding, "values"):
        return list(response.embedding.values)
    elif hasattr(response, "embeddings") and len(response.embeddings) > 0:
        return list(response.embeddings[0].values)
    
    raise ValueError("Failed to retrieve valid embedding values from Gemini API.")


def get_local_embedding(text: str) -> list:
    """
    Generates embeddings using local Ollama if enabled.
    Falls back gracefully to Gemini API when Ollama is unavailable.
    """
    if ENABLE_OLLAMA_PULL:
        try:
            payload = {
                "model": EMBEDDING_MODEL,
                "prompt": text
            }
            response = requests.post(OLLAMA_EMBED_URL, json=payload, timeout=3)
            if response.status_code == 200:
                return response.json().get("embedding")
        except Exception as e:
            print(f"[Embedding Fallback] Ollama unreachable ({e}). Switching to Gemini API...")

    return get_gemini_embedding(text)


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


def process_pdf(file_path: str):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    filename = os.path.basename(file_path)
    print(f"Processing '{filename}'...")

    reader = PdfReader(file_path)
    full_text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            full_text += extracted + "\n"

    raw_chunks = chunk_text(full_text)
    print(f"Split into {len(raw_chunks)} chunks. Generating embeddings...")

    db: Session = SessionLocal()
    try:
        for index, text_chunk in enumerate(raw_chunks):
            vector = get_local_embedding(text_chunk)
            db_chunk = DocumentChunk(
                source_filename=filename,
                chunk_index=index,
                content=text_chunk,
                embedding=vector
            )
            db.add(db_chunk)
        db.commit()
        print(f"Successfully stored {len(raw_chunks)} chunks for '{filename}' in PostgreSQL!")

    except Exception as e:
        db.rollback()
        print(f"Error during ingestion transaction: {e}")
        raise e
    finally:
        db.close()