"""
global-tracker/main.py

Singleton global person tracker service.

Reads Re-ID feature updates from reid_features via plain XREAD BLOCK (no consumer
group — singleton, must see every update).

Reads identity assignments from identity_results via consumer group
cg::global_tracker_identity so other consumers are not blocked.

Maintains GlobalPersonTracker state (EMA feature blending, cosine matching) ported
directly from DataModel/GlobalPersonTracker.py.

Exposes results via FastAPI:
  GET /global_persons   — snapshot of all tracked persons
  GET /health           — liveness probe

Persists global person state to Redis Hash global_persons::{global_id} for
crash recovery.

Writes Redis key global_id::{camera_name}::{track_id} = global_id so that
face-recog-worker and action-pose-worker can tag their output messages.

Environment variables:
  REDIS_URL      Redis URL (default: redis://localhost:6379)
  HTTP_PORT      Port for the HTTP API (default: 8080)
  LOG_LEVEL      Logging level (default: info)
"""

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

_SERVICES_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SERVICES_ROOT)

from shared.redis_client import get_redis_client
from shared.stream_utils import (
    ensure_consumer_group,
    xreadgroup_json,
    log_json,
    parse_message,
)

# ── Configuration ─────────────────────────────────────────────────────────────
HTTP_PORT: int = int(os.environ.get("HTTP_PORT", "8080"))
CONSUMER_NAME = "global-tracker-0"

REID_STREAM = "reid_features"
IDENTITY_STREAM = "identity_results"
IDENTITY_GROUP = "cg::global_tracker_identity"

FEATURE_THRESHOLD = 0.4
REID_WEIGHT = 0.5
COLOR_WEIGHT = 0.3
SPATIAL_WEIGHT = 0.2

STALE_TRACK_TTL = 30.0   # seconds before a global person is forgotten
GLOBAL_ID_KEY_TTL = 60   # seconds for global_id::{cam}::{track} Redis key

# ── Data structures (ported from GlobalPersonTracker.py) ──────────────────────

@dataclass
class LocalTrack:
    camera_name: str
    local_person_id: str
    feature_vector: Optional[np.ndarray] = None
    color_hist: Optional[np.ndarray] = None
    last_seen: float = field(default_factory=time.time)
    bbox: Optional[List[int]] = None

    def update(
        self,
        feature_vector: Optional[np.ndarray] = None,
        color_hist: Optional[np.ndarray] = None,
        bbox: Optional[List[int]] = None,
    ) -> None:
        alpha = 0.15
        if feature_vector is not None:
            if self.feature_vector is None:
                self.feature_vector = feature_vector.copy()
            else:
                blended = (1.0 - alpha) * self.feature_vector + alpha * feature_vector
                self.feature_vector = blended / (np.linalg.norm(blended) + 1e-8)
        if color_hist is not None:
            if self.color_hist is None:
                self.color_hist = color_hist.copy()
            else:
                self.color_hist = (1.0 - alpha) * self.color_hist + alpha * color_hist
        if bbox is not None:
            self.bbox = bbox
        self.last_seen = time.time()


