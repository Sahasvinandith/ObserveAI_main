# Birds Eye View - Quick Implementation Guide

## 📋 TL;DR Summary

**What**: Add a new "Birds Eye View" page showing how the same person appears across multiple cameras, with homography-based 2D projection onto the floor map.

**Why**: Understand multi-camera detection overlaps and stereo-vision triangulation visually. Debug mode shows per-camera projections (different colors) + stereo-calculated position (green dot).

**How**: 
- Use OpenCV homography to project camera frames → bird's-eye view
- Draw per-camera detections (colored circles) 
- Mark stereo position (green dot)
- Toggle debug mode to see all projections

**Time**: 8-12 hours
**Complexity**: Medium
**Lines**: ~800-1000

---

## 🔍 Visual Example

### Normal Mode
```
   Camera_A
      📷
     /|\  
    / | \
   /  |  \
  /   ★   \   ← Green dot (stereo position)
      (person here)
```

### Debug Mode
```
   Camera_A            Camera_B
      📷                  📷
     /|                    |\
    / ●RED              BLUE● \
    \ |                    | /
     \|                    |/
      ★ (green - stereo pos from triangulation)
      
   Legend:
   ● = projected from each camera (different colors)
   ★ = stereo-calculated position (averaging/triangulation)
```

---

## 📐 Core Concepts

### 1. Homography Transform
**What it does**: Maps frame pixel → floor world coordinate

```
Frame (camera view)          Floor Map (bird's-eye)
─────────────────────        ─────────────────────
   (800, 400)   ────H────→   (145.2, 198.7)
   
   Where:
   - Input: bbox center in camera frame (pixels)
   - H: homography matrix (computed from calibration)
   - Output: position on floor map
```

**Formula**:
```python
point_world = H @ point_frame  # homogeneous multiplication
```

### 2. Per-Camera Projection
When debug mode ON:
1. Get all cameras detecting this person
2. For each camera:
   - Get homography H
   - Project person bbox from frame → world
   - Draw colored circle at projected position
   - Draw line from camera to projection
3. Draw green circle at stereo-calculated position (average of projections)

### 3. Stereo Triangulation
System computes global position by:
1. Getting all per-camera projections
2. Averaging or triangulating to find best global position
3. Already done by GlobalPersonTracker (using `position_callback`)

---

## 🛠️ Implementation Steps (Fast Path)

### Step 1: Create HomographyProjector (30 min)
**File**: `components/HomographyProjector.py`

```python
import cv2
import numpy as np
from typing import Tuple

class HomographyProjector:
    """Homography-based frame→world projection"""
    
    @staticmethod
    def compute_homography_from_calibration(
        camera_pos: Tuple[float, float],
        camera_rotation: float,
        fov_degrees: float,
        frame_width: int,
        frame_height: int
    ) -> np.ndarray:
        """
        Compute homography matrix H.
        
        Maps: frame pixel → floor world coordinate
        Assumes: flat ground plane (Z=0)
        """
        # Define 4-5 frame points (corners + center)
        src = np.array([
            [0, 0],
            [frame_width, 0],
            [frame_width, frame_height],
            [0, frame_height],
            [frame_width/2, frame_height/2]
        ], dtype=np.float32)
        
        # Compute corresponding world points
        dst = []
        for frame_pt in src:
            # Normalize frame coordinates
            fx = (frame_pt[0] / frame_width) - 0.5
            fy = (frame_pt[1] / frame_height) - 0.5
            
            # Angle from camera center
            angle_from_center = fx * np.radians(fov_degrees / 2)
            
            # Rotate to world
            angle_world = angle_from_center + np.radians(camera_rotation)
            
            # Distance (Y coordinate in frame = depth)
            # Frame Y: 0=top (far), 1=bottom (close)
            distance = (1 - fy) * 250  # Arbitrary range
            
            # World position
            wx = camera_pos[0] + distance * np.cos(angle_world)
            wy = camera_pos[1] + distance * np.sin(angle_world)
            
            dst.append([wx, wy])
        
        dst = np.array(dst, dtype=np.float32)
        
        # Compute homography
        H = cv2.getPerspectiveTransform(src[:4], dst[:4])
        return H
    
    @staticmethod
    def project_bbox_to_world(
        bbox: Tuple[int, int, int, int],
        H: np.ndarray,
        frame_height: int
    ) -> Tuple[float, float]:
        """Project bbox center from frame → world"""
        # Get bbox center
        cx = bbox[0] + bbox[2] / 2
        cy = bbox[1] + bbox[3] / 2
        
        # Apply homography
        point = np.array([[[cx, cy]]], dtype=np.float32)
        result = cv2.perspectiveTransform(point, H)
        
        return (result[0][0][0], result[0][0][1])
```

