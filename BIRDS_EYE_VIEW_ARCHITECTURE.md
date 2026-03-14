# Birds Eye View - Technical Architecture & Implementation Guide

## 📐 System Architecture

### Current Data Flow
```
┌─────────────────────────────────────────────────────────────────┐
│                    Multi-Camera Tracking System                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  DetectionSystem (per camera)                                   │
│  ├── YOLO detection (persons)                                   │
│  ├── DeepSORT tracking (local IDs)                              │
│  ├── Re-ID feature extraction                                   │
│  └── Send: (camera_name, local_id, bbox, features)             │
│         ↓                                                       │
│  GlobalPersonTracker (cross-camera)                            │
│  ├── Feature matching → global_id assignment                   │
│  ├── Camera tracks: {camera_name → LocalTrack}                 │
│  ├── Position estimation (stereo vision)                       │
│  ├── Dominant camera selection                                 │
│  ├── Position callback:                                        │
│  │   (global_id, x, y, camera_name) → MainWindow              │
│  └── person.smoothed_position = (world_x, world_y)            │
│         ↓                                                       │
│  MainWindow                                                     │
│  ├── Current: Update floor map dots                            │
│  ├── NEW: Update birds-eye view projection                     │
│  └── Signal: person_position_signal                           │
│         ↓                                                       │
│  BirdsEyeViewWidget (NEW)                                       │
│  ├── Homography-based projection                               │
│  ├── Multi-camera visualization                                │
│  └── Debug mode highlighting                                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 Component Details

### 1. BirdsEyeViewWidget

**Purpose**: Main visualization container
**Location**: `components/BirdsEyeViewWidget.py`
**Inheritance**: `QWidget`

**Key Attributes**:
```python
self.graphics_view: QGraphicsView        # Qt visualization
self.graphics_scene: QGraphicsScene      # Scene for drawing
self.debug_toggle: QPushButton           # Debug mode toggle
self.debug_mode: bool                    # State flag
self.homography_cache: Dict[str, np.ndarray]  # Cached H matrices
self.person_circle_items: Dict[int, QGraphicsEllipseItem]  # G.ID → circle
self.projection_items: Dict[(int, str), QGraphicsEllipseItem]  # (G.ID, cam) → circle
```

**Key Methods**:
```python
# Initialization & Setup
__init__(parent: QWidget = None) → None

# Main Update
update_visualization(
    global_tracker: GlobalPersonTracker,
    scene_cameras: Dict[str, CameraItem]
) → None

# Scene Drawing
_draw_background(scene_cameras) → None
_draw_cameras(scene_cameras) → None
_draw_persons_normal_mode() → None
_draw_persons_debug_mode() → None

# Debug Mode
_on_debug_toggled(checked: bool) → None
_draw_debug_projections(
    person: GlobalPerson,
    global_tracker: GlobalPersonTracker,
    scene_cameras: Dict
) → None

# Helper Methods
_clear_scene() → None
_compute_debug_color_for_camera(index: int) → QColor
```

**State Management**:
```
States:
  IDLE          → Waiting for data
  RENDERING     → Drawing current state
  DEBUG_ON      → Showing multi-camera projections
  DEBUG_OFF     → Showing only global positions

Transitions:
  button click (debug_toggle)
  └→ _on_debug_toggled() → _draw_persons_*() → state change
```

---

### 2. HomographyProjector

**Purpose**: Compute & apply homography transformations
**Location**: `components/HomographyProjector.py`
**Type**: Static utility class (no instances)

**Key Methods**:

#### 2.1 compute_homography_from_calibration()
```python
@staticmethod
def compute_homography_from_calibration(
    camera_pos: Tuple[float, float],        # (cx, cy) on floor
    camera_rotation: float,                  # degrees (0-360)
    fov_degrees: float,                      # field of view (40-140)
    frame_width: int,                        # 1920, 1280, etc
    frame_height: int                        # 1080, 720, etc
) → np.ndarray:
```

**Algorithm**:
```
1. Normalize frame dimensions: [-0.5, 0.5] range
   frame_norm = frame_pixel / frame_size - 0.5

2. Compute angle from center to frame point:
   angle_from_center = frame_norm_x * (FOV / 2)
   
3. Rotate by camera rotation:
   angle_world = angle_from_center + camera_rotation
   
4. Compute world distance from center to edge:
   For frame Y position (0=top, 1=bottom):
   - Perspective projection: farther objects smaller
   - Use camera range to estimate distance

5. Combine: world_x, world_y from angle + distance
   
6. Compute homography matrix H from point correspondences:
   H = cv2.getPerspectiveTransform(frame_points, world_points)
   
