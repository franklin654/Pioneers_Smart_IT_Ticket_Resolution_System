FROM python:3.11-slim AS base

WORKDIR /app

# Build deps: gcc for numpy/scikit-learn, libpq-dev for asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
# Install all runtime deps (no dev extras)
RUN pip install --no-cache-dir -e .

# Download spaCy model used by Presidio PII masker (en_core_web_sm)
RUN python -m spacy download en_core_web_sm

# Pre-fetch sentence-transformers model so first request isn't slow
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY src/ src/

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD curl -f http://localhost:8000/api/v1/health/live || exit 1

CMD ["uvicorn", "src.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--log-config", "/dev/null"]
