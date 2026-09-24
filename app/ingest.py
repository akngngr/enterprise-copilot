import os
from pypdf import PdfReader
import requests
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import DocumentChunk

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

OLLAMA_GEN_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_EMBED_URL = f"{OLLAMA_BASE_URL}/api/embeddings"
EMBEDDING_MODEL = "nomic-embed-text"

def get_local_embedding(text: str) -> list:

    payload = {
        "model": EMBEDDING_MODEL,
        "prompt": text
    }
    response = requests.post(OLLAMA_EMBED_URL, json=payload)
    if response.status_code == 200:
        return response.json().get("embedding")
    else:
        raise Exception(f"Ollama embedding failed: {response.text}")

def chunk_text(text:str, max_chars: int = 500) -> list:

    if not text:
        return []
    
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        # If a single paragraph is longer than max_chars, force-split it
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
    print(f"Split into {len(raw_chunks)} chunks. Generating via Ollama...")

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
    finally:
        db.close()

if __name__ == "__main__":
    sample_file = "test.pdf"
    if os.path.exists(sample_file):
        process_pdf(sample_file)
    else:
        print(f"Place a file named '{sample_file}' in the project root to test the ingestion process.")
