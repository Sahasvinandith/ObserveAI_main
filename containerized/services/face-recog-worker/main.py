"""
face-recog-worker/main.py

Reads face crops from the face_crops stream (consumer group cg::face_recog),
runs ArcFace recognition against the Faces_db embedding cache, and publishes
identity results to identity_results.

Unknown handling:
  - Consecutive Unknown counter per face_id key.
  - After 3 consecutive Unknowns, assigns a new User_X identity.
  - Confirmed identities are locked after 3 consistent frames.

Listens for embedding_cache_invalidate events on the face_db_events stream
(published by face-db-writer) to reload the cache incrementally when a new
user is saved or a folder is updated.

The service queries Redis key global_id::{camera_name}::{track_id} (written by
global-tracker) to populate the global_id field in identity_results.

Environment variables:
  REDIS_URL          Redis URL (default: redis://localhost:6379)
  FACES_DB_PATH      Path to Faces_db directory (default: /app/Faces_db)
  POD_NAME           Unique consumer name. Falls back to "face-recog-worker-0".
  LOG_LEVEL          Logging level (default: info)
"""

import json
import os
import sys
import threading
import time

import cv2
import numpy as np
from deepface import DeepFace

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
POD_NAME: str = os.environ.get("POD_NAME", "face-recog-worker-0")

INPUT_STREAM = "face_crops"
CONSUMER_GROUP = "cg::face_recog"
OUTPUT_STREAM = "identity_results"
OUTPUT_MAXLEN = 500

DB_EVENTS_STREAM = "face_db_events"
DB_EVENTS_GROUP = "cg::face_recog_cache"

ARCFACE_THRESHOLD = 0.6    # matches original DetectionSystem threshold (schema §3.6)
CONFIRM_FRAMES = 3         # frames before locking identity
UNKNOWN_THRESHOLD = 3      # consecutive unknowns before creating new user
CONFIDENCE_THRESHOLD = 0.6

# ── Embedding Cache ───────────────────────────────────────────────────────────

class EmbeddingCache:
    """
    Ported directly from DataModel/EmbeddingCache.py.
    Computes averaged ArcFace embeddings for all users at startup.
    Thread-safe via RLock.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.embeddings: dict[str, np.ndarray] = {}
        self._lock = threading.RLock()
        self._computing: set[str] = set()
        os.makedirs(db_path, exist_ok=True)
        self.load_all_embeddings()

    def load_all_embeddings(self) -> None:
        log_json("info", "face-recog-worker", "Building embedding cache...",
                 db_path=self.db_path)
        with self._lock:
            self.embeddings.clear()
            if not os.path.isdir(self.db_path):
                return
            for user_folder in os.listdir(self.db_path):
                user_path = os.path.join(self.db_path, user_folder)
                if not os.path.isdir(user_path):
                    continue
                self._load_user(user_folder, user_path)
        log_json("info", "face-recog-worker", "Embedding cache built",
                 n_users=len(self.embeddings))

    def _load_user(self, user_folder: str, user_path: str) -> None:
        images = [f for f in os.listdir(user_path) if f.lower().endswith((".jpg", ".png"))]
        if not images:
            return
        embs = []
        for img_file in images:
            img_path = os.path.join(user_path, img_file)
            try:
                emb = DeepFace.represent(
                    img_path=img_path,
                    model_name="ArcFace",
                    enforce_detection=False,
                )[0]["embedding"]
                embs.append(np.array(emb))
            except Exception as exc:
                log_json("warning", "face-recog-worker", "Embedding failed for image",
                         image=img_file, error=str(exc))
        if embs:
            self.embeddings[user_folder] = np.mean(embs, axis=0)
            log_json("info", "face-recog-worker", "Cached user",
                     user=user_folder, n_images=len(embs))

    def find_match(self, face_img: np.ndarray) -> tuple[str, float]:
        """ArcFace cosine distance matching. Returns (user_id, distance)."""
        try:
            q_emb = DeepFace.represent(
                img_path=face_img,
                model_name="ArcFace",
                detector_backend="skip",
                enforce_detection=False,
            )[0]["embedding"]
            q_emb = np.array(q_emb)

            with self._lock:
                snapshot = dict(self.embeddings)

            best_name = None
            best_dist = float("inf")
            for user_name, stored in snapshot.items():
                dist = 1.0 - np.dot(q_emb, stored) / (
                    np.linalg.norm(q_emb) * np.linalg.norm(stored) + 1e-8
                )
                if dist < best_dist:
                    best_dist = dist
                    best_name = user_name

            if best_dist < ARCFACE_THRESHOLD:
                return best_name, best_dist
            return "Unknown", 1.0

        except Exception as exc:
            log_json("warning", "face-recog-worker", "Recognition error", error=str(exc))
            return "Unknown", 1.0

    def add_or_refresh_user(self, user_folder: str) -> None:
        """Reload a single user's embedding from disk."""
        user_path = os.path.join(self.db_path, user_folder)
        if not os.path.isdir(user_path):
            return
        with self._lock:
            self._load_user(user_folder, user_path)
        log_json("info", "face-recog-worker", "Cache refreshed for user", user=user_folder)

    def get_next_user_id(self) -> int:
        """Find the next available User_X number."""
        highest = 0
        if not os.path.isdir(self.db_path):
            return 1
        for item in os.listdir(self.db_path):
            if item.startswith("User_") and os.path.isdir(os.path.join(self.db_path, item)):
                try:
                    n = int(item.split("_")[1])
                    if n > highest:
                        highest = n
                except (IndexError, ValueError):
                    pass
        return highest + 1