7. Return H (3x3 matrix)
```

**Example**:
```python
# Camera specs
cam_pos = (150, 200)      # Center of floor map
cam_rot = 45.0            # Degrees (pointing NE)
fov = 80.0                # Wide-angle lens
frame_sz = (1920, 1080)

# Compute H
H = HomographyProjector.compute_homography_from_calibration(
    cam_pos, cam_rot, fov, 1920, 1080
)

# Use H
point_frame = np.array([[[960, 540]]], dtype=np.float32)  # Center of frame
point_world = cv2.perspectiveTransform(point_frame, H)
# → Should be near (150, 200) since frame center ≈ camera direction
```

---

#### 2.2 project_bbox_to_world()
```python
@staticmethod
def project_bbox_to_world(
    bbox: Tuple[int, int, int, int],        # (x, y, w, h) in frame
    H: np.ndarray,                          # homography matrix
    frame_height: int                       # for Y-flip
) → Tuple[float, float]:
```

**Algorithm**:
```
1. Extract bbox center:
   cx_frame = bbox[0] + bbox[2] / 2
   cy_frame = bbox[1] + bbox[3] / 2

2. Flip Y (frame: 0=top, world: increases upward):
   cy_frame_normalized = frame_height - cy_frame

3. Create homogeneous coordinate:
   point = [[cx_frame, cy_frame_normalized, 1]]^T

4. Apply homography:
   point_world = H @ point

5. Normalize (divide by last coordinate):
   x_world = point_world[0] / point_world[2]
   y_world = point_world[1] / point_world[2]

6. Return (x_world, y_world)
```

**Example**:
```python
# Person bbox in Camera_A's frame
bbox = (800, 400, 100, 120)  # x, y, width, height

# Get homography for Camera_A
H = HomographyProjector.compute_homography_from_calibration(...)

# Project to world
world_x, world_y = HomographyProjector.project_bbox_to_world(
    bbox, H, frame_height=1080
)
# → (x_world, y_world) on floor map
```

---

### 3. Integration Points

#### 3.1 MainWindow Changes

**File**: `main/MainWindow.py`

**In `__init__()`**:
```python
# Add birds eye view widget
from components.BirdsEyeViewWidget import BirdsEyeViewWidget

self.birds_eye_view_widget = BirdsEyeViewWidget(self)

# Add to stacked widget
birds_eye_page = QWidget()  # Or load from UI
birds_eye_layout = QVBoxLayout(birds_eye_page)
birds_eye_layout.addWidget(self.birds_eye_view_widget)
self.Content_stack.addWidget(birds_eye_page)
self.birds_eye_view_page = birds_eye_page

# Connect button
self.birds_eye_btn.clicked.connect(self._on_birds_eye_btn_clicked)
```

**New Methods**:
```python
def _on_birds_eye_btn_clicked(self):
    """Switch to birds eye view page"""
    page_index = self.Content_stack.indexOf(self.birds_eye_view_page)
    self.Content_stack.setCurrentIndex(page_index)

def on_person_position_update(self, global_id, x, y, cam_name):
    """Called by person_position_signal from GlobalPersonTracker"""
    
    # Existing: Update floor map dots
    self._update_floor_map_dot(global_id, x, y)
    
    # NEW: Update birds eye view
    if hasattr(self, 'birds_eye_view_widget'):
        self.birds_eye_view_widget.update_visualization(
            self.global_tracker,
            self.scene_cameras
        )
