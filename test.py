import json
from PyQt6.QtWidgets import (QListWidgetItem,QFileDialog,QGraphicsScene,QApplication, QMainWindow, QLabel, QVBoxLayout,QLineEdit,QDialogButtonBox,QDialog, QGraphicsRectItem)
import sys
from PyQt6.QtCore import QPointF, QSize
from PyQt6.uic import loadUi
from components.Wall import WallItem
from components.AddCamera_Dialog import AddCameraDialog
from components.Camera_widget import CameraItem
from components.Camera_list_widget import CameraFeedWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        loadUi("./UIs/main.ui", self)
        
        self.graphics_scene = QGraphicsScene()
        
        #  ADD TRACKERS ---
        # These will keep track of all items for saving
        self.feed_widgets = []    # Tracks QListWidget items
        self.scene_cameras = {}   # Tracks QGraphicsScene cameras (name -> item)
        self.scene_walls = []     # Tracks QGraphicsScene walls

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
        self.save_map_btn.clicked.connect(self.save_layout)
        self.load_map_btn.clicked.connect(self.load_layout)
    
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
                # Check if camera name already exists
                if name in self.scene_cameras:
                    print(f"Error: Camera name '{name}' already exists.")
                    # TODO: Show a QMessageBox to the user
                    return
                
                # --- 6. CALL THE NEW CENTRAL FUNCTION ---
                self.create_camera_items(name, url)
                print("Camera added.")
    
    def create_camera_items(self, name, url, pos=None, rot=None):
        """
        Creates and adds a camera to BOTH the list and the scene.
        'pos' and 'rot' are for loading saved layouts.
        """
        
        # 1. Create and add LIST item (CameraFeedWidget)
        print(f"Creating feed widget for {name}")
        feed_widget = CameraFeedWidget(name, url)
        self.feed_widgets.append(feed_widget) # Track for cleanup
        
        item = QListWidgetItem()
        item.setSizeHint(feed_widget.sizeHint())
        self.cam_list.addItem(item)
        self.cam_list.setItemWidget(item, feed_widget)

        # 2. Create and add SCENE item (CameraItem)
        print(f"Creating scene item for {name}")
        cam_item = CameraItem(name=name, url=url)
        
        # Apply saved position/rotation if they exist
        if pos:
            cam_item.setPos(pos)
        else:
            cam_item.setPos(30, 30) # Default new pos
            
        if rot is not None:
            cam_item.setRotation(rot)
            
        self.graphics_scene.addItem(cam_item)
        self.scene_cameras[name] = cam_item
        
    def save_layout(self):
        """
        Saves the current scene layout to a JSON file.
        """
        path, _ = QFileDialog.getSaveFileName(self, "Save Layout", "", "JSON Files (*.json)")
        if not path:
            return # User cancelled

        layout_data = {
            "cameras": [],
            "walls": []
        }

        # Save all cameras
        for name, cam_item in self.scene_cameras.items():
            pos = cam_item.scenePos()
            layout_data["cameras"].append({
                "name": cam_item.name,
                "url": cam_item.url,
                "pos": [pos.x(), pos.y()],
                "rot": cam_item.rotation()
            })

        # Save all walls
        walls = [item for item in self.drag_area.scene().items() if isinstance(item, WallItem)]
        for wall in walls:
            print("wall found")
            pos = wall.scenePos()
            rect = wall.rect()
            layout_data["walls"].append({
                "width": rect.width(),
                "height": rect.height(),
                "pos": [pos.x(), pos.y()],
                "rot": wall.rotation()
            })

        # Write to file
        try:
            with open(path, 'w') as f:
                json.dump(layout_data, f, indent=4)
            print(f"Layout saved to {path}")
        except Exception as e:
            print(f"Error saving layout: {e}") # TODO: Show a QMessageBox

    def load_layout(self):
        """
        Loads a scene layout from a JSON file.
        """
        path, _ = QFileDialog.getOpenFileName(self, "Load Layout", "", "JSON Files (*.json)")
        if not path:
            return # User cancelled

        try:
            with open(path, 'r') as f:
                layout_data = json.load(f)
        except Exception as e:
            print(f"Error loading layout: {e}") # TODO: Show a QMessageBox
            return

        # --- CRUCIAL: Clear everything first ---
        self.clear_all()

        # Load walls
        for wall_data in layout_data.get("walls", []):
            try:
                # We use 0,0 for x,y and let setPos handle the position
                wall = WallItem(0, 0, wall_data["width"], wall_data["height"])
                wall.setPos(QPointF(wall_data["pos"][0], wall_data["pos"][1]))
                wall.setRotation(wall_data["rot"])
                
                self.graphics_scene.addItem(wall)
                self.scene_walls.append(wall) # Re-track
            except Exception as e:
                print(f"Error loading a wall: {e}")

        # Load cameras
        for cam_data in layout_data.get("cameras", []):
            try:
                self.create_camera_items(
                    cam_data["name"],
                    cam_data["url"],
                    QPointF(cam_data["pos"][0], cam_data["pos"][1]),
                    cam_data["rot"]
                )
            except Exception as e:
                print(f"Error loading camera '{cam_data.get('name')}': {e}")
        
        print("Layout loaded successfully.")

    def clear_all(self):
        """
        Stops all feeds and clears the scene and list.
        """
        print("Clearing all items...")
        # 1. Stop all camera feed threads
        for widget in self.feed_widgets:
            widget.stop_feed()
        
        # 2. Clear all trackers
        self.feed_widgets.clear()
        self.scene_cameras.clear()
        self.scene_walls.clear()
        
        # 3. Clear the Qt widgets themselves
        self.cam_list.clear() # Clears the QListWidget
        self.graphics_scene.clear() # Clears the QGraphicsScene
                
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
