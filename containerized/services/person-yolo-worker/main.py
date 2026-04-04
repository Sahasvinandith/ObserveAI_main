"""
person-yolo-worker/main.py

Reads raw frames from shared_raw_frames (consumer group cg::person_yolo),
runs YOLOv8 person detection, and publishes bounding boxes to
person_detections::{camera_name}.

Publishes one message per input frame even when zero persons are detected
so the downstream DeepSORT tracker can advance its Kalman filter.

Environment variables:
  REDIS_URL          Redis URL (default: redis://localhost:6379)
  YOLO_MODEL_PATH    Path to yolov8n.pt (default: yolov8n.pt)
  POD_NAME           Unique consumer name — use Kubernetes downward API.
                     Falls back to "person-yolo-worker-0".
  LOG_LEVEL          Logging level (default: info)
"""

import os
import sys
import time

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
YOLO_MODEL_PATH: str = os.environ.get("YOLO_MODEL_PATH", "yolov8n.pt")
POD_NAME: str = os.environ.get("POD_NAME", "person-yolo-worker-0")

INPUT_STREAM = "shared_raw_frames"
CONSUMER_GROUP = "cg::person_yolo"
OUTPUT_STREAM_PREFIX = "person_detections"
OUTPUT_MAXLEN = 150
PERSON_CONFIDENCE_THRESHOLD = 0.5
PERSON_CLASS_ID = 0  # COCO class for "person"

# ── Model loading ─────────────────────────────────────────────────────────────

def load_model() -> YOLO:
    log_json("info", "person-yolo-worker", "Loading YOLO model", path=YOLO_MODEL_PATH)
    model = YOLO(YOLO_MODEL_PATH)
    log_json("info", "person-yolo-worker", "YOLO model loaded")
    return model


def detect_persons(model: YOLO, frame) -> tuple[list[dict], float]:
    """
    Run YOLO inference on a BGR frame.

    Returns:
        detections: list of {"bbox_ltwh": [l,t,w,h], "confidence": float, "class_id": 0}
        inference_ms: float — wall-clock inference time
    """
    t0 = time.perf_counter()
    results = model(frame, verbose=False)
    inference_ms = (time.perf_counter() - t0) * 1000.0

    detections = []
    for r in results:
        for box in r.boxes:
            if int(box.cls[0]) != PERSON_CLASS_ID:
                continue
            conf = float(box.conf[0])
            if conf < PERSON_CONFIDENCE_THRESHOLD:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            # LTWH format — mandatory for DeepSORT
            detections.append({
                "bbox_ltwh": [x1, y1, x2 - x1, y2 - y1],
                "confidence": round(conf, 4),
                "class_id": PERSON_CLASS_ID,
            })

    return detections, inference_ms


def main():
    log_json("info", "person-yolo-worker", "Service starting", consumer=POD_NAME)
    r = get_redis_client()
    log_json("info", "person-yolo-worker", "Redis connected")

    ensure_consumer_group(r, INPUT_STREAM, CONSUMER_GROUP, start_id="$")
    model = load_model()

    log_json("info", "person-yolo-worker", "Entering processing loop")

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
                        # Decode frame
                        jpeg_b64 = fields.get("jpeg_b64", "")
                        if not jpeg_b64:
                            raise ValueError("Empty jpeg_b64 field")

                        frame = decode_frame(jpeg_b64)
                        camera_name = fields["camera_name"]

                        detections, inference_ms = detect_persons(model, frame)

                        out_stream = f"{OUTPUT_STREAM_PREFIX}::{camera_name}"
                        out_msg = {
                            "request_id": fields.get("request_id", ""),
                            "camera_name": camera_name,
                            "camera_epoch": fields.get("camera_epoch", "0"),
                            "frame_index": fields.get("frame_index", "0"),
                            "timestamp": f"{time.time():.3f}",
                            "frame_width": fields.get("frame_width", "0"),
                            "frame_height": fields.get("frame_height", "0"),
                            "detections": detections,   # xadd_json will JSON-encode this list
                            "inference_ms": f"{inference_ms:.2f}",
                        }

                        xadd_json(r, out_stream, out_msg, maxlen=OUTPUT_MAXLEN)

                        # ACK the message
                        r.xack(INPUT_STREAM, CONSUMER_GROUP, msg_id)

                        if len(detections) > 0:
                            log_json(
                                "info", "person-yolo-worker", "Frame processed",
                                camera=camera_name,
                                frame_index=fields.get("frame_index"),
                                n_detections=len(detections),
                                inference_ms=f"{inference_ms:.1f}",
                            )

                    except Exception as exc:
                        log_json("error", "person-yolo-worker", "Message processing failed",
                                 msg_id=msg_id, error=str(exc))
                        publish_to_dlq(
                            r,
                            original_stream=INPUT_STREAM,
                            original_msg_id=msg_id,
                            original_fields=fields,
                            error=exc,
                            consumer_name=POD_NAME,
                            group_name=CONSUMER_GROUP,
                        )
                        # ACK even on failure — we have routed to DLQ
                        r.xack(INPUT_STREAM, CONSUMER_GROUP, msg_id)

        except Exception as loop_exc:
            log_json("error", "person-yolo-worker", "Loop error — continuing",
                     error=str(loop_exc))
            time.sleep(0.5)


if __name__ == "__main__":
    main()
