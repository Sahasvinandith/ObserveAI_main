"""
action-pose-worker/main.py

Reads confirmed person tracks from person_tracks::{CAMERA_NAME} (consumer group
cg::action_detect), runs YOLOv8-Pose estimation, and compares keypoints against
reference actions loaded from /app/Actions_db/.

Action matching uses normalised Euclidean distance on YOLO keypoints (same logic
as DetectionSystem.process_actions()).  Threshold: 0.10.

Cooldown: Redis key cooldown::{camera_name}::{track_id}::{action_name} with 5 s TTL.

Publishes matched actions to action_events stream.

Environment variables:
  REDIS_URL          Redis URL (default: redis://localhost:6379)
  CAMERA_NAME        Camera identifier — determines input stream key.
  ACTIONS_DB_PATH    Path to Actions_db directory (default: /app/Actions_db)
  POSE_MODEL_PATH    Path to yolov8n-pose.pt (default: yolov8n-pose.pt)
  POD_NAME           Unique consumer name. Falls back to "action-pose-worker-0".
  LOG_LEVEL          Logging level (default: info)
"""

import json
import os
import sys
import time

import numpy as np
from ultralytics import YOLO

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
CAMERA_NAME: str = os.environ.get("CAMERA_NAME", "")
ACTIONS_DB_PATH: str = os.environ.get("ACTIONS_DB_PATH", "/app/Actions_db")
POSE_MODEL_PATH: str = os.environ.get("POSE_MODEL_PATH", "yolov8n-pose.pt")
POD_NAME: str = os.environ.get("POD_NAME", "action-pose-worker-0")

CONSUMER_GROUP = "cg::action_detect"
OUTPUT_STREAM = "action_events"
OUTPUT_MAXLEN = 200
ACTION_THRESHOLD = 0.10
ACTION_COOLDOWN_TTL = 5   # seconds (Redis key TTL)


# ── Action loading ────────────────────────────────────────────────────────────

def load_actions(db_path: str) -> dict[str, dict]:
    """
    Load all JSON action reference files from db_path.
    Identical to ActionManager.load_all_actions().
    Returns {action_name: pose_data_dict}.
    """
    actions: dict[str, dict] = {}
    if not os.path.isdir(db_path):
        log_json("warning", "action-pose-worker", "Actions_db not found", path=db_path)
        return actions

    for fname in os.listdir(db_path):
        if not fname.endswith(".json"):
            continue
        action_name = fname[:-5]
        fpath = os.path.join(db_path, fname)
        try:
            with open(fpath, "r") as f:
                data = json.load(f)
            actions[action_name] = data
            log_json("info", "action-pose-worker", "Loaded action", action=action_name)
        except Exception as exc:
            log_json("warning", "action-pose-worker", "Failed to load action",
                     file=fname, error=str(exc))
    return actions


def _extract_ref_marks(ref_data: dict) -> np.ndarray | None:
    """
    Extract reference landmarks from action JSON.
    Supports both dict format (new pose_creator) and list format (legacy).
    Returns (17, 3) numpy array or None.
    """
    raw = ref_data.get("landmarks")
    if raw is None:
        return None

    if isinstance(raw, dict):
        marks = []
        for i in range(17):
            pt = raw.get(str(i), {"x": 0, "y": 0, "z": 0})
            marks.append([pt.get("x", 0), pt.get("y", 0), pt.get("z", 0)])
        return np.array(marks)
    else:
        arr = np.array(raw)
        return arr[:17] if len(arr) >= 17 else None


def compare_pose(
    detected_kpts: np.ndarray,     # (17, 3)
    ref_marks: np.ndarray,          # (17, 3)
    active_indices: list[int],
) -> float:
    """
    Normalised Euclidean distance over active keypoints.
    Matches process_actions() logic.  Lower = closer match.
    """
    active_indices = [i for i in active_indices if i < 17]
    if not active_indices:
        return 1.0
    current_active = np.array([detected_kpts[i] for i in active_indices])
    ref_active = np.array([ref_marks[i] for i in active_indices])
    dist = np.linalg.norm(current_active - ref_active) / len(active_indices)
    return float(dist)