@dataclass
class GlobalPerson:
    global_id: int
    feature_vector: Optional[np.ndarray] = None
    color_hist: Optional[np.ndarray] = None
    color_hist_count: int = 0
    camera_tracks: Dict[str, LocalTrack] = field(default_factory=dict)
    local_user_id: str = "Unknown"
    best_confidence: float = 1.0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def update_from_camera(
        self,
        camera_name: str,
        local_id: str,
        feature_vector: Optional[np.ndarray],
        color_hist: Optional[np.ndarray],
        bbox: Optional[List[int]],
    ) -> None:
        if camera_name in self.camera_tracks:
            self.camera_tracks[camera_name].update(feature_vector, color_hist, bbox)
        else:
            self.camera_tracks[camera_name] = LocalTrack(
                camera_name=camera_name,
                local_person_id=local_id,
                feature_vector=feature_vector,
                color_hist=color_hist,
                bbox=bbox,
            )

        # EMA blend global features
        alpha = max(0.10, 1.0 / (self.color_hist_count + 1))
        if feature_vector is not None:
            if self.feature_vector is None:
                self.feature_vector = feature_vector.copy()
            else:
                blended = (1.0 - alpha) * self.feature_vector + alpha * feature_vector
                self.feature_vector = blended / (np.linalg.norm(blended) + 1e-8)
        if color_hist is not None:
            if self.color_hist is None:
                self.color_hist = color_hist.copy()
                self.color_hist_count = 1
            else:
                self.color_hist = (1.0 - alpha) * self.color_hist + alpha * color_hist
                self.color_hist_count += 1

        self.last_seen = time.time()

    def update_identity(self, user_id: str, confidence: float) -> None:
        if user_id in ("Unknown", "Scanning..."):
            return
        if confidence < self.best_confidence:
            self.local_user_id = user_id
            self.best_confidence = confidence

    def as_dict(self) -> dict:
        return {
            "global_id": self.global_id,
            "local_user_id": self.local_user_id,
            "best_confidence": round(self.best_confidence, 4),
            "cameras": list(self.camera_tracks.keys()),
            "first_seen": round(self.first_seen, 3),
            "last_seen": round(self.last_seen, 3),
        }


class GlobalPersonTracker:
    """
    Ported core logic from DataModel/GlobalPersonTracker.py.
    Cosine Re-ID + color histogram matching with EMA blending.
    """

    def __init__(
        self,
        feature_threshold: float = FEATURE_THRESHOLD,
        reid_weight: float = REID_WEIGHT,
        color_weight: float = COLOR_WEIGHT,
        spatial_weight: float = SPATIAL_WEIGHT,
    ):
        self.global_persons: Dict[int, GlobalPerson] = {}
        self.next_id: int = 1
        self.feature_threshold = feature_threshold
        self.reid_weight = reid_weight
        self.color_weight = color_weight
        self.spatial_weight = spatial_weight
        self.lock = threading.Lock()

    def _cosine_distance(self, v1: np.ndarray, v2: np.ndarray) -> float:
        try:
            v1n = v1 / (np.linalg.norm(v1) + 1e-8)
            v2n = v2 / (np.linalg.norm(v2) + 1e-8)
            return float(1.0 - np.dot(v1n, v2n))
        except Exception:
            return 999.0

    def _color_distance(self, h1: np.ndarray, h2: np.ndarray) -> float:
        if h1 is None or h2 is None:
            return 0.5
        try:
            h1f = h1.astype(np.float32)
            h2f = h2.astype(np.float32)
            return float(cv2.compareHist(h1f, h2f, cv2.HISTCMP_BHATTACHARYYA))
        except Exception:
            return 0.5

    def _find_match(
        self,
        feature_vector: np.ndarray,
        color_hist: Optional[np.ndarray],
        exclude_camera: str,
        current_local_id: str,
    ) -> Optional[int]:
        """Called with self.lock already held."""
        if feature_vector is None:
            return None

        best_id = None
        best_dist = float("inf")

        for gp in self.global_persons.values():
            if gp.feature_vector is None:
                continue

            # Skip if actively tracked in the same camera recently
            if exclude_camera in gp.camera_tracks:
                track_age = time.time() - gp.camera_tracks[exclude_camera].last_seen
                if track_age < 1.0:
                    continue

            reid_dist = self._cosine_distance(feature_vector, gp.feature_vector)

            # Also check per-camera track distances
            for t in gp.camera_tracks.values():
                if t.feature_vector is not None:
                    d = self._cosine_distance(feature_vector, t.feature_vector)
                    if d < reid_dist:
                        reid_dist = d

            color_dist = 0.5
            if color_hist is not None and gp.color_hist is not None:
                color_dist = self._color_distance(color_hist, gp.color_hist)

            combined = (
                self.reid_weight * reid_dist
                + self.color_weight * color_dist
                + self.spatial_weight * 0.5  # neutral spatial — no map data in this service
            )

            if combined < best_dist:
                best_dist = combined
                best_id = gp.global_id

        if best_dist < self.feature_threshold:
            return best_id
        return None

    def create_or_update(
        self,
        camera_name: str,
        local_id: str,
        feature_vector: Optional[np.ndarray],
        color_hist: Optional[np.ndarray],
        bbox: Optional[List[int]],
    ) -> int:
        with self.lock:
            matched_id = self._find_match(feature_vector, color_hist, camera_name, local_id)

            if matched_id is not None:
                self.global_persons[matched_id].update_from_camera(
                    camera_name, local_id, feature_vector, color_hist, bbox
                )
                return matched_id
            else:
                new_id = self.next_id
                self.next_id += 1
                gp = GlobalPerson(global_id=new_id)
                gp.update_from_camera(camera_name, local_id, feature_vector, color_hist, bbox)
                self.global_persons[new_id] = gp
                log_json("info", "global-tracker", "New global person",
                         global_id=new_id, camera=camera_name, local_id=local_id)
                return new_id

    def update_identity(self, global_id: int, user_id: str, confidence: float) -> None:
        with self.lock:
            if global_id in self.global_persons:
                self.global_persons[global_id].update_identity(user_id, confidence)

    def get_snapshot(self) -> list[dict]:
        with self.lock:
            return [gp.as_dict() for gp in self.global_persons.values()]

    def evict_stale(self, ttl: float = STALE_TRACK_TTL) -> None:
        now = time.time()
        with self.lock:
            stale = [gid for gid, gp in self.global_persons.items()
                     if now - gp.last_seen > ttl]
            for gid in stale:
                del self.global_persons[gid]
                log_json("info", "global-tracker", "Evicted stale person", global_id=gid)

    def persist_to_redis(self, r) -> None:
        """Write all global persons to Redis Hashes for crash recovery."""
        with self.lock:
            snapshot = list(self.global_persons.values())
        for gp in snapshot:
            key = f"global_persons::{gp.global_id}"
            r.hset(key, mapping={
                "local_user_id": gp.local_user_id,
                "best_confidence": str(gp.best_confidence),
                "cameras": json.dumps(list(gp.camera_tracks.keys())),
                "first_seen": str(gp.first_seen),
                "last_seen": str(gp.last_seen),
            })


