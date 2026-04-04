"""
face-db-writer/main.py

Reads from identity_results (consumer group cg::face_db_writer).
Implements quality-gated face saving:
  - Fill phase:       save up to MAX_FACES_PER_USER images unconditionally.
  - Replacement phase: save only if quality_score > current minimum on disk.

Quality score = Laplacian variance (+ other factors from calculate_face_quality).
Filename includes quality score: face_{TIMESTAMP}_q{QUALITY}.jpg

After each save or meaningful event, publishes to face_db_events stream so other
services (particularly face-recog-worker) can refresh their caches.

Environment variables:
  REDIS_URL             Redis URL (default: redis://localhost:6379)
  FACES_DB_PATH         Path to Faces_db directory (default: /app/Faces_db)
  MAX_FACES_PER_USER    Max images per user folder (default: 5)
  POD_NAME              Unique consumer name. Falls back to "face-db-writer-0".
  LOG_LEVEL             Logging level (default: info)
"""

import json
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np

_SERVICES_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SERVICES_ROOT)

from shared.redis_client import get_redis_client
from shared.image_codec import decode_frame
from shared.stream_utils import (
    xadd_json,
    xreadgroup_json,
    ensure_consumer_group,
    publish_to_dlq,
    log_json,
    parse_message,
)

# ── Configuration ─────────────────────────────────────────────────────────────
FACES_DB_PATH: str = os.environ.get("FACES_DB_PATH", "/app/Faces_db")
MAX_FACES_PER_USER: int = int(os.environ.get("MAX_FACES_PER_USER", "5"))
POD_NAME: str = os.environ.get("POD_NAME", "face-db-writer-0")

INPUT_STREAM = "identity_results"
CONSUMER_GROUP = "cg::face_db_writer"
EVENTS_STREAM = "face_db_events"
EVENTS_MAXLEN = 500
MIN_QUALITY_THRESHOLD = 50.0


# ── Quality helpers ───────────────────────────────────────────────────────────

def _calculate_face_quality(face_img: np.ndarray) -> float:
    """Ported from DataModel/face_detection.py:calculate_face_quality."""
    gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY) if len(face_img.shape) > 2 else face_img
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    hist_n = hist / (hist.sum() + 1e-8)
    entropy = float(np.sum(-hist_n * np.log2(hist_n + 1e-10)))
    size_ratio = (face_img.shape[0] * face_img.shape[1]) / (640 * 480)
    h, w = face_img.shape[:2]
    aspect = w / h if h > 0 else 0
    frontal = max(0.0, 1.0 - abs(aspect - 1.0) * 0.5)
    return lap_var * 0.4 + entropy * 30 + size_ratio * 30 + frontal * 30


def _get_existing_images(user_path: str) -> list[tuple[str, float]]:
    """
    Return list of (filepath, quality_score) for images in user_path,
    sorted by quality ascending (worst first).
    """
    images = []
    for fname in os.listdir(user_path):
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        fpath = os.path.join(user_path, fname)
        quality = 0.0
        if "_q" in fname:
            try:
                q_part = fname.split("_q")[1].split(".")[0]
                quality = float(q_part)
            except (IndexError, ValueError):
                quality = 0.0
        images.append((fpath, quality))
    images.sort(key=lambda x: x[1])  # worst first
    return images


