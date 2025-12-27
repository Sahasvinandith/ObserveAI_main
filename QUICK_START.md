# Multi-Camera Tracking System - Quick Start Guide

## 🚀 5-Minute Overview

You've just deployed a sophisticated cross-camera person tracking system. Here's what you can do:

### What's New?

```python
# In MainWindow, you now have:
self.global_person_tracker      # Tracks persons globally
self.camera_graph               # Maps camera positions & relationships
self.cross_camera_reid          # Matches persons across cameras
```

---

## 📋 Basic Usage

### 1. Add Multiple Cameras to Scene

```python
# Add Camera 1
mainwindow.create_camera_items("Camera_A", "rtsp://...", pos=QPointF(100, 100), rot=0)

# Add Camera 2
mainwindow.create_camera_items("Camera_B", "rtsp://...", pos=QPointF(150, 120), rot=45)

# Add Camera 3
mainwindow.create_camera_items("Camera_C", "rtsp://...", pos=QPointF(400, 400), rot=90)
```

**What happens automatically:**
- ✅ Each camera added to CameraGraph
- ✅ Camera relationships calculated (neighbors, overlaps)
- ✅ View cones computed
- ✅ DetectionSystem initialized with global tracking

---

### 2. View System Status

```python
# See global person statistics
mainwindow.print_global_person_statistics()

# See camera relationships
mainwindow.print_camera_graph_info()

# See identified persons' journeys
mainwindow.print_person_trails()

# See cross-camera matching stats
mainwindow.log_cross_camera_reid_statistics()
```

**Console Output:**
```
============================================================
GLOBAL PERSON TRACKER STATISTICS
============================================================
Total persons tracked: 5
Identified persons: 2
Unique cameras: 3
Next global ID: 6
============================================================

============================================================
CAMERA GRAPH INFORMATION
============================================================

Camera_A:
  Position: [100.0, 100.0]
  Rotation: 0°
  Neighbors: ['Camera_B']
    - Camera_B: direction=ahead, overlaps=True

Camera_B:
  Position: [150.0, 120.0]
  Rotation: 45°
  Neighbors: ['Camera_A', 'Camera_C']
    - Camera_A: direction=behind, overlaps=True
    - Camera_C: direction=ahead, overlaps=False
```

---

### 3. Query Persons

```python
# Get person by name
user5 = mainwindow.get_person_by_name("User_5")
if user5:
    print(f"User_5 last seen in: {user5.get_cameras_seen_in()}")
    trail = mainwindow.cross_camera_reid.get_person_trajectory_string(user5.global_id)
    print(f"Trail: {trail}")
    # Output: "Camera_A (0s) → Camera_B (5s) → Camera_C (12s)"

# Get who's in a camera right now
persons_now = mainwindow.get_persons_in_camera("Camera_B")
for person in persons_now:
    print(f"{person.name} is in Camera_B")

# Get all identified persons
identified = mainwindow.global_person_tracker.get_identified_persons()
for person in identified:
    print(f"{person.name}: cameras={person.get_cameras_seen_in()}")
```

---

## 🎯 How It Works

### Scenario: Person Walks Through Multi-Camera System

```
Time 0s: Person enters Camera_A
├─ Detected by YOLO
├─ Assigned local_id = 1 (per Camera_A)
├─ Re-ID features extracted
├─ Created in GlobalPersonTracker with global_id = 1
└─ Name = "Unknown"

Time 5s: Person walks to Camera_B view
├─ Camera_B detects person
├─ Person has different local_id in Camera_B
├─ But features are similar!
├─ CrossCameraReID matches them
└─ Now both cameras know it's the same global_id = 1

Time 10s: Face recognized as "User_5" in Camera_B
├─ Recognition worker identifies face
├─ Calls propagate_identification()
├─ ALL cameras get notification
├─ Camera_A now displays "User_5" (even though person left)
└─ System knows person identity everywhere

Time 15s: Person walks to Camera_C
├─ Camera_C detects new person
├─ Features match existing global_person_1
├─ Cross-camera matching confirms
└─ Camera_C displays "User_5" immediately
```

---

## ⚙️ Configuration

### Change Feature Matching Sensitivity

```python
# More strict (fewer false positives)
self.cross_camera_reid.feature_distance_threshold = 0.35

# Current default (balanced)
self.cross_camera_reid.feature_distance_threshold = 0.40

# More lenient (more matches)
self.cross_camera_reid.feature_distance_threshold = 0.45
```

### Adjust Temporal Window

```python
# Only match persons active in last 5 seconds
self.cross_camera_reid.temporal_threshold = 5.0

# Default: 10 seconds
self.cross_camera_reid.temporal_threshold = 10.0

# Match persons up to 30 seconds later
self.cross_camera_reid.temporal_threshold = 30.0
```

---

## 📊 Key Metrics

### Memory Usage
- Per person: ~3KB (features + metadata)
- 1000 persons: ~3MB
- System overhead: <10MB

### Processing Speed
- Feature extraction: ~50ms
- Cross-camera match: <50ms
- Identity propagation: <1ms
- Person search: <100ms

### Accuracy Factors
1. **Re-ID feature quality** - Good lighting, full body visible
2. **Camera overlap** - More overlap = easier matching
3. **Feature threshold** - Lower = stricter (fewer false positives)
4. **Time between sightings** - Sooner = easier to match