```

**Connection in `create_camera_items()`**:
```python
# Register position callback with global tracker
self.global_tracker.set_position_callback(
    self.on_person_position_update
)
```

---

## 🎨 Visualization Design

### Normal Mode (Debug OFF)
```
┌──────────────────────────────────────────────────┐
│           Bird's Eye View - Floor Map            │
├──────────────────────────────────────────────────┤
│                                                  │
│  ┌─────────────────────────────────────────┐   │
│  │                                         │   │
│  │  ┌──────┐  ┌──────┐  ┌──────┐          │   │
│  │  │  📷  │  │  📷  │  │  📷  │          │   │
│  │  │ Cam_A│  │ Cam_B│  │ Cam_C│          │   │
│  │  └──────┘  └──────┘  └──────┘          │   │
│  │                                         │   │
│  │    ★ (green) = Person 1                │   │
│  │    ★ (red)   = Person 2                │   │
│  │    ★ (blue)  = Person 3                │   │
│  │                                         │   │
│  │    Grid: 1 square = 1 meter            │   │
│  └─────────────────────────────────────────┘   │
│                                                  │
│  🐛 Debug: OFF  [Switch to Debug]               │
└──────────────────────────────────────────────────┘
```

### Debug Mode (Debug ON)
```
┌──────────────────────────────────────────────────┐
│         Bird's Eye View - Debug Mode             │
├──────────────────────────────────────────────────┤
│                                                  │
│  ┌─────────────────────────────────────────┐   │
│  │                                         │   │
│  │    Cam_A→┐  Cam_B→┐                    │   │
│  │       ●RED  ●BLUE                      │   │
│  │         ╲  ╱                           │   │
│  │          ★ GREEN (stereo pos)          │   │
│  │                                         │   │
│  │    Person 1 (Global ID: 5)             │   │
│  │    Cam_A: Local 12, bbox (800, 400)    │   │
│  │    Cam_B: Local 8,  bbox (1200, 350)   │   │
│  │                                         │   │
│  │    Cam_C→◯ (detection outside frame)   │   │
│  │       YELLOW                           │   │
│  │       (person in Cam_C too!)           │   │
│  │                                         │   │
│  └─────────────────────────────────────────┘   │
│                                                  │
│  🐛 Debug: ON   [Switch to Normal]              │
└──────────────────────────────────────────────────┘
```

**Legend**:
- 📷 = Camera position + FOV cone (reused from CameraItem)
- ● = Per-camera projection (colored by camera)
- ★ = Stereo-vision calculated global position
- — = Homography projection line from camera
- ╲╱ = Convergence showing triangulation

---

## 🔄 Update Flow (Real-time)

```
Timeline: Frame-by-frame processing

┌─────────────────────────────────────────────────────┐
│ Frame N                                             │
├─────────────────────────────────────────────────────┤
│                                                     │
│ 1. Camera feeds → DetectionSystem (per camera)     │
│    └→ Local detections: {local_id, bbox, features}│
│                                                     │
│ 2. GlobalPersonTracker                             │
│    └→ Feature matching → global_id assignment      │
│    └→ Stereo triangulation → world position        │
│    └→ Emit: position_signal(global_id, x, y, cam) │
│                                                     │
│ 3. MainWindow.on_person_position_update()          │
│    ├→ Update floor map dots (existing)             │
│    ├→ Call birds_eye_view_widget.update_visualization() │
│    │                                               │
│    └→ BirdsEyeViewWidget                           │
│        ├→ Clear scene                              │
│        ├→ Draw grid                                │
│        ├→ Draw cameras                             │
│        ├→ FOR each global person:                  │
│        │  ├→ If debug_mode:                        │
│        │  │  ├→ Get all camera tracks              │
│        │  │  ├→ For each camera:                   │
│        │  │  │  ├→ Get homography H                │
│        │  │  │  ├→ Project bbox → world pos        │
│        │  │  │  ├→ Draw colored circle             │
│        │  │  │  ├→ Draw line to camera             │
│        │  │  │  └→ Draw camera name label          │
│        │  │  │                                     │
│        │  │  └→ Draw green circle at stereo pos   │
│        │  │  └→ Draw person ID+name label          │
│        │  │                                        │
│        │  └→ Else:                                 │
│        │     └→ Draw green circle only             │
│        │                                           │
│        └→ Render to graphics_view                  │
│                                                     │
│ 4. Display update (60 FPS typical)                │
│    └→ Birds Eye View refreshed with new data      │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 📊 Data Structures

### GlobalPerson (existing, used by BirdsEyeView)
```python
@dataclass
class GlobalPerson:
    global_id: int                              # Unique ID
    camera_tracks: Dict[str, LocalTrack]        # {cam_name → track}
        ├── camera_name: str
        ├── local_person_id: int
        ├── feature_vector: np.ndarray (optional)
        ├── bbox: (x, y, w, h) (optional)
        └── last_seen: float (timestamp)
    
    name: str                                   # "User_5" or "Unknown"
    confidence: float                           # Match confidence
    smoothed_position: (x, y) (optional)        # Stereo-calculated
    last_position_camera: str (optional)        # Which camera calculated it
    
    first_seen: float                           # Timestamp
    last_seen: float                            # Timestamp
```

### CameraInfo (existing, used by BirdsEyeView)
```python
@dataclass
class CameraInfo:
    name: str                                   # "Camera_A"
    position: (float, float)                    # (cx, cy) on floor
    rotation: float                             # degrees (0-360)
    fov: float                                  # 40-140 degrees
    view_range: float                           # effective range (pixels)
    frame_width: int                            # 1920, 1280, etc
    frame_height: int                           # 1080, 720, etc
```

---

## ⚙️ Algorithm Details

