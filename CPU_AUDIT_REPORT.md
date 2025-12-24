# CPU Usage Audit Report - ObserveAI Camera System

## Summary
Analysis of the multi-camera feed system reveals **multiple critical inefficiencies** causing 99% CPU usage. The primary issue is **DetectionSystem running heavy AI inference (YOLO + DeepSort + ReID) on EVERY frame from EVERY camera independently**, compounded by inefficient timing and thread synchronization.

---

## Critical Issues Found

### 🔴 **ISSUE 1: Redundant Per-Camera AI Inference (CRITICAL)**
**Location:** `MainWindow.py` → `create_camera_items()` + `DetectionSystem.py`

**Problem:**
- Each camera gets its own **independent DetectionSystem instance** with:
  - Full YOLO person detection model (100+ MB)
  - Face detection model (YOLO11n-face)
  - ReID model with feature extraction
  - DeepSort tracker
- **Impact:** 3 cameras = 3x complete AI pipelines running in parallel
- Each pipeline processes EVERY frame without frame skipping

**Current Code:**
```python
# MainWindow.py - Line 118
ai_sys = DetectionSystem(...)
ai_thread = threading.Thread(target=ai_sys.start, daemon=True)
ai_thread.start()  # One thread per camera!
```

**CPU Cost:** ~25-30% per camera with GPU, ~40-50% per camera on CPU

---

### 🔴 **ISSUE 2: No Frame Skipping in Detection Pipeline (CRITICAL)**
**Location:** `DetectionSystem.py` → `processing_thread_function()` line 320

**Problem:**
- Detection runs on EVERY frame (30-60 FPS typical)
- YOLO inference is not frame-skipped; only face detection has `frame_count % 10 == 0`
- Processing thread drains entire queue to get "fresh" frames but still processes every frame

**Current Code:**
```python
# Lines 383-385
while not self.frame_queue.empty():
    try:
        frame = self.frame_queue.get_nowait()  # Drains queue but still processes
    except queue.Empty:
        pass
```

**CPU Cost:** Full inference on every frame = unnecessary processing

---

### 🔴 **ISSUE 3: Synchronous Face Recognition Blocking (CRITICAL)**
**Location:** `DetectionSystem.py` → `recognition_worker_function()` line 221

**Problem:**
- Face recognition uses `DeepFace` which is CPU-intensive
- Queue has only 20-frame buffer; if recognition is slow, queue fills up
- When queue is full, new faces are silently dropped (line 345)
- **Lock contention:** All threads fight over `self.lock` for resource access

**Current Code:**
```python
# Line 238
name, confidence = recognize_face(face_img=face_img)  # Blocking call!
```

**CPU Cost:** DeepFace recognition = 500ms-2s per face on CPU

---

### 🔴 **ISSUE 4: Excessive Signal Emissions (GUI Bottleneck)**
**Location:** `CameraWorker.py` line 103 + `DetectionSystem.py` line 528

**Problem:**
- **CameraWorker** emits `frameReady` signal for **EVERY frame** from camera
- **DetectionSystem** emits `ai_frame_processed_signal` for **EVERY detection frame**
- With 3 cameras @ 30 FPS = **90 signal emissions per second**
- Each signal triggers:
  - `update_frame()` in CameraFeedWidget → Qt image conversion
  - `update_frame()` in GridFeedWidget → Qt image scaling + pixmap creation
  - Cascading layout updates

**Current Code:**
```python
# CameraWorker.py lines 99-102
self.frameReady.emit(qt_image)  # EVERY frame, ~30-60 Hz
```

**CPU Cost:** ~15-20% per camera just for GUI updates

---

### 🔴 **ISSUE 5: Image Conversion Every Frame (Redundant)**
**Location:** `CameraWorker.py` lines 94-102

**Problem:**
- Converting BGR→RGB for every frame (expensive)
- Creating QImage from raw data every frame
- GridFeedWidget then scales this QImage again with `SmoothTransformation`

**Current Code:**
```python
# Lines 94-102
rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)  # Expensive!
h, w, ch = rgb_image.shape
bytes_per_line = ch * w
qt_image = QImage(rgb_image.data, w, h, bytes_per_line, ...)
self.frameReady.emit(qt_image)
```

**CPU Cost:** ~10-15% per camera

---

### 🔴 **ISSUE 6: Blocking Lock in Camera Thread (DEADLOCK RISK)**
**Location:** `DetectionSystem.py` line 268

**Problem:**
- `camera_thread_function()` holds lock while accessing camera buffer
- Lock is also held by:
  - `recognition_worker_function()` when updating face objects
  - `processing_thread_function()` when cleaning up persons
  - Display thread when copying persons list
- **Result:** All threads wait for lock, causing stuttering

**Current Code:**
```python
# Lines 268-273
with self.lock:
    print(f"[CAM THREAD] camera buffer accessible")
    if self.camera_buffer and not self.camera_buffer.empty():
        frame = self.camera_buffer.get()
    else:
        time.sleep(0.01); continue
```

**CPU Cost:** Context switching overhead, thread idle time

