import sys
import cv2
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QListWidgetItem, QLabel,
    QGraphicsScene, QGraphicsWidget, QDialog, QVBoxLayout,
    QLineEdit, QPushButton, QDialogButtonBox, QGraphicsItem,
    QGraphicsLinearLayout, QGraphicsProxyWidget
)
from PyQt6.QtCore import QTimer, Qt, QObject, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.uic import loadUi

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

# --- Custom Draggable Camera Widget ---
# --- THIS CLASS IS MODIFIED ---

class CameraWidget(QGraphicsWidget):
    """
    A draggable widget that contains a QLabel for video.
    It now connects to the camera asynchronously.
    """
    
    # Signal to add this camera's name to the main list
    # THIS WILL NOW BE EMITTED FROM next_frame_slot
    camera_added = pyqtSignal(str) 
    
    def __init__(self, name, url, scene):
        super().__init__()
        # Note: We no longer use the 'scene' argument in __init__
        # but we keep it to avoid breaking the call.
        self.name = name
        self.url_str = url # Store the original URL string
        self.cap = None      # Camera isn't opened yet
        self.is_running = False # Not running yet
        
        # Try to parse URL as an int (for webcam 0, 1, etc.)
        try:
            self.url_int = int(self.url_str)
        except ValueError:
            self.url_int = None # It's a string (IP/URL)

        # --- Widget UI Setup (this part is instant) ---
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        
        self.layout = QGraphicsLinearLayout(Qt.Orientation.Vertical)
        
        # Title Label
        self.title_label = QLabel(self.name)
        self.title_label.setStyleSheet("background-color: black; color: white; font-weight: bold;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        proxy_title = QGraphicsProxyWidget()
        proxy_title.setWidget(self.title_label)
        self.layout.addItem(proxy_title)
        
        # Video Label
        self.video_label = QLabel("Connecting...") # Initial state
        self.video_label.setFixedSize(320, 240)
        self.video_label.setStyleSheet("background-color: black; color: gray;")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        proxy_video = QGraphicsProxyWidget()
        proxy_video.setWidget(self.video_label)
        self.layout.addItem(proxy_video)

        self.setLayout(self.layout)
        
        # --- Timer Setup ---
        # The timer's job is to *try* to connect, and then *get frames*
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame_slot)
        self.timer.start(30) # Start polling immediately

        # --- !! REMOVED !! ---
        # We no longer add to scene or emit from here.
        # The MainAppWindow is now responsible for this.
        # self.scene.addItem(self)
        # self.camera_added.emit(self.name) 
        
    def next_frame_slot(self):
        
        # --- 1. Connection Phase ---
        if self.cap is None:
            # We haven't tried to connect yet, or it failed. Try now.
            url_to_try = self.url_int if self.url_int is not None else self.url_str
            self.cap = cv2.VideoCapture(url_to_try)
            
            if not self.cap.isOpened():
                # Failed this time. Release it and try again on next tick.
                self.cap = None 
                self.video_label.setText(f"Connecting to:\n{self.url_str}...")
                return
            else:
                # --- SUCCESSFUL CONNECTION ---
                self.is_running = True
                self.video_label.setText("") # Clear "Connecting" text
                self.video_label.setStyleSheet("") # Clear background
                
                # --- !! SIGNAL EMITTED HERE !! ---
                # Now that we are connected, we emit the signal.
                # The MainAppWindow has had time to connect its slot.
                self.camera_added.emit(self.name)
        
        # --- 2. Frame Grab Phase ---
        if self.is_running:
            ret, frame = self.cap.read()
            if not ret:
                # Connection lost
                self.video_label.setText("Camera disconnected")
                self.video_label.setStyleSheet("background-color: black; color: red;")
                self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.is_running = False
                self.cap.release()
                self.cap = None # Set to None so we try to reconnect
                return
            
            # --- Your DeepFace/CV Logic would go here ---
            # processed_frame = your_function(frame)
            processed_frame = frame 
            # ---
            
            # Convert for Qt
            rgb_image = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            qt_image_scaled = qt_image.scaled(self.video_label.width(), self.video_label.height(), 
                                              Qt.AspectRatioMode.KeepAspectRatio)
            
            self.video_label.setPixmap(QPixmap.fromImage(qt_image_scaled))

    def closeEvent(self, event):
        """Clean up on close."""
        self.timer.stop()
        if self.cap:
            self.cap.release()
        super().closeEvent(event)

# --- MainAppWindow class ---
# --- THIS CLASS IS MODIFIED ---

class MainAppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # --- Load the UI file ---
        loadUi("./UIs/gemini.ui", self)
        
        # --- Set up the QGraphicsScene ---
        self.scene = QGraphicsScene()
        self.graphicsViewScene.setScene(self.scene) # 'graphicsViewScene' is the name from the .ui file
        self.scene.setSceneRect(0, 0, 2000, 2000) # Give the "map" a large size
        
        # --- Connect Signals from .ui file ---
        self.actionAdd_Camera.triggered.connect(self.show_add_camera_dialog)
        self.actionExit.triggered.connect(self.close)
        self.listWidgetCameras.itemClicked.connect(self.focus_on_camera)
        
        self.cameras = {} # To keep track of our camera widgets

    def show_add_camera_dialog(self):
        """
        Called when the 'actionAdd_Camera' (button) is triggered.
        """
        dialog = AddCameraDialog(self)
        
        if dialog.exec():
            name, url = dialog.get_details()
            if name and url:
                print(f"Adding camera: {name}, {url}")
                
                # --- !! NEW, CORRECT ORDER !! ---
                
                # 1. Create the new camera widget
                #    Its __init__ will run and return immediately.
                new_cam = CameraWidget(name, url, self.scene)
                
                # 2. Connect the signal. The "wire" is now live,
                #    waiting for the camera to emit.
                new_cam.camera_added.connect(self.add_camera_to_list)
                
                # 3. Add the widget to the scene
                self.scene.addItem(new_cam)
                
                # 4. Store a reference
                self.cameras[name] = new_cam 
                print("xrr")

    def add_camera_to_list(self, name):
        """
        Slot that gets called by the CameraWidget's signal
        """
        # This will now be called, and you will see the prints
        print(f"--- Slot Invoked ---")
        print(f"Adding camera name to list: {name}")
        
        # 'listWidgetCameras' is the name from the .ui file
        QListWidgetItem(name, self.listWidgetCameras)

    def focus_on_camera(self, item):
        """
        Called when a camera name is clicked in the list.
        """
        name = item.text()
        if name in self.cameras:
            # Get the camera widget
            cam_widget = self.cameras[name]
            
            # De-select all other items
            for other_item in self.scene.selectedItems():
                other_item.setSelected(False)
            
            # Select and focus this one
            cam_widget.setSelected(True)
            self.graphicsViewScene.centerOn(cam_widget)
            print(f"Focused on {name}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainAppWindow()
    window.show()
    sys.exit(app.exec())