# Birds Eye View Enhancement - Suggested Workflow

## 🎯 Objective
Add a new "Birds Eye View" page with homography-based bird's-eye projection and debug visualization showing how the same person appears across multiple cameras and their stereo-calculated global position.

---

## 📊 Architecture Overview

### Current System Structure
```
Main UI (main.ui):
├── Camera Settings (Grid + Floor Map)
├── Camera Feed (Grid Layout)
├── Database
├── Logs
└── Settings

NEW: Birds Eye View (To be added)
    ├── Homography-based bird's-eye projection canvas
    ├── Debug Toggle Button
    ├── Multi-camera person visualization
    └── Stereo position markers
```

### Data Flow
```
GlobalPersonTracker (cross-camera person tracking)
    ↓
GlobalPerson objects (global_id, camera_tracks[], position)
    ↓
Birds Eye View Widget
    ├── For each GlobalPerson:
    │   ├── Get all camera tracks
    │   ├── Get camera calibration (position, rotation, FOV, view_range)
    │   ├── Project person bbox from each camera using homography
    │   ├── Draw projected positions on canvas
    │   ├── Mark stereo-calculated global position
    │   └── If DEBUG: show per-camera projections in different colors
    └── Render to QGraphicsView/Canvas
```

---

## 🔧 Component Breakdown & Implementation Sequence

### PHASE 1: UI Enhancement (MainWindow)

#### 1.1 Add Menu Button
**File**: `UIs/main.ui`
- Add new `QPushButton` called `birds_eye_btn` to Menubar
- Text: "Birds Eye View"
- Same styling as other buttons

**Estimated Lines**: 10-15 lines in XML

---

#### 1.2 Create BirdsEyeViewWidget
**New File**: `components/BirdsEyeViewWidget.py`

```python
class BirdsEyeViewWidget(QWidget):
    """
    Main widget for bird's-eye view visualization.
    - Displays homography-projected person positions from all cameras
    - Shows stereo-vision calculated global positions
    - Debug mode highlights camera-specific projections
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.graphics_view = QGraphicsView(self)
        self.graphics_scene = QGraphicsScene(self)
        
        # Control layout
        self.debug_toggle = QPushButton("🐛 Debug: OFF")
        self.debug_toggle.setCheckable(True)
        self.debug_mode = False
        
        # Main layout
        main_layout = QVBoxLayout(self)
        
        # Top: Debug button
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Bird's Eye View - Homography Projection"))
        top_layout.addStretch()
        top_layout.addWidget(self.debug_toggle)
        main_layout.addLayout(top_layout)
        
        # Center: Graphics view
        self.graphics_view.setScene(self.graphics_scene)
        main_layout.addWidget(self.graphics_view)
        
        self.debug_toggle.toggled.connect(self._on_debug_toggled)
```

**Key Methods**:
- `update_visualization()` - Main rendering function
- `_on_debug_toggled()` - Switch debug mode
- `_draw_person_projections()` - Draw per-camera projections
- `_calculate_homography()` - Compute 2D→bird's-eye transform for each camera
- `_project_bbox_to_bird_eye()` - Project person bbox to bird's-eye view

**Estimated Lines**: 250-300

---

### PHASE 2: Homography Calculation & Projection

#### 2.1 Homography Calculator Component
**New File**: `components/HomographyProjector.py`