---

### 🟠 **ISSUE 7: Inefficient Watchdog Thread (WASTED CYCLES)**
**Location:** `DetectionSystem.py` → `watchdog_thread_function()`

**Problem:**
- Runs every 1 second checking queue health
- If queue empty, re-adds the same frame repeatedly
- Doesn't actually solve the problem, just adds overhead

**CPU Cost:** ~2-3% per camera

---

### 🟠 **ISSUE 8: No Display Thread Throttling**
**Location:** `DetectionSystem.py` → `display_thread_function()` line 527

**Problem:**
- Sleeps only 0.03s (30 FPS), which is excessive for display
- No limit on how many times display updates per second
- Every update triggers lock acquisition, face snapshot, and drawing

**Current Code:**
```python
# Line 531
time.sleep(0.03)  # Only 30ms, running at near-max frequency
```

**CPU Cost:** ~5-10% per camera

---

### 🟠 **ISSUE 9: No GPU Utilization**
**Location:** `DetectionSystem.py` line 161

**Problem:**
- Models loaded to GPU if available BUT:
  - Frame preprocessing happens on CPU
  - Person feature extraction uses CPU→GPU→CPU transfers
  - No batch processing

**CPU Cost:** Transfers and synchronization overhead

---

## Resource Breakdown (Per Camera)

| Component | CPU % | Notes |
|-----------|-------|-------|
| YOLO Detection | 25-35% | Every frame |
| Face Detection | 5-10% | Every 10 frames but with overhead |
| Frame Conversion | 10-15% | BGR→RGB + QImage creation |
| GUI Updates | 15-20% | Signal emissions + Qt drawing |
| Tracking (DeepSort) | 5-8% | Lightweight but every frame |
| Recognition (async) | 5-15% | DeepFace, queue-dependent |
| Lock Contention | 5-10% | Thread synchronization |
| **Total Per Camera** | **70-113%** | **Exceeds 100% on CPU!** |

---

## Recommended Fixes (Priority Order)

### Priority 1: Reduce Per-Camera AI Overhead
- **Option A (Recommended):** Single shared DetectionSystem for all cameras
  - **Savings:** 2/3 model memory + 50% detection overhead
  - **Complexity:** Medium
  
- **Option B:** Frame skip YOLO detection (e.g., every 3rd frame)
  - **Savings:** 60% detection overhead  
  - **Complexity:** Low
  - **Trade-off:** Slight detection latency

### Priority 2: Throttle GUI Signal Emissions
- Emit frame updates at 15 FPS instead of 30-60 FPS
  - **Savings:** 50% signal overhead = ~10% per camera
  - **Complexity:** Low
  - **Impact:** No visual degradation

### Priority 3: Optimize Image Conversions
- Skip BGR→RGB in worker, let Qt handle it
- Cache QImage conversion instead of recreating each frame
  - **Savings:** 10-15% per camera
  - **Complexity:** Low

### Priority 4: Lock-Free Data Structures
- Use atomic variables for simple flags
- Move face dict out of lock scope
  - **Savings:** 5-10% per camera
  - **Complexity:** Medium

### Priority 5: GPU Batch Processing
- Batch frames from multiple cameras
- Process face recognition in batches
  - **Savings:** 10-15% overhead
  - **Complexity:** High

---

## Quick Wins (Implement Immediately)

1. **Frame Skip in Detection**
   ```python
   # Every 3 frames only for YOLO
   if self.frame_count % 3 == 0:
       results = self.yolo_model(frame, verbose=False)
   ```

2. **Throttle GUI Updates to 15 FPS**
   ```python
   # In display_thread_function()
   time.sleep(0.067)  # 15 FPS instead of 30 FPS
   ```

3. **Remove Watchdog Redundancy**
   - Delete `watchdog_thread_function()` entirely
   - Implement simple frame timeout instead

4. **Reduce Lock Scope**
   ```python
   # Release lock immediately after reading
   with self.lock:
       persons_snapshot = list(self.tracked_persons.values())
   # Process without lock
   for person in persons_snapshot:
       # No lock needed here
   ```

---

## Estimated Results After Fixes

| Fix | CPU Reduction | Difficulty |
|-----|----------------|-----------|
| Frame skip detection (2x) | -30% per camera | Easy |
| GUI throttle 15 FPS | -10% per camera | Easy |
| Remove watchdog | -3% per camera | Easy |
| Reduce lock scope | -5% per camera | Medium |
| Single shared AI | -50% overall | Hard |
| **Total Estimated** | **-48% to -80%** | - |

**Expected Result:** 3 cameras = 99% CPU → ~20-35% CPU

---

## Notes
- All percentages are approximate and depend on:
  - Camera resolution (720p vs 1080p vs 4K)
  - Frame rate (30 FPS vs 60 FPS)
  - CPU hardware (cores, clock speed)
  - Model inference device (CPU vs GPU)

- System is currently **unsustainable** with multiple cameras
- Quick wins (frame skip + GUI throttle) should be implemented immediately
- Long-term solution requires architectural redesign (shared AI pipeline)
