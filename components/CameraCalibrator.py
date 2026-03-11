"""
CameraCalibrator - Two-Point Camera Position Calibration

Uses two reference points (person standing at known world positions)
to compute the camera's exact position and rotation on the floor plan.

Math:
- Each reference point gives us: world position (wx, wy) and frame position (fx)
- The camera must be at a position where both observations are consistent
- We use a coarse-to-fine grid search to find the optimal camera position
"""

import math
from typing import Tuple, Optional, List


class CalibrationPoint:
    """A single calibration reference point."""
    def __init__(self, world_x: float, world_y: float, frame_x_normalized: float):
        self.world_x = world_x          # Where person is on the map (pixels)
        self.world_y = world_y          
        self.frame_x_normalized = frame_x_normalized  # Where person is in frame (0.0=left, 1.0=right)
    
    def __repr__(self):
        return f"CalPt(world=({self.world_x:.1f}, {self.world_y:.1f}), frame={self.frame_x_normalized:.3f})"


def _angle_diff(a: float, b: float) -> float:
    """Compute the smallest signed angle difference between two angles in radians."""
    diff = a - b
    while diff > math.pi:
        diff -= 2 * math.pi
    while diff < -math.pi:
        diff += 2 * math.pi
    return diff


def solve_camera_position(
    points: List[CalibrationPoint],
    fov_degrees: float,
    initial_guess: Tuple[float, float],
    search_radius: float = 300.0
) -> Optional[Tuple[float, float, float]]:
    """
    Solve for camera position (cx, cy) and rotation (R) given reference points.
    
    Uses a coarse-to-fine grid search:
    1. Coarse: search ±search_radius around initial guess, step=5px
    2. Fine: search ±10px around best coarse result, step=0.5px
    
    For each candidate (cx, cy):
    - Compute the expected angle difference between reference points
    - Compare to the actual angle difference from frame positions
    - The best (cx, cy) minimizes this error
    - Then compute rotation R from any single observation
    
    Args:
        points: List of 2+ CalibrationPoints
        fov_degrees: Camera field of view in degrees
        initial_guess: Current camera position (cx, cy) on map
        search_radius: How far from initial guess to search (pixels)
    
    Returns:
        (cx, cy, rotation_degrees) or None if calibration fails
    """
    if len(points) < 2:
        return None
    
    fov_rad = math.radians(fov_degrees)
    
    # Compute expected angle differences from frame positions
    # Between point 0 and each subsequent point
    expected_diffs = []
    for i in range(1, len(points)):
        # Angle offset in frame: (frame_x - 0.5) * FOV
        offset_0 = (points[0].frame_x_normalized - 0.5) * fov_rad
        offset_i = (points[i].frame_x_normalized - 0.5) * fov_rad
        expected_diffs.append(offset_0 - offset_i)
    
    def compute_error(cx: float, cy: float) -> float:
        """Cost function: how well does (cx, cy) explain the observations."""
        total_error = 0.0
        
        # Check for degenerate case (camera at a reference point)
        for p in points:
            dx = p.world_x - cx
            dy = p.world_y - cy
            if dx * dx + dy * dy < 1.0:  # Too close
                return float('inf')
        
        # Compute actual angle to each reference point
        angle_0 = math.atan2(points[0].world_y - cy, points[0].world_x - cx)
        
        for i, expected_diff in enumerate(expected_diffs):
            angle_i = math.atan2(points[i + 1].world_y - cy, points[i + 1].world_x - cx)
            actual_diff = _angle_diff(angle_0, angle_i)
            error = _angle_diff(actual_diff, expected_diff)
            total_error += error * error
        
        return total_error
    
    # --- Coarse search ---
    gx, gy = initial_guess
    best_error = float('inf')
    best_cx, best_cy = gx, gy
    
    step = 5.0
    x = gx - search_radius
    while x <= gx + search_radius:
        y = gy - search_radius
        while y <= gy + search_radius:
            err = compute_error(x, y)
            if err < best_error:
                best_error = err
                best_cx, best_cy = x, y
            y += step
        x += step
    
    # --- Fine search around best coarse result ---
    fine_radius = 15.0
    fine_step = 0.5
    coarse_cx, coarse_cy = best_cx, best_cy
    
    x = coarse_cx - fine_radius
    while x <= coarse_cx + fine_radius:
        y = coarse_cy - fine_radius
        while y <= coarse_cy + fine_radius:
            err = compute_error(x, y)
            if err < best_error:
                best_error = err
                best_cx, best_cy = x, y
            y += fine_step
        x += fine_step
    
    # Check if solution is valid (error should be very small)
    if best_error > 0.01:  # ~5.7 degrees error threshold
        print(f"[CALIBRATION] Warning: best error {best_error:.4f} is high, solution may be imprecise")
    
    # --- Compute rotation from the solution ---
    # R = angle_to_point_0 - (frame_x_0 - 0.5) * FOV
    angle_to_0 = math.atan2(points[0].world_y - best_cy, points[0].world_x - best_cx)
    offset_0 = (points[0].frame_x_normalized - 0.5) * fov_rad
    rotation_rad = angle_to_0 - offset_0
    rotation_deg = math.degrees(rotation_rad) % 360
    
    print(f"[CALIBRATION] Solution: pos=({best_cx:.1f}, {best_cy:.1f}), rot={rotation_deg:.1f}°, error={best_error:.6f}")
    
    return (best_cx, best_cy, rotation_deg)