---

### Step 2: Create BirdsEyeViewWidget (60 min)
**File**: `components/BirdsEyeViewWidget.py`

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGraphicsView, QGraphicsScene
from PyQt6.QtCore import pyqtSlot, Qt
from PyQt6.QtGui import QColor, QBrush, QPen, QImage, QPixmap
from PyQt6.QtWidgets import QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsSimpleTextItem
import numpy as np
import cv2

from components.HomographyProjector import HomographyProjector
from components.GridFloor import GridFloor
from components.Camera_widget import CameraItem
from DataModel.GlobalPersonTracker import GlobalPersonTracker, GlobalPerson

class BirdsEyeViewWidget(QWidget):
    """Bird's-eye view with homography projection"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Graphics setup
        self.graphics_scene = QGraphicsScene(self)
        self.graphics_view = QGraphicsView(self.graphics_scene)
        
        # Debug mode
        self.debug_toggle = QPushButton("🐛 Debug: OFF")
        self.debug_toggle.setCheckable(True)
        self.debug_mode = False
        self.debug_toggle.toggled.connect(self._on_debug_toggled)
        
        # Layout
        main_layout = QVBoxLayout(self)
        
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("Bird's Eye View - Homography Projection"))
        top_layout.addStretch()
        top_layout.addWidget(self.debug_toggle)
        
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.graphics_view, stretch=1)
        
        # Cache
        self.homography_cache = {}
        self.debug_colors = [
            QColor(255, 0, 0),      # Red
            QColor(0, 0, 255),      # Blue
            QColor(255, 255, 0),    # Yellow
            QColor(0, 255, 255),    # Cyan
        ]
    
    @pyqtSlot(bool)
    def _on_debug_toggled(self, checked):
        """Toggle debug mode"""
        self.debug_mode = checked
        self.debug_toggle.setText(f"🐛 Debug: {'ON' if checked else 'OFF'}")
        # Redraw (would normally come from update signal)
    
    def update_visualization(self, global_tracker: GlobalPersonTracker, 
                            scene_cameras: dict):
        """Main update: render all persons"""
        self.graphics_scene.clear()
        
        # Draw background grid
        grid = GridFloor(scene_width=1200, scene_height=1200, 
                        pixels_per_meter=30.0)
        self.graphics_scene.addItem(grid)
        
        # Draw cameras
        for cam_name, cam_item in scene_cameras.items():
            # TODO: Draw camera icon + FOV cone (reuse CameraItem drawing)
            pass
        
        # Draw persons
        for global_id, person in global_tracker.global_persons.items():
            if self.debug_mode:
                self._draw_debug_projections(person, global_tracker, scene_cameras)
            else:
                self._draw_global_position(person)
    
    def _draw_global_position(self, person: GlobalPerson):
        """Draw stereo-calculated position (normal mode)"""
        if person.smoothed_position is None:
            return
        
        x, y = person.smoothed_position
        
        # Green circle
        circle = QGraphicsEllipseItem(x - 10, y - 10, 20, 20)
        circle.setBrush(QBrush(QColor(0, 255, 0, 180)))
        circle.setPen(QPen(QColor(0, 255, 0), 2))
        self.graphics_scene.addItem(circle)
        
        # Label
        label = QGraphicsSimpleTextItem(f"G:{person.global_id} {person.name}")
        label.setPos(x + 15, y - 10)
        label.setBrush(QBrush(QColor(0, 255, 0)))
        self.graphics_scene.addItem(label)
    
    def _draw_debug_projections(self, person: GlobalPerson, 
                                global_tracker: GlobalPersonTracker,
                                scene_cameras: dict):
        """Draw per-camera projections (debug mode)"""
        
        camera_index = 0
        for cam_name, local_track in person.camera_tracks.items():
            
            # Get camera info
            if cam_name not in global_tracker.cameras:
                continue
            
            cam_info = global_tracker.cameras[cam_name]
            
            # Get or compute homography
            if cam_name not in self.homography_cache:
                H = HomographyProjector.compute_homography_from_calibration(
                    cam_info.position,
                    cam_info.rotation,
                    cam_info.fov,
                    cam_info.frame_width,
                    cam_info.frame_height
                )
                self.homography_cache[cam_name] = H
            else:
                H = self.homography_cache[cam_name]
            
            # Project bbox
            if local_track.bbox is not None:
                proj_x, proj_y = HomographyProjector.project_bbox_to_world(
                    local_track.bbox, H, cam_info.frame_height
                )
                
                # Get color for this camera
                color = self.debug_colors[camera_index % len(self.debug_colors)]
                
                # Draw circle
                circle = QGraphicsEllipseItem(proj_x - 8, proj_y - 8, 16, 16)
                circle.setBrush(QBrush(color))
                circle.setPen(QPen(color, 2))
                self.graphics_scene.addItem(circle)
                
                # Draw line from camera to projection
                line = QGraphicsLineItem(
                    cam_info.position[0], cam_info.position[1],
                    proj_x, proj_y
                )
                line.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
                self.graphics_scene.addItem(line)
                
                # Draw label
                label = QGraphicsSimpleTextItem(cam_name)
                label.setPos(proj_x + 10, proj_y - 10)
                label.setBrush(QBrush(color))
                self.graphics_scene.addItem(label)
            
            camera_index += 1
        
        # Draw global position (green)
        if person.smoothed_position:
            x, y = person.smoothed_position
            circle = QGraphicsEllipseItem(x - 12, y - 12, 24, 24)
            circle.setBrush(QBrush(QColor(0, 255, 0, 180)))
            circle.setPen(QPen(QColor(0, 255, 0), 3))
            self.graphics_scene.addItem(circle)
            
            label = QGraphicsSimpleTextItem(f"G:{person.global_id}")
            label.setPos(x + 15, y)
            label.setBrush(QBrush(QColor(0, 255, 0)))
            self.graphics_scene.addItem(label)
```

---

### Step 3: Update main.ui (5 min)
- Add button `birds_eye_btn` to Menubar with text "Birds Eye View"
- Or: Use Qt Designer to add it visually

---

### Step 4: Wire MainWindow (15 min)
**File**: `main/MainWindow.py`

```python
# In __init__():
from components.BirdsEyeViewWidget import BirdsEyeViewWidget

self.birds_eye_widget = BirdsEyeViewWidget(self)

# Add to stack
self.birds_eye_page = QWidget()
layout = QVBoxLayout(self.birds_eye_page)
layout.addWidget(self.birds_eye_widget)
self.Content_stack.addWidget(self.birds_eye_page)

# Wire button
self.birds_eye_btn.clicked.connect(self._on_birds_eye_btn_clicked)

# New method:
def _on_birds_eye_btn_clicked(self):
    idx = self.Content_stack.indexOf(self.birds_eye_page)
    self.Content_stack.setCurrentIndex(idx)

# Update person_position_signal slot:
@pyqtSlot(int, float, float, str)
def on_person_position_update(self, global_id, x, y, cam_name):
    # ... existing code ...
    
    # NEW:
    if hasattr(self, 'birds_eye_widget'):
        self.birds_eye_widget.update_visualization(
            self.global_tracker,
            self.scene_cameras
        )
```

---

## 🧪 Testing Quick Checklist

- [ ] Code compiles without errors
- [ ] Button appears in menu
- [ ] Click button → switches to Birds Eye View page
- [ ] Grid and cameras display
- [ ] Person dots appear when detected
- [ ] Toggle debug: OFF shows green dots only
- [ ] Toggle debug: ON shows colored projections
- [ ] Debug colors cycle through cameras
- [ ] Lines drawn from cameras to projections
- [ ] No crashes with 2-3 cameras

---

## 📊 File Summary

| File | Lines | Purpose |
|------|-------|---------|
| `components/HomographyProjector.py` | ~80 | Homography math |
| `components/BirdsEyeViewWidget.py` | ~180 | Main widget + rendering |
| `main/MainWindow.py` | +30 | Integration |
| `UIs/main.ui` | +10 | Button add |

**Total**: ~300 lines new code, ~30 lines modified

---

## 🎯 Success Indicators

✅ Birds eye view page loads
✅ Displays grid + cameras
✅ Shows person dots
✅ Debug mode reveals per-camera projections
✅ No performance issues
✅ Layout matches camera settings page

---

## 💾 Next: Deployment

When ready:
```bash
# Create files
touch components/BirdsEyeViewWidget.py
touch components/HomographyProjector.py

# Copy code from guide above
# Wire MainWindow
# Test

# Commit
git add .
git commit -m "Add Birds Eye View with homography projection"
```

---

**Ready to implement?** → See BIRDS_EYE_VIEW_ARCHITECTURE.md for full details

