import cv2
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

class ClickableLabel(QLabel):
    clicked = pyqtSignal(int, int)  # CHANGED: Now emits both x and y coordinates
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(event.pos().x(), event.pos().y())  # Emit both coordinates
            event.accept()
        else:
            super().mouseReleaseEvent(event)

class ImageClickDialog(QDialog):
    """
    Shows a camera frame and lets the user click a point.
    Returns the normalized X and Y coordinates of the click.
    
    Y coordinate helps estimate camera view range and depth perception.
    """
    def __init__(self, frame, camera_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Click the matching point in {camera_name}")
        self.setStyleSheet("""
            QDialog { background-color: rgb(39, 7, 40); color: white; }
            QLabel { color: white; background-color: transparent; border: none; font-size: 14px; font-weight: bold; }
            QPushButton { 
                background-color: rgb(60, 30, 65); color: white; 
                border: 1px solid rgb(100, 50, 110); border-radius: 4px; padding: 5px 15px;
            }
            QPushButton:hover { background-color: rgb(100, 50, 110); border: 1px solid rgb(0, 255, 100); }
        """)
        
        self.normalized_x = None
        self.normalized_y = None  # NEW: Capture Y coordinate
        self.layout = QVBoxLayout(self)
        
        lbl = QLabel(f"Click the exact spot on the video where you just clicked on the map.")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(lbl)
        
        # Convert CV2 frame (BGR) to QPixmap
        height, width, channel = frame.shape
        bytes_per_line = 3 * width
        
        # Keep a max width so it fits on screen
        max_dialog_width = 1280
        scale_factor = 1.0
        if width > max_dialog_width:
            scale_factor = max_dialog_width / width
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            frame = cv2.resize(frame, (new_width, new_height))
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            
        self.scale_factor = scale_factor
        self.original_width = int(width / scale_factor)
        self.original_height = int(height / scale_factor)

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qimg = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        self.pixmap = QPixmap.fromImage(qimg)
        
        self.image_label = ClickableLabel()
        self.image_label.setPixmap(self.pixmap)
        self.image_label.setCursor(Qt.CursorShape.CrossCursor)
        self.image_label.clicked.connect(self._on_image_clicked)  # CHANGED: New signal name
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.layout.addWidget(self.image_label)
        
        btn_layout = QVBoxLayout()
        cancel_btn = QPushButton("Cancel Point")
        cancel_btn.setFixedSize(120, 30)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.layout.addLayout(btn_layout)

    def _on_image_clicked(self, label_x: int, label_y: int):  # CHANGED: Now receives both coordinates
        # Handle X coordinate
        pixmap_width = self.pixmap.width()
        label_width = self.image_label.width()
        x_offset = (label_width - pixmap_width) / 2 if label_width > pixmap_width else 0
        
        actual_x = label_x - x_offset
        if actual_x < 0: actual_x = 0
        if actual_x > pixmap_width: actual_x = pixmap_width
        
        # Handle Y coordinate
        pixmap_height = self.pixmap.height()
        label_height = self.image_label.height()
        y_offset = (label_height - pixmap_height) / 2 if label_height > pixmap_height else 0
        
        actual_y = label_y - y_offset
        if actual_y < 0: actual_y = 0
        if actual_y > pixmap_height: actual_y = pixmap_height
        
        # Calculate normalized coordinates
        self.normalized_x = actual_x / pixmap_width
        self.normalized_y = actual_y / pixmap_height
        
        self.accept()
