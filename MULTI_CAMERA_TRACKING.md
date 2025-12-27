# Multi-Camera Tracking System - Implementation Guide

## Overview

A sophisticated cross-camera person re-identification and tracking system has been integrated into ObserveAI. This enables:

1. **Spatial Awareness** - Cameras are positioned in a scene graph with overlap detection
2. **Global Person Tracking** - Single global identity across multiple cameras
3. **Cross-Camera Re-ID** - Automatic matching when persons move between cameras
4. **Identity Propagation** - When identified in one camera, all cameras know the identity

---

## Architecture

### Three Core Components

#### 1. **GlobalPersonTracker** (`DataModel/GlobalPersonTracker.py`)
Maintains a global registry of all persons detected in the system.

**Key Classes:**
- `GlobalPerson` - Represents a person with:
  - `global_id` - Unique identifier across all cameras
  - `name` - Identified name (e.g., "User_5") or "Unknown"
  - `camera_tracks` - Dict of which cameras have seen this person
  - `primary_features` - Best Re-ID feature vector
  - `sightings` - Chronological trail across cameras

- `GlobalPersonTracker` - Registry managing all global persons
  - `create_global_person()` - Create new tracked person
  - `link_local_to_global()` - Link camera's local person to global
  - `update_person_identity()` - Update when identified
  - `get_identified_persons()` - Get all identified persons
  - `get_statistics()` - System stats

**Usage:**
```python
tracker = GlobalPersonTracker()
gid = tracker.create_global_person()  # Returns global ID
tracker.link_local_to_global("Camera_A", local_id=1, features=features_vec, global_person_id=gid)
tracker.update_person_identity(gid, "User_5", 0.95)  # Propagates across cameras
```

---

#### 2. **CameraGraph** (`DataModel/CameraGraph.py`)
Maintains spatial relationships between cameras.

**Key Features:**
- `add_camera()` - Add camera with position, rotation, FOV
- `update_camera_pose()` - Update position/rotation dynamically
- `get_neighbors()` - Get adjacent cameras
- `overlaps_with()` - Check if view cones overlap
- `get_direction()` - Get relative direction (ahead, left, right, behind)
- `get_coverage_map()` - Heatmap of surveillance coverage

**Camera Config:**
```python
graph.add_camera(
    name="Camera_A",
    position=(100, 100),      # (x, y) scene coordinates
    rotation_degree=0,         # Facing direction
    view_range=500,           # Detection range in pixels
    fov=60                    # Field of view in degrees
)
```

**Output:**
```
Camera_A neighbors: ['Camera_B']
Camera_B is ahead of Camera_A
Camera_A overlaps with Camera_B: True
```

---

#### 3. **CrossCameraReID** (`DataModel/CrossCameraReID.py`)
Matches persons across cameras using Re-ID features and spatial consistency.

**Key Methods:**
- `match_person_across_cameras()` - Find matching person in neighbors when exiting
- `propagate_identification()` - When identified in one camera, all cameras know
- `link_persons_across_cameras()` - Explicitly link local persons as same global person
- `get_person_trail()` - Get chronological path across cameras
- `find_best_match_in_all_cameras()` - Search entire system for similar person

**How Matching Works:**
```
Person exits Camera_A with Re-ID features:
├─ Get neighboring cameras (Camera_B, Camera_C)
├─ Compare Re-ID features with active persons in neighbors
├─ L2 distance < threshold? YES → MATCH
├─ Check spatial consistency (direction matches)
└─ Link to same global person
```

---

## Integration with MainWindow

### Initialization

```python
# In MainWindow.__init__():
self.global_person_tracker = GlobalPersonTracker()
self.camera_graph = CameraGraph()
self.cross_camera_reid = CrossCameraReID(
    self.global_person_tracker,
    self.camera_graph,
    feature_distance_threshold=0.4  # Matching sensitivity
)
```

### When Adding Camera

```python
def create_camera_items(self, name, url, pos=None, rot=None):
    # ... existing code ...
    
    # NEW: Add to spatial graph
    self.camera_graph.add_camera(
        name=name,
        position=tuple(cam_item.position),
        rotation_degree=cam_item.rotation_degree,
        view_range=cam_item.view_range,
        fov=cam_item.view_angle
    )
    
    # Pass systems to AI detection
    ai_sys = DetectionSystem(
        camera_name=name,
        # ... other params ...
        global_person_tracker=self.global_person_tracker,
        cross_camera_reid=self.cross_camera_reid,
        camera_graph=self.camera_graph
    )
```

### When Moving Camera

```python
def update_camera(self):
    for name, cam_item in self.scene_cameras.items():
        # ... update position/rotation ...
        
        # NEW: Update camera graph
        self.camera_graph.update_camera_pose(
            name,
            position=tuple(cam_item.position),
            rotation_degree=cam_item.rotation_degree
        )
```