```python
class HomographyProjector:
    """
    Computes and applies homography transforms to project camera view
    bounding boxes into bird's-eye view.
    
    Key Concept:
    - Camera projects 3D world → 2D frame (perspective)
    - Homography reverses this: 2D frame position → 2D world position
    - Assumes flat ground plane (Z = 0)
    """
    
    @staticmethod
    def compute_homography_from_calibration(
        camera_pos: Tuple[float, float],
        camera_rotation: float,
        fov_degrees: float,
        frame_width: int,
        frame_height: int
    ) -> np.ndarray:
        """
        Build homography matrix from camera calibration parameters.
        
        Math:
        - Camera position on floor: (cx, cy)
        - Camera rotation: angle R (degrees)
        - FOV: field of view angle
        - Maps: frame pixel → floor world coordinate
        
        Returns: 3x3 homography matrix (cv2.perspectiveTransform compatible)
        """
        # Implementation:
        # 1. Define source points (frame corners + center)
        # 2. Compute corresponding world points using camera model
        # 3. Compute homography H = cv2.getPerspectiveTransform()
        # 4. Return H
    
    @staticmethod
    def project_bbox_to_world(
        bbox: Tuple[int, int, int, int],  # (x, y, w, h) in frame
        H: np.ndarray,  # homography matrix
        frame_height: int
    ) -> Tuple[float, float]:
        """
        Project bounding box center from frame → world coordinates using homography.
        
        Args:
            bbox: (x, y, w, h) in frame pixels
            H: homography matrix
            frame_height: for Y-flip (frame Y increases downward, world Y upward)
        
        Returns:
            (world_x, world_y) - projected position on floor map
        """
        # Get bbox center in frame
        cx_frame = bbox[0] + bbox[2] / 2
        cy_frame = bbox[1] + bbox[3] / 2
        
        # Apply homography
        point = np.array([[[cx_frame, cy_frame]]], dtype=np.float32)
        projected = cv2.perspectiveTransform(point, H)
        
        return (projected[0][0][0], projected[0][0][1])
```

**Estimated Lines**: 150-200

---

#### 2.2 Integration with GlobalPersonTracker
**File**: `DataModel/GlobalPersonTracker.py` (minimal additions)

- Add method: `get_all_active_persons()` - return list of currently visible GlobalPerson objects
- Already has: `camera_tracks`, `position_callback`, `global_persons` dict

**Estimated Changes**: 10-20 lines

---

### PHASE 3: Birds Eye View Rendering

#### 3.1 Multi-Camera Projection Rendering
**In BirdsEyeViewWidget**:

```python
def update_visualization(self, global_tracker: GlobalPersonTracker, 
                         scene_cameras: Dict[str, CameraItem]):
    """
    Main update function called when persons change or positions update.
    """
    self.graphics_scene.clear()
    
    # 1. Draw background grid (reuse GridFloor from camera settings)
    grid = GridFloor(scene_width=1200, scene_height=1200, 
                     pixels_per_meter=30.0)
    self.graphics_scene.addItem(grid)
    
    # 2. Draw camera positions + FOV cones (reuse CameraItem visual logic)
    for cam_name, cam_item in scene_cameras.items():
        # Draw camera icon + FOV cone
        pass
    
    # 3. For each active person in global tracker:
    for global_id, person in global_tracker.global_persons.items():
        
        if self.debug_mode:
            # DEBUG: Show per-camera projections in different colors
            self._draw_debug_projections(person, global_tracker, scene_cameras)
        else:
            # NORMAL: Show only stereo-calculated position
            self._draw_person_global_position(person)
```

**Debug Mode Visualization**:
```
┌─────────────────────────────────────┐
│  Bird's Eye View (DEBUG MODE)        │
├─────────────────────────────────────┤
│                                     │
│    🚪 Cam_A        🪟 Cam_B        │
│     ↗ RED proj      ↗ BLUE proj     │
│        ↖ person ↖                   │
│      [★] GLOBAL POS (green dot)     │
│                                     │
│    🚪 Cam_C                         │
│     ↗ YELLOW proj                   │
│        ↗ matching same person       │
│                                     │
└─────────────────────────────────────┘

Legend:
• RED = Camera_A's projection
• BLUE = Camera_B's projection
• YELLOW = Camera_C's projection
• ★ = Stereo-calculated global position
```

**Estimated Lines**: 400-500

---

### PHASE 4: Debug Visualization Details

#### 4.1 Per-Camera Projection Drawing
**Function**: `_draw_debug_projections()`

