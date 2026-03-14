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

        # Draw camera position as a small circle
        camera_pen = QPen(QColor(0, 200, 0), 2)
        camera_brush = QBrush(QColor(0, 200, 0, 100))
        painter.setPen(camera_pen)
        painter.setBrush(camera_brush)
        painter.drawEllipse(int(scaled_x - 8), int(scaled_y - 8), 16, 16)

        # Draw FOV cone
        cone_radius = 150  # pixels
        half_fov = self.fov / 2
        
        # Rotation in radians
        rotation_rad = math.radians(self.rotation)
        
        # Draw FOV cone lines
        cone_pen = QPen(QColor(0, 150, 0, 150), 1, Qt.PenStyle.DashLine)
        painter.setPen(cone_pen)
        
        # Left edge of cone
        left_angle = rotation_rad - math.radians(half_fov)
        left_x = scaled_x + cone_radius * math.sin(left_angle)
        left_y = scaled_y + cone_radius * math.cos(left_angle)
        painter.drawLine(int(scaled_x), int(scaled_y), int(left_x), int(left_y))
        
        # Right edge of cone
        right_angle = rotation_rad + math.radians(half_fov)
        right_x = scaled_x + cone_radius * math.sin(right_angle)
        right_y = scaled_y + cone_radius * math.cos(right_angle)
        painter.drawLine(int(scaled_x), int(scaled_y), int(right_x), int(right_y))

        # Draw camera name label
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QPen(QColor(0, 200, 0)))
        painter.drawText(int(scaled_x + 15), int(scaled_y - 10), self.cam_name)


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
            print("[BEV] DEBUG: global_tracker is None")
            return

        self._is_updating = True
        try:
            self.graphics_scene.clear()

            # Calculate scene bounds based on camera and person positions
            min_x, max_x = 0, 1200
            min_y, max_y = 0, 1200
            
            # Check camera positions
            for cam_info in self.global_tracker.cameras.values():
                cam_scaled_x = cam_info.position[0] * GRID_PIXELS_PER_UNIT
                cam_scaled_y = cam_info.position[1] * GRID_PIXELS_PER_UNIT
                min_x = min(min_x, cam_scaled_x - 200)
                max_x = max(max_x, cam_scaled_x + 200)
                min_y = min(min_y, cam_scaled_y - 200)
                max_y = max(max_y, cam_scaled_y + 200)
            
            # Check person positions
            for person in self.global_tracker.global_persons.values():
                if hasattr(person, 'smoothed_position') and person.smoothed_position:
                    pers_scaled_x = person.smoothed_position[0] * GRID_PIXELS_PER_UNIT
                    pers_scaled_y = person.smoothed_position[1] * GRID_PIXELS_PER_UNIT
                    min_x = min(min_x, pers_scaled_x - 50)
                    max_x = max(max_x, pers_scaled_x + 50)
                    min_y = min(min_y, pers_scaled_y - 50)
                    max_y = max(max_y, pers_scaled_y + 50)
            
            # Ensure minimum scene size
            scene_width = max(max_x - min_x, 1200)
            scene_height = max(max_y - min_y, 1200)
            
            # Set scene rect with padding
            padding = 100
            self.graphics_scene.setSceneRect(
                min_x - padding, 
                min_y - padding, 
                scene_width + 2*padding, 
                scene_height + 2*padding
            )
            
            print(f"[BEV] DEBUG: Scene rect: ({min_x}, {min_y}, {scene_width}, {scene_height})")

            # DEBUG: Print what we have
            print(f"[BEV] DEBUG: scene_cameras keys = {list(self.scene_cameras.keys())}")
            print(f"[BEV] DEBUG: global_tracker.cameras keys = {list(self.global_tracker.cameras.keys())}")
            print(f"[BEV] DEBUG: global_persons count = {len(self.global_tracker.global_persons)}")
            print(f"[BEV] DEBUG: debug_mode = {self.debug_mode}")

            # Draw grid background
            grid = GridOverlay(int(scene_width + 2*padding), int(scene_height + 2*padding), GRID_SIZE)
            grid.setPos(min_x - padding, min_y - padding)
            self.graphics_scene.addItem(grid)
            print("[BEV] DEBUG: Grid added to scene")

            # Draw camera visualizations
            for cam_name, cam_item in self.scene_cameras.items():
                try:
                    # Get camera info from tracker
                    if cam_name not in self.global_tracker.cameras:
                        print(f"[BEV] DEBUG: Camera {cam_name} not in tracker.cameras")
                        continue
                    
                    cam_info = self.global_tracker.cameras[cam_name]
                    print(f"[BEV] DEBUG: Drawing camera {cam_name} at {cam_info.position}")
                    
                    cam_viz = CameraVisualization(
                        cam_name=cam_name,
                        position=cam_info.position,
                        rotation=cam_info.rotation,
                        fov=cam_info.fov,
                        scale=GRID_PIXELS_PER_UNIT
                    )
                    self.graphics_scene.addItem(cam_viz)
                except Exception as e:
                    print(f"Error drawing camera {cam_name}: {e}")

            # Draw persons
            if hasattr(self.global_tracker, 'global_persons'):
                print(f"[BEV] DEBUG: Found {len(self.global_tracker.global_persons)} global persons")
                for global_id, person in self.global_tracker.global_persons.items():
                    try:
                        print(f"[BEV] DEBUG: Drawing person {global_id}, smoothed_pos={getattr(person, 'smoothed_position', None)}")
                        if self.debug_mode:
                            self._draw_debug_projections(person)
                        else:
                            self._draw_person_global_position(person)
                    except Exception as e:
                        print(f"Error drawing person {global_id}: {e}")
        finally:
            self._is_updating = False
            # Fit view to show all scene items after drawing
            if self.graphics_scene.items():
                self.graphics_view.fitInView(
                    self.graphics_scene.itemsBoundingRect(),
                    Qt.AspectRatioMode.KeepAspectRatio
                )

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

        world_x, world_y = person.smoothed_position
        scaled_x = world_x * GRID_PIXELS_PER_UNIT
        scaled_y = world_y * GRID_PIXELS_PER_UNIT

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
                        proj_world = HomographyProjector.project_bbox_to_world(
                            local_track.bbox, H, 480
                        )
                        
                        if proj_world is None:
                            continue
                        
                        proj_x, proj_y = proj_world
                        scaled_proj_x = proj_x * GRID_PIXELS_PER_UNIT
                        scaled_proj_y = proj_y * GRID_PIXELS_PER_UNIT
                        
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
                        cam_scaled_x = cam_info.position[0] * GRID_PIXELS_PER_UNIT
                        cam_scaled_y = cam_info.position[1] * GRID_PIXELS_PER_UNIT
                        
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
                    print(f"Error drawing projection for {cam_name}: {e}")

        # Draw global stereo position (green, prominent)
        if hasattr(person, 'smoothed_position') and person.smoothed_position:
            world_x, world_y = person.smoothed_position
            scaled_x = world_x * GRID_PIXELS_PER_UNIT
            scaled_y = world_y * GRID_PIXELS_PER_UNIT

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
        print("[BEV] showEvent - starting timer")
        self._start_timer()
    
    def hideEvent(self, event):
        """Called when widget is hidden - stop update timer"""
        print("[BEV] hideEvent - stopping timer")
        self._stop_timer()
        super().hideEvent(event)
    
    def _start_timer(self):
        """Start the update timer if not already running"""
        if self._timer_active or self.update_timer is not None:
            print("[BEV] Timer already running, skipping")
            return
        
        print("[BEV] Creating and starting timer")
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._on_timer_tick)
        self.update_timer.start(100)  # Update every 100ms
        self._timer_active = True
        print("[BEV] Timer started")
    
    def _stop_timer(self):
        """Stop the update timer"""
        if self.update_timer is not None:
            self.update_timer.stop()
            self.update_timer.deleteLater()
            self.update_timer = None
        self._timer_active = False
        print("[BEV] Timer stopped")
    
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
        """Fit scene to view on resize"""
        super().resizeEvent(event)
        if not self.graphics_scene.items():
            return
        
        self.graphics_view.fitInView(
            self.graphics_scene.itemsBoundingRect(),
            Qt.AspectRatioMode.KeepAspectRatio
        )
