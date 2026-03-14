#!/usr/bin/env python3
"""
GUI test for BirdsEyeViewWidget with actual visualization
"""
import sys
sys.path.insert(0, '/home/sahas/Projects/ObserveAI_main')

from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from PyQt6.QtCore import Qt, QTimer
from components.BirdsEyeViewWidget import BirdsEyeViewWidget
from DataModel.GlobalPersonTracker import GlobalPersonTracker

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BirdsEyeView Test")
        self.setGeometry(100, 100, 1200, 800)
        
        # Create tracker and widget
        self.tracker = GlobalPersonTracker()
        self.tracker.register_camera(
            name="Cam1",
            position=(0, 0),
            rotation=0,
            fov=90,
            view_range=5
        )
        self.tracker.register_camera(
            name="Cam2",
            position=(3, 3),
            rotation=45,
            fov=85,
            view_range=4
        )
        
        # Create widget and set data
        self.bev_widget = BirdsEyeViewWidget(self)
        self.bev_widget.set_data_sources(self.tracker, {"Cam1": None, "Cam2": None})
        
        # Create layout
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.bev_widget)
        
        # Add button to add fake person
        btn = QPushButton("Add Person")
        btn.clicked.connect(self.add_person)
        layout.addWidget(btn)
        
        self.setCentralWidget(widget)
        
        # Timer to add persons automatically
        self.person_id = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.add_random_person)
        self.timer.start(2000)  # Add person every 2 seconds
    
    def add_person(self):
        self.add_random_person()
    
    def add_random_person(self):
        self.person_id += 1
        import random
        
        # Create a fake person
        person = type('Person', (), {
            'global_id': self.person_id,
            'smoothed_position': (random.uniform(-1, 3), random.uniform(-1, 3)),
            'camera_tracks': {},
        })()
        
        self.tracker.global_persons[self.person_id] = person
        print(f"Added person {self.person_id} at {person.smoothed_position}")
        
        # Update visualization
        self.bev_widget.update_visualization()
        
        if self.person_id >= 5:
            self.timer.stop()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())