```python
def _draw_debug_projections(self, person: GlobalPerson, 
                            global_tracker: GlobalPersonTracker,
                            scene_cameras: Dict[str, CameraItem]):
    """
    When DEBUG is ON and person detected in multiple cameras,
    draw their projections from each camera in different colors.
    """
    
    DEBUG_COLORS = [
        (255, 0, 0),      # Red (Camera 1)
        (0, 0, 255),      # Blue (Camera 2)
        (255, 255, 0),    # Yellow (Camera 3)
        (0, 255, 255),    # Cyan (Camera 4)
        (255, 0, 255),    # Magenta (Camera 5)
        (128, 255, 0),    # Green-Yellow (Camera 6)
    ]
    
    camera_index = 0
    for camera_name, local_track in person.camera_tracks.items():
        
        # Get camera calibration info
        cam_info = global_tracker.cameras[camera_name]
        
        # Compute homography for this camera
        H = HomographyProjector.compute_homography_from_calibration(
            camera_pos=cam_info.position,
            camera_rotation=cam_info.rotation,
            fov_degrees=cam_info.fov,
            frame_width=cam_info.frame_width,
            frame_height=cam_info.frame_height
        )
        
        # Project bbox from this camera
        if local_track.bbox is not None:
            proj_x, proj_y = HomographyProjector.project_bbox_to_world(
                local_track.bbox, H, cam_info.frame_height
            )
            
            # Draw projection point in this camera's color
            color = DEBUG_COLORS[camera_index % len(DEBUG_COLORS)]
            
            # Circle with camera name label
            circle = QGraphicsEllipseItem(proj_x - 8, proj_y - 8, 16, 16)
            circle.setBrush(QBrush(QColor(*color)))
            circle.setPen(QPen(QColor(*color), 2))
            self.graphics_scene.addItem(circle)
            
            # Label: Camera name
            text = QGraphicsSimpleTextItem(camera_name)
            text.setPos(proj_x + 10, proj_y - 10)
            text.setBrush(QBrush(QColor(*color)))
            self.graphics_scene.addItem(text)
            
            # Draw line from camera position to projection
            line = QGraphicsLineItem(
                cam_info.position[0], cam_info.position[1],
                proj_x, proj_y
            )
            line.setPen(QPen(QColor(*color, 100), 1, Qt.PenStyle.DashLine))
            self.graphics_scene.addItem(line)
        
        camera_index += 1
    
    # Draw global stereo position (calculated by system)
    if person.smoothed_position:
        global_marker = QGraphicsEllipseItem(
            person.smoothed_position[0] - 12,
            person.smoothed_position[1] - 12,
            24, 24
        )
        global_marker.setBrush(QBrush(QColor(0, 255, 0, 180)))  # Green
        global_marker.setPen(QPen(QColor(0, 255, 0), 3))
        self.graphics_scene.addItem(global_marker)
        
        # Label: Person ID + Name
        label_text = f"G:{person.global_id} {person.name}"
        label = QGraphicsSimpleTextItem(label_text)
        label.setPos(person.smoothed_position[0] + 15, person.smoothed_position[1] - 10)
        label.setBrush(QBrush(QColor(0, 255, 0)))
        self.graphics_scene.addItem(label)
```

**Estimated Lines**: 120-150

---

### PHASE 5: Integration with MainWindow

#### 5.1 UI Wiring
**File**: `main/MainWindow.py`

```python
class MainWindow(QMainWindow):
    
    def __init__(self):
        # ... existing code ...
        
        # Add in menu button connections:
        self.birds_eye_btn.clicked.connect(self.show_birds_eye_view)
    
    def show_birds_eye_view(self):
        """Switch to Birds Eye View page"""
        self.Content_stack.setCurrentWidget(self.birds_eye_view_page)
    
    def create_birds_eye_view_page(self):
        """
        Create the Birds Eye View widget and add it to the stacked widget.
        Called during MainWindow initialization.
        """
        self.birds_eye_view_widget = BirdsEyeViewWidget(self)
        # ... create page widget ...
        self.Content_stack.addWidget(self.birds_eye_view_page)
```

**Estimated Lines**: 40-60

---

#### 5.2 Update Connection
**File**: `main/MainWindow.py` (in `person_position_signal` slot)

```python
@pyqtSlot(int, float, float, str)
def on_person_position_update(self, global_id: int, x: float, y: float, cam_name: str):
    """
    Called when GlobalPersonTracker updates a person's position.
    """
    # ... existing code (update floor map dots) ...
    
    # NEW: Update birds eye view
    if hasattr(self, 'birds_eye_view_widget'):
        self.birds_eye_view_widget.update_visualization(
            self.global_tracker,
            self.scene_cameras
        )
```

**Estimated Lines**: 5-10

---

## 📋 Implementation Checklist

### Phase 1: UI Setup
- [ ] Add `birds_eye_btn` to `main.ui`
- [ ] Create `BirdsEyeViewWidget` class
- [ ] Add page to stacked widget in MainWindow
- [ ] Wire button click to page switching

