# Multi-Camera Tracking System - Architecture Diagrams

## 1. System Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                       ObserveAI Application                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              MainWindow (PyQt6)                          │  │
│  │  ┌───────────────────────────────────────────────────┐   │  │
│  │  │  Global Person Tracking System (NEW)             │   │  │
│  │  │  ┌──────────────────────────────────────────────┐ │   │  │
│  │  │  │ • GlobalPersonTracker (registry)             │ │   │  │
│  │  │  │   - Tracks global_id, name, features        │ │   │  │
│  │  │  │   - Stores camera_tracks dict                │ │   │  │
│  │  │  │   - Manages sightings history               │ │   │  │
│  │  │  │                                              │ │   │  │
│  │  │  │ • CameraGraph (spatial mapping)             │ │   │  │
│  │  │  │   - Position, rotation, FOV for each cam    │ │   │  │
│  │  │  │   - Overlap detection                       │ │   │  │
│  │  │  │   - Neighbor relationships                  │ │   │  │
│  │  │  │                                              │ │   │  │
│  │  │  │ • CrossCameraReID (matching engine)        │ │   │  │
│  │  │  │   - L2 feature matching                     │ │   │  │
│  │  │  │   - Spatial consistency checks               │ │   │  │
│  │  │  │   - Identity propagation                    │ │   │  │
│  │  │  └──────────────────────────────────────────────┘ │   │  │
│  │  └───────────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                    ┌─────────┴─────────┐                         │
│                    ▼                   ▼                         │
│  ┌──────────────────────┐  ┌──────────────────────┐             │
│  │   Camera Widgets     │  │   Feed Grid/List     │             │
│  │                      │  │                      │             │
│  │ • CameraItem         │  │ • GridFeedWidget     │             │
│  │ • Position & FOV     │  │ • CameraFeedWidget   │             │
│  │   rendering          │  │ • Display frames     │             │
│  └──────────────────────┘  └──────────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐  ┌─────────┐  ┌─────────┐
   │Camera_A │  │Camera_B │  │Camera_C │
   │ (Worker)│  │ (Worker)│  │ (Worker)│
   └─────────┘  └─────────┘  └─────────┘
        │                ▼                │
        │         ┌──────────────┐        │
        │         │ Spatial Map  │        │
        │         │  (CameraGrph)│        │
        │         └──────────────┘        │
        └─────────────┬────────────────────┘
                      │
        ┌─────────────┴──────────────┐
        ▼                            ▼
   ┌──────────────┐        ┌──────────────────────┐
   │DetectionSys │        │ Detection System     │
   │ (per camera)│        │ (per camera)         │
   │             │        │                      │
   │ • YOLO      │        │ • YOLO detection     │
   │ • DeepSORT  │        │ • Face recognition   │
   │ • Faces     │◄─────┤ • Global linking      │
   │ • Features  │        │ • Cross-camera ID    │
   └──────────────┘        └──────────────────────┘
        ▲                             ▲
        │                             │
        │         (feedback)          │
        └─────────────────────────────┘
            Feature vectors & IDs
```

---

## 2. Data Flow: Person Detection to Global Tracking

```
Camera Frame
    │
    ▼
┌─────────────────┐
│  YOLO Person    │  Detects person bounding box
│  Detection      │  Returns: (x, y, w, h, confidence)
└────────┬────────┘
         │
         ▼
┌──────────────────┐
│  Deep SORT       │  Assigns person ID based on appearance
│  Tracking        │  Maintains track across frames
└────────┬─────────┘
         │ person_id = 1
         │ (local to this camera)
         ▼
┌─────────────────────┐
│  Extract Re-ID      │  Crop person from frame
│  Features           │  Run through feature extractor
│  (256-dim vector)   │  Get appearance embedding
└────────┬────────────┘
         │
         ├─────────────────────────┐
         │                         │
         ▼                         ▼
