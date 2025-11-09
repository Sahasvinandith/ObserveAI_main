from PyQt6.QtCore import  QObject, pyqtSignal
import cv2
from PyQt6.QtGui import QImage

class CameraWorker(QObject):
    """
    Runs in a separate thread to handle blocking cv2 operations.
    """
    # --- Signals ---
    # Signal to send a new frame (as a QImage) to the GUI
    frameReady = pyqtSignal(QImage)
    # Signal to report connection success
    connectionSuccess = pyqtSignal(str)
    # Signal to report a failure
    connectionFailed = pyqtSignal(str)

    def __init__(self, name, url, parent=None):
        super().__init__(parent)
        self.name = name
        self.url_str = url
        self.is_running = True # Flag to control the loop

        try:
            self.url_int = int(self.url_str)
        except ValueError:
            self.url_int = None
            
    def run(self):
        """
        The main work loop. This runs in the background thread.
        """
        cap = None
        
        # --- 1. Connection Phase ---
        print(f"[{self.name}] Worker thread: Trying to connect...")
        url_to_try = self.url_int if self.url_int is not None else self.url_str
        cap = cv2.VideoCapture(url_to_try)
        
        if not cap or not cap.isOpened():
            self.connectionFailed.emit(f"Failed to open:\n{self.url_str}")
            return # Stop the thread
        
        self.connectionSuccess.emit("Connected")
        
        # --- 2. Frame Grab Phase ---
        while self.is_running:
            ret, frame = cap.read()
            
            if not ret:
                self.connectionFailed.emit("Camera disconnected")
                self.is_running = False # Stop loop
                break # Exit loop
            
            # Convert frame for Qt
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            
            # Emit the frame
            self.frameReady.emit(qt_image)
            
            # A short sleep to prevent the thread from
            # hogging 100% CPU if the camera is fast.
            # QThread.msleep(10) # ~100 fps max
            
        # --- 3. Cleanup ---
        if cap:
            cap.release()
        print(f"[{self.name}] Worker thread stopped.")

    def stop(self):
        """
        Sets the flag to stop the run() loop.
        """
        print(f"[{self.name}] stop() called.")
        self.is_running = False