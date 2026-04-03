# ObserveAI — Final Changes: PyQt6 to Web UI Conversion

## Overview

The ObserveAI surveillance system has been converted from a PyQt6 desktop application to a browser-based web application. The conversion is **additive** — no existing AI or data pipeline code was modified. Only the presentation layer was replaced.

---

## What Was NOT Changed (Preserved Entirely)

| File / Directory | Role |
|---|---|
| `DataModel/DetectionSystem.py` | Per-camera AI pipeline (YOLO, DeepSORT, DeepFace, pose) |
| `DataModel/GlobalPersonTracker.py` | Cross-camera person registry with Re-ID |
| `DataModel/ActionManager.py` | Pose-based action definitions |
| `DataModel/SettingsManager.py` | Config read/write to `settings.json` |
| `DataModel/LogManager.py` | SQLite activity logging |
| `DataModel/Reid_model.py` | Re-ID feature extraction |
| `DataModel/EmbeddingCache.py` | Face embedding cache |
| `components/Camera_worker.py` | Original PyQt6 camera worker (still present) |
| `Faces_db/` | Face image database |
| `Actions_db/` | Pose action JSON files |
| `maps/` | Camera calibration / spatial mapping |
| `settings.json` | Runtime config (format unchanged) |
| `main.py` / `test.py` | Original desktop entry points (still functional) |
| `UIs/` | Qt Designer `.ui` files (still present) |

---

## New Files Added

### Backend

| File | Purpose |
|---|---|
| `web_main.py` | New entry point — starts the FastAPI/uvicorn web server on port 8000 |
| `web/__init__.py` | Python package marker |
| `web/server.py` | FastAPI application — all REST API endpoints + WebSocket + MJPEG streaming |
| `web/camera_manager.py` | Camera orchestration without PyQt6 — replaces `MainWindow`'s camera logic |
| `web/requirements.txt` | Additional Python dependencies for the web layer |

### Frontend

| File | Purpose |
|---|---|
| `web/frontend/index.html` | HTML shell for the React SPA |
| `web/frontend/vite.config.ts` | Vite build config (proxies `/api` and `/ws` to FastAPI in dev) |
| `web/frontend/tsconfig.json` | TypeScript strict mode config |
| `web/frontend/package.json` | Node dependencies (React 18, Zustand, Vite, TypeScript) |
| `web/frontend/src/main.tsx` | React DOM root mount |
| `web/frontend/src/App.tsx` | Root component — sidebar + status bar + page router |
| `web/frontend/src/store/appStore.ts` | Zustand global state (cameras, settings, WS events, toasts) |
| `web/frontend/src/types/index.ts` | TypeScript type definitions for all data models |
| `web/frontend/src/components/Sidebar.tsx` | Navigation sidebar (6 page links + camera controls) |
| `web/frontend/src/components/StatusBar.tsx` | Top bar — CPU/memory, WS connection indicator |
| `web/frontend/src/components/ToastContainer.tsx` | Auto-dismissing notification toasts |
| `web/frontend/src/components/AddCameraModal.tsx` | Modal form to add new cameras |
| `web/frontend/src/components/CameraFeedPage.tsx` | Live camera grid with MJPEG streams and AI overlays |
| `web/frontend/src/components/CameraMapPage.tsx` | HTML5 Canvas floor plan — draggable cameras, FOV cones, person dots |
| `web/frontend/src/components/FaceDatabasePage.tsx` | Face DB browser — list, photo gallery, rename, delete, upload |
| `web/frontend/src/components/LogsPage.tsx` | Activity log viewer with evidence image viewer |
| `web/frontend/src/components/SettingsPage.tsx` | All detection thresholds with sliders + number inputs |
| `web/frontend/src/components/ActionsPage.tsx` | Pose action library + camera-to-action assignment panel |

---

## Architectural Changes

### Communication: Qt Signals → Callbacks + asyncio

**Before:**
```
CameraWorker (PyQt6 QThread)
  --pyqtSignal--> MainWindow
  --pyqtSignal--> Camera_widget (QLabel)
```

**After:**
```
CameraWorkerThread (plain threading.Thread)
  --callback--> CameraManager
  --call_soon_threadsafe--> asyncio Queue
  --MJPEG HTTP stream--> Browser <img> tag
```

The new `CameraWorkerThread` in `web/camera_manager.py` replicates the behaviour of the original `CameraWorker` using Python `threading.Thread` and plain function callbacks instead of Qt signals.

### Video Delivery: QLabel Pixmap → MJPEG over HTTP

Annotated frames from `Ai_System_thread` are JPEG-encoded at 75% quality and served as `multipart/x-mixed-replace` streams at:

```
GET /api/cameras/{name}/stream
```

The browser renders them with a standard `<img src="...">` element — no WebRTC or additional plugins required.

