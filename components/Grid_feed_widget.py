from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QToolButton, QFrame, QSizePolicy
)
from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtGui import QImage, QPixmap

class GridFeedWidget(QWidget):
    """
    A custom widget for displaying a single video feed in the grid.
    Includes a title bar with the camera name and a maximize button.
    """
    
    # Signal to tell MainWindow to maximize/minimize this widget
    toggle_maximize = pyqtSignal()

    def __init__(self, camera_name: str, parent=None):
        super().__init__(parent)
        self.camera_name = camera_name
        
        # --- Set Size Policy and Minimum Size ---
        # This is for your "smart sizing" requirement.
        # Expanding: It will try to fill space.
        # Ignored: It can also be shrunk below its sizeHint.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        
        # This is your "minimum size threshold".
        # Adjust this (width, height) to your liking.
        self.setMinimumSize(320, 240) 

        # --- Main Layout ---
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2) # Small border
        main_layout.setSpacing(0)

        # --- 1. Title Bar ---
        self.title_bar = QFrame(self)
        self.title_bar.setStyleSheet("background-color: #333; border-radius: 2px;")
        self.title_bar.setFixedHeight(25)
        
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(5, 0, 0, 0)
        title_layout.setSpacing(5)

        self.title_label = QLabel(self.camera_name)
        self.title_label.setStyleSheet("color: white; font-weight: bold;")
        
        self.maximize_button = QToolButton(self)
        self.maximize_button.setText("□") # "Maximize" character
        self.maximize_button.setToolTip("Toggle Fullscreen")
        self.maximize_button.setStyleSheet("""
            QToolButton { color: white; border: none; font-size: 16px; }
            QToolButton:hover { background-color: #555; }
        """)
        # Connect the button click to our signal
        self.maximize_button.clicked.connect(self.toggle_maximize.emit)

        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        title_layout.addWidget(self.maximize_button)

        # --- 2. Video Label ---
        self.video_label = QLabel("Connecting...", self)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; color: gray;")
        # The video label should take up all remaining space
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding) 

        # --- Add to main layout ---
        main_layout.addWidget(self.title_bar)
        main_layout.addWidget(self.video_label, stretch=1) # stretch=1 makes it fill

    def update_frame(self, qt_image: QImage):
        """Public slot to receive a new frame."""
        if not qt_image.isNull():
            # Scale the image to fit the label, keeping aspect ratio.
            # This makes the widget resizable.
            self.video_label.setPixmap(QPixmap.fromImage(qt_image).scaled(
                self.video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
        else:
            self.video_label.setText("No Signal")
            self.video_label.setStyleSheet("background-color: black; color: red;")

    def set_error_message(self, message: str):
        """Public slot to show an error."""
        self.video_label.setText(message)
        self.video_label.setStyleSheet("background-color: black; color: red;")

    def on_connection_success(self, message: str):
        """Public slot to clear error/connecting message."""
        self.video_label.setText("") # Clear "Connecting..."
        self.video_label.setStyleSheet("background-color: black;")