┌────────────────┐    ┌─────────────────────────┐
│ LOCAL STORAGE  │    │ GLOBAL TRACKING (NEW)   │
│                │    │                         │
│ Camera_A:      │    │ GlobalPersonTracker:    │
│  person_id=1   │    │  global_id = 1          │
│  features = [] │    │  name = "Unknown"       │
│                │    │  features = []          │
│  person_id=2   │    │  camera_tracks = {...}  │
│  features = [] │    │  sightings = [...]      │
└────────────────┘    └───────┬─────────────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │ Face Recognition     │
                   │ (Async in queue)     │
                   │                      │
                   │ DeepFace matching    │
                   │ against Faces_db/    │
                   └───────┬──────────────┘
                           │
                    ┌──────┴──────┐
                    ▼             ▼
            ┌──────────────┐  ┌──────────────┐
            │ IDENTIFIED   │  │   UNKNOWN    │
            │ User_5       │  │ Save to new  │
            │ conf: 0.95   │  │ User folder  │
            └────┬─────────┘  └──────┬───────┘
                 │                   │
                 └─────────┬─────────┘
                           ▼
        ┌──────────────────────────────────┐
        │ CrossCameraReID                  │
        │ .propagate_identification()      │
        │                                  │
        │ Broadcast "User_5" to:           │
        │  • Camera_B                      │
        │  • Camera_C                      │
        │  • All other cameras             │
        └────┬─────────────────────────────┘
             │
             ▼
    All cameras now display "User_5"
    even if they haven't seen this person
```

---

## 3. Cross-Camera Person Matching Flow

```
Scenario: Person moves from Camera_A to Camera_B

Time 0-5s: Person in Camera_A
┌────────────────────────┐
│ Camera_A               │
│ person_local_id = 1    │
│ features = [vec_A]     │ ──────┐
│ name = "Unknown"       │       │
└────────────────────────┘       │
                                 ▼
                    ┌────────────────────────┐
                    │ GlobalPersonTracker    │
                    │ global_person_id = 1   │
                    │ name = "Unknown"       │
                    │ camera_tracks =        │
                    │   Camera_A: local_id=1 │
                    │   features=[vec_A]     │
                    └─────────┬──────────────┘
                              │
                        (Person moves)
                              │
Time 5-6s: Person crosses border ──┤
                              │
                        (Person in Camera_B now)
                              │
┌────────────────────────┐    │
│ Camera_B               │◄───┘
│ person_local_id = 1    │
│ features = [vec_B]     │
│ name = "Unknown"       │
└────────────────────────┘

Time 6s: Camera_A loses person
┌─────────────────────────────────────────┐
│ Processing Thread (DetectionSystem_A)   │
├─────────────────────────────────────────┤
│ Person 1 no longer in current_tracked   │
│                                         │
│ CROSS-CAMERA MATCHING:                  │
│ ┌───────────────────────────────────┐   │
│ │ cross_camera_reid.               │   │
│ │  match_person_across_cameras()    │   │
│ │                                   │   │
│ │ Input: Camera_A, person_1, vec_A  │   │
│ │                                   │   │
│ │ 1. Get neighbors: [Camera_B]      │   │
│ │ 2. Get active persons in Camera_B │   │
│ │ 3. For each person in Camera_B:   │   │
│ │    distance = L2(vec_A, vec_B)    │   │
│ │    0.15 < threshold(0.4)?         │   │
│ │    YES! ✓ MATCH FOUND             │   │
│ │                                   │   │
│ │ Output: (Camera_B, person_1, 0.15)│   │
│ └───────────────────────────────────┘   │
│                                         │
│ ACTION: Link as same global person      │
└──────────────┬──────────────────────────┘
               │
               ▼
    ┌──────────────────────────────┐
    │ GlobalPersonTracker          │
    │                              │
    │ global_person_id = 1         │
    │ camera_tracks =              │
    │   Camera_A:                  │
    │     local_id = 1             │
    │     features = [vec_A]       │
    │   Camera_B:                  │ ◄── LINKED!
    │     local_id = 1             │
    │     features = [vec_B]       │
    └──────────────────────────────┘
               │
               ▼
    Both cameras tracking same person!
    Even if appearance changes slightly,
    they maintain continuity.