### Phase 2: Homography Foundation
- [ ] Create `HomographyProjector` class
- [ ] Implement `compute_homography_from_calibration()`
- [ ] Implement `project_bbox_to_world()`
- [ ] Test with sample calibration data

### Phase 3: Base Visualization
- [ ] Draw grid background (reuse GridFloor)
- [ ] Draw camera positions + FOV cones
- [ ] Implement `update_visualization()` basic version
- [ ] Display stereo-calculated global position (green dot)

### Phase 4: Debug Mode
- [ ] Implement debug toggle button
- [ ] Implement `_draw_debug_projections()`
- [ ] Per-camera colored circles + labels
- [ ] Lines from camera to projection points
- [ ] Test with 2-3 camera setup

### Phase 5: Integration & Polish
- [ ] Wire person position updates to refresh view
- [ ] Test layout matches grid layout from camera settings
- [ ] Optimize rendering performance (scene refresh rate)
- [ ] Add tooltips/hover info showing person details
- [ ] Handle edge cases (person in single camera, no position, etc.)

---

## 🔑 Key Technical Details

### Homography Mathematics

The homography transformation maps frame coordinates → world coordinates:

```
┌─────────────────────────────────────────────────────────────────┐
│ Frame Coordinate System              World Coordinate System    │
│ (0,0) ─── camera view ───┐           Floor Map                  │
│   │                      │              ↑ +Y (north)           │
│   ├─ FOV cone ────────┐  │              │                       │
│   │                   │  │        ·─────┼─────·                 │
│   ├─ Person bbox ─────┼──┼→ Homography │  @ Camera             │
│   │                   │  │             └─→ +X (east)           │
│   └──────────────────── ┘                                       │
│                                                                 │
│ Formula: P_world = H × P_frame                                  │
│ (where P is homogeneous coordinate [x, y, 1])                  │
└─────────────────────────────────────────────────────────────────┘
```

**Why Homography Works**:
- Assumes flat ground plane (Z = 0)
- Valid for top-down camera view
- Directly invertible from calibration points

**Computation**:
```python
# From camera calibration: position, rotation, FOV
# Define 4 known frame points (corners) and their world positions
# cv2.getPerspectiveTransform() solves for H
# Apply with cv2.perspectiveTransform()
```

---

### Layout Consistency with Camera Settings Page

**Camera Settings Page Layout**:
- Left: QGraphicsView (drag_area) - draws floor plan + cameras + walls
- Right: QListWidget (cam_list) - shows camera list

**Birds Eye View Layout** (proposed):
- Top: Control bar (Debug toggle, title)
- Center: QGraphicsView - homography-based bird's-eye visualization
  - Same grid background (GridFloor)
  - Same camera drawings (CameraItem visuals)
  - Multi-camera person projections (NEW)
- No sidebar (full-width visualization)

---

## 🎨 Design Consistency

**Colors & Styling**:
- Follow existing dark theme (rgb(39, 7, 40) background)
- Reuse DOT_COLORS from MainWindow for camera/projection colors
- Use same grid styling as GridFloor
- Buttons styled like camera settings buttons

**Interactive Elements**:
- Debug toggle: QPushButton (checkable)
- Mouse hover: Show person details (tooltip)
- Click on projection: Show per-camera info
- Right-click: Show context menu (optional)

---

## ⚡ Performance Considerations

### Rendering Optimization
```python
# Only redraw when:
1. Person list changes (new/removed)
2. Person position updates (smoothed_position)
3. Debug mode toggled
4. Camera calibration changes

# NOT every frame (would be too slow)
```

### Caching
```python
# Cache homography matrices (recompute only when:
- Camera calibration updated
- Camera FOV changed)

self.homography_cache = {
    "Camera_A": H_A,
    "Camera_B": H_B,
    ...
}
```

---

## 🧪 Testing Strategy

### Unit Tests
1. **Homography Computation**
   - Test with known calibration (wide-angle, standard, telephoto)
   - Verify projected points are on-screen

2. **Bbox Projection**
   - Test with bbox at frame center (should project near camera)
   - Test with bbox at frame edges

