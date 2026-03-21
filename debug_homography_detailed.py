#!/usr/bin/env python3
"""
Debug the homography computation to see what world points are being calculated.
"""
import json
import math
import numpy as np
import cv2
import sys

sys.path.insert(0, '/home/sahas/Projects/ObserveAI_main')

def compute_homography_debug(camera_pos, camera_rotation, fov_degrees, frame_width, frame_height, view_range):
    """
    Compute homography with full debug output to see what's happening
    """
    print(f"\n{'='*80}")
    print(f"Camera: pos={camera_pos}, rot={camera_rotation}°, fov={fov_degrees}°")
    print(f"Frame: {frame_width}x{frame_height}, view_range={view_range}")
    print(f"{'='*80}")
    
    rotation_rad = math.radians(camera_rotation)
    
    frame_ref_points = np.array([
        [0, 0],
        [frame_width, 0],
        [frame_width, frame_height],
        [0, frame_height]
    ], dtype=np.float32)
    
    print("\nFrame Reference Points:")
    for i, (fx, fy) in enumerate(frame_ref_points):
        print(f"  Corner {i}: ({fx}, {fy})")
    
    half_fov_rad = math.radians(fov_degrees / 2)
    world_points = []
    
    print(f"\nComputing World Points:")
    print(f"  Rotation: {camera_rotation}° = {rotation_rad:.4f} rad")
    print(f"  sin(rot)={math.sin(rotation_rad):.4f}, cos(rot)={math.cos(rotation_rad):.4f}")
    print(f"  Half FOV: {fov_degrees/2}° = {half_fov_rad:.4f} rad")
    
    for idx, (fx, fy) in enumerate(frame_ref_points):
        print(f"\n  Corner {idx}: frame ({fx}, {fy})")
        
        norm_x = (fx / frame_width) - 0.5
        norm_y = fy / frame_height
        print(f"    Normalized: x={norm_x:.4f}, y={norm_y:.4f}")
        
        angle = norm_x * fov_degrees / 2
        distance = view_range * norm_y  # FIXED: was (1.0 - norm_y)
        print(f"    Angle: {angle:.2f}°, Distance: {distance:.2f}")
        
        angle_rad = math.radians(angle)
        print(f"    sin(angle)={math.sin(angle_rad):.4f}, cos(angle)={math.cos(angle_rad):.4f}")
        
        # Local camera coordinates
        local_x = distance * math.sin(angle_rad)
        local_y = distance * math.cos(angle_rad)
        print(f"    Local camera coords: x={local_x:.4f}, y={local_y:.4f}")
        
        # Rotate to world
        world_x = (local_x * math.cos(rotation_rad) - 
                  local_y * math.sin(rotation_rad) + camera_pos[0])
        world_y = (local_x * math.sin(rotation_rad) + 
                  local_y * math.cos(rotation_rad) + camera_pos[1])
        print(f"    World coords: ({world_x:.2f}, {world_y:.2f})")
        
        world_points.append([world_x, world_y])
    
    world_points = np.array(world_points, dtype=np.float32)
    
    print(f"\nWorld Reference Points:")
    for i, (wx, wy) in enumerate(world_points):
        print(f"  Corner {i}: ({wx:.2f}, {wy:.2f})")
    
    print(f"\nChecking if world points are degenerate...")
    # Check if all corners are the same (which would be degenerate)
    if np.allclose(world_points[0], world_points[1:]):
        print("  ✗ ERROR: All world points are nearly identical! This is a degenerate case!")
        print(f"  All corners map to approximately: {world_points[0]}")
    elif np.allclose(world_points[2], world_points[3]):
        print("  ✗ ERROR: Some world points are identical!")
    
    # Compute homography
    H = cv2.getPerspectiveTransform(frame_ref_points, world_points)
    print(f"\nHomography Matrix H:\n{H}")
    
    # Test the homography
    print(f"\nTesting Homography:")
    test_frame = np.array([[[320, 240]]], dtype=np.float32)  # Center
    result = cv2.perspectiveTransform(test_frame, H)
    print(f"  Frame (320, 240) → World {result[0][0]}")
    
    return H


# Test with Cheap camera
print("\n" + "="*80)
print("CHEAP CAMERA")
print("="*80)
compute_homography_debug(
    camera_pos=(243.5, 56.0),
    camera_rotation=91.46,
    fov_degrees=46,
    frame_width=640,
    frame_height=480,
    view_range=400.0
)

# Test with HD camera
print("\n" + "="*80)
print("HD CAMERA")
print("="*80)
compute_homography_debug(
    camera_pos=(3.0, 157.5),
    camera_rotation=1.86,
    fov_degrees=42,
    frame_width=640,
    frame_height=480,
    view_range=400.0
)
