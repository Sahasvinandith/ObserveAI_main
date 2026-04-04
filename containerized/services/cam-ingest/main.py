"""
cam-ingest/main.py

Camera ingestion service. Reads frames from a camera source (RTSP URL or
/dev/videoN device index) and publishes them to the shared_raw_frames Redis Stream.

Environment variables:
  REDIS_URL       Redis URL (default: redis://localhost:6379)
  CAMERA_NAME     Logical camera identifier, e.g. "entrance_left"
  CAMERA_SOURCE   RTSP URL or integer device index, e.g. "0" or "rtsp://..."
  LOG_LEVEL       Logging level (default: info)
"""

import os
import sys
import time
import uuid

import cv2

# Allow running from any working directory by adding the services root to path
_SERVICES_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SERVICES_ROOT)

from shared.redis_client import get_redis_client
from shared.image_codec import encode_frame, resize_if_larger
from shared.stream_utils import xadd_json, log_json

# ── Configuration ─────────────────────────────────────────────────────────────
CAMERA_NAME: str = os.environ.get("CAMERA_NAME", "default_camera")
CAMERA_SOURCE_RAW: str = os.environ.get("CAMERA_SOURCE", "0")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "info").lower()

STREAM_KEY = "shared_raw_frames"
STREAM_MAXLEN = 600           # ~5 s at 120 frames/s across 4 cameras
JPEG_QUALITY = 85
MAX_WIDTH = 1920
MAX_HEIGHT = 1080

# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_source(raw: str):
    """Return integer device index or RTSP URL string."""
    try:
        return int(raw)
    except ValueError:
        return raw


def _open_capture(source) -> cv2.VideoCapture:
    log_json("info", "cam-ingest", "Opening capture", camera=CAMERA_NAME, source=str(source))
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera source: {source}")
    return cap


def _run(r, source):
    """
    Main capture loop. Publishes every decoded frame to shared_raw_frames.
    On reconnect, increments camera_epoch so downstream consumers can detect
    the frame_index reset.
    """
    camera_epoch = 0
    frame_index: int = 0

    while True:
        try:
            cap = _open_capture(source)
            camera_epoch += 1
            frame_index = 0
            log_json("info", "cam-ingest", "Capture opened", epoch=camera_epoch, camera=CAMERA_NAME)

            while True:
                ret, frame = cap.read()
                if not ret:
                    log_json("warning", "cam-ingest", "Frame read failed — reconnecting",
                             camera=CAMERA_NAME, epoch=camera_epoch)
                    break

                # Resize if needed
                frame = resize_if_larger(frame, MAX_WIDTH, MAX_HEIGHT)
                h, w = frame.shape[:2]

                # Encode
                try:
                    jpeg_b64 = encode_frame(frame, quality=JPEG_QUALITY)
                except Exception as enc_err:
                    log_json("error", "cam-ingest", "Encode failed", error=str(enc_err))
                    frame_index += 1
                    continue

                msg = {
                    "request_id": str(uuid.uuid4()),
                    "camera_name": CAMERA_NAME,
                    "camera_epoch": str(camera_epoch),
                    "frame_index": str(frame_index),
                    "timestamp": f"{time.time():.3f}",
                    "frame_width": str(w),
                    "frame_height": str(h),
                    "jpeg_b64": jpeg_b64,
                }

                try:
                    xadd_json(r, STREAM_KEY, msg, maxlen=STREAM_MAXLEN)
                except Exception as redis_err:
                    log_json("error", "cam-ingest", "Redis publish failed", error=str(redis_err))

                frame_index += 1

            cap.release()

        except Exception as exc:
            log_json("error", "cam-ingest", "Capture loop error — retrying in 3 s",
                     error=str(exc), camera=CAMERA_NAME)
            time.sleep(3.0)


def main():
    log_json("info", "cam-ingest", "Service starting", camera=CAMERA_NAME,
             source=CAMERA_SOURCE_RAW)
    source = _parse_source(CAMERA_SOURCE_RAW)
    r = get_redis_client()
    log_json("info", "cam-ingest", "Redis connected")
    _run(r, source)


if __name__ == "__main__":
    main()
