# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI — deepsort-tracker service
#
# Per-camera stateful DeepSORT tracker pod.
# Reads person_detections::{CAMERA_NAME} via plain XREAD BLOCK (no consumer
# group — ordering is critical and one pod owns each camera stream).
# Publishes confirmed tracks to person_tracks::{CAMERA_NAME}.
#
# CPU workload; no GPU required.
# Stateful: 1 pod per camera, no horizontal scaling.
# Build context: project root (/)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

LABEL maintainer="ObserveAI"
LABEL description="DeepSORT tracker — stateful per-camera tracker pod"

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
COPY containerized/services/deepsort-tracker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Shared utilities ─────────────────────────────────────────────────────────
COPY containerized/services/shared/ /app/shared/

# ── Service source ────────────────────────────────────────────────────────────
COPY containerized/services/deepsort-tracker/main.py /app/main.py

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV REDIS_URL=redis://redis:6379
ENV CAMERA_NAME=default_camera
ENV LOG_LEVEL=info

# ── Health check ─────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import redis, os; r=redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["python", "main.py"]
