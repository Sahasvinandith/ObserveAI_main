#!/usr/bin/env python3
"""
Visual test for BirdsEyeViewWidget
"""
import sys
sys.path.insert(0, '/home/sahas/Projects/ObserveAI_main')

from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLabel
from PyQt6.QtCore import Qt, QTimer
from components.BirdsEyeViewWidget import BirdsEyeViewWidget
from DataModel.GlobalPersonTracker import GlobalPersonTracker

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Birds Eye View Test")
        self.setGeometry(100, 100, 1400, 900)
        
        # Create tracker
        self.tracker = GlobalPersonTracker()
        self.tracker.register_camera(
            name="Cheap",
            position=(243.5, 56.0),
            rotation=0,
            fov=85,
            view_range=300
        )
        self.tracker.register_camera(
            name="HD",
            position=(3.0, 157.5),
            rotation=90,
            fov=90,
            view_range=400
        )
        
        # Create widget
        self.bev = BirdsEyeViewWidget(self)
        self.bev.set_data_sources(self.tracker, {"Cheap": None, "HD": None})
        
        # Create layout
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Add label
        label = QLabel("Bird's Eye View - Scaled correctly now!")
        label.setStyleSheet("color: white; background-color: rgb(39, 7, 40);")
        layout.addWidget(label)
        
        layout.addWidget(self.bev)
        self.setCentralWidget(widget)
        
        # Add persons
        self.person_count = 0
        self.add_test_person()
        
        # Auto-update timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_person)
        self.timer.start(500)
    
    def add_test_person(self):
        self.person_count += 1
        person = type('Person', (), {
            'global_id': 1,
            'name': 'Test',
            'smoothed_position': (221.88, 162.90),
            'camera_tracks': {},
        })()
        self.tracker.global_persons[1] = person
        self.bev.update_visualization()
    
    def update_person(self):
        import random
        # Jitter the person position slightly
        person = self.tracker.global_persons.get(1)
        if person:
            x, y = person.smoothed_position
            person.smoothed_position = (
                x + random.uniform(-0.5, 0.5),
                y + random.uniform(-0.5, 0.5)
            )
            self.bev.update_visualization()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = TestWindow()
    window.show()
    sys.exit(app.exec())
