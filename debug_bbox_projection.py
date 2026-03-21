#!/usr/bin/env python3
"""
Debug script to test homography projection with actual bbox values.
"""
import json
import math
import numpy as np
import cv2
import sys

sys.path.insert(0, '/home/sahas/Projects/ObserveAI_main')

from components.HomographyProjector import HomographyProjector

def test_bbox_projection():
    """Test homography with the actual bbox values from your detection"""
    
    # Load map config
    with open('maps/Modifide.json', 'r') as f:
        config = json.load(f)
    
    print("="*80)
    print("TESTING BBOX PROJECTION WITH ACTUAL VALUES")
    print("="*80)
    
    # Test bboxes from your debug output
    test_cases = [
        {
            'camera': 'Cheap',
            'bbox': (211, 108, 293, 359),  # x, y, w, h
            'frame': (640, 480)
        },
        {
            'camera': 'HD',
            'bbox': (353, 136, 607, 579),  # x, y, w, h
            'frame': (640, 480)
        },
    ]
    
    for test in test_cases:
        cam_name = test['camera']
        bbox = test['bbox']
        frame_w, frame_h = test['frame']
        
        # Find camera config
        cam_config = None
        for cam in config['cameras']:
            if cam['name'] == cam_name:
                cam_config = cam
                break
        
        if not cam_config:
            print(f"Camera {cam_name} not found!")
            continue
        
        print(f"\n{cam_name} Camera Test:")
        print(f"  Frame size: {frame_w}x{frame_h}")
        print(f"  Bbox (x, y, w, h): {bbox}")
        
        # Check if bbox is valid
        x, y, w, h = bbox
        if x + w > frame_w or y + h > frame_h:
            print(f"  ⚠️  WARNING: Bbox extends beyond frame!")
            print(f"     Right edge: {x + w} > {frame_w}")
            print(f"     Bottom edge: {y + h} > {frame_h}")
        
        # Compute homography
        H = HomographyProjector.compute_homography_from_calibration(
            camera_pos=tuple(cam_config['pos']),
            camera_rotation=cam_config['rot'],
            fov_degrees=cam_config['fov'],
            frame_width=frame_w,
            frame_height=frame_h,
            view_range=cam_config['view_range']
        )
        
        if H is None:
            print("  ERROR: Could not compute homography!")
            continue
        
        print(f"  Homography Matrix computed")
        
        # Test projection
        print(f"\n  Testing projection:")
        
        # Test points
        test_points = {
            'center': (x + w/2, y + h/2),
            'bottom-center': (x + w/2, y + h),
            'top-center': (x + w/2, y),
        }
        
        for point_name, (px, py) in test_points.items():
            print(f"    {point_name}: frame({px:.1f}, {py:.1f})", end=" → ")
            
            point = np.array([[[px, py]]], dtype=np.float32)
            projected = cv2.perspectiveTransform(point, H)
            
            if projected is not None:
                wx, wy = projected[0][0]
                cam_x, cam_y = cam_config['pos']
                dist_from_cam = math.sqrt((wx - cam_x)**2 + (wy - cam_y)**2)
                print(f"world({wx:.1f}, {wy:.1f}) dist_from_cam={dist_from_cam:.1f}")
                
                if abs(wx - cam_x) < 0.5 and abs(wy - cam_y) < 0.5:
                    print(f"      ⚠️  PROBLEM: Projects to camera position!")
            else:
                print("FAILED")
        
        # Now test with proper bbox projection function
        print(f"\n  Using project_bbox_to_world():")
        proj = HomographyProjector.project_bbox_to_world(bbox, H, frame_h)
        if proj:
            wx, wy = proj
            cam_x, cam_y = cam_config['pos']
            dist = math.sqrt((wx - cam_x)**2 + (wy - cam_y)**2)
            print(f"    Result: world({wx:.1f}, {wy:.1f}) dist_from_cam={dist:.1f}")
            if dist < 0.5:
                print(f"    ⚠️  PROBLEM: Projects to camera position!")
        else:
            print(f"    Projection returned None!")

if __name__ == '__main__':
    test_bbox_projection()
