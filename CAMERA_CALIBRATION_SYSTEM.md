# Camera Calibration System - Current Implementation

## Overview
The ObserveAI camera calibration system automatically determines a camera's position and rotation on the floor map using reference points. The user marks corresponding points on both the floor map and the camera feed, and the system solves for the camera's location mathematically.

## Architecture

### Components

#### 1. **MainWindow Calibration Interface** (main/MainWindow.py)
Handles user interactions and orchestration of the calibration workflow.

**Key Methods**:
- `_start_calibration(camera_name)`: Enters calibration mode for a specific camera
- `eventFilter(source, event)`: Captures mouse clicks on the floor map
- `keyPressEvent(event)`: Handles Escape key for cancellation
- `_on_calibration_click(world_x, world_y)`: Processes map clicks and opens image dialog
- `_finish_calibration()`: Runs the solver and applies results
- `_cancel_calibration()`: Cancels the process
- `_cleanup_calibration()`: Cleans up visual markers and state
- `_on_camera_context_menu(camera_name)`: Shows calibration option in right-click menu

**State Management**:
- `_calibration_camera`: Currently calibrated camera name
- `_calibration_points`: List of CalibrationPoint objects
- `_calibration_markers`: Visual markers on the scene
- `_calibration_active`: Boolean flag for calibration mode

#### 2. **CameraCalibrator Module** (components/CameraCalibrator.py)
Mathematical solver for camera position and rotation.

**Key Class: CalibrationPoint**
```python
class CalibrationPoint:
    world_x: float                  # Position on floor map (pixels)
    world_y: float                  
    frame_x_normalized: float       # Position in camera frame (0.0 = left, 1.0 = right)
```

**Key Function: solve_camera_position()**
- **Input**: 2+ CalibrationPoints, camera FOV, initial position guess, search radius
- **Output**: (camera_x, camera_y, rotation_degrees) or None

**Algorithm**:
1. **Coarse-to-Fine Grid Search**: Two-stage optimization
   - **Coarse**: ±search_radius around initial guess, 5-pixel steps
   - **Fine**: ±15 pixels around best coarse result, 0.5-pixel steps
2. **Error Function**: For each candidate position (cx, cy):
   - Compute actual angles from camera to each reference point
   - Compare to expected angles from frame positions
   - Minimize total squared angle error
3. **Rotation Computation**: Derived from the solution using the first calibration point

**Math Details**:
- For each frame position: `offset = (frame_x - 0.5) × FOV`
- Expected angle difference between two points: `offset_0 - offset_i`
- Actual angle to point: `angle = atan2(world_y - cy, world_x - cx)`
- Error: minimize `sum((actual_angle_diff - expected_angle_diff)²)`

#### 3. **ImageClickDialog** (components/ImageClickDialog.py)
Qt dialog for selecting a point in the camera feed.

**Features**:
- Displays the camera frame with crosshair cursor
- Auto-scales large frames to fit on screen
- Returns normalized X coordinate (0.0 = left edge, 1.0 = right edge)
- Maintains accuracy despite scaling
- Dark theme styling

## Calibration Workflow

### Step-by-Step Process

1. **Initiation**
   - User right-clicks a camera on the floor map
   - Selects "📐 Calibrate Position" from context menu

2. **Calibration Mode Entry**
   - System enters calibration mode
   - Event filter installed on graphics view
   - Instructions dialog shown to user

3. **Reference Point Capture** (repeat for each point)
   - User clicks a known location on the floor map (e.g., corner, intersection)
   - ImageClickDialog opens with live camera feed
   - User clicks the exact same physical spot in the camera view
   - System captures:
     - World coordinates: map click position
     - Frame coordinate: normalized X from image click
   - Visual markers added to map (P1, P2, etc.)

4. **Solution Computation**
   - User presses Escape or Right-click with 2+ points
   - `solve_camera_position()` executed
   - Grid search finds optimal camera position and rotation

5. **Result Review**
   - Dialog shows:
     - Old position and rotation
     - New position and rotation
     - Confirmation button
   - User can accept or reject

6. **Application**
   - Camera item repositioned on floor map
   - GlobalPersonTracker updated with new registration
   - Calibration markers cleaned up
   - Normal operation resumes

### Calibration State Diagram

