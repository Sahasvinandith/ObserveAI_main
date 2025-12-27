"""
GlobalPersonTracker: Maintains a global registry of persons across all cameras.
Tracks identity, features, and movement history.
"""
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import numpy as np


@dataclass
class CameraTrack:
    """Represents a person's track in a specific camera"""
    local_person_id: int
    features: Optional[np.ndarray] = None
    last_seen: float = field(default_factory=time.time)
    bounding_box: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h)


@dataclass
class Sighting:
    """Represents a person sighting in a camera"""
    camera_name: str
    timestamp: float
    local_person_id: int
    confidence: float = 1.0


class GlobalPerson:
    """
    Represents a person tracked globally across the system.
    Maintains identity information and camera-specific tracks.
    """
    
    def __init__(self, global_id: int):
        self.global_id = global_id
        self.name = "Unknown"  # "User_5" when identified
        self.confidence = 0.0  # Confidence of identification
        
        # Tracks per camera
        self.camera_tracks: Dict[str, CameraTrack] = {}
        
        # Best features for matching
        self.primary_features: Optional[np.ndarray] = None
        self.primary_features_confidence: float = 0.0
        
        # Chronological sightings
        self.sightings: List[Sighting] = []
        
        # Metadata
        self.created_at = time.time()
        self.last_updated = time.time()
    
    def update_from_camera(
        self, 
        cam_name: str, 
        local_person_id: int,
        features: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        name: Optional[str] = None,
        confidence: Optional[float] = None
    ):
        """Update person info when seen in a camera"""
        
        # Update or create track for this camera
        if cam_name not in self.camera_tracks:
            self.camera_tracks[cam_name] = CameraTrack(
                local_person_id=local_person_id,
                features=features,
                bounding_box=bbox
            )
        else:
            track = self.camera_tracks[cam_name]
            track.local_person_id = local_person_id
            track.last_seen = time.time()
            if features is not None:
                track.features = features
            if bbox is not None:
                track.bounding_box = bbox
        
        # Record sighting
        self.sightings.append(Sighting(
            camera_name=cam_name,
            timestamp=time.time(),
            local_person_id=local_person_id,
            confidence=confidence or 1.0
        ))
        
        # Update primary features if better
        if features is not None:
            if self.primary_features is None or (confidence and confidence > self.primary_features_confidence):
                self.primary_features = features
                self.primary_features_confidence = confidence or 1.0
        
        # Update identity if provided
        if name and name != "Unknown" and name != "Scanning...":
            self.name = name
            self.confidence = confidence or self.confidence
        
        self.last_updated = time.time()
    
    def get_person_trail(self) -> List[Tuple[str, float]]:
        """Get chronological path across cameras: [(cam_name, timestamp), ...]"""
        return [(s.camera_name, s.timestamp) for s in sorted(self.sightings, key=lambda x: x.timestamp)]
    
    def get_cameras_seen_in(self) -> List[str]:
        """Get list of unique cameras this person has been seen in"""
        return list(self.camera_tracks.keys())
    
    def is_active_in_camera(self, cam_name: str, timeout: float = 5.0) -> bool:
        """Check if person was recently active in a camera"""
        if cam_name not in self.camera_tracks:
            return False
        return (time.time() - self.camera_tracks[cam_name].last_seen) < timeout
    
    def __repr__(self) -> str:
        cameras = list(self.camera_tracks.keys())
        return f"GlobalPerson(id={self.global_id}, name={self.name}, cameras={cameras})"


class GlobalPersonTracker:
    """
    Central registry for all persons detected in the system.
    Manages global IDs, identity propagation, and tracking.
    """
    
    def __init__(self):
        self.global_persons: Dict[int, GlobalPerson] = {}
        self.next_global_id = 1
        self.lock = __import__('threading').Lock()  # Thread-safe operations
    
    def create_global_person(self) -> int:
        """Create a new global person and return its ID"""
        with self.lock:
            gid = self.next_global_id
            self.global_persons[gid] = GlobalPerson(gid)
            self.next_global_id += 1
            return gid
    
    def get_or_create_global_person(self, global_id: Optional[int] = None) -> GlobalPerson:
        """Get existing person or create new one"""
        if global_id is None:
            global_id = self.create_global_person()
        elif global_id not in self.global_persons:
            with self.lock:
                self.global_persons[global_id] = GlobalPerson(global_id)
        return self.global_persons[global_id]
    
    def get_person(self, global_id: int) -> Optional[GlobalPerson]:
        """Get person by global ID"""
        return self.global_persons.get(global_id)
    
    def get_persons_in_camera(self, cam_name: str) -> List[GlobalPerson]:
        """Get all persons currently being tracked in a specific camera"""
        with self.lock:
            return [p for p in self.global_persons.values() if cam_name in p.camera_tracks]
    
    def get_active_persons_in_camera(self, cam_name: str, timeout: float = 5.0) -> List[GlobalPerson]:
        """Get persons recently active in a camera"""
        with self.lock:
            return [p for p in self.global_persons.values() if p.is_active_in_camera(cam_name, timeout)]
    
    def get_identified_persons(self) -> List[GlobalPerson]:
        """Get all persons that have been identified (name != 'Unknown')"""
        with self.lock:
            return [p for p in self.global_persons.values() if p.name != "Unknown"]
    
    def update_person_identity(self, global_id: int, name: str, confidence: float):
        """Update identification for a person (propagates across cameras)"""
        with self.lock:
            person = self.global_persons.get(global_id)
            if person:
                person.name = name
                person.confidence = confidence
    
    def link_local_to_global(
        self,
        cam_name: str,
        local_person_id: int,
        features: Optional[np.ndarray] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        global_person_id: Optional[int] = None
    ) -> int:
        """Link a local person to a global person"""
        if global_person_id is None:
            global_person_id = self.create_global_person()
        
        person = self.get_or_create_global_person(global_person_id)
        person.update_from_camera(cam_name, local_person_id, features, bbox)
        
        return global_person_id
    
    def get_person_statistics(self) -> Dict:
        """Get overall statistics about tracked persons"""
        with self.lock:
            total_persons = len(self.global_persons)
            identified_count = len([p for p in self.global_persons.values() if p.name != "Unknown"])
            unique_cameras = len(set(
                cam for p in self.global_persons.values() for cam in p.camera_tracks.keys()
            ))
            
            return {
                'total_persons': total_persons,
                'identified_persons': identified_count,
                'unique_cameras': unique_cameras,
                'next_global_id': self.next_global_id
            }
    
    def cleanup_inactive_persons(self, timeout: float = 30.0):
        """Remove persons not seen for specified time"""
        with self.lock:
            to_remove = []
            for gid, person in self.global_persons.items():
                if time.time() - person.last_updated > timeout:
                    to_remove.append(gid)
            
            for gid in to_remove:
                del self.global_persons[gid]
            
            return len(to_remove)
