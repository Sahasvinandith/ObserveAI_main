"""
GlobalPersonTracker - Spatial-Aware Cross-Camera Person Tracking

This module provides a reliable system for tracking persons across
multiple cameras using Re-ID feature matching combined with spatial awareness.

Key Principles:
- Feature matching is the PRIMARY mechanism (proven reliable)
- Spatial awareness ENHANCES matching (camera positions + bbox angles)
- Simple data structures (easy to debug)
- Graceful degradation (works even with missing features or spatial data)
"""

import numpy as np
import math
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple, Callable


@dataclass
class CameraInfo:
    """Stores camera spatial information for cross-camera tracking"""
    name: str
    position: Tuple[float, float]  # (x, y) on floor plan
    rotation: float  # Degrees, 0 = pointing right, increases counter-clockwise
    fov: float = 70.0  # Field of view in degrees
    view_range: float = 200.0  # Max effective detection range in floor plan units
    frame_width: int = 1920  # Frame width for bbox normalization
    frame_height: int = 1080  # Frame height


@dataclass
class LocalTrack:
    """Represents a person's track in a specific camera"""
    camera_name: str
    local_person_id: int  # DeepSORT track ID in this camera
    feature_vector: Optional[np.ndarray] = None
    color_hist: Optional[np.ndarray] = None
    last_seen: float = field(default_factory=time.time)
    bbox: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h)
    
    def update(self, feature_vector: Optional[np.ndarray] = None, 
               color_hist: Optional[np.ndarray] = None,
               bbox: Optional[Tuple[int, int, int, int]] = None):
        """Update track information. Color histogram is blended (EMA) rather than replaced."""
        if feature_vector is not None:
            if self.feature_vector is None:
                self.feature_vector = feature_vector.copy()
            else:
                # EMA blend for Re-ID embeddings (alpha=0.15)
                # We blend then re-normalize to keep the vector on the unit hypersphere
                alpha = 0.15
                blended = (1.0 - alpha) * self.feature_vector + alpha * feature_vector
                self.feature_vector = blended / (np.linalg.norm(blended) + 1e-8)
        if color_hist is not None:
            if self.color_hist is None:
                # First observation — accept it directly
                self.color_hist = color_hist.copy()
            else:
                # Exponential moving average: new frames have low weight (0.15)
                # so ~20 stable frames needed to fully shift the histogram.
                # Side-facing or partial frames can only nudge it slightly.
                alpha = 0.15
                self.color_hist = (1.0 - alpha) * self.color_hist + alpha * color_hist
        if bbox is not None:
            self.bbox = bbox
        self.last_seen = time.time()


