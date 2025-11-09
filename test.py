from PyQt6.QtWidgets import (QGraphicsItem,QGraphicsScene,QApplication, QMainWindow, QLabel, QVBoxLayout,QLineEdit,QDialogButtonBox,QDialog, QGraphicsRectItem)
import sys
from PyQt6.uic import loadUi
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QBrush, QPen
from components.Wall import WallItem
from components.AddCamera_Dialog import AddCameraDialog
from components.Camera_widget import CameraItem

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
        self.add_camera_btn.clicked.connect(self.add_camera)
        self.add_wall_btn.clicked.connect(self.add_a_wall)
    
    def add_a_wall(self):
        wall = WallItem(30,30,150,10)
        self.drag_area.scene().addItem(wall)
        
    def add_camera(self):
        """
        Called when the 'addCameraButton' is clicked.
        """
        cam = CameraItem()
        
        cam.setPos(30,30)
        
        # Add the camera to the scene (at position 0,0 by default)
        self.drag_area.scene().addItem(cam)
        
        # Set its position to the center of the current view
        # (This is more user-friendly)
        # center_point = self.drag_area.mapToScene(self.graphics_scene.viewport().rect().center())
        # cam.setPos()
        print("Camera added.")
    
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
    window.setWindowTitle("ObserveAI")
    window.showMaximized()
    sys.exit(app.exec())
