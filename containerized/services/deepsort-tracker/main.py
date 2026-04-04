"""
deepsort-tracker/main.py

Per-camera stateful DeepSORT tracker pod.

Reads person_detections::{CAMERA_NAME} via plain XREAD BLOCK (no consumer group —
ordering is critical and only one pod owns each camera stream).

Implements the frame reorder buffer (min-heap, 200 ms forced flush) defined in
STREAMS_SCHEMA.md Section 5 to guarantee DeepSORT receives frames in frame_index
order even when YOLO workers return results out of order.

For each confirmed track:
  - Extracts person crop from the full frame decoded from shared_raw_frames cache.
  - Encodes crop as JPEG base64.
  - Publishes to person_tracks::{CAMERA_NAME}.

Person crop size gate: width < 100 OR height < 200 => person_crop_b64 = "".

NOTE: We do NOT use DeepSORT's built-in embedder. update_tracks() is called with
frame=None. Re-ID features are produced by the separate reid-feature-worker.

Environment variables:
  REDIS_URL      Redis URL (default: redis://localhost:6379)
  CAMERA_NAME    Camera identifier — determines which streams to read/write
  LOG_LEVEL      Logging level (default: info)
"""

import heapq
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field

import cv2
from deep_sort_realtime.deepsort_tracker import DeepSort

_SERVICES_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SERVICES_ROOT)

from shared.redis_client import get_redis_client
from shared.image_codec import decode_frame, encode_frame, resize_if_larger
from shared.stream_utils import xadd_json, log_json, publish_to_dlq

# ── Configuration ─────────────────────────────────────────────────────────────
CAMERA_NAME: str = os.environ.get("CAMERA_NAME", "default_camera")

INPUT_STREAM = f"person_detections::{CAMERA_NAME}"
OUTPUT_STREAM = f"person_tracks::{CAMERA_NAME}"
RAW_FRAMES_STREAM = "shared_raw_frames"

OUTPUT_MAXLEN = 300
PERSON_TRACKING_MAX_AGE = 30
PERSON_TRACKING_N_INIT = 3

MIN_CROP_W = 100
MIN_CROP_H = 200
MAX_CROP_W = 512
MAX_CROP_H = 1024
JPEG_QUALITY = 95

# Reorder buffer parameters
MAX_WAIT_MS = 200.0
BUFFER_CAPACITY = 30

# ── Reorder Buffer ────────────────────────────────────────────────────────────

@dataclass(order=True)
class BufferedDetection:
    frame_index: int
    arrival_time: float = field(compare=False)
    message: dict = field(compare=False)


class FrameReorderBuffer:
    """
    Reorder buffer ensuring DeepSORT receives frames in monotonically increasing
    frame_index order even when YOLO workers return results out of order.
    Matches the design in STREAMS_SCHEMA.md Section 5.
    """

    def __init__(self, max_wait_ms: float = 200.0, buffer_capacity: int = 30):
        self.heap: list[BufferedDetection] = []
        self.next_expected: int = 0
        self.max_wait_ms = max_wait_ms
        self.buffer_capacity = buffer_capacity
        self.camera_epoch: int = -1

    def push(self, message: dict) -> None:
        epoch = int(message.get("camera_epoch", 0))
        frame_idx = int(message.get("frame_index", 0))

        if epoch != self.camera_epoch:
            self._force_flush_all()
            self.camera_epoch = epoch
            self.next_expected = frame_idx
            log_json("info", "deepsort-tracker", "Epoch reset",
                     camera=CAMERA_NAME, new_epoch=epoch, start_frame=frame_idx)

        entry = BufferedDetection(
            frame_index=frame_idx,
            arrival_time=time.monotonic(),
            message=message,
        )
        heapq.heappush(self.heap, entry)

        # Buffer overflow: evict the highest frame_index (furthest future frame)
        # so that we preserve the frames closest to next_expected.
        # heapq is a min-heap, so we must find and remove the max element.
        while len(self.heap) > self.buffer_capacity:
            # Find index of largest frame_index in heap
            max_idx = max(range(len(self.heap)), key=lambda i: self.heap[i].frame_index)
            evicted = self.heap[max_idx]
            # Swap with last element and pop (heap invariant restored by siftup)
            self.heap[max_idx] = self.heap[-1]
            self.heap.pop()
            if max_idx < len(self.heap):
                heapq._siftup(self.heap, max_idx)
                heapq._siftdown(self.heap, 0, max_idx)
            log_json("warning", "deepsort-tracker", "Buffer overflow — evicting frame",
                     camera=CAMERA_NAME, frame_index=evicted.frame_index)

    def drain(self) -> list[dict]:
        now = time.monotonic()
        deliverable = []

        while self.heap:
            top = self.heap[0]

            if top.frame_index == self.next_expected:
                heapq.heappop(self.heap)
                deliverable.append(top.message)
                self.next_expected += 1
                continue

            if top.frame_index > self.next_expected:
                age_ms = (now - top.arrival_time) * 1000.0
                if age_ms >= self.max_wait_ms:
                    gap = top.frame_index - self.next_expected
                    log_json("warning", "deepsort-tracker", "Frame gap — forced flush",
                             camera=CAMERA_NAME, from_frame=self.next_expected, gap=gap)
                    self.next_expected = top.frame_index
                    continue

            break

        return deliverable

    def _force_flush_all(self) -> None:
        self.heap.clear()


