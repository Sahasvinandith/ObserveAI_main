"""
Homography-based bird's-eye projection for multi-camera visualization.

This module provides functionality to transform camera frame coordinates
into bird's-eye view (world/floor map) coordinates using homography matrices
computed from camera calibration data.

Key Concept:
- Camera projects 3D world → 2D frame (perspective projection)
- Homography reverses this: 2D frame position → 2D world position
- Assumes flat ground plane (Z = 0) and camera looking down at angle

Math:
- For a camera at (cx, cy) with rotation R and FOV θ:
  - Define 4 known frame points (corners of reference rectangle)
  - Compute their corresponding world coordinates using camera geometry
  - Use cv2.getPerspectiveTransform() to compute 3x3 homography matrix H
  - Apply with cv2.perspectiveTransform(point, H) to transform coordinates

Author: ObserveAI System
"""

import numpy as np
import cv2
import math
from typing import Tuple, Dict, Optional, List


class HomographyProjector:
    """
    Computes and applies homography transforms to project camera view
    bounding boxes into bird's-eye view.
    """

    @staticmethod
    def compute_homography_from_calibration(
        camera_pos: Tuple[float, float],
        camera_rotation: float,
        fov_degrees: float,
        frame_width: int,
        frame_height: int,
        view_range: float = 300.0
    ) -> Optional[np.ndarray]:
        """
        Build homography matrix from camera calibration parameters.

        The homography assumes:
        - Camera is mounted looking downward at a fixed angle
        - Ground plane is at Z=0
        - Camera position (cx, cy) is in world coordinates
        - Rotation is in degrees (0° = +X direction, 90° = +Y direction)

        Args:
            camera_pos: (cx, cy) camera position on floor map
            camera_rotation: Camera rotation in degrees
            fov_degrees: Field of view in degrees (horizontal)
            frame_width: Frame width in pixels
            frame_height: Frame height in pixels
            view_range: Maximum view range in world units (default 300)

        Returns:
            3x3 homography matrix (numpy array) or None if computation fails
            The matrix transforms frame coordinates to world coordinates:
            world_point = H @ [frame_x, frame_y, 1]

        Raises:
            ValueError: If calibration parameters are invalid
        """
        try:
            if fov_degrees <= 0 or fov_degrees >= 180:
                raise ValueError(f"Invalid FOV: {fov_degrees}°")
            if frame_width <= 0 or frame_height <= 0:
                raise ValueError(f"Invalid frame size: {frame_width}x{frame_height}")

            # Convert rotation to radians
            rotation_rad = math.radians(camera_rotation)

            # Define reference rectangle in frame (normalized 0-1)
            # This represents the visible area of the ground plane
            frame_ref_points = np.array([
                [0, 0],                    # Top-left
                [frame_width, 0],          # Top-right
                [frame_width, frame_height * 0.8],  # Near-bottom-right (80% of frame)
                [0, frame_height * 0.8]   # Near-bottom-left (80% of frame)
            ], dtype=np.float32)

            # Compute corresponding world points
            # Camera sees:
            # - Top of frame: farthest distance (near edge of view range)
            # - Bottom of frame: closest distance (near camera)
            # - Left/Right: depends on FOV and rotation

            half_fov_rad = math.radians(fov_degrees / 2)
            
            # Camera model:
            # - Horizontal FOV spans from -half_fov to +half_fov
            # - Frame X [0, width] maps to angles [-half_fov, +half_fov]
            # - Frame Y [0, height] maps to distances [view_range, 0]

            world_points = []
            
            for fx, fy in frame_ref_points:
                # Map frame coordinates to angles and distances
                # Normalize frame coords to [-0.5, 0.5] range
                norm_x = (fx / frame_width) - 0.5
                norm_y = fy / frame_height

                # Angle: left-right (based on horizontal FOV)
                angle = norm_x * fov_degrees / 2  # in degrees
                
                # Distance: top-to-bottom (based on view range)
                # For a downward-looking camera:
                # - Top of frame (fy=0) = far away = farthest visible point
                # - Bottom of frame (fy=height) = near camera = closest point
                # 
                # IMPORTANT: The mapping depends on camera orientation!
                # If camera is looking DOWN: top=far, bottom=near
                # If camera is looking UP or SIDE: this might be reversed
                #
                # Current model assumes: top=far, bottom=near
                distance = view_range * (1.0 - norm_y)  # Top=view_range, Bottom=0
                
                # Convert to world coordinates
                # Camera faces along its rotation direction
                angle_rad = math.radians(angle)
                
                # Local camera coordinates (distance along gaze, offset by angle)
                local_x = distance * math.sin(angle_rad)
                local_y = distance * math.cos(angle_rad)
                
                # Rotate to world coordinates
                world_x = (local_x * math.cos(rotation_rad) - 
                          local_y * math.sin(rotation_rad) + camera_pos[0])
                world_y = (local_x * math.sin(rotation_rad) + 
                          local_y * math.cos(rotation_rad) + camera_pos[1])
                
                world_points.append([world_x, world_y])
            
            world_points = np.array(world_points, dtype=np.float32)

            # Compute homography: frame -> world
            H = cv2.getPerspectiveTransform(frame_ref_points, world_points)
            
            return H

        except Exception as e:
            print(f"Error computing homography: {e}")
            return None

    @staticmethod
    def project_bbox_to_world(
        bbox: Tuple[int, int, int, int],
        H: np.ndarray,
        frame_height: int
    ) -> Optional[Tuple[float, float]]:
        """
        Project bounding box center from frame → world coordinates using homography.

        The bounding box is assumed to be at ground level (bottom of bbox in frame).

        Args:
            bbox: (x, y, w, h) in frame pixels
                  x, y: top-left corner of bbox
                  w, h: width and height
            H: 3x3 homography matrix
            frame_height: Frame height in pixels (for Y-flip if needed)

        Returns:
            (world_x, world_y) - projected position on floor map
            Returns None if projection fails

        Math:
            1. Get bbox center: (cx_frame, cy_frame)
            2. Use bottom of bbox as ground point (person standing point)
               → Actually use center for consistency, or bottom for contact point
            3. Apply homography: p_world = H @ [px_frame, py_frame, 1]
            4. Return normalized coordinates
        """
        try:
            if H is None or H.shape != (3, 3):
                return None

            # Get bbox center
            cx_frame = bbox[0] + bbox[2] / 2.0
            cy_frame = bbox[1] + bbox[3] / 2.0
            
            # Debug: Check if bbox looks like (x1, y1, x2, y2) format instead of (x, y, w, h)
            if bbox[2] > 640 or bbox[3] > 480:
                print(f"[HOMOGRAPHY WARN] Unusual bbox values: {bbox} - might be (x1,y1,x2,y2) instead of (x,y,w,h)!")
            
            # Use bbox BOTTOM (contact point with ground) for accurate ground projection
            # This represents where the person's feet touch the ground
            cy_bottom = bbox[1] + bbox[3]  # Bottom of bbox = feet on ground
            # Note: This is more accurate than using center (which is at head/chest height)

            # Apply homography
            point = np.array([[[cx_frame, cy_bottom]]], dtype=np.float32)
            projected = cv2.perspectiveTransform(point, H)

            if projected is not None and len(projected) > 0:
                world_x = projected[0][0][0]
                world_y = projected[0][0][1]
                return (world_x, world_y)
            
            return None

        except Exception as e:
            print(f"Error projecting bbox: {e}")
            return None

    @staticmethod
    def project_point_to_world(
        point: Tuple[float, float],
        H: np.ndarray
    ) -> Optional[Tuple[float, float]]:
        """
        Project a single point from frame → world coordinates.

        Args:
            point: (x, y) in frame pixels
            H: 3x3 homography matrix

        Returns:
            (world_x, world_y) or None if projection fails
        """
        try:
            if H is None or H.shape != (3, 3):
                return None

            point_array = np.array([[[point[0], point[1]]]], dtype=np.float32)
            projected = cv2.perspectiveTransform(point_array, H)

            if projected is not None and len(projected) > 0:
                return (projected[0][0][0], projected[0][0][1])
            
            return None

        except Exception as e:
            print(f"Error projecting point: {e}")
            return None

    @staticmethod
    def validate_homography(H: np.ndarray, 
                           ref_points: List[Tuple[float, float]],
                           tolerance: float = 10.0) -> bool:
        """
        Validate homography by checking if reference points project reasonably.

        Args:
            H: Homography matrix
            ref_points: List of (world_x, world_y) reference points to validate against
            tolerance: Maximum allowed projection error in world units

        Returns:
            True if homography appears valid, False otherwise
        """
        if H is None or len(ref_points) < 2:
            return False

        try:
            # Check a few frame points to see if they project to world points
            # This is a simple sanity check
            for i in range(min(3, len(ref_points))):
                # Sample point in frame (arbitrary)
                frame_point = np.array([[[100.0 + i*50, 100.0]]], dtype=np.float32)
                projected = cv2.perspectiveTransform(frame_point, H)
                
                if projected is None:
                    return False
                
                # Check that projected point is reasonable (not NaN, not extreme)
                world_x, world_y = projected[0][0]
                if math.isnan(world_x) or math.isnan(world_y):
                    return False
                if abs(world_x) > 10000 or abs(world_y) > 10000:
                    return False
            
            return True

        except Exception:
            return False

    @staticmethod
    def invert_homography(H: np.ndarray) -> Optional[np.ndarray]:
        """
        Compute inverse homography (world → frame).

        Args:
            H: Forward homography matrix (frame → world)

        Returns:
            Inverse homography matrix (world → frame) or None if singular
        """
        try:
            H_inv = cv2.invert(H)
            if H_inv[0] > 0:  # Success indicator
                return H_inv[1]
            return None
        except Exception as e:
            print(f"Error inverting homography: {e}")
            return None