# ── Per-face state tracking ───────────────────────────────────────────────────
# Keyed by face_id: "{camera_name}::{track_id}::{sequential_int}"
# Values are dicts with fields: name, locked_identity, unknown_count, confirm_buf, avg_conf

_face_state: dict[str, dict] = {}
_face_seq_counter: dict[str, int] = {}   # (camera_name, track_id) -> sequential int


def _get_face_id(camera_name: str, track_id: str, track_epoch: str) -> str:
    key = f"{camera_name}::{track_epoch}::{track_id}"
    if key not in _face_seq_counter:
        _face_seq_counter[key] = 0
    # We reuse the same face_id for a track; increment only for truly new detections
    return f"{camera_name}::{track_id}::{_face_seq_counter.get(key, 0)}"


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


# ── Cache invalidation listener ───────────────────────────────────────────────

def _start_cache_listener(r, cache: EmbeddingCache) -> None:
    """Background thread that listens for cache invalidation events."""
    ensure_consumer_group(r, DB_EVENTS_STREAM, DB_EVENTS_GROUP, start_id="$")

    def _listen():
        last_id = ">"
        while True:
            try:
                messages = xreadgroup_json(
                    r,
                    group=DB_EVENTS_GROUP,
                    consumer=f"{POD_NAME}-cache",
                    streams={DB_EVENTS_STREAM: last_id},
                    count=10,
                    block_ms=1000,
                )
                for _stream, entries in messages:
                    for msg_id, fields in entries:
                        event_type = fields.get("event_type", "")
                        user_folder = fields.get("user_folder", "")
                        if event_type in ("saved", "new_user") and user_folder:
                            cache.add_or_refresh_user(user_folder)
                        r.xack(DB_EVENTS_STREAM, DB_EVENTS_GROUP, msg_id)
            except Exception as exc:
                log_json("warning", "face-recog-worker", "Cache listener error", error=str(exc))
                time.sleep(1.0)

    t = threading.Thread(target=_listen, daemon=True)
    t.start()


