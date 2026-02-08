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
    frame_width: int = 1920  # Frame width for bbox normalization
    frame_height: int = 1080  # Frame height


@dataclass
class LocalTrack:
    """Represents a person's track in a specific camera"""
    camera_name: str
    local_person_id: int  # DeepSORT track ID in this camera
    feature_vector: Optional[np.ndarray] = None
    last_seen: float = field(default_factory=time.time)
    bbox: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h)
    
    def update(self, feature_vector: Optional[np.ndarray] = None, 
               bbox: Optional[Tuple[int, int, int, int]] = None):
        """Update track information"""
        if feature_vector is not None:
            self.feature_vector = feature_vector
        if bbox is not None:
            self.bbox = bbox
        self.last_seen = time.time()


@dataclass
class GlobalPerson:
    """Represents a person tracked across multiple cameras"""
    global_id: int
    feature_vector: Optional[np.ndarray] = None  # Most recent/best features
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
    
    def update_face_identity(self, user_id: str, confidence: float) -> str:
        """
        Update face identity for this global person.
        Keeps the best match (lowest confidence/distance).
        
        Returns: The consolidated (winner) user ID
        """
        if user_id in ("Unknown", "Scanning..."):
            return self.local_user_id
        
        # If this is a better match (lower distance), update
        if confidence < self.best_confidence:
            print(f"[CONSOLIDATE] Global {self.global_id}: {self.local_user_id} ({self.best_confidence:.2f}) -> {user_id} ({confidence:.2f})")
            self.local_user_id = user_id
            self.best_confidence = confidence
            # Also update legacy fields
            self.name = user_id
            self.confidence = confidence
        
        return self.local_user_id
    
    def update_from_camera(self, camera_name: str, local_id: int,
                          feature_vector: Optional[np.ndarray] = None,
                          bbox: Optional[Tuple[int, int, int, int]] = None):
        """Update or create a local track for this camera"""
        if camera_name in self.camera_tracks:
            # Update existing track
            self.camera_tracks[camera_name].update(feature_vector, bbox)
        else:
            # Create new track
            self.camera_tracks[camera_name] = LocalTrack(
                camera_name=camera_name,
                local_person_id=local_id,
                feature_vector=feature_vector,
                bbox=bbox
            )
        
        # Update global features if provided
        if feature_vector is not None:
            self.feature_vector = feature_vector
        
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
    
    def __init__(self, feature_threshold: float = 0.5, 
                 reid_weight: float = 0.7, 
                 spatial_weight: float = 0.5,
                 position_callback: Optional[Callable] = None):
        """
        Initialize the global person tracker with spatial awareness.
        
        Args:
            feature_threshold: Maximum combined distance for match (0.0-2.0)
                              Lower = stricter matching
                              Recommended: 0.4-0.6
            reid_weight: Weight for Re-ID feature matching (default 0.7)
            spatial_weight: Weight for spatial matching (default 0.3)
            position_callback: Optional callback(global_id, x, y, camera_name) 
                              for floor map visualization
        """
        self.global_persons: Dict[int, GlobalPerson] = {}
        self.next_id: int = 1
        self.feature_threshold: float = feature_threshold
        self.reid_weight: float = reid_weight
        self.spatial_weight: float = spatial_weight
        self.lock = threading.Lock()
        
        # Camera spatial data
        self.cameras: Dict[str, CameraInfo] = {}
        
        # Callback for position updates (for floor map visualization)
        self.position_callback = position_callback
        
        print(f"[GLOBAL TRACKER] Initialized with threshold={feature_threshold}, "
              f"weights: reid={reid_weight}, spatial={spatial_weight}")
    
    # =========================================================================
    # Face Identity Consolidation
    # =========================================================================
    
    def update_face_identity(self, global_id: int, user_id: str, confidence: float) -> str:
        """
        Update face identity for a global person. If multiple cameras report
        different IDs for the same global person, keep the best (lowest distance).
        
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
            return person.update_face_identity(user_id, confidence)
    
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
    
    # =========================================================================
    # Camera Registration
    # =========================================================================
    
    def register_camera(self, name: str, position: Tuple[float, float], 
                       rotation: float, fov: float = 70.0,
                       frame_width: int = 1920, frame_height: int = 1080):
        """
        Register a camera with its spatial information.
        
        Args:
            name: Camera name (must match name used in create_or_update)
            position: (x, y) position on floor plan
            rotation: Camera rotation in degrees (0 = pointing right)
            fov: Field of view in degrees (default 70)
            frame_width: Frame width in pixels for bbox normalization
            frame_height: Frame height in pixels
        """
        with self.lock:
            self.cameras[name] = CameraInfo(
                name=name,
                position=position,
                rotation=rotation,
                fov=fov,
                frame_width=frame_width,
                frame_height=frame_height
            )
            print(f"[GLOBAL TRACKER] Registered camera '{name}' at pos={position}, rot={rotation}°, fov={fov}°")
    
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
                                   distance_estimate: float = 100.0) -> Optional[Tuple[float, float]]:
        """
        Estimate person's world position based on camera location and viewing angle.
        
        This is an approximation that projects the person along the viewing ray
        at a fixed distance from the camera.
        
        Args:
            camera_name: Name of the camera
            bbox: (x, y, w, h) bounding box
            distance_estimate: Estimated distance from camera (in floor plan units)
            
        Returns:
            (x, y) estimated position on floor plan, or None
        """
        if camera_name not in self.cameras:
            return None
        
        camera = self.cameras[camera_name]
        world_angle = self._bbox_to_world_angle(camera_name, bbox)
        
        if world_angle is None:
            return None
        
        # Convert angle to radians
        angle_rad = math.radians(world_angle)
        
        # Project from camera position along the viewing angle
        est_x = camera.position[0] + distance_estimate * math.cos(angle_rad)
        est_y = camera.position[1] + distance_estimate * math.sin(angle_rad)
        
        return (est_x, est_y)
    
    def _spatial_distance(self, camera1: str, bbox1: Tuple[int, int, int, int],
                          camera2: str, bbox2: Tuple[int, int, int, int]) -> float:
        """
        Calculate spatial distance score between two observations.
        
        Combines:
        1. Angular alignment: Are they looking at the same direction?
        2. Camera proximity: How close are the cameras?
        
        Returns:
            Distance score (0 = very likely same person, 1 = unlikely)
        """
        # If either camera not registered, return neutral score
        if camera1 not in self.cameras or camera2 not in self.cameras:
            return 0.5  # Neutral - don't affect matching
        
        # Get world angles
        angle1 = self._bbox_to_world_angle(camera1, bbox1)
        angle2 = self._bbox_to_world_angle(camera2, bbox2)
        
        if angle1 is None or angle2 is None:
            return 0.5
        
        # Angular distance (0-180 degrees)
        angle_diff = abs(angle1 - angle2)
        if angle_diff > 180:
            angle_diff = 360 - angle_diff
        
        # Normalize angular distance to 0-1
        # 0 degrees difference = 0 (same direction)
        # 180 degrees difference = 1 (opposite directions)
        angular_score = angle_diff / 180.0
        
        # Camera physical distance
        cam1 = self.cameras[camera1]
        cam2 = self.cameras[camera2]
        cam_distance = math.sqrt(
            (cam1.position[0] - cam2.position[0])**2 + 
            (cam1.position[1] - cam2.position[1])**2
        )
        
        # Normalize camera distance (assume max relevant distance is 500 units)
        # Closer cameras = more likely to see same person
        cam_score = min(cam_distance / 500.0, 1.0)
        
        # Combine scores: weight angular alignment more heavily
        # If cameras are far apart, angular alignment matters less
        combined = 0.7 * angular_score + 0.3 * cam_score
        
        return combined
    
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
                           exclude_camera: Optional[str] = None,
                           current_bbox: Optional[Tuple[int, int, int, int]] = None,
                           current_camera: Optional[str] = None) -> Optional[int]:
        """
        Find a matching global person using combined Re-ID + Spatial scoring.
        
        **IMPORTANT:** This method assumes the lock is already held by the caller!
        Use only from within locked sections.
        
        Args:
            feature_vector: Re-ID features to match against
            exclude_camera: Optional camera to exclude from search
                          (useful when looking for person in OTHER cameras)
            current_bbox: Current bbox for spatial calculations
            current_camera: Current camera name for spatial calculations
        
        Returns:
            global_id if match found, None otherwise
        """
        if feature_vector is None:
            return None
        
        best_match_id = None
        best_combined_distance = float('inf')
        
        # Note: NO LOCK HERE - assumes caller already has it!
        for person in self.global_persons.values():
            # Skip if person has no features
            if person.feature_vector is None:
                continue
            
            # Skip if we want to exclude this person's camera
            if exclude_camera and person.is_in_camera(exclude_camera):
                continue
            
            # Calculate Re-ID distance (normalized to ~0-1 range)
            reid_distance = self._cosine_distance(feature_vector, person.feature_vector)
            
            # Calculate Spatial distance (0-1 range)
            spatial_distance = 0.5  # Default neutral if no spatial data
            
            if current_bbox is not None and current_camera is not None:
                # Find the person's most recent track in another camera
                for cam_name, track in person.camera_tracks.items():
                    if cam_name != current_camera and track.bbox is not None:
                        spatial_distance = self._spatial_distance(
                            current_camera, current_bbox,
                            cam_name, track.bbox
                        )
                        break  # Use first available track
            
            # Combined weighted score
            combined_distance = (self.reid_weight * reid_distance + 
                                self.spatial_weight * spatial_distance)
            
            print(f"[GLOBAL TRACKER] ID={person.global_id}: reid={reid_distance:.3f}, "
                  f"spatial={spatial_distance:.3f}, combined={combined_distance:.3f}")
            
            # Track best match
            if combined_distance < best_combined_distance:
                best_combined_distance = combined_distance
                best_match_id = person.global_id
        
        print(f"[GLOBAL TRACKER] Best match: ID={best_match_id}, combined={best_combined_distance:.3f}")
        
        # Return match if below threshold
        if best_combined_distance < self.feature_threshold:
            print(f"[GLOBAL TRACKER] Match found! ID={best_match_id}, distance={best_combined_distance:.3f}")
            return best_match_id
        
        return None
    
    def create_or_update(self, camera_name: str, local_id: int,
                        feature_vector: Optional[np.ndarray] = None,
                        bbox: Optional[Tuple[int, int, int, int]] = None,
                        frame_shape: Optional[Tuple[int, int]] = None) -> int:
        """
        Main entry point: Find matching person or create new one.
        
        Args:
            camera_name: Name of the camera
            local_id: Local person ID (DeepSORT track ID)
            feature_vector: Re-ID features (optional but recommended)
            bbox: Bounding box (x, y, w, h)
            frame_shape: (width, height) of the frame for bbox normalization
        
        Returns:
            global_id: The assigned global person ID
        """
        print("[GLOBAL TRACKER] Creating or updating person...")
        
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
                    exclude_camera=camera_name,
                    current_bbox=bbox,
                    current_camera=camera_name
                )
            
            if matched_id is not None:
                # Match found - update existing person
                person = self.global_persons[matched_id]
                person.update_from_camera(camera_name, local_id, feature_vector, bbox)
                global_id = matched_id
                print(f"[GLOBAL TRACKER] Updated person {matched_id} in {camera_name}")
            else:
                # No match - create new person
                new_id = self.next_id
                self.next_id += 1
                
                person = GlobalPerson(global_id=new_id)
                person.update_from_camera(camera_name, local_id, feature_vector, bbox)
                self.global_persons[new_id] = person
                global_id = new_id
                print(f"[GLOBAL TRACKER] Created new person {new_id} in {camera_name}")
            
            # Emit position callback for floor map visualization
            if self.position_callback and bbox is not None:
                estimated_pos = self._estimate_person_position(camera_name, bbox)
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
