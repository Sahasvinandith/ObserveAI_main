"""
reid-feature-worker/main.py

Reads confirmed person tracks from person_tracks::{camera_name} (consumer group
cg::reid_extract), extracts a 2048-dim L2-normalized Re-ID feature vector and a
512-element HSV color histogram using the ResNet-50 backbone from Reid_model.py.
Publishes results to reid_features.

Skips messages where person_crop_b64 is empty.
Skips crops below MIN_CROP_W x MIN_CROP_H (100 x 200 px).

Environment variables:
  REDIS_URL      Redis URL (default: redis://localhost:6379)
  CAMERA_NAME    Camera identifier — determines input stream key.
  POD_NAME       Unique consumer name. Falls back to "reid-feature-worker-0".
  LOG_LEVEL      Logging level (default: info)
"""

import json
import os
import sys
import time

import cv2
import numpy as np
import torch
from torchvision.transforms import transforms

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
POD_NAME: str = os.environ.get("POD_NAME", "reid-feature-worker-0")

CONSUMER_GROUP = "cg::reid_extract"
OUTPUT_STREAM = "reid_features"
OUTPUT_MAXLEN = 200

MIN_CROP_W = 100
MIN_CROP_H = 200
WARMUP_FRAMES = 5   # number of crops to collect before first feature extraction

# Per-track warmup state (in-process; resets on pod restart)
# key: (camera_name, track_epoch, track_id)  value: list of (area, crop)
_warmup_buffers: dict[tuple, list] = {}
# Per-track refresh counter
_refresh_counters: dict[tuple, int] = {}
REFRESH_EVERY = 30   # emit updated features every N frames for the same track

# ── Model initialization ──────────────────────────────────────────────────────

def _build_reid_model():
    """Build ResNet-50 Re-ID model identical to DataModel/Reid_model.py."""
    import torch.nn as nn

    try:
        model = torch.hub.load(
            "pytorch/vision:v0.10.0", "resnet50", pretrained=True
        )
    except Exception:
        # Offline fallback: load from torchvision directly
        import torchvision.models as tv_models
        model = tv_models.resnet50(weights=tv_models.ResNet50_Weights.DEFAULT)

    model.fc = torch.nn.Identity()
    return model


_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

log_json("info", "reid-feature-worker", "Loading Re-ID model...")
_reid_model = _build_reid_model().to(_device)
_reid_model.eval()
log_json("info", "reid-feature-worker", "Re-ID model loaded", device=str(_device))

_preprocess = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((256, 128)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def extract_features(crop: np.ndarray) -> np.ndarray | None:
    """
    Extract 2048-dim L2-normalized feature vector from a BGR person crop.
    Identical logic to DetectionSystem.extract_person_features().
    """
    try:
        if crop.shape[0] == 0 or crop.shape[1] == 0:
            return None
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        tensor = _preprocess(rgb).unsqueeze(0).to(_device)
        with torch.no_grad():
            feat = _reid_model(tensor)
        vec = feat.squeeze().cpu().numpy()
        # L2 normalize
        norm = np.linalg.norm(vec) + 1e-8
        return vec / norm
    except Exception as exc:
        log_json("warning", "reid-feature-worker", "Feature extraction failed", error=str(exc))
        return None


def extract_color_hist(crop: np.ndarray) -> np.ndarray | None:
    """
    Extract 512-element normalized 3D HSV histogram from the torso region.
    Identical logic to DetectionSystem.extract_color_features() — torso isolation
    + Gray World normalization + 8x8x8 HSV histogram.
    """
    try:
        h, w = crop.shape[:2]
        if h <= 2 or w <= 2:
            return None

        # Torso region: 35-70% height, 25-75% width
        y_start = int(h * 0.35)
        y_end = int(h * 0.70)
        x_start = int(w * 0.25)
        x_end = int(w * 0.75)

        if y_end <= y_start or x_end <= x_start:
            return None

        torso = crop[y_start:y_end, x_start:x_end].copy()

        # Gray World colour normalization
        gw = torso.astype(np.float32)
        means = gw.mean(axis=(0, 1))
        if all(m > 5 for m in means):
            scale = 128.0 / means
            gw *= scale
            torso = np.clip(gw, 0, 255).astype(np.uint8)

        hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 8], [0, 180, 0, 256, 0, 256])
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        return hist.flatten()

    except Exception as exc:
        log_json("warning", "reid-feature-worker", "Color hist extraction failed", error=str(exc))
        return None


