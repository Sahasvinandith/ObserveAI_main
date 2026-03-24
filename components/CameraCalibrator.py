"""
CameraCalibrator - Enhanced Multi-Parameter Camera Calibration

Uses reference points (person at known world positions) to compute:
- Camera position (cx, cy) on the floor plan
- Camera rotation (R) around its vertical axis
- Camera field of view (FOV) - detects actual zoom/focal length
- Effective view range - depth of field performance

Math:
- Each reference point gives us: world position (wx, wy), frame position (fx)
- With 2 points: solve for (cx, cy, R) with fixed FOV
- With 3+ points: can also solve for FOV to find actual zoom level
- With Y-coordinate: can estimate view range and camera tilt
"""

import math
from typing import Tuple, Optional, List


class CalibrationPoint:
    """A single calibration reference point with optional Y coordinate."""
    def __init__(self, world_x: float, world_y: float, frame_x_normalized: float, 
                 frame_y_normalized: float = 0.5):
        self.world_x = world_x          # Where person is on the map (pixels)
        self.world_y = world_y          
        self.frame_x_normalized = frame_x_normalized  # Where person is in frame (0.0=left, 1.0=right)
        self.frame_y_normalized = frame_y_normalized  # Vertical position (0.0=top, 1.0=bottom) - NEW
    
    def __repr__(self):
        return f"CalPt(world=({self.world_x:.1f}, {self.world_y:.1f}), frame=({self.frame_x_normalized:.3f}, {self.frame_y_normalized:.3f})"


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
    search_radius: float = 300.0,
    detect_fov: bool = False,
    detect_view_range: bool = False,
    lock_position: bool = False
) -> Optional[Tuple[float, float, float, float, float]]:
    """
    Solve for camera parameters given reference points.
    
    **NEW CAPABILITY**: Can now strictly lock the map position and only detect FOV and view_range!
    
    Uses a coarse-to-fine grid search:
    1. Coarse: search ±search_radius around initial guess, step=5px
    2. Fine: search ±15px around best coarse result, step=0.5px
    3. If detect_fov=True: Also search for optimal FOV (60-120 degrees)
    4. If detect_view_range=True: Estimate effective view range from Y positions
    
    For each candidate (cx, cy):
    - Compute the expected angle difference between reference points
    - Compare to the actual angle difference from frame positions
    - The best (cx, cy) minimizes this error
    - Then compute rotation R from any single observation
    
    Args:
        points: List of 2+ CalibrationPoints
        fov_degrees: Initial camera field of view in degrees
        initial_guess: Current camera position (cx, cy) on map
        search_radius: How far from initial guess to search (pixels)
        detect_fov: If True, search for optimal FOV (more points needed for accuracy)
        detect_view_range: If True, estimate view range from vertical frame positions
        lock_position: If True, strictly enforces cx,cy = initial_guess, bypassing position grid-search completely.
    
    Returns:
        (cx, cy, rotation_degrees, detected_fov, detected_view_range) or None if calibration fails
        - If detect_fov=False: detected_fov = input fov_degrees
        - If detect_view_range=False: detected_view_range = 200.0 (default)
    """
    if len(points) < 2:
        return None
    
    # --- PHASE 1: Search for optimal position with fixed or variable FOV ---
    
    if detect_fov and len(points) >= 3:
        # With 3+ points, we can search for both position and FOV
        best_result = _solve_with_fov_search(points, fov_degrees, initial_guess, search_radius, lock_position)
        if best_result is None:
            return None
        best_cx, best_cy, best_fov, rotation_deg, best_error = best_result
    else:
        # Standard solve with fixed FOV
        best_result = _solve_fixed_fov(points, fov_degrees, initial_guess, search_radius, lock_position)
        if best_result is None:
            return None
        best_cx, best_cy, rotation_deg, best_error = best_result
        best_fov = fov_degrees
    
    # --- PHASE 2: Estimate view range from Y positions (if provided) ---
    
    if detect_view_range:
        detected_range = _estimate_view_range(points, best_cx, best_cy, best_fov)
    else:
        detected_range = 200.0  # Default fallback
    
    print(f"[CALIBRATION] ✓ Solution: pos=({best_cx:.1f}, {best_cy:.1f}), rot={rotation_deg:.1f}°, " 
          f"fov={best_fov:.1f}° (detected={detect_fov}), range={detected_range:.1f} (detected={detect_view_range}), error={best_error:.6f}")
    
    return (best_cx, best_cy, rotation_deg, best_fov, detected_range)


