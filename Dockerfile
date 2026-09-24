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

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and entrypoint script
COPY . .

# Make entrypoint script executable
RUN chmod +x /app/entrypoint.sh

# Expose API port (8000), Streamlit port (8501), and Ollama port (11434)
EXPOSE 8000 8501 11434

# Execute application via entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]