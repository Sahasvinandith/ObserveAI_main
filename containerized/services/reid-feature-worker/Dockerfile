# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI — reid-feature-worker service
#
# Reads confirmed person tracks from person_tracks::{CAMERA_NAME} (consumer
# group cg::reid_extract), extracts a 2048-dim L2-normalized Re-ID feature
# vector and a 512-element HSV color histogram using ResNet-50.
# Publishes results to reid_features.
#
# GPU workload: requires NVIDIA CUDA runtime.
# Stateless: horizontally scalable (KEDA ScaledObject on stream lag).
# Build context: project root (/)
# ─────────────────────────────────────────────────────────────────────────────

FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

LABEL maintainer="ObserveAI"
LABEL description="Re-ID feature extraction worker — ResNet-50 on person crops"

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
COPY containerized/services/reid-feature-worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# ── Shared utilities ─────────────────────────────────────────────────────────
COPY containerized/services/shared/ /app/shared/

# ── Service source ────────────────────────────────────────────────────────────
COPY containerized/services/reid-feature-worker/main.py /app/main.py

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV REDIS_URL=redis://redis:6379
ENV CAMERA_NAME=
ENV POD_NAME=reid-feature-worker-0
ENV LOG_LEVEL=info
# PyTorch Hub cache — ResNet-50 weights are downloaded here on first run
ENV TORCH_HOME=/app/torch_hub_cache

# ── Health check ─────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import redis, os; r=redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

# ── Entry point ───────────────────────────────────────────────────────────────
CMD ["python", "main.py"]