### Real-Time Events: Qt Signals → WebSocket

All real-time events that previously used Qt signals now broadcast over a single WebSocket endpoint:

```
ws://localhost:8000/ws/events
```

| Event type | Triggered by | Old equivalent |
|---|---|---|
| `action_detected` | Pose action fires in AI thread | Qt signal → alert dialog |
| `person_update` | GlobalPersonTracker position update | Qt signal → BirdsEyeViewWidget |
| `camera_status` | Camera connect / disconnect | Qt signal → status label |
| `system_status` | Every 3 seconds | Qt timer → status bar |
| `init` | On WS connect | MainWindow startup state |

### Camera Orchestration: MainWindow → CameraManager

`MainWindow` previously managed all camera threads directly (2000+ lines). This logic was extracted into `web/camera_manager.py:CameraManager`, which:

- Manages `CameraWorkerThread` instances (one per camera)
- Launches `Ai_System_thread` from `DataModel/DetectionSystem.py` — **the same class, called identically**
- Initialises and manages `GlobalPersonTracker` — **same class, unchanged**
- Handles camera add / remove / update / restart at runtime
- Saves and loads floor plan layouts to/from JSON (same format as before)

### State Management: PyQt6 Widgets → Zustand Store

The browser frontend uses a single Zustand store (`appStore.ts`) as the source of truth for:
- Camera list and statuses
- Application settings
- Person positions on the floor map
- Recent action detections
- Notification toasts
- WebSocket connection state

The store opens the WebSocket on app mount and auto-reconnects every 3 seconds on disconnect.

### Page Navigation: QStackedWidget → In-Memory Router

The original `QStackedWidget` with 6 pages is replaced by a simple `currentPage` string in the Zustand store. Each page component renders conditionally in `App.tsx`.

---

## API Reference (New)

### REST Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/cameras` | List all cameras |
| `POST` | `/api/cameras` | Add a new camera |
| `PATCH` | `/api/cameras/{name}` | Update camera config |
| `DELETE` | `/api/cameras/{name}` | Remove a camera |
| `POST` | `/api/cameras/{name}/restart` | Reconnect a camera |
| `POST` | `/api/cameras/finish-setup` | Start AI for all cameras |
| `GET` | `/api/cameras/{name}/stream` | MJPEG video stream |
| `GET` | `/api/settings` | Get all settings |
| `PATCH` | `/api/settings` | Update settings (live-applied) |
| `POST` | `/api/settings/reset` | Reset to defaults |
| `GET` | `/api/actions` | List pose actions |
| `DELETE` | `/api/actions/{name}` | Delete a pose action |
| `POST` | `/api/actions/upload` | Upload a new pose JSON |
| `GET` | `/api/camera-actions` | Get camera→action mappings |
| `PUT` | `/api/camera-actions` | Update camera→action mappings |
| `GET` | `/api/faces` | List persons in Faces_db |
| `GET` | `/api/faces/{person}/images` | List images for a person |
| `GET` | `/api/faces/{person}/images/{filename}` | Serve a face image |
| `POST` | `/api/faces/{person}/rename` | Rename a person |
| `DELETE` | `/api/faces/{person}` | Delete a person |
| `DELETE` | `/api/faces/{person}/images/{filename}` | Delete a face image |
| `POST` | `/api/faces/{person}/upload` | Upload a new face image |
| `GET` | `/api/logs` | Query activity logs |
| `GET` | `/api/logs/summary/{person}` | Person activity summary |
| `GET` | `/api/evidence/{filename}` | Serve a detection evidence image |
| `GET` | `/api/status` | Current CPU/memory/camera status |
| `GET` | `/api/detect-cameras` | Enumerate local USB cameras |
| `POST` | `/api/layout/save` | Save floor plan layout |
| `POST` | `/api/layout/load` | Load floor plan layout |
| `GET` | `/api/layout/maps` | List saved layout files |

### WebSocket

```
ws://localhost:8000/ws/events
```

---

## How to Run

### Production (single server)
```bash
cd web/frontend && npm run build   # build frontend once
python web_main.py                 # serves UI + API on http://localhost:8000
```

### Development (hot-reload)
```bash
# Terminal 1
python web_main.py                 # API on http://localhost:8000

# Terminal 2
cd web/frontend && npm run dev     # UI on http://localhost:5173 with HMR
```

API documentation (auto-generated by FastAPI):
```
http://localhost:8000/docs
```

### Original desktop app (unchanged)
```bash
python main.py    # or python test.py
```

---

## Dependencies Added

### Python (`web/requirements.txt`)
```
fastapi
uvicorn[standard]
python-multipart
psutil
```

### Node (`web/frontend/package.json`)
```
react 18
react-dom 18
zustand
typescript
vite
@types/react
@types/react-dom
```
