"""
Birds Eye View Widget - Homography-based multi-camera visualization.

This widget displays a bird's-eye view of the scene with:
- Homography-projected person positions from each camera
- Stereo-vision calculated global person positions
- Debug mode showing per-camera projections in different colors
- Camera positions, FOV cones, and grid background

Author: ObserveAI System
"""

import math
from typing import Dict, Optional, Tuple, List
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QGraphicsView, QGraphicsScene, QGraphicsItem,
                             QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsSimpleTextItem,
                             QGraphicsRectItem, QGraphicsPolygonItem)
from PyQt6.QtCore import Qt, QSize, QPointF, QTimer
from PyQt6.QtGui import QColor, QBrush, QPen, QPolygonF, QFont, QPainter
import numpy as np

from components.HomographyProjector import HomographyProjector


# Debug colors for multi-camera projections (RGB format for consistency)
DEBUG_COLORS = [
    (255, 0, 0),        # Red (Camera 1)
    (0, 0, 255),        # Blue (Camera 2)
    (255, 255, 0),      # Yellow (Camera 3)
    (0, 255, 255),      # Cyan (Camera 4)
    (255, 0, 255),      # Magenta (Camera 5)
    (0, 255, 128),      # Spring Green (Camera 6)
    (255, 165, 0),      # Orange (Camera 7)
    (128, 0, 128),      # Purple (Camera 8)
]

GRID_SIZE = 50  # Grid cell size in world units
GRID_PIXELS_PER_UNIT = 30  # Pixels per world unit


class GridOverlay(QGraphicsItem):
    """
    Draws a grid background for the bird's-eye view.
    Helps visualize scale and coordinate system.
    """
    def __init__(self, width: int, height: int, cell_size: int = 50):
        super().__init__()
        self.width = width
        self.height = height
        self.cell_size = cell_size
        self._bounding_rect = None

    def boundingRect(self):
        # Return fixed bounding rect to avoid recursion
        if self._bounding_rect is None:
            from PyQt6.QtCore import QRectF
            self._bounding_rect = QRectF(0, 0, self.width, self.height)
        return self._bounding_rect

    def paint(self, painter, option, widget):
        # Draw grid lines
        pen = QPen(QColor(80, 80, 80), 1, Qt.PenStyle.SolidLine)
        painter.setPen(pen)

        # Vertical lines
        for x in range(0, self.width, self.cell_size):
            painter.drawLine(x, 0, x, self.height)

        # Horizontal lines
        for y in range(0, self.height, self.cell_size):
            painter.drawLine(0, y, self.width, y)

        # Draw origin axes
        axis_pen = QPen(QColor(150, 150, 150), 2)
        painter.setPen(axis_pen)
        origin_x, origin_y = self.width // 2, self.height // 2
        painter.drawLine(origin_x, 0, origin_x, self.height)
        painter.drawLine(0, origin_y, self.width, origin_y)


