# ObserveAI Redis Streams Schema

**Version:** 1.0  
**Date:** 2026-04-03  
**Status:** Design — ready for implementation  

This document is the authoritative contract for all inter-service message passing in the
containerized ObserveAI pipeline. Every field name, type, encoding choice, and retention
policy defined here must be implemented exactly as written. Changes require updating this
document first.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Camera Ingest Layer  (one pod per camera)                              │
│                                                                         │
│  cam-ingest::cam_a  ──┐                                                 │
│  cam-ingest::cam_b  ──┼──► shared_raw_frames  (fan-out read)           │
│  cam-ingest::cam_c  ──┤                                                 │
│  cam-ingest::cam_d  ──┘                                                 │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Person YOLO Pool        │
                    │  Consumer group:         │
                    │  cg::person_yolo         │
                    │  [stateless, scale 1–N]  │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼──────────────────────────────────────┐
                    │  per-camera detection streams                      │
                    │  person_detections::{camera_name}                  │
                    └──────────────┬────────────────────────────────────┘
                                   │  (one stream per camera, FIFO)
                    ┌──────────────▼──────────────┐
                    │  Per-Camera DeepSORT Tracker │
                    │  [stateful, 1 pod per camera]│
                    └──────┬───────────────────────┘
                           │
              ┌────────────▼────────────────────────────────┐
              │  person_tracks::{camera_name}                │
              └──────────┬───────────────────────────────────┘
                         │
          ┌──────────────┴──────────────────────────────┐
          │                                              │
┌─────────▼───────────┐                    ┌────────────▼──────────────┐
│  Face YOLO Pool      │                   │  Re-ID Feature Pool        │
│  cg::face_yolo       │                   │  cg::reid_extract          │
│  [stateless, 1–N]    │                   │  [stateless, 1–N]          │
└─────────┬────────────┘                   └────────────┬───────────────┘
          │ face_crops                                   │ reid_features
┌─────────▼────────────┐                    ┌───────────▼───────────────┐
│  Face Recog Pool     │                    │  Global Person Tracker     │
│  cg::face_recog      │                    │  [stateful singleton]      │
│  [stateless, 1–N]    │                    └───────────────────────────┘
└─────────┬────────────┘
          │ identity_results
┌─────────▼────────────┐
│  Face DB Writer Pool │
│  cg::face_db_writer  │
│  [stateless, 1–N]    │
└──────────────────────┘

Also parallel to DeepSORT output:
person_tracks::{camera_name}
          │
┌─────────▼────────────┐
│  Action/Pose Pool    │
│  cg::action_detect   │
│  [stateless, 1–N]    │
└──────────────────────┘
          │ action_events
┌─────────▼────────────┐
│  Event Bus / UI      │
└──────────────────────┘
```

**Fan-out vs competing consumers:**

| Stream | Pattern | Reason |
|--------|---------|--------|
| `shared_raw_frames` | Fan-out (independent consumer groups per consumer type) | Person YOLO pool and any future consumers each need every frame |
| `person_detections::{cam}` | Single consumer (DeepSORT for that camera) | Frame ordering is critical; only one tracker owns each camera |
| `person_tracks::{cam}` | Fan-out (Re-ID pool, Face YOLO pool, Action pool each have own group) | Three independent downstream stages all need every track update |
| `face_crops` | Competing consumers (`cg::face_recog`) | Face recognition is expensive; distribute across pool |
| `reid_features` | Single consumer (GlobalPersonTracker) | Singleton stateful merger; must see all features |
| `identity_results` | Competing consumers (`cg::face_db_writer`) | Write parallelism safe when keyed by user folder |
| `action_events` | Fan-out (UI and any alert service) | Multiple independent sinks |
| `dlq::*` | Single consumer per DLQ stream (monitoring/alerting) | Dead-letter inspection |

---

## 2. Stream Catalogue

Throughput baseline: **4 cameras × 30 FPS = 120 raw frames/sec**. YOLO runs on every frame
(frame_skip_interval removed in the containerized design — the pool handles load). Tracking
messages are one per confirmed person per processed frame.

| Stream Name | Producer | Consumer Group(s) | msg/sec (peak) | MAXLEN | Drop policy |
|-------------|----------|-------------------|----------------|--------|-------------|
| `shared_raw_frames` | cam-ingest (4 pods) | `cg::person_yolo` | 120 | 600 (5 s @ 120/s) | MAXLEN trim — stale frames worthless |
| `person_detections::{cam}` | person-yolo-worker | deepsort-tracker-{cam} | ~30/cam | 150 | MAXLEN trim — tracker drains quickly |
| `person_tracks::{cam}` | deepsort-tracker-{cam} | `cg::reid_extract`, `cg::face_yolo`, `cg::action_detect` | ~30/cam (×active persons) | 300 | MAXLEN trim |
| `face_crops` | face-yolo-worker | `cg::face_recog` | ~20 (burst) | 200 | MAXLEN trim — older crops superseded |
| `reid_features` | reid-feature-worker | `cg::global_tracker` | ~20 | 200 | NEVER drop — EMA state update |
| `identity_results` | face-recog-worker | `cg::face_db_writer`, `cg::ui_events` | ~5 | 500 | NEVER drop — identity assignments |
| `action_events` | action-detect-worker | `cg::ui_events`, `cg::alert_sink` | ~2 (burst) | 200 | MAXLEN trim |
| `dlq::shared_raw_frames` | any worker | monitoring | <1 | 1000 | Keep all — audit trail |
| `dlq::person_detections` | deepsort-tracker | monitoring | <1 | 1000 | Keep all |
| `dlq::face_crops` | face-recog-worker | monitoring | <1 | 1000 | Keep all |
| `dlq::reid_features` | global-tracker | monitoring | <1 | 1000 | Keep all |
| `dlq::identity_results` | face-db-writer | monitoring | <1 | 1000 | Keep all |

MAXLEN values use `MAXLEN ~ ` (approximate trimming). Exact Redis command example:
`XADD shared_raw_frames MAXLEN ~ 600 * field value`

---

## 3. Per-Stream Message Schemas

### Conventions

- All messages are Redis hashes with string-encoded values.
- JSON fields nested inside a message are serialized as a single string value under a
  key named `payload`. This allows Redis hash field access for routing headers without
  deserializing the full payload.
- Timestamps: Unix epoch float, millisecond precision, as string: `"1743676800.123"`.
- Images: JPEG-encoded, then Base64 (standard alphabet). Quality: 85 for raw frames,
  95 for face crops (higher quality needed for ArcFace embedding accuracy).
- `request_id`: UUID4 string assigned by the producer at message origin. Propagated
  unchanged through every downstream message derived from the same source frame.
- `frame_index`: Monotonically increasing uint64 per camera, assigned by the camera
  ingest pod. Resets to 0 only on pod restart (tracked via `camera_epoch`).

---

### 3.1 `shared_raw_frames`

**Producer:** cam-ingest pod  
**Purpose:** Raw decoded video frame for person detection.

```
Redis Stream ID: auto-generated (XADD *)

