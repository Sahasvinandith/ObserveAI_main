# ObserveAI — Containerized Deployment

This directory contains all Docker and Kubernetes artifacts for running ObserveAI
as a containerized application. The original monolithic source code in the project
root is not modified (except for the addition of the `/health` endpoint to
`web/server.py`, which is a non-breaking addition).

---

## Architecture

### Why one backend service?

The core AI pipeline is composed of components that share in-process memory:

```
CameraWorkerThread ──(queue)──> DetectionSystem
                                    │
                                    ├─ YOLO inference (yolov8n.pt, yolov11n-face.pt)
                                    ├─ DeepSORT tracker (per-camera)
                                    ├─ Re-ID (ResNet-50, EMA feature blending)
                                    ├─ DeepFace (ArcFace recognition)
                                    └─ GlobalPersonTracker (singleton, thread-locked)
```

These components communicate via `queue.Queue`, `threading.Lock`, and direct
method calls. Splitting them across containers would require replacing all
in-process communication with a message broker (e.g., Redis Streams), which
would be a major rewrite and introduce network latency between every frame.

**Decision**: all AI components run in the single `ai-backend` service.

### Service map

```
┌─────────────────────────────────────────────────────┐
│  ai-backend (port 8000)                             │
│                                                     │
│  FastAPI (web/server.py)                            │
│    ├── REST API  /api/*                             │
│    ├── WebSocket /ws/events                         │
│    ├── MJPEG streams /api/cameras/{name}/stream     │
│    └── React SPA at / (served from web/frontend/dist│
│                                                     │
│  CameraManager (web/camera_manager.py)              │
│    ├── CameraWorkerThread × N  (one per camera)     │
│    └── Ai_System_thread × N    (one per camera)     │
│          └── DetectionSystem                        │
│                ├── YOLO person + face + pose        │
│                ├── DeepSORT tracker                 │
│                ├── Re-ID (ResNet-50)                │
│                └── DeepFace (ArcFace)               │
│                                                     │
│  GlobalPersonTracker (singleton, thread-safe)       │
│  EmbeddingCache (singleton, thread-safe)            │
│  SettingsManager → /app/settings.json (volume)     │
│  LogManager → /app/logs.db (volume)                │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  web-frontend (port 80) — OPTIONAL                  │
│                                                     │
│  Nginx serving pre-built React static assets        │
│  Proxies /api/* and /ws/* to ai-backend             │
│                                                     │
│  Use with: docker compose --profile frontend up     │
└─────────────────────────────────────────────────────┘
```

The `web-frontend` (Nginx) service is optional. `ai-backend` already serves the
React SPA at its root URL, so you only need Nginx if you want to decouple static
asset serving from the Python process.

---

## Quick Start (Docker Compose)

### Prerequisites

- Docker >= 24.0
- Docker Compose v2 (included in Docker Desktop / `docker compose` plugin)
- NVIDIA Container Toolkit (for GPU) — optional, falls back to CPU

### 1. Build and start

```bash
cd /path/to/ObserveAI_main

# Build the ai-backend image
docker compose -f containerized/docker-compose.yml build

# Start (detached)
docker compose -f containerized/docker-compose.yml up -d

# Open the web UI
open http://localhost:8000
```

### 2. Populate model weights

The YOLO `.pt` files must be in the `yolo-weights` volume. The easiest way is
to copy them from the project root on first run:

```bash
docker run --rm \
  -v "$(pwd)":/src:ro \
  -v observeai_yolo-weights:/dst \
  alpine sh -c "cp /src/yolov8n.pt /src/yolov11n-face.pt /src/yolov8n-pose.pt /dst/"
```

Alternatively, if the weights are missing the container will print a warning
and YOLO will auto-download them on first inference (requires internet access).

### 3. Migrate existing data (optional)

```bash
# Migrate face database
docker run --rm \
  -v "$(pwd)/Faces_db":/src:ro \
  -v observeai_faces-db:/dst \
  alpine sh -c "cp -r /src/. /dst/"

# Migrate actions
docker run --rm \
  -v "$(pwd)/Actions_db":/src:ro \
  -v observeai_actions-db:/dst \
  alpine sh -c "cp -r /src/. /dst/"

# Migrate settings
docker run --rm \
  -v "$(pwd)/settings.json":/src/settings.json:ro \
  -v observeai_settings:/dst \
  alpine sh -c "cp /src/settings.json /dst/"
```

### 4. USB cameras

USB cameras require device access inside the container. Uncomment the relevant
lines in `docker-compose.yml`:

