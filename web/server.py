"""
web/server.py

FastAPI backend for ObserveAI.
Replaces the PyQt6 MainWindow GUI layer while keeping all AI/detection
code (DetectionSystem, GlobalPersonTracker, CameraWorker, ActionManager)
completely intact.

Run with:
    cd /path/to/ObserveAI_main
    python web/server.py

Or with uvicorn directly:
    uvicorn web.server:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import sys
import asyncio
import json
import time
import threading
import queue
import cv2
import psutil
import base64
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ["TF_USE_LEGACY_KERAS"] = "1"

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from DataModel.SettingsManager import get_settings
from DataModel.ActionManager import ActionManager
from DataModel.LogManager import get_log_manager
from DataModel.EmbeddingCache import get_embedding_cache
from web.camera_manager import CameraManager, detect_local_cameras


# ─────────────────────────────────────────────
# Global state
# ─────────────────────────────────────────────

# Per-camera MJPEG frame queues: camera_name -> asyncio.Queue
_mjpeg_queues: Dict[str, asyncio.Queue] = {}
_mjpeg_queues_lock = threading.Lock()

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.active.append(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self.active:
                self.active.remove(ws)

    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = []
        async with self._lock:
            targets = list(self.active)
        for ws in targets:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


ws_manager = ConnectionManager()
camera_manager: Optional[CameraManager] = None
_event_loop: Optional[asyncio.AbstractEventLoop] = None


# ─────────────────────────────────────────────
# Camera callbacks (called from worker threads)
# ─────────────────────────────────────────────

def _on_ai_frame(camera_name: str, frame):
    """
    Receives annotated BGR numpy frame from DetectionSystem.
    Encodes to JPEG and pushes into the asyncio queue for MJPEG streaming.
    """
    try:
        ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ret:
            return
        jpeg_bytes = jpeg.tobytes()

        with _mjpeg_queues_lock:
            if camera_name not in _mjpeg_queues:
                return
            q = _mjpeg_queues[camera_name]

        # Thread-safe push into asyncio queue via call_soon_threadsafe
        if _event_loop and not _event_loop.is_closed():
            try:
                _event_loop.call_soon_threadsafe(_push_frame_sync, camera_name, jpeg_bytes)
            except RuntimeError:
                pass
    except Exception as e:
        print(f"[SERVER] Frame encode error for '{camera_name}': {e}")


def _push_frame_sync(camera_name: str, jpeg_bytes: bytes):
    """Must be called from the event loop thread."""
    with _mjpeg_queues_lock:
        q = _mjpeg_queues.get(camera_name)
    if q is None:
        return
    # Drain if full to keep latency low
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break
    try:
        q.put_nowait(jpeg_bytes)
    except asyncio.QueueFull:
        pass


def _on_action_detected(camera: str, person: str, action: str, timestamp: float, evidence_path: Optional[str]):
    """Broadcast action detection event to all WebSocket clients."""
    ev_url = None
    if evidence_path:
        filename = os.path.basename(evidence_path)
        ev_url = f"/api/evidence/{filename}"

    payload = {
        "type": "action_detected",
        "camera": camera,
        "person": person,
        "action": action,
        "timestamp": timestamp,
        "evidence_url": ev_url
    }
    if _event_loop and not _event_loop.is_closed():
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), _event_loop)


def _on_person_position(global_id: int, x: float, y: float, camera_name: str):
    """Broadcast person position update to WebSocket clients."""
    payload = {
        "type": "person_update",
        "global_id": global_id,
        "camera": camera_name,
        "x": x,
        "y": y
    }
    if _event_loop and not _event_loop.is_closed():
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), _event_loop)


def _on_camera_status(camera_name: str, status: str, message: str):
    """Broadcast camera status change to WebSocket clients."""
    payload = {
        "type": "camera_status",
        "camera": camera_name,
        "status": status,
        "message": message
    }
    if _event_loop and not _event_loop.is_closed():
        asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), _event_loop)


# ─────────────────────────────────────────────
# App lifecycle
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global camera_manager, _event_loop
    _event_loop = asyncio.get_event_loop()

    camera_manager = CameraManager(
        on_ai_frame=_on_ai_frame,
        on_action_detected=_on_action_detected,
        on_person_position=_on_person_position,
        on_camera_status=_on_camera_status
    )

    # Start system status broadcast task
    asyncio.create_task(_status_broadcast_loop())

    print("[SERVER] ObserveAI web server started.")
    yield

    # Shutdown
    if camera_manager:
        camera_manager.shutdown()
    print("[SERVER] ObserveAI web server stopped.")


app = FastAPI(title="ObserveAI API", version="2.0.0", lifespan=lifespan)

# Allow dev frontend (Vite on :5173) to access the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# System status broadcast
# ─────────────────────────────────────────────

async def _status_broadcast_loop():
    while True:
        try:
            cameras_status = {}
            if camera_manager:
                for cam in camera_manager.get_cameras():
                    cameras_status[cam["name"]] = {
                        "status": cam["status"],
                        "ai_running": cam["ai_running"]
                    }

            payload = {
                "type": "system_status",
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_percent": psutil.virtual_memory().percent,
                "cameras": cameras_status
            }
            await ws_manager.broadcast(payload)
        except Exception as e:
            print(f"[SERVER] Status broadcast error: {e}")
        await asyncio.sleep(3)


# ─────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────

class AddCameraRequest(BaseModel):
    name: str
    url: str
    fov: float = 70.0
    view_range: float = 200.0
    pos: List[float] = [30.0, 30.0]
    rot: float = 0.0
    actions: List[str] = []


class UpdateCameraRequest(BaseModel):
    url: Optional[str] = None
    fov: Optional[float] = None
    view_range: Optional[float] = None
    pos: Optional[List[float]] = None
    rot: Optional[float] = None
    actions: Optional[List[str]] = None


class SettingsUpdate(BaseModel):
    feature_threshold: Optional[float] = None
    reid_weight: Optional[float] = None
    color_weight: Optional[float] = None
    spatial_weight: Optional[float] = None
    spatial_region_weight: Optional[float] = None
    spatial_depth_weight: Optional[float] = None
    ref_human_height_px: Optional[int] = None
    default_fov: Optional[float] = None
    dot_radius: Optional[int] = None
    min_quality_threshold: Optional[int] = None
    max_faces_per_user: Optional[int] = None
    identity_confirm_frames: Optional[int] = None
    identity_confidence_threshold: Optional[float] = None
    identity_change_margin: Optional[float] = None
    min_face_width: Optional[int] = None
    min_face_height: Optional[int] = None
    min_face_confidence: Optional[float] = None


class RenamePersonRequest(BaseModel):
    new_name: str


class CameraActionsUpdate(BaseModel):
    camera_actions: Dict[str, List[str]]


# ─────────────────────────────────────────────
# Camera API
# ─────────────────────────────────────────────

@app.get("/api/cameras")
def list_cameras():
    if not camera_manager:
        return []
    return camera_manager.get_cameras()


@app.post("/api/cameras")
def add_camera(req: AddCameraRequest):
    if not camera_manager:
        raise HTTPException(503, "Server not ready")
    ok = camera_manager.add_camera(
        name=req.name, url=req.url, fov=req.fov,
        view_range=req.view_range, pos=req.pos, rot=req.rot, actions=req.actions
    )
    if not ok:
        raise HTTPException(409, f"Camera '{req.name}' already exists")

    # Create MJPEG queue for this camera
    with _mjpeg_queues_lock:
        _mjpeg_queues[req.name] = asyncio.Queue(maxsize=2)

    return {"status": "ok", "name": req.name}


@app.patch("/api/cameras/{name}")
def update_camera(name: str, req: UpdateCameraRequest):
    if not camera_manager:
        raise HTTPException(503, "Server not ready")
    ok = camera_manager.update_camera(
        name=name,
        url=req.url, fov=req.fov, view_range=req.view_range,
        pos=req.pos, rot=req.rot, actions=req.actions
    )
    if not ok:
        raise HTTPException(404, f"Camera '{name}' not found")
    return {"status": "ok"}


@app.delete("/api/cameras/{name}")
def delete_camera(name: str):
    if not camera_manager:
        raise HTTPException(503, "Server not ready")
    camera_manager.remove_camera(name)

    with _mjpeg_queues_lock:
        _mjpeg_queues.pop(name, None)

    return {"status": "ok"}


@app.post("/api/cameras/{name}/restart")
def restart_camera(name: str):
    if not camera_manager:
        raise HTTPException(503, "Server not ready")
    worker = camera_manager.camera_workers.get(name)
    if not worker:
        raise HTTPException(404, f"Camera '{name}' not found")
    worker.restart()
    return {"status": "ok"}


@app.post("/api/cameras/finish-setup")
def finish_camera_setup():
    if not camera_manager:
        raise HTTPException(503, "Server not ready")
    camera_manager.finish_setup()
    return {"status": "ok", "message": "AI started for all cameras"}


# ─────────────────────────────────────────────
# MJPEG Video Streaming
# ─────────────────────────────────────────────

@app.get("/api/cameras/{name}/stream")
async def stream_camera(name: str):
    """
    MJPEG stream for a camera's annotated (AI overlay) video feed.
    The browser connects with an <img> tag or EventSource.
    """
    if camera_manager and name not in camera_manager.camera_workers:
        raise HTTPException(404, f"Camera '{name}' not found")

    # Ensure MJPEG queue exists
    with _mjpeg_queues_lock:
        if name not in _mjpeg_queues:
            _mjpeg_queues[name] = asyncio.Queue(maxsize=2)
        q = _mjpeg_queues[name]

    async def frame_generator():
        while True:
            try:
                jpeg_bytes = await asyncio.wait_for(q.get(), timeout=5.0)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" +
                    jpeg_bytes +
                    b"\r\n"
                )
            except asyncio.TimeoutError:
                # Send a keepalive empty boundary so the connection stays alive
                yield b"--frame\r\n\r\n"
            except Exception:
                break

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# ─────────────────────────────────────────────
# Layout save/load
# ─────────────────────────────────────────────

@app.post("/api/layout/save")
def save_layout(path: str = "maps/web_layout.json"):
    if not camera_manager:
        raise HTTPException(503, "Server not ready")
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    camera_manager.save_layout(path)
    return {"status": "ok", "path": path}


@app.post("/api/layout/load")
def load_layout(path: str = "maps/web_layout.json"):
    if not camera_manager:
        raise HTTPException(503, "Server not ready")
    if not os.path.exists(path):
        raise HTTPException(404, f"Layout file not found: {path}")
    data = camera_manager.load_layout(path)
    # Recreate MJPEG queues for newly loaded cameras
    with _mjpeg_queues_lock:
        for cam in camera_manager.get_cameras():
            if cam["name"] not in _mjpeg_queues:
                _mjpeg_queues[cam["name"]] = asyncio.Queue(maxsize=2)
    return {"status": "ok", "data": data}


@app.get("/api/layout/maps")
def list_maps():
    maps_dir = os.path.join(PROJECT_ROOT, "maps")
    if not os.path.exists(maps_dir):
        return []
    return [f for f in os.listdir(maps_dir) if f.endswith(".json")]


# ─────────────────────────────────────────────
# Local Camera Detection
# ─────────────────────────────────────────────

@app.get("/api/detect-cameras")
def api_detect_cameras():
    """Returns a list of locally connected cameras."""
    return detect_local_cameras()


# ─────────────────────────────────────────────
# Settings API
# ─────────────────────────────────────────────

@app.get("/api/settings")
def get_all_settings():
    return get_settings().get_all()


@app.patch("/api/settings")
def update_settings(update: SettingsUpdate):
    settings = get_settings()
    data = update.model_dump(exclude_none=True)
    for key, value in data.items():
        settings.set(key, value)

    # Apply to global tracker live
    if camera_manager and camera_manager.global_tracker:
        gt = camera_manager.global_tracker
        if "feature_threshold" in data:
            gt.feature_threshold = data["feature_threshold"]
        if "reid_weight" in data:
            gt.reid_weight = data["reid_weight"]
        if "spatial_weight" in data:
            gt.spatial_weight = data["spatial_weight"]

    settings.save()
    return {"status": "ok"}


@app.post("/api/settings/reset")
def reset_settings():
    settings = get_settings()
    defaults = settings.reset_defaults()
    settings.save()
    return defaults


# ─────────────────────────────────────────────
# Camera Actions API
# ─────────────────────────────────────────────

@app.get("/api/actions")
def list_actions():
    am = ActionManager()
    return am.get_action_list()


@app.delete("/api/actions/{name}")
def delete_action(name: str):
    am = ActionManager()
    if not am.delete_action(name):
        raise HTTPException(404, f"Action '{name}' not found")
    return {"status": "ok"}


@app.post("/api/actions/upload")
async def upload_action(name: str = Form(...), file: UploadFile = File(...)):
    """Upload a pose JSON file to create a new action."""
    content = await file.read()
    try:
        pose_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON file")

    am = ActionManager()
    ok = am.save_action(name, pose_data)
    if not ok:
        raise HTTPException(500, "Failed to save action")
    return {"status": "ok", "name": name}


@app.get("/api/camera-actions")
def get_camera_actions():
    settings = get_settings()
    return settings.get("camera_actions") or {}


@app.put("/api/camera-actions")
def set_camera_actions(update: CameraActionsUpdate):
    settings = get_settings()
    settings.set("camera_actions", update.camera_actions)
    settings.save()

    # Hot-reload on running AI instances
    if camera_manager:
        for cam_name, detection_sys in camera_manager.ai_instances.items():
            try:
                detection_sys.reload_actions()
            except Exception as e:
                print(f"[SERVER] Action reload failed for '{cam_name}': {e}")

    return {"status": "ok"}


# ─────────────────────────────────────────────
# Face Database API
# ─────────────────────────────────────────────

@app.get("/api/faces")
def list_faces():
    """List all persons in Faces_db."""
    db_path = os.path.join(PROJECT_ROOT, "Faces_db")
    if not os.path.exists(db_path):
        return []
    return sorted([
        d for d in os.listdir(db_path)
        if os.path.isdir(os.path.join(db_path, d))
    ])


@app.get("/api/faces/{person}/images")
def list_face_images(person: str):
    """List image filenames for a person."""
    db_path = os.path.join(PROJECT_ROOT, "Faces_db")
    person_path = os.path.join(db_path, person)
    if not os.path.exists(person_path):
        raise HTTPException(404, f"Person '{person}' not found")
    valid = ('.jpg', '.jpeg', '.png')
    return sorted([f for f in os.listdir(person_path) if f.lower().endswith(valid)])


@app.get("/api/faces/{person}/images/{filename}")
def get_face_image(person: str, filename: str):
    """Serve a face image file."""
    db_path = os.path.join(PROJECT_ROOT, "Faces_db")
    img_path = os.path.join(db_path, person, filename)
    if not os.path.exists(img_path):
        raise HTTPException(404, "Image not found")
    return FileResponse(img_path)


@app.post("/api/faces/{person}/rename")
def rename_person(person: str, req: RenamePersonRequest):
    """Rename a person in Faces_db and update embedding cache."""
    new_name = req.new_name.strip()
    if not new_name:
        raise HTTPException(400, "New name cannot be empty")

    db_path = os.path.join(PROJECT_ROOT, "Faces_db")
    old_path = os.path.join(db_path, person)
    new_path = os.path.join(db_path, new_name)

    if not os.path.exists(old_path):
        raise HTTPException(404, f"Person '{person}' not found")
    if os.path.exists(new_path):
        raise HTTPException(409, f"Person '{new_name}' already exists")

    # Use tracker/cache rename if available
    success = False
    if camera_manager and camera_manager.global_tracker:
        success = camera_manager.global_tracker.rename_user(person, new_name)
    if not success:
        try:
            cache = get_embedding_cache()
            success = cache.rename_user(person, new_name)
        except Exception as e:
            print(f"[SERVER] Cache rename error: {e}")

    if not success:
        # Fallback: direct filesystem rename
        try:
            os.rename(old_path, new_path)
            success = True
        except Exception as e:
            raise HTTPException(500, f"Rename failed: {e}")

    return {"status": "ok", "old_name": person, "new_name": new_name}


@app.delete("/api/faces/{person}")
def delete_person(person: str):
    """Delete a person and all their face images."""
    import shutil
    db_path = os.path.join(PROJECT_ROOT, "Faces_db")
    person_path = os.path.join(db_path, person)
    if not os.path.exists(person_path):
        raise HTTPException(404, f"Person '{person}' not found")
    shutil.rmtree(person_path)
    return {"status": "ok"}


@app.delete("/api/faces/{person}/images/{filename}")
def delete_face_image(person: str, filename: str):
    """Delete a specific face image."""
    db_path = os.path.join(PROJECT_ROOT, "Faces_db")
    img_path = os.path.join(db_path, person, filename)
    if not os.path.exists(img_path):
        raise HTTPException(404, "Image not found")
    os.remove(img_path)
    return {"status": "ok"}


@app.post("/api/faces/{person}/upload")
async def upload_face_image(person: str, file: UploadFile = File(...)):
    """Upload a new face image for a person (creates person if needed)."""
    db_path = os.path.join(PROJECT_ROOT, "Faces_db")
    person_path = os.path.join(db_path, person)
    os.makedirs(person_path, exist_ok=True)

    filename = file.filename or f"upload_{int(time.time())}.jpg"
    save_path = os.path.join(person_path, filename)
    content = await file.read()
    with open(save_path, 'wb') as f:
        f.write(content)

    return {"status": "ok", "filename": filename}


# ─────────────────────────────────────────────
# Logs API
# ─────────────────────────────────────────────

@app.get("/api/logs")
def get_logs(
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    person_name: Optional[str] = None,
    limit: int = 200
):
    lm = get_log_manager()
    logs = lm.get_logs(start_time=start_time, end_time=end_time, person_name=person_name)
    return logs[:limit]


@app.get("/api/logs/summary/{person}")
def get_person_summary(person: str):
    lm = get_log_manager()
    return {"summary": lm.get_person_activity_summary(person)}


@app.get("/api/evidence/{filename}")
def get_evidence(filename: str):
    path = os.path.join(PROJECT_ROOT, "detections", filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Evidence file not found")
    return FileResponse(path)


# ─────────────────────────────────────────────
# System Status API
# ─────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    cameras = camera_manager.get_cameras() if camera_manager else []
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": psutil.virtual_memory().percent,
        "cameras": {c["name"]: {"status": c["status"], "ai_running": c["ai_running"]} for c in cameras}
    }


# ─────────────────────────────────────────────
# WebSocket endpoint
# ─────────────────────────────────────────────

@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    Primary WebSocket endpoint.
    Broadcasts:
      - action_detected events
      - person_update (position) events
      - camera_status events
      - system_status (every 3s)
    """
    await ws_manager.connect(websocket)
    try:
        # Send initial state
        await websocket.send_text(json.dumps({
            "type": "init",
            "cameras": camera_manager.get_cameras() if camera_manager else [],
            "settings": get_settings().get_all()
        }))

        while True:
            # Keep connection alive; server-side pushes handle messages
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # Handle client-to-server messages if needed
                data = json.loads(msg)
                if data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket)


# ─────────────────────────────────────────────
# Serve React frontend (production build)
# ─────────────────────────────────────────────

FRONTEND_BUILD = os.path.join(os.path.dirname(__file__), "frontend", "dist")

if os.path.exists(FRONTEND_BUILD):
    # Serve static assets
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_BUILD, "assets")), name="assets")

    @app.get("/")
    def serve_root():
        return FileResponse(os.path.join(FRONTEND_BUILD, "index.html"))

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # SPA fallback — serve index.html for any non-API route
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            raise HTTPException(404)
        index = os.path.join(FRONTEND_BUILD, "index.html")
        if os.path.exists(index):
            return FileResponse(index)
        raise HTTPException(404)
else:
    @app.get("/")
    def serve_dev_info():
        return {
            "message": "ObserveAI API is running. Start the frontend dev server with: cd web/frontend && npm run dev",
            "api_docs": "/docs",
            "websocket": "ws://localhost:8000/ws/events",
            "video_stream": "http://localhost:8000/api/cameras/{name}/stream"
        }


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "web.server:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )
