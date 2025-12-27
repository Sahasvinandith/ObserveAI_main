"""
CrossCameraReID: Cross-camera person re-identification.
Matches persons across cameras using Re-ID features and spatial relationships.
"""
import math
import numpy as np
from typing import Optional, Tuple, Dict, List
from DataModel.GlobalPersonTracker import GlobalPersonTracker
from DataModel.CameraGraph import CameraGraph


class CrossCameraReID:
    """
    Enables person re-identification across multiple cameras.
    Uses Re-ID features, spatial relationships, and identity propagation.
    """
    
    def __init__(
        self,
        global_tracker: GlobalPersonTracker,
        camera_graph: CameraGraph,
        feature_distance_threshold: float = 0.4,
        temporal_threshold: float = 10.0  # seconds
    ):
        """
        Args:
            global_tracker: GlobalPersonTracker instance
            camera_graph: CameraGraph instance
            feature_distance_threshold: L2 distance threshold for feature matching
            temporal_threshold: Max time between sightings to consider same person
        """
        self.global_tracker = global_tracker
        self.camera_graph = camera_graph
        self.feature_distance_threshold = feature_distance_threshold
        self.temporal_threshold = temporal_threshold
        
        # Statistics
        self.matches_found = 0
        self.false_positives = 0
    
    def match_person_across_cameras(
        self,
        exiting_camera: str,
        exiting_local_person_id: int,
        exiting_features: np.ndarray,
        exiting_bbox: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Tuple[str, int, float]]:
        """
        Try to match a person exiting one camera in neighboring cameras.
        
        Args:
            exiting_camera: Name of camera where person is exiting
            exiting_local_person_id: Local person ID in exiting camera
            exiting_features: Re-ID feature vector
            exiting_bbox: Bounding box (x, y, w, h) of person
        
        Returns:
            (neighbor_camera, neighbor_person_id, match_confidence) if match found, else None
        """
        if exiting_features is None:
            return None
        
        # Step 1: Get neighboring cameras
        neighbors = self.camera_graph.get_neighbors(exiting_camera)
        
        if not neighbors:
            return None
        
        best_match = None
        best_distance = float('inf')
        
        # Step 2: Search for matching persons in neighboring cameras
        for neighbor_camera in neighbors:
            # Get all active persons in neighbor camera
            neighbor_persons = self.global_tracker.get_active_persons_in_camera(
                neighbor_camera,
                timeout=self.temporal_threshold
            )
            
            for global_person in neighbor_persons:
                # Get features in this camera
                if neighbor_camera not in global_person.camera_tracks:
                    continue
                
                neighbor_track = global_person.camera_tracks[neighbor_camera]
                neighbor_features = neighbor_track.features
                
                if neighbor_features is None:
                    continue
                
                # Step 3: Compare features using L2 distance
                distance = np.linalg.norm(exiting_features - neighbor_features)
                
                # Step 4: Check spatial consistency
                spatial_valid = self._check_spatial_consistency(
                    exiting_camera,
                    neighbor_camera,
                    exiting_bbox,
                    neighbor_track.bounding_box
                )
                
                if spatial_valid and distance < best_distance:
                    best_distance = distance
                    best_match = (neighbor_camera, neighbor_track.local_person_id, global_person)
            
            # Check if match is within threshold
            if best_distance < self.feature_distance_threshold:
                self.matches_found += 1
                return (best_match[0], best_match[1], 1.0 - best_distance)
        
        return None
    
    def _check_spatial_consistency(
        self,
        cam1: str,
        cam2: str,
        bbox1: Optional[Tuple[int, int, int, int]],
        bbox2: Optional[Tuple[int, int, int, int]]
    ) -> bool:
        """
        Check if person movement between cameras is spatially consistent.
        """
        # Get camera relationship
        direction = self.camera_graph.get_direction(cam1, cam2)
        
        # If cameras don't overlap, require consistent direction
        if not self.camera_graph.overlaps_with(cam1, cam2):
            # Person should be exiting on the side facing cam2
            if direction in ['left', 'right', 'ahead']:
                return True
            # If coming from behind or no direction info, still allow
            return True
        
        # If cameras overlap, any valid match is acceptable
        return True
    
    def propagate_identification(
        self,
        global_person_id: int,
        identified_name: str,
        identified_confidence: float,
        identified_in_camera: str
    ):
        """
        When a person is identified in one camera, propagate across all cameras.
        
        Args:
            global_person_id: Global person ID
            identified_name: Identified name (e.g., "User_5")
            identified_confidence: Confidence score
            identified_in_camera: Which camera made the identification
        """
        # Update global tracker
        self.global_tracker.update_person_identity(
            global_person_id,
            identified_name,
            identified_confidence
        )
        
        # Log the propagation
        person = self.global_tracker.get_person(global_person_id)
        if person:
            cameras_informed = list(person.camera_tracks.keys())
            print(f"[CROSS-CAM ID] {identified_name} identified in {identified_in_camera}")
            print(f"  → Propagating to cameras: {cameras_informed}")
    
    def link_persons_across_cameras(
        self,
        cam1: str,
        local_id1: int,
        features1: np.ndarray,
        cam2: str,
        local_id2: int,
        features2: Optional[np.ndarray] = None
    ) -> int:
        """
        Explicitly link two local persons from different cameras to same global person.
        Used when confident match is found.
        
        Returns:
            global_person_id of the linked person
        """
        # Find if either person already has global ID
        existing_global_id = None
        
        # Check if cam1's person is already linked
        for gid, person in self.global_tracker.global_persons.items():
            if cam1 in person.camera_tracks and person.camera_tracks[cam1].local_person_id == local_id1:
                existing_global_id = gid
                break
        
        if existing_global_id is None:
            # Create new global person
            existing_global_id = self.global_tracker.create_global_person()
        
        # Link both local persons to same global person
        person = self.global_tracker.get_person(existing_global_id)
        person.update_from_camera(cam1, local_id1, features1)
        person.update_from_camera(cam2, local_id2, features2)
        
        return existing_global_id
    
    def get_person_trail(self, global_person_id: int) -> List[Tuple[str, float]]:
        """
        Get chronological trail of a person across cameras.
        
        Returns:
            List of (camera_name, timestamp) in chronological order
        """
        person = self.global_tracker.get_person(global_person_id)
        if person:
            return person.get_person_trail()
        return []
    
    def get_person_trajectory_string(self, global_person_id: int) -> str:
        """
        Get a human-readable trajectory string.
        Example: "Camera_A (0s) → Camera_B (5s) → Camera_C (12s)"
        """
        trail = self.get_person_trail(global_person_id)
        if not trail:
            return "No trail"
        
        parts = []
        start_time = trail[0][1]
        
        for cam_name, timestamp in trail:
            elapsed = timestamp - start_time
            parts.append(f"{cam_name} ({elapsed:.1f}s)")
        
        return " → ".join(parts)
    
    def get_statistics(self) -> Dict:
        """Get cross-camera ReID statistics"""
        return {
            'matches_found': self.matches_found,
            'false_positives': self.false_positives,
            'feature_threshold': self.feature_distance_threshold,
            'temporal_threshold': self.temporal_threshold
        }
    
    def find_best_match_in_all_cameras(
        self,
        query_features: np.ndarray,
        exclude_camera: Optional[str] = None,
        top_k: int = 5
    ) -> List[Tuple[str, int, int, float]]:
        """
        Find best matching persons across all cameras.
        Useful for searching the entire system.
        
        Args:
            query_features: Feature vector to search for
            exclude_camera: Exclude persons from this camera
            top_k: Return top K matches
        
        Returns:
            List of (camera_name, global_person_id, local_person_id, distance)
        """
        matches = []
        
        for global_id, person in self.global_tracker.global_persons.items():
            if person.primary_features is None:
                continue
            
            distance = np.linalg.norm(query_features - person.primary_features)
            
            for cam_name, track in person.camera_tracks.items():
                if exclude_camera and cam_name == exclude_camera:
                    continue
                
                matches.append((cam_name, global_id, track.local_person_id, distance))
        
        # Sort by distance and return top K
        matches.sort(key=lambda x: x[3])
        return matches[:top_k]
    
    def __repr__(self) -> str:
        stats = self.get_statistics()
        return f"CrossCameraReID(matches={stats['matches_found']}, threshold={stats['feature_threshold']:.2f})"
