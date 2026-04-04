# ObserveAI — Monolith to Container Migration

## Overview

This document describes the full containerization of the ObserveAI surveillance system, migrating it from a PyQt6 desktop monolith to a Docker-based architecture deployable on any Linux host (with or without a GPU) or on Kubernetes.

The original monolith is permanently preserved on the `main` branch and tagged as `v1.0-monolith`. All containerization work lives on the `feature/containerize` branch.

---

## Original Architecture (Monolith)

ObserveAI was a PyQt6 desktop application — a single Python process handling everything:

| Responsibility | Component |
|---|---|
| GUI rendering | `main/MainWindow.py` (PyQt6) |
| Camera frame capture | `components/Camera_worker.py` |
| YOLO person/face/pose detection | `DataModel/DetectionSystem.py` |
| Multi-object tracking (DeepSORT) | `DataModel/DetectionSystem.py` |
| Cross-camera identity linking | `DataModel/GlobalPersonTracker.py` |
| Face recognition (DeepFace/ArcFace) | `DataModel/DetectionSystem.py` |
| Re-ID feature blending (EMA) | `DataModel/GlobalPersonTracker.py` |
| Pose-based action recognition | `DataModel/ActionManager.py` |
| Settings persistence | `DataModel/SettingsManager.py` |

All components communicated via `queue.Queue`, `threading.Lock`, and direct method calls — all within one OS process.

---

## Key Discovery That Shaped Everything

The commit `a080c1d` (the last commit before containerization began) already added:
- `web/server.py` — a **FastAPI server** replacing `MainWindow.py` as the central controller
- `web/camera_manager.py` — a `CameraWorkerThread` that works headlessly, without any display server

This meant the entire AI pipeline already ran without PyQt6. **Zero refactoring of AI logic was required.**

---

## Architecture Decision: One Service, Not Many

### Why all AI stays in one container

`DetectionSystem`, `GlobalPersonTracker`, `EmbeddingCache`, and `CameraWorkerThread` all communicate through:
- `queue.Queue` — in-process, no network
- `threading.Lock` — in-process, no network
- Direct Python callbacks — in-process, no network

Splitting these into separate containers would require replacing every queue with **Redis Streams**, every lock with a **distributed lock service**, and every callback with an **HTTP or gRPC call**. That is a complete rewrite of the tracking system, not a containerization.

**Decision: all AI components run in a single `ai-backend` container.**

The web frontend is optionally served by a separate Nginx container, but FastAPI already serves the built React app from `/` — so Nginx is entirely optional.

---