def main():
    log_json("info", "face-recog-worker", "Service starting",
             consumer=POD_NAME, db_path=FACES_DB_PATH)
    r = get_redis_client()
    log_json("info", "face-recog-worker", "Redis connected")

    ensure_consumer_group(r, INPUT_STREAM, CONSUMER_GROUP, start_id="$")

    cache = EmbeddingCache(FACES_DB_PATH)
    _start_cache_listener(r, cache)

    log_json("info", "face-recog-worker", "Entering processing loop")

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
                        face_b64 = fields.get("face_crop_b64", "")
                        if not face_b64:
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        camera_name = fields.get("camera_name", "")
                        track_id = fields.get("track_id", "0")
                        track_epoch = fields.get("track_epoch", "0")
                        frame_index = fields.get("frame_index", "0")
                        request_id = fields.get("request_id", "")

                        face_img = decode_frame(face_b64)
                        quality_score = _calculate_face_quality(face_img)

                        # Determine face_id for this track
                        face_id = _get_face_id(camera_name, track_id, track_epoch)

                        if face_id not in _face_state:
                            _face_state[face_id] = {
                                "name": "Scanning...",
                                "locked_identity": None,
                                "unknown_count": 0,
                                "confirm_buf": [],
                                "avg_conf": 1.0,
                                "is_new_user": False,
                            }

                        state = _face_state[face_id]

                        # Run recognition
                        name, distance = cache.find_match(face_img)
                        log_json("info", "face-recog-worker", "Recognition result",
                                 face_id=face_id, name=name, dist=f"{distance:.3f}")

                        is_new_user = False

                        if name == "Unknown":
                            state["unknown_count"] = state.get("unknown_count", 0) + 1
                            if state["unknown_count"] < UNKNOWN_THRESHOLD:
                                state["name"] = "Scanning..."
                            else:
                                # Create new user
                                new_num = cache.get_next_user_id()
                                new_folder = f"User_{new_num}"
                                log_json("info", "face-recog-worker",
                                         "Creating new user", folder=new_folder)
                                state["name"] = new_folder
                                state["locked_identity"] = new_folder
                                initial_conf = max(0.1, min(0.5, 0.5 - (quality_score - 200) / 400))
                                state["avg_conf"] = initial_conf
                                state["unknown_count"] = 0
                                state["is_new_user"] = True
                                is_new_user = True
                        else:
                            # Known match
                            state["unknown_count"] = 0
                            state["confirm_buf"].append((name, distance))
                            # Keep only last CONFIRM_FRAMES
                            state["confirm_buf"] = state["confirm_buf"][-CONFIRM_FRAMES:]

                            if len(state["confirm_buf"]) >= CONFIRM_FRAMES:
                                # Check consistency
                                names_in_buf = [x[0] for x in state["confirm_buf"]]
                                if len(set(names_in_buf)) == 1:
                                    # Consistent — lock identity
                                    avg_dist = sum(x[1] for x in state["confirm_buf"]) / len(state["confirm_buf"])
                                    if avg_dist < CONFIDENCE_THRESHOLD:
                                        state["locked_identity"] = name
                                        state["avg_conf"] = avg_dist
                                        state["name"] = name

                            if state["locked_identity"]:
                                state["name"] = state["locked_identity"]
                            else:
                                state["name"] = "Scanning..."

                        # Query global_id from Redis (set by global-tracker service)
                        global_id_key = f"global_id::{camera_name}::{track_id}"
                        global_id_val = r.get(global_id_key) or ""

                        out_msg = {
                            "request_id": request_id,
                            "camera_name": camera_name,
                            "camera_epoch": fields.get("camera_epoch", "0"),
                            "frame_index": frame_index,
                            "track_id": track_id,
                            "track_epoch": track_epoch,
                            "face_id": face_id,
                            "timestamp": f"{time.time():.3f}",
                            "matched_user_id": state["name"],
                            "distance": f"{distance:.4f}",
                            "is_new_user": "true" if is_new_user else "false",
                            "quality_score": f"{quality_score:.2f}",
                            "face_crop_b64": face_b64,
                            "global_id": str(global_id_val),
                        }
                        xadd_json(r, OUTPUT_STREAM, out_msg, maxlen=OUTPUT_MAXLEN)

                        r.xack(stream_name, CONSUMER_GROUP, msg_id)

                    except Exception as exc:
                        log_json("error", "face-recog-worker", "Message processing failed",
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
            log_json("error", "face-recog-worker", "Loop error — continuing",
                     error=str(loop_exc))
            time.sleep(0.5)


if __name__ == "__main__":
    main()
