#!/usr/bin/env python3
"""
Quick test script to check BirdsEyeViewWidget functionality
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

# Create widget
widget = BirdsEyeViewWidget()

# Set data sources (empty scene_cameras)
widget.set_data_sources(tracker, {})

print("=" * 60)
print("Testing BirdsEyeViewWidget")
print("=" * 60)
print(f"Widget created: {widget}")
print(f"Tracker: {tracker}")
print(f"Scene cameras: {widget.scene_cameras}")
print(f"Global tracker cameras: {tracker.cameras}")
print(f"Global persons: {tracker.global_persons}")

# Try to update visualization
print("\n[TEST] Calling update_visualization()...")
widget.update_visualization()

print("\n[TEST] Scene items: {}")
for item in widget.graphics_scene.items():
    print(f"  - {item}")

print("\nTest complete.")
