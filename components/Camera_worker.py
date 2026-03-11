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
    finished = pyqtSignal()

    def __init__(self, name, url,frame_buffer: queue.Queue, parent=None):
        super().__init__(parent)
        self.name = name
        self.url_str = url
        self.frame_buffer = frame_buffer
        self.is_running = True # Flag to control the loop
        self.should_reconnect = False  # Flag to trigger reconnection attempt

        try:
            self.url_int = int(self.url_str)
        except ValueError:
            self.url_int = None
            
    def run(self):
        """
        The main work loop. This runs in the background thread.
        """
        cap = None
        
        try:
        
            # --- 1. Connection Phase ---
            print(f"[{self.name}] Worker thread: Trying to connect...")
            url_to_try = self.url_int if self.url_int is not None else self.url_str
            cap = cv2.VideoCapture(url_to_try)
            
            if not cap or not cap.isOpened():
                self.connectionFailed.emit(f"Failed to open:\n{self.url_str}")
                cap = None
            else:
                self.connectionSuccess.emit("Connected")
            
            # --- 2. Frame Grab Phase ---
            while self.is_running:
                # Check if reconnection is requested
                if self.should_reconnect:
                    print(f"[{self.name}] Reconnection attempt requested...")
                    self.should_reconnect = False
                    
                    # Release old connection if it exists
                    if cap is not None:
                        cap.release()
                        cap = None
                    
                    # Try to reconnect
                    cap = cv2.VideoCapture(url_to_try)
                    if not cap or not cap.isOpened():
                        self.connectionFailed.emit(f"Reconnection failed:\n{self.url_str}")
                        cap = None
                    else:
                        self.connectionSuccess.emit("Reconnected")
                
                # Only try to grab frames if connected
                if cap is None or not cap.isOpened():
                    QThread.msleep(500)  # Wait a bit before trying again
                    continue
                    
                ret, frame = cap.read()
                
                if not ret:
                    self.connectionFailed.emit("Camera disconnected")
                    if cap is not None:
                        cap.release()
                        cap = None
                    QThread.msleep(500)  # Wait before attempting reconnection
                    continue
                
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
                # adding the captured frame as a Qimage and outputing in cameralist widget
                try:
                    # Convert to RGB for Qt Display
                    rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    bytes_per_line = ch * w
                    
                    # Create QImage from buffer
                    qt_image_ref = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                    
                    # 2. FIX: Create a deep copy to decouple from the local 'rgb_image' numpy array
                    qt_image_safe = qt_image_ref.copy() 

                    self.latest_frame = frame.copy()
                    self.frameReady.emit(qt_image_safe)

                except Exception as e:
                    print(f"Error converting frame for display: {e}")
                    QThread.msleep(10) # ~100 FPS cap, adjust as needed
                
            # --- 3. Cleanup ---
            if cap:
                cap.release()
            print(f"[{self.name}] Worker thread stopped.")
                
        except Exception as e:
            print(f"[{self.name}] Worker thread error: {e}")

    def stop(self):
        """
        Sets the flag to stop the run() loop.
        """
        print(f"[{self.name}] stop() called.")
        self.is_running = False
    
    def restart(self):
        """
        Request a reconnection attempt without stopping the thread.
        This is the minimum-CPU-cost way to refresh the camera connection.
        """
        print(f"[{self.name}] restart() called - requesting reconnection.")
        self.should_reconnect = True