def _solve_fixed_fov(
    points: List[CalibrationPoint],
    fov_degrees: float,
    initial_guess: Tuple[float, float],
    search_radius: float,
    lock_position: bool = False
) -> Optional[Tuple[float, float, float, float]]:
    """
    Standard solver: Find (cx, cy, rotation) with fixed FOV.
    Returns: (cx, cy, rotation_deg, error)
    """
    fov_rad = math.radians(fov_degrees)
    
    # Compute expected angle differences from frame positions
    expected_diffs = []
    for i in range(1, len(points)):
        offset_0 = (points[0].frame_x_normalized - 0.5) * fov_rad
        offset_i = (points[i].frame_x_normalized - 0.5) * fov_rad
        expected_diffs.append(offset_0 - offset_i)
    
    def compute_error(cx: float, cy: float) -> float:
        """Cost function: how well does (cx, cy) explain the observations."""
        total_error = 0.0
        
        # Check for degenerate case
        for p in points:
            dx = p.world_x - cx
            dy = p.world_y - cy
            if dx * dx + dy * dy < 1.0:
                return float('inf')
        
        # Compute actual angle to each reference point
        angle_0 = math.atan2(points[0].world_y - cy, points[0].world_x - cx)
        
        for i, expected_diff in enumerate(expected_diffs):
            angle_i = math.atan2(points[i + 1].world_y - cy, points[i + 1].world_x - cx)
            actual_diff = _angle_diff(angle_0, angle_i)
            error = _angle_diff(actual_diff, expected_diff)
            total_error += error * error
        
        return total_error
    
    gx, gy = initial_guess
    
    if lock_position:
        # Bypass positional search entirely and use the user's explicit map coordinates
        best_cx, best_cy = gx, gy
        best_error = compute_error(gx, gy)
    else:
        # --- Coarse search ---
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
        
        # --- Fine search ---
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
    
    # Check validity
    if best_error > 0.01:
        print(f"[CALIBRATION] Warning: best error {best_error:.4f} is high")
    
    # --- Compute rotation ---
    angle_to_0 = math.atan2(points[0].world_y - best_cy, points[0].world_x - best_cx)
    offset_0 = (points[0].frame_x_normalized - 0.5) * fov_rad
    rotation_rad = angle_to_0 - offset_0
    rotation_deg = math.degrees(rotation_rad) % 360
    
    return (best_cx, best_cy, rotation_deg, best_error)


def _solve_with_fov_search(
    points: List[CalibrationPoint],
    initial_fov: float,
    initial_guess: Tuple[float, float],
    search_radius: float,
    lock_position: bool = False
) -> Optional[Tuple[float, float, float, float, float]]:
    """
    Enhanced solver: Find (cx, cy, fov, rotation) by searching FOV range.
    
    For 3+ points, we can over-constrain the system and solve for FOV.
    We search multiple FOV values and find the one with lowest total error.
    
    Returns: (cx, cy, detected_fov, rotation_deg, error)
    """
    best_global_error = float('inf')
    best_cx, best_cy, best_fov, rotation_deg = None, None, None, None
    
    # Search FOV from 40 to 140 degrees (covers most cameras)
    fov_candidates = list(range(40, 141, 5))  # Coarse: 40, 45, 50, ..., 140
    
    print(f"[CALIBRATION] Searching {len(fov_candidates)} FOV candidates with {len(points)} points...")
    
    for test_fov in fov_candidates:
        # For this FOV, find best position
        result = _solve_fixed_fov(points, test_fov, initial_guess, search_radius, lock_position)
        if result is None:
            continue
        
        cx, cy, rot, error = result
        
        if error < best_global_error:
            best_global_error = error
            best_cx, best_cy, best_fov, rotation_deg = cx, cy, test_fov, rot
            print(f"  FOV {test_fov}°: error={error:.6f} (NEW BEST)")
        else:
            print(f"  FOV {test_fov}°: error={error:.6f}")
    
    # --- Fine search around best FOV ---
    if best_fov is not None:
        fine_fov_candidates = []
        for fov_offset in range(-4, 5):
            test_fov = best_fov + fov_offset
            if 40 <= test_fov <= 140 and test_fov not in fov_candidates:
                fine_fov_candidates.append(test_fov)
        
        if fine_fov_candidates:
            print(f"[CALIBRATION] Fine-tuning FOV around {best_fov}°...")
            for test_fov in fine_fov_candidates:
                result = _solve_fixed_fov(points, test_fov, (best_cx, best_cy), 10.0, lock_position)
                if result is None:
                    continue
                cx, cy, rot, error = result
                if error < best_global_error:
                    best_global_error = error
                    best_cx, best_cy, best_fov, rotation_deg = cx, cy, test_fov, rot
                    print(f"  FOV {test_fov}°: error={error:.6f} (REFINED)")
    
    if best_fov is None:
        return None
    
    return (best_cx, best_cy, best_fov, rotation_deg, best_global_error)


def _estimate_view_range(
    points: List[CalibrationPoint],
    camera_x: float,
    camera_y: float,
    fov_degrees: float
) -> float:
    """
    Estimate the effective view range from calibration points' Y positions.
    
    Logic:
    - Points at the bottom of frame (high Y) appear closer than top of frame (low Y)
    - We use this depth cue to estimate how far away the 'standard' view range should be
    - Returns the estimated range in pixels
    
    With more Y-coordinate data, this becomes more accurate.
    """
    if not points:
        return 200.0
    
    # Get distances from camera to each point
    distances = []
    for p in points:
        dx = p.world_x - camera_x
        dy = p.world_y - camera_y
        dist = math.hypot(dx, dy)
        distances.append((dist, p.frame_y_normalized))
    
    if len(distances) < 2:
        return 200.0
    
    # Fit a simple model: frame_y ≈ 1 - (distance / view_range) * k
    # Higher Y in frame (bottom) = closer distance
    # Lower Y in frame (top) = farther distance
    
    distances.sort(key=lambda x: x[1])  # Sort by frame Y
    
    closest_dist, closest_y = distances[0]
    farthest_dist, farthest_y = distances[-1]
    
    # Estimate based on extreme points
    # Rough heuristic: view_range ≈ farthest_distance / (1 - closest_y / farthest_y)
    if farthest_dist > closest_dist and (farthest_y - closest_y) > 0.1:
        estimated_range = farthest_dist * 0.8  # Conservative estimate
        estimated_range = max(50.0, min(500.0, estimated_range))  # Clamp to reasonable bounds
    else:
        estimated_range = 200.0  # Fallback default
    
    print(f"[CALIBRATION] View range estimation: closest={closest_dist:.1f}px (frame_y={closest_y:.2f}), "
          f"farthest={farthest_dist:.1f}px (frame_y={farthest_y:.2f}) → estimated_range={estimated_range:.1f}px")
    
    return estimated_range