## Container Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Host / k8s Node                  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ai-backend  :8000                      │   │
│  │                                                     │   │
│  │   FastAPI (uvicorn, 1 worker)                       │   │
│  │     ├─ CameraWorkerThread  ──► DetectionSystem      │   │
│  │     ├─ GlobalPersonTracker (in-process registry)    │   │
│  │     ├─ EmbeddingCache / DeepFace                    │   │
│  │     ├─ ActionManager                                │   │
│  │     └─ SettingsManager                              │   │
│  │                                                     │   │
│  │   YOLO inference ──► NVIDIA GPU (optional)          │   │
│  └────────────────────────────┬────────────────────────┘   │
│                               │                             │
│  ┌────────────────────────────▼────────────────────────┐   │
│  │          web-frontend  :80  (optional)              │   │
│  │                                                     │   │
│  │   Nginx                                             │   │
│  │     ├─ Serves built React SPA (/assets/*)           │   │
│  │     ├─ Proxies /api/* → ai-backend:8000             │   │
│  │     └─ Proxies /ws/*  → ai-backend:8000 (WS)       │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  Named Volumes: faces-db  actions-db  maps  settings        │
│                 logs  detections  yolo-weights               │
│                 torch-hub-cache  deepface-weights            │
└─────────────────────────────────────────────────────────────┘
```

---

## Files Created

### Repository root

| File | Purpose |
|---|---|
| `.dockerignore` | Excludes model weights (`*.pt`), `Faces_db/`, `Actions_db/`, `node_modules/`, debug images, and dev-only files from every Docker build context |

### `containerized/`

```
containerized/
├── docker-compose.yml
├── services/
│   ├── ai-backend/
│   │   ├── Dockerfile
│   │   ├── entrypoint.sh
│   │   └── requirements.txt
│   └── web-frontend/
│       ├── Dockerfile
│       └── nginx.conf
└── k8s/
    ├── namespace.yaml
    ├── persistent-volumes.yaml
    ├── configmap.yaml
    ├── ai-backend-deployment.yaml
    ├── ai-backend-service.yaml
    └── kustomization.yaml
```

### `web/server.py`

One line added: a `/health` endpoint returning `{"status": "ok"}` — used by Docker and Kubernetes health probes.

---

## File-by-File Breakdown

### `containerized/docker-compose.yml`

The primary deployment artifact. Defines two services:

**`ai-backend`** (mandatory)
- Builds from `containerized/services/ai-backend/Dockerfile` with the project root as the build context
- NVIDIA GPU passthrough via `deploy.resources.reservations.devices` (remove this block for CPU-only)
- Exposes port `8000`
- 9 named volumes for all persistent state
- Health check hits `/health` with a 90-second start period to allow YOLO and DeepFace model loading
- Memory limit: 8 GB | CPU limit: 4 cores
- `UVICORN_WORKERS=1` — mandatory, because all camera state is in-process

**`web-frontend`** (optional, `--profile frontend`)
- Only needed if you want Nginx to serve static assets separately from FastAPI
- Waits for `ai-backend` to pass its health check before starting
- Memory limit: 128 MB | CPU limit: 0.5 cores

**9 named volumes:**

| Volume | Mounted at | Purpose |
|---|---|---|
| `faces-db` | `/app/Faces_db` | DeepFace per-person face crops |
| `actions-db` | `/app/Actions_db` | JSON pose-action definitions |
| `maps` | `/app/maps` | Camera calibration / homography data |
| `settings` | `/app/settings.json` | Runtime config (thresholds, weights) |
| `logs` | `/app/logs.db` | SQLite activity log |
| `detections` | `/app/detections` | Evidence frames saved on detection events |
| `yolo-weights` | `/app/yolo-weights` | `yolov8n.pt`, `yolov11n-face.pt`, `yolov8n-pose.pt` |
| `torch-hub-cache` | `/app/torch_hub_cache` | PyTorch Hub cache (ResNet-50 for Re-ID) |
| `deepface-weights` | `/app/deepface_weights` | ArcFace model weights |

---

### `containerized/services/ai-backend/Dockerfile`

Base image: `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`

For CPU-only deployments, swap the `FROM` line to `python:3.12-slim`.

Build steps:
1. Install system packages: Python 3.12 (via deadsnakes PPA), OpenCV runtime libs (`libglib2.0-0`, `libgl1-mesa-glx`, etc.), `ffmpeg` for RTSP/H.264 decoding, V4L2 utils for USB cameras, build tools
2. Install pip for Python 3.12 via `get-pip.py`
3. Install Python dependencies from `requirements.txt` (cached layer)
4. Copy source: `DataModel/`, `web/`, `web_main.py`
5. Set environment variables for TensorFlow, PyTorch Hub, DeepFace, and YOLO model paths
6. Install and configure `entrypoint.sh`

Key environment variables set in the image:

| Variable | Value | Reason |
|---|---|---|
| `TF_USE_LEGACY_KERAS` | `1` | DeepFace requires Keras 2 API; TF 2.16+ uses Keras 3 by default |
| `TF_CPP_MIN_LOG_LEVEL` | `2` | Suppress TensorFlow C++ log noise |
| `TORCH_HOME` | `/app/torch_hub_cache` | Pins PyTorch Hub cache to the named volume |
| `DEEPFACE_HOME` | `/app/deepface_weights` | Pins ArcFace weights to the named volume |
| `YOLO_CONFIG_DIR` | `/app/yolo-weights` | Tells YOLO where to cache downloaded weights |

---

### `containerized/services/ai-backend/entrypoint.sh`

Runs before `uvicorn` starts. Five responsibilities:

1. **Scaffold data directories** — creates `Faces_db/`, `Actions_db/`, `maps/`, `detections/`, `torch_hub_cache/`, `deepface_weights/`, `yolo-weights/` if they don't exist. Ensures a clean first-run even with empty volumes.

2. **Create default `settings.json`** — if the settings volume is empty on first run, writes sensible defaults (all thresholds matching the original PyQt6 app).

3. **Symlink YOLO weights** — `DetectionSystem.py` calls `YOLO("yolov8n.pt")` using bare filenames, which resolve relative to the working directory (`/app`). The weights live in `/app/yolo-weights/`. The entrypoint creates symlinks `yolov8n.pt → yolo-weights/yolov8n.pt` etc. in `/app/` so the existing code works without any modification. If weights are missing, YOLO downloads them automatically and caches them in the volume.

4. **Report GPU status** — runs `nvidia-smi` and prints GPU name/VRAM to the container log. Falls back gracefully if no GPU is present.

5. **Start uvicorn** — `python -m uvicorn web.server:app --host 0.0.0.0 --port 8000 --workers 1`. Workers is fixed at 1; using more would create multiple independent `GlobalPersonTracker` instances with no shared state.

---

### `containerized/services/ai-backend/requirements.txt`

All Python dependencies with pinned major versions for reproducible builds:

| Package | Purpose |
|---|---|
| `fastapi`, `uvicorn[standard]` | Web framework and ASGI server |
| `python-multipart` | File upload support (face enrollment) |
| `opencv-contrib-python-headless` | Computer vision — headless build (no GTK/Qt) |
| `torch`, `torchvision` | PyTorch with CUDA 12.4 wheels |
| `ultralytics` | YOLOv8/v11 detection, tracking, pose |
| `deep-sort-realtime` | DeepSORT multi-object tracker |
| `deepface` | Face recognition (ArcFace backend) |
| `tensorflow`, `tf_keras` | Required by DeepFace |
| `psutil`, `numpy` | System monitoring and array ops |

`opencv-contrib-python-headless` replaces `opencv-contrib-python` from the original install — the headless variant excludes GTK/Qt GUI bindings that have no meaning inside a container.

---

### `containerized/services/web-frontend/Dockerfile`

Two-stage build:

**Stage 1 — Node 20:** Installs npm dependencies (`npm ci`) then runs `npm run build` (Vite), producing `dist/`.

**Stage 2 — Nginx 1.27 Alpine:** Copies `dist/` into `/usr/share/nginx/html`. Minimal final image (~25 MB).

---

### `containerized/services/web-frontend/nginx.conf`

Configures Nginx as a reverse proxy and SPA server:

- `/assets/*` — served directly with 1-year cache headers (Vite hashes filenames)
- `/api/*` — proxied to `ai-backend:8000` with **buffering disabled** (`proxy_buffering off`, `proxy_read_timeout 3600s`) to keep MJPEG camera streams alive without buffering
- `/ws/*` — proxied with WebSocket upgrade headers (`Upgrade`, `Connection: upgrade`)
- `/` — SPA fallback (`try_files $uri $uri/ /index.html`) for React Router client-side routing
- Gzip compression enabled for JS, CSS, JSON, SVG

---

### `containerized/k8s/` — Kubernetes Manifests

Six YAML files for deploying on a Kubernetes cluster:

| File | Contents |
|---|---|
| `namespace.yaml` | `observeai` namespace |
| `persistent-volumes.yaml` | 9 PersistentVolumeClaims matching the 9 Docker volumes |
| `configmap.yaml` | `settings.json` stored as a ConfigMap |
| `ai-backend-deployment.yaml` | Deployment (replicas: 1), GPU resource request, volume mounts, liveness + readiness probes |
| `ai-backend-service.yaml` | ClusterIP service exposing port 8000 |
| `kustomization.yaml` | Kustomize entry point referencing all the above |

**Why `replicas: 1` is locked:** Horizontal Pod Autoscaling cannot be applied here. `GlobalPersonTracker` is an in-process singleton. Multiple replicas would each maintain independent tracking state and produce inconsistent identity assignments for the same physical person. Scaling requires a Redis-backed rewrite of the tracker — out of scope for this migration.

**GPU in Kubernetes:** The pod requests `nvidia.com/gpu: 1`. Requires the NVIDIA device plugin:
```bash
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.5/nvidia-device-plugin.yml
```
Node affinity is configured to prefer nodes labelled `nvidia.com/gpu.present=true`.

---

## What Was Not Changed

- All files in `DataModel/`, `components/`, `main/`, `Actions_db/`, `Faces_db/`, `maps/` — untouched
- `web/server.py` — one `/health` endpoint added, nothing else changed
- `settings.json` schema — identical to the original PyQt6 app; the entrypoint uses the same default values

---

## Deployment

### Docker Compose (recommended for single-host)

```bash
# Build and start (GPU)
cd ObserveAI_main
docker compose -f containerized/docker-compose.yml up --build -d

# CPU-only: edit docker-compose.yml and remove the `deploy` block first

# With optional Nginx frontend on port 80
docker compose -f containerized/docker-compose.yml --profile frontend up --build -d

# View logs
docker compose -f containerized/docker-compose.yml logs -f ai-backend

# Open the dashboard
# http://localhost:8000
```

### USB Cameras

Uncomment the `devices` and `privileged` sections in `docker-compose.yml`:
```yaml
devices:
  - /dev/video0:/dev/video0
privileged: true
```

### RTSP Cameras

No extra configuration — RTSP streams connect over the network. No device mounts needed.

### Kubernetes

```bash
kubectl apply -k containerized/k8s/
kubectl -n observeai rollout status deployment/ai-backend
kubectl -n observeai port-forward svc/ai-backend 8000:8000
```

---

## GPU vs CPU Performance Note

YOLO inference, Re-ID feature extraction, and DeepFace all benefit significantly from a GPU. Without one, expect:
- Reduced frame rate per camera
- Higher CPU usage
- Slower face recognition

The container runs on CPU automatically if no GPU is present — no code changes needed.