```
START
  ↓
[_start_calibration()]
  ├→ Set _calibration_active = True
  ├→ Clear calibration points/markers
  ├→ Install event filter
  └→ Show instructions
  ↓
[Event Filter Active]
  ├→ Left-click: [_on_calibration_click()]
  │  ├→ Get latest camera frame
  │  ├→ Open [ImageClickDialog]
  │  ├→ Create CalibrationPoint
  │  ├→ Add visual marker
  │  └→ Loop (2+ points required)
  │
  └→ Right-click or Escape: [_finish_calibration()]
     ├→ Call solve_camera_position()
     ├→ Show result dialog
     ├→ Apply if confirmed
     └→ [_cleanup_calibration()]
        ├→ Remove event filter
        ├→ Clear markers
        └→ Reset state
  ↓
END (Resume normal operation)
```

## Configuration & Parameters

### Solver Parameters (Tunable in solve_camera_position)
- **search_radius**: 300.0 pixels (how far from initial guess to search)
- **coarse_step**: 5 pixels (coarse grid step)
- **fine_radius**: 15 pixels (fine search area)
- **fine_step**: 0.5 pixels (fine grid step)
- **error_threshold**: 0.01 radians (~5.7°)

### Validation Criteria
- **Minimum points**: 2 (more points improve accuracy)
- **Max error tolerance**: 0.01 radians (warning if exceeded)
- **Degenerate case check**: Rejects if camera position is too close to reference point

## Integration with GlobalPersonTracker

After successful calibration:
```python
self.global_tracker.register_camera(
    name=camera_name,
    position=(new_x, new_y),
    rotation=new_rotation,
    fov=fov,
    view_range=view_range
)
```

This enables:
- Spatial awareness in cross-camera matching
- Position estimation on floor map
- Stereo triangulation with multiple cameras

## Accuracy Considerations

### Factors Affecting Accuracy

**Positive Factors**:
- Using reference points far apart (maximizes angle differences)
- Using 3+ reference points (over-constrained system is more robust)
- Using prominent, unambiguous physical landmarks
- Accurate clicking on both map and frame

**Negative Factors**:
- Reference points close together (small angle differences)
- Using only 2 points (minimal constraint)
- Non-distinctive landmarks
- Camera distortion not accounted for
- Wide FOV lenses (non-linear perspective)

### Expected Precision
- **Position**: ±5-10 pixels typical
- **Rotation**: ±2-5 degrees typical
- **Improves with**: More reference points, better spacing, accurate clicks

## Error Handling

**Scenarios Handled**:
1. **No video feed available**: Dialog warning, calibration cancelled
2. **Degenerate position** (camera at reference point): Solver rejects
3. **High error threshold**: Warning shown but result accepted
4. **No solution found** (parallel rays): Calibration cancelled
5. **User cancellation**: Escape key or insufficient points

## Current Limitations

1. **Monocular Approach**: Uses only horizontal (X) frame coordinate
   - Could be enhanced with vertical (Y) information
   - Assumes person has feet on the floor

2. **Simplified Camera Model**: Ignores
   - Lens distortion
   - Camera tilt (assumes level camera)
   - Vertical FOV (only horizontal FOV used)

3. **2D Assumption**: Treats floor as completely flat
   - Works well for true ground-level reference points
   - May be less accurate with elevated features

4. **Manual Process**: Requires user to identify matching points
   - Could be semi-automated with feature detection
   - Could use known-size objects for automatic scaling

## Future Enhancement Possibilities

1. **Vertical Coordinate Integration**
   - Use both X and Y in frame coordinates
   - Better constraint on camera height and tilt

2. **Lens Distortion Modeling**
   - Support wide-angle and fisheye lenses
   - Non-linear perspective correction

3. **Multi-Point Visualization**
   - Show confidence regions
   - Visualize error magnitude

4. **Semi-Automatic Calibration**
   - Suggest points using feature detection
   - Automatic matching with ArUco markers or QR codes

5. **Batch Calibration**
   - Simultaneously calibrate multiple cameras
   - Use cross-camera visibility constraints

## Testing the Calibration

### How to Test
1. Place two distinctive physical markers at known map positions
2. Right-click camera → "Calibrate Position"
3. Click first marker on map, then in camera feed
4. Click second marker on map, then in camera feed
5. Review computed position vs expected position
6. Accept or reject

### Verification
- Camera item should reposition on the map to match reality
- Person dots on floor map should align with visible people in feeds
- Cross-camera tracking should improve accuracy