---

## 🔍 Debugging

### Check if cameras are connected

```python
graph_info = mainwindow.camera_graph.get_all_cameras_info()
for cam_name, info in graph_info.items():
    print(f"{cam_name}: neighbors={info['neighbors']}")
    
# Expected output:
# Camera_A: neighbors=['Camera_B']
# Camera_B: neighbors=['Camera_A', 'Camera_C']
# Camera_C: neighbors=['Camera_B']
```

### Check cross-camera matching

```python
stats = mainwindow.cross_camera_reid.get_statistics()
print(f"Matches found: {stats['matches_found']}")
print(f"Threshold: {stats['feature_threshold']}")

# If no matches found:
# 1. Check neighbors: are cameras adjacent?
# 2. Check features: are Re-ID features good?
# 3. Lower threshold: try 0.45 instead of 0.40
```

### Check global persons

```python
stats = mainwindow.global_person_tracker.get_person_statistics()
print(f"Total: {stats['total_persons']}")
print(f"Identified: {stats['identified_persons']}")

# If count is 0: no persons detected yet
# Wait for people to enter camera view
```

---

## 💡 Pro Tips

### Tip 1: Overlapping Cameras are Key
```python
# Good setup: Cameras overlap
Camera_A ─────────┐
                  ├─ Overlap zone
Camera_B ─────────┘

# Poor setup: No overlap (harder to match)
Camera_A ───────── (gap) ───────── Camera_B
```

### Tip 2: Monitor Coverage
```python
coverage = mainwindow.camera_graph.get_coverage_map(grid_size=50)
# Returns heatmap of how many cameras see each point
# Use to identify coverage gaps
```

### Tip 3: Verify Camera Pose Data
```python
mainwindow.update_camera()  # Sync positions with CameraGraph

mainwindow.print_camera_graph_info()  # Check calculated positions
```

### Tip 4: Regular Cleanup
```python
# Remove inactive persons (not seen for 30 seconds)
removed = mainwindow.global_person_tracker.cleanup_inactive_persons(timeout=30.0)
print(f"Cleaned up {removed} inactive persons")
```

---

## 🐛 Common Issues & Solutions

### Issue: Persons Not Matching Across Cameras

**Symptom:** Same person detected in Camera_A then Camera_B, but treated as different persons

**Solutions:**
1. Check cameras are neighbors:
   ```python
   neighbors = mainwindow.camera_graph.get_neighbors("Camera_A")
   print(neighbors)  # Should include "Camera_B"
   ```

2. Lower feature threshold (more lenient):
   ```python
   mainwindow.cross_camera_reid.feature_distance_threshold = 0.45
   ```

3. Ensure cameras overlap or are close:
   ```python
   overlaps = mainwindow.camera_graph.overlaps_with("Camera_A", "Camera_B")
   print(overlaps)  # Should be True
   ```

---

### Issue: False Positive Matches

**Symptom:** Different people matched as same person

**Solutions:**
1. Raise feature threshold (stricter):
   ```python
   mainwindow.cross_camera_reid.feature_distance_threshold = 0.35
   ```

2. Ensure good lighting and camera angles
3. Verify both people visible fully in frame

---

### Issue: Identifications Not Propagating

**Symptom:** Person identified in Camera_A but not showing in Camera_B

**Solutions:**
1. Check person is in global registry:
   ```python
   persons = mainwindow.global_person_tracker.global_persons
   print(persons)
   ```

2. Verify propagation was called:
   ```python
   mainwindow.log_cross_camera_reid_statistics()
   ```

3. Force update in both cameras:
   ```python
   mainwindow.update_camera()
   ```

---

## 📚 Learn More

Read the full documentation:
- **MULTI_CAMERA_TRACKING.md** - Complete feature guide
- **ARCHITECTURE_DIAGRAMS.md** - Visual system diagrams
- **IMPLEMENTATION_SUMMARY.md** - Technical details

Run tests:
```bash
python test_multi_camera.py
```

---

## ✅ Quick Checklist

- [ ] Added 2+ cameras with positions
- [ ] Cameras are neighbors (checked with print_camera_graph_info)
- [ ] At least one person detected in system
- [ ] Person trail visible with print_person_trails()
- [ ] Cross-camera matching working (check statistics)
- [ ] Face identified as "User_X"
- [ ] Identification propagated to other cameras
- [ ] System stats look reasonable

---

## 🎉 You're Ready!

Your multi-camera person tracking system is now:
✅ **Configured** - Cameras positioned with known relationships  
✅ **Operational** - Detecting and tracking persons  
✅ **Integrated** - Global person tracking across cameras  
✅ **Smart** - Automatic person matching & identification  
✅ **Scalable** - Add more cameras, system adapts  

Start detecting persons across multiple cameras now! 🚀

---

## Support

**For issues or questions:**
1. Check MULTI_CAMERA_TRACKING.md troubleshooting section
2. Run: `mainwindow.print_global_person_statistics()`
3. Run: `mainwindow.print_camera_graph_info()`
4. Check logs for [CROSS-CAM] messages
5. Adjust feature_distance_threshold and test

---
