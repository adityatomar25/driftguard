# ── DriftGuard API ────────────────────────────────────────────
# Multi-stage build for smaller production image
# Build:  docker build -t driftguard-api .
# Run:    docker run -p 8000:8000 driftguard-api

# --- stage 1: install deps ---
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- stage 2: runtime ---
FROM python:3.11-slim

LABEL org.opencontainers.image.title="DriftGuard API" \
      org.opencontainers.image.description="Infrastructure drift detection & reconciliation" \
      org.opencontainers.image.source="https://github.com/adityatomar25/driftguard"

RUN groupadd -r driftguard && useradd -r -g driftguard driftguard

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

# Writable data directory for the SQLite DB
RUN mkdir -p /data && chown driftguard:driftguard /data
VOLUME ["/data"]

USER driftguard

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/metrics')" || exit 1

CMD ["uvicorn", "driftguard.api:app", "--host", "0.0.0.0", "--port", "8000"]