### Homography Computation Algorithm

**Input**: Camera calibration parameters
**Output**: 3×3 homography matrix H

**Steps**:

1. **Define frame source points** (4 corners + center):
   ```python
   frame_points = np.array([
       [0, 0],                           # Top-left
       [frame_width, 0],                 # Top-right
       [frame_width, frame_height],      # Bottom-right
       [0, frame_height],                # Bottom-left
       [frame_width/2, frame_height/2]   # Center
   ], dtype=np.float32)
   ```

2. **Compute corresponding world points**:
   ```
   For each frame point:
       - Normalize: fx = (x / width) - 0.5,  fy = (y / height) - 0.5
       - Angle from camera: angle = fx * (FOV/2)
       - Rotate to world: world_angle = angle + camera_rotation
       - Distance from camera: dist = (1 - fy) * view_range
         (fy=0 at top=far, fy=1 at bottom=close)
       - World position:
           world_x = cx + dist * cos(world_angle)
           world_y = cy + dist * sin(world_angle)
   ```

3. **Compute homography**:
   ```python
   H = cv2.getPerspectiveTransform(frame_points, world_points)
   ```

4. **Apply to projected bboxes**:
   ```python
   # For each detected person bbox in frame:
   bbox_center_frame = (bbox[0] + bbox[2]/2, bbox[1] + bbox[3]/2)
   
   # Convert to homogeneous coordinates
   point = np.array([[[bbox_center_frame[0], bbox_center_frame[1]]]], 
                     dtype=np.float32)
   
   # Apply homography
   proj_world = cv2.perspectiveTransform(point, H)
   
   # Result: (proj_world[0][0][0], proj_world[0][0][1])
   ```

---

## 🎯 Performance Optimization

### Caching Strategy
```python
class BirdsEyeViewWidget:
    def __init__(self):
        self.homography_cache = {}          # {cam_name → H}
        self.camera_info_cache = {}         # {cam_name → CameraInfo}
        self.last_update_time = 0
        self.update_throttle = 0.033        # 30 FPS max
```

### Computation Reduction
```python
# Only recompute homography when:
# 1. Camera position changed
# 2. Camera rotation changed
# 3. Camera FOV changed
# 4. Camera frame size changed

def _should_recompute_homography(self, cam_name: str, cam_info: CameraInfo) -> bool:
    cached = self.camera_info_cache.get(cam_name)
    if cached is None:
        return True
    return (cached.position != cam_info.position or
            cached.rotation != cam_info.rotation or
            cached.fov != cam_info.fov or
            cached.frame_width != cam_info.frame_width or
            cached.frame_height != cam_info.frame_height)
```

### Rendering Optimization
```python
# Update only when necessary:
# 1. Person added/removed
# 2. Person position changed (smoothed_position)
# 3. Debug mode toggled
# 4. Camera calibration updated

# NOT every frame (would be unnecessary rendering)

def update_visualization(self, global_tracker, scene_cameras):
    if self._is_visualization_stale(global_tracker):
        self._render_scene(global_tracker, scene_cameras)
    else:
        return  # Skip expensive redraw
```

---

## 🐛 Debug Information Display

### Per-Camera Debug Info
```python
# When DEBUG mode ON, for each camera detecting the person:

debug_info = {
    "camera_name": "Camera_A",
    "local_id": 12,
    "bbox_frame": (800, 400, 100, 120),
    "bbox_center_frame": (850, 460),
    "projection_world": (145.2, 198.7),
    "confidence": 0.92,
    "last_seen": 0.1,  # seconds ago
    "color": (255, 0, 0),  # Red
}

# Display as:
# "Camera_A (L:12): proj=[145.2, 198.7] conf=0.92"
```

### Global Position Debug Info
```python
# Stereo-vision calculated position

global_info = {
    "global_id": 5,
    "name": "User_5",
    "position": (146.5, 198.2),  # Average of projections
    "confidence": 0.95,           # Consistency score
    "num_cameras": 2,
    "cameras": ["Camera_A", "Camera_B"],
    "last_position_camera": "Camera_A",
    "smoothed_position": (146.5, 198.2),
}

# Display as:
# "Global:5 User_5 @ [146.5, 198.2] (2 cameras)"
```

---

## 🧪 Testing Scenarios

### Test Case 1: Single Camera
```
Setup:
- 1 camera at (150, 200), rot=0°, FOV=70°
- 1 person in frame

Expected:
- Projection near camera position
- Normal mode: 1 green dot
- Debug mode: 1 colored circle + green dot
```