def _save_face(
    r,
    user_folder: str,
    face_img: np.ndarray,
    quality_score: float,
    is_new_user: bool,
) -> str:
    """
    Save a face image to disk using quality-gated logic.
    Returns one of: "saved", "replaced", "skipped", "error".
    """
    user_path = os.path.join(FACES_DB_PATH, user_folder)
    os.makedirs(user_path, exist_ok=True)

    existing = _get_existing_images(user_path)
    n_existing = len(existing)

    if n_existing < MAX_FACES_PER_USER:
        # Fill phase — save unconditionally
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        fname = f"face_{ts}_q{quality_score:.1f}.jpg"
        save_path = os.path.join(user_path, fname)
        cv2.imwrite(save_path, face_img)
        log_json("info", "face-db-writer", "Saved face (fill phase)",
                 user=user_folder, quality=f"{quality_score:.1f}",
                 count=f"{n_existing + 1}/{MAX_FACES_PER_USER}")
        return "saved" if not is_new_user else "new_user"

    # Replacement phase
    if quality_score < MIN_QUALITY_THRESHOLD:
        log_json("info", "face-db-writer", "Skipped — below min quality threshold",
                 user=user_folder, quality=f"{quality_score:.1f}")
        return "skipped"

    worst_path, worst_quality = existing[0]
    if quality_score <= worst_quality:
        log_json("info", "face-db-writer", "Skipped — not better than worst on disk",
                 user=user_folder, new_q=f"{quality_score:.1f}", worst_q=f"{worst_quality:.1f}")
        return "skipped"

    # Replace worst
    try:
        os.remove(worst_path)
    except OSError:
        pass
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    fname = f"face_{ts}_q{quality_score:.1f}.jpg"
    save_path = os.path.join(user_path, fname)
    cv2.imwrite(save_path, face_img)
    log_json("info", "face-db-writer", "Replaced low-quality face",
             user=user_folder, new_q=f"{quality_score:.1f}", old_q=f"{worst_quality:.1f}")
    return "replaced"


def main():
    log_json("info", "face-db-writer", "Service starting",
             consumer=POD_NAME, db_path=FACES_DB_PATH, max_faces=str(MAX_FACES_PER_USER))
    os.makedirs(FACES_DB_PATH, exist_ok=True)
    r = get_redis_client()
    log_json("info", "face-db-writer", "Redis connected")

    ensure_consumer_group(r, INPUT_STREAM, CONSUMER_GROUP, start_id="$")

    log_json("info", "face-db-writer", "Entering processing loop")

    while True:
        try:
            messages = xreadgroup_json(
                r,
                group=CONSUMER_GROUP,
                consumer=POD_NAME,
                streams={INPUT_STREAM: ">"},
                count=4,
                block_ms=100,
            )

            for stream_name, entries in messages:
                for msg_id, fields in entries:
                    fields = parse_message(fields)
                    try:
                        matched_user_id = fields.get("matched_user_id", "")
                        is_new_user_str = fields.get("is_new_user", "false")
                        is_new_user = is_new_user_str.lower() == "true"

                        # Only process known / new users — skip Scanning and Unknown
                        if matched_user_id in ("Unknown", "Scanning...", ""):
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        face_b64 = fields.get("face_crop_b64", "")
                        if not face_b64:
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        face_img = decode_frame(face_b64)

                        # Use pre-computed quality from face-recog-worker when available
                        try:
                            quality_score = float(fields.get("quality_score", "0"))
                        except (ValueError, TypeError):
                            quality_score = 0.0
                        if quality_score == 0.0:
                            quality_score = _calculate_face_quality(face_img)

                        result = _save_face(
                            r,
                            user_folder=matched_user_id,
                            face_img=face_img,
                            quality_score=quality_score,
                            is_new_user=is_new_user,
                        )

                        # Publish event for cache invalidation
                        if result in ("saved", "replaced", "new_user"):
                            event_msg = {
                                "event_type": result,
                                "user_folder": matched_user_id,
                                "quality_score": f"{quality_score:.2f}",
                                "camera_name": fields.get("camera_name", ""),
                                "track_id": fields.get("track_id", ""),
                                "timestamp": f"{time.time():.3f}",
                            }
                            xadd_json(r, EVENTS_STREAM, event_msg, maxlen=EVENTS_MAXLEN)

                        r.xack(stream_name, CONSUMER_GROUP, msg_id)

                    except Exception as exc:
                        log_json("error", "face-db-writer", "Message processing failed",
                                 msg_id=msg_id, error=str(exc))
                        publish_to_dlq(
                            r,
                            original_stream=stream_name,
                            original_msg_id=msg_id,
                            original_fields=fields,
                            error=exc,
                            consumer_name=POD_NAME,
                            group_name=CONSUMER_GROUP,
                        )
                        r.xack(stream_name, CONSUMER_GROUP, msg_id)

        except Exception as loop_exc:
            log_json("error", "face-db-writer", "Loop error — continuing",
                     error=str(loop_exc))
            time.sleep(0.5)


if __name__ == "__main__":
    main()