---

## Integration with DetectionSystem

### Initialization

```python
class DetectionSystem:
    def __init__(self, ..., global_person_tracker=None, cross_camera_reid=None, camera_graph=None):
        self.global_person_tracker = global_person_tracker
        self.cross_camera_reid = cross_camera_reid
        self.camera_graph = camera_graph
        self.local_to_global_mapping = {}  # Maps local person ID → global ID
```

### When Person Exits (Cleanup)

```python
# In processing_thread_function():
if pid not in current_tracked_ids and time.time() - person.last_seen > 2.0:
    # Try cross-camera match
    if self.cross_camera_reid and person.feature_vector:
        match = self.cross_camera_reid.match_person_across_cameras(
            self.camera_name,
            pid,
            person.feature_vector,
            (person.x, person.y, person.w, person.h)
        )
        
        if match:
            neighbor_cam, neighbor_local_id, confidence = match
            print(f"[CROSS-CAM] Matched {pid} from {self.camera_name} in {neighbor_cam}")
```

### When Face is Identified

```python
# In recognition_worker_function():
if name != "Unknown":
    # Propagate to global tracker
    gid = self.global_person_tracker.link_local_to_global(
        self.camera_name,
        person_id,
        self.tracked_persons[person_id].feature_vector
    )
    
    # Propagate identification across all cameras
    self.cross_camera_reid.propagate_identification(
        gid,
        name,
        confidence,
        self.camera_name
    )
```

---

## Usage Examples

### Example 1: Get Person's Journey

```python
# Get a person's trail through the system
person = mainwindow.get_person_by_name("User_5")
if person:
    trail = mainwindow.cross_camera_reid.get_person_trajectory_string(person.global_id)
    print(trail)
    # Output: "Camera_A (0s) → Camera_B (5s) → Camera_C (12s)"
```

### Example 2: Find Who's in a Camera Right Now

```python
persons_now = mainwindow.get_persons_in_camera("Camera_B")
for person in persons_now:
    print(f"{person.name} is in Camera_B (confidence: {person.confidence:.2f})")
```

### Example 3: Camera Coverage Map

```python
coverage = mainwindow.camera_graph.get_coverage_map(grid_size=50)
# Returns 50x50 array showing how many cameras see each point
# Useful for identifying coverage gaps
```

### Example 4: Print System Statistics

```python
mainwindow.print_global_person_statistics()
mainwindow.print_camera_graph_info()
mainwindow.print_person_trails()
mainwindow.log_cross_camera_reid_statistics()
```

---

## Key Workflows

### Workflow 1: Person Detection & Tracking

```
Person walks into Camera_A
├─ YOLO detects person → local_id=1
├─ Deep SORT tracks → continues tracking
├─ Re-ID features extracted
├─ Linked to new global_person (gid=1)
└─ UI shows "Person 1" (Unknown)

Face recognized as User_5
├─ GlobalPersonTracker updated: gid=1 → "User_5"
├─ CrossCameraReID propagates to all cameras
└─ All cameras now show "User_5"
```

### Workflow 2: Person Movement Between Cameras

```
Person walks from Camera_A toward Camera_B
├─ In Camera_A: actively tracked, name="User_5"
├─ Moves out of view
├─ Processing thread: person_id=1 not in current_tracked
│   └─ Calls: cross_camera_reid.match_person_across_cameras()
│       ├─ Gets neighbors of Camera_A → [Camera_B]
│       ├─ Compares Re-ID features
│       ├─ Finds match in Camera_B
│       └─ Confidence=0.92 (similar features)
├─ Links: Camera_B local_person=2 → same global_person=1
└─ Camera_B displays "User_5" immediately
```

### Workflow 3: Cross-Camera Search

```
Query: "Find person similar to this face"
├─ Extract Re-ID features from query face
├─ Call: reid.find_best_match_in_all_cameras(query_features)
├─ Compare against all persons in system
├─ Return top K matches with distances
└─ User finds person across different camera & time
```

---

## Configuration

### Feature Matching Threshold

```python
# In MainWindow.__init__():
self.cross_camera_reid = CrossCameraReID(
    self.global_person_tracker,
    self.camera_graph,
    feature_distance_threshold=0.4  # Lower = stricter matching
)
```

**Threshold Guide:**
- `0.3` - Very strict, only high confidence matches
- `0.4` - Recommended, balances precision & recall
- `0.5` - More lenient, catches more matches but more false positives

### Temporal Threshold

```python
# Max time between sightings to consider same person
cross_camera_reid = CrossCameraReID(
    global_tracker,
    camera_graph,
    temporal_threshold=10.0  # seconds
)
```

---

## Performance Considerations

### 1. Feature Extraction
- Only extracted when person is first detected
- Stored in `Person.feature_vector`
- Reused for all cross-camera matching