@dataclass
class GlobalPerson:
    """Represents a person tracked across multiple cameras"""
    global_id: int
    feature_vector: Optional[np.ndarray] = None  # Most recent/best features
    color_hist: Optional[np.ndarray] = None
    color_hist_count: int = 0  # How many observations have been blended in
    camera_tracks: Dict[str, LocalTrack] = field(default_factory=dict)
    
    # Face recognition results (legacy fields kept for compatibility)
    name: str = "Unknown"
    confidence: float = 0.0
    
    # Consolidated user identity (best match across all cameras)
    local_user_id: str = "Unknown"  # The winner ID (e.g., "User_3")
    best_confidence: float = 1.0    # Lower is better (distance)
    
    # Lifecycle tracking
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    
    # Position smoothing (prevents dot from jumping when estimation method changes)
    smoothed_position: Optional[Tuple[float, float]] = None
    last_position_camera: Optional[str] = None
    
    def update_face_identity(self, user_id: str, confidence: float) -> tuple:
        """
        Update face identity for this global person.
        Keeps the best match (lowest confidence/distance).
        
        Returns: Tuple of (winner_user_id, old_user_id_if_changed or None)
                 old_user_id is set when identity CHANGES to a different user
        """
        if user_id in ("Unknown", "Scanning..."):
            return (self.local_user_id, None)
        
        # Log the incoming identity report
        print(f"[ID REPORT] Global {self.global_id}: Received '{user_id}' (conf={confidence:.3f}), current='{self.local_user_id}' (best={self.best_confidence:.3f})")
        
        old_id_for_merge = None  # Track if we need to merge
        
        # If this is a better match (lower distance), update
        if confidence < self.best_confidence:
            old_id = self.local_user_id
            old_conf = self.best_confidence
            
            self.local_user_id = user_id
            self.best_confidence = confidence
            # Also update legacy fields
            self.name = user_id
            self.confidence = confidence
            
            # Log the identity change - mark for merge if changing to different user
            if old_id != "Unknown" and old_id != user_id:
                print(f"[ID CHANGE] Global {self.global_id}: SWITCHED from '{old_id}' ({old_conf:.3f}) to '{user_id}' ({confidence:.3f}) - lower distance wins!")
                old_id_for_merge = old_id  # Return old_id so tracker can merge folders
            else:
                print(f"[ID SET] Global {self.global_id}: Set to '{user_id}' ({confidence:.3f})")
        else:
            # Log when incoming identity was rejected
            if user_id != self.local_user_id:
                print(f"[ID REJECT] Global {self.global_id}: Rejected '{user_id}' ({confidence:.3f}) - current '{self.local_user_id}' ({self.best_confidence:.3f}) is better")
        
        return (self.local_user_id, old_id_for_merge)
    
    def _get_dominant_camera(self) -> Optional[str]:
        """
        Determines the single 'best' camera tracking this person right now.
        Used to prevent a single global person from appearing in multiple
        locations on the map at the same time.
        
        Logic:
        1. Only consider cameras where the person was seen in the last 2 seconds.
        2. Filter out cameras with no bounding box.
        3. Pick the camera where the person's bounding box area is the largest 
           (usually implies they are closer/clearer in that camera).
        """
        current_time = time.time()
        active_tracks = []
        
        for cam_name, track in self.camera_tracks.items():
            if current_time - track.last_seen < 2.0 and track.bbox is not None:
                active_tracks.append((cam_name, track))
                
        if not active_tracks:
            return None
            
        # Sort by bounding box area (width * height), largest first
        active_tracks.sort(key=lambda item: item[1].bbox[2] * item[1].bbox[3], reverse=True)
        return active_tracks[0][0]

    
    def update_from_camera(self, camera_name: str, local_id: int,
                          feature_vector: Optional[np.ndarray] = None,
                          color_hist: Optional[np.ndarray] = None,
                          bbox: Optional[Tuple[int, int, int, int]] = None):
        """Update or create a local track for this camera"""
        if camera_name in self.camera_tracks:
            # Update existing track
            self.camera_tracks[camera_name].update(feature_vector, color_hist, bbox)
        else:
            # Create new track
            self.camera_tracks[camera_name] = LocalTrack(
                camera_name=camera_name,
                local_person_id=local_id,
                feature_vector=feature_vector,
                color_hist=color_hist,
                bbox=bbox
            )
        
        # Update global features if provided (using EMA for stability)
        if feature_vector is not None:
            if self.feature_vector is None:
                self.feature_vector = feature_vector.copy()
            else:
                # Decaying alpha for global Re-ID signature
                alpha = max(0.10, 1.0 / (self.color_hist_count + 1))
                blended = (1.0 - alpha) * self.feature_vector + alpha * feature_vector
                self.feature_vector = blended / (np.linalg.norm(blended) + 1e-8)
        if color_hist is not None:
            if self.color_hist is None:
                # Very first observation for this global person
                self.color_hist = color_hist.copy()
                self.color_hist_count = 1
            else:
                # EMA blend: weight new observation less as count grows,
                # settling at alpha=0.10 after ~10 observations.
                # This means brief side-angle frames barely shift the profile.
                alpha = max(0.10, 1.0 / (self.color_hist_count + 1))
                self.color_hist = (1.0 - alpha) * self.color_hist + alpha * color_hist
                self.color_hist_count += 1
        
        self.last_seen = time.time()
    
    def get_cameras_seen_in(self) -> List[str]:
        """Get list of cameras where this person has been seen"""
        return list(self.camera_tracks.keys())
    
    def is_in_camera(self, camera_name: str) -> bool:
        """Check if person is currently tracked in a camera"""
        return camera_name in self.camera_tracks



