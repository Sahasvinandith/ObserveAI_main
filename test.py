from PyQt6.QtWidgets import (QGraphicsItem,QGraphicsScene,QApplication, QMainWindow, QLabel, QVBoxLayout,QLineEdit,QDialogButtonBox,QDialog, QGraphicsRectItem)
import sys
from PyQt6.uic import loadUi
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QBrush, QPen

class WallItem(QGraphicsRectItem):
    """
    A custom rectangular item that represents a wall.
    It can be rotated and resized using keyboard keys.
    """
    def __init__(self, x, y, width, height):
        # Call the parent __init__ with the rectangle's geometry
        # (x, y, width, height) relative to the item's local 0,0
        super().__init__(0, 0, width, height)
        
        # Set the item's initial position in the scene
        self.setPos(x, y)
        
        # Set visual properties
        self.setBrush(QBrush(QColor(150, 150, 150))) # Gray color
        self.setPen(QPen(QColor(20, 20, 20), 2))     # Dark border
        
        # self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        # --- Set flags to make it interactive ---
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable) # CRITICAL: to receive key presses
        
        # --- Set rotation origin to the center ---
        # This makes rotation feel natural
        self.setTransformOriginPoint(width / 2, height / 2)

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
            self.setRect(0, 0, new_width, current_rect.height())
            
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

# --- AddCameraDialog class (no changes) ---
class AddCameraDialog(QDialog):
    """
    A simple popup dialog to get a camera name and IP/URL.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Camera")
        
        self.layout = QVBoxLayout(self)
        # Camera Name Entry
        self.name_label = QLabel("Camera Name:")
        self.name_input = QLineEdit("Lobby Camera")
        self.layout.addWidget(self.name_label)
        self.layout.addWidget(self.name_input)
        
        # Camera URL/IP Entry
        self.url_label = QLabel("Camera URL (or 0 for webcam):")
        self.url_input = QLineEdit("0")
        self.layout.addWidget(self.url_label)
        self.layout.addWidget(self.url_input)
        
        # OK and Cancel Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def get_details(self):
        """Helper function to return the entered text."""
        return self.name_input.text(), self.url_input.text()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        loadUi("./UIs/main.ui", self)
        
        self.graphics_scene = QGraphicsScene()

        # 2. Tell your 'drag_area' (the QGraphicsView) to look at this new scene
        self.drag_area.setScene(self.graphics_scene)

        # 3. (Optional but recommended) Set a size for the scene
        self.graphics_scene.setSceneRect(0, 0, 1200, 1200)
        
        
        self.signal_setup()
        self.Content_stack.setCurrentIndex(0)
    
    def signal_setup(self):
        self.cam_set_btn.clicked.connect(lambda: self.Content_stack.setCurrentIndex(0))
        self.cam_feed_btn.clicked.connect(lambda: self.Content_stack.setCurrentIndex(1))       
        self.db_btn.clicked.connect(lambda: self.Content_stack.setCurrentIndex(2))
        self.add_camera_btn.clicked.connect(self.show_add_camera_dialog)
        self.add_wall_btn.clicked.connect(self.add_a_wall)
    
    def add_a_wall(self):
        wall = WallItem(30,30,150,20)
        print(f"tpye of {type(self.drag_area.scene())}")
        self.drag_area.scene().addItem(wall)
    
    def show_add_camera_dialog(self):
        """
        Called when the 'actionAdd_Camera' (button) is triggered.
        """
        dialog = AddCameraDialog(self)
        
        if dialog.exec():
            name, url = dialog.get_details()
            if name and url:
                print(f"Adding camera: {name}, {url}")
                
                # # --- !! NEW, CORRECT ORDER !! ---
                
                # # 1. Create the new camera widget
                # #    Its __init__ will run and return immediately.
                # new_cam = CameraWidget(name, url, self.scene)
                
                # # 2. Connect the signal. The "wire" is now live,
                # #    waiting for the camera to emit.
                # new_cam.camera_added.connect(self.add_camera_to_list)
                
                # # 3. Add the widget to the scene
                # self.scene.addItem(new_cam)
                
                # # 4. Store a reference
                # self.cameras[name] = new_cam 
                # print("xrr")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