# ── Frame cache: store raw frames keyed by camera_name+frame_index ────────────
# The DeepSORT tracker needs the original frame to extract person crops.
# The easiest approach: cache the last N raw frames decoded from shared_raw_frames.

class FrameCache:
    """
    Simple LRU-style cache mapping (camera_name, frame_index) -> BGR frame.
    We also cache (camera_epoch, frame_index) tuples so stale epochs are evicted.
    """

    def __init__(self, max_entries: int = 60):
        self._cache: dict[tuple, object] = {}
        self._max = max_entries

    def put(self, camera_name: str, epoch: int, frame_index: int, frame) -> None:
        key = (camera_name, epoch, frame_index)
        if len(self._cache) >= self._max:
            # Drop oldest (approximation — pop arbitrary entry)
            try:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            except StopIteration:
                pass
        self._cache[key] = frame

    def get(self, camera_name: str, epoch: int, frame_index: int):
        return self._cache.get((camera_name, epoch, frame_index))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log_json("info", "deepsort-tracker", "Service starting", camera=CAMERA_NAME)
    r = get_redis_client()
    log_json("info", "deepsort-tracker", "Redis connected")

    tracker = DeepSort(max_age=PERSON_TRACKING_MAX_AGE, n_init=PERSON_TRACKING_N_INIT)
    reorder_buf = FrameReorderBuffer(max_wait_ms=MAX_WAIT_MS, buffer_capacity=BUFFER_CAPACITY)
    frame_cache = FrameCache(max_entries=120)
    track_epoch = str(uuid.uuid4().int % 65535)  # uint32-style epoch

    # We read raw frames from shared_raw_frames directly (plain XREAD) so we can
    # match frames to their detections.  We maintain two independent stream positions.
    raw_last_id = "$"
    det_last_id = "$"

    log_json("info", "deepsort-tracker", "Entering processing loop")

    while True:
        try:
            # ── 1. Pull new raw frames into cache ─────────────────────────────
            raw_results = r.xread(
                {RAW_FRAMES_STREAM: raw_last_id},
                count=10,
                block=1,  # 1 ms — non-blocking effectively
            )
            if raw_results:
                for _stream, entries in raw_results:
                    for msg_id, fields in entries:
                        raw_last_id = msg_id
                        cam = fields.get("camera_name", "")
                        if cam != CAMERA_NAME:
                            continue
                        epoch = int(fields.get("camera_epoch", 0))
                        fidx = int(fields.get("frame_index", 0))
                        jpeg_b64 = fields.get("jpeg_b64", "")
                        if jpeg_b64:
                            try:
                                frame = decode_frame(jpeg_b64)
                                frame_cache.put(cam, epoch, fidx, frame)
                            except Exception:
                                pass

            # ── 2. Pull detection messages into reorder buffer ────────────────
            det_results = r.xread(
                {INPUT_STREAM: det_last_id},
                count=20,
                block=50,
            )
            if det_results:
                for _stream, entries in det_results:
                    for msg_id, fields in entries:
                        det_last_id = msg_id
                        reorder_buf.push(fields)

            # ── 3. Drain buffer in order, run DeepSORT ────────────────────────
            ordered_msgs = reorder_buf.drain()
            for fields in ordered_msgs:
                try:
                    camera_name = fields.get("camera_name", CAMERA_NAME)
                    epoch = int(fields.get("camera_epoch", 0))
                    frame_index = int(fields.get("frame_index", 0))
                    request_id = fields.get("request_id", str(uuid.uuid4()))

                    # Parse detections JSON
                    raw_dets = fields.get("detections", "[]")
                    if isinstance(raw_dets, str):
                        raw_dets = json.loads(raw_dets)

                    # Convert to DeepSORT format: list of ([l,t,w,h], conf, class_id)
                    ds_detections = []
                    for det in raw_dets:
                        bbox = det["bbox_ltwh"]   # already LTWH
                        conf = float(det["confidence"])
                        cls = int(det.get("class_id", 0))
                        ds_detections.append((bbox, conf, cls))

                    # Retrieve source frame from cache
                    src_frame = frame_cache.get(camera_name, epoch, frame_index)

                    # Update DeepSORT (pass frame=None — no built-in embedder)
                    tracks = tracker.update_tracks(ds_detections, frame=None)

                    frame_w = int(fields.get("frame_width", 0))
                    frame_h = int(fields.get("frame_height", 0))

                    for track in tracks:
                        if not track.is_confirmed():
                            continue

                        tid = track.track_id
                        l, t, ri, b = map(int, track.to_ltrb())
                        crop_w = ri - l
                        crop_h = b - t

                        # Extract and encode person crop
                        person_crop_b64 = ""
                        if (
                            src_frame is not None
                            and crop_w >= MIN_CROP_W
                            and crop_h >= MIN_CROP_H
                        ):
                            try:
                                crop = src_frame[
                                    max(0, t): min(src_frame.shape[0], b),
                                    max(0, l): min(src_frame.shape[1], ri),
                                ]
                                if crop.size > 0:
                                    crop = resize_if_larger(crop, MAX_CROP_W, MAX_CROP_H)
                                    person_crop_b64 = encode_frame(crop, quality=JPEG_QUALITY)
                            except Exception as crop_err:
                                log_json("warning", "deepsort-tracker", "Crop encode failed",
                                         error=str(crop_err))

                        out_msg = {
                            "request_id": request_id,
                            "camera_name": camera_name,
                            "camera_epoch": str(epoch),
                            "frame_index": str(frame_index),
                            "timestamp": f"{time.time():.3f}",
                            "frame_width": str(frame_w),
                            "frame_height": str(frame_h),
                            "track_id": str(tid),
                            "track_epoch": track_epoch,
                            "is_confirmed": "true",
                            "hits": str(track.hits),
                            "age": str(track.age),
                            "time_since_update": str(track.time_since_update),
                            "bbox_ltrb": json.dumps([l, t, ri, b]),
                            "person_crop_b64": person_crop_b64,
                        }

                        xadd_json(r, OUTPUT_STREAM, out_msg, maxlen=OUTPUT_MAXLEN)

                except Exception as exc:
                    log_json("error", "deepsort-tracker", "Processing error",
                             camera=CAMERA_NAME, error=str(exc))
                    publish_to_dlq(
                        r,
                        original_stream=INPUT_STREAM,
                        original_msg_id="unknown",
                        original_fields=fields,
                        error=exc,
                        consumer_name=f"deepsort-tracker-{CAMERA_NAME}",
                        group_name="none",
                    )

        except Exception as loop_exc:
            log_json("error", "deepsort-tracker", "Loop error — continuing",
                     camera=CAMERA_NAME, error=str(loop_exc))
            time.sleep(0.5)


if __name__ == "__main__":
    main()
