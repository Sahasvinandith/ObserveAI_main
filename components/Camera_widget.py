import math
from PyQt6.QtWidgets import (
    QGraphicsObject, 
    QGraphicsPixmapItem, 
    QGraphicsPolygonItem, 
    QGraphicsItem,
    QGraphicsSimpleTextItem
)
from PyQt6.QtGui import (
    QPixmap, 
    QPolygonF, 
    QColor, 
    QBrush, 
    QPen
)
from PyQt6.QtCore import QPointF, QLineF, Qt, QRectF

from components.Wall import WallItem


class CameraItem(QGraphicsObject):
    """
    A custom graphics item representing a camera.
    It contains a pixmap for the icon and a polygon for the FOV.
    It automatically updates its FOV by ray casting against WallItems.
    """
    def __init__(self, parent=None,name="Webcam", url="0"):
        super().__init__(parent)
        
        # 1. SETTINGS (You can change these)
        self.view_angle = 70.0  # Field of View in degrees
        self.view_range = 200.0 # Max range in pixels
        self.view_rays = 90     # Number of rays to cast (more is smoother)
        self.name = name
        self.url = url

        # 2. CHILD ITEMS
        # --- The camera icon ---
        self.pixmap_item = QGraphicsPixmapItem(self)
        try:
            # Make sure 'camera.png' is in the same directory
            # or you provide the full path
            pix = QPixmap("./images/cctv_logo_light.png") 
            self.pixmap_item.setPixmap(pix.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio))
        except Exception as e:
            print(f"Warning: Could not load camera.png. {e}")
            
        # Center the pixmap on the item's (0,0) origin
        rect = self.pixmap_item.boundingRect()
        self.pixmap_item.setOffset(-rect.width() / 2, -rect.height() / 2)

        # --- The FOV cone ---
        self.fov_item = QGraphicsPolygonItem(self)
        self.fov_item.setBrush(QBrush(QColor(255, 255, 0, 60))) # Semi-transparent yellow
        self.fov_item.setPen(QPen(QColor(255, 255, 0, 100), 1))
        self.fov_item.setZValue(-1) # Draw FOV *behind* the camera icon
        
        # --- NEW: The camera name label ---
        self.text_item = QGraphicsSimpleTextItem(name, self)
        self.text_item.setBrush(QBrush(QColor(255, 255, 255))) # White text
        self.text_item.setZValue(1) # Draw label on top of icon

        # Center the text *below* the camera icon
        pixmap_rect = self.pixmap_item.boundingRect()
        text_rect = self.text_item.boundingRect()
        
        # Position it:
        # X: Centered horizontally relative to the item's (0,0)
        # Y: Just below the pixmap's bottom edge
        self.text_item.setPos(
            -text_rect.width() / 2,
            pixmap_rect.height() / 2
        )

        # --- THIS IS THE IMPORTANT PART ---
        # Stop the text from rotating with the parent
        self.text_item.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
        )

        # 3. ITEM FLAGS
        # Make the whole group movable, selectable, and make it
        # notify us when its position changes.
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges
        )
        
        # We need this to get keyboard focus to allow rotation
        self.setAcceptHoverEvents(True)

    # We must implement these two methods for a QGraphicsObject
    def boundingRect(self):
        # Return the combined bounding rect of the children
        return self.childrenBoundingRect()

    def paint(self, painter, option, widget):
        # We don't need to paint anything ourselves, 
        # the child items (pixmap and fov) do the painting.
        pass

    # 4. THE TRIGGER FOR FOV UPDATES
    # This is called whenever the item's state changes
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and self.scene():
            # When the item moves, update the FOV
            self.updateFov()
        return super().itemChange(change, value)

    # Also update FOV when rotated
    def setRotation(self, rotation):
        super().setRotation(rotation)
        self.updateFov()

    # 5. THE CORE LOGIC: UPDATE FOV
    def updateFov(self):
        if not self.scene():
            return # Can't do anything if not in a scene

        # Get all walls from the scene
        walls = [item for item in self.scene().items() if isinstance(item, WallItem)]
        
        # This will hold the points of our FOV polygon
        fov_points = [QPointF(0, 0)] # Start at the camera's center (local 0,0)
        
        camera_pos = self.scenePos()
        camera_rotation = self.rotation() # Get item's rotation
        
        # Cast rays
        start_angle = -camera_rotation - (self.view_angle / 2)
        
        for i in range(self.view_rays + 1):
            # Calculate the angle of the current ray
            current_angle = start_angle + (self.view_angle * i / self.view_rays)
            
            # Calculate the end point of the ray at max range
            rad = math.radians(current_angle)
            end_x = self.view_range * math.cos(rad)
            end_y = -self.view_range * math.sin(rad) # Y is inverted
            
            # Create the ray as a line in SCENE coordinates
            ray_line = QLineF(camera_pos, camera_pos + QPointF(end_x, end_y))
            # print(f"line coordinates: {camera_pos.x(),camera_pos.y(),end_x,end_y}")
            
            # This will be the final end-point of our ray
            closest_intersection = ray_line.p2()
            min_dist_sq = self.view_range**2

            # Check this ray against EVERY wall
            for wall in walls:
                # 1. Get the wall's 4 corners in its *local* coordinate system
                local_rect = wall.rect()
                p1_local = local_rect.topLeft()
                p2_local = local_rect.topRight()
                p3_local = local_rect.bottomRight()
                p4_local = local_rect.bottomLeft()

                # 2. Get the wall's transformation (position + rotation)
                transform = wall.sceneTransform()

                # 3. Map the 4 local corners to their *true* scene positions
                p1_scene = transform.map(p1_local)
                p2_scene = transform.map(p2_local)
                p3_scene = transform.map(p3_local)
                p4_scene = transform.map(p4_local)

                # 4. Create the 4 *actual* rotated edge lines
                wall_lines = [
                    QLineF(p1_scene, p2_scene),
                    QLineF(p2_scene, p3_scene),
                    QLineF(p3_scene, p4_scene),
                    QLineF(p4_scene, p1_scene),
                ]
                
                for line in wall_lines:
                    # Check for intersection
                    intersect_type, intersect_point = ray_line.intersects(line)
                    
                    if intersect_type == QLineF.IntersectionType.BoundedIntersection:
                        # We hit a wall! Check if it's the closest hit so far
                        dist_sq = QLineF(camera_pos, intersect_point).length()**2
                        if dist_sq < min_dist_sq:
                            min_dist_sq = dist_sq
                            closest_intersection = intersect_point
            
            # Add the final point to our polygon
            # We must map it from scene coordinates back to this item's
            # local coordinates, since the fov_item is a child.
            fov_points.append(self.mapFromScene(closest_intersection))

        # Update the polygon item
        self.fov_item.setPolygon(QPolygonF(fov_points))
        
    # 6. (Optional) Add rotation with Ctrl + Mouse Wheel
    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Rotate camera
            if event.delta() > 0:
                self.setRotation(self.rotation() - 5) # Rotate right
            else:
                self.setRotation(self.rotation() + 5) # Rotate left
            event.accept()
        else:
            # Let the scene handle zooming
            event.ignore()
            
    # Show a tooltip
    def hoverEnterEvent(self, event):
        self.setToolTip("Camera (Drag to move, Ctrl+Wheel to rotate)")
        super().hoverEnterEvent(event)