"""
web/camera_manager.py

Replaces the PyQt6 MainWindow's camera orchestration logic.
Manages CameraWorker threads, Ai_System_thread instances, and
GlobalPersonTracker — all without any Qt dependency.

The PyQt6 CameraWorker used Qt signals for communication.
Here we use a pure-Python adapter (CameraWorkerThread) that
calls asyncio-safe callbacks instead.
"""

import os
import sys
import asyncio
import threading
import queue
import time
import json
import cv2
import re
import subprocess
from typing import Dict, Callable, Optional, Any

# Add project root to path so existing DataModel imports work
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from DataModel.GlobalPersonTracker import GlobalPersonTracker
from DataModel.ActionManager import ActionManager
from DataModel.SettingsManager import get_settings
from DataModel.DetectionSystem import Ai_System_thread
from DataModel.LogManager import get_log_manager


def detect_local_cameras() -> list:
    """Enumerate USB/V4L2 cameras. Returns list of {name, device} dicts."""
    cameras = []
    try:
        output = subprocess.check_output(
            ["v4l2-ctl", "--list-devices"],
            stderr=subprocess.DEVNULL,
            timeout=3
        ).decode("utf-8", errors="ignore")

        current_name = None
        dev_re = re.compile(r"^\s+(/dev/video\d+)\s*$")
        for line in output.splitlines():
            dev_match = dev_re.match(line)
            if dev_match:
                dev = dev_match.group(1)
                if current_name and not any(c["device"] == dev for c in cameras):
                    cameras.append({"name": current_name, "device": dev})
                    current_name = None
            elif line.strip() and not line.startswith("\t") and not line.startswith(" "):
                current_name = line.strip().rstrip(":")
        return cameras
    except Exception:
        pass

    for i in range(10):
        cap = cv2.VideoCapture(f"/dev/video{i}")
        if cap.isOpened():
            cameras.append({"name": f"Camera (video{i})", "device": f"/dev/video{i}"})
            cap.release()
    return cameras


class CameraWorkerThread:
    """
    Pure-Python replacement for the PyQt6 CameraWorker.
    Runs frame capture in a daemon thread.
    Uses callbacks instead of Qt signals.
    """

    def __init__(self, name: str, url: str, frame_buffer: queue.Queue,
                 on_frame=None, on_connected=None, on_error=None):
        self.name = name
        self.url_str = url
        self.frame_buffer = frame_buffer
        self.on_frame = on_frame          # callback(name, bgr_frame)
        self.on_connected = on_connected  # callback(name, message)
        self.on_error = on_error          # callback(name, message)

        self.is_running = False
        self.should_reconnect = False
        self.latest_frame = None
        self._thread: Optional[threading.Thread] = None

    def _parse_url(self):
        if isinstance(self.url_str, str):
            if self.url_str.startswith("image://"):
                return None
            match = re.search(r'/dev/video(\d+)', self.url_str)
            if match:
                return int(match.group(1))
            try:
                return int(self.url_str)
            except ValueError:
                return None
        return None

    def _open_camera(self):
        url_int = self._parse_url()
        is_device_path = isinstance(self.url_str, str) and self.url_str.startswith("/dev/video")
        url_to_try = url_int if url_int is not None else self.url_str

        if is_device_path:
            cap = cv2.VideoCapture(url_to_try, cv2.CAP_V4L2)
        else:
            cap = cv2.VideoCapture(url_to_try)

        if not cap or not cap.isOpened():
            return None

        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if is_device_path:
            fourcc_mjpg = cv2.VideoWriter.fourcc(*"MJPG")
            cap.set(cv2.CAP_PROP_FOURCC, fourcc_mjpg)

        return cap

    def _run(self):
        cap = None
        is_image = False
        static_image = None

        def _init_source():
            nonlocal is_image, static_image, cap
            is_image = isinstance(self.url_str, str) and self.url_str.startswith("image://")

            if cap is not None:
                cap.release()

            if is_image:
                image_path = self.url_str[8:]
                static_image = cv2.imread(image_path)
                if static_image is None:
                    if self.on_error:
                        self.on_error(self.name, f"Failed to load image: {image_path}")
                else:
                    if self.on_connected:
                        self.on_connected(self.name, "Image Loaded")
            else:
                cap_local = self._open_camera()
                if not cap_local or not cap_local.isOpened():
                    if self.on_error:
                        self.on_error(self.name, f"Failed to open: {self.url_str}")
                else:
                    if self.on_connected:
                        self.on_connected(self.name, "Connected")
                    return cap_local
            return None

        cap = _init_source()

        while self.is_running:
            if self.should_reconnect:
                self.should_reconnect = False
                cap = _init_source()

            if is_image:
                if static_image is None:
                    time.sleep(0.5)
                    continue
                frame = static_image.copy()
                time.sleep(0.033)
            else:
                if cap is None or not cap.isOpened():
                    time.sleep(0.5)
                    continue

                ret, frame = cap.read()
                if not ret:
                    if self.on_error:
                        self.on_error(self.name, "Camera disconnected")
                    if cap is not None:
                        cap.release()
                        cap = None
                    time.sleep(0.5)
                    continue

            self.latest_frame = frame.copy()

            # Push to AI buffer
            if self.frame_buffer:
                try:
                    self.frame_buffer.put_nowait(frame.copy())
                except queue.Full:
                    try:
                        self.frame_buffer.get_nowait()
                        self.frame_buffer.put_nowait(frame.copy())
                    except queue.Empty:
                        pass

            # Fire raw frame callback (for MJPEG of raw feed)
            if self.on_frame:
                self.on_frame(self.name, frame)

        if cap is not None:
            cap.release()

    def start(self):
        self.is_running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"cam-{self.name}")
        self._thread.start()

    def stop(self):
        self.is_running = False

    def restart(self):
        self.should_reconnect = True