```yaml
devices:
  - /dev/video0:/dev/video0
```

For RTSP IP cameras, no device mount is needed — just add the camera via the
web UI using its RTSP URL (e.g., `rtsp://192.168.1.100:554/stream`).

### 5. CPU-only (no GPU)

Remove or comment out the `deploy.resources.reservations.devices` block in
`docker-compose.yml`. The PyTorch / YOLO inference will still work on CPU,
but at lower throughput (typically 2–5 FPS per camera vs. 15–30 FPS with GPU).

---

## Directory Structure

```
containerized/
  services/
    ai-backend/
      Dockerfile          — Multi-stage build: CUDA base + Python deps + source
      requirements.txt    — Python dependencies (pinned major versions)
      entrypoint.sh       — Startup script: mkdir, symlinks, uvicorn launch
      .dockerignore       — Excludes .pt files, node_modules, pycache, etc.
      src/README.md       — Note: source is copied from project root at build time
    web-frontend/
      Dockerfile          — Two-stage: Node.js build → Nginx runtime
      nginx.conf          — MJPEG-aware proxy config + SPA fallback
  docker-compose.yml      — Orchestrates ai-backend (+ optional web-frontend)
  k8s/
    namespace.yaml
    configmap.yaml        — Default settings.json
    persistent-volumes.yaml
    ai-backend-deployment.yaml
    ai-backend-service.yaml
    kustomization.yaml
  volumes/
    README.md             — Volume mount reference + data migration guide
  README.md               — This file
```

---

## Kubernetes Deployment

```bash
# Apply all resources
kubectl apply -k containerized/k8s/

# Check pod status
kubectl get pods -n observeai

# View logs
kubectl logs -n observeai deployment/ai-backend -f

# Port-forward for local access
kubectl port-forward -n observeai svc/ai-backend 8000:8000
```

### Populating PVCs before first pod start

Use an init Job or a temporary pod to copy data into the PVCs:

```bash
# Example: seed yolo-weights PVC
kubectl run seed-weights --rm -i --tty \
  --namespace observeai \
  --image=alpine \
  --overrides='{"spec":{"volumes":[{"name":"v","persistentVolumeClaim":{"claimName":"yolo-weights-pvc"}}],"containers":[{"name":"seed","image":"alpine","command":["sh"],"volumeMounts":[{"name":"v","mountPath":"/dst"}]}]}}' \
  -- sh
# (inside the container) wget -O /dst/yolov8n.pt https://...
```

---

## Architectural Decisions

| Decision | Rationale |
|---|---|
| Single `ai-backend` service | All AI components share in-process Python memory via `queue.Queue` and `threading.Lock`. Network-splitting requires a Redis rewrite — deferred. |
| FastAPI serves React SPA | `web/server.py` already mounts `web/frontend/dist` at `/`. No separate Nginx needed for the default deployment. |
| Nginx `web-frontend` is opt-in | Useful for high-traffic deployments or when a CDN sits in front, but adds operational complexity unnecessarily for most use cases. |
| CUDA base image | `torch.cuda.is_available()` is checked at runtime; the same image runs on CPU if no GPU is present. |
| workers=1 (uvicorn) | GlobalPersonTracker, EmbeddingCache, and per-camera queues are in-process singletons. Multiple workers would each have an isolated copy, breaking cross-camera tracking. |
| Volumes for all data | Model weights, face DB, logs, and settings are externalized so the container image is stateless and can be rebuilt without data loss. |
| settings.json as file volume | SettingsManager resolves `settings.json` relative to CWD (`/app`). Mounting as a volume file allows live edits without rebuilding the image. |

---

## Known Limitations

1. **USB cameras in Kubernetes**: Not supported without a device plugin or
   DaemonSet. Use RTSP streams from IP cameras in k8s environments.

2. **Horizontal scaling**: Replica count must remain 1. The GlobalPersonTracker
   singleton is not distributed. Future work: externalize tracker state to Redis.

3. **PyQt6 desktop app**: The containerized deployment uses the web UI
   (`web/server.py`) only. The PyQt6 `main/MainWindow.py` is not containerized
   as it requires a display server and Qt libraries.

4. **First-start model download**: DeepFace downloads ArcFace weights (~300 MB)
   and PyTorch Hub downloads ResNet-50 (~100 MB) on first run. The `torch-hub-cache`
   and `deepface-weights` volumes persist these downloads across restarts.

5. **SQLite concurrency**: `logs.db` uses SQLite with a 30-second timeout.
   This is sufficient for single-replica deployments but would need PostgreSQL
   migration for multi-replica setups.
