from PyQt6.QtCore import  QObject, pyqtSignal ,QThread
import cv2
from PyQt6.QtGui import QImage
import queue

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

    def __init__(self, name, url,frame_buffer: queue.Queue, parent=None):
        super().__init__(parent)
        self.name = name
        self.url_str = url
        self.frame_buffer = frame_buffer
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
            
            if self.frame_buffer:
                try:
                    # Put a *copy* in the queue
                    self.frame_buffer.put_nowait(frame.copy())
                except queue.Full:
                    # Queue is full, drop the frame
                    # You could also drop the *oldest* frame first, then add
                    try:
                        self.frame_buffer.get_nowait() # Remove oldest
                        self.frame_buffer.put_nowait(frame.copy()) # Add newest
                    except queue.Empty:
                        pass # Should not happen, but good to check
                    
                    
                    # adding the captured frame as a Qimage and outputing in cameralist widget
            try:
                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_image.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                self.frameReady.emit(qt_image)
            except Exception as e:
                print(f"Error converting frame for display: {e}")
            
            
            # A short sleep to prevent the thread from
            # hogging 100% CPU if the camera is fast.
            # QThread.msleep(10) # ~100 fps max
            
        # --- 3. Cleanup ---
        if cap:
            cap.release()
        print(f"[{self.name}] Worker thread stopped.")
        
        QThread.msleep(10) # ~100 FPS cap, adjust as needed

    def stop(self):
        """
        Sets the flag to stop the run() loop.
        """
        print(f"[{self.name}] stop() called.")
        self.is_running = False