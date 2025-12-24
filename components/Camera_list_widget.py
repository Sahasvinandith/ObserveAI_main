from PyQt6.QtWidgets import QWidget, QLabel
from PyQt6.QtCore import pyqtSlot, Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6 import uic  # Import uic module
import os

class CameraFeedWidget(QWidget):
    """
    A QWidget that shows a live camera feed.
    """
    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        
        # --- 1. Load UI from Designer file ---
        # Ensure the path is correct relative to this script
        uic.loadUi("./UIs/camera_feed_widget.ui", self)
        
        # --- 2. Post-Load Setup ---
        # Access widgets by the objectNames you set in Designer
        self.title_label.setText(self.name)
        
        # (Optional) If you didn't set fixed size in Designer, you can still do it here:
        # self.video_label.setFixedSize(240, 180) 

    @pyqtSlot(QImage)
    def update_frame(self, qt_image):
        """Slot to receive the QImage from the worker thread."""
        if not qt_image.isNull():
            # self.video_label is automatically available after loadUi
            scaled_image = qt_image.scaled(self.video_label.width(), self.video_label.height(),
                                        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.video_label.setPixmap(QPixmap.fromImage(scaled_image))

    @pyqtSlot(str)
    def set_error_message(self, message):
        self.video_label.setStyleSheet("background-color: black; color: red;")
        self.video_label.setText(message)

    @pyqtSlot(str)
    def on_connection_success(self, message):
        self.video_label.setStyleSheet("") 
        self.video_label.setText("")