# ── Shared tracker instance ───────────────────────────────────────────────────
_tracker = GlobalPersonTracker()

# ── Background processing threads ─────────────────────────────────────────────

def _parse_vec(raw) -> Optional[np.ndarray]:
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    return np.array(raw, dtype=np.float32)


def _reid_reader_loop(r) -> None:
    """
    Reads from reid_features via plain XREAD BLOCK (singleton — no consumer group).
    Updates GlobalPersonTracker with new feature vectors.
    Also writes global_id::{camera}::{track} keys for other services.
    """
    last_id = "$"
    log_json("info", "global-tracker", "Reid reader started")

    while True:
        try:
            results = r.xread({REID_STREAM: last_id}, count=20, block=100)
            if not results:
                continue

            for _stream, entries in results:
                for msg_id, fields in entries:
                    last_id = msg_id
                    try:
                        camera_name = fields.get("camera_name", "")
                        track_id = fields.get("track_id", "")
                        track_epoch = fields.get("track_epoch", "0")
                        feature_raw = fields.get("feature_vector", "")
                        color_raw = fields.get("color_hist", "")

                        feat = _parse_vec(feature_raw)
                        color = _parse_vec(color_raw)

                        bbox_raw = fields.get("bbox_ltrb", "")
                        bbox = None
                        if bbox_raw:
                            if isinstance(bbox_raw, str):
                                try:
                                    bbox = json.loads(bbox_raw)
                                except Exception:
                                    pass
                            else:
                                bbox = bbox_raw

                        global_id = _tracker.create_or_update(
                            camera_name=camera_name,
                            local_id=track_id,
                            feature_vector=feat,
                            color_hist=color,
                            bbox=bbox,
                        )

                        # Write global_id lookup key for other services
                        key = f"global_id::{camera_name}::{track_id}"
                        r.setex(key, GLOBAL_ID_KEY_TTL, str(global_id))

                    except Exception as exc:
                        log_json("error", "global-tracker", "Reid message error",
                                 msg_id=msg_id, error=str(exc))

        except Exception as loop_exc:
            log_json("error", "global-tracker", "Reid reader loop error",
                     error=str(loop_exc))
            time.sleep(0.5)


