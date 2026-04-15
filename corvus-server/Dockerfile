# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# Stage 2: Production image
FROM python:3.11-slim AS production

# Install curl and jq for entrypoint scripts (1Password Connect secret fetching)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*


# Security: Create non-root user
RUN groupadd --gid 1000 corvus \
    && useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home corvus

WORKDIR /app

# Install dependencies from wheels (faster, no build tools needed)
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application code
COPY src/ src/
COPY runbooks/ /app/config/runbooks/

# Security: Set proper ownership
RUN chown -R corvus:corvus /app

# Switch to non-root user
USER corvus

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=2).raise_for_status()"

VOLUME /data

EXPOSE 8000

CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