### 2. Matching Cost
- **Time**: O(N_neighbors × M_active_persons) per person exit
- **Space**: 256 floats per person (Re-ID features)
- Typically **<50ms** per match

### 3. Garbage Collection
```python
# Periodically clean up inactive persons
mainwindow.global_person_tracker.cleanup_inactive_persons(timeout=30.0)
```

---

## Debugging & Logging

### View All Systems Logs

```python
mainwindow.print_global_person_statistics()
mainwindow.print_camera_graph_info()
mainwindow.print_person_trails()
mainwindow.log_cross_camera_reid_statistics()
```

### Sample Output

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
  View Range: 200.0px
  FOV: 70°
  Neighbors: ['Camera_B']
    - Camera_B: direction=ahead, overlaps=True

Camera_B:
  Position: [150.0, 120.0]
  Rotation: 45°
  ...
```

---

## Files Changed/Created

| File | Change | Purpose |
|------|--------|---------|
| `DataModel/GlobalPersonTracker.py` | NEW | Global person registry |
| `DataModel/CameraGraph.py` | NEW | Camera spatial mapping |
| `DataModel/CrossCameraReID.py` | NEW | Cross-camera matching |
| `components/Camera_widget.py` | MODIFIED | Added `global_person_id` field |
| `DataModel/DetectionSystem.py` | MODIFIED | Added cross-camera hooks |
| `main/MainWindow.py` | MODIFIED | Full integration of all systems |
| `test_multi_camera.py` | NEW | Test script & examples |

---

## Next Steps

1. **Test with Real Cameras**: Run system with actual multi-camera setup
2. **Tune Thresholds**: Adjust `feature_distance_threshold` based on real-world performance
3. **Visualize Coverage**: Use `camera_graph.get_coverage_map()` to visualize gaps
4. **Optimize Performance**: Profile and optimize for your specific hardware
5. **Add UI Widgets**: Create visual displays for:
   - Person trails on camera layout
   - Cross-camera match notifications
   - System statistics dashboard

---

## Testing

Run the test suite:
```bash
python test_multi_camera.py
```

Output:
```
✅ ALL TESTS PASSED!
- GlobalPersonTracker: ✓
- CameraGraph: ✓
- CrossCameraReID: ✓
- Integration: ✓
```

---

## Troubleshooting

### Persons Not Being Matched Across Cameras

1. **Check camera graph**: `mainwindow.print_camera_graph_info()`
   - Are cameras neighbors?
   - Check `direction` and `overlaps`

2. **Check feature quality**: Re-ID features may be poor
   - Ensure good lighting
   - Persons need to be in view for full frame

3. **Adjust threshold**: Lower `feature_distance_threshold`
   - Current: 0.4
   - Try: 0.45 (more lenient)

### Incorrect Identifications Propagating

1. **Check match confidence**: Should be > 0.7
2. **Review person trail**: `mainwindow.print_person_trails()`
3. **Increase threshold**: Higher value = stricter matching

### Performance Issues

1. **Profile**: Check CPU usage of detection system
2. **Reduce FPS**: Lower `gui_fps_limit` in DetectionSystem
3. **Increase frame skip**: Higher `frame_skip_interval`

---

## API Reference

### GlobalPersonTracker

```python
tracker.create_global_person() → int
tracker.get_person(global_id) → GlobalPerson | None
tracker.get_persons_in_camera(cam_name) → List[GlobalPerson]
tracker.get_identified_persons() → List[GlobalPerson]
tracker.update_person_identity(gid, name, confidence)
tracker.cleanup_inactive_persons(timeout=30.0) → int_removed
```

### CameraGraph

```python
graph.add_camera(name, position, rotation, view_range, fov)
graph.update_camera_pose(name, position, rotation)
graph.get_neighbors(cam_name) → List[str]
graph.overlaps_with(cam1, cam2) → bool
graph.get_direction(from_cam, to_cam) → str
graph.get_camera_view_cone(cam_name) → List[Tuple[float, float]]
graph.get_coverage_map(grid_size=50) → np.ndarray
```

### CrossCameraReID

```python
reid.match_person_across_cameras(camera, local_id, features, bbox) → Tuple | None
reid.propagate_identification(gid, name, confidence, camera)
reid.link_persons_across_cameras(cam1, id1, feat1, cam2, id2, feat2) → int
reid.get_person_trail(gid) → List[Tuple[str, float]]
reid.get_person_trajectory_string(gid) → str
reid.find_best_match_in_all_cameras(features, exclude_cam, top_k) → List
```

---

## Version History

- **v1.0** - Initial implementation
  - GlobalPersonTracker
  - CameraGraph with overlap detection
  - CrossCameraReID with feature matching
  - Full MainWindow integration
  - DetectionSystem hooks for global tracking

---
