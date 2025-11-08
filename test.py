from PyQt6.QtWidgets import (QGraphicsItem,QGraphicsScene,QApplication, QMainWindow, QLabel, QVBoxLayout,QLineEdit,QDialogButtonBox,QDialog, QGraphicsRectItem)
import sys
from PyQt6.uic import loadUi
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QBrush, QPen
from components.Wall import WallItem

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
        wall = WallItem(30,30,150,10)
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
