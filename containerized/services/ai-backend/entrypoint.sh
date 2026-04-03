#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# ObserveAI ai-backend entrypoint
#
# 1. Creates empty data directory scaffolding (volumes populate these)
# 2. Creates default settings.json if not present
# 3. Symlinks YOLO .pt model files from the mounted volume into /app/ so
#    YOLO("yolov8n.pt") resolves correctly (DetectionSystem uses bare filenames)
# 4. Reports GPU availability
# 5. Starts uvicorn
# ─────────────────────────────────────────────────────────────────────────────

set -e

WORKDIR="/app"

echo "[ENTRYPOINT] Starting ObserveAI ai-backend..."

# ── Ensure data directories exist ────────────────────────────────────────────
# These are normally populated by Docker volume mounts. Creating them here
# ensures a clean first-run even without pre-populated volumes.
mkdir -p "${WORKDIR}/Faces_db"
mkdir -p "${WORKDIR}/Actions_db"
mkdir -p "${WORKDIR}/maps"
mkdir -p "${WORKDIR}/detections"
mkdir -p "${WORKDIR}/torch_hub_cache"
mkdir -p "${WORKDIR}/deepface_weights"
mkdir -p "${WORKDIR}/yolo-weights"

# ── Create default settings.json if not present ──────────────────────────────
SETTINGS_FILE="${WORKDIR}/settings.json"
if [ ! -f "${SETTINGS_FILE}" ]; then
    echo "[ENTRYPOINT] Creating default settings.json..."
    cat > "${SETTINGS_FILE}" <<'SETTINGS'
{
    "feature_threshold": 0.5,
    "reid_weight": 0.4,
    "color_weight": 0.3,
    "spatial_weight": 0.3,
    "spatial_region_weight": 0.6,
    "spatial_depth_weight": 0.4,
    "ref_human_height_px": 250,
    "default_fov": 70,
    "dot_radius": 8,
    "min_quality_threshold": 50,
    "max_faces_per_user": 5,
    "identity_confirm_frames": 3,
    "identity_confidence_threshold": 0.6,
    "identity_change_margin": 0.15,
    "min_face_width": 70,
    "min_face_height": 90,
    "min_face_confidence": 0.5,
    "camera_actions": {}
}
SETTINGS
fi

# ── Symlink YOLO .pt weights into /app/ ──────────────────────────────────────
# DetectionSystem.py calls YOLO("yolov8n.pt") using bare filenames, which
# resolve relative to the working directory (/app). The model files live in
# the mounted volume at /app/yolo-weights/. We create symlinks in /app/ so
# the existing code works without modification.
#
# Expected volume contents:
#   /app/yolo-weights/yolov8n.pt
#   /app/yolo-weights/yolov11n-face.pt
#   /app/yolo-weights/yolov8n-pose.pt
#
# If the weights volume is empty (first run), YOLO will download the models
# automatically from the internet and they will be cached in YOLO_CONFIG_DIR.

YOLO_MODELS=("yolov8n.pt" "yolov11n-face.pt" "yolov8n-pose.pt")

for model in "${YOLO_MODELS[@]}"; do
    src="${WORKDIR}/yolo-weights/${model}"
    dst="${WORKDIR}/${model}"
    if [ -f "${src}" ] && [ ! -e "${dst}" ]; then
        ln -sf "${src}" "${dst}"
        echo "[ENTRYPOINT] Symlinked ${model} -> yolo-weights/${model}"
    elif [ -f "${dst}" ]; then
        echo "[ENTRYPOINT] ${model} already present at ${dst}"
    else
        echo "[ENTRYPOINT] WARNING: ${model} not found in yolo-weights volume — YOLO will download it on first inference."
    fi
done

# ── Report GPU availability ───────────────────────────────────────────────────
if command -v nvidia-smi &>/dev/null; then
    echo "[ENTRYPOINT] GPU detected:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
else
    echo "[ENTRYPOINT] No GPU detected — running on CPU. Performance will be degraded."
fi

echo "[ENTRYPOINT] Launching uvicorn on 0.0.0.0:8000..."

# ── Start FastAPI server ──────────────────────────────────────────────────────
# workers=1 is mandatory — all camera state is held in-process memory.
exec python -m uvicorn web.server:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info
