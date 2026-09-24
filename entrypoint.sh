#!/bin/bash

# Start Ollama service in the background
echo "Starting Ollama service..."
ollama serve &

# Wait briefly for Ollama daemon to initialize
sleep 2

# Conditionally pull models if requested via environment variable
if [ "$ENABLE_OLLAMA_PULL" = "true" ]; then
    echo "ENABLE_OLLAMA_PULL is set to true. Pulling models..."
    ollama pull nomic-embed-text &
    ollama pull llama3 &
else
    echo "ENABLE_OLLAMA_PULL is not set to true. Skipping model downloads."
fi

# Start FastAPI server in the background
echo "Starting FastAPI server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# Start Streamlit UI in the foreground
echo "Starting Streamlit UI..."
exec streamlit run app/frontend.py --server.address=0.0.0.0 --server.port=8501