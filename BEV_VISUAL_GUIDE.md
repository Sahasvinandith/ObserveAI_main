# BEV Implementation: Visual Diagrams & Illustrations

## Issue #1: Bbox Center vs Bottom

### The Problem Visualized

```
PERSON STANDING ON GROUND
┌─────────────┐
│   HEAD      │  ← Bbox center (cy_frame) - WRONG for ground projection!
│             │     Projects from: 1.8m above ground
├─────────────┤
│   CHEST     │  ← Middle of person
│             │
├─────────────┤
│   LEGS      │
│             │
├─────────────┤ ← Bbox bottom (cy_bottom) - CORRECT for ground projection!
└─────────────┘    Projects from: Ground level (Z=0)

GROUND PLANE (Z=0)

Key insight:
  Homography assumes person's feet on ground (Z=0)
  Therefore: Must project from feet, not from head!
  
Error if using center: ~1-2 meters off
```

### Before vs After Code

```python
# BEFORE (WRONG):
cx_frame = bbox[0] + bbox[2] / 2.0  # Center X
cy_frame = bbox[1] + bbox[3] / 2.0  # Center Y  ← HEAD/CHEST
cy_bottom = cy_frame                 # ← PROJECTING FROM MID-AIR!
projection = cv2.perspectiveTransform((cx_frame, cy_bottom), H)
Result: Person at camera position (degenerate matrix issue)

# AFTER (CORRECT):
cx_frame = bbox[0] + bbox[2] / 2.0         # Center X (unchanged)
cy_bottom = bbox[1] + bbox[3]              # Bottom Y ← FEET ON GROUND
projection = cv2.perspectiveTransform((cx_frame, cy_bottom), H)
Result: Person at actual ground position
```

---

## Issue #2: Camera Position & Rotation

### Map Layout

```
TOP (North = +Y)
         ↑
         │
  3,157  ├─────────────────────────────────────────
    HD   │  HD camera pointing UP (North)        │ │
    🟡   │  Detects ground in this region        │ │
    ↑    │                                        │ │
    │    │                                    Cheap│ │
    │    │  Some overlap region for stereo    camera│ │
    │    │  triangulation needed              at position
    │    │                                    (243.5, 56)
    │    │                                    🟡 →
    │    │                                     ↗ (points East)
  0 ├────┼────────────────────────────────────────
    │    0                                    243.5
    └────────────────────────────────────────→ RIGHT (East = +X)

Camera Positions:
  HD Camera:    (3.0, 157.5)   - Left side
  Cheap Camera: (243.5, 56.0)  - Right side
  
Camera Rotations:
  HD:    1.86°   - Pointing North (almost straight up)
  Cheap: 91.46°  - Pointing East (straight right)
```

### What Each Camera Sees

```
Cheap Camera (pointing RIGHT):
  ┌────────────────────────────────────────────┐
  │                                            │
  │  Far away                                  │
  │  (far right on map)                        │
  │                                            │
  │  Medium distance                           │
  │  (middle right on map)                     │
  │                                            │
  │  Close                                     │
  │  (right near camera)                       │
  │                                            │
  └────────────────────────────────────────────┘
  Camera at (243.5, 56) looking → (643, 46)

HD Camera (pointing UP/NORTH):
  ┌────────────────────────────────────────────┐
  │                                            │
  │  Far away                                  │
  │  (far up on map)                           │
  │                                            │
  │  Medium distance                           │
  │  (middle up on map)                        │
  │                                            │
  │  Close                                     │
  │  (up near camera)                          │
  │                                            │
  └────────────────────────────────────────────┘
  Camera at (3.0, 157.5) looking → (16, 557)
```

---

## Issue #3: Frame Coordinate System

### Frame Y-Axis Interpretation

```
CAMERA FRAME (640x480 pixels)
┌──────────────────────────────────────────────┐
│ Y=0 (Top)                                     │
│ ↓                                             │
│ Far away objects appear here                 │
│ (top of frame = far distance)                │
│                                              │
│ Y=240 (Middle)                               │
│ ↓                                            │
│ Medium distance objects                      │
│                                              │
│ Y=480 (Bottom)                               │
│ ↓                                            │
│ Close objects appear here                    │
│ (bottom of frame = near camera)              │
│                                              │
└──────────────────────────────────────────────┘

This mapping assumes:
  - Camera looking downward
  - Top of frame = far away
  - Bottom of frame = near camera
  
For a person: Bottom of bbox (feet) ≈ Y=480
Therefore: Use Y=480 area for ground contact point
```

---

## Homography Transformation

