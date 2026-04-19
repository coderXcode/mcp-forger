FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    nodejs \
    npm \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create runtime directories
RUN mkdir -p data logs generated

# Expose FastAPI port
EXPOSE 8000
# Expose MCP server port
EXPOSE 8001

# Default: run the web app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