Fields:
  request_id      string   UUID4  — origin trace ID for this frame
  camera_name     string   Camera identifier, e.g. "entrance_left"
  camera_epoch    string   uint32 — increments each time cam-ingest restarts;
                           used by consumers to detect frame_index reset
  frame_index     string   uint64 — monotonic frame counter within this epoch,
                           assigned by cam-ingest before publishing
  timestamp       string   float  — Unix epoch (ms precision) when frame was captured
  frame_width     string   int    — pixel width of encoded frame
  frame_height    string   int    — pixel height of encoded frame
  jpeg_b64        string   Base64-encoded JPEG bytes, quality=85
                           Max dimensions: 1920×1080 before encoding.
                           If source is larger, cam-ingest resizes to fit.
```

**JSON example (flattened into Redis hash fields):**
```
request_id   = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
camera_name  = "entrance_left"
camera_epoch = "3"
frame_index  = "14523"
timestamp    = "1743676800.123"
frame_width  = "1280"
frame_height = "720"
jpeg_b64     = "/9j/4AAQSkZJRgAB..."  (truncated)
```

**Encoding note:** cam-ingest calls `cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])`
then `base64.b64encode(buf).decode('ascii')`.

---

### 3.2 `person_detections::{camera_name}`

**Producer:** person-yolo-worker (pool member)  
**Purpose:** Raw YOLO bounding boxes before tracking. One message per frame processed,
even if zero persons detected (DeepSORT needs empty updates to age tracks correctly).

Stream key pattern: `person_detections::entrance_left`, `person_detections::warehouse_b`, etc.

```
Fields:
  request_id      string   Propagated from source shared_raw_frames message
  camera_name     string   Must match stream key suffix
  camera_epoch    string   Propagated from source frame
  frame_index     string   Propagated from source frame — DeepSORT tracker uses
                           this to enforce ordering (see Section 5)
  timestamp       string   Unix epoch when YOLO inference completed
  frame_width     string   Pixel dimensions of the frame that was inferenced
  frame_height    string
  detections      string   JSON array of detection objects (see schema below)
  inference_ms    string   float — YOLO wall-clock inference time in milliseconds
                           (used for performance monitoring)
```

**`detections` field — JSON array:**
```json
[
  {
    "bbox_ltwh": [423, 156, 87, 210],
    "confidence": 0.847,
    "class_id": 0
  },
  {
    "bbox_ltwh": [701, 220, 65, 198],
    "confidence": 0.612,
    "class_id": 0
  }
]
```

Field definitions:
- `bbox_ltwh`: `[left, top, width, height]` in pixels — **LTWH format** as required by
  `DeepSort.update_tracks()`. Do not convert to XYXY; the tracker will reject it.
- `confidence`: float in [0.0, 1.0] — YOLO detection confidence.
- `class_id`: int — always 0 (COCO person class). Included for forward compatibility.

**Empty frame (no persons):**
```json
[]
```
An empty array must still be published so the DeepSORT tracker can advance its Kalman
filter and age existing tracks. A missing message is not equivalent to an empty detection.

---

### 3.3 `person_tracks::{camera_name}`

**Producer:** deepsort-tracker-{camera_name} pod  
**Purpose:** Confirmed DeepSORT tracks with position and person crop. One message per
confirmed track per frame (multiple messages per frame if multiple persons tracked).

Stream key pattern: `person_tracks::entrance_left`

```
Fields:
  request_id      string   Propagated from source detection message
  camera_name     string   Must match stream key suffix
  camera_epoch    string   Propagated
  frame_index     string   Propagated
  timestamp       string   Unix epoch when tracking update completed
  frame_width     string   Frame dimensions for coordinate normalization
  frame_height    string
  track_id        string   int — DeepSORT local track ID within this camera.
                           NOT globally unique. Unique only within one camera's
                           lifetime. Resets on tracker pod restart.
  track_epoch     string   uint32 — increments on tracker pod restart so
                           consumers can detect track_id namespace resets
  is_confirmed    string   "true" — only confirmed tracks are published.
                           Tentative tracks are dropped at the tracker.
  hits            string   int — DeepSORT track.hits (consecutive frames seen)
  age             string   int — DeepSORT track.age (frames since first seen)
  time_since_update string int — DeepSORT track.time_since_update
  bbox_ltrb       string   JSON array [left, top, right, bottom] in pixels.
                           Derived from track.to_ltrb(). Used by all downstream
                           consumers for crop extraction.
  person_crop_b64 string   Base64-encoded JPEG of the person crop,
                           frame[top:bottom, left:right], quality=95.
                           Max crop size before encoding: 512×1024 px.
                           If crop exceeds this, resize preserving aspect ratio.
                           Empty string "" if crop area is zero or below minimum
                           size threshold (width < 100px OR height < 200px).
