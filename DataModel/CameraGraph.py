"""
CameraGraph: Spatial mapping and relationship management for cameras.
Detects overlaps, calculates view cones, and manages camera adjacency.
"""
import math
from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass
import numpy as np


@dataclass
class CameraConfig:
    """Configuration for a camera in spatial terms"""
    name: str
    position: Tuple[float, float]  # (x, y) in scene coordinates
    rotation_degree: float  # Facing direction in degrees
    view_range: float  # Detection range in pixels
    fov: float  # Field of view in degrees
    
    def get_view_cone_points(self, num_rays: int = 30) -> List[Tuple[float, float]]:
        """Generate points representing the camera's viewing cone"""
        points = [(self.position[0], self.position[1])]  # Center point
        
        angle_start = self.rotation_degree - (self.fov / 2)
        
        for i in range(num_rays + 1):
            angle = angle_start + (self.fov * i / num_rays)
            rad = math.radians(angle)
            
            x = self.position[0] + self.view_range * math.cos(rad)
            y = self.position[1] + self.view_range * math.sin(rad)
            
            points.append((x, y))
        
        return points
    
    def contains_point(self, point: Tuple[float, float]) -> bool:
        """Check if a point is within this camera's view cone"""
        px, py = point
        cx, cy = self.position
        
        # Check distance
        dist = math.sqrt((px - cx)**2 + (py - cy)**2)
        if dist > self.view_range:
            return False
        
        # Check angle
        angle_to_point = math.degrees(math.atan2(py - cy, px - cx))
        angle_diff = angle_to_point - self.rotation_degree
        
        # Normalize to [-180, 180]
        while angle_diff > 180:
            angle_diff -= 360
        while angle_diff < -180:
            angle_diff += 360
        
        # Check if within FOV
        return abs(angle_diff) <= (self.fov / 2)


