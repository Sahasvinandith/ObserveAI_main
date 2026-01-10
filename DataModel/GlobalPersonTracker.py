"""
GlobalPersonTracker - Simple Feature-Based Cross-Camera Person Tracking

This module provides a lightweight, reliable system for tracking persons across
multiple cameras using Re-ID feature matching (no complex spatial logic).

Key Principles:
- Feature matching is the PRIMARY mechanism (proven reliable)
- Simple data structures (easy to debug)
- No spatial calculations required
- Graceful degradation (works even with missing features)
"""

import numpy as np
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple


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
    
    # Face recognition results
    name: str = "Unknown"
    confidence: float = 0.0
    
    # Lifecycle tracking
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    
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
    Tracks persons across multiple cameras using Re-ID feature matching.
    
    This is a simple, reliable implementation that:
    - Uses cosine distance for feature matching
    - Checks ALL cameras for matches (no spatial restrictions)
    - Creates new person if no match found
    - Thread-safe for multi-camera use
    """
    
    def __init__(self, feature_threshold: float = 0.5):
        """
        Initialize the global person tracker.
        
        Args:
            feature_threshold: Maximum cosine distance for feature match (0.0-2.0)
                              Lower = stricter matching
                              Recommended: 0.4-0.6
        """
        self.global_persons: Dict[int, GlobalPerson] = {}
        self.next_id: int = 1
        self.feature_threshold: float = feature_threshold
        self.lock = threading.Lock()
        
        print(f"[GLOBAL TRACKER] Initialized with threshold={feature_threshold}")
    
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
                           exclude_camera: Optional[str] = None) -> Optional[int]:
        """
        Find a matching global person by comparing Re-ID features.
        
        **IMPORTANT:** This method assumes the lock is already held by the caller!
        Use only from within locked sections.
        
        Args:
            feature_vector: Re-ID features to match against
            exclude_camera: Optional camera to exclude from search
                          (useful when looking for person in OTHER cameras)
        
        Returns:
            global_id if match found, None otherwise
        """
        if feature_vector is None:
            return None
        
        best_match_id = None
        best_distance = float('inf')
        
        # Note: NO LOCK HERE - assumes caller already has it!
        for person in self.global_persons.values():
            # Skip if person has no features
            if person.feature_vector is None:
                continue
            
            # Skip if we want to exclude this person's camera
            if exclude_camera and person.is_in_camera(exclude_camera):
                continue
            
            # Calculate distance
            distance = self._cosine_distance(feature_vector, person.feature_vector)
            
            # Track best match
            if distance < best_distance:
                best_distance = distance
                best_match_id = person.global_id
        
        print(f"[GLOBAL TRACKER] Best match: ID={best_match_id}, distance={best_distance:.3f}")
        
        # Return match if below threshold
        if best_distance < self.feature_threshold:
            print(f"[GLOBAL TRACKER] Match found! ID={best_match_id}, distance={best_distance:.3f}")
            return best_match_id
        
        return None
    
    def create_or_update(self, camera_name: str, local_id: int,
                        feature_vector: Optional[np.ndarray] = None,
                        bbox: Optional[Tuple[int, int, int, int]] = None) -> int:
        """
        Main entry point: Find matching person or create new one.
        
        Args:
            camera_name: Name of the camera
            local_id: Local person ID (DeepSORT track ID)
            feature_vector: Re-ID features (optional but recommended)
            bbox: Bounding box (x, y, w, h)
        
        Returns:
            global_id: The assigned global person ID
        """
        print("[GLOBAL TRACKER] Creating or updating person...")
        with self.lock:
            # Try to find existing match using features (lock already held!)
            matched_id = None
            if feature_vector is not None:
                # Look for match in OTHER cameras (not this one)
                matched_id = self._find_match_unsafe(feature_vector, exclude_camera=camera_name)
            
            if matched_id is not None:
                # Match found - update existing person
                person = self.global_persons[matched_id]
                person.update_from_camera(camera_name, local_id, feature_vector, bbox)
                print(f"[GLOBAL TRACKER] Updated person {matched_id} in {camera_name}")
                return matched_id
            else:
                # No match - create new person
                new_id = self.next_id
                self.next_id += 1
                
                person = GlobalPerson(global_id=new_id)
                person.update_from_camera(camera_name, local_id, feature_vector, bbox)
                self.global_persons[new_id] = person
                
                print(f"[GLOBAL TRACKER] Created new person {new_id} in {camera_name}")
                return new_id
    
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