```

**JSON example (Redis hash fields):**
```
request_id       = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
camera_name      = "entrance_left"
camera_epoch     = "3"
frame_index      = "14523"
timestamp        = "1743676800.198"
frame_width      = "1280"
frame_height     = "720"
track_id         = "42"
track_epoch      = "1"
is_confirmed     = "true"
hits             = "18"
age              = "21"
time_since_update = "0"
bbox_ltrb        = "[423, 156, 510, 366]"
person_crop_b64  = "/9j/4AAQSkZJRgAB..."
```

**Minimum crop threshold:** Do not publish `person_crop_b64` if:
`(right - left) < 100` or `(bottom - top) < 200`. Set `person_crop_b64 = ""`.
This mirrors the `MIN_CROP_W = 100, MIN_CROP_H = 200` gate in the original
`processing_thread_function`.

**One message per track per frame:** If a frame has 3 confirmed tracks, publish 3 messages
to `person_tracks::cam_name`, all with the same `frame_index`. Downstream consumers
correlate by `frame_index` + `track_id`.

---

### 3.4 `face_crops`

**Producer:** face-yolo-worker (pool member)  
**Purpose:** Individual face crop detected within a person crop, ready for ArcFace
embedding. One message per detected face.

```
Fields:
  request_id      string   Propagated
  camera_name     string   Source camera (needed so face-recog result routes back correctly)
  camera_epoch    string   Propagated
  frame_index     string   Propagated
  track_id        string   DeepSORT local track ID that owns this face
  track_epoch     string   Propagated — used with track_id to form a stable key
  timestamp       string
  face_bbox_in_person string JSON array [left, top, width, height] of face within
                              the PERSON CROP coordinate space (not full frame).
                              Derived from yolov11n-face.pt inference on person_crop.
  face_bbox_global string  JSON array [left, top, width, height] in full frame
                            coordinates. Computed as:
                            gx = person_left + face_lx1
                            gy = person_top  + face_ly1
  face_width      string   int — pixel width of face crop
  face_height     string   int — pixel height of face crop
  yolo_confidence string   float — face YOLO detection confidence
  face_crop_b64   string   Base64-encoded JPEG of the face crop only,
                           frame[gy:gy+gh, gx:gx+gw], quality=95.
                           Only published if width >= 70 AND height >= 90
                           (mirrors MIN_FACE_SIZE validation in original code).
                           Messages that fail this gate are dropped (not DLQ'd).
```

**JSON example:**
```
request_id        = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
camera_name       = "entrance_left"
camera_epoch      = "3"
frame_index       = "14523"
track_id          = "42"
track_epoch       = "1"
timestamp         = "1743676800.245"
face_bbox_in_person = "[12, 5, 68, 82]"
face_bbox_global  = "[435, 161, 68, 82]"
face_width        = "68"
face_height       = "82"
yolo_confidence   = "0.923"
face_crop_b64     = "/9j/4AAQSkZJRgAB..."
```

**Size gate applied by face-yolo-worker before publishing:**
```python
if face_width < 70 or face_height < 90:
    # Drop silently — person is too distant for recognition
    # Increment a Prometheus counter: face_crops_dropped_too_small_total
    return
```

---

### 3.5 `reid_features`

**Producer:** reid-feature-worker (pool member)  
**Purpose:** 2048-dimensional ResNet-50 Re-ID feature vector and HSV color histogram
for a tracked person. Published on initial feature extraction (warmup complete) and
every 30 frames thereafter.

```
Fields:
  request_id      string   Propagated
  camera_name     string
  camera_epoch    string
  frame_index     string
  track_id        string   DeepSORT local track ID
  track_epoch     string
  timestamp       string
  bbox_ltrb       string   JSON array — person bbox in full frame coordinates
  feature_vector  string   JSON array of 2048 float32 values (L2-normalized).
                           Serialized as: json.dumps([float(x) for x in vec])
                           Precision: 6 decimal places is sufficient (ArcFace).
  color_hist      string   JSON array of 512 float32 values.
                           96-bin HSV histogram (32 H + 32 S + 32 V bins,
                           concatenated), normalized to sum=1.0.
                           Matches extract_color_features() output from original code.
  is_warmup       string   "true" if this is the first feature extraction for this
                           track_id (warmup buffer complete), "false" for refresh.
  crop_width      string   int — person crop dimensions used for feature extraction
  crop_height     string
```

**JSON example:**
```
request_id     = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
camera_name    = "entrance_left"
camera_epoch   = "3"
frame_index    = "14523"
track_id       = "42"
track_epoch    = "1"
timestamp      = "1743676800.301"
bbox_ltrb      = "[423, 156, 510, 366]"
feature_vector = "[0.012345, -0.234567, 0.891234, ...]"  // 2048 elements
color_hist     = "[0.003201, 0.004512, ...]"             // 512 elements
is_warmup      = "true"
crop_width     = "87"
crop_height    = "210"
```

**Size gate (applied by reid-feature-worker before publishing):**
```python
if crop_width < 100 or crop_height < 200:
    # Below warmup threshold — do not publish
    return
```

**Normalization contract:** The feature vector MUST be L2-normalized before publishing:
```python
vec = vec / (np.linalg.norm(vec) + 1e-8)
```
The GlobalPersonTracker EMA blending assumes unit-vector inputs and re-normalizes after
blending. Publishing an unnormalized vector will corrupt cross-camera matching.

---

### 3.6 `identity_results`

**Producer:** face-recog-worker (pool member)  
**Purpose:** ArcFace match result for a face crop. Published after every recognition
attempt regardless of outcome (including "Unknown" and "Scanning...").

```
Fields:
  request_id      string   Propagated from face_crops message
  camera_name     string
  camera_epoch    string
  frame_index     string
  track_id        string
  track_epoch     string
  face_id         string   Ephemeral face tracking ID within this camera session.
                           Format: "{camera_name}::{track_id}::{sequential_int}"
                           Example: "entrance_left::42::7"
                           Used by the face-db-writer to route updates.
  timestamp       string
  matched_user_id string   "User_3", "Unknown", or "Scanning..."
  distance        string   float — ArcFace cosine distance to best match.
                           Lower is better. Threshold: 0.6 (from original code).
                           Set to "-1.0" if no embeddings in cache (empty Faces_db).
  is_new_user     string   "true" if matched_user_id is a newly created User_X
                           (face had no match after 3 consecutive Unknown results).
                           "false" otherwise.
  quality_score   string   float — face image quality score from calculate_face_quality().
                           Used by face-db-writer to decide whether to save.
  face_crop_b64   string   Base64-encoded JPEG of the face crop (propagated from
                           face_crops message). Needed by face-db-writer.
                           Do NOT re-encode; propagate the original bytes.
  global_id       string   int or "" — GlobalPersonTracker global_id if already
                           assigned to this track, or empty string if not yet registered.
                           Populated by face-recog-worker by querying the tracker service
                           via a Redis GET on key `global_id::{camera_name}::{track_id}`.
```

**JSON example:**
```
request_id      = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
camera_name     = "entrance_left"
camera_epoch    = "3"
frame_index     = "14523"
track_id        = "42"
track_epoch     = "1"
face_id         = "entrance_left::42::7"
timestamp       = "1743676800.612"
matched_user_id = "User_3"
distance        = "0.234"
is_new_user     = "false"
quality_score   = "312.5"
face_crop_b64   = "/9j/4AAQSkZJRgAB..."
global_id       = "15"
```

---

### 3.7 `action_events`

**Producer:** action-detect-worker (pool member)  
**Purpose:** Pose-match result when a defined action is detected for a tracked person.
Published only when distance < 0.10 AND cooldown (5 s) has elapsed.

```
Fields:
  request_id      string   Propagated from person_tracks message
  camera_name     string
  camera_epoch    string
  frame_index     string
  track_id        string
  timestamp       string   Unix epoch when action was detected
  action_name     string   Name of the matched action, e.g. "raised_hand"
  person_name     string   Display name: global_id's matched user or "Unknown"
  global_id       string   GlobalPersonTracker global_id or ""
  pose_distance   string   float — normalized Euclidean distance to reference pose.
                           Values below 0.10 trigger an event.
  keypoints_json  string   JSON array of 17 keypoints [[x, y], ...] normalized 0–1.
                           Derived from YOLOv8-Pose xyn output.
```

**JSON example:**
```
request_id    = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
camera_name   = "entrance_left"
camera_epoch  = "3"
frame_index   = "14523"
track_id      = "42"
timestamp     = "1743676800.890"
action_name   = "raised_hand"
person_name   = "User_3"
global_id     = "15"
pose_distance = "0.071"
keypoints_json = "[[0.45, 0.12], [0.44, 0.18], ...]"
```

---

### 3.8 Dead Letter Queue Messages (`dlq::{stream_name}`)

See Section 7 for DLQ design. All DLQ messages share this envelope:

```
Fields:
  original_stream  string   Stream the message came from
  original_msg_id  string   Redis Stream message ID that failed
  original_fields  string   JSON object of all original message fields
  error_class      string   Python exception class name, e.g. "json.JSONDecodeError"
  error_message    string   str(exception)
  retry_count      string   int — number of processing attempts before DLQ
  failed_at        string   Unix epoch when the final failure occurred
  consumer_name    string   Redis consumer name that failed (e.g. "face-recog-worker-3")
  group_name       string   Consumer group name
```

---

## 4. Consumer Group Assignments

### Fan-out streams (multiple independent groups)

`shared_raw_frames` has one consumer group:
- `cg::person_yolo` — competed among person-yolo-worker pod replicas

`person_tracks::{cam}` has three independent consumer groups:
- `cg::reid_extract` — competed among reid-feature-worker replicas
- `cg::face_yolo` — competed among face-yolo-worker replicas
- `cg::action_detect` — competed among action-detect-worker replicas

`identity_results` has two independent consumer groups:
- `cg::face_db_writer` — competed among face-db-writer replicas
- `cg::ui_events` — consumed by the web-server pod for WebSocket push

`action_events` has two independent consumer groups:
- `cg::ui_events` — web-server pod for WebSocket push
- `cg::alert_sink` — optional alerting service

### Single-consumer streams (no competing consumers)

`person_detections::{cam}` is consumed by exactly one pod: `deepsort-tracker-{cam}`.
No consumer group is used. The tracker pod reads via `XREAD BLOCK` with its own
stream position. This guarantees ordering without group ACK overhead.

`reid_features` is consumed by exactly one pod: `global-tracker`. No consumer group.
Uses `XREAD BLOCK`. The GlobalPersonTracker is a singleton; parallel consumers would
produce race conditions in EMA state updates.

### Redis consumer group creation commands

Run once at system startup (idempotent with `MKSTREAM`):

```redis
XGROUP CREATE shared_raw_frames         cg::person_yolo   $ MKSTREAM
XGROUP CREATE person_tracks::cam_a      cg::reid_extract  $ MKSTREAM
XGROUP CREATE person_tracks::cam_a      cg::face_yolo     $ MKSTREAM
XGROUP CREATE person_tracks::cam_a      cg::action_detect $ MKSTREAM
XGROUP CREATE face_crops                cg::face_recog    $ MKSTREAM
XGROUP CREATE identity_results          cg::face_db_writer $ MKSTREAM
XGROUP CREATE identity_results          cg::ui_events     $ MKSTREAM
XGROUP CREATE action_events             cg::ui_events     $ MKSTREAM
XGROUP CREATE action_events             cg::alert_sink    $ MKSTREAM
```

Repeat the `person_tracks::*` group creation for each camera name.

### Consumer naming convention

Each pod instance registers a unique consumer name within its group:
```
{service_name}-{pod_index}
```
Examples: `person-yolo-worker-0`, `face-recog-worker-2`, `reid-feature-worker-1`.

In Kubernetes, use the `$(POD_NAME)` downward API environment variable as the
consumer name to guarantee uniqueness.

### Camera isolation for DeepSORT

A person-yolo-worker reads from `shared_raw_frames` (any camera). When publishing
results, it writes to the camera-specific stream `person_detections::{camera_name}`
using the `camera_name` field from the source message. The DeepSORT tracker for
camera `X` only reads `person_detections::X`. This provides natural isolation without
any routing logic in the tracker itself.

---

## 5. Frame Ordering Guarantee Mechanism

### Problem statement

The person-yolo-worker pool has N replicas that consume `shared_raw_frames` in
parallel. Worker-0 might finish YOLO inference on frame 15 and publish to
`person_detections::cam_a` before worker-1 finishes frame 14. If the DeepSORT
tracker processes frame 15 before frame 14, the Kalman filter prediction is corrupted:
it expects monotonically advancing time and position.

### Solution: Reorder buffer in the DeepSORT tracker pod

The DeepSORT tracker for each camera maintains a small in-memory reorder buffer.
It never passes a detection to the DeepSORT `update_tracks()` call until it has
verified no earlier `frame_index` is pending.

**Parameters:**
- `MAX_WAIT_MS = 200` — maximum time to hold a buffered message before forcing
  flush (prevents indefinite stall on YOLO worker failure)
- `BUFFER_CAPACITY = 30` — maximum messages held in the reorder buffer (covers
  ~1 second of 30 FPS with pool parallelism)

**Reorder buffer pseudocode (Python):**

```python
import heapq
import time
from dataclasses import dataclass, field
from typing import Optional

@dataclass(order=True)
class BufferedDetection:
    frame_index: int
    arrival_time: float = field(compare=False)
    message: dict = field(compare=False)   # full Redis message dict

class FrameReorderBuffer:
    """
    Reorder buffer for per-camera DeepSORT tracker.
    Holds out-of-order detection messages until in-order delivery is possible.
    """

    def __init__(self, max_wait_ms: float = 200.0, buffer_capacity: int = 30):
        self.heap: list[BufferedDetection] = []   # min-heap by frame_index
        self.next_expected: int = 0               # next frame_index to deliver
        self.max_wait_ms = max_wait_ms
        self.buffer_capacity = buffer_capacity
        self.camera_epoch: int = -1               # detect epoch resets

    def push(self, message: dict) -> None:
        """Add a new detection message to the buffer."""
        epoch = int(message["camera_epoch"])
        frame_idx = int(message["frame_index"])

        # On epoch change (cam-ingest restart), flush buffer and reset
        if epoch != self.camera_epoch:
            self._force_flush_all()
            self.camera_epoch = epoch
            self.next_expected = frame_idx

        entry = BufferedDetection(
            frame_index=frame_idx,
            arrival_time=time.monotonic(),
            message=message
        )
        heapq.heappush(self.heap, entry)

        # Evict oldest if over capacity (prevents unbounded memory growth)
        while len(self.heap) > self.buffer_capacity:
            evicted = heapq.heappop(self.heap)
            self._send_to_dlq(evicted.message, reason="buffer_overflow")

    def drain(self) -> list[dict]:
        """
        Return all messages that are safe to deliver in order.

        A message is delivered if:
          (a) its frame_index == next_expected, OR
          (b) it has waited longer than max_wait_ms (force flush)

        Returns a list of messages sorted by frame_index ascending.
        """
        now = time.monotonic()
        deliverable = []

        while self.heap:
            top = self.heap[0]

            # Case (a): in-order delivery
            if top.frame_index == self.next_expected:
                heapq.heappop(self.heap)
                deliverable.append(top.message)
                self.next_expected += 1
                continue

            # Case (b): gap detected and oldest message has timed out
            if top.frame_index > self.next_expected:
                age_ms = (now - top.arrival_time) * 1000
                if age_ms >= self.max_wait_ms:
                    # The missing frames are gone (YOLO worker dropped or crashed).
                    # Log the gap and advance next_expected to this frame.
                    gap_size = top.frame_index - self.next_expected
                    self._log_gap(self.next_expected, gap_size)
                    self.next_expected = top.frame_index
                    continue   # Re-evaluate top of heap

            # Top is either in the future and not timed out — stop draining
            break

        return deliverable

    def _force_flush_all(self) -> None:
        """Flush all buffered messages in frame_index order (used on epoch reset)."""
        while self.heap:
            entry = heapq.heappop(self.heap)
            # DeepSORT will be re-initialized on epoch reset anyway; discard.

    def _log_gap(self, from_idx: int, gap_size: int) -> None:
        import logging
        logging.warning(
            "frame_gap camera_epoch=%d from=%d size=%d — forcing advance",
            self.camera_epoch, from_idx, gap_size
        )
        # Emit Prometheus counter: deepsort_frame_gaps_total{camera=self.camera_name}

    def _send_to_dlq(self, message: dict, reason: str) -> None:
        # Publish to dlq::person_detections (see Section 7)
        pass


# --- Tracker main loop ---

def deepsort_tracker_loop(camera_name: str, redis_client):
    buffer = FrameReorderBuffer(max_wait_ms=200, buffer_capacity=30)
    stream_key = f"person_detections::{camera_name}"
    last_id = "0"

    while True:
        # Read new messages (block up to 50 ms)
        results = redis_client.xread(
            {stream_key: last_id}, count=50, block=50
        )

        if results:
            for stream, messages in results:
                for msg_id, fields in messages:
                    last_id = msg_id
                    buffer.push(fields)

        # Drain buffer and process in order
        for msg in buffer.drain():
            detections = _parse_detections(msg["detections"])
            tracks = deepsort.update_tracks(detections, frame=None)
            # frame=None: we pass None because DeepSORT's built-in Re-ID is not used.
            # The LTWH→track conversion only needs the detection list.
            _publish_tracks(camera_name, msg, tracks, redis_client)
```

### What `frame=None` means for DeepSORT

The original code calls `update_tracks(detections, frame=frame)`. In the containerized
design, the tracker pod does not have access to raw frames — it only has detections.
The `frame` parameter in `deep-sort-realtime` is used only for its internal visual
Re-ID feature extraction (OSNet), which ObserveAI does not use (it uses ResNet-50 via
a separate Re-ID pool instead). Passing `frame=None` disables internal Re-ID without
affecting IoU matching or Kalman filtering.

**Initialization:** DeepSort must be initialized with `embedder=None` to prevent it
from attempting to load its internal Re-ID model:
```python
from deep_sort_realtime.deepsort_tracker import DeepSort
deepsort = DeepSort(
    max_age=30,
    n_init=3,
    embedder=None,   # Disable built-in Re-ID — we use external reid-feature-worker
)
```

---

## 6. Backpressure Policy

### Principle

Streams carrying raw video frames (raw pixels) may be trimmed aggressively — a
stale frame has no value once a newer frame is available. Streams carrying derived
identity state (recognition results, Re-ID features) must never be trimmed below
the consumer's processing capacity.

| Stream | Drop allowed? | Mechanism | Risk if dropped |
|--------|--------------|-----------|-----------------|
| `shared_raw_frames` | Yes | MAXLEN ~ 600 (5 s buffer). Oldest frames evicted. | YOLO worker skips frame — no state corruption |
| `person_detections::{cam}` | Yes | MAXLEN ~ 150. DeepSORT ages out missing frames gracefully after `max_age=30` frames. | Track age increases, eventually track deleted — acceptable |
| `person_tracks::{cam}` | Yes | MAXLEN ~ 300. Downstream pools skip a track update — person crop just not recognized in that frame. | Missed recognition attempt — tolerable at video rate |
| `face_crops` | Yes | MAXLEN ~ 200. Older crops are superseded by newer crops of same person. | One face crop not recognized — person recognized in next cycle |
| `reid_features` | **No** | MAXLEN ~ 200, but monitor consumer lag. Alert if lag > 100. Scale up global-tracker horizontally if needed (requires leader-election refactor). | EMA feature miss causes cross-camera matching degradation |
| `identity_results` | **No** | MAXLEN ~ 500. face-db-writer is fast (disk IO only). Scale horizontally if needed. | Lost identity assignment — person remains "Unknown" permanently until next face scan |
| `action_events` | Yes | MAXLEN ~ 200. Events are fire-and-forget alerts. | One action event not displayed — acceptable |

### Slow consumer handling

When `face_crops` consumer lag exceeds 100 messages (measured by comparing group
`pending-entries` to MAXLEN):

1. Add a replica to the `cg::face_recog` consumer group (Kubernetes HPA).
2. If lag exceeds MAXLEN (200), oldest messages are trimmed by Redis. These represent
   face crops for frames already multiple seconds old — not useful for real-time
   recognition.

When `reid_features` consumer lag exceeds 50 messages:

1. Alert (Prometheus alert rule: `reid_consumer_lag > 50`).
2. The GlobalPersonTracker is a stateful singleton and cannot trivially be scaled
   horizontally without distributed locking. Mitigation: optimize GlobalPersonTracker
   processing time (the EMA computation is O(N) in number of global persons; keep
   person count bounded by pruning persons unseen for > 60 s).

### Producer-side backpressure: cam-ingest

cam-ingest pods write to `shared_raw_frames`. If a pod falls behind (e.g., YOLO pool
is overloaded), frames accumulate in the stream until MAXLEN trim. This is intentional:
cam-ingest must never block or drop frames at the capture layer; Redis MAXLEN trimming
handles overload at the consumer side.

**Cam-ingest must use non-blocking XADD:** If Redis itself is overloaded (unlikely at
these message rates), cam-ingest should log a warning and drop the frame rather than
blocking the capture loop.

---

## 7. Dead Letter Queue Design

### Naming convention

```
dlq::{original_stream_name}
```

Examples:
- `dlq::shared_raw_frames`
- `dlq::face_crops`
- `dlq::reid_features`
- `dlq::identity_results`

For camera-specific streams: `dlq::person_detections::entrance_left`

### Retry policy

Each consumer maintains a retry counter per message using a Redis Hash key:
```
retry_count::{original_stream_id}
```
TTL: 300 seconds (auto-expires after 5 minutes regardless of outcome).

**Retry sequence:**
1. Message pulled from stream, processing fails with exception.
2. Consumer increments `HINCRBY retry_count::{msg_id} count 1`.
3. If count < 3: re-ACK and re-add to the pending queue via `XCLAIM` with a short
   delay (500 ms). This simulates re-delivery.
4. If count >= 3: publish to `dlq::{stream}` with full DLQ envelope (see Section 3.8),
   then `XACK` the original message to remove it from pending.

**Implementation:**
```python
MAX_RETRIES = 3
RETRY_DELAY_MS = 500

def process_with_retry(redis_client, group, consumer, stream, msg_id, fields, handler):
    retry_key = f"retry_count::{msg_id}"
    count = int(redis_client.hincrby(retry_key, "count", 1))
    redis_client.expire(retry_key, 300)

    try:
        handler(fields)
        redis_client.xack(stream, group, msg_id)
    except Exception as exc:
        if count < MAX_RETRIES:
            # Re-claim after delay: another worker (or same) will pick it up
            redis_client.xclaim(
                stream, group, consumer, RETRY_DELAY_MS, [msg_id]
            )
        else:
            # Send to DLQ
            dlq_key = f"dlq::{stream}"
            redis_client.xadd(dlq_key, {
                "original_stream":  stream,
                "original_msg_id":  msg_id,
                "original_fields":  json.dumps(dict(fields)),
                "error_class":      type(exc).__name__,
                "error_message":    str(exc)[:1000],
                "retry_count":      str(count),
                "failed_at":        str(time.time()),
                "consumer_name":    consumer,
                "group_name":       group,
            }, maxlen=1000)
            redis_client.xack(stream, group, msg_id)
```

### What triggers a DLQ entry

| Trigger | Stream | Notes |
|---------|--------|-------|
| JSON parse failure in `detections` field | `person_detections::{cam}` | Malformed YOLO output |
| Base64 decode failure of `jpeg_b64` or `*_crop_b64` | Any | Corrupt frame in transit |
| YOLO inference exception (OOM, model crash) | DLQ is in worker, not stream | Worker logs + DLQ |
| ArcFace inference exception | `face_crops` | DeepFace model failure |
| Disk write failure in face-db-writer | `identity_results` | Filesystem full |
| FrameReorderBuffer overflow (> BUFFER_CAPACITY) | `person_detections::{cam}` | YOLO pool backlog |
| Re-ID feature vector dimension mismatch (not 2048) | `reid_features` | Model version mismatch |

### DLQ monitoring

A lightweight monitoring consumer reads each `dlq::*` stream with a simple loop
(no consumer group, single consumer, `XREAD` from `0-0`) and:
1. Emits a Prometheus counter: `dlq_messages_total{stream="...", error_class="..."}`
2. Logs the full DLQ envelope at ERROR level.
3. Does not delete DLQ messages — they persist for forensic inspection.

DLQ streams use `MAXLEN 1000` (approximate). Entries older than the MAXLEN window are
trimmed. For compliance/audit use cases, point a log shipper at the monitoring consumer
output instead of relying on Redis persistence.

---

## 8. Redis Deployment Recommendation

### Topology: Standalone with AOF persistence

**Recommended:** Single Redis 7.x instance (standalone) with Append-Only File (AOF)
persistence using `appendfsync everysec`.

**Rationale:**
- At 4 cameras × 30 FPS, peak message throughput is ~120 raw frames/sec plus derived
  messages (~300 total msgs/sec). A single Redis instance handles >1 million ops/sec
  and is not the bottleneck.
- Redis Cluster partitions data across shards, but Redis Streams consumer groups cannot
  span shards. Cross-shard fan-out would require application-level routing, adding
  complexity without benefit at this scale.
- Redis Sentinel (1 primary + 2 replicas) adds high availability with automatic failover
  in ~30 s. Use Sentinel if uptime SLA requires it. Connection to Sentinel requires
  Sentinel-aware clients (`redis-py` supports this natively).

**For production (> 4 cameras or SLA requirement):** Use Redis Sentinel with 1 primary
and 2 replicas. Sentinel election time is 10–30 s, during which services reconnect.
Design all workers to reconnect on `ConnectionError` with exponential back-off (max 30 s).

### Memory estimate

| Stream | MAXLEN | Avg msg size | Memory |
|--------|--------|--------------|--------|
| `shared_raw_frames` | 600 | ~35 KB (1280×720 JPEG q=85 ≈ 80 KB raw → ~35 KB JPEG, then Base64 ≈ 47 KB per field + overhead) | ~28 MB |
| `person_detections::{cam}` × 4 | 150 each | ~800 B (bbox JSON, no image) | ~0.5 MB |
| `person_tracks::{cam}` × 4 | 300 each | ~20 KB (512×1024 person crop JPEG q=95 ≈ 15 KB → Base64 ≈ 20 KB) | ~24 MB |
| `face_crops` | 200 | ~8 KB (68×82 face crop JPEG q=95 → Base64 ≈ 7 KB + fields) | ~1.6 MB |
| `reid_features` | 200 | ~18 KB (2048 floats as JSON ≈ 16 KB + 512 floats color ≈ 4 KB) | ~3.6 MB |
| `identity_results` | 500 | ~8 KB (propagated face crop + identity fields) | ~4 MB |
| `action_events` | 200 | ~2 KB | ~0.4 MB |
| `dlq::*` × 8 | 1000 each | ~2 KB | ~16 MB |
| Redis overhead (tracking, pending lists) | — | — | ~20 MB |
| **Total** | | | **~98 MB** |

**Recommended Redis `maxmemory` setting:** `256mb`  
**Eviction policy:** `noeviction` — Redis must refuse writes rather than silently
evict stream entries. Backpressure handling (Section 6) is the correct mechanism for
load shedding, not eviction.

```
# redis.conf excerpt
maxmemory 256mb
maxmemory-policy noeviction
appendonly yes
appendfsync everysec
save ""   # Disable RDB snapshots (AOF is sufficient)
```

### Key expiry

Redis Streams manage retention via `MAXLEN`, not TTL. Do not set TTL on stream keys.

The retry counter keys (`retry_count::*`) use `EXPIRE 300` (set in application code).

The global tracker stores mutable state in Redis hashes outside of Streams:
```
global_id::{camera_name}::{track_id}  →  STRING, value = global_id (int)
```
Set TTL to 30 s (refreshed on each update). This prevents stale camera-to-global
mappings from accumulating when tracks are deleted.

### Connection pool settings (`redis-py`)

```python
import redis

pool = redis.ConnectionPool(
    host="redis",
    port=6379,
    max_connections=20,          # One pool per service pod
    socket_connect_timeout=5,
    socket_timeout=10,
    retry_on_timeout=True,
    health_check_interval=30,
)
client = redis.Redis(connection_pool=pool)
```

---

## 9. Field Reference Summary

Quick lookup for implementers.

| Field | Type | Source | Propagated through |
|-------|------|--------|-------------------|
| `request_id` | UUID4 string | cam-ingest | All downstream streams |
| `camera_name` | string | cam-ingest | All downstream streams |
| `camera_epoch` | uint32 string | cam-ingest | All downstream streams |
| `frame_index` | uint64 string | cam-ingest | All downstream streams |
| `track_id` | int string | deepsort-tracker | person_tracks, face_crops, reid_features, identity_results, action_events |
| `track_epoch` | uint32 string | deepsort-tracker | Same as track_id |
| `face_id` | string (composite) | face-recog-worker | identity_results |
| `global_id` | int string or "" | global-tracker (via Redis GET) | identity_results, action_events |
| `timestamp` | float string | Each service (wall clock at publish time) | Not propagated — each service sets own |
| `inference_ms` | float string | Inference workers | Not propagated |

---

## 10. Implementation Checklist

Before a service is considered complete, verify:

**cam-ingest:**
- [ ] Assigns `frame_index` atomically using `INCR camera_frame_counter::{camera_name}`
- [ ] Publishes `camera_epoch` (increments on pod start via `INCR camera_epoch::{camera_name}`)
- [ ] Resizes frames to max 1920×1080 before JPEG encoding
- [ ] Uses `XADD ... MAXLEN ~ 600` on every publish

**person-yolo-worker:**
- [ ] Reads from `shared_raw_frames` via `cg::person_yolo` consumer group
- [ ] Publishes to `person_detections::{camera_name}` (from message field, not hardcoded)
- [ ] Publishes empty detection array `[]` for frames with no persons
- [ ] Detections in LTWH format (verified against DeepSort API)

**deepsort-tracker-{cam}:**
- [ ] Initialized with `embedder=None`
- [ ] Uses `FrameReorderBuffer` before passing to `update_tracks()`
- [ ] Passes `frame=None` to `update_tracks()`
- [ ] Publishes one `person_tracks::{cam}` message per confirmed track per frame
- [ ] Sets `person_crop_b64 = ""` for crops below minimum size threshold
- [ ] Stores `global_id::{cam}::{track_id}` in Redis with 30 s TTL

**reid-feature-worker:**
- [ ] L2-normalizes feature vector before publishing
- [ ] Only publishes when crop >= 100×200 px
- [ ] Publishes on warmup completion (after 5 valid crops) and every 30 frames thereafter
- [ ] Uses `embedder=None` ResNet-50 preprocessing: ToPILImage → Resize(256,128) → ToTensor → Normalize

**face-yolo-worker:**
- [ ] Runs `yolov11n-face.pt` on person crop (not full frame)
- [ ] Converts face bbox from person-crop coordinates to full-frame coordinates
- [ ] Drops faces below 70×90 px (does not publish, does not DLQ)

**face-recog-worker:**
- [ ] Reads `global_id::{cam}::{track_id}` from Redis to populate `global_id` field
- [ ] Implements 3-strike Unknown threshold before publishing `is_new_user=true`
- [ ] Propagates `face_crop_b64` unchanged from input to output

**global-tracker:**
- [ ] Applies EMA with alpha=0.15 for Re-ID features: `new = alpha * incoming + (1-alpha) * existing`
- [ ] Re-normalizes blended vector: `vec / (norm(vec) + 1e-8)`
- [ ] Updates `global_id::{cam}::{track_id}` in Redis with 30 s TTL on every assignment
- [ ] Prunes GlobalPersons unseen for > 60 s to bound memory

**All workers:**
- [ ] Implements retry-then-DLQ logic (max 3 retries, 500 ms delay)
- [ ] Reconnects to Redis on `ConnectionError` with exponential back-off
- [ ] Exposes `/health` HTTP endpoint (liveness probe)
- [ ] Emits Prometheus metrics for consumer lag, inference latency, and DLQ count
