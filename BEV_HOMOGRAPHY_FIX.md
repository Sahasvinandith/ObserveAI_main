# Fix for BEV Homography Projection Bug

## Problem Analysis

The homography computation has a fundamental flaw:

### Frame Coordinates vs World Mapping
```
Frame Y=0 (top)     → distance=400 → far away from camera
Frame Y=240 (mid)   → distance=200 → medium distance
Frame Y=480 (bottom) → distance=0  → AT THE CAMERA POSITION
```

When `distance = 0`, both bottom corners map to the camera position (243.5, 56.0) or (3.0, 157.5).

This creates a **degenerate quadrilateral** for the homography:
- Corners 2 and 3 are IDENTICAL  
- OpenCV's `getPerspectiveTransform()` cannot properly invert this

### The Real Issue

The **conceptual model is wrong**:
- Current code assumes: Frame Y=480 (bottom) is where the camera sees the ground directly below it
- This is backwards for looking-down cameras!

For a camera mounted looking downward:
- **Top of frame (Y=0)** should be closest to camera (on ground right below)
- **Bottom of frame (Y=480)** should be farthest away

The code currently has this INVERTED!

---

## Solution: Fix the Homography Computation

The fix is in [components/HomographyProjector.py](components/HomographyProjector.py#L115-L130), specifically the distance calculation:

### Current (BROKEN):
```python
norm_y = fy / frame_height
distance = view_range * (1.0 - norm_y)
# This gives: Y=0 → dist=400 (far), Y=480 → dist=0 (camera)
```

### Fixed (CORRECT):
```python
norm_y = fy / frame_height  
distance = view_range * norm_y  
# This gives: Y=0 → dist=0 (close), Y=480 → dist=400 (far)
```

**OR** If your camera setup actually has Y=480 as the close point:
```python
# Then swap the mapping - Y=480 is at camera, Y=0 is far
# This would be unusual for a downward-looking camera
```

---

## Verification

After applying the fix, the world points should be:

```
Cheap Camera:
  Frame (0, 0)     →  Far left of camera view
  Frame (640, 0)   →  Far right of camera view
  Frame (640, 480) →  Close right of camera view (near camera)
  Frame (0, 480)   →  Close left of camera view (near camera)

HD Camera:
  Frame (0, 0)     →  Far left of camera view
  Frame (640, 0)   →  Far right of camera view
  Frame (640, 480) →  Close right of camera view
  Frame (0, 480)   →  Close left of camera view
```

With non-identical corners, the homography will be proper and invertible.

---

## Additional Consideration: What Does Y=480 Actually Represent?

You need to determine:
1. **Is Y=480 the bottom of the frame from the camera's perspective?**
   - If camera is looking DOWN and mounted overhead, then Y=480 might be the foreground (close)
   - If camera is looking UP or at an angle, Y=480 might be the background (far)

2. **For ground plane projection, what should the mapping be?**
   - Typically: top of frame = distance away, bottom of frame = closer

3. **Check your actual camera setup**
   - Look at a test frame from your camera
   - Mark where objects appear in the frame vs their real world position
   - Verify the Y-axis mapping is correct

---

## Implementation Steps

1. **Modify [components/HomographyProjector.py](components/HomographyProjector.py#L115)**:
   ```python
   # Line ~115, change:
   # OLD: distance = view_range * (1.0 - norm_y)
   # NEW: distance = view_range * norm_y
   ```

2. **Run the debug script again**:
   ```bash
   python debug_homography_detailed.py
   ```
   Verify that world points are now properly spread out (not degenerate).

3. **Test with real person detection**:
   - Enable BEV debug mode (press 🐛 button)
   - See if person projections from each camera now cluster near each other
   - Compare with green stereo position

4. **If projections are still wrong**:
   - The issue might be camera calibration (position/rotation in map is wrong)
   - Or camera mounting angle (camera might not be looking straight down)

