import sys
import os
import cv2
import json
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QListWidgetItem,
    QInputDialog, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen, QColor

from ultralytics import YOLO

# YOLOv8-Pose (COCO) Landmark names (17 points)
LANDMARK_NAMES = [
    "0 - NOSE",
    "1 - LEFT_EYE", "2 - RIGHT_EYE",
    "3 - LEFT_EAR", "4 - RIGHT_EAR",
    "5 - LEFT_SHOULDER", "6 - RIGHT_SHOULDER",
    "7 - LEFT_ELBOW", "8 - RIGHT_ELBOW",
    "9 - LEFT_WRIST", "10 - RIGHT_WRIST",
    "11 - LEFT_HIP", "12 - RIGHT_HIP",
    "13 - LEFT_KNEE", "14 - RIGHT_KNEE",
    "15 - LEFT_ANKLE", "16 - RIGHT_ANKLE"
]

class PoseCreator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Action Pose Creator (YOLOv8-Pose)")
        self.resize(1000, 700)
        self.setStyleSheet("background-color: rgb(39, 7, 40); color: white;")

        # Initialize YOLOv8-Pose
        print("[INFO] Loading YOLOv8-Pose model...")
        self.detector = YOLO("yolov8n-pose.pt")

        self.current_image = None
        self.current_landmarks = None  # Dict of str_idx: {x, y, z}
        self.active_keypoints = set()
        
        # Test mode variables
        self.cap = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_live_frame)
        self.reference_action = None # The loaded .json data
        self.is_live_testing = False

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        
        # Left side: Image Display
        left_layout = QVBoxLayout()
        self.image_label = QLabel("No Image Loaded")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: black; border: 1px solid #7a3a8a;")
        self.image_label.setMinimumSize(600, 600)
        left_layout.addWidget(self.image_label)
        
        btn_layout = QHBoxLayout()
        self.load_btn = QPushButton("Load Image")
        self.load_btn.setStyleSheet("background-color: rgb(80, 30, 90); padding: 10px; border-radius: 4px;")
        self.load_btn.clicked.connect(self.load_image)
        btn_layout.addWidget(self.load_btn)
        
        self.save_btn = QPushButton("Save Action")
        self.save_btn.setStyleSheet("background-color: rgb(0, 100, 50); padding: 10px; border-radius: 4px;")
        self.save_btn.clicked.connect(self.save_action)
        self.save_btn.setEnabled(False)
        btn_layout.addWidget(self.save_btn)
        
        left_layout.addLayout(btn_layout)
        
        # Test btn layout
        test_btn_layout = QHBoxLayout()
        
        self.load_action_btn = QPushButton("Load Existing Action")
        self.load_action_btn.setStyleSheet("background-color: rgb(30, 80, 120); padding: 10px; border-radius: 4px;")
        self.load_action_btn.clicked.connect(self.load_action_file)
        test_btn_layout.addWidget(self.load_action_btn)
        
        self.test_live_btn = QPushButton("Start Live Test")
        self.test_live_btn.setStyleSheet("background-color: rgb(150, 80, 0); padding: 10px; border-radius: 4px;")
        self.test_live_btn.clicked.connect(self.toggle_live_test)
        test_btn_layout.addWidget(self.test_live_btn)
        
        left_layout.addLayout(test_btn_layout)
        
        self.status_label = QLabel("Mode: Creator")
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: yellow; padding: 5px;")
        left_layout.addWidget(self.status_label)
        
        # Right side: Landmark Checklist
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Select Active Keypoints:"))
        
        self.landmark_list = QListWidget()
        self.landmark_list.setStyleSheet("background-color: rgb(60, 30, 65); padding: 5px;")
        for name in LANDMARK_NAMES:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.landmark_list.addItem(item)
            
        self.landmark_list.itemChanged.connect(self.on_landmark_toggled)
        right_layout.addWidget(self.landmark_list)
        
        # Add to main
        main_layout.addLayout(left_layout, stretch=3)
        main_layout.addLayout(right_layout, stretch=1)

    def load_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", "Images (*.png *.jpg *.jpeg)")
        if not file_path:
            return
            
        img = cv2.imread(file_path)
        if img is None:
            QMessageBox.critical(self, "Error", "Could not load image.")
            return
            
        self.process_image(img)

    def process_image(self, img):
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        # Run YOLOv8-Pose detection
        results = self.detector(img, verbose=False) # Use BGR for YOLO, it handles it
        
        # Get first person detected
        if len(results) == 0 or results[0].keypoints is None or len(results[0].keypoints.data) == 0:
            QMessageBox.warning(self, "No Pose", "YOLO could not detect a pose in this image.")
            return
            
        # Store original image for drawing
        self.current_image = rgb_img.copy()
        h, w = img.shape[:2]
        
        # Extract landmarks (take first detected pose)
        # YOLO keypoints are [x, y, conf]
        kpts = results[0].keypoints.data[0].cpu().numpy() # [17, 3]
        
        self.current_landmarks = {}
        for idx, kp in enumerate(kpts):
            self.current_landmarks[str(idx)] = {
                "x": float(kp[0] / w), # Normalize to 0-1
                "y": float(kp[1] / h),
                "z": 0.0 # YOLO pose doesn't provide Z, but we keep format for compatibility
            }
            
        self.save_btn.setEnabled(True)
        self.update_display()
            
        self.save_btn.setEnabled(True)
        self.update_display()

    def on_landmark_toggled(self, item):
        self.active_keypoints.clear()
        for i in range(self.landmark_list.count()):
            if self.landmark_list.item(i).checkState() == Qt.CheckState.Checked:
                self.active_keypoints.add(i)
        
        if self.current_image is not None:
            self.update_display()

    def update_display(self):
        if self.current_image is None or not self.current_landmarks:
            return
            
        img_draw = self.current_image.copy()
        h, w, _ = img_draw.shape
        
        # Draw on image using OpenCV for speed
        for idx_str, lm in self.current_landmarks.items():
            idx = int(idx_str)
            cx, cy = int(lm["x"] * w), int(lm["y"] * h)
            
            # Draw color depending on if it's active
            if idx in self.active_keypoints:
                color = (0, 255, 0) # Green for active
                radius = 8
                thickness = -1
            else:
                color = (255, 0, 0) # Red for inactive
                radius = 4
                thickness = 2
                
            cv2.circle(img_draw, (cx, cy), radius, color, thickness)
            
        # Convert back to QPixmap for display
        bytes_per_line = 3 * w
        q_img = QImage(img_draw.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        
        # Scale to fit label
        self.image_label.setPixmap(pixmap.scaled(
            self.image_label.width(), self.image_label.height(), 
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_display()

    def save_action(self):
        if not self.current_landmarks:
            return
            
        if not self.active_keypoints:
            reply = QMessageBox.question(self, "Warning", "No keypoints selected! Do you want to save ALL 33 keypoints as active?", 
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.active_keypoints = set(range(33))
            else:
                return

        action_name, ok = QInputDialog.getText(self, "Action Name", "Enter a name for this action (e.g., 'Smoking'):")
        if not ok or not action_name.strip():
            return
            
        action_name = action_name.strip()
        
        # Build JSON
        data = {
            "action_name": action_name,
            "active_keypoints": sorted(list(self.active_keypoints)),
            "landmarks": self.current_landmarks
        }
        
        # Ensure Actions_db exists
        db_path = "Actions_db"
        os.makedirs(db_path, exist_ok=True)
        
        tgt_file = os.path.join(db_path, f"{action_name}.json")
        try:
            with open(tgt_file, 'w') as f:
                json.dump(data, f, indent=4)
            QMessageBox.information(self, "Success", f"Action '{action_name}' saved successfully to {tgt_file}!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save JSON: {e}")

    def load_action_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Action JSON", "Actions_db", "JSON Files (*.json)")
        if not file_path:
            return
            
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            self.reference_action = data
            self.active_keypoints = set(data.get("active_keypoints", []))
            self.current_landmarks = data.get("landmarks", {})
            
            # Update checklist
            self.landmark_list.blockSignals(True)
            for i in range(self.landmark_list.count()):
                item = self.landmark_list.item(i)
                item.setCheckState(Qt.CheckState.Checked if i in self.active_keypoints else Qt.CheckState.Unchecked)
            self.landmark_list.blockSignals(False)
            
            self.status_label.setText(f"Loaded Action: {data.get('action_name', 'Unknown')}")
            QMessageBox.information(self, "Loaded", f"Loaded action '{data.get('action_name')}' with {len(self.active_keypoints)} active keypoints.")
            
            # If we have landmarks, we can visualize them if we have an image
            if self.current_image is not None:
                self.update_display()
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load action: {e}")

    def toggle_live_test(self):
        if not self.is_live_testing:
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                QMessageBox.critical(self, "Error", "Could not open webcam.")
                return
            
            self.is_live_testing = True
            self.test_live_btn.setText("Stop Live Test")
            self.test_live_btn.setStyleSheet("background-color: rgb(200, 30, 30); padding: 10px; border-radius: 4px;")
            self.timer.start(33) # ~30 FPS
            self.status_label.setText("Mode: Live Testing...")
        else:
            self.is_live_testing = False
            self.timer.stop()
            if self.cap:
                self.cap.release()
            
            self.test_live_btn.setText("Start Live Test")
            self.test_live_btn.setStyleSheet("background-color: rgb(150, 80, 0); padding: 10px; border-radius: 4px;")
            self.status_label.setText("Mode: Creator")

    def update_live_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            return
            
        # Run YOLOv8-Pose
        results = self.detector(frame, verbose=False)
        
        draw_frame = frame.copy()
        h, w = frame.shape[:2]
        
        if len(results) > 0 and results[0].keypoints is not None and len(results[0].keypoints.data) > 0:
            kpts = results[0].keypoints.xyn[0].cpu().numpy() # Normalized 0-1 [17, 2]
            
            # Visualize detected pose
            for idx, kp in enumerate(kpts):
                cx, cy = int(kp[0] * w), int(kp[1] * h)
                color = (0, 255, 0) if idx in self.active_keypoints else (100, 100, 100)
                cv2.circle(draw_frame, (cx, cy), 5, color, -1)
            
            # If we have a reference action loaded, compare!
            if self.reference_action:
                ref_landmarks = self.reference_action.get("landmarks", {})
                active_indices = self.reference_action.get("active_keypoints", [])
                
                if active_indices:
                    # Extract active landmarks from current frame
                    current_marks = []
                    for idx in active_indices:
                        current_marks.append([kpts[idx][0], kpts[idx][1]])
                    
                    # Extract active landmarks from reference
                    ref_marks = []
                    for idx in active_indices:
                        ref_l = ref_landmarks.get(str(idx), {"x":0, "y":0})
                        ref_marks.append([ref_l["x"], ref_l["y"]])
                        
                    current_marks = np.array(current_marks)
                    ref_marks = np.array(ref_marks)
                    
                    # Calculate distance
                    dist = np.linalg.norm(current_marks - ref_marks) / len(active_indices)
                    
                    # Display score
                    score_text = f"Action Score: {dist:.4f}"
                    match_info = "MATCH!" if dist < 0.10 else "No Match"
                    color = (0, 255, 0) if dist < 0.10 else (0, 0, 255)
                    
                    cv2.putText(draw_frame, f"{score_text} ({match_info})", (20, 40), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                    
                    self.status_label.setText(f"Testing '{self.reference_action.get('action_name')}': {match_info} (Score: {dist:.4f})")

        # Convert to QPixmap
        rgb_frame = cv2.cvtColor(draw_frame, cv2.COLOR_BGR2RGB)
        bytes_per_line = 3 * w
        q_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        self.image_label.setPixmap(pixmap.scaled(
            self.image_label.width(), self.image_label.height(), 
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PoseCreator()
    window.show()
    sys.exit(app.exec())