class CameraVisualization(QGraphicsItem):
    """
    Visualizes a camera position and FOV cone in bird's-eye view.
    """
    def __init__(self, cam_name: str, position: Tuple[float, float],
                 rotation: float, fov: float, scale: float = GRID_PIXELS_PER_UNIT):
        super().__init__()
        self.cam_name = cam_name
        self.position = position
        self.rotation = rotation  # in degrees
        self.fov = fov  # in degrees
        self.scale = scale
        self.setAcceptHoverEvents(True)
        self._bounding_rect = None

    def boundingRect(self):
        # Return fixed bounding rect to avoid recursion
        if self._bounding_rect is None:
            from PyQt6.QtCore import QRectF
            radius = 250  # Approximate cone radius
            scaled_x = self.position[0] * self.scale
            scaled_y = self.position[1] * self.scale
            self._bounding_rect = QRectF(
                scaled_x - radius, scaled_y - radius,
                radius * 2, radius * 2
            )
        return self._bounding_rect

    def paint(self, painter, option, widget):
        scaled_x = self.position[0] * self.scale
        scaled_y = self.position[1] * self.scale

        # Draw CCTV camera icon - a larger circle with triangle pointing to rotation
        camera_size = 20
        
        # Outer circle (camera body) - yellow
        camera_pen = QPen(QColor(255, 200, 0), 2)
        camera_brush = QBrush(QColor(255, 200, 0, 180))
        painter.setPen(camera_pen)
        painter.setBrush(camera_brush)
        painter.drawEllipse(
            int(scaled_x - camera_size), 
            int(scaled_y - camera_size), 
            camera_size * 2, 
            camera_size * 2
        )
        
        # Draw direction indicator (arrow pointing in rotation direction)
        # In map coordinates: 0° = North (up), 90° = East (right), 180° = South (down), 270° = West (left)
        rotation_rad = math.radians(self.rotation)
        indicator_length = camera_size + 8
        # Use -cos for Y because Y increases downward in screen coords, but we want 0° to point UP
        tip_x = scaled_x + indicator_length * math.sin(rotation_rad)
        tip_y = scaled_y - indicator_length * math.cos(rotation_rad)  # Negated to point up at 0°
        
        indicator_pen = QPen(QColor(255, 255, 0), 2)
        painter.setPen(indicator_pen)
        painter.drawLine(int(scaled_x), int(scaled_y), int(tip_x), int(tip_y))
        
        # Draw a small filled triangle at the tip
        triangle_size = 5
        painter.setBrush(QBrush(QColor(255, 255, 0)))
        painter.drawEllipse(
            int(tip_x - triangle_size), 
            int(tip_y - triangle_size),
            triangle_size * 2,
            triangle_size * 2
        )

        # Draw FOV cone (semi-transparent)
        cone_radius = 120  # pixels
        half_fov = self.fov / 2
        
        # Draw FOV as arc
        cone_pen = QPen(QColor(0, 200, 255, 100), 1, Qt.PenStyle.DashLine)
        painter.setPen(cone_pen)
        
        # Left edge of cone (pointing left from camera direction)
        left_angle = rotation_rad - math.radians(half_fov)
        left_x = scaled_x + cone_radius * math.sin(left_angle)
        left_y = scaled_y - cone_radius * math.cos(left_angle)  # Negated for correct orientation
        painter.drawLine(int(scaled_x), int(scaled_y), int(left_x), int(left_y))
        
        # Right edge of cone (pointing right from camera direction)
        right_angle = rotation_rad + math.radians(half_fov)
        right_x = scaled_x + cone_radius * math.sin(right_angle)
        right_y = scaled_y - cone_radius * math.cos(right_angle)  # Negated for correct orientation
        painter.drawLine(int(scaled_x), int(scaled_y), int(right_x), int(right_y))

        # Draw camera name label
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(255, 255, 100)))
        painter.drawText(int(scaled_x + 25), int(scaled_y - 5), self.cam_name)


