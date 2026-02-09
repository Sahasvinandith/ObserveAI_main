import json
from PyQt6.QtWidgets import (QListWidgetItem,QFileDialog,QGraphicsScene,QApplication, QMainWindow, QLabel, QVBoxLayout,QLineEdit,QDialogButtonBox,QDialog, QGraphicsRectItem, QGraphicsEllipseItem)
from PyQt6.QtCore import (QPointF,QThread,Qt, pyqtSignal,pyqtSlot)
from PyQt6.QtGui import QImage, QBrush, QPen, QColor
import threading
import cv2
from PyQt6.uic import loadUi
from components.Wall import WallItem
from components.AddCamera_Dialog import AddCameraDialog
from components.Camera_widget import CameraItem
from components.Camera_list_widget import CameraFeedWidget
from components.Grid_feed_widget import GridFeedWidget
from components.Camera_worker import CameraWorker
from components.Database_viewer import DatabaseViewer
import queue
from DataModel.DetectionSystem import Ai_System_thread


class MainWindow(QMainWindow):
    ai_frame_processed_signal = pyqtSignal(str,object)
    person_position_signal = pyqtSignal(int, float, float, str)  # global_id, x, y, camera_name
    def __init__(self):
        super().__init__()
        loadUi("./UIs/main.ui", self)
        
        self.graphics_scene = QGraphicsScene()
        
        # test parameters
        self.is_running = True
        
        #  ADD TRACKERS ---
        # These will keep track of all items for saving
        self.feed_widgets = {}    # Tracks QListWidget items
        self.scene_cameras:dict[str,CameraItem] = {}   # Tracks QGraphicsScene cameras (name -> item)
        self.scene_walls = []     # Tracks QGraphicsScene walls
        self.grid_feed_widgets = {} # name -> GridFeedWidget
        
        self.camera_workers ={}
        self.camera_threads = {}
        
        # --- AI MANAGEMENT ---
        self.ai_instances = {} # Stores the DetectionSystem objects
        self.ai_threads = {}   # Stores the Python Threads for AI
        
        # Adding the buffer dictionary for each 
        self.camera_buffers = {}
        self.FRAME_BUFFER_SIZE = 10 # Max frames to hold per camera
        
        self.maximized_widget = None # Tracks which widget is maximized, if any
        self.COLUMNS_IN_GRID = 3     # Set how many columns you want
        
        # --- Settings Manager ---
        from DataModel.SettingsManager import SettingsManager
        self.settings = SettingsManager()
        
        # --- Person Position Tracking on Floor Map ---
        self.person_dots: dict[int, QGraphicsEllipseItem] = {}  # global_id -> dot item
        self.DOT_RADIUS = self.settings.get("dot_radius")  # Radius of person indicator dots
        self.DOT_COLORS = [
            QColor(255, 100, 100),   # Red
            QColor(100, 255, 100),   # Green
            QColor(100, 100, 255),   # Blue
            QColor(255, 255, 100),   # Yellow
            QColor(255, 100, 255),   # Magenta
            QColor(100, 255, 255),   # Cyan
            QColor(255, 165, 0),     # Orange
            QColor(148, 0, 211),     # Violet
        ]
        
        # --- Global Person Tracking System ---
        from DataModel.GlobalPersonTracker import GlobalPersonTracker
        self.global_tracker = GlobalPersonTracker(
            feature_threshold=self.settings.get("feature_threshold"),
            reid_weight=self.settings.get("reid_weight"),
            spatial_weight=self.settings.get("spatial_weight"),
            position_callback=self._on_person_position_update
        )
        self.DEFAULT_FOV = self.settings.get("default_fov")  # Store for camera registration
        
        # 2. Tell your 'drag_area' (the QGraphicsView) to look at this new scene
        self.drag_area.setScene(self.graphics_scene)

        # 3. (Optional but recommended) Set a size for the scene
        self.graphics_scene.setSceneRect(0, 0, 1200, 1200)
        
        
        self.signal_setup()
        
        # database setup
        self.setup_database_page()
        
        # Connect the AI Signal to the UI Slot
        self.ai_frame_processed_signal.connect(self.update_grid_from_ai)
        
        # Connect person position signal for floor map visualization
        self.person_position_signal.connect(self._update_person_dot)
        
        self.Content_stack.setCurrentIndex(0)
    
    def signal_setup(self):
        self.cam_set_btn.clicked.connect(lambda: self.Content_stack.setCurrentIndex(0))
        self.cam_feed_btn.clicked.connect(lambda: self.Content_stack.setCurrentIndex(1))       
        self.db_btn.clicked.connect(lambda: self.Content_stack.setCurrentIndex(2))
        self.add_camera_btn.clicked.connect(self.add_camera)
        self.update_btn.clicked.connect(self.update_camera)
        self.add_wall_btn.clicked.connect(self.add_a_wall)
        self.save_map_btn.clicked.connect(self.save_layout)
        self.load_map_btn.clicked.connect(self.load_layout)
        self.db_btn.clicked.connect(self.show_database_page)
        self.logs_btn.clicked.connect(lambda: self.Content_stack.setCurrentIndex(3))
        self.settings_btn.clicked.connect(self.show_settings_page)
        
        # Setup settings page controls
        self.setup_settings_page()
    
    # =========================================================================
    # Floor Map Person Position Visualization
    # =========================================================================
    
    def _on_person_position_update(self, global_id: int, x: float, y: float, camera_name: str):
        """
        Callback from GlobalPersonTracker (called from AI thread).
        Emits signal to update UI safely on main thread.
        """
        try:
            self.person_position_signal.emit(global_id, x, y, camera_name)
        except Exception as e:
            print(f"[MAIN] Error emitting position signal: {e}")
    
    @pyqtSlot(int, float, float, str)
    def _update_person_dot(self, global_id: int, x: float, y: float, camera_name: str):
        """
        Updates or creates a person dot on the floor map.
        Called on the main thread via signal.
        """
        try:
            if global_id in self.person_dots:
                # Update existing dot position
                dot = self.person_dots[global_id]
                dot.setPos(x - self.DOT_RADIUS, y - self.DOT_RADIUS)
            else:
                # Create new dot
                color = self.DOT_COLORS[global_id % len(self.DOT_COLORS)]
                brush = QBrush(color)
                pen = QPen(Qt.GlobalColor.black)
                pen.setWidth(2)
                
                dot = QGraphicsEllipseItem(
                    0, 0, 
                    self.DOT_RADIUS * 2, 
                    self.DOT_RADIUS * 2
                )
                dot.setBrush(brush)
                dot.setPen(pen)
                dot.setPos(x - self.DOT_RADIUS, y - self.DOT_RADIUS)
                dot.setZValue(100)  # Draw on top of other items
                
                # Add tooltip with person info
                dot.setToolTip(f"Person G:{global_id}\nCamera: {camera_name}")
                
                self.graphics_scene.addItem(dot)
                self.person_dots[global_id] = dot
                print(f"[FLOOR MAP] Created dot for person {global_id} at ({x:.1f}, {y:.1f})")
        except Exception as e:
            print(f"[FLOOR MAP] Error updating dot: {e}")
    
    def _cleanup_stale_dots(self, active_global_ids: set):
        """Remove dots for persons no longer being tracked"""
        stale_ids = set(self.person_dots.keys()) - active_global_ids
        for gid in stale_ids:
            if gid in self.person_dots:
                dot = self.person_dots.pop(gid)
                self.graphics_scene.removeItem(dot)
                print(f"[FLOOR MAP] Removed stale dot for person {gid}")
    
    # =========================================================================
    # Settings Page
    # =========================================================================
    
    def setup_settings_page(self):
        """Initialize settings page with current values and connect signals."""
        # Load current settings into spinboxes
        self.threshold_spinbox.setValue(self.settings.get("feature_threshold"))
        self.reid_weight_spinbox.setValue(self.settings.get("reid_weight"))
        self.spatial_weight_spinbox.setValue(self.settings.get("spatial_weight"))
        self.fov_spinbox.setValue(self.settings.get("default_fov"))
        self.dot_radius_spinbox.setValue(self.settings.get("dot_radius"))
        self.min_quality_spinbox.setValue(self.settings.get("min_quality_threshold"))
        self.max_faces_spinbox.setValue(self.settings.get("max_faces_per_user"))
        # Identity verification settings
        self.identity_confirm_frames_spinbox.setValue(self.settings.get("identity_confirm_frames"))
        self.identity_confidence_spinbox.setValue(self.settings.get("identity_confidence_threshold"))
        self.identity_margin_spinbox.setValue(self.settings.get("identity_change_margin"))
        # Face validation settings
        self.min_face_width_spinbox.setValue(self.settings.get("min_face_width"))
        self.min_face_height_spinbox.setValue(self.settings.get("min_face_height"))
        self.min_face_confidence_spinbox.setValue(self.settings.get("min_face_confidence"))
        
        # Connect save and reset buttons
        self.save_settings_btn.clicked.connect(self._save_settings)
        self.reset_settings_btn.clicked.connect(self._reset_settings)
        
        # Connect spinboxes to apply settings in real-time (optional)
        self.threshold_spinbox.valueChanged.connect(self._on_threshold_changed)
        self.reid_weight_spinbox.valueChanged.connect(self._on_reid_weight_changed)
        self.spatial_weight_spinbox.valueChanged.connect(self._on_spatial_weight_changed)
        self.fov_spinbox.valueChanged.connect(self._on_fov_changed)
        self.dot_radius_spinbox.valueChanged.connect(self._on_dot_radius_changed)
    
    def show_settings_page(self):
        """Switch to settings page (index 4)"""
        self.Content_stack.setCurrentIndex(4)
    
    def _save_settings(self):
        """Save current spinbox values to settings file."""
        self.settings.set("feature_threshold", self.threshold_spinbox.value())
        self.settings.set("reid_weight", self.reid_weight_spinbox.value())
        self.settings.set("spatial_weight", self.spatial_weight_spinbox.value())
        self.settings.set("default_fov", self.fov_spinbox.value())
        self.settings.set("dot_radius", self.dot_radius_spinbox.value())
        self.settings.set("min_quality_threshold", self.min_quality_spinbox.value())
        self.settings.set("max_faces_per_user", self.max_faces_spinbox.value())
        # Identity verification settings
        self.settings.set("identity_confirm_frames", self.identity_confirm_frames_spinbox.value())
        self.settings.set("identity_confidence_threshold", self.identity_confidence_spinbox.value())
        self.settings.set("identity_change_margin", self.identity_margin_spinbox.value())
        # Face validation settings
        self.settings.set("min_face_width", self.min_face_width_spinbox.value())
        self.settings.set("min_face_height", self.min_face_height_spinbox.value())
        self.settings.set("min_face_confidence", self.min_face_confidence_spinbox.value())
        
        if self.settings.save():
            print("[SETTINGS] Settings saved successfully!")
        else:
            print("[SETTINGS] Failed to save settings!")
    
    def _reset_settings(self):
        """Reset all settings to defaults."""
        defaults = self.settings.reset_defaults()
        
        # Update spinboxes
        self.threshold_spinbox.setValue(defaults["feature_threshold"])
        self.reid_weight_spinbox.setValue(defaults["reid_weight"])
        self.spatial_weight_spinbox.setValue(defaults["spatial_weight"])
        self.fov_spinbox.setValue(defaults["default_fov"])
        self.dot_radius_spinbox.setValue(defaults["dot_radius"])
        self.min_quality_spinbox.setValue(defaults["min_quality_threshold"])
        self.max_faces_spinbox.setValue(defaults["max_faces_per_user"])
        # Identity verification settings
        self.identity_confirm_frames_spinbox.setValue(defaults["identity_confirm_frames"])
        self.identity_confidence_spinbox.setValue(defaults["identity_confidence_threshold"])
        self.identity_margin_spinbox.setValue(defaults["identity_change_margin"])
        # Face validation settings
        self.min_face_width_spinbox.setValue(defaults["min_face_width"])
        self.min_face_height_spinbox.setValue(defaults["min_face_height"])
        self.min_face_confidence_spinbox.setValue(defaults["min_face_confidence"])
        
        # Apply to tracker
        self.global_tracker.feature_threshold = defaults["feature_threshold"]
        self.global_tracker.reid_weight = defaults["reid_weight"]
        self.global_tracker.spatial_weight = defaults["spatial_weight"]
        self.DEFAULT_FOV = defaults["default_fov"]
        self.DOT_RADIUS = defaults["dot_radius"]
        
        print("[SETTINGS] Reset to defaults")
    
    def _on_threshold_changed(self, value):
        """Apply threshold change to tracker."""
        self.global_tracker.feature_threshold = value
        self.settings.set("feature_threshold", value)
    
    def _on_reid_weight_changed(self, value):
        """Apply Re-ID weight change to tracker."""
        self.global_tracker.reid_weight = value
        self.settings.set("reid_weight", value)
    
    def _on_spatial_weight_changed(self, value):
        """Apply spatial weight change to tracker."""
        self.global_tracker.spatial_weight = value
        self.settings.set("spatial_weight", value)
    
    def _on_fov_changed(self, value):
        """Store new default FOV."""
        self.DEFAULT_FOV = value
        self.settings.set("default_fov", value)
    
    def _on_dot_radius_changed(self, value):
        """Apply dot radius change."""
        self.DOT_RADIUS = value
        self.settings.set("dot_radius", value)
    
    def setup_database_page(self):
        """
        Injects the DatabaseViewer into the database_page widget.
        """
        # 1. Create the viewer instance
        self.db_viewer = DatabaseViewer(db_path="Faces_db")
        
        # 2. Add it to the existing database_page layout
        # Note: Your XML for database_page has 'horizontalLayout_3'
        # We can simply add the widget to it.
        
        # Clear any placeholder labels if you want (optional)
        # for i in range(self.database_page.layout().count()):
        #     self.database_page.layout().itemAt(i).widget().deleteLater()
        self.database_page.layout().addWidget(self.db_viewer)

    def show_database_page(self):
        """Switch to DB page and refresh data"""
        self.Content_stack.setCurrentIndex(2)
        if hasattr(self, 'db_viewer'):
            self.db_viewer.refresh_database()
    
    @pyqtSlot(str, object)
    def update_grid_from_ai(self, cam_name, frame):
        """
        Receives (Name, Frame) from DetectionSystem thread.
        Converts numpy array to QImage and updates the UI.
        """
        if cam_name in self.grid_feed_widgets:
            try:
                # 1. Get dimensions
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                
                # 2. Convert BGR (OpenCV) to RGB (Qt)
                # We create a copy to avoid memory issues when the numpy array is garbage collected
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # 3. Create QImage
                qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                
                # 4. Update the widget with the QImage
                self.grid_feed_widgets[cam_name].update_frame(qt_image)
                
            except Exception as e:
                print(f"Error converting AI frame: {e}")
                
    
    def add_a_wall(self):
        wall = WallItem(30,30,150,10)
        self.drag_area.scene().addItem(wall)
        
    def add_camera(self):
        """
        Called when the 'addCameraButton' is clicked.
        """
        
        self.show_add_camera_dialog()
        # self.start_buffer_test()
    
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
        --- 5. THIS IS THE NEW REFACTORED FUNCTION ---
        Creates and connects all objects for a new camera.
        Now includes spatial mapping for cross-camera tracking.
        """
        
        # --- 1. Create Data Objects ---
        frame_buffer = queue.Queue(maxsize=self.FRAME_BUFFER_SIZE)
        qt_thread = QThread()
        worker = CameraWorker(name, url, frame_buffer)
        
        worker.moveToThread(qt_thread)
        
        # --- 2. Create UI Widgets ---
        list_widget = CameraFeedWidget(name)
        grid_widget = GridFeedWidget(name)
        cam_item = CameraItem(name=name, url=url)
        
        # Set position and rotation
        if pos:
            cam_item.setPos(pos)
            cam_item.position = [pos.x(), pos.y()]
        else:
            cam_item.setPos(30, 30)
            cam_item.position = [30, 30]
        
        if rot is not None:
            cam_item.setRotation(rot)
            cam_item.rotation_degree = rot
        
        
        # --- 3. Pass Worker References to Widgets (for refresh capability) ---
        list_widget.worker = worker
        grid_widget.worker = worker
        
        # --- 4. Connect Worker Signals to UI Slots ---
        # When worker gets a frame, update BOTH widgets
        worker.frameReady.connect(list_widget.update_frame)
        
        # Connect error/success signals
        worker.connectionFailed.connect(list_widget.set_error_message)
        worker.connectionFailed.connect(grid_widget.set_error_message)
        worker.connectionSuccess.connect(list_widget.on_connection_success)
        worker.connectionSuccess.connect(grid_widget.on_connection_success)
        
        # Connect thread management
        qt_thread.started.connect(worker.run)
        worker.finished.connect(qt_thread.quit)
        worker.finished.connect(worker.deleteLater)
        qt_thread.finished.connect(qt_thread.deleteLater)


        # --- 5. Connect Grid Widget's Maximize Signal ---
        # Use lambda to pass the widget itself to the slot
        grid_widget.toggle_maximize.connect(
            lambda: self.handle_maximize_toggle(grid_widget)
        )

        # --- 6. Add Widgets to Layouts ---
        # Add to List (cam_list)
        item = QListWidgetItem()
        item.setSizeHint(list_widget.sizeHint())
        self.cam_list.addItem(item)
        self.cam_list.setItemWidget(item, list_widget)
        
        # Add to Scene (drag_area)
        self.graphics_scene.addItem(cam_item)
        
        # Add to Grid (feed_grid_layout)
        # This is how we add to the grid. We calculate the (row, col)
        # based on how many widgets are already there.
        count = len(self.grid_feed_widgets)
        row = count // self.COLUMNS_IN_GRID
        col = count % self.COLUMNS_IN_GRID
        # This is the `feed_grid_layout` you named in Qt Designer
        self.cam_feed_layout.addWidget(grid_widget, row, col)

        # --- 7. Store Objects in Trackers ---
        self.camera_buffers[name] = frame_buffer
        self.camera_threads[name] = qt_thread
        self.camera_workers[name] = worker
        self.feed_widgets[name] = list_widget
        self.grid_feed_widgets[name] = grid_widget
        self.scene_cameras[name] = cam_item

        # --- 8. Register Camera with Global Tracker for Spatial Awareness ---
        if self.global_tracker:
            cam_pos = cam_item.position if hasattr(cam_item, 'position') else [30, 30]
            cam_rot = cam_item.rotation_degree if hasattr(cam_item, 'rotation_degree') else 0.0
            self.global_tracker.register_camera(
                name=name,
                position=(cam_pos[0], cam_pos[1]),
                rotation=cam_rot if cam_rot is not None else 0.0,
                fov=self.DEFAULT_FOV  # Use configured default FOV
            )
            print(f"[MAIN] Registered camera '{name}' with global tracker")

        # --- 9. Start the Thread ---
        qt_thread.start()
        
        # =========================================================
        # --- 9. AUTO-START AI DETECTION SYSTEM ---
        # =========================================================
        print(f"Initializing AI System for Camera{name}...")
        
        # Create and Start the AI Thread
        ai_thread = threading.Thread(target=Ai_System_thread, args=(name, "Faces_db", frame_buffer, self.ai_frame_processed_signal.emit, 3, 15, self.global_tracker, self.ai_instances), daemon=True)
        self.ai_threads[name] = ai_thread
        ai_thread.start()
        
        print(f"AI System for {name} started.")
    
    def handle_maximize_toggle(self, widget_to_toggle: GridFeedWidget):
        """
        --- 6. NEW: Handles the maximize/minimize logic ---
        """
        if self.maximized_widget is None:
            # --- MAXIMIZING ---
            self.maximized_widget = widget_to_toggle
            self.maximized_widget.maximize_button.setText("v") # "Minimize"
            
            # Hide all *other* widgets in the grid
            for widget in self.grid_feed_widgets.values():
                if widget is not self.maximized_widget:
                    widget.hide()
            
            # Disable scrolling while maximized
            self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        else:
            # --- MINIMIZING ---
            self.maximized_widget.maximize_button.setText("□") # "Maximize"
            self.maximized_widget = None
            
            # Show all widgets
            for widget in self.grid_feed_widgets.values():
                widget.show()
                
            # Re-enable scrolling
            self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def update_camera(self):
        """Update camera positions and rotations"""
        for name, cam_item in self.scene_cameras.items():
            pos = cam_item.scenePos()
            cam_item.position = [pos.x(), pos.y()]
            cam_item.rotation_degree = cam_item.rotation()
            cam_item.print()


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
                print(f"Camera data: {cam_data}")
        
        print("Layout loaded successfully.")


    def clear_all(self):
        """
        Stops all workers AND AI threads.
        """
        print("Clearing all items...")
        
        # 1. Stop AI Threads first
        for name, ai_sys in self.ai_instances.items():
            ai_sys.stop()
        self.ai_instances.clear()
        self.ai_threads.clear()

        # 2. Stop Camera Workers
        for name, worker in self.camera_workers.items():
            worker.stop()
        for name, thread in self.camera_threads.items():
            thread.quit()
            if not thread.wait(1000):
                thread.terminate()
                
        # 3. Clear UI and Trackers
        self.feed_widgets.clear()
        self.scene_cameras.clear()
        self.scene_walls.clear()
        self.grid_feed_widgets.clear()
        self.camera_workers.clear()
        self.camera_threads.clear()
        
        # 4. Clear Person Dots from floor map
        self.person_dots.clear()
        
        while self.cam_feed_layout.count():
            child = self.cam_feed_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # 5. Clear Buffers
        for q in self.camera_buffers.values():
            while not q.empty():
                try: q.get_nowait()
                except queue.Empty: pass
        self.camera_buffers.clear()
        
        self.cam_list.clear()
        self.graphics_scene.clear()
                
    def closeEvent(self, event):
        print("Window closing, stopping all threads...")
        self.is_running = False
        self.clear_all()
        super().closeEvent(event)
    
    # --- Buffer Testing ---
        """
        Called when the 'test_buffer_btn' is clicked.
        Starts a new thread to display the buffer feed in a CV2 window.
        """
        # Get camera name from the QLineEdit
        # (Make sure your .ui file has a QLineEdit named 'test_buffer_name_input')
             
        cam_name = "cam1"

        if not cam_name:
            print("Please enter a camera name in the text box.")
            return

        if cam_name not in self.camera_buffers:
            print(f"Error: No buffer found with name '{cam_name}'.")
            return
            
        print(f"Starting buffer test thread for: {cam_name}")
        
        # Run the 'buffer_test_worker' in a new daemon thread.
        # 'daemon=True' means the thread will auto-close when the app exits.
        test_thread = threading.Thread(
            target=self.buffer_test_worker, 
            args=(cam_name,),
            daemon=True
        )
        test_thread.start()
        
    def buffer_test_worker(self, camera_name='cam1'):

        """
        This function runs in a separate thread.
        It pulls frames from the buffer and displays them using cv2.
        """
        try:
            buffer = self.camera_buffers[camera_name]
        except KeyError:
            print(f"[Thread {camera_name}] Buffer does not exist.")
            return

        window_name = f"Buffer Feed: {camera_name} (Press 'q' to close)"

        while self.is_running:
            try:
                # Wait up to 1 second for a new frame
                frame = buffer.get(timeout=1.0)
                
                # We got a frame, display it
                cv2.imshow(window_name, frame)

            except queue.Empty:
                # No frame in 1 second, just loop again
                print(f"[{camera_name} buffer] No new frame...")
                pass # Just continue the loop
            except Exception as e:
                print(f"Error in buffer test thread: {e}")
                break

            # Check for 'q' key to quit *this window*
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        # --- Cleanup ---
        print(f"Closing CV2 test window for {camera_name}.")
        try:
            cv2.destroyWindow(window_name)
        except:
            pass # Window might already be closed
    

