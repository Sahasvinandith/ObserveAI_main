from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QBrush, QPen
from PyQt6.QtWidgets import (QGraphicsItem, QGraphicsRectItem)

class WallItem(QGraphicsRectItem):
    """
    A custom rectangular item that represents a wall.
    It can be rotated and resized using keyboard keys.
    """
    def __init__(self, x, y, width, height):
        # Call the parent __init__ with the rectangle's geometry
        # (x, y, width, height) relative to the item's local 0,0
        super().__init__(-width / 2, -height / 2, width, height)
        
        # Set the item's initial position in the scene
        self.setPos((2*x+width)/2, (2*x+height)/2)
        
        # Set visual properties
        self.setBrush(QBrush(QColor(150, 150, 150))) # Gray color
        self.setPen(QPen(QColor(150, 150, 150), 2))     # Dark border
        
        # self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        # --- Set flags to make it interactive ---
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable) # CRITICAL: to receive key presses
        
        # --- Set rotation origin to the center ---
        # This makes rotation feel natural
        self.setTransformOriginPoint(0,0)

    def keyPressEvent(self, event):
        """
        This event handler is called when the item has focus and a key is pressed.
        """
        
        # --- Handle Rotation ---
        if event.key() == Qt.Key.Key_R:
            # Get current rotation and add 15 degrees
            current_rotation = self.rotation()
            self.setRotation(current_rotation + 15)
            print(f"Rotated to: {self.rotation()} degrees")

        # --- Handle Resizing (Grow) ---
        elif event.key() == Qt.Key.Key_Plus or event.key() == Qt.Key.Key_Equal:
            current_rect = self.rect() # Get the current QRectF
            new_width = current_rect.width() + 10
            
            
            # Set the new rectangle
            self.setRect(-10,-10, new_width, current_rect.height())
            
            # IMPORTANT: Update the transform origin to the new center
            self.setTransformOriginPoint(new_width / 2, current_rect.height() / 2)
            print(f"Resized to width: {new_width}")

        # --- Handle Resizing (Shrink) ---
        elif event.key() == Qt.Key.Key_Minus:
            current_rect = self.rect()
            # Don't let it get smaller than 10 pixels
            new_width = max(10, current_rect.width() - 10) 
            
            self.setRect(0, 0, new_width, current_rect.height())
            
            # Update the transform origin
            self.setTransformOriginPoint(new_width / 2, current_rect.height() / 2)
            print(f"Resized to width: {new_width}")
            
        else:
            # Pass other key events to the parent class
            super().keyPressEvent(event)