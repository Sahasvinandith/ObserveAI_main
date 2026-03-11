"""
GridFloor - A calibrated grid overlay for the QGraphicsScene floor plan.

Draws a meter-based grid on the scene with:
- Grid lines at regular intervals (1 meter per square by default)
- Scale label showing "1 square = Xm"
- Coordinate labels at grid intersections on hover
"""

import math
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, 
    QGraphicsSimpleTextItem, QGraphicsObject,
    QGraphicsSceneHoverEvent
)
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QFontMetrics
)
from PyQt6.QtCore import Qt, QRectF, QPointF


class GridFloor(QGraphicsObject):
    """
    A grid overlay that represents real-world meters on the floor plan.
    
    The grid cell size is determined by `pixels_per_meter`:
    - Each grid square = 1 meter × 1 meter in real life
    - Grid lines are drawn at pixel intervals of `pixels_per_meter`
    
    Features:
    - Subtle grid lines that don't overpower the camera cones
    - Scale label in the corner
    - Coordinate tooltip on hover (shows meters from origin)
    """
    
    def __init__(self, scene_width: float = 1200, scene_height: float = 1200,
                 pixels_per_meter: float = 30.0, parent=None):
        super().__init__(parent)
        
        self.scene_width = scene_width
        self.scene_height = scene_height
        self.pixels_per_meter = pixels_per_meter
        
        # Visual settings
        self.grid_color = QColor(60, 60, 80, 120)         # Subtle blue-gray
        self.grid_color_major = QColor(80, 80, 110, 180)   # Slightly brighter for every 5m
        self.origin_color = QColor(255, 100, 100, 200)     # Red for origin axes
        self.text_color = QColor(180, 180, 200, 220)       # Light gray for labels
        self.bg_color = QColor(25, 25, 35)                 # Dark background
        
        self.label_font = QFont("Segoe UI", 8)
        self.scale_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        
        # Hover coordinate display
        self._hover_pos = None
        self._hover_coord_text = ""
        self.setAcceptHoverEvents(True)
        
        # Draw behind everything
        self.setZValue(-1000)
        
        # Coordinate label items at intersections — created on demand
        self._coord_label = QGraphicsSimpleTextItem(self)
        self._coord_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._coord_label.setBrush(QBrush(QColor(255, 255, 255, 230)))
        self._coord_label.setZValue(2000)
        self._coord_label.setVisible(False)
        
        # Background for coordinate label
        self._coord_bg = QGraphicsRectItem(self)
        self._coord_bg.setBrush(QBrush(QColor(30, 30, 50, 220)))
        self._coord_bg.setPen(QPen(QColor(100, 130, 255, 180), 1))
        self._coord_bg.setZValue(1999)
        self._coord_bg.setVisible(False)
    
    def set_pixels_per_meter(self, ppm: float):
        """Update the scale and redraw the grid."""
        self.pixels_per_meter = ppm
        self.update()
    
    def set_scene_size(self, width: float, height: float):
        """Update the grid to cover a new scene size."""
        self.prepareGeometryChange()
        self.scene_width = width
        self.scene_height = height
        self.update()
    
    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.scene_width, self.scene_height)
    
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        
        ppm = self.pixels_per_meter
        if ppm <= 0:
            return
        
        rect = self.boundingRect()
        
        # --- 1. Draw background ---
        painter.fillRect(rect, QBrush(self.bg_color))
        
        # --- 2. Draw grid lines ---
        # Minor grid: every 1 meter
        minor_pen = QPen(self.grid_color, 1, Qt.PenStyle.SolidLine)
        # Major grid: every 5 meters
        major_pen = QPen(self.grid_color_major, 1.5, Qt.PenStyle.SolidLine)
        
        # Calculate grid bounds
        max_x = int(rect.width())
        max_y = int(rect.height())
        
        # Vertical lines
        meter_index = 0
        x = 0.0
        while x <= max_x:
            if meter_index % 5 == 0:
                painter.setPen(major_pen)
            else:
                painter.setPen(minor_pen)
            px = int(x)
            painter.drawLine(px, 0, px, max_y)
            x += ppm
            meter_index += 1
        
        # Horizontal lines
        meter_index = 0
        y = 0.0
        while y <= max_y:
            if meter_index % 5 == 0:
                painter.setPen(major_pen)
            else:
                painter.setPen(minor_pen)
            py = int(y)
            painter.drawLine(0, py, max_x, py)
            y += ppm
            meter_index += 1
        
        # --- 3. Draw origin axes (thicker, colored) ---
        origin_pen = QPen(self.origin_color, 2, Qt.PenStyle.SolidLine)
        painter.setPen(origin_pen)
        painter.drawLine(0, 0, max_x, 0)  # Top edge (X axis)
        painter.drawLine(0, 0, 0, max_y)  # Left edge (Y axis)
        
        # --- 4. Draw meter labels along edges ---
        painter.setFont(self.label_font)
        painter.setPen(QPen(self.text_color))
        
        # X-axis labels (along top)
        meter_index = 0
        x = 0.0
        while x <= max_x:
            if meter_index % 5 == 0 and meter_index > 0:
                label = f"{meter_index}m"
                painter.drawText(int(x) + 3, 14, label)
            x += ppm
            meter_index += 1
        
        # Y-axis labels (along left)
        meter_index = 0
        y = 0.0
        while y <= max_y:
            if meter_index % 5 == 0 and meter_index > 0:
                label = f"{meter_index}m"
                painter.drawText(3, int(y) - 3, label)
            y += ppm
            meter_index += 1
        
        # --- 5. Draw scale indicator ---
        painter.setFont(self.scale_font)
        painter.setPen(QPen(QColor(200, 200, 230, 250)))
        
        # Scale box in bottom-left corner
        scale_text = f"1 square = 1m  ({self.pixels_per_meter:.0f} px/m)"
        text_rect = QFontMetrics(self.scale_font).boundingRect(scale_text)
        
        box_x = 10
        box_y = max_y - 35
        box_w = text_rect.width() + 20
        box_h = 28
        
        # Background box
        painter.fillRect(int(box_x), int(box_y), int(box_w), int(box_h),
                        QBrush(QColor(20, 20, 35, 200)))
        painter.setPen(QPen(QColor(80, 100, 180, 180), 1))
        painter.drawRect(int(box_x), int(box_y), int(box_w), int(box_h))
        
        # Text
        painter.setPen(QPen(QColor(200, 200, 230, 250)))
        painter.drawText(box_x + 10, box_y + 20, scale_text)
    
    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
        """Show coordinate tooltip when hovering near grid intersections."""
        pos = event.pos()
        ppm = self.pixels_per_meter
        
        if ppm <= 0:
            self._coord_label.setVisible(False)
            self._coord_bg.setVisible(False)
            return
        
        # Find nearest grid intersection
        meter_x = pos.x() / ppm
        meter_y = pos.y() / ppm
        
        snap_meter_x = round(meter_x)
        snap_meter_y = round(meter_y)
        
        snap_px_x = snap_meter_x * ppm
        snap_px_y = snap_meter_y * ppm
        
        # Only show label if close to an intersection (within 0.3 meters)
        dist_px = math.sqrt((pos.x() - snap_px_x)**2 + (pos.y() - snap_px_y)**2)
        threshold = ppm * 0.3  # 30% of a grid cell
        
        if dist_px < threshold:
            coord_text = f"({snap_meter_x:.0f}m, {snap_meter_y:.0f}m)"
            self._coord_label.setText(coord_text)
            
            # Position the label near the intersection
            label_rect = self._coord_label.boundingRect()
            label_x = snap_px_x + 6
            label_y = snap_px_y - label_rect.height() - 4
            
            # Keep label inside the scene
            if label_x + label_rect.width() > self.scene_width:
                label_x = snap_px_x - label_rect.width() - 6
            if label_y < 0:
                label_y = snap_px_y + 6
            
            self._coord_label.setPos(label_x, label_y)
            self._coord_label.setVisible(True)
            
            # Background rectangle
            pad = 4
            self._coord_bg.setRect(
                label_x - pad, label_y - pad,
                label_rect.width() + pad * 2, label_rect.height() + pad * 2
            )
            self._coord_bg.setVisible(True)
        else:
            self._coord_label.setVisible(False)
            self._coord_bg.setVisible(False)
    
    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        """Hide coordinate label when mouse leaves the grid."""
        self._coord_label.setVisible(False)
        self._coord_bg.setVisible(False)