```

---

## 4. Camera Graph - Spatial Relationships

```
                    View Cone Visualization
                    
        Camera_A (0°)             Camera_B (45°)
        
        ┌──────────┐              ┌──────────┐
        │    →     │              │   ↗      │
        │   FOV    │              │  FOV    │
        │    60°   │              │  60°    │
        └──────────┘              └──────────┘
         /      \                  /      \
        /  View  \                /  View  \
       /  Cone   \              /  Cone   \
      /___________\            /___________\
     (100,100)                (150,120)
        A                        B
        
        Distance: 71px
        Overlap: YES ✓
        Direction A→B: "ahead"


    Adjacency Matrix
    ┌─────────────────┐
    │     │A│B│C│    │
    │ ────────────────│
    │ A   │ │✓│ │    │ Neighbors of A: [B]
    │ B   │✓│ │✓│    │ Neighbors of B: [A, C]
    │ C   │ │✓│ │    │ Neighbors of C: [B]
    └─────────────────┘
    
    Overlap Matrix
    ┌──────────────────────┐
    │     │A│B│C│         │
    │ ────────────────────│
    │ A   │-│YES│NO│      │
    │ B   │YES│-│NO│      │
    │ C   │NO│NO│-│       │
    └──────────────────────┘
    
    Direction Matrix
    ┌──────────────────────────┐
    │     │A→B│A→C│B→A│B→C│C→A│C→B│
    │ ───────────────────────│
    │     │ahead│behind│behind│ahead│ahead│behind│
    └──────────────────────────┘
```

---

## 5. Feature Matching Process

```
Person Exiting Camera_A
    │
    ├─ Local Person ID: 1
    ├─ Re-ID Features: [0.23, 0.45, ..., 0.78] (256-dim)
    └─ Bounding Box: (100, 100, 50, 100)

             ▼

┌──────────────────────────────────────┐
│ CrossCameraReID.match_person...()    │
├──────────────────────────────────────┤
│ 1. Get neighbors of Camera_A:        │
│    → [Camera_B]                      │
│                                      │
│ 2. Get active persons in Camera_B:   │
│    → Person_1: features=[...]        │
│    → Person_2: features=[...]        │
│    → Person_3: features=[...]        │
│                                      │
│ 3. Compare features (L2 distance):   │
│    ┌────────────────────────────┐   │
│    │ Person_1:                  │   │
│    │ dist = √Σ(a_i - b_i)²      │   │
│    │ dist = 0.15 < 0.4? YES ✓   │   │
│    │ confidence = 1 - 0.15 = 0.85│   │
│    │                            │   │
│    │ Person_2:                  │   │
│    │ dist = 0.32 < 0.4? YES ✓   │   │
│    │ confidence = 1 - 0.32 = 0.68│   │
│    │                            │   │
│    │ Person_3:                  │   │
│    │ dist = 0.52 > 0.4? NO ✗    │   │
│    │ confidence = 0.0            │   │
│    └────────────────────────────┘   │
│                                      │
│ 4. Pick best match:                  │
│    → Person_1 (distance 0.15)        │
│                                      │
│ 5. Spatial consistency check:        │
│    ┌────────────────────────────┐   │
│    │ Direction A→B: "ahead"     │   │
│    │ Person movement: ✓         │   │
│    │ Spatial valid: YES          │   │
│    └────────────────────────────┘   │
└────────────────────────────────────┘
             │
             ▼
    MATCH FOUND!
    Camera_B Person_1 = Camera_A Person_1
    
    Return: ("Camera_B", 1, 0.85)
```

---

## 6. Identity Propagation Flow

```
Time 10s: Face Recognized in Camera_B

