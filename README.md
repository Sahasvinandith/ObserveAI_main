# ObserveAI

**Real-time multi-camera surveillance powered by YOLO · DeepSORT · DeepFace · Re-ID**

ObserveAI is a production-grade computer vision surveillance system that detects, tracks, and recognises people across multiple camera feeds in real time. It ships in three deployment modes — a native desktop GUI, a browser-based web interface, and a fully containerised microservices architecture designed for horizontal scaling on Kubernetes.

<div align="center">
  <video src="https://github.com/user-attachments/assets/2ad8a3e0-196f-4696-a2cb-0af0d1091232"
         width="100%"
         controls
         autoplay
         loop
         muted>
    Your browser does not support the video tag.
  </video>
</div>

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [AI Pipeline](#ai-pipeline)
- [Deployment Modes](#deployment-modes)
  - [Mode 1 — Desktop GUI (PyQt6)](#mode-1--desktop-gui-pyqt6)
  - [Mode 2 — Web UI (FastAPI + React)](#mode-2--web-ui-fastapi--react)
  - [Mode 3 — Containerised Microservices](#mode-3--containerised-microservices)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Version History](#version-history)

---

## Features

| Capability | Detail |
|---|---|
| **Person detection** | YOLOv8n — real-time bounding boxes on every camera frame |
| **Multi-object tracking** | DeepSORT — stable local track IDs per camera with Kalman filter prediction |
| **Cross-camera re-identification** | ResNet-50 Re-ID — EMA-blended 2048-d feature vectors link the same person across cameras |
| **Face detection** | YOLOv11n-face — detects faces within person crops, quality-gated |
| **Face recognition** | DeepFace ArcFace — matches faces against an enrolled `Faces_db/` database |
| **Pose-based action recognition** | YOLOv8n-pose — compares keypoints against reference poses from `Actions_db/` |
| **GPU acceleration** | CUDA 12.4 / cuDNN — all YOLO and Re-ID inference runs on GPU when available |
| **Multi-camera support** | Unlimited local (V4L2) or network (RTSP) cameras simultaneously |
| **Horizontal scaling** | Stateless AI workers scale independently via Redis Streams + KEDA |

---

## Architecture

ObserveAI processes every camera feed through a layered AI pipeline. In the desktop and web modes this runs in a single process; in microservices mode each stage becomes an independent, scalable pod.

```
Camera (USB / RTSP)
  └─► Frame Capture
        └─► Person Detection (YOLOv8n)
              └─► Local Tracking (DeepSORT — per camera)
                    ├─► Face Detection (YOLOv11n-face)
                    │     └─► Face Recognition (DeepFace ArcFace)
                    │           └─► Face DB Writer (quality-gated save)
                    ├─► Re-ID Feature Extraction (ResNet-50)
                    │     └─► Global Person Tracker (cross-camera EMA matching)
                    └─► Pose Estimation (YOLOv8n-pose)
                          └─► Action Recognition (reference pose matching)
```

### Cross-camera identity linking

`GlobalPersonTracker` maintains a unified identity registry. When a person moves from one camera to another, the system matches their Re-ID embedding (cosine similarity) against all active global persons and merges the tracks. Feature vectors are blended using EMA (`α = 0.15`) to prevent drift from noisy frames.

---

## AI Pipeline

| Stage | Model | Input | Output |
|---|---|---|---|
| Person detection | `yolov8n.pt` | Full frame | Bounding boxes + confidence |
| Local tracking | DeepSORT | Bboxes per frame | Track IDs (per camera) |
| Face detection | `yolov11n-face.pt` | Person crop | Face bboxes + confidence |
| Face recognition | DeepFace ArcFace | Face crop | Identity + distance |
| Re-ID extraction | ResNet-50 (torchvision) | Person crop | 2048-d L2-normalised vector |
| Pose estimation | `yolov8n-pose.pt` | Person crop | 17-keypoint skeleton |
| Action recognition | Reference JSON matching | Keypoints | Action name + distance |

---

## Deployment Modes

### Mode 1 — Desktop GUI (PyQt6)

The original desktop application. All AI runs in a single Python process with a native Qt window rendering annotated video feeds.

**Best for:** Development, single-machine setups, no network dependency.

**Run:**
```bash
# Install dependencies
pip install opencv-contrib-python PyQt6 psutil ultralytics deep-sort-realtime \
            deepface torch torchvision tensorflow tf_keras

# Start
python main.py
```

Python 3.12 is required (see `.python-version`).

**What you get:**
- Native desktop window with live annotated camera grids
- Per-camera AI configuration panel
- Face enrolment and management UI
- Pose action creator (`python pose_creator.py`)
- Settings persisted to `settings.json`

---

### Mode 2 — Web UI (FastAPI + React)

A headless server mode that replaces the PyQt6 window with a FastAPI backend and a React frontend. All AI components remain identical — only the presentation layer changes. Runs without a display server, making it suitable for remote or headless hosts.

**Best for:** Remote access via browser, headless servers, LAN/VPN deployments.

**Run:**
```bash
# Install dependencies
pip install opencv-contrib-python psutil ultralytics deep-sort-realtime \
            deepface torch torchvision tensorflow tf_keras \
            fastapi uvicorn[standard] python-multipart

# Build the React frontend (one-time)
cd web/frontend
npm install && npm run build
cd ../..

# Start the server
python web_main.py
# Open http://localhost:8000
```

Or with uvicorn directly:
```bash
uvicorn web.server:app --host 0.0.0.0 --port 8000
```

**What you get:**
- Browser-based camera grid dashboard
- REST API for camera management, face enrolment, settings
- MJPEG video streaming per camera
- WebSocket real-time detection events
- Identical AI behaviour to the desktop mode

---

### Mode 3 — Containerised Microservices

The production deployment model. Each AI stage is an independent Docker container connected by **Redis Streams**. Stateless inference workers (YOLO, Re-ID, face recognition, pose) scale horizontally via **KEDA** autoscaling triggered by queue depth. The stateful components (DeepSORT tracker, Global Tracker) run as singletons.

**Best for:** Production, cloud/Kubernetes deployments, high camera counts, GPU cluster utilisation.

#### Pipeline topology

```
All Cameras ──► shared_raw_frames (Redis Stream)
                        │
            ┌───────────▼────────────┐
            │  Person YOLO Pool       │  ← scales 1–4 pods on queue depth
            └───────────┬────────────┘
                        │ person_detections::{camera}
            ┌───────────▼────────────┐
            │  DeepSORT Tracker       │  ← 1 pod per camera (stateful)
            └──────┬─────────────────┘
                   │ person_tracks::{camera}
       ┌───────────┼─────────────────┐
       │           │                 │
  ┌────▼────┐ ┌────▼─────┐ ┌────────▼──────┐
  │Face YOLO│ │Re-ID Pool│ │ Pose/Action   │  ← all scale 1–4 pods
  │  Pool   │ │          │ │   Pool        │
  └────┬────┘ └────┬─────┘ └───────────────┘
       │ face_crops     │ reid_features
  ┌────▼────┐ ┌────▼──────────┐
  │Face     │ │Global Person  │  ← singleton (stateful EMA matching)
  │Recog    │ │Tracker        │
  │Pool     │ └───────────────┘
  └────┬────┘
       │ identity_results
  ┌────▼────┐
  │Face DB  │  ← scales 1–3 pods
  │Writer   │
  └─────────┘
```

#### Quick start (Docker Compose)

```bash
cd ObserveAI_main

# GPU host (recommended)
docker compose -f containerized/docker-compose.yml up --build -d

# CPU-only: remove the `deploy` block from each GPU service in docker-compose.yml first

# Open the dashboard
# http://localhost:8000
```

#### Kubernetes + KEDA

```bash
# 1. Install KEDA autoscaler
kubectl apply -f https://github.com/kedacore/keda/releases/download/v2.13.1/keda-2.13.1.yaml

# 2. Deploy the full stack
kubectl apply -k containerized/k8s/microservices/

# 3. Check rollout
kubectl -n observeai get pods
kubectl -n observeai rollout status deployment/global-tracker
```

#### Services and autoscaling

| Service | Replicas | GPU | Scales on |
|---|---|---|---|
| `cam-ingest` | 1 per camera | No | Fixed |
| `person-yolo-worker` | 1 → 4 | Yes | `shared_raw_frames` depth > 30 |
| `deepsort-tracker` | 1 per camera | No | Fixed (stateful) |
| `face-yolo-worker` | 1 → 4 | Yes | `person_tracks` depth > 20 |
| `reid-feature-worker` | 1 → 4 | Yes | `person_tracks` depth > 20 |
| `face-recog-worker` | 1 → 4 | No | `face_crops` depth > 20 |
| `face-db-writer` | 1 → 3 | No | `identity_results` depth > 30 |
| `action-pose-worker` | 1 → 4 | Yes | `person_tracks` depth > 20 |
| `global-tracker` | 1 (singleton) | No | Fixed (stateful) |

#### Using USB cameras in Docker

Uncomment the `devices` section in `docker-compose.yml` for each `cam-ingest` service:
```yaml
devices:
  - /dev/video0:/dev/video0
```

RTSP cameras require no device mounts — configure via `CAMERA_SOURCE=rtsp://...` env var.

---

## Configuration

All runtime settings are stored in `settings.json` and managed through the UI or directly.

| Key | Default | Description |
|---|---|---|
| `feature_threshold` | `0.5` | Cosine distance threshold for Re-ID matching |
| `reid_weight` | `0.4` | Weight of Re-ID score in global matching |
| `color_weight` | `0.3` | Weight of colour histogram in global matching |
| `spatial_weight` | `0.3` | Weight of spatial proximity in global matching |
| `min_face_width` | `70` | Minimum face width (px) to attempt recognition |
| `min_face_height` | `90` | Minimum face height (px) to attempt recognition |
| `min_face_confidence` | `0.5` | Minimum YOLO face detection confidence |
| `identity_confirm_frames` | `3` | Consecutive matches required to lock an identity |
| `identity_confidence_threshold` | `0.6` | ArcFace distance threshold (lower = stricter) |
| `max_faces_per_user` | `5` | Maximum face images stored per enrolled person |
| `camera_actions` | `{}` | Maps camera names to their assigned action sets |

---

## Project Structure

```
ObserveAI_main/
│
├── main.py                     # Entry point — desktop GUI mode
├── web_main.py                 # Entry point — web UI mode
├── pose_creator.py             # Utility to record reference pose actions
├── settings.json               # Runtime configuration
│
├── main/
│   └── MainWindow.py           # PyQt6 central controller
│
├── DataModel/
│   ├── DetectionSystem.py      # Per-camera AI pipeline (YOLO + DeepSORT + DeepFace)
│   ├── GlobalPersonTracker.py  # Cross-camera identity registry (EMA Re-ID)
│   ├── Reid_model.py           # ResNet-50 Re-ID feature extractor
│   ├── ActionManager.py        # Pose-action loader and matcher
│   ├── SettingsManager.py      # settings.json read/write
│   └── EmbeddingCache.py       # Lazy-loaded DeepFace embedding cache
│
├── components/
│   ├── Camera_worker.py        # Frame capture thread (USB / RTSP)
│   └── Camera_widget.py        # PyQt6 single-camera video widget
│
├── web/
│   ├── server.py               # FastAPI app (replaces MainWindow in web mode)
│   ├── camera_manager.py       # Headless camera + AI orchestration
│   └── frontend/               # React + TypeScript dashboard (Vite)
│
├── UIs/                        # Qt Designer .ui files
├── Faces_db/                   # Enrolled face images (per-person subfolders)
├── Actions_db/                 # Reference pose JSON files
├── maps/                       # Camera calibration / homography data
│
└── containerized/
    ├── docker-compose.yml      # Full stack: Redis + 9 microservices + original backend
    ├── STREAMS_SCHEMA.md       # Redis Streams message contracts
    ├── VERIFICATION_REPORT.md  # Static analysis + bug fix log
    ├── CONTAINERIZATION.md     # Architecture decision record
    │
    ├── services/
    │   ├── shared/             # redis_client, image_codec, stream_utils
    │   ├── cam-ingest/
    │   ├── person-yolo-worker/
    │   ├── deepsort-tracker/
    │   ├── face-yolo-worker/
    │   ├── reid-feature-worker/
    │   ├── face-recog-worker/
    │   ├── face-db-writer/
    │   ├── action-pose-worker/
    │   └── global-tracker/
    │
    └── k8s/
        ├── (monolith manifests)
        └── microservices/      # Redis, 9 Deployments, KEDA ScaledObjects
```

---

## Requirements

### Desktop / Web mode

- Python **3.12**
- CUDA-capable GPU recommended (CPU fallback available)

```bash
pip install opencv-contrib-python PyQt6 psutil ultralytics deep-sort-realtime \
            deepface torch torchvision tensorflow tf_keras \
            fastapi "uvicorn[standard]" python-multipart
```

### Containerised mode

- Docker Engine 24+ with [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) for GPU support
- Docker Compose v2.20+
- **Kubernetes:** kubectl, [KEDA v2.13](https://keda.sh/docs/2.13/deploy/)

---

## Version History

| Tag | Mode | Description |
|---|---|---|
| `v1.0-monolith` | Desktop GUI | Original PyQt6 single-process application |
| `v2.0-scalable` | Web UI + Microservices | Headless FastAPI server + Redis Streams microservices with KEDA autoscaling |
