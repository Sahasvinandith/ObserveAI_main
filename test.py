from PyQt6.QtWidgets import (QListWidgetItem,QGraphicsItem,QGraphicsScene,QApplication, QMainWindow, QLabel, QVBoxLayout,QLineEdit,QDialogButtonBox,QDialog, QGraphicsRectItem)
import sys
from PyQt6.uic import loadUi
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QBrush, QPen
from components.Wall import WallItem
from components.AddCamera_Dialog import AddCameraDialog
from components.Camera_widget import CameraItem
from components.Camera_list_widget import CameraFeedWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        loadUi("./UIs/main.ui", self)
        
        self.graphics_scene = QGraphicsScene()

        # 2. Tell your 'drag_area' (the QGraphicsView) to look at this new scene
        self.drag_area.setScene(self.graphics_scene)

        # 3. (Optional but recommended) Set a size for the scene
        self.graphics_scene.setSceneRect(0, 0, 1200, 1200)
        # --- List for cleanup ---
        self.feed_widgets = []
        
        
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
        
        self.show_add_camera_dialog()
        
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
                
                cam = CameraItem(name=name, url=url)
                cam.setPos(30,30)
                # Add the camera to the scene (at position 0,0 by default)
                self.drag_area.scene().addItem(cam)
                
                # Adding the camera feed to the list
                feed_widget = CameraFeedWidget(name, url)
                self.feed_widgets.append(feed_widget)
                
                item = QListWidgetItem()
                
                # 3. Set the row's size to match the widget
                item.setSizeHint(feed_widget.sizeHint())
                
                # 4. Add the row to the list
                self.cam_list.addItem(item)
                
                # 5. Set your custom widget to be the content of that row
                self.cam_list.setItemWidget(item, feed_widget)
                
    def closeEvent(self, event):
        """
        This is crucial! It stops all camera threads
        when you close the main window.
        """
        print("Window closing, stopping all camera feeds...")
        for widget in self.feed_widgets:
            widget.stop_feed()
        
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.setWindowTitle("ObserveAI")
    # window.showMaximized()
    window.showMinimized()
    sys.exit(app.exec())
