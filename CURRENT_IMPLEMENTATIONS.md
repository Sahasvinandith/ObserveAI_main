# Current Implementations - ObserveAI Project

## Overview
ObserveAI is a multi-camera person identification and tracking system built with Python, PyQt6, and various AI/ML libraries. The system processes video feeds from multiple cameras to detect, track, and identify persons across camera views.

## Core Components

### 1. DetectionSystem (DataModel/DetectionSystem.py)
**Purpose**: Main AI processing engine for individual cameras.

**Key Features**:
- **Person Detection**: Uses YOLOv8n model (`yolov8n.pt`) for real-time person detection
- **Face Detection**: Uses YOLOv11n-face model (`yolov11n-face.pt`) for face detection
- **Tracking**: Implements DeepSORT tracker for maintaining person identities within camera view
- **Re-Identification**: Uses ResNet-50 based ReIDModel for extracting feature vectors from person crops
- **Face Recognition**: Integrates DeepFace with ArcFace model for face identification
- **Multi-threading**: Separate threads for camera capture, processing, display, recognition, and database updates

**Key Classes**:
- `DetectionSystem`: Main class handling all AI processing
- `Person`: Represents a tracked person with position, faces, and global ID
- `Ai_System_thread`: Function to create and start detection system instances

**Configuration Parameters**:
- Frame skip interval: 3 (process every 3rd frame)
- GUI FPS limit: 15
- Confidence thresholds: Person (0.5), Face recognition (0.6)
- Minimum sizes: Person (50x100), Face (80x80)

### 2. GlobalPersonTracker (DataModel/GlobalPersonTracker.py)
**Purpose**: Cross-camera person tracking and identification consolidation.

**Key Features**:
- **Feature Matching**: Uses cosine distance on Re-ID feature vectors for matching persons across cameras
- **Spatial Awareness**: Incorporates camera positions, rotations, and field-of-view for improved matching
- **Position Estimation**: Estimates real-world positions using camera calibration and triangulation
- **Identity Consolidation**: Maintains best face recognition results across all camera views
- **Thread-safe**: Uses locks for concurrent access from multiple camera threads

**Key Classes**:
- `GlobalPerson`: Represents a person tracked across multiple cameras
- `LocalTrack`: Tracks person in a specific camera
- `CameraInfo`: Stores spatial information for each camera
- `GlobalPersonTracker`: Main tracker class

**Algorithms**:
- Combined scoring: Re-ID distance (70%) + Spatial distance (30%)
- Position estimation: Single-camera depth estimation or stereo triangulation
- Exponential smoothing for position stability

### 3. Face Recognition System
**Components**:
- **EmbeddingCache** (DataModel/EmbeddingCache.py): Caches averaged face embeddings per user using ArcFace
- **face_detection.py**: Handles face detection, quality assessment, and Kalman filtering for tracking

**Features**:
- Database storage in `Faces_db/` with user folders
- Quality-based face saving (threshold: 100)
- Automatic user folder merging on identity changes
- Thread-safe embedding cache

### 4. Re-Identification Model (DataModel/Reid_model.py)
**Purpose**: Extract feature vectors for person re-identification.

**Implementation**:
- Pre-trained ResNet-50 with final layer removed
- Input preprocessing: Resize to 256x128, normalize with ImageNet stats
- Feature extraction for person crops
- Used for cross-camera matching in GlobalPersonTracker

### 5. Face Management (DataModel/Face.py)
**Purpose**: Represents individual face detections with identity verification.

**Key Features**:
- Identity history tracking
- Confidence averaging
- Identity locking after consistent matches
- Position tracking with Kalman filtering
- Unknown count for new user creation

**Identity Verification Logic**:
- Requires N consistent matches before locking identity
- Change margin prevents identity flipping
- Tracks consecutive unknown results

### 6. Settings Management (DataModel/SettingsManager.py)
**Purpose**: Centralized configuration with JSON persistence.

**Key Settings Categories**:
- Global Tracker: feature_threshold, reid_weight, spatial_weight
- Face Quality: min_quality_threshold, max_faces_per_user
- Identity Verification: confirm_frames, confidence_threshold, change_margin
- Face Validation: min_face_width, min_face_height, min_face_confidence

**Features**:
- Default values for all settings
- Runtime modification and persistence
- Type-safe access methods

### 7. User Interface Components
**MainWindow** (main/MainWindow.py):
- PyQt6-based GUI with stacked widget interface
- Camera management and visualization
- Floor map with person position dots
- Pop-out windows for individual components
- AI system integration and thread management

**Camera Components**:
- `Camera_widget.py`: Individual camera feed display with person annotations
- `Camera_list_widget.py`: Camera list management
- `Grid_feed_widget.py`: Grid layout for multiple feeds
- `Camera_worker.py`: Background camera capture and processing

### 8. Database and Assets
**Faces_db/**: Directory structure with user folders containing face images
**maps/**: JSON files for camera calibration and floor maps
**UIs/**: PyQt6 UI files and compiled Python interfaces

## Data Flow

1. **Camera Input**: Video frames captured from RTSP/USB cameras
2. **Detection**: YOLO models detect persons and faces in frames
3. **Tracking**: DeepSORT maintains local IDs within each camera
4. **Feature Extraction**: ReID model extracts feature vectors from person crops
5. **Global Matching**: GlobalPersonTracker matches features across cameras
6. **Face Recognition**: DeepFace identifies faces against cached embeddings
7. **Position Estimation**: Camera calibration used to estimate real-world positions
8. **UI Update**: Processed data displayed in GUI with person dots on floor map

## Key Technologies

- **Computer Vision**: OpenCV, YOLO, DeepSORT
- **Deep Learning**: PyTorch, ResNet-50, ArcFace
- **Face Recognition**: DeepFace library
- **GUI**: PyQt6
- **Threading**: Python threading for concurrent processing
- **Data Storage**: File-based with JSON for maps, images for faces

## Performance Optimizations

- Frame skipping (every 3rd frame)
- Asynchronous processing queues
- Embedding caching for fast face recognition
- Kalman filtering for face tracking
- Exponential smoothing for position stability

## Current Limitations

- Requires camera calibration for accurate positioning
- Face recognition depends on lighting and angle quality
- Re-ID matching may fail with significant appearance changes
- Real-time processing limited by hardware capabilities

## Future Enhancements

- Multi-person tracking improvements
- Advanced pose estimation
- Behavior analysis
- Integration with additional sensors
- Cloud-based processing options</content>
<parameter name="filePath">/home/sahas/Projects/ObserveAI_main/CURRENT_IMPLEMENTATIONS.md