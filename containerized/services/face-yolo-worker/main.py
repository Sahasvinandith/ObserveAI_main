"""
face-yolo-worker/main.py

Reads confirmed person tracks from person_tracks::{camera_name} (consumer group
cg::face_yolo), runs YOLOv11n-face detection on the person crop, and publishes
face crops to the face_crops stream.

Size gate: face width < 70 OR height < 90 => drop silently.

Skips messages where person_crop_b64 is empty (person too small).

Environment variables:
  REDIS_URL          Redis URL (default: redis://localhost:6379)
  YOLO_MODEL_PATH    Path to yolov11n-face.pt (default: yolov11n-face.pt)
  CAMERA_NAME        Camera identifier (used to build the input stream key).
                     If empty, the worker subscribes to ALL camera track streams
                     by reading camera_name from each message.
                     In practice, deploy one pod per camera with CAMERA_NAME set.
  POD_NAME           Unique consumer name. Falls back to "face-yolo-worker-0".
  LOG_LEVEL          Logging level (default: info)
"""

import json
import os
import sys
import time

from ultralytics import YOLO

_SERVICES_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SERVICES_ROOT)

from shared.redis_client import get_redis_client
from shared.image_codec import decode_frame, encode_frame
from shared.stream_utils import (
    xadd_json,
    xreadgroup_json,
    ensure_consumer_group,
    publish_to_dlq,
    log_json,
    parse_message,
)

# ── Configuration ─────────────────────────────────────────────────────────────
YOLO_MODEL_PATH: str = os.environ.get("YOLO_MODEL_PATH", "yolov11n-face.pt")
CAMERA_NAME: str = os.environ.get("CAMERA_NAME", "")
POD_NAME: str = os.environ.get("POD_NAME", "face-yolo-worker-0")

CONSUMER_GROUP = "cg::face_yolo"
OUTPUT_STREAM = "face_crops"
OUTPUT_MAXLEN = 200
JPEG_QUALITY = 95

# Size gate (mirrors MIN_FACE_SIZE from DetectionSystem)
MIN_FACE_W = 70
MIN_FACE_H = 90
FACE_YOLO_CONF = 0.5


def get_input_streams(camera_name: str) -> list[str]:
    """Return the list of input stream keys this pod subscribes to."""
    if camera_name:
        return [f"person_tracks::{camera_name}"]
    # Fallback: worker will need camera_name from each message
    # (not recommended in production — use CAMERA_NAME env var)
    return []


def load_model() -> YOLO:
    log_json("info", "face-yolo-worker", "Loading face YOLO model", path=YOLO_MODEL_PATH)
    model = YOLO(YOLO_MODEL_PATH)
    log_json("info", "face-yolo-worker", "Face YOLO model loaded")
    return model


def main():
    log_json("info", "face-yolo-worker", "Service starting",
             camera=CAMERA_NAME or "any", consumer=POD_NAME)
    r = get_redis_client()
    log_json("info", "face-yolo-worker", "Redis connected")

    input_streams = get_input_streams(CAMERA_NAME)
    if not input_streams:
        log_json("error", "face-yolo-worker",
                 "CAMERA_NAME env var is required. Set it to the camera to track.")
        sys.exit(1)

    for stream in input_streams:
        ensure_consumer_group(r, stream, CONSUMER_GROUP, start_id="$")

    model = load_model()

    log_json("info", "face-yolo-worker", "Entering processing loop",
             streams=input_streams)

    while True:
        try:
            stream_args = {s: ">" for s in input_streams}
            messages = xreadgroup_json(
                r,
                group=CONSUMER_GROUP,
                consumer=POD_NAME,
                streams=stream_args,
                count=8,
                block_ms=100,
            )

            for stream_name, entries in messages:
                for msg_id, fields in entries:
                    fields = parse_message(fields)
                    try:
                        person_crop_b64 = fields.get("person_crop_b64", "")
                        if not person_crop_b64:
                            # Person crop below minimum size — skip
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        camera_name = fields.get("camera_name", CAMERA_NAME)
                        track_id = fields.get("track_id", "0")
                        track_epoch = fields.get("track_epoch", "0")
                        frame_index = fields.get("frame_index", "0")
                        request_id = fields.get("request_id", "")

                        # Decode person crop
                        person_crop = decode_frame(person_crop_b64)
                        ph, pw = person_crop.shape[:2]

                        # Person bbox in full frame (LTRB)
                        bbox_ltrb_raw = fields.get("bbox_ltrb", "[0,0,0,0]")
                        if isinstance(bbox_ltrb_raw, str):
                            bbox_ltrb = json.loads(bbox_ltrb_raw)
                        else:
                            bbox_ltrb = bbox_ltrb_raw
                        person_left = bbox_ltrb[0] if len(bbox_ltrb) >= 4 else 0
                        person_top = bbox_ltrb[1] if len(bbox_ltrb) >= 4 else 0

                        # Run face detection
                        t0 = time.perf_counter()
                        results = model(person_crop, verbose=False)
                        inference_ms = (time.perf_counter() - t0) * 1000.0

                        faces_published = 0
                        for r_item in results:
                            for box in r_item.boxes:
                                yolo_conf = float(box.conf[0]) if box.conf is not None else 0.0
                                if yolo_conf < FACE_YOLO_CONF:
                                    continue

                                lx1, ly1, lx2, ly2 = map(int, box.xyxy[0])
                                face_w = lx2 - lx1
                                face_h = ly2 - ly1

                                # Size gate
                                if face_w < MIN_FACE_W or face_h < MIN_FACE_H:
                                    continue

                                # Global coordinates
                                gx = person_left + lx1
                                gy = person_top + ly1

                                # Crop face from person crop
                                face_crop = person_crop[
                                    max(0, ly1): min(ph, ly2),
                                    max(0, lx1): min(pw, lx2),
                                ]
                                if face_crop.size == 0:
                                    continue

                                face_b64 = encode_frame(face_crop, quality=JPEG_QUALITY)

                                out_msg = {
                                    "request_id": request_id,
                                    "camera_name": camera_name,
                                    "camera_epoch": fields.get("camera_epoch", "0"),
                                    "frame_index": frame_index,
                                    "track_id": track_id,
                                    "track_epoch": track_epoch,
                                    "timestamp": f"{time.time():.3f}",
                                    "face_bbox_in_person": json.dumps([lx1, ly1, face_w, face_h]),
                                    "face_bbox_global": json.dumps([gx, gy, face_w, face_h]),
                                    "face_width": str(face_w),
                                    "face_height": str(face_h),
                                    "yolo_confidence": f"{yolo_conf:.4f}",
                                    "face_crop_b64": face_b64,
                                }
                                xadd_json(r, OUTPUT_STREAM, out_msg, maxlen=OUTPUT_MAXLEN)
                                faces_published += 1

                        r.xack(stream_name, CONSUMER_GROUP, msg_id)

                        if faces_published > 0:
                            log_json("info", "face-yolo-worker", "Faces detected",
                                     camera=camera_name, track_id=track_id,
                                     n_faces=faces_published,
                                     inference_ms=f"{inference_ms:.1f}")

                    except Exception as exc:
                        log_json("error", "face-yolo-worker", "Message processing failed",
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
            log_json("error", "face-yolo-worker", "Loop error — continuing",
                     error=str(loop_exc))
            time.sleep(0.5)


if __name__ == "__main__":
    main()
