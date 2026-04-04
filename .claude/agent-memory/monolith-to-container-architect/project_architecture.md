---
name: ObserveAI container architecture decisions
description: Service boundaries, rationale, shared state solutions, and key constraints discovered during containerization
type: project
---

## Container Boundary Decision: Single ai-backend Service

All AI components run in one container (`ai-backend`) because they share in-process memory:
- `CameraWorkerThread` → `queue.Queue` → `DetectionSystem` → `GlobalPersonTracker`
- `EmbeddingCache` is a process-level singleton accessed by all camera threads
- `GlobalPersonTracker` is a singleton with threading.Lock protecting cross-camera state
- Splitting would require Redis Streams or similar message broker — deferred

**Why:** Network latency between containers would break real-time frame processing.
**How to apply:** Never split these components across services without first externalizing
GlobalPersonTracker and EmbeddingCache state to Redis.

## Key Architectural Insight: web/ Directory Already Replaces PyQt6

The `web/` directory (added in the latest commit `a080c1d`) provides:
- `web/server.py` — FastAPI that replaces MainWindow, serves REST + WebSocket + MJPEG
- `web/camera_manager.py` — CameraWorkerThread (pure Python, no Qt signals)
- `web/frontend/` — React + Vite + Zustand frontend

`web_main.py` is the entry point. `uvicorn web.server:app --workers 1` is the container command.
Workers MUST stay at 1 — all state is in-process.

## YOLO Model File Resolution

`DetectionSystem.py` calls `YOLO("yolov8n.pt")` using bare filenames that resolve
relative to the working directory. The entrypoint.sh symlinks:
  `/app/yolo-weights/{model}.pt` → `/app/{model}.pt`
so YOLO finds them without code changes.

Models: yolov8n.pt, yolov11n-face.pt, yolov8n-pose.pt

## settings.json Path

`SettingsManager` resolves `settings.json` relative to CWD (hardcoded as `"settings.json"`).
In the container CWD is `/app`, so the volume mounts to `/app/settings.json`.

## /health Endpoint

Added to `web/server.py` (non-breaking) for Docker/k8s health probes.
Location in file: immediately before `/api/status`.

## GPU

CUDA 12.4.1 + Ubuntu 22.04 base image. Falls back to CPU automatically.
TORCH_HOME=/app/torch_hub_cache, DEEPFACE_HOME=/app/deepface_weights (both volumed).

## Build Context

Build context is the project root for both services. Dockerfile paths:
- ai-backend: `containerized/services/ai-backend/Dockerfile`
- web-frontend: `containerized/services/web-frontend/Dockerfile`

## web-frontend Service

Optional (profile: frontend). Nginx proxying /api/* and /ws/* to ai-backend.
Required for MJPEG streaming: proxy_buffering off, proxy_read_timeout 3600s.
FastAPI already serves the React SPA so this service is only needed for
static asset CDN decoupling.