def main():
    if not CAMERA_NAME:
        log_json("error", "reid-feature-worker",
                 "CAMERA_NAME env var is required.")
        sys.exit(1)

    input_stream = f"person_tracks::{CAMERA_NAME}"
    log_json("info", "reid-feature-worker", "Service starting",
             camera=CAMERA_NAME, consumer=POD_NAME)
    r = get_redis_client()
    log_json("info", "reid-feature-worker", "Redis connected")

    ensure_consumer_group(r, input_stream, CONSUMER_GROUP, start_id="$")

    log_json("info", "reid-feature-worker", "Entering processing loop",
             stream=input_stream)

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
                        track_epoch = fields.get("track_epoch", "0")
                        frame_index = fields.get("frame_index", "0")

                        crop = decode_frame(person_crop_b64)
                        ch, cw = crop.shape[:2]

                        if cw < MIN_CROP_W or ch < MIN_CROP_H:
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        track_key = (camera_name, track_epoch, track_id)

                        # ── Warmup buffer logic ──────────────────────────────
                        if track_key not in _warmup_buffers:
                            _warmup_buffers[track_key] = []
                            _refresh_counters[track_key] = 0

                        buf = _warmup_buffers[track_key]
                        is_warmup = False

                        if len(buf) < WARMUP_FRAMES:
                            buf.append((cw * ch, crop.copy()))

                        if len(buf) == WARMUP_FRAMES:
                            # First extraction: use best crop from warmup buffer
                            best_crop = max(buf, key=lambda x: x[0])[1]
                            feat = extract_features(best_crop)
                            color = extract_color_hist(best_crop)
                            is_warmup = True
                            # Mark buffer as done by setting to sentinel
                            _warmup_buffers[track_key] = "done"
                        elif _warmup_buffers[track_key] == "done":
                            # Periodic refresh
                            _refresh_counters[track_key] = _refresh_counters.get(track_key, 0) + 1
                            if _refresh_counters[track_key] < REFRESH_EVERY:
                                r.xack(stream_name, CONSUMER_GROUP, msg_id)
                                continue
                            _refresh_counters[track_key] = 0
                            feat = extract_features(crop)
                            color = extract_color_hist(crop)
                        else:
                            # Warmup still accumulating
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        if feat is None:
                            r.xack(stream_name, CONSUMER_GROUP, msg_id)
                            continue

                        bbox_ltrb_raw = fields.get("bbox_ltrb", "[0,0,0,0]")
                        if isinstance(bbox_ltrb_raw, str):
                            bbox_ltrb = json.loads(bbox_ltrb_raw)
                        else:
                            bbox_ltrb = bbox_ltrb_raw

                        out_msg = {
                            "request_id": fields.get("request_id", ""),
                            "camera_name": camera_name,
                            "camera_epoch": fields.get("camera_epoch", "0"),
                            "frame_index": frame_index,
                            "track_id": track_id,
                            "track_epoch": track_epoch,
                            "timestamp": f"{time.time():.3f}",
                            "bbox_ltrb": json.dumps(bbox_ltrb),
                            "feature_vector": json.dumps([round(float(x), 6) for x in feat]),
                            "color_hist": json.dumps(
                                [round(float(x), 6) for x in color] if color is not None else []
                            ),
                            "is_warmup": "true" if is_warmup else "false",
                            "crop_width": str(cw),
                            "crop_height": str(ch),
                        }
                        xadd_json(r, OUTPUT_STREAM, out_msg, maxlen=OUTPUT_MAXLEN)

                        r.xack(stream_name, CONSUMER_GROUP, msg_id)

                        log_json("info", "reid-feature-worker", "Features published",
                                 camera=camera_name, track_id=track_id,
                                 is_warmup=str(is_warmup))

                    except Exception as exc:
                        log_json("error", "reid-feature-worker", "Message processing failed",
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
            log_json("error", "reid-feature-worker", "Loop error — continuing",
                     error=str(loop_exc))
            time.sleep(0.5)


if __name__ == "__main__":
    main()
