import cv2
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

class ClickableLabel(QLabel):
    clicked_x = pyqtSignal(int)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked_x.emit(event.pos().x())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

class ImageClickDialog(QDialog):
    """
    Shows a camera frame and lets the user click a point.
    Returns the normalized X coordinate of the click.
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

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qimg = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        self.pixmap = QPixmap.fromImage(qimg)
        
        self.image_label = ClickableLabel()
        self.image_label.setPixmap(self.pixmap)
        self.image_label.setCursor(Qt.CursorShape.CrossCursor)
        self.image_label.clicked_x.connect(self._on_image_clicked)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.layout.addWidget(self.image_label)
        
        btn_layout = QVBoxLayout()
        cancel_btn = QPushButton("Cancel Point")
        cancel_btn.setFixedSize(120, 30)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.layout.addLayout(btn_layout)

    def _on_image_clicked(self, label_x: int):
        # image_label might be wider/centered, but label_x is relative to the widget.
        # However, we set alignment center, so the pixmap might be centered in the label.
        # To be precise, we calculate the x offset.
        
        pixmap_width = self.pixmap.width()
        label_width = self.image_label.width()
        x_offset = (label_width - pixmap_width) / 2 if label_width > pixmap_width else 0
        
        actual_x = label_x - x_offset
        if actual_x < 0: actual_x = 0
        if actual_x > pixmap_width: actual_x = pixmap_width
        
        # Calculate normalized X coordinate across the original frame
        self.normalized_x = actual_x / pixmap_width
        self.accept()
