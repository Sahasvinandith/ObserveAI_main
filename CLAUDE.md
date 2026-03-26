# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Main entry point
python main.py

# Alternative (identical behavior)
python test.py

# Pose action creator utility
python pose_creator.py
```

Python 3.12.10 is required (see `.python-version`).

## Installing Dependencies

```bash
pip install opencv-contrib-python PyQt6 psutil ultralytics deep-sort-realtime deepface torch torchvision tensorflow tf_keras
```

## Architecture Overview

ObserveAI is a real-time multi-camera CCTV surveillance system built on PyQt6 + YOLO + DeepSORT + DeepFace.

### Data Flow

```
Camera (local/RTSP)
  → CameraWorker (capture thread, components/Camera_worker.py)
  → DetectionSystem (per-camera AI thread, DataModel/DetectionSystem.py)
      ├─ YOLO person detection (yolov8n.pt)
      ├─ DeepSORT tracking (local IDs per camera)
      ├─ YOLO face detection (yolov11n-face.pt)
      ├─ Re-ID feature extraction (DataModel/Reid_model.py)
      ├─ YOLOv8-Pose detection (yolov8n-pose.pt)
      └─ DeepFace recognition against Faces_db/
  → GlobalPersonTracker (DataModel/GlobalPersonTracker.py)
      └─ Thread-safe global registry linking local per-camera IDs to global person IDs
  → MainWindow (main/MainWindow.py) — orchestrates GUI, cameras, and AI
```

### Key Components

- **`main/MainWindow.py`** — Central controller. Initializes GlobalPersonTracker, CameraGraph, ActionManager, and all camera threads. Handles UI events.
- **`DataModel/DetectionSystem.py`** — Per-camera AI pipeline running in `Ai_System_thread`. All YOLO inference, tracking, face recognition, and pose detection happens here.
- **`DataModel/GlobalPersonTracker.py`** — Singleton registry for all persons across cameras. Uses EMA (alpha=0.15) to blend Re-ID feature vectors across frames. Thread-safe with locks.
- **`DataModel/ActionManager.py`** — Loads/saves pose-based action definitions from `Actions_db/` (JSON files). Assigned to cameras via `settings.json`.
- **`DataModel/SettingsManager.py`** — Persists configuration to `settings.json`. Manages thresholds, weights, and camera-action mappings.
- **`components/BirdsEyeViewWidget.py`** — Homography-based top-down floor plan view showing all camera FOVs and tracked persons.
- **`components/Camera_widget.py`** — PyQt6 widget rendering a single camera's annotated video feed.

### UI Files

Qt Designer `.ui` files are in `UIs/` and have corresponding generated `_ui.py` files. Edit the `.ui` files with Qt Designer; the `_ui.py` files are auto-generated.

### Data Directories

- `Faces_db/` — Face crops organized in per-person subfolders (used by DeepFace)
- `Actions_db/` — JSON pose reference files for action recognition
- `maps/` — Camera calibration and spatial mapping data
- `settings.json` — Runtime config: thresholds, weights, camera-action assignments

### Threading Model

Each camera has two threads:
1. **CameraWorker** (`components/Camera_worker.py`) — frame capture only
2. **Ai_System_thread** inside DetectionSystem — all AI inference

The main thread runs the PyQt6 event loop. Communication between threads uses Qt signals/slots and thread-safe queues.

### Re-ID Feature Blending

Feature vectors are blended using EMA: `new = alpha * incoming + (1 - alpha) * existing` (alpha=0.15). Color histograms follow the same pattern. This prevents identity drift from single noisy frames.