class GlobalPersonTracker:
    """
    Tracks persons across multiple cameras using Re-ID feature matching
    enhanced with spatial awareness from camera positions and bbox angles.
    
    Features:
    - Cosine distance for Re-ID feature matching
    - Spatial distance based on camera positions and viewing angles
    - Combined scoring with configurable weights
    - Position callback for floor map visualization
    - Thread-safe for multi-camera use
    """
    
    def __init__(self, feature_threshold: float = 0.4, 
                 reid_weight: float = 0.5, 
                 color_weight: float = 0.3,
                 spatial_weight: float = 0.2,
                 position_callback: Optional[Callable] = None,
                 pixels_per_meter: float = 30.0):
        """
        Initialize the global person tracker with spatial awareness.
        
        Args:
            feature_threshold: Maximum combined distance for match (0.0-2.0)
                              Lower = stricter matching
                              Recommended: 0.4-0.6
            reid_weight: Weight for Re-ID feature matching (default 0.5)
            color_weight: Weight for Color Histogram matching (default 0.3)
            spatial_weight: Weight for spatial matching (default 0.2)
            position_callback: Optional callback(global_id, x, y, camera_name) 
                              for floor map visualization
            pixels_per_meter: Scale factor for the map (how many pixels = 1 meter)
                             Used to convert between real-world distances and map coordinates
        """
        self.global_persons: Dict[int, GlobalPerson] = {}
        self.next_id: int = 1
        self.feature_threshold: float = feature_threshold
        self.reid_weight: float = reid_weight
        self.color_weight: float = color_weight
        self.spatial_weight: float = spatial_weight
        self.lock = threading.Lock()
        
        # Map scale: how many pixels on the map = 1 meter in real life
        self.pixels_per_meter: float = pixels_per_meter
        
        # Camera spatial data
        self.cameras: Dict[str, CameraInfo] = {}
        
        # Callback for position updates (for floor map visualization)
        self.position_callback = position_callback
        
        # Position smoothing factor (0 = no smoothing, 1 = never update)
        self.position_smoothing: float = 0.4
        
        print(f"[GLOBAL TRACKER] Initialized with threshold={feature_threshold}, "
              f"weights: reid={reid_weight}, spatial={spatial_weight}, "
              f"pixels_per_meter={pixels_per_meter}")
    
    # =========================================================================
    # Face Identity Consolidation
    # =========================================================================
    
    def update_face_identity(self, global_id: int, user_id: str, confidence: float) -> str:
        """
        Update face identity for a global person. If multiple cameras report
        different IDs for the same global person, keep the best (lowest distance).
        
        When identity CHANGES (e.g., User_2 -> User_1), automatically merges
        the old user folder into the new user folder.
        
        Args:
            global_id: The global person ID
            user_id: The local user ID from face recognition (e.g., "User_3")
            confidence: The match confidence/distance (lower = better)
            
        Returns:
            The consolidated (winner) user ID for this global person
        """
        with self.lock:
            if global_id not in self.global_persons:
                return user_id  # No global person, return as-is
            
            person = self.global_persons[global_id]
            winner_id, old_id_to_merge = person.update_face_identity(user_id, confidence)
            
            # If identity changed, merge the old user folder into the winner
            if old_id_to_merge is not None:
                print(f"[MERGE TRIGGER] Identity changed from '{old_id_to_merge}' to '{winner_id}', merging folders...")
                # Import and get embedding cache singleton
                try:
                    from DataModel.EmbeddingCache import get_embedding_cache
                    cache = get_embedding_cache()
                    # Merge old folder INTO winner folder (old folder will be deleted)
                    cache.merge_users(old_id_to_merge, winner_id)
                except Exception as e:
                    print(f"[MERGE ERROR] Failed to merge folders: {e}")
            
            return winner_id
    
    def get_consolidated_name(self, global_id: int) -> str:
        """
        Get the consolidated/best name for a global person.
        
        Returns:
            The best user ID for this global person, or "Unknown" if not found
        """
        with self.lock:
            if global_id not in self.global_persons:
                return "Unknown"
            return self.global_persons[global_id].local_user_id
    
    def get_person_identity(self, global_id: int) -> tuple:
        """
        Get the full identity info for a global person.
        Used for cross-camera identity inheritance.
        
        Returns:
            Tuple of (user_id, confidence) or ("Unknown", 1.0) if not found/identified
        """
        with self.lock:
            if global_id not in self.global_persons:
                return ("Unknown", 1.0)
            person = self.global_persons[global_id]
            if person.local_user_id in ("Unknown", "Scanning..."):
                return ("Unknown", 1.0)
            return (person.local_user_id, person.best_confidence)
    
    # =========================================================================
    # Camera Registration
    # =========================================================================
    
    def register_camera(self, name: str, position: Tuple[float, float], 
                       rotation: float, fov: float = 70.0, view_range: float = 200.0,
                       frame_width: int = 1920, frame_height: int = 1080):
        """
        Register a camera with its spatial information.
        
        Args:
            name: Camera name (must match name used in create_or_update)
            position: (x, y) position on floor plan
            rotation: Camera rotation in degrees (0 = pointing right)
            fov: Field of view in degrees (default 70)
            view_range: Max effective detection range in floor plan units (default 200)
            frame_width: Frame width in pixels for bbox normalization
            frame_height: Frame height in pixels
        """
        with self.lock:
            self.cameras[name] = CameraInfo(
                name=name,
                position=position,
                rotation=rotation,
                fov=fov,
                view_range=view_range,
                frame_width=frame_width,
                frame_height=frame_height
            )
            print(f"[GLOBAL TRACKER] Registered camera '{name}' at pos={position}, rot={rotation}°, fov={fov}°, range={view_range}")
    
    def update_camera_params(self, name: str, fov: Optional[float] = None, range_val: Optional[float] = None):
        """
        Update a camera's FOV or view range at runtime.
        """
        with self.lock:
            if name in self.cameras:
                if fov is not None:
                    self.cameras[name].fov = fov
                if range_val is not None:
                    self.cameras[name].view_range = range_val
                print(f"[GLOBAL TRACKER] Updated camera '{name}': fov={self.cameras[name].fov}, range={self.cameras[name].view_range}")
    
    def update_camera_frame_size(self, name: str, width: int, height: int):
        """Update frame dimensions for a camera (call when actual frame size is known)"""
        with self.lock:
            if name in self.cameras:
                self.cameras[name].frame_width = width
                self.cameras[name].frame_height = height
    
    # =========================================================================
    # Spatial Calculations
    # =========================================================================
    
    def _bbox_to_world_angle(self, camera_name: str, 
                             bbox: Tuple[int, int, int, int]) -> Optional[float]:
        """
        Convert bbox center to world angle direction.
        
        Logic:
        1. Get bbox center_x in frame
        2. Normalize to [-0.5, 0.5] (center of frame = 0)
        3. Multiply by FOV to get offset angle
        4. Add camera rotation to get world angle
        
        Args:
            camera_name: Name of the camera
            bbox: (x, y, w, h) bounding box
            
        Returns:
            Angle in degrees (0-360) or None if camera not registered
        """
        if camera_name not in self.cameras:
            return None
        
        camera = self.cameras[camera_name]
        x, y, w, h = bbox
        
        # Calculate bbox center x position
        center_x = x + w / 2
        
        # Normalize to [-0.5, 0.5] where 0 = frame center
        normalized_x = (center_x / camera.frame_width) - 0.5
        
        # Convert to angle offset within FOV
        # Left edge = -FOV/2, center = 0, right edge = +FOV/2
        angle_offset = normalized_x * camera.fov
        
        # Add camera rotation to get world angle
        world_angle = camera.rotation + angle_offset
        
        # Normalize to 0-360
        world_angle = world_angle % 360
        
        return world_angle
    
    def _estimate_person_position(self, camera_name: str, 
                                   bbox: Tuple[int, int, int, int],
                                   distance_estimate: Optional[float] = None,
                                   last_known_pos: Optional[Tuple[float, float]] = None) -> Optional[Tuple[float, float]]:
        """
        Estimate person's world position based on camera location and viewing angle.
        
        This is an approximation that projects the person along the viewing ray.
        Uses the camera's configured view_range to scale the distance estimate.
        If last_known_pos is provided, it maintains the previous depth to prevent jumping.
        
        Args:
            camera_name: Name of the camera
            bbox: (x, y, w, h) bounding box
            distance_estimate: Override distance from camera. If None, uses half the camera's view_range.
            last_known_pos: (x, y) previous position to estimate depth.
            
        Returns:
            (x, y) estimated position on floor plan, or None
        """
        if camera_name not in self.cameras:
            return None
        
        camera = self.cameras[camera_name]
        
        if distance_estimate is None:
            if last_known_pos is not None:
                # Calculate distance from camera to last known position
                dx = last_known_pos[0] - camera.position[0]
                dy = last_known_pos[1] - camera.position[1]
                dist = math.hypot(dx, dy)
                # Keep distance within reasonable bounds (10% to 100% of view range)
                distance_estimate = max(camera.view_range * 0.1, min(dist, camera.view_range))
            else:
                # Use Bounding Box feet position to estimate depth computationally
                x, y, w, h = bbox
                bottom_y = y + h
                
                # Normalize to 0.0 (top) to 1.0 (bottom of frame)
                frame_height = getattr(camera, 'frame_height', 640)
                normalized_y = min(1.0, max(0.0, bottom_y / frame_height))
                
                # Linear approximation of depth perspective:
                # Feet near bottom of frame (1.0) = 10% of view range (very close)
                # Feet at top of frame (0.0) = 100% of view range (very far)
                distance_factor = 1.0 - (normalized_y * 0.9)
                distance_estimate = camera.view_range * distance_factor
                
                # Floor constraint so they don't appear *inside* the camera
                distance_estimate = max(20.0, distance_estimate)
        
        world_angle = self._bbox_to_world_angle(camera_name, bbox)
        
        if world_angle is None:
            return None
        
        # Convert angle to radians
        angle_rad = math.radians(world_angle)
        
        # Project from camera position along the viewing angle
        est_x = camera.position[0] + distance_estimate * math.cos(angle_rad)
        est_y = camera.position[1] + distance_estimate * math.sin(angle_rad)
        
        return (est_x, est_y)
    
    def _triangulate_position(self, cam1_name: str, bbox1: Tuple[int, int, int, int],
                               cam2_name: str, bbox2: Tuple[int, int, int, int]) -> Optional[Tuple[float, float]]:
        """
        Stereo triangulation: find a person's floor position using 2 camera rays.
        
        Each camera gives us a ray (camera position + world angle from bbox).
        The intersection of these two 2D rays is the person's actual position.
        
        Uses Cramer's rule on the system:
            P1 + t1 * D1 = P2 + t2 * D2
        
        Returns:
            (x, y) triangulated position, or None if rays are parallel/invalid
        """
        if cam1_name not in self.cameras or cam2_name not in self.cameras:
            return None
        
        cam1 = self.cameras[cam1_name]
        cam2 = self.cameras[cam2_name]
        
        # Get world angles for person in each camera
        angle1 = self._bbox_to_world_angle(cam1_name, bbox1)
        angle2 = self._bbox_to_world_angle(cam2_name, bbox2)
        
        if angle1 is None or angle2 is None:
            return None
        
        # Ray directions
        theta1 = math.radians(angle1)
        theta2 = math.radians(angle2)
        
        d1x, d1y = math.cos(theta1), math.sin(theta1)
        d2x, d2y = math.cos(theta2), math.sin(theta2)
        
        # Camera positions
        p1x, p1y = cam1.position
        p2x, p2y = cam2.position
        
        # Solve using Cramer's rule:
        # t1 * d1x - t2 * d2x = p2x - p1x
        # t1 * d1y - t2 * d2y = p2y - p1y
        det = d1x * (-d2y) - (-d2x) * d1y  # = sin(theta1 - theta2)
        
        # If det ≈ 0, rays are nearly parallel — can't triangulate
        if abs(det) < 0.01:
            print(f"[STEREO] REJECT parallel rays: {cam1_name}({angle1:.1f}°) vs {cam2_name}({angle2:.1f}°), det={det:.4f}")
            return None
        
        dx = p2x - p1x
        dy = p2y - p1y
        
        t1 = (dx * (-d2y) - (-d2x) * dy) / det
        t2 = (d1x * dy - d1y * dx) / det
        
        # Both t-values must be positive (intersection in FRONT of both cameras)
        if t1 < 0 or t2 < 0:
            print(f"[STEREO] REJECT behind camera: {cam1_name}({angle1:.1f}°) t1={t1:.1f}, {cam2_name}({angle2:.1f}°) t2={t2:.1f}")
            return None
        
        # Compute intersection point using ray 1
        ix = p1x + t1 * d1x
        iy = p1y + t1 * d1y
        
        # Sanity check: intersection shouldn't be absurdly far from either camera
        # Use a generous limit — 5x view_range — to avoid rejecting valid positions
        max_range = max(cam1.view_range, cam2.view_range) * 5.0
        if t1 > max_range or t2 > max_range:
            print(f"[STEREO] REJECT too far: t1={t1:.1f}, t2={t2:.1f}, max_range={max_range:.1f}")
            return None
        
        return (ix, iy)
    
    def _get_best_position(self, person: 'GlobalPerson', camera_name: str,
                            bbox: Tuple[int, int, int, int]) -> Optional[Tuple[float, float]]:
        """
        Get the best position estimate for a person.
        
        Strategy:
        1. If 2+ cameras are actively tracking this person, use stereo triangulation
           (pick the two most recent active cameras for best accuracy).
        2. If only 1 camera, fall back to single-camera depth estimate.
        3. Apply exponential smoothing to prevent sudden dot jumps.
        
        Returns:
            (x, y) smoothed estimated floor position, or None
        """
        current_time = time.time()
        ACTIVE_THRESHOLD = 2.0  # seconds
        
        # Gather all active camera tracks with valid bboxes
        active_tracks = []
        for cam_name, track in person.camera_tracks.items():
            if current_time - track.last_seen < ACTIVE_THRESHOLD and track.bbox is not None:
                active_tracks.append((cam_name, track))
        
        # Also include the current update (it may not be in camera_tracks yet)
        current_in_list = any(c == camera_name for c, _ in active_tracks)
        if not current_in_list and camera_name in self.cameras:
            active_tracks.append((camera_name, LocalTrack(
                camera_name=camera_name, local_person_id=0,
                bbox=bbox, last_seen=current_time
            )))
        
        raw_position = None
        
        # STEREO: If 2+ cameras, triangulate using the two with most recent data
        if len(active_tracks) >= 2:
            active_tracks.sort(key=lambda item: item[1].last_seen, reverse=True)
            
            cam1_name, track1 = active_tracks[0]
            cam2_name, track2 = active_tracks[1]
            
            bbox1 = bbox if cam1_name == camera_name else track1.bbox
            bbox2 = bbox if cam2_name == camera_name else track2.bbox
            
            raw_position = self._triangulate_position(cam1_name, bbox1, cam2_name, bbox2)
        
        # FALLBACK: Single-camera estimate
        if raw_position is None:
            raw_position = self._estimate_person_position(
                camera_name, bbox, last_known_pos=person.smoothed_position
            )
        
        if raw_position is None:
            return None
        
        # Apply exponential smoothing to prevent sudden jumps
        if person.smoothed_position is not None:
            alpha = self.position_smoothing  # 0.4 = blend 40% old + 60% new
            sx = alpha * person.smoothed_position[0] + (1 - alpha) * raw_position[0]
            sy = alpha * person.smoothed_position[1] + (1 - alpha) * raw_position[1]
            smoothed = (sx, sy)
        else:
            # First position — no smoothing, place immediately
            smoothed = raw_position
        
        # Store smoothed position for next frame
        person.smoothed_position = smoothed
        person.last_position_camera = camera_name
        
        return smoothed
    
    
    
    def _spatial_distance(self, camera_name: str, bbox: Tuple[int, int, int, int], person: 'GlobalPerson') -> float:
        """
        Calculate spatial distance score between a new observation and a tracked person.
        
        Leverages the person's precise 2D floor `smoothed_position` (triangulated from 
        multiple cameras) to accurately calculate the physical meter deviation of the 
        new camera's ray from the person's true location.
        
        Returns:
            Distance score (0 = highly confident same location, 1 = physically impossible)
        """
        if camera_name not in self.cameras:
            return 0.5  # Neutral - don't affect matching
            
        map_distance = None
        
        # 1. Primary Method: Pinpoint Ray Deviation using Stereoscopic Known Position
        if getattr(person, 'smoothed_position', None) is not None:
            # Project the new camera's ray until it hits the depth of the known person
            pos1 = self._estimate_person_position(camera_name, bbox, last_known_pos=person.smoothed_position)
            
            if pos1 is not None:
                # The map distance is exactly the chord length (in pixels) between 
                # where the ray *is pointing* and where the person *actually is*.
                map_distance = math.hypot(pos1[0] - person.smoothed_position[0], pos1[1] - person.smoothed_position[1])
                
        # 2. Fallback Method: Single-Camera Depth Approximation (for brand new targets)
        if map_distance is None:
            active_tracks = [t for c, t in person.camera_tracks.items() if c != camera_name and t.bbox is not None]
            if not active_tracks:
                return 0.5
                
            active_tracks.sort(key=lambda t: t.last_seen, reverse=True)
            other_track = active_tracks[0]
            
            pos1 = self._estimate_person_position(camera_name, bbox)
            pos2 = self._estimate_person_position(other_track.camera_name, other_track.bbox)
            
            if pos1 is None or pos2 is None:
                return 0.5
                
            map_distance = math.hypot(pos1[0] - pos2[0], pos1[1] - pos2[1])
        
        # Determine maximum tolerable map distance
        pixels_per_meter = getattr(self, 'pixels_per_meter', 30.0)
        # 3.0 meters deviation bubble gracefully accommodates bbox cropping jitter.
        max_valid_distance = 0.5 * pixels_per_meter
        
        # Normalize distance to 0.0 - 1.0 (Maximum Penalty) score
        spatial_score = min(1.0, map_distance / max_valid_distance)
        
        # Add slight exponential curve to penalize farther distances more aggressively
        spatial_score = spatial_score ** 0.8
        
        return spatial_score
    
    def _color_distance(self, hist1: np.ndarray, hist2: np.ndarray) -> float:
        """
        Calculate Bhattacharyya distance between two normalized histograms.
        
        Returns:
            Distance in range [0, 1] where 0 = identical, 1 = completely disjoint colors
        """
        if hist1 is None or hist2 is None:
            return 0.5
        try:
            import cv2
            dist = cv2.compareHist(hist1, hist2, cv2.HISTCMP_BHATTACHARYYA)
            return float(dist)
        except Exception as e:
            print(f"[GLOBAL TRACKER] Error calculating color distance: {e}")
            return 0.5

    def _cosine_distance(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        Calculate cosine distance between two feature vectors.
        
        Returns:
            Distance in range [0, 2] where 0 = identical, 2 = opposite
        """
        try:
            # Normalize vectors
            vec1_norm = vec1 / (np.linalg.norm(vec1) + 1e-8)
            vec2_norm = vec2 / (np.linalg.norm(vec2) + 1e-8)
            
            # Cosine similarity
            similarity = np.dot(vec1_norm, vec2_norm)
            
            # Convert to distance (0 = same, 2 = opposite)
            distance = 1.0 - similarity
            
            return distance
        except Exception as e:
            print(f"[GLOBAL TRACKER] Error calculating distance: {e}")
            return 999.0  # Return large distance on error
    
    def _find_match_unsafe(self, feature_vector: np.ndarray, 
                           color_hist: Optional[np.ndarray] = None,
                           exclude_camera: Optional[str] = None,
                           current_bbox: Optional[Tuple[int, int, int, int]] = None,
                           current_camera: Optional[str] = None,
                           current_local_id: Optional[int] = None) -> Optional[int]:
        """
        Find a matching global person using combined Re-ID + Spatial scoring.
        
        **IMPORTANT:** This method assumes the lock is already held by the caller!
        Use only from within locked sections.
        """
        if feature_vector is None:
            print(f"[MATCH DEBUG] No feature vector provided, skipping match")
            return None
        
        best_match_id = None
        best_combined_distance = float('inf')
        
        print(f"[MATCH DEBUG] === Searching for match from camera='{current_camera}', exclude='{exclude_camera}' ===")
        print(f"[MATCH DEBUG] Total global persons: {len(self.global_persons)}, threshold: {self.feature_threshold}")
        
        # Note: NO LOCK HERE - assumes caller already has it!
        for global_person in self.global_persons.values():
            gid = global_person.global_id
            cameras_in = list(global_person.camera_tracks.keys())
            identity = global_person.local_user_id
            
            # Skip if person has no features
            if global_person.feature_vector is None:
                print(f"[MATCH DEBUG] G:{gid} ('{identity}') SKIP - no feature vector. cameras={cameras_in}")
                continue
            
            # Skip if person is ACTIVELY tracked in the excluded camera
            # BUT: if the track is stale (person left), OR if it's a DeepSORT fragment
            # in the same spatial position, still consider matching!
            if exclude_camera and global_person.is_in_camera(exclude_camera):
                track = global_person.camera_tracks[exclude_camera]
                track_age = time.time() - track.last_seen
                stale_threshold = 1.0  # seconds - if track older than this, person has left
                
                if track_age < stale_threshold:
                    allowed_fragment = False
                    # Check spatial overlap to detect same-camera fragmented tracking
                    if current_bbox is not None and track.bbox is not None:
                        # Compare bounding box centers
                        cx1 = current_bbox[0] + current_bbox[2] / 2
                        cy1 = current_bbox[1] + current_bbox[3] / 2
                        cx2 = track.bbox[0] + track.bbox[2] / 2
                        cy2 = track.bbox[1] + track.bbox[3] / 2
                        
                        pixel_dist = math.hypot(cx1 - cx2, cy1 - cy2)
                        # Require centers to be highly overlapping (e.g. less than 1.5x width/height)
                        max_allowed_dist = max(current_bbox[2], current_bbox[3]) * 0.5
                        
                        if pixel_dist < max_allowed_dist:
                            print(f"[MATCH DEBUG] G:{gid} ('{identity}') SAME-CAMERA FRAGMENT DETECTED in '{exclude_camera}'! "
                                  f"(dist={pixel_dist:.1f}px < {max_allowed_dist:.1f}px). Circumventing camera exclusion rule.")
                            allowed_fragment = True

                    if not allowed_fragment:
                        print(f"[MATCH DEBUG] G:{gid} ('{identity}') SKIP - distinct person actively tracked in '{exclude_camera}' "
                              f"(track age={track_age:.1f}s < {stale_threshold}s). cameras={cameras_in}")
                        continue
                else:
                    print(f"[MATCH DEBUG] G:{gid} ('{identity}') STALE track in '{exclude_camera}' "
                          f"(track age={track_age:.1f}s >= {stale_threshold}s) - considering for re-match. cameras={cameras_in}")
            
            # Calculate Re-ID distance using a multi-view matching approach
            reid_distance = float('inf')
            
            # 1. Evaluate against the overarching global feature vector
            if global_person.feature_vector is not None:
                reid_distance = self._cosine_distance(feature_vector, global_person.feature_vector)
                
            # 2. Evaluate against every single camera's specific view (LocalTracks)
            for track in global_person.camera_tracks.values():
                if track.feature_vector is not None:
                    track_dist = self._cosine_distance(feature_vector, track.feature_vector)
                    if track_dist < reid_distance:
                        reid_distance = track_dist

            # Calculate Color distance
            color_distance = 0.5
            if color_hist is not None:
                color_distance = float('inf')
                if global_person.color_hist is not None:
                    color_distance = self._color_distance(color_hist, global_person.color_hist)
                for track in global_person.camera_tracks.values():
                    if track.color_hist is not None:
                        track_col_dist = self._color_distance(color_hist, track.color_hist)
                        if track_col_dist < color_distance:
                            color_distance = track_col_dist
                if color_distance == float('inf'): color_distance = 0.5
            
            # Calculate Spatial distance (0-1 range)
            spatial_distance = 0.5  # Default neutral if no spatial data
            
            if current_bbox is not None and current_camera is not None:
                spatial_distance = self._spatial_distance(
                    current_camera, current_bbox, global_person
                )
            
            # Combined weighted score (uniform weights for both same- and cross-camera)
            combined_distance = (self.reid_weight  * reid_distance +
                                 self.color_weight * color_distance +
                                 self.spatial_weight * spatial_distance)
            
            cam_str = ", ".join([f"{c}(L:{t.local_person_id})" for c, t in global_person.camera_tracks.items()])
            loc_str = f"L:{current_local_id}" if current_local_id is not None else "L:?"
            print(f"\n[DEBUG DETAILED LOG] --- MATCHING CHECK ---")
            print(f"[DEBUG] Inspecting detected {loc_str} in camera '{current_camera}' vs existing Global Person G:{gid} ('{identity}') tracked in [{cam_str}]")
            print(f"[DEBUG] Re-ID Matching Score      : {reid_distance:.4f} (Weight: {self.reid_weight})")
            print(f"[DEBUG] Color Matching Score      : {color_distance:.4f} (Weight: {self.color_weight})")
            print(f"[DEBUG] Spatial Matching Score    : {spatial_distance:.4f} (Weight: {self.spatial_weight})")
            print(f"[DEBUG] Final Matching Value      : {combined_distance:.4f} (Threshold: {self.feature_threshold})")
            print(f"[DEBUG] -----------------------------------\n")

            # Track best match
            if combined_distance < best_combined_distance:
                best_combined_distance = combined_distance
                best_match_id = global_person.global_id
        
        print(f"[MATCH DEBUG] Best match evaluated: G:{best_match_id}, final matching value={best_combined_distance:.3f}, threshold={self.feature_threshold}")
        
        # Return match if below threshold
        if best_combined_distance < self.feature_threshold:
            print(f"[MATCH DEBUG] ✓ MATCHED to G:{best_match_id} (Final matching value {best_combined_distance:.3f} is below threshold {self.feature_threshold})")
            return best_match_id
        
        print(f"[MATCH DEBUG] ✗ NO MATCH (Best final matching value {best_combined_distance:.3f} is >= threshold {self.feature_threshold})")
        return None
    
    def update_person_position(self, global_id: int, camera_name: str,
                                bbox: Tuple[int, int, int, int],
                                feature_vector: Optional[np.ndarray] = None,
                                color_hist: Optional[np.ndarray] = None):
        """
        Lightweight position + feature update for an already-matched global person.
        No match search — just updates bbox and fires position callback.
        
        Args:
            global_id: The known global person ID
            camera_name: Camera name
            bbox: Current bounding box (x, y, w, h)
            feature_vector: Optional updated Re-ID features
            color_hist: Optional updated color Histogram
        """
        with self.lock:
            if global_id not in self.global_persons:
                return
            
            person = self.global_persons[global_id]
            
            # Update the camera track's bbox and last_seen
            if camera_name in person.camera_tracks:
                person.camera_tracks[camera_name].bbox = bbox
                person.camera_tracks[camera_name].last_seen = time.time()
                if color_hist is not None:
                    # Use LocalTrack's EMA blend method
                    person.camera_tracks[camera_name].update(color_hist=color_hist)
            
            # Update Re-ID features if provided (using the EMA method on the track)
            if feature_vector is not None:
                if person.feature_vector is None:
                    person.feature_vector = feature_vector.copy()
                else:
                    alpha = max(0.10, 1.0 / (person.color_hist_count + 1))
                    blended = (1.0 - alpha) * person.feature_vector + alpha * feature_vector
                    person.feature_vector = blended / (np.linalg.norm(blended) + 1e-8)
                
                if camera_name in person.camera_tracks:
                    # Update the local camera track's embedding as well
                    person.camera_tracks[camera_name].update(feature_vector=feature_vector)
                    
            if color_hist is not None:
                if person.color_hist is None:
                    person.color_hist = color_hist.copy()
                    person.color_hist_count = 1
                else:
                    alpha = max(0.10, 1.0 / (person.color_hist_count + 1))
                    person.color_hist = (1.0 - alpha) * person.color_hist + alpha * color_hist
                    person.color_hist_count += 1
            
            person.last_seen = time.time()
            person.last_camera = camera_name
            person.last_bbox = bbox
            dominant_camera = person._get_dominant_camera()
            
            # Compute position while we still hold the lock (accesses camera_tracks)
            estimated_pos = None
            if self.position_callback and bbox is not None and camera_name == dominant_camera:
                estimated_pos = self._get_best_position(person, camera_name, bbox)
        
        # Fire position callback outside lock to avoid deadlocks
        if estimated_pos is not None:
            try:
                self.position_callback(global_id, estimated_pos[0], estimated_pos[1], camera_name)
            except Exception as e:
                print(f"[GLOBAL TRACKER] Position callback error: {e}")
    
    def create_or_update(self, camera_name: str, local_id: int,
                        feature_vector: Optional[np.ndarray] = None,
                        color_hist: Optional[np.ndarray] = None,
                        bbox: Optional[Tuple[int, int, int, int]] = None,
                        frame_shape: Optional[Tuple[int, int]] = None) -> int:
        """
        Main entry point: Find matching person or create new one.
        """
        print(f"[GLOBAL TRACKER] === create_or_update called: camera='{camera_name}', local_id={local_id}, has_features={feature_vector is not None} ===")
        
        # Update frame dimensions if provided
        if frame_shape and camera_name in self.cameras:
            self.update_camera_frame_size(camera_name, frame_shape[0], frame_shape[1])
        
        with self.lock:
            # Try to find existing match using features + spatial data (lock already held!)
            matched_id = None
            if feature_vector is not None:
                # Look for match in OTHER cameras (not this one)
                matched_id = self._find_match_unsafe(
                    feature_vector, 
                    color_hist=color_hist,
                    exclude_camera=camera_name,
                    current_bbox=bbox,
                    current_camera=camera_name,
                    current_local_id=local_id
                )
            else:
                print(f"[GLOBAL TRACKER] No features, skipping match search")
            
            if matched_id is not None:
                # Match found - update existing person
                person = self.global_persons[matched_id]
                old_cameras = list(person.camera_tracks.keys())
                person.update_from_camera(camera_name, local_id, feature_vector, color_hist, bbox)
                global_id = matched_id
                print(f"[GLOBAL TRACKER] ✓ Updated person G:{matched_id} in '{camera_name}' (was in cameras: {old_cameras})")
            else:
                # No match - create new person
                new_id = self.next_id
                self.next_id += 1
                
                person = GlobalPerson(global_id=new_id)
                person.update_from_camera(camera_name, local_id, feature_vector, color_hist, bbox)
                self.global_persons[new_id] = person
                global_id = new_id
                print(f"[GLOBAL TRACKER] ✗ Created NEW person G:{new_id} in '{camera_name}' (no match found)")
            
            dominant_camera = person._get_dominant_camera()
            
            # Emit position callback for floor map visualization ONLY if dominant
            if self.position_callback and bbox is not None and camera_name == dominant_camera:
                estimated_pos = self._get_best_position(person, camera_name, bbox)
                if estimated_pos:
                    try:
                        self.position_callback(global_id, estimated_pos[0], estimated_pos[1], camera_name)
                    except Exception as e:
                        print(f"[GLOBAL TRACKER] Position callback error: {e}")
            
            return global_id
    
    def update_identification(self, global_id: int, name: str, confidence: float):
        """
        Update face recognition result for a global person.
        
        Args:
            global_id: Global person ID
            name: Identified name
            confidence: Recognition confidence (0.0-1.0)
        """
        with self.lock:
            if global_id in self.global_persons:
                person = self.global_persons[global_id]
                # Only update if confidence is higher
                if confidence > person.confidence:
                    person.name = name
                    person.confidence = confidence
                    print(f"[GLOBAL TRACKER] Identified person {global_id} as {name} (conf={confidence:.2f})")
    
    def get_person(self, global_id: int) -> Optional[GlobalPerson]:
        """Get a global person by ID"""
        with self.lock:
            return self.global_persons.get(global_id)
    
    def get_all_persons(self) -> List[GlobalPerson]:
        """Get all tracked persons"""
        with self.lock:
            return list(self.global_persons.values())
    
    def get_active_persons(self, timeout: float = 10.0) -> List[GlobalPerson]:
        """
        Get persons seen recently.
        
        Args:
            timeout: Consider person inactive after this many seconds
        """
        current_time = time.time()
        with self.lock:
            return [p for p in self.global_persons.values() 
                   if (current_time - p.last_seen) < timeout]
    
    def cleanup_stale(self, timeout: float = 30.0):
        """
        Remove persons not seen recently.
        
        Args:
            timeout: Remove persons not seen for this many seconds
        """
        current_time = time.time()
        with self.lock:
            stale_ids = [pid for pid, person in self.global_persons.items()
                        if (current_time - person.last_seen) > timeout]
            
            for pid in stale_ids:
                del self.global_persons[pid]
                print(f"[GLOBAL TRACKER] Removed stale person {pid}")
    
    def get_statistics(self) -> dict:
        """Get tracker statistics"""
        with self.lock:
            identified = sum(1 for p in self.global_persons.values() if p.name != "Unknown")
            cameras_used = set()
            for p in self.global_persons.values():
                cameras_used.update(p.get_cameras_seen_in())
            
            return {
                'total_persons': len(self.global_persons),
                'identified_persons': identified,
                'unique_cameras': len(cameras_used),
                'next_global_id': self.next_id,
                'feature_threshold': self.feature_threshold
            }
    
    def print_statistics(self):
        """Print current tracker statistics"""
        stats = self.get_statistics()
        print("\n" + "="*60)
        print("GLOBAL PERSON TRACKER STATISTICS")
        print("="*60)
        print(f"Total persons tracked: {stats['total_persons']}")
        print(f"Identified persons: {stats['identified_persons']}")
        print(f"Unique cameras: {stats['unique_cameras']}")
        print(f"Next global ID: {stats['next_global_id']}")
        print(f"Feature threshold: {stats['feature_threshold']}")
        print("="*60 + "\n")
