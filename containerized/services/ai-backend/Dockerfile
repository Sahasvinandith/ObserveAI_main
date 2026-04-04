# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI — ai-backend service
#
# Runs the FastAPI server (web/server.py) together with all AI components:
#   - CameraWorker (web/camera_manager.py:CameraWorkerThread)
#   - DetectionSystem (DataModel/DetectionSystem.py)
#   - GlobalPersonTracker (DataModel/GlobalPersonTracker.py)
#   - EmbeddingCache / DeepFace (DataModel/EmbeddingCache.py)
#
# These components share in-process memory via Python threading + queues.
# Splitting them across containers would require a message-broker rewrite,
# so they all live in this single service.
#
# Build context: project root (/)
# Dockerfile location: containerized/services/ai-backend/Dockerfile
#
# GPU: Pass NVIDIA GPU via --gpus=all (or k8s nvidia.com/gpu resource).
#      Falls back to CPU automatically (torch.cuda.is_available() == False).
# ─────────────────────────────────────────────────────────────────────────────

ARG CUDA_VERSION=12.4.1
ARG UBUNTU_VERSION=22.04

# Use the NVIDIA CUDA base image to support GPU-accelerated YOLO and Re-ID.
# If you do NOT have an NVIDIA GPU, swap to:
#   FROM python:3.12-slim
FROM nvidia/cuda:${CUDA_VERSION}-cudnn-runtime-ubuntu${UBUNTU_VERSION}

LABEL maintainer="ObserveAI"
LABEL description="AI backend — FastAPI + YOLO + DeepSORT + DeepFace + GlobalPersonTracker"

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python 3.12 (Ubuntu 22.04 ships 3.10; we add the deadsnakes PPA)
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3.12-distutils \
    python3.12-venv \
    # pip bootstrap
    curl \
    # OpenCV runtime dependencies
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    # V4L2 utils (for USB camera detection — non-fatal if absent)
    v4l-utils \
    # ffmpeg for RTSP / H.264 decoding via OpenCV
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libswscale-dev \
    # Build tools required by some pip packages (e.g., cryptography)
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install pip for Python 3.12 via get-pip.py
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

# Make python3.12 the default interpreter
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# ── Python dependencies ──────────────────────────────────────────────────────
# Copy requirements first — Docker caches this layer until requirements change.
COPY containerized/services/ai-backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Application source ────────────────────────────────────────────────────────
WORKDIR /app

# Copy Python source packages (DataModel, web, components needed by web stack)
COPY DataModel/          /app/DataModel/
COPY web/                /app/web/

# Copy the web entry point
COPY web_main.py         /app/web_main.py

# ── Runtime environment ───────────────────────────────────────────────────────
# Tell TensorFlow to use the legacy Keras interface (required by deepface)
ENV TF_USE_LEGACY_KERAS=1

# Silence TensorFlow C++ log noise (0=all, 1=info+, 2=warn+, 3=errors only)
ENV TF_CPP_MIN_LOG_LEVEL=2

# PyTorch Hub model cache — ResNet-50 for Re-ID is downloaded here
ENV TORCH_HOME=/app/torch_hub_cache

# DeepFace ArcFace model weights cache
ENV DEEPFACE_HOME=/app/deepface_weights

# YOLO model search path — set so YOLO("yolov8n.pt") resolves to the
# mounted volume at /app/yolo-weights/ rather than downloading on each start.
# The entrypoint.sh symlinks /app/yolo-weights/*.pt into /app/ so the
# filename-only references in DetectionSystem.py continue to work.
ENV YOLO_CONFIG_DIR=/app/yolo-weights

# ── Health check ─────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Expose port ───────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Entry point ───────────────────────────────────────────────────────────────
COPY containerized/services/ai-backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
