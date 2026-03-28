import os
import json
import time
from PyQt6.QtCore import (QPointF, QThread, Qt, pyqtSignal, pyqtSlot, QPropertyAnimation, QPoint, QRect, QEasingCurve, QTimer, QDateTime, QDate, QTime)
from datetime import datetime
from PyQt6.QtGui import QImage, QBrush, QPen, QColor, QPixmap
from PyQt6.QtWidgets import (QListWidgetItem, QFileDialog, QGraphicsScene, QApplication, QMainWindow, QLabel, QVBoxLayout, QLineEdit, QDialogButtonBox, QDialog, QGraphicsRectItem, QGraphicsEllipseItem, QMenu, QWidget, QGraphicsSimpleTextItem, QInputDialog, QMessageBox, QHBoxLayout, QListWidget, QGraphicsOpacityEffect, QDateTimeEdit, QTextBrowser)
import threading
import cv2
from PyQt6.uic import loadUi
from components.Wall import WallItem
from components.AddCamera_Dialog import AddCameraDialog, detect_local_cameras
from components.Camera_widget import CameraItem
from components.Camera_list_widget import CameraFeedWidget
from components.Grid_feed_widget import GridFeedWidget
from components.Camera_worker import CameraWorker
from components.Database_viewer import DatabaseViewer
from components.BirdsEyeViewWidget import BirdsEyeViewWidget
from components.CameraActionManagerDialog import CameraActionManagerDialog
import queue
from DataModel.DetectionSystem import Ai_System_thread
from DataModel.LogManager import get_log_manager


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
        # Inherits global style from StyleHelper
        
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
    action_detected_signal = pyqtSignal(str, str, str, float)    # camera, person, action, timestamp
    def __init__(self):
        super().__init__()
        loadUi("./UIs/main.ui", self)
        
        self.graphics_scene = QGraphicsScene()
        
        # test parameters
        self.is_running = True
        self.camera_setup_done = False
        
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
        
        # --- Action Manager ---
        from DataModel.ActionManager import ActionManager
        self.action_manager = ActionManager()
        
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
            color_weight=self.settings.get("color_weight", 0.3),
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
        
        # --- Birds Eye View Setup ---
        self.birds_eye_widget = BirdsEyeViewWidget(self)
        self.birds_eye_view_page.layout().addWidget(self.birds_eye_widget)
        
        # Initial configure button states
        self.add_camera_btn.hide()
        self.add_wall_btn.hide()
        self.done_setup_btn.hide()
        self.configure_cameras_btn.show()

        self.signal_setup()
        
        # database setup
        self.setup_database_page()
        
        # Connect the AI Signal to the UI Slot
        self.ai_frame_processed_signal.connect(self.update_grid_from_ai)
        
        # Connect person position signal for floor map visualization
        self.person_position_signal.connect(self._update_person_dot)
        
        # Connect action detection signal to log panel
        self.action_detected_signal.connect(self._on_action_detected)
        
        # --- Logs Page Setup ---
        self.log_manager = get_log_manager()
        self.setup_logs_page()

        # --- Actions UI Initialization (Always ready) ---
        self._setup_actions_log_panel()
        self._actions_page_initialized = True
        
        self.Content_stack.setCurrentIndex(0)
    
    def signal_setup(self):
        # --- Page navigation (left-click switches in main window) ---
        self.cam_set_btn.clicked.connect(lambda: self._switch_or_focus_page(0))
        self.cam_feed_btn.clicked.connect(lambda: self._switch_or_focus_page(1))       
        self.db_btn.clicked.connect(lambda: self._switch_or_focus_page(2))
        self.configure_cameras_btn.clicked.connect(self.start_camera_setup)
        self.done_setup_btn.clicked.connect(self.finish_camera_setup)
        self.add_camera_btn.clicked.connect(self.add_camera)
        self.update_btn.clicked.connect(self.update_camera)
        self.add_wall_btn.clicked.connect(self.add_a_wall)
        self.save_map_btn.clicked.connect(self.save_layout)
        self.load_map_btn.clicked.connect(self.load_layout)
        self.db_btn.clicked.connect(self.show_database_page)
        self.logs_btn.clicked.connect(lambda: self._switch_or_focus_page(3))
        self.birds_eye_btn.clicked.connect(self.show_birds_eye_view)
        self.settings_btn.clicked.connect(self.show_settings_page)
        
        # --- Actions UI ---
        self.actions_btn.clicked.connect(self.show_actions_page)
        self.create_action_btn.clicked.connect(self.create_action)
        self.delete_action_btn.clicked.connect(self.delete_action)
        self.manage_camera_actions_btn.clicked.connect(self.manage_camera_actions)
        
        # --- Right-click context menus for pop-out ---
        self._page_info = {
            0: ("Camera Settings", self.cam_set_btn),
            1: ("Camera Feed", self.cam_feed_btn),
            2: ("Database", self.db_btn),
            3: ("Logs", self.logs_btn),
            4: ("Settings", self.settings_btn),
            5: ("Birds Eye View", self.birds_eye_btn),
            6: ("Actions", self.actions_btn),
        }
        for page_idx, (title, btn) in self._page_info.items():
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, idx=page_idx, t=title, b=btn: self._show_popout_menu(pos, idx, t, b)
            )
        
        # Setup settings page controls
        self.setup_settings_page()
    def start_camera_setup(self):
        """Show configuration buttons and hide 'Configure Cameras'."""
        self.configure_cameras_btn.hide()
        self.add_camera_btn.show()
        self.add_wall_btn.show()
        self.done_setup_btn.show()

    def finish_camera_setup(self):
        """Hide configuration buttons and start AI threads."""
        self.camera_setup_done = True
        self.add_camera_btn.hide()
        self.add_wall_btn.hide()
        self.done_setup_btn.hide()
        self.configure_cameras_btn.show()
        
        # Start AI for all cameras that haven't started yet
        for name, frame_buffer in self.camera_buffers.items():
            if name not in self.ai_threads:
                self._start_ai_for_camera(name, frame_buffer)

    def _start_ai_for_camera(self, name, frame_buffer):
        """Helper to start the AI tracking thread for a camera."""
        print(f"Initializing AI System for Camera {name}...")
        ai_thread = threading.Thread(
            target=Ai_System_thread, 
            args=(name, "Faces_db", frame_buffer, self.ai_frame_processed_signal.emit, 3, 15, self.global_tracker, self.ai_instances), 
            kwargs={"action_callback": self.action_detected_signal.emit},
            daemon=True
        )
        self.ai_threads[name] = ai_thread
        ai_thread.start()
        print(f"AI System for {name} started.")
        
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
            
            # Note: BirdsEyeViewWidget has its own timer for updates (every 100ms)
            # So we don't need to manually call update_visualization() here
            # This avoids potential recursion issues
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
        self.db_viewer = DatabaseViewer(db_path="Faces_db", tracker=self.global_tracker)

        
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
    
    def show_birds_eye_view(self):
        """Switch to Birds Eye View page and initialize data sources"""
        self._switch_or_focus_page(5)  # Birds Eye View is at index 5 (after Settings at 4)
        if hasattr(self, 'birds_eye_widget'):
            # Set data sources if not already set
            if self.birds_eye_widget.global_tracker is None:
                self.birds_eye_widget.set_data_sources(
                    self.global_tracker,
                    self.scene_cameras
                )
            # Force update
            self.birds_eye_widget.update_visualization()
    
    def show_actions_page(self):
        """Switch to Actions page and update the list"""
        self._switch_or_focus_page(6)
        self.update_actions_list()

    def _setup_actions_log_panel(self):
        """Inject the Recent Detections log widget into the Actions page."""
        from PyQt6.QtWidgets import QListWidget, QLabel, QVBoxLayout
        # Find the actions page layout (it should already exist from .ui)
        page = self.Content_stack.widget(6)  # Actions page index
        layout = page.layout()
        if layout is None:
            layout = QVBoxLayout(page)

        sep = QLabel("Recent Detections:")
        sep.setStyleSheet("color: #ccc; font-weight: bold; font-size: 11pt; margin-top: 8px;")
        layout.addWidget(sep)

        # Horizontal layout for Log + Preview
        h_layout = QHBoxLayout()
        h_layout.setSpacing(10)
        
        self.action_log_list = QListWidget()
        self.action_log_list.setStyleSheet(
            "background-color: rgb(30, 10, 35); color: #00ff88; "
            "border: 1px solid #7a3a8a; border-radius: 4px; font-size: 10pt;"
        )
        self.action_log_list.setMaximumHeight(250)
        self.action_log_list.currentItemChanged.connect(self._on_action_log_selection_changed)
        h_layout.addWidget(self.action_log_list, stretch=2)

        # Preview Label
        self.action_preview_label = QLabel("Select an action to view frame")
        self.action_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.action_preview_label.setStyleSheet(
            "background-color: rgb(20, 5, 25); color: #888; "
            "border: 1px solid #7a3a8a; border-radius: 4px;"
        )
        self.action_preview_label.setFixedSize(320, 240) # Fixed size for preview
        h_layout.addWidget(self.action_preview_label, stretch=3)
        
        layout.addLayout(h_layout)

    def _on_action_log_selection_changed(self, current, previous):
        """Update the preview label when an action log entry is selected."""
        if current is None:
            self.action_preview_label.clear()
            self.action_preview_label.setText("Select an action to view frame")
            return
            
        img_path = current.data(Qt.ItemDataRole.UserRole)
        if img_path and os.path.exists(img_path):
            pixmap = QPixmap(img_path)
            # Scale to fit while maintaining aspect ratio
            scaled = pixmap.scaled(self.action_preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.action_preview_label.setPixmap(scaled)
        else:
            self.action_preview_label.clear()
            self.action_preview_label.setText("No evidence frame available")

    @pyqtSlot(str, str, str, float)
    def _on_action_detected(self, camera: str, person: str, action: str, timestamp: float):
        """Receives an action detection event from the AI thread and logs it with evidence."""
        import datetime
        ts_str = datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
        entry = f"[{camera}]  {person}  →  {action}  at {ts_str}"
        
        # 1. Capture and Save Evidence Frame
        image_path = None
        if camera in self.camera_workers:
            worker = self.camera_workers[camera]
            if hasattr(worker, 'latest_frame') and worker.latest_frame is not None:
                # Save as JPG in detections/ folder
                os.makedirs("detections", exist_ok=True)
                filename = f"act_{int(timestamp)}_{camera.replace(' ','_')}.jpg"
                save_path = os.path.join("detections", filename)
                try:
                    import cv2
                    cv2.imwrite(save_path, worker.latest_frame)
                    image_path = os.path.abspath(save_path)
                except Exception as e:
                    print(f"[ACTION LOG] Failed to save evidence frame: {e}")

        # 2. Add to Log List
        if hasattr(self, 'action_log_list'):
            item = QListWidgetItem(entry)
            if image_path:
                item.setData(Qt.ItemDataRole.UserRole, image_path)
            self.action_log_list.insertItem(0, item)
            # Cap at 100 entries to avoid memory growth
            while self.action_log_list.count() > 100:
                self.action_log_list.takeItem(self.action_log_list.count() - 1)
        
        # 3. Toast Notification
        self._show_notification(f"<b>{action}</b> detected on <i>{camera}</i>")
        
        # 4. Immediate Logs Page Refresh
        self.log_manager.add_log(
            log_type='action', 
            person_name=person, 
            cameras=[camera], 
            action=action, 
            message=f"{action} detected on {camera}",
            evidence_path=image_path
        )
        
        if self.Content_stack.currentIndex() == 3:
            self.search_logs()
        
        print(f"[ACTION LOG] {entry}")

    def _show_notification(self, message: str):
        """Show an animated toast notification in the top-right corner."""
        notification = QLabel(message, self)
        # High-end neon styling
        notification.setStyleSheet("""
            background-color: rgba(30, 10, 35, 230);
            color: #00ff88;
            border: 2px solid #7a3a8a;
            border-radius: 10px;
            padding: 12px 20px;
            font-size: 11pt;
        """)
        notification.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        notification.adjustSize()
        
        # Position at top-right
        margin = 20
        x = self.width() - notification.width() - margin
        y = margin
        notification.move(x, y)
        
        # Animation: Fade in and out
        effect = QGraphicsOpacityEffect(notification)
        notification.setGraphicsEffect(effect)
        
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(500)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        
        notification.show()
        anim.start()
        
        # Keep reference to avoid GC
        if not hasattr(self, '_active_notifications'):
            self._active_notifications = []
        self._active_notifications.append((notification, anim))
        
        # Fade out after 3 seconds
        def fade_out():
            self._out_anim = QPropertyAnimation(effect, b"opacity")
            self._out_anim.setDuration(800)
            self._out_anim.setStartValue(1.0)
            self._out_anim.setEndValue(0.0)
            self._out_anim.finished.connect(notification.deleteLater)
            self._out_anim.start()
            # Remove from tracking list
            if (notification, anim) in self._active_notifications:
                self._active_notifications.remove((notification, anim))
                
        QTimer.singleShot(3000, fade_out)

    def manage_camera_actions(self):
        """Open the Camera Action Manager dialog."""
        if not self.scene_cameras:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Cameras", "Add at least one camera first.")
            return
        dlg = CameraActionManagerDialog(
            camera_names=list(self.scene_cameras.keys()),
            ai_instances=self.ai_instances,
            parent=self
        )
        dlg.exec()
        # Refresh the actions list in case names changed
        self.update_actions_list()

    def update_actions_list(self):
        self.actions_list.clear()
        actions = self.action_manager.get_action_list()
        for act in actions:
            self.actions_list.addItem(act)

    def create_action(self):
        action_name, ok1 = QInputDialog.getText(self, "Create Action", "Enter Action Name:")
        if not ok1 or not action_name.strip():
            return
            
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Pose Data File", "", "JSON Files (*.json)")
        if not file_path:
            return
            
        try:
            with open(file_path, 'r') as f:
                import json
                pose_data = json.load(f)
            self.action_manager.save_action(action_name.strip(), pose_data)
            self.update_actions_list()
            QMessageBox.information(self, "Success", f"Action '{action_name}' created successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load pose data: {e}")

    def delete_action(self):
        selected_items = self.actions_list.selectedItems()
        if not selected_items:
            return
        action_name = selected_items[0].text()
        if self.action_manager.delete_action(action_name):
            self.update_actions_list()

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
            name, url, fov, view_range, selected_actions = dialog.get_details()
            if name and url:
                # Check if camera name already exists
                if name in self.scene_cameras:
                    print(f"Error: Camera name '{name}' already exists.")
                    # TODO: Show a QMessageBox to the user
                    return
                
                # Update camera actions in settings
                cam_actions = self.settings.get("camera_actions")
                if not cam_actions:
                    cam_actions = {}
                cam_actions[name] = selected_actions
                self.settings.set("camera_actions", cam_actions)
                self.settings.save()
                
                # --- 6. CALL THE NEW CENTRAL FUNCTION ---
                self.create_camera_items(name, url, fov=fov, view_range=view_range)
                print(f"Camera added: {name} (fov={fov}°, range={view_range}, actions={selected_actions})")
    
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
        grid_widget.configure_clicked.connect(self._on_configure_camera_clicked)
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
        # --- 9. CONDITIONAL START AI DETECTION SYSTEM ---
        # =========================================================
        if self.camera_setup_done:
            self._start_ai_for_camera(name, frame_buffer)
        else:
            print(f"AI System for {name} queued until camera setup is done.")
    
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
        detected_cams = None # Lazy-load if needed
        
        for cam_data in layout_data.get("cameras", []):
            try:
                name = cam_data["name"]
                url = cam_data["url"]
                
                # --- Robust Camera Re-detection for Local Devices ---
                if isinstance(url, str) and url.startswith("/dev/video"):
                    if not os.path.exists(url):
                        print(f"[MAIN] Camera '{name}' saved at {url} not found. Attempting re-detection...")
                        if detected_cams is None:
                            detected_cams = detect_local_cameras()
                        
                        # Fallback 1: Match by name
                        match = next((c for c in detected_cams if c['name'] == name), None)
                        if match:
                            url = match['device']
                            print(f"[MAIN] Camera '{name}' re-detected at {url}")
                        else:
                            # Fallback 2: Manual selection
                            choices = [f"{c['name']} ({c['device']})" for c in detected_cams]
                            if choices:
                                from PyQt6.QtWidgets import QInputDialog
                                item, ok = QInputDialog.getItem(
                                    self, "Camera Not Found", 
                                    f"Could not find '{name}' at {url}.\nPlease select the camera from the list:",
                                    choices, 0, False
                                )
                                if ok and item:
                                    # Extract device path from "Name (/dev/videoX)"
                                    url = item.split("(")[-1].rstrip(")")
                                    print(f"[MAIN] Camera '{name}' manually rebound to {url}")
                
                self.create_camera_items(
                    name,
                    url,
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
        # Inherits global style from StyleHelper
        
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
        
        # Log exits for all active persons before shutting down
        if hasattr(self, 'global_tracker'):
            self.global_tracker.shutdown()
            
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
        if camera_name not in self.camera_workers:
            self._styled_msgbox("Calibration", 
                              f"Camera '{camera_name}' is not running.\n"
                              "Please make sure the video feed is working.",
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
            f"1. Click a known spot on the floor map.\n"
            f"2. A window will pop up with the camera feed.\n"
            f"3. Click the exact SAME spot on the camera image.\n"
            f"4. Repeat for at least 2 different spots.\n\n"
            f"When you have enough points, RIGHT-CLICK the map or press ESCAPE to finish and compute the position.")
        
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
                # Right-click finishes calibration if we have 2+ points, otherwise cancels
                if len(self._calibration_points) >= 2:
                    self._finish_calibration()
                else:
                    self._cancel_calibration()
                return True
        
        return super().eventFilter(source, event)
    
    def keyPressEvent(self, event):
        """Handle Escape key to cancel/finish calibration."""
        from PyQt6.QtCore import Qt
        if event.key() == Qt.Key.Key_Escape and self._calibration_active:
            if len(self._calibration_points) >= 2:
                self._finish_calibration()
            else:
                self._cancel_calibration()
            return
        super().keyPressEvent(event)
    
    def _on_calibration_click(self, world_x: float, world_y: float):
        """
        Handle a click on the map during calibration.
        Opens a dialog to capture the corresponding frame position.
        """
        camera_name = self._calibration_camera
        
        # Get the latest frame directly from the camera worker
        worker = self.camera_workers.get(camera_name)
        if worker is None or not hasattr(worker, 'latest_frame'):
            self._styled_msgbox("Calibration",
                f"No video feed available for {camera_name}.\n"
                "Please wait for the feed to load.", "warning")
            return
            
        frame = worker.latest_frame
        if frame is None:
            QMessageBox.warning(self, "Calibration", "Failed to grab frame from video feed.")
            return
            
        # Open the image click dialog
        from components.ImageClickDialog import ImageClickDialog
        dlg = ImageClickDialog(frame, camera_name, self)
        
        if dlg.exec() and dlg.normalized_x is not None:
            frame_x_normalized = dlg.normalized_x
            frame_y_normalized = dlg.normalized_y if dlg.normalized_y is not None else 0.5  # Default to middle
        else:
            return  # Cancelled clicking for this point
        
        # Create calibration point with Y coordinate for enhanced accuracy
        from components.CameraCalibrator import CalibrationPoint
        cal_point = CalibrationPoint(world_x, world_y, frame_x_normalized, frame_y_normalized)
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
                         f"Frame: ({frame_x_normalized:.3f}, {frame_y_normalized:.3f})")
        self.graphics_scene.addItem(marker)
        self._calibration_markers.append(marker)
        
        # Add label
        label = QGraphicsSimpleTextItem(f"P{len(self._calibration_points)}")
        label.setBrush(QBrush(QColor(255, 255, 255)))
        label.setPos(world_x + 10, world_y - 10)
        label.setZValue(501)
        self.graphics_scene.addItem(label)
        self._calibration_markers.append(label)
        
        print(f"[CALIBRATION] Point {len(self._calibration_points)}: world=({world_x:.1f}, {world_y:.1f}), "
              f"frame=({frame_x_normalized:.3f}, {frame_y_normalized:.3f})")
        
        # Since we support infinite points, we don't automatically trigger finish.
        # But we hint the user after 2 points.
        if len(self._calibration_points) == 2:
            self._styled_msgbox("Camera Calibration",
                f"2 points captured! The position can now be computed.\n\n"
                f"You can keep adding more points to increase accuracy and detect FOV/range, \n"
                f"or RIGHT-CLICK anywhere on the grid (or press ESCAPE) to finish calibration.\n\n"
                f"TIP: 3+ points enables automatic FOV detection!")
    
    def _finish_calibration(self):
        """
        Run the enhanced calibration solver with FOV and view_range detection.
        """
        camera_name = self._calibration_camera
        cam_item = self.scene_cameras.get(camera_name)
        if cam_item is None:
            print(f"[CALIBRATION] Camera item not found: {camera_name}")
            self._cancel_calibration()
            return
        
        # Get current camera state
        current_pos = cam_item.scenePos()
        current_fov = cam_item.view_angle
        current_range = cam_item.view_range
        
        # Decide whether to detect FOV and view_range based on point count
        detect_fov = len(self._calibration_points) >= 3
        detect_range = len(self._calibration_points) >= 3
        
        print(f"[CALIBRATION] Running solver with {len(self._calibration_points)} points "
              f"(detect_fov={detect_fov}, detect_range={detect_range})...")
        
        # Run enhanced solver
        from components.CameraCalibrator import solve_camera_position
        result = solve_camera_position(
            points=self._calibration_points,
            fov_degrees=current_fov,
            initial_guess=(current_pos.x(), current_pos.y()),
            search_radius=400.0,
            detect_fov=detect_fov,
            detect_view_range=detect_range,
            lock_position=True  # Strictly enforce map origin placement
        )
        
        if result is None:
            self._styled_msgbox("Calibration Failed",
                "Could not compute camera position.\n"
                "Try using reference points that are further apart.",
                "warning")
            self._cancel_calibration()
            return
        
        # Unpack enhanced result (now includes FOV and view_range)
        new_x, new_y, new_rotation, detected_fov, detected_range = result
        
        # Build informative result message
        fov_changed = abs(detected_fov - current_fov) > 0.1
        range_changed = abs(detected_range - current_range) > 1.0
        
        result_text = f"Calibration complete!\n\n"
        result_text += f"Old position: ({current_pos.x():.1f}, {current_pos.y():.1f}), rot={cam_item.rotation():.1f}°\n"
        result_text += f"New position: ({new_x:.1f}, {new_y:.1f}), rot={new_rotation:.1f}°\n\n"
        
        if detect_fov:
            result_text += f"Old FOV: {current_fov:.1f}°\n"
            result_text += f"Detected FOV: {detected_fov:.1f}° {'⚠️ CHANGED' if fov_changed else '✓ Confirmed'}\n\n"
        
        if detect_range:
            result_text += f"Old view range: {current_range:.1f} px\n"
            result_text += f"Detected range: {detected_range:.1f} px {'⚠️ CHANGED' if range_changed else '✓ Confirmed'}\n\n"
        
        result_text += f"Apply these changes?"
        
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, "Calibration Result", result_text, 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # Reposition camera item
            from PyQt6.QtCore import QPointF
            cam_item.setPos(QPointF(new_x, new_y))
            cam_item.setRotation(new_rotation)
            cam_item.rotation_degree = new_rotation
            cam_item.position = [new_x, new_y]
            
            # Update FOV and view_range if detected
            if detect_fov:
                cam_item.view_angle = detected_fov
                print(f"[CALIBRATION] FOV updated: {current_fov:.1f}° → {detected_fov:.1f}°")
            
            if detect_range:
                cam_item.view_range = detected_range
                print(f"[CALIBRATION] View range updated: {current_range:.1f} → {detected_range:.1f}px")
            
            # Update GlobalPersonTracker registration with new parameters
            if self.global_tracker:
                # Get frame dimensions for bbox normalization
                frame_width = 1920
                frame_height = 1080
                worker = self.camera_workers.get(camera_name)
                if worker and hasattr(worker, 'latest_frame') and worker.latest_frame is not None:
                    frame_height, frame_width = worker.latest_frame.shape[:2]

                self.global_tracker.register_camera(
                    name=camera_name,
                    position=(new_x, new_y),
                    rotation=new_rotation,
                    fov=detected_fov,
                    view_range=detected_range,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    calibration_points=self._calibration_points
                )
            
            print(f"[CALIBRATION] ✓ Applied all parameters to camera '{camera_name}'")
        
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
        # Inherits global style from StyleHelper
        
        calibrate_action = menu.addAction("📐 Calibrate Position")
        calibrate_action.triggered.connect(lambda: self._start_calibration(camera_name))
        
        config_action = menu.addAction("⚙ Configure Feed")
        config_action.triggered.connect(lambda: self._on_configure_camera_clicked(camera_name))
        
        menu.exec(global_pos)
        
    def _on_configure_camera_clicked(self, camera_name: str):
        """
        Open the configuration dialog for an existing camera and apply changes.
        """
        if camera_name not in self.scene_cameras:
            return
            
        cam_item = self.scene_cameras[camera_name]
        worker = self.camera_workers.get(camera_name)
        
        # Get current actions for this camera
        current_actions = []
        if camera_name in self.ai_instances:
            current_actions = list(self.ai_instances[camera_name].actions.keys())
            
        # Prepare current info
        camera_info = {
            "name": camera_name,
            "url": worker.url if worker else "",
            "fov": cam_item.view_angle,
            "range": cam_item.view_range,
            "actions": current_actions
        }
        
        from components.AddCamera_Dialog import AddCameraDialog
        dialog = AddCameraDialog(self, camera_info=camera_info)
        
        if dialog.exec():
            new_name, new_url, new_fov, new_range, selected_actions = dialog.get_details()
            
            # 1. Update FOV and Range (Visual and Tracking)
            cam_item.view_angle = new_fov
            cam_item.view_range = new_range
            cam_item.update() # Refresh the cone in the map
            
            if self.global_tracker:
                self.global_tracker.update_camera_params(camera_name, fov=new_fov, range_val=new_range)
            
            # 2. Update Actions
            if camera_name in self.ai_instances:
                ai_system = self.ai_instances[camera_name]
                # Sync actions with selected ones
                ai_system.set_actions(selected_actions)
                print(f"[{camera_name}] Actions updated: {selected_actions}")
            
            # 3. Update URL (Source)
            if worker and worker.url != new_url:
                print(f"[{camera_name}] URL changed to {new_url}. Restarting worker...")
                worker.url = new_url
                cam_item.url = new_url
                worker.restart()
            
            # 4. Handle Name Change (If different)
            if new_name != camera_name:
                # This would require updating all dict keys. 
                # For now, we'll suggest adding a new camera or inform the user.
                # But since the user might expect it, let's at least update the UI label.
                # Handling full rename is complex, let's keep name read-only in dialog if possible.
                print(f"[MAIN] Note: Camera renaming at runtime is not fully supported yet.")
                
            print(f"[{camera_name}] Configuration updated successfully.")

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
        # Inherits global style from StyleHelper
        
        if msg_type == "warning" or msg_type == "critical":
            msg.setIcon(QMessageBox.Icon.Warning)
        elif msg_type == "question":
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            return msg.exec()
        else:
            msg.setIcon(QMessageBox.Icon.Information)
        
        msg.exec()
    def setup_logs_page(self):
        """Initializes the logs page UI components and connections."""
        # Set default times: roughly 1 hour before to 1 hour after current time
        now = QDateTime.currentDateTime()
        
        # Round 1 hour before to the hour (e.g. 2:38 -> 2:00 as per user example)
        # Note: now.addSecs(-3600) gives '1 hour ago', then we take just the hour part
        start_time = now.addSecs(-3600)
        start_time = QDateTime(start_time.date(), QTime(start_time.time().hour(), 0))
        
        # 1 hour after, also rounded
        end_time = now.addSecs(3600)
        end_time = QDateTime(end_time.date(), QTime(end_time.time().hour(), 0))
        
        if hasattr(self, 'start_time_edit'):
            self.start_time_edit.setDateTime(start_time)
        if hasattr(self, 'end_time_edit'):
            self.end_time_edit.setDateTime(end_time)

        # Set display format for better time picking
        for edit in [self.start_time_edit, self.end_time_edit]:
            if hasattr(edit, 'setDisplayFormat'):
                edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")

        # Initialize time presets
        if hasattr(self, 'time_preset_combo'):
            self.time_preset_combo.addItems(["Custom", "Last 15m", "Last Hour", "Today", "Last 24h", "All Time"])
            self.time_preset_combo.currentIndexChanged.connect(self._on_time_preset_changed)
            
        # Connect search button
        if hasattr(self, 'search_logs_btn'):
            self.search_logs_btn.clicked.connect(self.search_logs)
            
        # Connect print button
        if hasattr(self, 'print_logs_btn'):
            self.print_logs_btn.clicked.connect(self.export_logs_to_file)
            
        # Connect list widget selection
        if hasattr(self, 'logs_list_widget'):
            self.logs_list_widget.itemSelectionChanged.connect(self._on_log_selected)
            
        # Real-time refresh timer (every 3 seconds)
        self.logs_refresh_timer = QTimer(self)
        self.logs_refresh_timer.timeout.connect(self._auto_refresh_logs)
        self.logs_refresh_timer.start(3000)
            
        # Initial log load
        self.search_logs()

    def _auto_refresh_logs(self):
        """Periodically refreshes the logs list if the logs page is visible."""
        # Only refresh if on logs page (index 3) and no search text or date changes by user
        if self.Content_stack.currentIndex() == 3:
            # We refresh even if searching, so the search results update live
            self.search_logs()

    def search_logs(self):
        """Retrieves and displays logs based on search criteria."""
        if not hasattr(self, 'logs_list_widget'):
            return
            
        search_text = self.search_input.text() if hasattr(self, 'search_input') else ""
        start_ts = self.start_time_edit.dateTime().toSecsSinceEpoch() if hasattr(self, 'start_time_edit') else None
        
        # If end time is very close to now (within 5 seconds), treat as "Live" and don't cap it
        end_dt = self.end_time_edit.dateTime() if hasattr(self, 'end_time_edit') else None
        end_ts = end_dt.toSecsSinceEpoch() if end_dt else None
        if end_dt and abs(end_dt.secsTo(QDateTime.currentDateTime())) < 60:
            end_ts = None # No upper limit for "live" logs
            
        logs = self.log_manager.get_logs(start_time=start_ts, end_time=end_ts, person_name=search_text)
        
        # Avoid clearing/jumping if count is the same (simple heuristic for "nothing new")
        if hasattr(self, '_last_log_count') and len(logs) == self._last_log_count and not self.logs_list_widget.count() == 0:
             return
        
        self._last_log_count = len(logs)
        self.logs_list_widget.clear()
        for log in logs:
            import datetime
            ts_str = datetime.datetime.fromtimestamp(log['timestamp']).strftime("%Y-%m-%d %H:%M:%S")
            msg = f"[{ts_str}] {log['message']}"
            
            item = QListWidgetItem(msg)
            # Store person name in UserRole for summary retrieval
            item.setData(Qt.ItemDataRole.UserRole, log['person_name'])
            
            # Color coding by type
            if log['type'] == 'action':
                item.setForeground(QColor("#ffaa00")) # Orange for actions
            elif log['type'] == 'entry':
                item.setForeground(QColor("#00ff00")) # Green for entry
            elif log['type'] == 'exit':
                item.setForeground(QColor("#ff5555")) # Red for exit
                
            self.logs_list_widget.addItem(item)

    def _on_log_selected(self):
        """Triggered when a log entry is selected. Shows person activity summary."""
        if not hasattr(self, 'logs_list_widget') or not hasattr(self, 'detail_view_browser'):
            return
            
        current_item = self.logs_list_widget.currentItem()
        if not current_item:
            return
            
        person_name = current_item.data(Qt.ItemDataRole.UserRole)
        if not person_name or person_name == "Unknown":
            self.detail_view_browser.setText("Select an identified person to see their activity summary.")
            return
            
        summary = self.log_manager.get_person_activity_summary(person_name)
        
        # Format summary with some HTML for better readability
        html_summary = f"<h2>Activity Summary: {person_name}</h2>"
        html_summary += summary.replace("\n", "<br>")
        
        self.detail_view_browser.setHtml(html_summary)

    def _on_time_preset_changed(self, index):
        """Updates start and end times based on preset selection."""
        if index == 0: # Custom
            return
            
        now = QDateTime.currentDateTime()
        self.end_time_edit.setDateTime(now)
        
        if index == 1: # Last 15m
            self.start_time_edit.setDateTime(now.addSecs(-15 * 60))
        elif index == 2: # Last Hour
            self.start_time_edit.setDateTime(now.addSecs(-3600))
        elif index == 3: # Today
            start_of_day = QDateTime(now.date(), QTime(0, 0))
            self.start_time_edit.setDateTime(start_of_day)
        elif index == 4: # Last 24h
            self.start_time_edit.setDateTime(now.addDays(-1))
        elif index == 5: # All Time
            # Set to a very early date
            self.start_time_edit.setDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0)))

        self.search_logs()

    def export_logs_to_file(self):
        """Exports currently filtered logs to a text file."""
        search_text = self.search_input.text() if hasattr(self, 'search_input') else ""
        start_ts = self.start_time_edit.dateTime().toSecsSinceEpoch() if hasattr(self, 'start_time_edit') else None
        end_ts = self.end_time_edit.dateTime().toSecsSinceEpoch() if hasattr(self, 'end_time_edit') else None
        
        logs = self.log_manager.get_logs(start_time=start_ts, end_time=end_ts, person_name=search_text)
        
        if not logs:
            self.show_message("Export", "No logs found to export with current filters.")
            return
            
        # Generate filename with timestamp
        filename = f"ObserveAI_Logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        file_path = os.path.join(os.getcwd(), filename)
        
        try:
            with open(file_path, 'w') as f:
                f.write(f"ObserveAI Logs Export\n")
                f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Filters: Name='{search_text}', Start='{self.start_time_edit.dateTime().toString()}', End='{self.end_time_edit.dateTime().toString()}'\n")
                f.write("-" * 50 + "\n\n")
                
                # Logs are sorted by timestamp DESC, so reverse for chronological export
                for log in reversed(logs):
                    log_ts = datetime.fromtimestamp(log['timestamp']).strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{log_ts}] {log['message']}\n")
            
            self.show_message("Export Success", f"Logs exported successfully to:\n{filename}")
        except Exception as e:
            self.show_message("Export Error", f"Failed to export logs: {str(e)}", "critical")
