import json
import time
from PyQt6.QtWidgets import (QListWidgetItem,QFileDialog,QGraphicsScene,QApplication, QMainWindow, QLabel, QVBoxLayout,QLineEdit,QDialogButtonBox,QDialog, QGraphicsRectItem, QGraphicsEllipseItem, QMenu, QWidget, QGraphicsSimpleTextItem)
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


class PopOutWindow(QMainWindow):
    """
    A standalone window that hosts a page popped out from the main QStackedWidget.
    When closed, it returns the page back to the main stack.
    """
    def __init__(self, page_widget, page_index, page_title, dock_callback, parent=None):
        super().__init__(parent)
        self.page_widget = page_widget
        self.page_index = page_index
        self.dock_callback = dock_callback
        
        self.setWindowTitle(f"ObserveAI — {page_title}")
        self.setMinimumSize(600, 400)
        self.setStyleSheet("background-color: rgb(39, 7, 40); color: rgb(255, 255, 255);")
        
        # Reparent the page widget into this window
        self.setCentralWidget(page_widget)
        page_widget.show()
    
    def closeEvent(self, event):
        """When the pop-out window is closed, dock the page back into the main stack."""
        self.dock_callback(self.page_widget, self.page_index)
        super().closeEvent(event)


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
        
        # --- Pop-Out Window Management ---
        self.popout_windows = {}  # page_index -> PopOutWindow
        
        self.camera_workers ={}
        self.camera_threads = {}
        
        # --- AI MANAGEMENT ---
        self.ai_instances = {} # Stores the DetectionSystem objects
        self.ai_threads = {}   # Stores the Python Threads for AI
        
        # Adding the buffer dictionary for each 
        self.camera_buffers = {}
        self.FRAME_BUFFER_SIZE = 10 # Max frames to hold per camera
        
        self.maximized_widget = None # Tracks which widget is maximized, if any
        
        # --- Camera Calibration Mode ---
        self._calibration_camera: str = None    # Camera name being calibrated, or None
        self._calibration_points: list = []     # CalibrationPoint objects
        self._calibration_markers: list = []    # Visual markers on scene
        self._calibration_active = False
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
        self.pixels_per_meter = 30.0  # Default scale: 30 pixels = 1 meter (overwritten by map JSON)
        self.global_tracker = GlobalPersonTracker(
            feature_threshold=self.settings.get("feature_threshold"),
            reid_weight=self.settings.get("reid_weight"),
            spatial_weight=self.settings.get("spatial_weight"),
            position_callback=self._on_person_position_update,
            pixels_per_meter=self.pixels_per_meter
        )
        self.DEFAULT_FOV = self.settings.get("default_fov")  # Store for camera registration
        
        # 2. Tell your 'drag_area' (the QGraphicsView) to look at this new scene
        self.drag_area.setScene(self.graphics_scene)

        # 3. (Optional but recommended) Set a size for the scene
        self.graphics_scene.setSceneRect(0, 0, 1200, 1200)
        
        # 4. Add calibrated grid floor to the scene
        from components.GridFloor import GridFloor
        self.grid_floor = GridFloor(
            scene_width=1200, scene_height=1200,
            pixels_per_meter=self.pixels_per_meter
        )
        self.graphics_scene.addItem(self.grid_floor)
        
        
        self.signal_setup()
        
        # database setup
        self.setup_database_page()
        
        # Connect the AI Signal to the UI Slot
        self.ai_frame_processed_signal.connect(self.update_grid_from_ai)
        
        # Connect person position signal for floor map visualization
        self.person_position_signal.connect(self._update_person_dot)
        
        self.Content_stack.setCurrentIndex(0)
    
    def signal_setup(self):
        # --- Page navigation (left-click switches in main window) ---
        self.cam_set_btn.clicked.connect(lambda: self._switch_or_focus_page(0))
        self.cam_feed_btn.clicked.connect(lambda: self._switch_or_focus_page(1))       
        self.db_btn.clicked.connect(lambda: self._switch_or_focus_page(2))
        self.add_camera_btn.clicked.connect(self.add_camera)
        self.update_btn.clicked.connect(self.update_camera)
        self.add_wall_btn.clicked.connect(self.add_a_wall)
        self.save_map_btn.clicked.connect(self.save_layout)
        self.load_map_btn.clicked.connect(self.load_layout)
        self.db_btn.clicked.connect(self.show_database_page)
        self.logs_btn.clicked.connect(lambda: self._switch_or_focus_page(3))
        self.settings_btn.clicked.connect(self.show_settings_page)
        
        # --- Right-click context menus for pop-out ---
        self._page_info = {
            0: ("Camera Settings", self.cam_set_btn),
            1: ("Camera Feed", self.cam_feed_btn),
            2: ("Database", self.db_btn),
            3: ("Logs", self.logs_btn),
            4: ("Settings", self.settings_btn),
        }
        for page_idx, (title, btn) in self._page_info.items():
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, idx=page_idx, t=title, b=btn: self._show_popout_menu(pos, idx, t, b)
            )
        
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
        self._switch_or_focus_page(4)
    
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
        self._switch_or_focus_page(2)
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
            name, url, fov, view_range = dialog.get_details()
            if name and url:
                # Check if camera name already exists
                if name in self.scene_cameras:
                    print(f"Error: Camera name '{name}' already exists.")
                    # TODO: Show a QMessageBox to the user
                    return
                
                # --- 6. CALL THE NEW CENTRAL FUNCTION ---
                self.create_camera_items(name, url, fov=fov, view_range=view_range)
                print(f"Camera added: {name} (fov={fov}°, range={view_range})")
    
    def create_camera_items(self, name, url, pos=None, rot=None, fov=70.0, view_range=200.0):
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
        cam_item = CameraItem(name=name, url=url, view_angle=fov, view_range=view_range)
        cam_item.context_menu_callback = self._on_camera_context_menu
        
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
                fov=fov,
                view_range=view_range
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
            "pixels_per_meter": self.pixels_per_meter,
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
                "rot": cam_item.rotation(),
                "fov": cam_item.view_angle,
                "view_range": cam_item.view_range
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
        
        # Load scale factor
        self.pixels_per_meter = layout_data.get("pixels_per_meter", 30.0)
        if self.global_tracker:
            self.global_tracker.pixels_per_meter = self.pixels_per_meter
            print(f"[MAIN] Map scale set to {self.pixels_per_meter} pixels/meter")
        
        # Update grid floor with new scale
        if hasattr(self, 'grid_floor'):
            self.grid_floor.set_pixels_per_meter(self.pixels_per_meter)

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
                    cam_data["rot"],
                    fov=cam_data.get("fov", 70.0),
                    view_range=cam_data.get("view_range", 200.0)
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
        
        # Re-add grid floor (scene.clear() destroys all items)
        from components.GridFloor import GridFloor
        self.grid_floor = GridFloor(
            scene_width=1200, scene_height=1200,
            pixels_per_meter=self.pixels_per_meter
        )
        self.graphics_scene.addItem(self.grid_floor)
                
    # =========================================================================
    # Pop-Out Window Management
    # =========================================================================
    
    def _show_popout_menu(self, pos, page_index, page_title, button):
        """Show right-click context menu with pop-out option."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: rgb(60, 30, 65); color: white; border: 1px solid #555; }
            QMenu::item:selected { background-color: rgb(100, 50, 110); }
        """)
        
        if page_index in self.popout_windows:
            dock_action = menu.addAction("⬅ Dock Back")
            dock_action.triggered.connect(lambda: self._dock_page_back_by_index(page_index))
        else:
            popout_action = menu.addAction("⎗ Open in New Window")
            popout_action.triggered.connect(lambda: self._popout_page(page_index, page_title))
        
        menu.exec(button.mapToGlobal(pos))
    
    def _switch_or_focus_page(self, page_index):
        """
        Left-click behavior: if the page is popped out, bring that window to front.
        Otherwise, switch the stacked widget to it.
        """
        if page_index in self.popout_windows:
            win = self.popout_windows[page_index]
            win.raise_()
            win.activateWindow()
        else:
            self.Content_stack.setCurrentIndex(page_index)
    
    def _popout_page(self, page_index, page_title):
        """Pop a page out of the QStackedWidget into its own window."""
        if page_index in self.popout_windows:
            return  # Already popped out
        
        page_widget = self.Content_stack.widget(page_index)
        if page_widget is None:
            return
        
        # Create the pop-out window (this reparents the widget)
        win = PopOutWindow(
            page_widget=page_widget,
            page_index=page_index,
            page_title=page_title,
            dock_callback=self._dock_page_back,
            parent=None  # No parent = independent window
        )
        
        self.popout_windows[page_index] = win
        win.resize(800, 600)
        win.show()
        
        # Switch the main stack to the nearest available page
        for i in range(self.Content_stack.count()):
            if i not in self.popout_windows:
                self.Content_stack.setCurrentIndex(i)
                break
        
        print(f"[POP-OUT] '{page_title}' opened in new window")
    
    def _dock_page_back(self, page_widget, page_index):
        """Return a popped-out page back into the QStackedWidget."""
        if page_index in self.popout_windows:
            del self.popout_windows[page_index]
        
        # Re-insert the widget at the correct position
        self.Content_stack.insertWidget(page_index, page_widget)
        self.Content_stack.setCurrentIndex(page_index)
        
        page_title = self._page_info.get(page_index, ("Page",))[0]
        print(f"[POP-OUT] '{page_title}' docked back into main window")
    
    def _dock_page_back_by_index(self, page_index):
        """Dock back from context menu (closes the pop-out window)."""
        if page_index in self.popout_windows:
            self.popout_windows[page_index].close()
    
    def closeEvent(self, event):
        print("Window closing, stopping all threads...")
        self.is_running = False
        
        # Close all pop-out windows first
        for win in list(self.popout_windows.values()):
            win.dock_callback = lambda w, i: None  # Disable dock-back during shutdown
            win.close()
        self.popout_windows.clear()
        
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
    
    # =========================================================================
    # Camera Calibration System
    # =========================================================================
    
    def _start_calibration(self, camera_name: str):
        """
        Enter calibration mode for a specific camera.
        The user will click 2 reference points on the map.
        """
        if camera_name not in self.ai_instances:
            self._styled_msgbox("Calibration", 
                              f"Camera '{camera_name}' has no active AI system.\n"
                              "Start detection first, then calibrate.",
                              "warning")
            return
        
        self._calibration_camera = camera_name
        self._calibration_points = []
        self._calibration_markers = []
        self._calibration_active = True
        
        # Install event filter on graphics view to capture clicks
        self.drag_area.viewport().installEventFilter(self)
        
        self._styled_msgbox("Camera Calibration",
            f"Calibrating: {camera_name}\n\n"
            f"Step 1 of 2:\n"
            f"Have ONE person stand at a known spot visible in {camera_name}.\n"
            f"Then click that spot on the floor map.\n\n"
            f"Press Escape to cancel.")
        
        print(f"[CALIBRATION] Started for camera '{camera_name}'")
    
    def eventFilter(self, source, event):
        """Capture mouse clicks on the scene during calibration mode."""
        from PyQt6.QtCore import QEvent
        
        if (self._calibration_active and 
            source == self.drag_area.viewport() and
            event.type() == QEvent.Type.MouseButtonPress):
            
            from PyQt6.QtCore import Qt
            if event.button() == Qt.MouseButton.LeftButton:
                # Convert viewport click to scene coordinates
                scene_pos = self.drag_area.mapToScene(event.pos())
                self._on_calibration_click(scene_pos.x(), scene_pos.y())
                return True  # Consume the event
            elif event.button() == Qt.MouseButton.RightButton:
                # Right-click cancels calibration
                self._cancel_calibration()
                return True
        
        return super().eventFilter(source, event)
    
    def keyPressEvent(self, event):
        """Handle Escape key to cancel calibration."""
        from PyQt6.QtCore import Qt
        if event.key() == Qt.Key.Key_Escape and self._calibration_active:
            self._cancel_calibration()
            return
        super().keyPressEvent(event)
    
    def _on_calibration_click(self, world_x: float, world_y: float):
        """
        Handle a click on the map during calibration.
        Captures the world position AND the current person's frame position.
        """
        camera_name = self._calibration_camera
        
        # Read the current person's bounding box from DetectionSystem
        ai_sys = self.ai_instances.get(camera_name)
        if ai_sys is None:
            print(f"[CALIBRATION] No AI system for {camera_name}")
            return
        
        # Get tracked persons — need exactly 1 for calibration
        persons = list(ai_sys.tracked_persons.values())
        recent_persons = [p for p in persons if (time.time() - p.last_seen) < 1.0]
        
        if len(recent_persons) == 0:
            self._styled_msgbox("Calibration",
                "No person detected in camera!\n"
                "Make sure one person is visible and detected.",
                "warning")
            return
        
        if len(recent_persons) > 1:
            self._styled_msgbox("Calibration",
                f"{len(recent_persons)} people detected!\n"
                "Only ONE person should be visible during calibration.",
                "warning")
            return
        
        person = recent_persons[0]
        
        # Compute normalized frame position (0.0 = left edge, 1.0 = right edge)
        # Get frame width from GlobalPersonTracker's camera info
        frame_width = 1920  # Default fallback
        if self.global_tracker and camera_name in self.global_tracker.cameras:
            frame_width = self.global_tracker.cameras[camera_name].frame_width
        bbox_center_x = person.x + person.w / 2
        frame_x_normalized = bbox_center_x / frame_width
        
        # Create calibration point
        from components.CameraCalibrator import CalibrationPoint
        cal_point = CalibrationPoint(world_x, world_y, frame_x_normalized)
        self._calibration_points.append(cal_point)
        
        # Add visual marker on scene
        marker_color = QColor(0, 255, 100) if len(self._calibration_points) == 1 else QColor(100, 100, 255)
        marker = QGraphicsEllipseItem(-6, -6, 12, 12)
        marker.setBrush(QBrush(marker_color))
        marker.setPen(QPen(Qt.GlobalColor.white, 2))
        marker.setPos(world_x, world_y)
        marker.setZValue(500)
        marker.setToolTip(f"Cal Point {len(self._calibration_points)}\n"
                         f"Map: ({world_x:.1f}, {world_y:.1f})\n"
                         f"Frame: {frame_x_normalized:.3f}")
        self.graphics_scene.addItem(marker)
        self._calibration_markers.append(marker)
        
        # Add label
        label = QGraphicsSimpleTextItem(f"P{len(self._calibration_points)}")
        label.setBrush(QBrush(QColor(255, 255, 255)))
        label.setPos(world_x + 10, world_y - 10)
        label.setZValue(501)
        self.graphics_scene.addItem(label)
        self._calibration_markers.append(label)
        
        print(f"[CALIBRATION] Point {len(self._calibration_points)}: world=({world_x:.1f}, {world_y:.1f}), frame_x={frame_x_normalized:.3f}")
        
        if len(self._calibration_points) == 1:
            # First point captured — ask for second
            self._styled_msgbox("Camera Calibration",
                f"Point 1 captured! ✓\n\n"
                f"Step 2 of 2:\n"
                f"Move the person to a DIFFERENT spot.\n"
                f"Then click that spot on the floor map.")
        
        elif len(self._calibration_points) >= 2:
            # Both points captured — run calibration
            self._finish_calibration()
    
    def _finish_calibration(self):
        """
        Run the calibration solver and reposition the camera.
        """
        camera_name = self._calibration_camera
        cam_item = self.scene_cameras.get(camera_name)
        
        if cam_item is None:
            print(f"[CALIBRATION] Camera item not found: {camera_name}")
            self._cancel_calibration()
            return
        
        # Get current camera state
        current_pos = cam_item.scenePos()
        fov = cam_item.view_angle
        
        # Run solver
        from components.CameraCalibrator import solve_camera_position
        result = solve_camera_position(
            points=self._calibration_points,
            fov_degrees=fov,
            initial_guess=(current_pos.x(), current_pos.y()),
            search_radius=400.0
        )
        
        if result is None:
            self._styled_msgbox("Calibration Failed",
                "Could not compute camera position.\n"
                "Try using reference points that are further apart.",
                "warning")
            self._cancel_calibration()
            return
        
        new_x, new_y, new_rotation = result
        
        # Show result and ask for confirmation
        reply = self._styled_msgbox("Calibration Result",
            f"Calibration complete!\n\n"
            f"Old position: ({current_pos.x():.1f}, {current_pos.y():.1f}), rot={cam_item.rotation():.1f}°\n"
            f"New position: ({new_x:.1f}, {new_y:.1f}), rot={new_rotation:.1f}°\n\n"
            f"Apply these changes?",
            "question")
        
        from PyQt6.QtWidgets import QMessageBox
        if reply == QMessageBox.StandardButton.Yes:
            # Reposition camera item
            from PyQt6.QtCore import QPointF
            cam_item.setPos(QPointF(new_x, new_y))
            cam_item.setRotation(new_rotation)
            cam_item.rotation_degree = new_rotation
            cam_item.position = [new_x, new_y]
            
            # Update GlobalPersonTracker registration
            if self.global_tracker:
                self.global_tracker.register_camera(
                    name=camera_name,
                    position=(new_x, new_y),
                    rotation=new_rotation,
                    fov=fov,
                    view_range=cam_item.view_range
                )
            
            print(f"[CALIBRATION] Applied: camera '{camera_name}' → pos=({new_x:.1f}, {new_y:.1f}), rot={new_rotation:.1f}°")
        
        self._cleanup_calibration()
    
    def _cancel_calibration(self):
        """Cancel calibration mode."""
        print(f"[CALIBRATION] Cancelled")
        self._styled_msgbox("Calibration", "Calibration cancelled.")
        self._cleanup_calibration()
    
    def _cleanup_calibration(self):
        """Clean up calibration state and visual markers."""
        # Remove event filter
        self.drag_area.viewport().removeEventFilter(self)
        
        # Remove visual markers
        for marker in self._calibration_markers:
            self.graphics_scene.removeItem(marker)
        
        self._calibration_camera = None
        self._calibration_points = []
        self._calibration_markers = []
        self._calibration_active = False
    
    def _on_camera_context_menu(self, camera_name: str, global_pos):
        """
        Show context menu when right-clicking a camera item.
        """
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: rgb(40, 40, 55); color: white; border: 1px solid #555; }
            QMenu::item:selected { background-color: rgb(80, 80, 120); }
        """)
        
        calibrate_action = menu.addAction("📐 Calibrate Position")
        calibrate_action.triggered.connect(lambda: self._start_calibration(camera_name))
        
        menu.exec(global_pos)
    
    def _styled_msgbox(self, title: str, text: str, msg_type: str = "info"):
        """
        Create a QMessageBox styled to match the app's dark theme.
        
        Args:
            title: Window title
            text: Message body
            msg_type: 'info', 'warning', or 'question'
        
        Returns:
            QMessageBox.StandardButton (for 'question' type)
        """
        from PyQt6.QtWidgets import QMessageBox
        
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: rgb(39, 7, 40);
                color: rgb(255, 255, 255);
            }
            QMessageBox QLabel {
                color: rgb(255, 255, 255);
                font-size: 13px;
            }
            QPushButton {
                background-color: rgb(60, 30, 65);
                color: white;
                border: 1px solid rgb(100, 50, 110);
                padding: 6px 20px;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: rgb(100, 50, 110);
            }
            QPushButton:pressed {
                background-color: rgb(120, 60, 130);
            }
        """)
        
        if msg_type == "warning":
            msg.setIcon(QMessageBox.Icon.Warning)
        elif msg_type == "question":
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            return msg.exec()
        else:
            msg.setIcon(QMessageBox.Icon.Information)
        
        msg.exec()
