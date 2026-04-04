# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI — face-recog-worker service
#
# Reads face crops from the face_crops stream (consumer group cg::face_recog),
# runs ArcFace recognition against the Faces_db embedding cache, and publishes
# identity results to identity_results.
#
# CPU-heavy workload (DeepFace / TensorFlow ArcFace inference).
# Stateless: horizontally scalable (KEDA ScaledObject on stream lag).
# Build context: project root (/)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

LABEL maintainer="ObserveAI"
LABEL description="Face recognition worker — ArcFace identity matching via DeepFace"

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OpenCV runtime dependencies
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    # Build tools required by TensorFlow / cryptography wheels
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
COPY containerized/services/face-recog-worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Shared utilities ─────────────────────────────────────────────────────────
COPY containerized/services/shared/ /app/shared/

# ── Service source ────────────────────────────────────────────────────────────
COPY containerized/services/face-recog-worker/main.py /app/main.py

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV REDIS_URL=redis://redis:6379
ENV FACES_DB_PATH=/app/Faces_db
ENV POD_NAME=face-recog-worker-0
ENV LOG_LEVEL=info
# TensorFlow / Keras compatibility required by deepface
ENV TF_USE_LEGACY_KERAS=1
ENV TF_CPP_MIN_LOG_LEVEL=2
# DeepFace ArcFace model weights cache
ENV DEEPFACE_HOME=/app/deepface_weights

# ── Health check ─────────────────────────────────────────────────────────────
# Longer start period: DeepFace downloads ArcFace weights on first run (~200 MB)
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
    CMD python -c "import redis, os; r=redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

# ── Volume mount points ───────────────────────────────────────────────────────
# /app/Faces_db       — face image database (mounted as named volume)
# /app/deepface_weights — DeepFace model weights cache (mounted as named volume)
VOLUME ["/app/Faces_db", "/app/deepface_weights"]

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["python", "main.py"]
