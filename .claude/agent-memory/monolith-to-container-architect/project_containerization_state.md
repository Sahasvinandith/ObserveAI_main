---
name: ObserveAI containerization state
description: Files created, validation results, and remaining work as of 2026-04-03
type: project
---

## Status: Phase 4 Complete — Dockerfiles + Full K8s Microservices Manifests

## Files Created

### Modified source files (project root)
- `web/server.py` — Added `/health` endpoint (non-breaking)
- `.dockerignore` — Excludes .pt files, node_modules, pycache from build context

### containerized/ directory (new, never touches original code)
```
containerized/
  docker-compose.yml              ✓ passes `docker compose config` (exit 0)
  README.md                       ✓
  STREAMS_SCHEMA.md               ✓
  services/
    ai-backend/
      Dockerfile                  ✓ CUDA 12.4.1 + Ubuntu 22.04 base
      requirements.txt            ✓
      entrypoint.sh               ✓
      .dockerignore               ✓
    web-frontend/
      Dockerfile                  ✓
      nginx.conf                  ✓
    shared/
      redis_client.py             ✓
      image_codec.py              ✓
      stream_utils.py             ✓
    cam-ingest/
      Dockerfile                  ✓ python:3.12-slim + ffmpeg/V4L2
      main.py                     ✓
      requirements.txt            ✓
    person-yolo-worker/
      Dockerfile                  ✓ nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
      main.py                     ✓
      requirements.txt            ✓
    deepsort-tracker/
      Dockerfile                  ✓ python:3.12-slim
      main.py                     ✓
      requirements.txt            ✓
    face-yolo-worker/
      Dockerfile                  ✓ nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
      main.py                     ✓
      requirements.txt            ✓
    reid-feature-worker/
      Dockerfile                  ✓ nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
      main.py                     ✓
      requirements.txt            ✓
    face-recog-worker/
      Dockerfile                  ✓ python:3.12-slim + build-essential
      main.py                     ✓
      requirements.txt            ✓
    face-db-writer/
      Dockerfile                  ✓ python:3.12-slim
      main.py                     ✓
      requirements.txt            ✓
    action-pose-worker/
      Dockerfile                  ✓ nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
      main.py                     ✓
      requirements.txt            ✓
    global-tracker/
      Dockerfile                  ✓ python:3.12-slim + FastAPI/uvicorn
      main.py                     ✓
      requirements.txt            ✓
  k8s/
    namespace.yaml                ✓ YAML valid
    configmap.yaml                ✓ YAML valid
    persistent-volumes.yaml       ✓ YAML valid (8 PVCs)
    ai-backend-deployment.yaml    ✓ YAML valid
    ai-backend-service.yaml       ✓ YAML valid
    kustomization.yaml            ✓ Updated to include microservices/ subdir
    microservices/
      redis-deployment.yaml       ✓ ConfigMap + PVC + Deployment + Service
      cam-ingest-deployment.yaml  ✓ 1 replica, Recreate, no GPU
      person-yolo-worker-deployment.yaml  ✓ GPU, KEDA-scalable
      deepsort-tracker-deployment.yaml    ✓ 1 replica, Recreate, no GPU
      face-yolo-worker-deployment.yaml    ✓ GPU, KEDA-scalable
      reid-feature-worker-deployment.yaml ✓ GPU, KEDA-scalable
      face-recog-worker-deployment.yaml   ✓ CPU-heavy, KEDA-scalable
      face-db-writer-deployment.yaml      ✓ CPU, KEDA-scalable (max 3)
      action-pose-worker-deployment.yaml  ✓ GPU, KEDA-scalable
      global-tracker-deployment.yaml      ✓ Recreate singleton + ClusterIP Service
      keda-scaledobjects.yaml     ✓ 6 KEDA ScaledObjects, all YAML valid
      persistent-volumes.yaml     ✓ 5 PVCs (yolo-weights, torch-hub, deepface, faces-db, actions-db)
      kustomization.yaml          ✓ YAML valid
  volumes/
    README.md                     ✓
```

## Validation Results
- `docker compose config`: exit 0 (clean) — validated in containerized/ dir
- K8s YAML: all 13 microservices manifests parse cleanly (yaml.safe_load_all)
- Root kustomization.yaml: YAML valid, includes microservices/ as sub-path
- `kubectl` not installed on dev machine — use `kubectl apply --dry-run=client` on cluster

## Phase 4 Architectural Decisions (Dockerfiles + K8s)

### Base image choices
| Service | Base image | Reason |
|---------|-----------|--------|
| cam-ingest | python:3.12-slim | I/O-bound, needs ffmpeg for RTSP |
| person-yolo-worker | nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 | YOLOv8 GPU inference |
| deepsort-tracker | python:3.12-slim | CPU-only; in-process Kalman filter |
| face-yolo-worker | nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 | YOLOv11n GPU inference |
| reid-feature-worker | nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 | ResNet-50 GPU inference |
| face-recog-worker | python:3.12-slim | TF/ArcFace — CPU sufficient at scale |
| face-db-writer | python:3.12-slim | Disk I/O only |
| action-pose-worker | nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 | YOLOv8n-pose GPU inference |
| global-tracker | python:3.12-slim | In-process EMA; FastAPI HTTP server |