class CameraGraph:
    """
    Maintains a spatial graph of all cameras.
    Detects overlaps, calculates relationships, and manages camera adjacency.
    """
    
    def __init__(self):
        self.cameras: Dict[str, CameraConfig] = {}
        self.adjacency: Dict[str, Set[str]] = {}  # cam_name → set of neighboring cameras
        self.overlaps: Dict[Tuple[str, str], bool] = {}  # (cam1, cam2) → overlaps? Stores combinations of cameras if they are overlapped in the other cameras view
        self.directions: Dict[Tuple[str, str], str] = {}  # (cam1, cam2) → direction
    
    def add_camera(
        self,
        name: str,
        position: Tuple[float, float],
        rotation_degree: float,
        view_range: float = 500.0,
        fov: float = 60.0
    ):
        """Add a camera to the graph"""
        config = CameraConfig(
            name=name,
            position=position,
            rotation_degree=rotation_degree,
            view_range=view_range,
            fov=fov
        )
        self.cameras[name] = config
        self.adjacency[name] = set()
        
        # Recalculate relationships with all existing cameras
        self._update_relationships()
    
    def update_camera_pose(
        self,
        name: str,
        position: Tuple[float, float],
        rotation_degree: float
    ):
        """Update camera position and rotation"""
        if name in self.cameras:
            self.cameras[name].position = position
            self.cameras[name].rotation_degree = rotation_degree
            self._update_relationships()
    
    def remove_camera(self, name: str):
        """Remove a camera from the graph"""
        if name in self.cameras:
            del self.cameras[name]
            del self.adjacency[name]
            
            # Clean up overlaps and directions
            keys_to_remove = [k for k in self.overlaps.keys() if name in k]
            for k in keys_to_remove:
                del self.overlaps[k]
            
            keys_to_remove = [k for k in self.directions.keys() if name in k]
            for k in keys_to_remove:
                del self.directions[k]
            
            # Remove from other adjacency lists
            for other in self.adjacency:
                self.adjacency[other].discard(name)
    
    def _update_relationships(self):
        """Recalculate all camera relationships"""
        cam_names = list(self.cameras.keys())
        
        for i, cam1_name in enumerate(cam_names):
            for cam2_name in cam_names[i+1:]:
                cam1 = self.cameras[cam1_name]
                cam2 = self.cameras[cam2_name]
                
                # Check overlap
                overlaps = self._cameras_overlap(cam1, cam2)
                self.overlaps[(cam1_name, cam2_name)] = overlaps
                self.overlaps[(cam2_name, cam1_name)] = overlaps
                
                # Calculate directions
                dir1to2 = self._get_direction(cam1, cam2)
                dir2to1 = self._get_direction(cam2, cam1)
                
                self.directions[(cam1_name, cam2_name)] = dir1to2
                self.directions[(cam2_name, cam1_name)] = dir2to1
                
                # Update adjacency (neighbors if overlapping or very close)
                if overlaps or self._cameras_close(cam1, cam2):
                    self.adjacency[cam1_name].add(cam2_name)
                    self.adjacency[cam2_name].add(cam1_name)
                else:
                    self.adjacency[cam1_name].discard(cam2_name)
                    self.adjacency[cam2_name].discard(cam1_name)
    
    def _cameras_overlap(self, cam1: CameraConfig, cam2: CameraConfig) -> bool:
        """Check if two camera view cones overlap"""
        # Simple check: does cam1's view contain cam2's center?
        cam2_in_cam1 = cam1.contains_point(cam2.position)
        
        # Does cam2's view contain cam1's center?
        cam1_in_cam2 = cam2.contains_point(cam1.position)
        
        return cam2_in_cam1 or cam1_in_cam2
    
    def _cameras_close(self, cam1: CameraConfig, cam2: CameraConfig, threshold: float = 150.0) -> bool:
        """Check if cameras are close to each other"""
        dx = cam2.position[0] - cam1.position[0]
        dy = cam2.position[1] - cam1.position[1]
        dist = math.sqrt(dx**2 + dy**2)
        return dist < threshold
    
    def _get_direction(self, from_cam: CameraConfig, to_cam: CameraConfig) -> str:
        """Get relative direction from one camera to another"""
        dx = to_cam.position[0] - from_cam.position[0]
        dy = to_cam.position[1] - from_cam.position[1]
        
        # Calculate angle from from_cam to to_cam
        angle_to_target = math.degrees(math.atan2(dy, dx))
        
        # Normalize relative to camera's facing direction
        relative_angle = angle_to_target - from_cam.rotation_degree
        
        # Normalize to [-180, 180]
        while relative_angle > 180:
            relative_angle -= 360
        while relative_angle < -180:
            relative_angle += 360
        
        # Classify direction
        if relative_angle < -112.5 or relative_angle > 112.5:
            return 'behind'
        elif -112.5 <= relative_angle < -67.5:
            return 'left'
        elif -67.5 <= relative_angle < -22.5:
            return 'left-front'
        elif -22.5 <= relative_angle < 22.5:
            return 'ahead'
        elif 22.5 <= relative_angle < 67.5:
            return 'right-front'
        elif 67.5 <= relative_angle <= 112.5:
            return 'right'
    
    def get_neighbors(self, cam_name: str) -> List[str]:
        """Get all neighboring cameras"""
        return list(self.adjacency.get(cam_name, set()))
    
    def overlaps_with(self, cam1_name: str, cam2_name: str) -> bool:
        """Check if two cameras overlap"""
        if cam1_name not in self.cameras or cam2_name not in self.cameras:
            return False
        cameras_overlapping:bool = self.overlaps.get((cam1_name, cam2_name), False)
        return cameras_overlapping
    
    def get_direction(self, from_cam: str, to_cam: str) -> Optional[str]:
        """Get direction from one camera to another"""
        return self.directions.get((from_cam, to_cam))
    
    def get_camera_view_cone(self, cam_name: str) -> List[Tuple[float, float]]:
        """Get view cone points for visualization"""
        if cam_name not in self.cameras:
            return []
        return self.cameras[cam_name].get_view_cone_points()
    
    def get_all_cameras_info(self) -> Dict[str, Dict]:
        """Get all camera information"""
        info = {}
        for name, config in self.cameras.items():
            neighbors = self.get_neighbors(name)
            info[name] = {
                'position': config.position,
                'rotation': config.rotation_degree,
                'view_range': config.view_range,
                'fov': config.fov,
                'neighbors': neighbors,
                'overlap_count': len([n for n in neighbors if self.overlaps_with(name, n)])
            }
        return info
    
    def get_coverage_map(self, grid_size: int = 50) -> np.ndarray:
        """
        Generate a coverage heatmap of the scene.
        Returns array where each cell shows how many cameras can see it.
        """
        if not self.cameras:
            return np.zeros((grid_size, grid_size))
        
        # Determine bounds
        positions = [c.position for c in self.cameras.values()]
        min_x = min(p[0] for p in positions) - 100
        max_x = max(p[0] for p in positions) + 100
        min_y = min(p[1] for p in positions) - 100
        max_y = max(p[1] for p in positions) + 100
        
        coverage = np.zeros((grid_size, grid_size), dtype=int)
        
        for i in range(grid_size):
            for j in range(grid_size):
                # Map grid cell to scene coordinates
                x = min_x + (max_x - min_x) * j / grid_size
                y = min_y + (max_y - min_y) * i / grid_size
                
                # Count how many cameras see this point
                for cam in self.cameras.values():
                    if cam.contains_point((x, y)):
                        coverage[i, j] += 1
        
        return coverage
    
    def __repr__(self) -> str:
        return f"CameraGraph(cameras={len(self.cameras)}, total_adjacencies={sum(len(v) for v in self.adjacency.values())//2})"
