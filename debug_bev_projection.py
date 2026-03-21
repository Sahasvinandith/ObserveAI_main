#!/usr/bin/env python3
"""
Debug script to visualize and verify homography projections
for each camera against the Modifide.json map configuration.

Run this to test if person positions are being correctly projected.
"""
import json
import math
import numpy as np
import cv2
import sys

sys.path.insert(0, '/home/sahas/Projects/ObserveAI_main')

from components.HomographyProjector import HomographyProjector

def load_map_config(map_path):
    """Load camera configuration from JSON map file"""
    with open(map_path, 'r') as f:
        return json.load(f)

def analyze_camera_homography(cam_config):
    """Analyze homography projection for a single camera"""
    
    print(f"\n{'='*70}")
    print(f"CAMERA: {cam_config['name']}")
    print(f"{'='*70}")
    print(f"Position: {cam_config['pos']}")
    print(f"Rotation: {cam_config['rot']}°")
    print(f"FOV: {cam_config['fov']}°")
    print(f"View Range: {cam_config['view_range']}")
    
    # Compute homography
    H = HomographyProjector.compute_homography_from_calibration(
        camera_pos=tuple(cam_config['pos']),
        camera_rotation=cam_config['rot'],
        fov_degrees=cam_config['fov'],
        frame_width=640,
        frame_height=480,
        view_range=cam_config['view_range']
    )
    
    if H is None:
        print("ERROR: Could not compute homography!")
        return
    
    print(f"\nHomography Matrix:\n{H}")
    
    # Test projections: frame corners and center
    test_points = {
        'Frame Center': (320, 240),
        'Frame Top-Left': (0, 0),
        'Frame Top-Right': (640, 0),
        'Frame Bottom-Left': (0, 480),
        'Frame Bottom-Right': (640, 480),
        'Frame Bottom-Center': (320, 480),  # Bottom center (ground contact point)
    }
    
    print(f"\nProjection Test Results:")
    print(f"{'Point':<20} {'Frame Coords':<20} {'World Coords':<30} {'Distance from Camera':<20}")
    print("-" * 90)
    
    cam_x, cam_y = cam_config['pos']
    
    for point_name, (fx, fy) in test_points.items():
        # Project using homography
        frame_point = np.array([[[fx, fy]]], dtype=np.float32)
        projected = cv2.perspectiveTransform(frame_point, H)
        
        if projected is not None:
            wx, wy = projected[0][0][0], projected[0][0][1]
            dist = math.sqrt((wx - cam_x)**2 + (wy - cam_y)**2)
            print(f"{point_name:<20} ({fx:3.0f}, {fy:3.0f})        ({wx:7.2f}, {wy:7.2f})    {dist:7.2f}")
        else:
            print(f"{point_name:<20} ({fx:3.0f}, {fy:3.0f})        PROJECTION FAILED")
    
    # Visualize camera direction
    rotation_rad = math.radians(cam_config['rot'])
    look_dir_x = math.sin(rotation_rad)
    look_dir_y = math.cos(rotation_rad)
    
    # Point where camera is looking (at view_range distance)
    gaze_world_x = cam_x + look_dir_x * cam_config['view_range']
    gaze_world_y = cam_y + look_dir_y * cam_config['view_range']
    
    print(f"\nCamera Direction:")
    print(f"  Rotation: {cam_config['rot']}°")
    print(f"  Direction Vector: ({look_dir_x:.4f}, {look_dir_y:.4f})")
    print(f"  Camera Position: ({cam_x}, {cam_y})")
    print(f"  Gaze Point (at max range): ({gaze_world_x:.2f}, {gaze_world_y:.2f})")


def test_person_projection(map_path, person_frame_bbox, camera_name):
    """Test projecting a person from a specific camera"""
    
    config = load_map_config(map_path)
    
    # Find camera
    cam_config = None
    for cam in config['cameras']:
        if cam['name'] == camera_name:
            cam_config = cam
            break
    
    if not cam_config:
        print(f"Camera '{camera_name}' not found in map!")
        return
    
    print(f"\n{'='*70}")
    print(f"PERSON PROJECTION TEST")
    print(f"{'='*70}")
    print(f"Camera: {camera_name}")
    print(f"Frame Bbox: {person_frame_bbox} (x, y, w, h)")
    
    # Compute homography
    H = HomographyProjector.compute_homography_from_calibration(
        camera_pos=tuple(cam_config['pos']),
        camera_rotation=cam_config['rot'],
        fov_degrees=cam_config['fov'],
        frame_width=640,
        frame_height=480,
        view_range=cam_config['view_range']
    )
    
    if H is None:
        print("ERROR: Could not compute homography!")
        return
    
    # Project bbox
    world_pos = HomographyProjector.project_bbox_to_world(
        person_frame_bbox, H, 480
    )
    
    if world_pos:
        wx, wy = world_pos
        cam_x, cam_y = cam_config['pos']
        dist = math.sqrt((wx - cam_x)**2 + (wy - cam_y)**2)
        
        print(f"\nProjection Result:")
        print(f"  World Position: ({wx:.2f}, {wy:.2f})")
        print(f"  Distance from Camera: {dist:.2f}")
        print(f"  Camera Position: ({cam_x}, {cam_y})")
    else:
        print("Projection returned None!")


def main():
    map_path = '/home/sahas/Projects/ObserveAI_main/maps/Modifide.json'
    
    # Load and analyze each camera
    config = load_map_config(map_path)
    
    print("\n" + "="*70)
    print("BIRD'S EYE VIEW HOMOGRAPHY PROJECTION DEBUG")
    print("="*70)
    print(f"Map File: {map_path}")
    print(f"Map Scale: {config['pixels_per_meter']} pixels/meter")
    
    # Analyze each camera
    for cam_config in config['cameras']:
        analyze_camera_homography(cam_config)
    
    # Test specific person projections
    print("\n\n" + "="*70)
    print("EXAMPLE: Person detected in 'Cheap' camera frame")
    print("="*70)
    
    # Example: person bbox at (300, 350, 100, 150) in frame
    test_person_projection(map_path, (300, 350, 100, 150), 'Cheap')
    
    print("\n" + "="*70)
    print("EXAMPLE: Person detected in 'HD' camera frame")
    print("="*70)
    
    # Example: person bbox at (320, 300, 110, 160) in frame
    test_person_projection(map_path, (320, 300, 110, 160), 'HD')
    
    print("\n\n" + "="*70)
    print("END OF DEBUG")
    print("="*70)


if __name__ == '__main__':
    main()