3. **Widget Rendering**
   - Test with 0 cameras, 1 camera, 5+ cameras
   - Test with 0 persons, 1 person, 10+ persons

### Integration Tests
1. **Multi-Camera Scenario**
   - 2-3 cameras detecting same person
   - Verify projections are reasonably close
   - Toggle debug mode, verify colors/labels appear

2. **Cross-Camera Tracking**
   - Person moves between cameras
   - Projections should follow person
   - Global position should update smoothly

### Manual Testing Checklist
- [ ] Birds Eye View loads without errors
- [ ] Grid and camera positions display correctly
- [ ] Person dots appear when detected
- [ ] Debug toggle shows/hides multi-camera projections
- [ ] Debug projections have correct colors
- [ ] Lines connect camera → projection points
- [ ] Global position marked in green (different from projections)
- [ ] Person name + ID labels visible
- [ ] Layout matches camera settings page design
- [ ] No performance issues with 5+ cameras

---

## 📦 Files to Create/Modify

### New Files
1. `components/BirdsEyeViewWidget.py` - Main visualization widget
2. `components/HomographyProjector.py` - Homography math
3. `UIs/birds_eye_view.ui` - Optional (for Qt Designer layout)
4. `BIRDS_EYE_VIEW_WORKFLOW.md` - This file

### Modified Files
1. `UIs/main.ui` - Add birds_eye_btn button
2. `main/MainWindow.py` - Integration + connections
3. `DataModel/GlobalPersonTracker.py` - Minor helper method (if needed)

### Documentation
1. `BIRDS_EYE_VIEW_WORKFLOW.md` - This workflow
2. `BIRDS_EYE_VIEW_IMPLEMENTATION.md` - After implementation
3. `BIRDS_EYE_VIEW_API.md` - API reference

---

## 🚀 Execution Priority

### Priority 1 (Core Functionality)
1. Homography projector (math foundation)
2. Basic visualization (grid + cameras + global dots)
3. MainWindow integration
4. Test with 2-3 camera scenario

### Priority 2 (Debug Mode)
1. Debug toggle button
2. Per-camera projections (colored circles)
3. Lines to projections
4. Labels with camera names

### Priority 3 (Polish & Optimization)
1. Performance caching
2. Hover tooltips
3. Visual refinements
4. Edge case handling

---

## 💡 Future Enhancements (Out of Scope)

1. **3D Bird's Eye View**
   - Include height information from camera tilt
   - Show person height estimates

2. **Trajectory Visualization**
   - Draw person movement trails over time
   - Color-coded by confidence/certainty

3. **Heatmap Overlay**
   - Show coverage density across floor
   - Highlight blind spots

4. **Annotation Tools**
   - Draw regions of interest
   - Annotate camera coverage zones
   - Mark danger/restricted areas

5. **Export/Recording**
   - Save bird's eye view as video
   - Export person trajectories as data

---

## 📞 Questions for Clarification

1. **Rendering Frequency**: Update on every frame or only on person changes?
   → Recommended: On person changes (lower CPU overhead)

2. **Max Persons to Display**: How many simultaneous persons?
   → Recommended: Start with 10, optimize if needed

3. **Debug Color Scheme**: 6 colors OK, or want different scheme?
   → Recommended: Use existing DOT_COLORS from MainWindow

4. **Grid Size**: Match camera settings (1200x1200 @ 30px/meter)?
   → Recommended: Yes, for consistency

5. **Camera Cone Drawing**: Show as in camera settings page?
   → Recommended: Yes, reuse CameraItem rendering code

---

## ✅ Success Criteria

The implementation is complete when:

1. ✅ Birds Eye View page exists and loads without errors
2. ✅ Grid and camera positions display correctly
3. ✅ Stereo-calculated person positions shown as green dots
4. ✅ Debug mode shows per-camera projections in different colors
5. ✅ Debug mode shows lines from cameras to projections
6. ✅ Debug mode shows person name/ID labels
7. ✅ Debug toggle works smoothly
8. ✅ Layout consistent with camera settings page
9. ✅ No performance issues with 5+ cameras
10. ✅ Tested with multi-camera scenario

---

**Total Estimated Implementation Time**: 8-12 hours
**Total Lines of Code**: ~800-1000 (components + integration)
**Complexity Level**: Medium (math + visualization)