class BirdsEyeViewWidget(QWidget):
    """
    Main widget for bird's-eye view visualization using homography-based projection.

    Features:
    - Displays homography-projected person positions from all cameras
    - Shows stereo-vision calculated global positions
    - Debug mode highlights camera-specific projections with different colors
    - Interactive grid-based canvas matching camera settings layout
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.global_tracker = None
        self.scene_cameras = {}
        self.debug_mode = False
        self.homography_cache: Dict[str, np.ndarray] = {}
        self._is_updating = False  # Recursion guard
        self._timer_active = False
        self.update_timer = None  # Will create on demand
        
        # Scaling variables for coordinate transformation
        self.current_scale = 1.0
        self.world_min_x = 0.0
        self.world_min_y = 0.0

        # UI Setup
        self._setup_ui()
        self.setStyleSheet("background-color: rgb(39, 7, 40);")

    def _setup_ui(self):
        """Create UI layout"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Top control bar
        top_layout = QHBoxLayout()
        
        title_label = QLabel("Bird's Eye View - Homography Projection")
        title_label.setStyleSheet("color: #aaa; font-size: 13px; font-weight: bold;")
        
        self.debug_toggle = QPushButton("🐛 Debug: OFF")
        self.debug_toggle.setCheckable(True)
        self.debug_toggle.setMaximumWidth(120)
        self.debug_toggle.setStyleSheet("""
            QPushButton {
                background-color: rgb(50, 50, 50);
                color: white;
                border: 1px solid rgb(80, 80, 80);
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton:checked {
                background-color: rgb(0, 120, 0);
                border: 1px solid rgb(0, 200, 0);
            }
            QPushButton:hover {
                background-color: rgb(80, 80, 80);
            }
        """)
        self.debug_toggle.toggled.connect(self._on_debug_toggled)
        
        top_layout.addWidget(title_label)
        top_layout.addStretch()
        top_layout.addWidget(self.debug_toggle)
        main_layout.addLayout(top_layout)

        # Graphics view for bird's-eye visualization
        self.graphics_view = QGraphicsView(self)
        self.graphics_scene = QGraphicsScene(self)
        self.graphics_view.setScene(self.graphics_scene)
        
        # Set background color
        self.graphics_view.setBackgroundBrush(QBrush(QColor(30, 30, 30)))
        self.graphics_view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        main_layout.addWidget(self.graphics_view)
        self.setLayout(main_layout)

    def set_data_sources(self, global_tracker, scene_cameras: Dict):
        """
        Set references to global tracker and camera items.

        Args:
            global_tracker: GlobalPersonTracker instance
            scene_cameras: Dict of CameraItem objects by camera name
        """
        self.global_tracker = global_tracker
        self.scene_cameras = scene_cameras

    def update_visualization(self):
        """
        Main update function called when persons/cameras change.
        Renders bird's-eye view based on current tracker state.
        """
        # Recursion guard: prevent multiple simultaneous updates
        if self._is_updating:
            return
        
        if self.global_tracker is None:
            return

        self._is_updating = True
        try:
            self.graphics_scene.clear()

            # Use FIXED scene rect like camera settings page (1200x1200)
            SCENE_SIZE = 1200
            self.graphics_scene.setSceneRect(0, 0, SCENE_SIZE, SCENE_SIZE)

            # Calculate world bounds from actual camera and person positions
            min_x = min_y = max_x = max_y = None
            
            # Check camera positions
            for cam_info in self.global_tracker.cameras.values():
                cam_x, cam_y = cam_info.position
                if min_x is None:
                    min_x = max_x = cam_x
                    min_y = max_y = cam_y
                else:
                    min_x = min(min_x, cam_x)
                    max_x = max(max_x, cam_x)
                    min_y = min(min_y, cam_y)
                    max_y = max(max_y, cam_y)
            
            # Check person positions
            for person in self.global_tracker.global_persons.values():
                if hasattr(person, 'smoothed_position') and person.smoothed_position:
                    pers_x, pers_y = person.smoothed_position
                    if min_x is None:
                        min_x = max_x = pers_x
                        min_y = max_y = pers_y
                    else:
                        min_x = min(min_x, pers_x)
                        max_x = max(max_x, pers_x)
                        min_y = min(min_y, pers_y)
                        max_y = max(max_y, pers_y)
            
            # Default bounds if no cameras/persons
            if min_x is None:
                min_x = max_x = 100
                min_y = max_y = 100
            
            # Add padding
            padding = (max_x - min_x) * 0.1 if (max_x - min_x) > 0 else 10
            if padding < 10:
                padding = 10
            
            world_min_x = min_x - padding
            world_max_x = max_x + padding
            world_min_y = min_y - padding
            world_max_y = max_y + padding
            
            world_width = world_max_x - world_min_x
            world_height = world_max_y - world_min_y
            
            # Calculate scale to fit everything in 1200x1200
            scale_x = (SCENE_SIZE - 50) / world_width if world_width > 0 else 1
            scale_y = (SCENE_SIZE - 50) / world_height if world_height > 0 else 1
            scale = min(scale_x, scale_y)  # Use minimum to fit both dimensions
            
            # Use this scale for drawing
            self.current_scale = scale
            self.world_min_x = world_min_x
            self.world_min_y = world_min_y
            
            print(f"[BEV] Bounds: X({world_min_x:.1f}-{world_max_x:.1f}) Y({world_min_y:.1f}-{world_max_y:.1f}) | Scale: {scale:.2f}")
            print(f"[BEV] Cameras: {list(self.scene_cameras.keys())} | Persons: {len(self.global_tracker.global_persons)}")
            
            # Debug: Log camera positions and parameters
            for cam_name, cam_info in self.global_tracker.cameras.items():
                print(f"[BEV CAM] {cam_name}: pos=({cam_info.position[0]:.1f}, {cam_info.position[1]:.1f}) rot={cam_info.rotation:.1f}° fov={cam_info.fov}° range={cam_info.view_range:.0f}")

            # Draw grid background
            grid = GridOverlay(SCENE_SIZE, SCENE_SIZE, int(50 / scale) if scale > 0 else 50)
            self.graphics_scene.addItem(grid)

            # Draw camera visualizations
            for cam_name, cam_item in self.scene_cameras.items():
                try:
                    if cam_name not in self.global_tracker.cameras:
                        continue
                    
                    cam_info = self.global_tracker.cameras[cam_name]
                    
                    # Transform world coordinates to scene coordinates
                    scene_x = (cam_info.position[0] - self.world_min_x) * self.current_scale + 25
                    scene_y = (cam_info.position[1] - self.world_min_y) * self.current_scale + 25
                    
                    cam_viz = CameraVisualization(
                        cam_name=cam_name,
                        position=(scene_x, scene_y),
                        rotation=cam_info.rotation,
                        fov=cam_info.fov,
                        scale=1.0  # Already in scene coordinates
                    )
                    self.graphics_scene.addItem(cam_viz)
                except Exception as e:
                    print(f"Error drawing camera {cam_name}: {e}")

            # Draw persons
            if hasattr(self.global_tracker, 'global_persons'):
                for global_id, person in self.global_tracker.global_persons.items():
                    try:
                        if self.debug_mode:
                            self._draw_debug_projections(person)
                        else:
                            self._draw_person_global_position(person)
                    except Exception as e:
                        print(f"Error drawing person {global_id}: {e}")
        finally:
            self._is_updating = False
            # DO NOT use fitInView - keep fixed scene rect visible
            # Just ensure the view is initialized
            if not self.graphics_view.isVisible():
                self.graphics_view.show()

    def _on_debug_toggled(self, checked: bool):
        """Handle debug toggle button"""
        self.debug_mode = checked
        button_text = "🐛 Debug: ON" if checked else "🐛 Debug: OFF"
        self.debug_toggle.setText(button_text)
        self.update_visualization()

    def _get_camera_homography(self, cam_name: str) -> Optional[np.ndarray]:
        """
        Get or compute homography for a camera.
        Uses cache to avoid recomputation.
        """
        if cam_name in self.homography_cache:
            return self.homography_cache[cam_name]

        try:
            cam_info = self.global_tracker.cameras[cam_name]
            
            # Get frame dimensions (approximate)
            frame_width = 640
            frame_height = 480
            if hasattr(cam_info, 'frame_width'):
                frame_width = cam_info.frame_width
            if hasattr(cam_info, 'frame_height'):
                frame_height = cam_info.frame_height

            H = HomographyProjector.compute_homography_from_calibration(
                camera_pos=cam_info.position,
                camera_rotation=cam_info.rotation,
                fov_degrees=cam_info.fov,
                frame_width=frame_width,
                frame_height=frame_height,
                view_range=cam_info.view_range if hasattr(cam_info, 'view_range') else 300.0
            )

            if H is not None:
                self.homography_cache[cam_name] = H
            return H

        except Exception as e:
            print(f"Error computing homography for {cam_name}: {e}")
            return None

    def _draw_person_global_position(self, person):
        """
        Draw person's stereo-calculated global position (normal mode).
        Shows only the final computed global position as a green dot.
        """
        if not hasattr(person, 'smoothed_position') or person.smoothed_position is None:
            return

        # Transform world coordinates to scene coordinates
        world_x, world_y = person.smoothed_position
        scaled_x = (world_x - self.world_min_x) * self.current_scale + 25
        scaled_y = (world_y - self.world_min_y) * self.current_scale + 25

        # Debug log
        print(f"[BEV STEREO] Person {person.global_id}: world=({world_x:.1f}, {world_y:.1f}) scene=({scaled_x:.1f}, {scaled_y:.1f})")

        # Draw global position marker (green circle)
        marker = QGraphicsEllipseItem(
            scaled_x - 12, scaled_y - 12, 24, 24
        )
        marker.setBrush(QBrush(QColor(0, 255, 0, 180)))
        marker.setPen(QPen(QColor(0, 255, 0), 3))
        self.graphics_scene.addItem(marker)

        # Draw label with person ID and name
        label_text = f"G:{person.global_id}"
        if hasattr(person, 'name') and person.name:
            label_text = f"G:{person.global_id} {person.name}"
        
        label = QGraphicsSimpleTextItem(label_text)
        label.setPos(scaled_x + 15, scaled_y - 15)
        label.setBrush(QBrush(QColor(0, 255, 0)))
        
        font = QFont()
        font.setPointSize(9)
        label.setFont(font)
        
        self.graphics_scene.addItem(label)

    def _draw_debug_projections(self, person):
        """
        Draw per-camera projections in debug mode.
        Shows individual camera projections in different colors and
        the stereo-calculated global position.
        """
        camera_count = 0
        
        # Draw projections from each camera detecting this person
        if hasattr(person, 'camera_tracks'):
            for cam_name, local_track in person.camera_tracks.items():
                try:
                    if cam_name not in self.global_tracker.cameras:
                        continue
                    
                    cam_info = self.global_tracker.cameras[cam_name]
                    
                    # Get or compute homography
                    H = self._get_camera_homography(cam_name)
                    if H is None:
                        continue

                    # Project bbox from this camera
                    if hasattr(local_track, 'bbox') and local_track.bbox:
                        bbox_x, bbox_y, bbox_w, bbox_h = local_track.bbox
                        print(f"[BEV DEBUG] {cam_name}: bbox={local_track.bbox} → unpacked as (x={bbox_x}, y={bbox_y}, w={bbox_w}, h={bbox_h})")
                        
                        # Check if bbox looks like it's in wrong format (x, y, x2, y2)
                        if bbox_w > 640 or bbox_h > 480:  # Looks like x2, y2 instead of w, h
                            print(f"[BEV BBOX WARN] {cam_name}: bbox might be in (x,y,x2,y2) format, not (x,y,w,h)!")
                            print(f"  Converting: ({bbox_x}, {bbox_y}, {bbox_w}, {bbox_h}) → ({bbox_x}, {bbox_y}, {bbox_w-bbox_x}, {bbox_h-bbox_y})")
                            bbox_x, bbox_y, bbox_w, bbox_h = bbox_x, bbox_y, bbox_w - bbox_x, bbox_h - bbox_y
                            bbox_to_use = (bbox_x, bbox_y, bbox_w, bbox_h)
                        else:
                            bbox_to_use = local_track.bbox
                        
                        proj_world = HomographyProjector.project_bbox_to_world(
                            bbox_to_use, H, 480
                        )
                        
                        if proj_world is None:
                            print(f"[BEV CAM-PROJ] {cam_name}: Projection failed for person {person.global_id}")
                            continue
                        
                        proj_x, proj_y = proj_world
                        # Debug log individual camera projection
                        bbox_info = f"bbox={bbox_to_use}" if hasattr(local_track, 'bbox') else "no-bbox"
                        print(f"[BEV CAM-PROJ] {cam_name}: Person {person.global_id} world=({proj_x:.1f}, {proj_y:.1f}) {bbox_info}")
                        
                        # Transform to scene coordinates
                        scaled_proj_x = (proj_x - self.world_min_x) * self.current_scale + 25
                        scaled_proj_y = (proj_y - self.world_min_y) * self.current_scale + 25
                        
                        # Use debug color for this camera
                        color_idx = camera_count % len(DEBUG_COLORS)
                        r, g, b = DEBUG_COLORS[color_idx]
                        color = QColor(r, g, b)
                        
                        # Draw projection point
                        circle = QGraphicsEllipseItem(
                            scaled_proj_x - 8, scaled_proj_y - 8, 16, 16
                        )
                        circle.setBrush(QBrush(color))
                        circle.setPen(QPen(color, 2))
                        self.graphics_scene.addItem(circle)
                        
                        # Draw label: Camera name
                        label = QGraphicsSimpleTextItem(cam_name)
                        label.setPos(scaled_proj_x + 10, scaled_proj_y - 10)
                        label.setBrush(QBrush(color))
                        
                        font = QFont()
                        font.setPointSize(8)
                        label.setFont(font)
                        
                        self.graphics_scene.addItem(label)
                        
                        # Draw line from camera position to projection
                        cam_scaled_x = (cam_info.position[0] - self.world_min_x) * self.current_scale + 25
                        cam_scaled_y = (cam_info.position[1] - self.world_min_y) * self.current_scale + 25
                        
                        line = QGraphicsLineItem(
                            cam_scaled_x, cam_scaled_y,
                            scaled_proj_x, scaled_proj_y
                        )
                        line_pen = QPen(color)
                        line_pen.setStyle(Qt.PenStyle.DashLine)
                        line_pen.setWidth(1)
                        line.setPen(line_pen)
                        self.graphics_scene.addItem(line)
                        
                        camera_count += 1
                
                except Exception as e:
                    print(f"[BEV CAM-PROJ ERROR] {cam_name}: {e}")
        
        # Summary debug log for this person
        print(f"[BEV PERSON] ID {person.global_id}: detected in {camera_count} camera(s)")

        # Draw global stereo position (green, prominent)
        if hasattr(person, 'smoothed_position') and person.smoothed_position:
            world_x, world_y = person.smoothed_position
            # Transform to scene coordinates
            scaled_x = (world_x - self.world_min_x) * self.current_scale + 25
            scaled_y = (world_y - self.world_min_y) * self.current_scale + 25

            # Draw global position as larger circle
            global_marker = QGraphicsEllipseItem(
                scaled_x - 15, scaled_y - 15, 30, 30
            )
            global_marker.setBrush(QBrush(QColor(0, 255, 0, 150)))
            global_marker.setPen(QPen(QColor(0, 255, 0), 4))
            self.graphics_scene.addItem(global_marker)

            # Draw label with stereo indicator
            label_text = f"STEREO:{person.global_id}"
            if hasattr(person, 'name') and person.name:
                label_text = f"{person.name}({camera_count})"
            
            label = QGraphicsSimpleTextItem(label_text)
            label.setPos(scaled_x + 20, scaled_y - 20)
            label.setBrush(QBrush(QColor(0, 255, 0)))
            
            font = QFont()
            font.setPointSize(9)
            font.setBold(True)
            label.setFont(font)
            
            self.graphics_scene.addItem(label)

    def showEvent(self, event):
        """Called when widget becomes visible - start update timer"""
        super().showEvent(event)
        self._start_timer()
    
    def hideEvent(self, event):
        """Called when widget is hidden - stop update timer"""
        self._stop_timer()
        super().hideEvent(event)
    
    def _start_timer(self):
        """Start the update timer if not already running"""
        if self._timer_active or self.update_timer is not None:
            return
        
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._on_timer_tick)
        self.update_timer.start(100)  # Update every 100ms
        self._timer_active = True
    
    def _stop_timer(self):
        """Stop the update timer"""
        if self.update_timer is not None:
            self.update_timer.stop()
            self.update_timer.deleteLater()
            self.update_timer = None
        self._timer_active = False
    
    def _on_timer_tick(self):
        """Periodic update timer callback"""
        if self.global_tracker is not None and not self._is_updating:
            try:
                self.update_visualization()
            except Exception as e:
                print(f"[BEV] Timer update error: {e}")

    def clear_cache(self):
        """Clear homography cache (call when camera calibration changes)"""
        self.homography_cache.clear()

    def wheelEvent(self, event):
        """Handle mouse wheel for zoom"""
        factor = 1.15
        if event.angleDelta().y() < 0:
            factor = 1 / factor
        
        self.graphics_view.scale(factor, factor)

    def resizeEvent(self, event):
        """Handle resize - no need to fitInView as we use fixed scene rect"""
        super().resizeEvent(event)
        # Scene rect is already set in update_visualization
        # Just let the view render the fixed scene rect
