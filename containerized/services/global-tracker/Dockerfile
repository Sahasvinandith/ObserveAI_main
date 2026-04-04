# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI — global-tracker service
#
# Singleton global person tracker.
# Reads Re-ID feature updates from reid_features (plain XREAD — singleton).
# Reads identity assignments from identity_results (consumer group
# cg::global_tracker_identity).
# Maintains GlobalPersonTracker state with EMA feature blending + cosine matching.
# Exposes FastAPI HTTP API:
#   GET /global_persons  — snapshot of all tracked persons
#   GET /health          — liveness probe
# Writes global_id::{camera}::{track} Redis keys for other services to consume.
#
# CPU workload; no GPU required.
# Singleton: 1 pod only — no HPA.
# Build context: project root (/)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

LABEL maintainer="ObserveAI"
LABEL description="Global person tracker — singleton FastAPI service with EMA Re-ID blending"

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OpenCV runtime dependencies (cv2.compareHist, cvtColor used in tracker)
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
COPY containerized/services/global-tracker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Shared utilities ─────────────────────────────────────────────────────────
COPY containerized/services/shared/ /app/shared/

# ── Service source ────────────────────────────────────────────────────────────
COPY containerized/services/global-tracker/main.py /app/main.py

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV REDIS_URL=redis://redis:6379
ENV HTTP_PORT=8080
ENV LOG_LEVEL=info

# ── Expose HTTP port ──────────────────────────────────────────────────────────
EXPOSE 8080

# ── Health check ─────────────────────────────────────────────────────────────
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["python", "main.py"]