def main():
    if not CAMERA_NAME:
        log_json("error", "action-pose-worker",
                 "CAMERA_NAME env var is required.")
        sys.exit(1)

    input_stream = f"person_tracks::{CAMERA_NAME}"
    log_json("info", "action-pose-worker", "Service starting",
             camera=CAMERA_NAME, consumer=POD_NAME)

    r = get_redis_client()
    log_json("info", "action-pose-worker", "Redis connected")

    ensure_consumer_group(r, input_stream, CONSUMER_GROUP, start_id="$")

    log_json("info", "action-pose-worker", "Loading YOLO Pose model", path=POSE_MODEL_PATH)
    pose_model = YOLO(POSE_MODEL_PATH)
    log_json("info", "action-pose-worker", "Pose model loaded")

    reference_actions = load_actions(ACTIONS_DB_PATH)
    if not reference_actions:
        log_json("warning", "action-pose-worker",
                 "No reference actions loaded — worker will process pose but never match.")

    log_json("info", "action-pose-worker", "Entering processing loop",
             stream=input_stream, n_actions=len(reference_actions))

    while True:
        try:
            messages = xreadgroup_json(
                r,
                group=CONSUMER_GROUP,
                consumer=POD_NAME,
                streams={input_stream: ">"},
                count=8,
                block_ms=100,
            )

            for stream_name, entries in messages:
                for msg_id, fields in entries:
                    fields = parse_message(fields)
                    try:
                        person_crop_b64 = fields.get("person_crop_b64", "")
                        if not person_crop_b64:
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        camera_name = fields.get("camera_name", CAMERA_NAME)
                        track_id = fields.get("track_id", "0")
                        frame_index = fields.get("frame_index", "0")
                        request_id = fields.get("request_id", "")

                        crop = decode_frame(person_crop_b64)
                        ch, cw = crop.shape[:2]

                        # Minimum crop gate (same as DetectionSystem: w>50, h>100 for pose)
                        if cw < 50 or ch < 100:
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        # Run pose estimation
                        pose_results = pose_model(crop, verbose=False)

                        if (
                            not pose_results
                            or pose_results[0].keypoints is None
                            or len(pose_results[0].keypoints.data) == 0
                        ):
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        # Extract normalised keypoints [17, 2] -> [17, 3]
                        kpts_xyn = pose_results[0].keypoints.xyn[0].cpu().numpy()
                        landmarks = np.zeros((17, 3))
                        landmarks[:, :2] = kpts_xyn

                        keypoints_list = kpts_xyn.tolist()

                        # Query global_id
                        global_id_val = r.get(f"global_id::{camera_name}::{track_id}") or ""

                        # Compare against all reference actions
                        for act_name, ref_data in reference_actions.items():
                            ref_marks = _extract_ref_marks(ref_data)
                            if ref_marks is None:
                                continue
                            if ref_marks.shape != landmarks.shape:
                                continue

                            active_indices = ref_data.get("active_keypoints", list(range(17)))
                            dist = compare_pose(landmarks, ref_marks, active_indices)

                            if dist >= ACTION_THRESHOLD:
                                continue

                            # Check cooldown via Redis TTL key
                            cooldown_key = f"cooldown::{camera_name}::{track_id}::{act_name}"
                            already_cooling = r.exists(cooldown_key)
                            if already_cooling:
                                continue

                            # Set cooldown
                            r.setex(cooldown_key, ACTION_COOLDOWN_TTL, "1")

                            # Determine person display name
                            person_name_key = f"identity::{camera_name}::{track_id}"
                            person_name = r.get(person_name_key) or "Unknown"

                            out_msg = {
                                "request_id": request_id,
                                "camera_name": camera_name,
                                "camera_epoch": fields.get("camera_epoch", "0"),
                                "frame_index": frame_index,
                                "track_id": track_id,
                                "timestamp": f"{time.time():.3f}",
                                "action_name": act_name,
                                "person_name": str(person_name),
                                "global_id": str(global_id_val),
                                "pose_distance": f"{dist:.4f}",
                                "keypoints_json": json.dumps(keypoints_list),
                            }
                            xadd_json(r, OUTPUT_STREAM, out_msg, maxlen=OUTPUT_MAXLEN)

                            log_json("info", "action-pose-worker", "Action detected",
                                     camera=camera_name, track=track_id,
                                     action=act_name, dist=f"{dist:.4f}")

                        r.xack(stream_name, CONSUMER_GROUP, msg_id)

                    except Exception as exc:
                        log_json("error", "action-pose-worker", "Message processing failed",
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
            log_json("error", "action-pose-worker", "Loop error — continuing",
                     error=str(loop_exc))
            time.sleep(0.5)


if __name__ == "__main__":
    main()
