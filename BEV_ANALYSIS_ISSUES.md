# Bird's Eye View Implementation Analysis

## Issues Found

### 1. **Person Position Projection Issue**
Your debug output shows persons are detected and tracked, BUT they appear to NOT be aligned with stereo-vision projected dots. This happens because:

#### Root Cause: Homography Projection in Debug Mode
In `BirdsEyeViewWidget.py`, the debug mode shows **per-camera projections** that may differ from the final **stereo-calculated global position**:

```python
def _draw_debug_projections(self, person):
    # Draws INDIVIDUAL camera projections (red dot for Cheap, blue dot for HD)
    # These are homography projections from frame → world
    # THEN draws GLOBAL position (green circle) from stereo triangulation
```

**What's happening:**
- Each camera projects the detected face to world coordinates using homography
- The stereo vision system triangulates from 2+ camera detections → global position
- These may NOT coincide if:
  1. **Homography is incorrect** (camera calibration off)
  2. **Camera rotations are wrong** (see issue #2 below)
  3. **Person is not on the ground plane** (homography assumes Z=0)
  4. **Stereo triangulation has errors** (re-projection error in triangulation)

---

### 2. **Camera Direction Mismatch** ⚠️ CRITICAL
The camera arrows in BEV are pointing in DIFFERENT directions than the camera settings page!

#### Map File (Modifide.json):
```
Cheap:  Rotation = 91.46°  →  Points RIGHT (East)
HD:     Rotation = 1.86°   →  Points NORTH (Up)
```

#### BEV Rendering Code (Line 155-160):
```python
# Draw direction indicator (arrow pointing in rotation direction)
rotation_rad = math.radians(self.rotation)
indicator_length = camera_size + 8
tip_x = scaled_x + indicator_length * math.sin(rotation_rad)
tip_y = scaled_y - indicator_length * math.cos(rotation_rad)  # Negated to point up at 0°
```

**This is CORRECT mathematically** - it properly converts degrees to screen coordinates.

**BUT the issue is:** Are the rotation values in your map correct for where cameras are actually pointing?

---

### 3. **Homography Projection Details**

The homography projection (`HomographyProjector.py`) works as follows:

```
Frame coordinates (0-640, 0-480)
            ↓ homography H
World coordinates (camera_pos adjusted)

For a person detected at frame position (320, 400):
1. Normalize to camera FOV angles
2. Compute distance along camera gaze direction
3. Rotate to world coordinates based on camera rotation
4. Add camera position offset
```

**Key Parameters:**
- `camera_pos`: Where camera is on the floor plan
- `camera_rotation`: Which direction camera points
- `fov_degrees`: How wide the camera sees
- `view_range`: Maximum visible distance (400m in your map)

---

## Current Camera Configuration

### Cheap Camera
- **Position**: (243.5, 56.0) - Right side of map
- **Rotation**: 91.46° - Pointing RIGHT (toward positive X)
- **FOV**: 46°
- **View Range**: 400.0 units

### HD Camera  
- **Position**: (3.0, 157.5) - Left side of map
- **Rotation**: 1.86° - Pointing UP/NORTH (toward positive Y)
- **FOV**: 42°
- **View Range**: 400.0 units

---

## 🚨 CRITICAL BUG FOUND: Homography Projection is Completely Broken

### The Problem
Running the debug script shows that **ALL frame coordinates project back to the CAMERA POSITION** instead of the expected world coordinates!

```
Cheap Camera at (243.5, 56.0):
  Frame Center (320, 240)     → World (243.50, 56.00)    ✗ WRONG (should be somewhere far away)
  Frame Bottom-Center (320, 480) → World (243.50, 56.00) ✗ WRONG (should match center?)

HD Camera at (3.0, 157.5):
  Frame Center (320, 240)     → World (3.00, 157.50)     ✗ WRONG
  Frame Bottom-Center (320, 480) → World (3.00, 157.50)  ✗ WRONG
```

### Root Cause: Homography Matrix is Degenerate

The homography matrices are near-zero in almost all elements:
```
Cheap: [[1.88e-16,  9.75e-01, -7.45e-13],
        [8.09e-16,  2.24e-01,  5.91e-14],
        [5.37e-21,  4.00e-03,  5.03e-15]]

HD:    [[1.96e-15,  1.90e-02, -7.99e-13],
        [4.19e-17,  9.99e-01,  9.55e-12],
        [-3.23e-19, 6.35e-03,  1.73e-14]]
```

This indicates the **camera calibration computation is wrong**.

### Debugging Checklist

### ✗ Homography is Computing INCORRECTLY
The issue is in `HomographyProjector.compute_homography_from_calibration()` around lines 108-130.

When computing world coordinates from frame points:
```python
# Current (BROKEN) code:
for fx, fy in frame_ref_points:
    norm_x = (fx / frame_width) - 0.5
    norm_y = fy / frame_height
    
    angle = norm_x * fov_degrees / 2
    distance = view_range * (1.0 - norm_y)
    
    angle_rad = math.radians(angle)
    local_x = distance * math.sin(angle_rad)
    local_y = distance * math.cos(angle_rad)
    
    # Rotate to world
    world_x = (local_x * cos(rotation) - local_y * sin(rotation) + cam_x)
    world_y = (local_x * sin(rotation) + local_y * cos(rotation) + cam_y)
```

**The problem:** The frame corners [0,0], [width,0], [width,height], [0,height] should map to 4 corners of a visible rectangle on the ground, but the current calculation is producing degenerate/nearly-identical points.

### ✓ Check if Person Detection is at Ground Level
The homography assumes the person's bounding box **bottom** is on the ground plane:
```python
# In HomographyProjector.project_bbox_to_world()
# Currently uses bbox CENTER, should maybe use bbox BOTTOM?
cy_bottom = bbox[1] + bbox[3]  # Bottom of bbox
```

### ✓ Check Camera Rotation Values
Run in calibration/camera settings page:
1. Manually point camera and verify it matches the rotation value
2. Take a reference image, note camera's orientation
3. Update map JSON with corrected rotation values

### ✓ Check Stereo Triangulation
In `GlobalPersonTracker.py`, verify the stereo vision calculation:
- Are you using both camera projections?
- Is the triangulation algorithm correct?
- Check the re-projection error

---

## Recommendation: Next Steps

1. **Enable per-camera debug logging** in homography projection
   - Print what each camera sees
   - Compare frame coordinates → projected world coordinates
   
2. **Verify camera calibration**
   - Place a known object at a known world position
   - Check if detected bbox projects to that position
   - If not, adjust camera rotation/position in map

3. **Test with stationary reference point**
   - Place person at (100, 100) world coordinates
   - Run debug mode
   - Should see:
     - Cheap camera projects to ~(100, 100)
     - HD camera projects to ~(100, 100)
     - Green stereo dot at ~(100, 100)
   - If they don't match → homography or camera params are wrong

4. **Add coordinate validation**
   - Check that projected world coordinates are within map bounds
   - Verify no NaN or infinity values in projections