def _identity_reader_loop(r) -> None:
    """
    Reads identity_results via consumer group to update face identities
    on global persons without competing with face-db-writer.
    """
    ensure_consumer_group(r, IDENTITY_STREAM, IDENTITY_GROUP, start_id="$")
    log_json("info", "global-tracker", "Identity reader started")

    while True:
        try:
            messages = xreadgroup_json(
                r,
                group=IDENTITY_GROUP,
                consumer=CONSUMER_NAME,
                streams={IDENTITY_STREAM: ">"},
                count=10,
                block_ms=200,
            )

            for _stream, entries in messages:
                for msg_id, fields in entries:
                    fields = parse_message(fields)
                    try:
                        camera_name = fields.get("camera_name", "")
                        track_id = fields.get("track_id", "")
                        matched_user_id = fields.get("matched_user_id", "")
                        distance_str = fields.get("distance", "1.0")
                        confidence = float(distance_str) if distance_str != "-1.0" else 1.0

                        # Look up global_id for this track
                        gid_raw = r.get(f"global_id::{camera_name}::{track_id}")
                        if gid_raw:
                            global_id = int(gid_raw)
                            _tracker.update_identity(global_id, matched_user_id, confidence)

                            # Write identity key for action-pose-worker
                            identity_key = f"identity::{camera_name}::{track_id}"
                            r.setex(identity_key, GLOBAL_ID_KEY_TTL, matched_user_id)

                        r.xack(IDENTITY_STREAM, IDENTITY_GROUP, msg_id)

                    except Exception as exc:
                        log_json("error", "global-tracker", "Identity message error",
                                 msg_id=msg_id, error=str(exc))
                        r.xack(IDENTITY_STREAM, IDENTITY_GROUP, msg_id)

        except Exception as loop_exc:
            log_json("error", "global-tracker", "Identity reader loop error",
                     error=str(loop_exc))
            time.sleep(0.5)


def _maintenance_loop(r) -> None:
    """Periodically evict stale persons and persist state to Redis."""
    while True:
        try:
            time.sleep(5.0)
            _tracker.evict_stale()
            _tracker.persist_to_redis(r)
        except Exception as exc:
            log_json("error", "global-tracker", "Maintenance error", error=str(exc))


# ── FastAPI application ───────────────────────────────────────────────────────
app = FastAPI(title="ObserveAI Global Tracker")


@app.get("/health")
def health():
    return {"status": "ok", "ts": time.time()}


@app.get("/global_persons")
def get_global_persons():
    snapshot = _tracker.get_snapshot()
    return JSONResponse(content={"global_persons": snapshot, "count": len(snapshot)})


@app.get("/global_persons/{global_id}")
def get_global_person(global_id: int):
    with _tracker.lock:
        gp = _tracker.global_persons.get(global_id)
    if gp is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return gp.as_dict()


def main():
    log_json("info", "global-tracker", "Service starting", http_port=str(HTTP_PORT))
    r = get_redis_client()
    log_json("info", "global-tracker", "Redis connected")

    # Start background threads
    threading.Thread(target=_reid_reader_loop, args=(r,), daemon=True, name="reid-reader").start()
    threading.Thread(target=_identity_reader_loop, args=(r,), daemon=True, name="identity-reader").start()
    threading.Thread(target=_maintenance_loop, args=(r,), daemon=True, name="maintenance").start()

    log_json("info", "global-tracker", "Background threads started — launching HTTP server")
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