class CameraManager:
    """
    Central manager for all cameras and AI threads.
    Replaces MainWindow's camera orchestration (without any PyQt6).

    Event callbacks (called from worker threads — must be thread-safe):
      on_ai_frame(camera_name, bgr_frame)     — annotated frame from AI
      on_action_detected(camera, person, action, timestamp)
      on_person_position(global_id, x, y, camera_name)
      on_camera_status(camera_name, status, message)
    """

    def __init__(self,
                 on_ai_frame: Optional[Callable] = None,
                 on_action_detected: Optional[Callable] = None,
                 on_person_position: Optional[Callable] = None,
                 on_camera_status: Optional[Callable] = None):

        self.settings = get_settings()
        self.action_manager = ActionManager()
        self.log_manager = get_log_manager()

        # Callbacks
        self.on_ai_frame = on_ai_frame
        self.on_action_detected = on_action_detected
        self.on_person_position = on_person_position
        self.on_camera_status = on_camera_status

        # Camera state
        self.camera_workers: Dict[str, CameraWorkerThread] = {}
        self.camera_buffers: Dict[str, queue.Queue] = {}
        self.ai_instances: Dict[str, Any] = {}
        self.ai_threads: Dict[str, threading.Thread] = {}
        self.camera_configs: Dict[str, dict] = {}  # name -> {url, fov, view_range, pos, rot}

        self.FRAME_BUFFER_SIZE = 10
        self.camera_setup_done = False

        # Global tracker
        self.global_tracker = GlobalPersonTracker(
            feature_threshold=self.settings.get("feature_threshold"),
            reid_weight=self.settings.get("reid_weight"),
            color_weight=self.settings.get("color_weight", 0.3),
            spatial_weight=self.settings.get("spatial_weight"),
            position_callback=self._on_person_position_update,
            pixels_per_meter=30.0
        )

    def _on_person_position_update(self, global_id: int, x: float, y: float, camera_name: str):
        if self.on_person_position:
            self.on_person_position(global_id, x, y, camera_name)

    def _on_action_callback(self, camera: str, person: str, action: str, timestamp: float):
        """Called from AI thread when an action is detected."""
        # Save evidence frame
        evidence_path = None
        worker = self.camera_workers.get(camera)
        if worker and worker.latest_frame is not None:
            os.makedirs("detections", exist_ok=True)
            filename = f"act_{int(timestamp)}_{camera.replace(' ', '_')}.jpg"
            save_path = os.path.join("detections", filename)
            try:
                cv2.imwrite(save_path, worker.latest_frame)
                evidence_path = save_path
            except Exception as e:
                print(f"[CAM MANAGER] Failed to save evidence: {e}")

        # Log it
        self.log_manager.add_log(
            log_type='action',
            person_name=person,
            cameras=[camera],
            action=action,
            message=f"{action} detected on {camera}",
            evidence_path=evidence_path
        )

        if self.on_action_detected:
            self.on_action_detected(camera, person, action, timestamp, evidence_path)

    def add_camera(self, name: str, url: str, fov: float = 70.0,
                   view_range: float = 200.0, pos: list = None,
                   rot: float = 0.0, actions: list = None) -> bool:
        """Add and start a new camera. Returns True on success."""
        if name in self.camera_workers:
            print(f"[CAM MANAGER] Camera '{name}' already exists.")
            return False

        pos = pos or [30.0, 30.0]
        actions = actions or []

        # Persist action assignment
        cam_actions = self.settings.get("camera_actions") or {}
        cam_actions[name] = actions
        self.settings.set("camera_actions", cam_actions)
        self.settings.save()

        # Store config
        self.camera_configs[name] = {
            "name": name, "url": url, "fov": fov,
            "view_range": view_range, "pos": pos, "rot": rot, "actions": actions
        }

        # Create frame buffer
        frame_buffer = queue.Queue(maxsize=self.FRAME_BUFFER_SIZE)
        self.camera_buffers[name] = frame_buffer

        # Create worker
        worker = CameraWorkerThread(
            name=name, url=url, frame_buffer=frame_buffer,
            on_frame=lambda n, frame: self._on_raw_frame(n, frame),
            on_connected=lambda n, msg: self._fire_status(n, "connected", msg),
            on_error=lambda n, msg: self._fire_status(n, "error", msg)
        )
        self.camera_workers[name] = worker
        worker.start()

        # Register with global tracker
        self.global_tracker.register_camera(
            name=name,
            position=tuple(pos),
            rotation=rot,
            fov=fov,
            view_range=view_range
        )

        # Start AI if setup is done
        if self.camera_setup_done:
            self._start_ai(name, frame_buffer)

        return True

    def _on_raw_frame(self, camera_name: str, frame):
        """Forward raw camera frames to the MJPEG stream before AI is running."""
        if camera_name not in self.ai_instances and self.on_ai_frame:
            self.on_ai_frame(camera_name, frame)

    def _start_ai(self, name: str, frame_buffer: queue.Queue):
        """Launch the AI thread for a camera."""
        print(f"[CAM MANAGER] Starting AI for '{name}'...")
        ai_thread = threading.Thread(
            target=Ai_System_thread,
            args=(name, "Faces_db", frame_buffer,
                  self._ai_output_callback, 3, 15, self.global_tracker, self.ai_instances),
            kwargs={"action_callback": self._on_action_callback},
            daemon=True,
            name=f"ai-{name}"
        )
        self.ai_threads[name] = ai_thread
        ai_thread.start()

    def _ai_output_callback(self, camera_name: str, frame):
        """Receives annotated BGR numpy frame from DetectionSystem."""
        if self.on_ai_frame:
            self.on_ai_frame(camera_name, frame)

    def _fire_status(self, camera_name: str, status: str, message: str):
        if self.on_camera_status:
            self.on_camera_status(camera_name, status, message)

    def finish_setup(self):
        """Mark setup as done and start AI for all cameras."""
        self.camera_setup_done = True
        for name, frame_buffer in self.camera_buffers.items():
            if name not in self.ai_threads:
                self._start_ai(name, frame_buffer)

    def remove_camera(self, name: str):
        """Stop and remove a camera."""
        if name in self.ai_instances:
            self.ai_instances[name].stop()
            del self.ai_instances[name]
        if name in self.ai_threads:
            del self.ai_threads[name]
        if name in self.camera_workers:
            self.camera_workers[name].stop()
            del self.camera_workers[name]
        if name in self.camera_buffers:
            del self.camera_buffers[name]
        if name in self.camera_configs:
            del self.camera_configs[name]

        cam_actions = self.settings.get("camera_actions") or {}
        cam_actions.pop(name, None)
        self.settings.set("camera_actions", cam_actions)
        self.settings.save()

    def update_camera(self, name: str, url: str = None, fov: float = None,
                      view_range: float = None, pos: list = None, rot: float = None,
                      actions: list = None):
        """Update camera configuration."""
        if name not in self.camera_configs:
            return False

        cfg = self.camera_configs[name]
        if url is not None:
            cfg["url"] = url
            worker = self.camera_workers.get(name)
            if worker:
                worker.url_str = url
                worker.restart()
        if fov is not None:
            cfg["fov"] = fov
        if view_range is not None:
            cfg["view_range"] = view_range
        if pos is not None:
            cfg["pos"] = pos
        if rot is not None:
            cfg["rot"] = rot
        if actions is not None:
            cfg["actions"] = actions
            cam_actions = self.settings.get("camera_actions") or {}
            cam_actions[name] = actions
            self.settings.set("camera_actions", cam_actions)
            self.settings.save()
            # Hot-reload actions on running AI
            if name in self.ai_instances:
                try:
                    self.ai_instances[name].reload_actions()
                except Exception as e:
                    print(f"[CAM MANAGER] Action reload failed for '{name}': {e}")

        return True

    def get_cameras(self) -> list:
        """Return list of camera config dicts."""
        result = []
        for name, cfg in self.camera_configs.items():
            status = "connected"
            if name in self.camera_workers:
                worker = self.camera_workers[name]
                status = "connected" if (worker.is_running and worker.latest_frame is not None) else "connecting"
            result.append({**cfg, "status": status, "ai_running": name in self.ai_instances})
        return result

    def save_layout(self, path: str):
        """Save current camera layout to JSON file (mirrors MainWindow.save_layout)."""
        layout_data = {
            "pixels_per_meter": getattr(self.global_tracker, 'pixels_per_meter', 30.0),
            "cameras": [],
            "walls": []
        }
        for name, cfg in self.camera_configs.items():
            layout_data["cameras"].append({
                "name": cfg["name"],
                "url": cfg["url"],
                "pos": cfg["pos"],
                "rot": cfg["rot"],
                "fov": cfg["fov"],
                "view_range": cfg["view_range"]
            })
        with open(path, 'w') as f:
            json.dump(layout_data, f, indent=4)
        return True

    def load_layout(self, path: str):
        """Load camera layout from JSON file."""
        with open(path, 'r') as f:
            layout_data = json.load(f)

        # Clear existing
        for name in list(self.camera_workers.keys()):
            self.remove_camera(name)

        ppm = layout_data.get("pixels_per_meter", 30.0)
        if self.global_tracker:
            self.global_tracker.pixels_per_meter = ppm

        for cam_data in layout_data.get("cameras", []):
            name = cam_data["name"]
            url = cam_data["url"]
            cam_actions = self.settings.get("camera_actions") or {}
            actions = cam_actions.get(name, [])
            self.add_camera(
                name=name, url=url,
                fov=cam_data.get("fov", 70.0),
                view_range=cam_data.get("view_range", 200.0),
                pos=cam_data.get("pos", [30.0, 30.0]),
                rot=cam_data.get("rot", 0.0),
                actions=actions
            )

        return layout_data

    def shutdown(self):
        """Stop all cameras and AI threads."""
        if self.global_tracker:
            self.global_tracker.shutdown()
        for name in list(self.camera_workers.keys()):
            self.remove_camera(name)
