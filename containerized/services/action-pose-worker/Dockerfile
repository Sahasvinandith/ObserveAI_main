# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI — action-pose-worker service
#
# Reads confirmed person tracks from person_tracks::{CAMERA_NAME} (consumer
# group cg::action_detect), runs YOLOv8n-pose estimation, and compares
# keypoints against reference actions loaded from /app/Actions_db/.
# Publishes matched actions to action_events stream.
#
# GPU workload: requires NVIDIA CUDA runtime.
# Stateless: horizontally scalable (KEDA ScaledObject on stream lag).
# Build context: project root (/)
# ─────────────────────────────────────────────────────────────────────────────

FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

LABEL maintainer="ObserveAI"
LABEL description="Action/pose detection worker — YOLOv8n-pose on person crops"

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3.12-distutils \
    python3.12-venv \
    curl \
    # OpenCV runtime dependencies
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Install pip for Python 3.12
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

# Make python3.12 the default interpreter
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# ── Working directory ────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
COPY containerized/services/action-pose-worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Shared utilities ─────────────────────────────────────────────────────────
COPY containerized/services/shared/ /app/shared/

# ── Service source ────────────────────────────────────────────────────────────
COPY containerized/services/action-pose-worker/main.py /app/main.py

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV REDIS_URL=redis://redis:6379
ENV CAMERA_NAME=
ENV ACTIONS_DB_PATH=/app/Actions_db
ENV POSE_MODEL_PATH=/app/yolo-weights/yolov8n-pose.pt
ENV POD_NAME=action-pose-worker-0
ENV LOG_LEVEL=info
ENV YOLO_CONFIG_DIR=/app/yolo-weights

# ── Health check ─────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import redis, os; r=redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

# ── Volume mount points ───────────────────────────────────────────────────────
# /app/Actions_db     — pose action JSON reference files
# /app/yolo-weights   — YOLO model weights (read-only)
VOLUME ["/app/Actions_db"]

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["python", "main.py"]
