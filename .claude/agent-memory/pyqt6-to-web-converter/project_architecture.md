---
name: ObserveAI Web Migration Architecture
description: Full architecture plan for PyQt6 to FastAPI+React migration — backend endpoints, threading model, pages
type: project
---

# ObserveAI Web Migration Architecture

**Status: COMPLETE AND BUILDING** (as of 2026-04-03)

**Why:** Replace PyQt6 GUI with browser-accessible UI while keeping AI pipeline intact (DetectionSystem, GlobalPersonTracker, CameraWorker, ActionManager all preserved).

**How to apply:** Backend wraps existing Python classes. Only the GUI layer is replaced — no changes to DetectionSystem.py, GlobalPersonTracker.py, CameraWorker, or ActionManager.

## Backend: FastAPI (web/server.py)
- Wraps CameraWorkerThread (pure Python, drops Qt signals, uses callback+queue)
- Ai_System_thread preserved exactly as-is from DataModel/DetectionSystem.py
- MJPEG stream endpoint: GET /api/cameras/{name}/stream
- WebSocket for all events: /ws/events (unified: detections, status, person_updates, camera_status)
- REST endpoints for CRUD on cameras, settings, faces, actions, logs
- Entry point: python web_main.py (starts uvicorn on port 8000)

## 6 Pages (matching original QStackedWidget pages 0-5):
- Page 0 (camera-map): CameraMapPage — HTML5 canvas floor plan, draggable cameras, FOV cones, person dots
- Page 1 (camera-feed): CameraFeedPage — MJPEG grid, configurable columns (1-4), fullscreen toggle
- Page 2 (database): FaceDatabasePage — person list, photo gallery, rename/delete, upload
- Page 3 (logs): LogsPage — SQLite log query, evidence viewer panel
- Page 4 (settings): SettingsPage — grouped settings with sliders and number inputs
- Page 5 (actions): ActionsPage — action library + camera assignments + live detection log

## Threading Model (preserved):
- Each camera: threading.Thread for CameraWorkerThread (capture)
- Each camera: threading.Thread for Ai_System_thread (AI inference)
- Main thread: FastAPI/asyncio event loop
- Communication: queue.Queue for frames (same as original)
- AI output callback: call_soon_threadsafe → asyncio.Queue → MJPEG stream

## TypeScript Build Notes:
- All React style objects must be typed as `Record<string, React.CSSProperties>` or have inline `as React.CSSProperties` casts
- Dynamic style functions return explicit `React.CSSProperties` return type
- Do NOT annotate static style dicts with `S = {` without type — TypeScript will reject string literal CSS values
- Build command: `cd web/frontend && npm run build` — outputs to web/frontend/dist/
- The FastAPI server auto-detects dist/ and serves it as SPA

## File Structure:
```
web/
  server.py          # FastAPI app, all routes
  camera_manager.py  # Manages cameras (replaces PyQt6 MainWindow camera logic)
  __init__.py        # Package marker
  requirements.txt   # FastAPI, uvicorn, python-multipart, psutil
  frontend/
    index.html
    package.json     # React 18, Zustand, TypeScript, Vite
    vite.config.ts   # Proxy: /api and /ws → localhost:8000
    tsconfig.json
    src/
      main.tsx
      App.tsx
      components/
        CameraGrid.tsx  (note: actual file is CameraFeedPage.tsx)
        CameraFeedPage.tsx
        CameraMapPage.tsx
        FaceDatabasePage.tsx
        LogsPage.tsx
        SettingsPage.tsx
        ActionsPage.tsx
        AddCameraModal.tsx
        Sidebar.tsx
        StatusBar.tsx
        ToastContainer.tsx
      store/
        appStore.ts    # Zustand store: cameras, settings, WS, toasts, actions
      types/
        index.ts       # Camera, AppSettings, LogEntry, WsEvent types
```

## Running the Web App:
```bash
# Development (two terminals):
python web_main.py                         # Backend on :8000
cd web/frontend && npm run dev             # Frontend dev server on :5173

# Production (single command):
cd web/frontend && npm run build           # Build once
python web_main.py                         # Serves API + built frontend on :8000
```

## API Workflow:
1. Add cameras via POST /api/cameras (name, url, fov, view_range, pos, rot, actions)
2. Call POST /api/cameras/finish-setup to start AI threads
3. Stream video via <img src="/api/cameras/{name}/stream"> (MJPEG)
4. Connect WebSocket to /ws/events for real-time events

## Known Constraints:
- workers=1 is mandatory in uvicorn — shared global state (camera_manager singleton)
- asyncio.Queue used for MJPEG frames; thread-safe via call_soon_threadsafe
- Full AI pipeline (deepface, ultralytics, torch) required for AI features
