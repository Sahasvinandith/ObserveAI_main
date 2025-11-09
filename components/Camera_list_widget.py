from PyQt6.QtWidgets import (QWidget, QLabel, QVBoxLayout) # Make sure QWidget is imported
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import QThread,pyqtSlot
from components.Camera_worker import CameraWorker

class CameraFeedWidget(QWidget):
    """
    A QWidget that shows a live camera feed.
    It now delegates all cv2 work to CameraWorker on a QThread.
    """
    def __init__(self, name, url, parent=None):
        super().__init__(parent)
        self.name = name
        
        # --- 1. UI Setup (Same as before) ---
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        self.title_label = QLabel(self.name)
        self.title_label.setStyleSheet("background-color: black; color: white; font-weight: bold; padding: 2px;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.title_label)
        
        self.video_label = QLabel("Connecting...")
        self.video_label.setFixedSize(240, 180)
        self.video_label.setStyleSheet("background-color: black; color: gray;")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.video_label)
        
        # --- 2. Thread and Worker Setup ---
        
        # Create the thread
        self.thread = QThread()
        # Create the worker
        self.worker = CameraWorker(name, url)
        
        # Move the worker to the thread. All its work will be done there.
        self.worker.moveToThread(self.thread)
        
        # --- 3. Connect Signals and Slots ---
        
        # When the thread starts, tell the worker to start its 'run' loop
        self.thread.started.connect(self.worker.run)
        
        # When the worker emits a frame, update our label
        self.worker.frameReady.connect(self.update_frame)
        
        # When the worker fails, update our label
        self.worker.connectionFailed.connect(self.set_error_message)
        
        # When the worker succeeds, clear the label
        self.worker.connectionSuccess.connect(self.on_connection_success)
        
        # When the thread finishes, clean it up
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.worker.deleteLater)
        
        # --- 4. Start the Thread ---
        self.thread.start()

    @pyqtSlot(QImage)
    def update_frame(self, qt_image):
        """Slot to receive the QImage from the worker thread."""
        scaled_image = qt_image.scaled(self.video_label.width(), self.video_label.height(),
                                       Qt.AspectRatioMode.KeepAspectRatio)
        self.video_label.setPixmap(QPixmap.fromImage(scaled_image))

    @pyqtSlot(str)
    def set_error_message(self, message):
        """Slot to show an error message."""
        self.video_label.setStyleSheet("background-color: black; color: red;")
        self.video_label.setText(message)

    @pyqtSlot(str)
    def on_connection_success(self, message):
        """Slot when connection is made."""
        self.video_label.setStyleSheet("") # Clear style
        self.video_label.setText("") # Clear text

    def stop_feed(self):
        """
        Tells the worker to stop its loop and tells the thread to quit.
        """
        print(f"[{self.name}] Stopping feed...")
        # Tell the worker to stop its loop
        self.worker.stop()
        
        # Tell the thread to quit
        self.thread.quit()
        
        # Wait for the thread to finish (optional but good for cleanup)
        self.thread.wait(500) # Wait max 500ms