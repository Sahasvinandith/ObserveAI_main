# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI — face-db-writer service
#
# Reads from identity_results (consumer group cg::face_db_writer).
# Implements quality-gated face saving to the Faces_db directory.
# Publishes face_db_events so face-recog-worker pods refresh their caches.
#
# CPU workload; no GPU required.
# Stateless: horizontally scalable (KEDA ScaledObject on stream lag).
# Build context: project root (/)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

LABEL maintainer="ObserveAI"
LABEL description="Face DB writer — quality-gated face saving to Faces_db"

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OpenCV runtime dependencies
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
COPY containerized/services/face-db-writer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Shared utilities ─────────────────────────────────────────────────────────
COPY containerized/services/shared/ /app/shared/

# ── Service source ────────────────────────────────────────────────────────────
COPY containerized/services/face-db-writer/main.py /app/main.py

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV REDIS_URL=redis://redis:6379
ENV FACES_DB_PATH=/app/Faces_db
ENV MAX_FACES_PER_USER=5
ENV POD_NAME=face-db-writer-0
ENV LOG_LEVEL=info

# ── Health check ─────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import redis, os; r=redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

# ── Volume mount point ────────────────────────────────────────────────────────
# /app/Faces_db — face image database shared with face-recog-worker
VOLUME ["/app/Faces_db"]

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["python", "main.py"]