┌──────────────────────────────┐
│ Recognition Worker Thread    │
│ (async DeepFace matching)    │
├──────────────────────────────┤
│                              │
│ Face crop detected           │
│ ↓                            │
│ Compare with Faces_db/       │
│ User_1/, User_2/, ...        │
│ ↓                            │
│ MATCH: User_5 (conf: 0.95)   │
│ ↓                            │
│ Update identified_faces[]    │
│ face_obj.name = "User_5"     │
│ ↓                            │
│ Link to GlobalPersonTracker  │
│ global_person_id = 1         │
│ ↓                            │
│ Propagate identification     │
│                              │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ CrossCameraReID.propagate_...()      │
├──────────────────────────────────────┤
│ Input: global_person_id=1,           │
│        name="User_5",                │
│        confidence=0.95,              │
│        camera="Camera_B"             │
│                                      │
│ Update GlobalPersonTracker:          │
│ global_person[1].name = "User_5"     │
│ global_person[1].confidence = 0.95   │
│                                      │
│ Print: "User_5 identified in Camera_B"
│        "→ Propagating to: [Camera_A, │
│                            Camera_C]"│
└──────────────┬───────────────────────┘
               │
      ┌────────┼────────┐
      ▼        ▼        ▼
   Camera_A Camera_B Camera_C
      │        │        │
   Display  Display  Display
   "User_5" "User_5" "User_5"
   
   Even if Camera_A doesn't see person,
   it knows identity from Camera_B's recognition!
```

---

## 7. State Machine: Person Lifecycle

```
                    CREATE
                      │
                      ▼
            ┌──────────────────┐
            │ UNKNOWN          │
            │ name = "Unknown" │
            │ conf = 0.0       │
            └────────┬─────────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
    (face match)  (new user)  (other)
         │           │           │
         ▼           ▼           ▼
    ┌────────────────────┐   (no change)
    │ IDENTIFIED         │
    │ name = "User_X"    │
    │ conf = 0.95        │
    │                    │
    │ PROPAGATED TO:     │
    │  • Camera_A        │
    │  • Camera_B        │
    │  • Camera_C        │
    └────────┬───────────┘
             │
    (no sightings for 30s)
             │
             ▼
    ┌──────────────────┐
    │ INACTIVE         │
    │ (cleaned up)     │
    │ Removed from     │
    │ system           │
    └──────────────────┘
```

---

## 8. System Performance Profile

```
Operation                  Time          Memory
─────────────────────────────────────────────────
Create global person       ~0.1ms        ~2KB
Link to camera             ~0.2ms        ~1KB
Extract Re-ID features     ~50ms         ~1KB
Match person L2 distance   ~0.05ms       0KB
Propagate identification   ~0.5ms        0KB

Per Person:
  Features (256-dim)                     ~1KB
  Global Person object                   ~2KB
  Total                                  ~3KB

System Scaling (1000 persons):
  Total memory usage                     ~3MB
  Match operation                        ~100ms
  Propagation operation                  ~10ms
```

---

## 9. Configuration & Tuning

```
Feature Distance Threshold
┌────────────────┬──────────────┬──────────────┐
│   Threshold    │ Characteristics│  Use Case   │
├────────────────┼──────────────┼──────────────┤
│ 0.3 (strict)   │ High precision│ Crowded     │
│                │ Low recall    │ scenes      │
├────────────────┼──────────────┼──────────────┤
│ 0.4 (balanced) │ Good balance  │ Standard    │
│                │ Recommended   │ (DEFAULT)   │
├────────────────┼──────────────┼──────────────┤
│ 0.5 (lenient)  │ More matches  │ Sparse      │
│                │ Higher FP     │ scenes      │
└────────────────┴──────────────┴──────────────┘

Default configuration in code:
┌────────────────────────────────────────────┐
│ self.cross_camera_reid =                   │
│     CrossCameraReID(                       │
│         global_tracker,                    │
│         camera_graph,                      │
│         feature_distance_threshold=0.4,   │
│         temporal_threshold=10.0            │
│     )                                      │
└────────────────────────────────────────────┘
```

---

This architecture enables:
✅ **Spatial Awareness** - Cameras understand their relationships
✅ **Global Identity** - Single person ID across all cameras
✅ **Automatic Linking** - Feature + spatial matching
✅ **Identity Propagation** - Identification reaches all cameras
✅ **Trajectory Tracking** - Know exact movement path
