#!/usr/bin/env python3
"""
Test if persons are being tracked and visualized
"""
import sys
sys.path.insert(0, '/home/sahas/Projects/ObserveAI_main')

from PyQt6.QtWidgets import QApplication
from components.BirdsEyeViewWidget import BirdsEyeViewWidget
from DataModel.GlobalPersonTracker import GlobalPersonTracker

# Create app
app = QApplication(sys.argv)

# Create tracker
tracker = GlobalPersonTracker()

# Register a test camera
tracker.register_camera(
    name="TestCam",
    position=(0, 0),
    rotation=0,
    fov=90,
    view_range=5
)

print("Camera registered:", tracker.cameras)

# Create widget
widget = BirdsEyeViewWidget()
widget.set_data_sources(tracker, {"TestCam": None})  # Use None as placeholder

print("\n[TEST] Initial state:")
print(f"  Scene cameras: {list(widget.scene_cameras.keys())}")
print(f"  Tracker cameras: {list(tracker.cameras.keys())}")
print(f"  Global persons: {list(tracker.global_persons.keys())}")

# Manually add a person to tracker
print("\n[TEST] Adding a fake person to tracker...")
fake_person = type('Person', (), {
    'global_id': 1,
    'smoothed_position': (1.5, 2.0),
    'camera_tracks': {},
})()
tracker.global_persons[1] = fake_person

print(f"  Global persons after add: {list(tracker.global_persons.keys())}")

# Try to update visualization
print("\n[TEST] Calling update_visualization()...")
widget.update_visualization()

print("\n[TEST] Scene items:")
for item in widget.graphics_scene.items():
    print(f"  - {type(item).__name__}")

print("\nTest complete.")
