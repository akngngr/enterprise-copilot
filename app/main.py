import os
import requests
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from google import genai
from google.genai import types

from app.database import get_db, engine, Base
from app.models import DocumentChunk
from app.ingest import process_pdf, get_local_embedding

app = FastAPI(title="Enterprise Knowledge & Support Copilot", version="1.0.0")

# Ollama Configurations
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_GEN_URL = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_EMBED_URL = f"{OLLAMA_BASE_URL}/api/embeddings"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/copilot_db")
GEN_MODEL = os.getenv("GEN_MODEL", "llama3")

# Gemini Fallback Configurations
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class AskRequest(BaseModel):
    question: str
    history: List[ChatMessage] = []


class SearchResult(BaseModel):
    source_filename: str
    chunk_index: int
    content: str
    similarity: float


class AskResponse(BaseModel):
    answer: str
    sources: List[SearchResult]

    model_config = {"from_attributes": True}


# Database setup
with engine.begin() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

Base.metadata.create_all(bind=engine)


def query_ollama(prompt: str) -> str:
    """Attempts generation via local Ollama API."""
    payload = {
        "model": GEN_MODEL,
        "prompt": prompt,
        "stream": False
    }
    # Short timeout (10s) so cloud deployments don't hang before triggering Gemini
    response = requests.post(OLLAMA_GEN_URL, json=payload, timeout=10)
    response.raise_for_status()
    return response.json().get("response", "").strip()


def query_gemini(prompt: str) -> str:
    """Fallback generation via Google Gemini API."""
    if not gemini_client:
        raise ValueError("GEMINI_API_KEY environment variable is not configured.")

    response = gemini_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
        ),
    )
    return response.text.strip()


@app.post("/ingest/")
async def ingest_document(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    temp_file_path = f"temp_{file.filename}"
    try:
        with open(temp_file_path, "wb") as buffer:
            buffer.write(await file.read())

        process_pdf(temp_file_path)
        return {"status": "success", "filename": file.filename, "message": "Document ingested and embedded successfully."}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while processing the document: {str(e)}")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)


@app.post("/search/", response_model=List[SearchResult])
async def search_documents(query: str, limit: int = 3, db: Session = Depends(get_db)):
    try:
        query_vector = get_local_embedding(query)

        results = db.query(
            DocumentChunk,
            DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
        ).order_by("distance").limit(limit).all()

        response = []
        for chunk, distance in results:
            similarity = float(1 - distance)
            response.append(SearchResult(
                source_filename=chunk.source_filename,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                similarity=similarity
            ))

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred while searching the documents: {str(e)}")


@app.post("/ask/", response_model=AskResponse)
async def ask_copilot(payload: AskRequest, db: Session = Depends(get_db)):
    """
    RAG Pipeline Endpoint: Retrieves relevant document chunks and 
    prompts the local LLM (Ollama) with automatic fallback to Gemini API.
    """
    try:
        question = payload.question
        history = payload.history

        # 1. Search top relevant chunks
        query_vector = get_local_embedding(question)
        results = db.query(
            DocumentChunk,
            (DocumentChunk.embedding.cosine_distance(query_vector)).label("distance")
        ).order_by("distance").limit(3).all()

        if not results:
            return AskResponse(answer="I couldn't find any relevant documents to answer your question.", sources=[])

        # 2. Extract sources & build context
        sources = []
        context_text = ""
        for chunk, distance in results:
            similarity = float(1 - distance)
            sources.append(SearchResult(
                source_filename=chunk.source_filename,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                similarity=similarity
            ))
            context_text += f"\n---\n{chunk.content}"

        history_text = ""
        for msg in history[-4:]:
            role_label = "User" if msg.role == "user" else "Assistant"
            history_text += f"{role_label}: {msg.content}\n"

        # 3. Construct prompt
        prompt = f"""You are an enterprise knowledge and support copilot. Answer the user's question accurately using ONLY the provided context below. If you cannot find the answer in the context, state that you don't know.

Context:
{context_text}

Conversation History:
{history_text if history_text else 'No prior conversation.'}

User Question: {question}
Answer:"""

        # 4. Attempt Ollama generation first, fallback to Gemini API
        answer_text = ""
        try:
            answer_text = query_ollama(prompt)
        except Exception as ollama_err:
            print(f"[Fallback Triggered] Ollama failed ({ollama_err}). Switching to Gemini API...")
            try:
                answer_text = query_gemini(prompt)
            except Exception as gemini_err:
                raise HTTPException(
                    status_code=500,
                    detail=f"Both primary (Ollama) and fallback (Gemini) LLM engines failed: {gemini_err}"
                )

        return AskResponse(answer=answer_text, sources=sources)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG pipeline failed: {str(e)}")