### GPU base image Python bootstrap
CUDA Ubuntu 22.04 images ship Python 3.10. All GPU Dockerfiles use the deadsnakes PPA
to install Python 3.12 (identical pattern to the existing ai-backend Dockerfile).

### docker-compose.yml changes
- Added `redis` service (redis:7-alpine, named volume redis-data, AOF config)
- Added 9 new microservices under `profiles: [microservices]`
- Existing ai-backend and web-frontend services unchanged
- Activate with: `docker compose --profile microservices up -d`
- Camera-specific services (cam-ingest-front-door, deepsort-tracker-front-door) demonstrate
  the pattern; operators duplicate for each physical camera

### K8s KEDA ScaledObject strategy
All scalable workers use KEDA redis-streams trigger on pendingEntriesCount:
- person-yolo-worker: shared_raw_frames / cg::person_yolo, threshold 30
- face-yolo-worker: person_tracks::Front_Door / cg::face_yolo, threshold 20
- reid-feature-worker: person_tracks::Front_Door / cg::reid_extract, threshold 20
- face-recog-worker: face_crops / cg::face_recog, threshold 20
- face-db-writer: identity_results / cg::face_db_writer, threshold 30
- action-pose-worker: person_tracks::Front_Door / cg::action_detect, threshold 20

### Singleton services use Recreate strategy
deepsort-tracker and global-tracker: Recreate strategy prevents two pods from
claiming the same ordered stream or in-process state simultaneously.

### PVC layout (microservices)
- yolo-weights-pvc (2 Gi, RWO) — shared across GPU workers, read-only mounts
- torch-hub-cache-pvc (2 Gi, RWO) — ResNet-50 weights for reid-feature-worker
- deepface-weights-pvc (2 Gi, RWO) — ArcFace weights for face-recog-worker
- faces-db-pvc (10 Gi, RWO) — shared between face-db-writer (rw) and face-recog-worker (ro)
- actions-db-pvc (1 Gi, RWO) — action JSON files, read-only for action-pose-worker
Note: faces-db requires ReadWriteMany if face-db-writer and face-recog-worker scale to
multiple replicas on different nodes. Use NFS/CephFS or co-locate via pod affinity.

## Phase 5 Complete — End-to-End Verification (2026-04-03)

Full verification report at: `containerized/VERIFICATION_REPORT.md`

### Bugs Fixed in Phase 5

1. **deepsort-tracker/main.py — buffer overflow eviction (Critical)**
   - `heapq.heappop()` was evicting the smallest frame_index (most needed frame)
   - Fixed to evict the largest frame_index (furthest future frame) via index-based max removal
   - Method: find max_idx, swap with last element, heap pop, sift to restore invariant

2. **face-recog-worker/main.py — ARCFACE_THRESHOLD mismatch**
   - Was 0.5; schema and original code specify 0.6
   - Fixed to 0.6 (values in [0.5, 0.6) would have been rejected as Unknown)

3. **global-tracker/main.py — unused `import math`**
   - Removed

4. **deepsort-tracker/requirements.txt — missing explicit numpy**
   - Added `numpy>=1.24.0`

5. **person-yolo-worker/requirements.txt, face-yolo-worker/requirements.txt**
   - Added `numpy>=1.24.0` explicitly (was transitive only via ultralytics)

### Verification Summary (all 10 checks)
- Python syntax: PASS (all 12 files)
- Import consistency: PASS (no PyQt6, no DataModel imports, all shared/ symbols valid)
- Stream name consistency: PASS (exact match throughout)
- Message field handoffs: PASS (all 3 critical handoffs verified)
- Reorder buffer: FIXED (overflow eviction bug corrected)
- Consumer group creation: PASS (all services call ensure_consumer_group before read loop)
- Dockerfile COPY paths: PASS (no service imports DataModel/; all use shared/)
- K8s YAML: PASS (namespaces, GPU requests+tolerations, KEDA references all correct)
- docker-compose deps: PASS (all services have depends_on: redis with service_healthy)
- End-to-end trace: PASS (full request_id flow from cam-ingest → identity results verified)

### Known Limitations (documented in VERIFICATION_REPORT.md)
- L1: global-tracker has no restore-from-Redis on startup (state lost on pod crash)
- L2: face-recog-worker EmbeddingCache per-replica may have brief stale window after save
- L3: deepsort-tracker FrameCache eviction is non-deterministic (uses dict ordering)
- L4: reid-feature-worker model loading is at module scope (slows startup)
- L5: KEDA ScaledObjects only target Front_Door camera; multi-camera needs duplicate triggers
- L6: deepsort-tracker decodes all 4-camera frames even though it only needs one camera's frames

## Remaining Work (Future Conversations)
1. Build Docker images and smoke-test each service in isolation
2. Verify GPU passthrough works on the target host (nvidia-smi in container)
3. Populate yolo-weights PVC with .pt files before deploying GPU workers
4. Fix L1: add restore_from_redis() to global-tracker main() startup
5. Fix L4: move reid-feature-worker model loading into main() function
6. Extend KEDA ScaledObjects for additional cameras (L5)