### Test Case 2: Two Cameras (Overlap)
```
Setup:
- Camera_A at (100, 100), rot=45°, FOV=80°
- Camera_B at (150, 120), rot=135°, FOV=70°
- 1 person detected in both

Expected:
- Normal mode: 1 green dot (stereo-averaged position)
- Debug mode: 
  - 2 colored circles (Camera_A=RED, Camera_B=BLUE)
  - Lines from each camera to projections
  - Green dot showing stereo-calculated position
  - Should be triangulation point between projections
```

### Test Case 3: Multi-Camera (3+)
```
Setup:
- 3 cameras at different positions
- 2 persons (1 in 2 cameras, 1 in 3 cameras)

Expected:
- Normal mode: 2 green dots
- Debug mode:
  - Person 1: 2 circles + green dot
  - Person 2: 3 circles + green dot
  - Proper color assignment per camera
  - Lines connecting cameras to projections
```

### Test Case 4: Person Leaving Frame
```
Setup:
- Person in Camera_A, exits to Camera_B
- GlobalPerson created, then updated as it moves

Expected:
- Normal mode: Dot moves smoothly
- Debug mode: 
  - Initially 1 circle (Camera_A)
  - Transitions to 1 circle (Camera_B)
  - Smooth position update
```

---

## 🎯 Integration Checklist

### Phase 1: Foundation ✓
- [ ] Create BirdsEyeViewWidget class
- [ ] Create HomographyProjector class
- [ ] Add to main.ui
- [ ] Wire button in MainWindow

### Phase 2: Basic Rendering ✓
- [ ] Draw grid background (GridFloor)
- [ ] Draw camera positions + cones
- [ ] Draw person dots (green)
- [ ] Connect position updates

### Phase 3: Debug Mode ✓
- [ ] Implement debug toggle
- [ ] Draw per-camera projections
- [ ] Draw projection lines
- [ ] Draw labels

### Phase 4: Polish ✓
- [ ] Hover tooltips
- [ ] Performance optimization
- [ ] Edge case handling
- [ ] Visual refinements

### Phase 5: Testing ✓
- [ ] Unit test homography math
- [ ] Integration test with 2-3 cameras
- [ ] Manual testing with live feeds
- [ ] Performance testing

---

## 📚 Reference Materials

### OpenCV Perspective Transform
```python
import cv2
import numpy as np

# Source points (frame coordinates)
src_pts = np.array([...], dtype=np.float32)

# Destination points (world coordinates)
dst_pts = np.array([...], dtype=np.float32)

# Compute homography
H = cv2.getPerspectiveTransform(src_pts, dst_pts)

# Apply homography to a point
point = np.array([[[x, y]]], dtype=np.float32)
result = cv2.perspectiveTransform(point, H)
```

### PyQt6 Graphics View
```python
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsEllipseItem
from PyQt6.QtGui import QBrush, QPen, QColor

scene = QGraphicsScene()
view = QGraphicsView(scene)

# Draw circle
circle = QGraphicsEllipseItem(x, y, 24, 24)
circle.setBrush(QBrush(QColor(255, 0, 0)))
circle.setPen(QPen(QColor(255, 0, 0), 2))
scene.addItem(circle)
```

### Qt Signals/Slots
```python
# Define signal
toggle_signal = pyqtSignal(bool)

# Connect
self.button.toggled.connect(self._on_toggled)

# Slot
@pyqtSlot(bool)
def _on_toggled(self, checked: bool):
    print(f"Toggled: {checked}")
```

---

## 🚀 Deployment Steps

1. **Backup current code**
   ```bash
   git commit -m "Backup before BirdsEyeView implementation"
   ```

2. **Create new components**
   ```bash
   # Create files
   touch components/BirdsEyeViewWidget.py
   touch components/HomographyProjector.py
   ```

3. **Implement components**
   - Copy template code into files
   - Implement methods one by one
   - Test each independently

4. **Update MainWindow**
   - Add to UI file
   - Wire connections
   - Test button navigation

5. **Integration testing**
   - Start with 1 camera
   - Add 2nd camera
   - Add 3rd camera
   - Test debug mode

6. **Performance testing**
   - Monitor CPU usage
   - Check frame rate
   - Profile homography computation

7. **Deployment**
   ```bash
   git add components/BirdsEyeViewWidget.py
   git add components/HomographyProjector.py
   git add UIs/main.ui
   git add main/MainWindow.py
   git add BIRDS_EYE_VIEW_WORKFLOW.md
   git commit -m "Add Birds Eye View with homography projection"
   ```

---

**Status**: Ready for implementation
**Last Updated**: March 14, 2026
**Author**: System Architecture
