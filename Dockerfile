FROM python:3.10-slim

WORKDIR /app

# Install system dependencies, curl, and zstd (required for Ollama installation)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    zstd \
    && rm -rf /var/lib/apt/lists/*

# Install Ollama engine
RUN curl -fsSL https://ollama.com/install.sh | sh

# Boot Ollama in the background temporarily to pull and bake models into the image
RUN bash -c "ollama serve & sleep 5 && ollama pull nomic-embed-text && ollama pull llama3"

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose API port (8000), Streamlit port (8501), and Ollama port (11434)
EXPOSE 8000 8501 11434

# Start Ollama and FastAPI in the background, then launch Streamlit in the foreground
CMD ["bash", "-c", "ollama serve & uvicorn app.main:app --host 0.0.0.0 --port 8000 & streamlit run app/frontend.py --server.address=0.0.0.0 --server.port=8501"]