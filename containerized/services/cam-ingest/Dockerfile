# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI — cam-ingest service
#
# Reads frames from a camera source (RTSP URL or /dev/videoN) and publishes
# them to the shared_raw_frames Redis Stream.
#
# I/O-bound workload; no GPU required.
# Build context: project root (/)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim

LABEL maintainer="ObserveAI"
LABEL description="Camera ingestion — reads frames and publishes to shared_raw_frames"

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OpenCV runtime dependencies
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    # ffmpeg for RTSP / H.264 decoding via OpenCV
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    # V4L2 utils (for USB camera detection)
    v4l-utils \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
COPY containerized/services/cam-ingest/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Shared utilities ─────────────────────────────────────────────────────────
COPY containerized/services/shared/ /app/shared/

# ── Service source ────────────────────────────────────────────────────────────
COPY containerized/services/cam-ingest/main.py /app/main.py

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV REDIS_URL=redis://redis:6379
ENV CAMERA_NAME=default_camera
ENV CAMERA_SOURCE=0
ENV LOG_LEVEL=info

# ── Health check ─────────────────────────────────────────────────────────────
# Verify Redis is reachable (simple connectivity test)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import redis, os; r=redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["python", "main.py"]