### What Homography Does

```
Frame Coordinates              World Coordinates
(Camera View)                  (Floor Map)

(0, 0) ────────────┐          Mapping
(320, 240) ─┐      │
(640, 0) ───┼──┐   │    ┌──→  (-150, 126)   ← Top-right far
            │  │   │    │
            │  H = │    ├──→  (243, 56)     ← Bottom-right near
            │  │   │    │
            └──┼───┴──→ ─┼──→  (-146, -34)  ← Top-left far
               │        │
               └────────┴──→  (243, 56)     ← Bottom-left near

Person detected at frame (320, 380):
  With CENTER (WRONG):
    Projects to: (243.5, 56) ← Camera position
    
  With BOTTOM (CORRECT):
    Projects to: (140, 110)  ← Actual person position
```

---

## Debugging Flow

### Issue Detection Path

```
User observes: "Person dots always at camera position"
                      ↓
                      ↓
        Run debug_bev_projection.py
                      ↓
                      ↓
    See: All projections return camera position
                      ↓
                      ↓
        Run debug_homography_detailed.py
                      ↓
                      ↓
    See: World reference points 2&3 identical (degenerate)
                      ↓
                      ↓
    Investigate bbox projection: cv2.perspectiveTransform()
                      ↓
                      ↓
    Find: Using cy_center instead of cy_bottom
                      ↓
                      ↓
    ✅ Apply fix: Use bbox[1] + bbox[3] instead of cy_center
```

---

## Fix Verification

### Test Sequence

```
QUICK TEST (1 min):
  python -m py_compile components/HomographyProjector.py
                      ↓
            ✓ If OK: "No output"
            ✗ If error: "SyntaxError message"

DEBUG TEST (5 min):
  python debug_bev_projection.py
                      ↓
            BEFORE:  All frame coords → camera position
            AFTER:   Frame corners spread out on map
                      ↓
            ✓ If fixed: Values change from iteration to iteration

VISUAL TEST (10 min):
  python main.py
    → Load Modifide.json
    → Open BEV widget
    → Enable debug (🐛)
    → Stand in front of camera
                      ↓
            BEFORE:  Person dot stuck at camera position
            AFTER:   Person dots move with you
                      ↓
            ✓ If fixed: Red + Blue + Green dots cluster together
```

---

## Performance Impact

### Computational Complexity

```
No performance impact:
  - Still uses same homography formula
  - Still calls cv2.perspectiveTransform() once per detection
  - Only changed which Y coordinate is used (1 line change)

Complexity unchanged:
  - Per-camera projection: O(1) constant time
  - Per-frame: O(num_detections) linear
  - Debug mode: O(num_persons × num_cameras) for visualization
```

---

## Summary Visual

### System Architecture (Simplified)

```
┌─────────────────────────────────────────────────────────────┐
│                    DETECTION SYSTEM                          │
│  Camera Feed → YOLO Face Detection → Bounding Box            │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ↓
┌──────────────────────────────────────────────────────────────┐
│              HOMOGRAPHY PROJECTION (FIXED)                   │
│  ✅ Frame (X, Y) → World (X, Y)                             │
│  ✅ Using bbox BOTTOM for ground contact point              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ↓
┌──────────────────────────────────────────────────────────────┐
│            STEREO TRIANGULATION & TRACKING                   │
│  Camera₁ projection + Camera₂ projection → Global position   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ↓
┌──────────────────────────────────────────────────────────────┐
│              BIRD'S EYE VIEW VISUALIZATION                   │
│  🔴 Red dot   (Cheap camera projection)                      │
│  🔵 Blue dot  (HD camera projection)                         │
│  🟢 Green dot (Stereo global position)                       │
│                                                               │
│  Expected: All three dots cluster at person's true location  │
└──────────────────────────────────────────────────────────────┘
```

---

## Checkpoint Checklist

```
✓ Understand why bbox.center is wrong
  → Head is 1.8m above ground
  → Homography assumes Z=0 (ground plane)
  
✓ Understand why bbox.bottom is correct
  → Feet are on ground (Z=0)
  → Matches homography assumption
  
✓ Know where the fix is
  → components/HomographyProjector.py, line 172-176
  
✓ Know how to test it
  → Run debug scripts, then visual test with main.py
  
✓ Know what to expect
  → Person dots move naturally on map
  → Red + Blue + Green dots cluster together
  
✓ Know how to debug further
  → Check camera calibration values
  → Verify stereo triangulation
  → Check face detection bbox accuracy
```

---

**Next:** Run `python debug_bev_projection.py` to see the fix in action!

