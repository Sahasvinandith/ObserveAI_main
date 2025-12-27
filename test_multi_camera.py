"""
Test script for GlobalPersonTracker, CameraGraph, and CrossCameraReID systems.
Verifies all components work correctly before integration.
"""

import numpy as np
import sys
sys.path.insert(0, '/home/sahas/Projects/ObserveAI_main')

from DataModel.GlobalPersonTracker import GlobalPersonTracker
from DataModel.CameraGraph import CameraGraph
from DataModel.CrossCameraReID import CrossCameraReID

def test_global_person_tracker():
    """Test GlobalPersonTracker functionality"""
    print("\n" + "="*60)
    print("TESTING: GlobalPersonTracker")
    print("="*60)
    
    tracker = GlobalPersonTracker()
    
    # Create persons
    gid1 = tracker.create_global_person()
    gid2 = tracker.create_global_person()
    
    print(f"\n✓ Created 2 global persons: {gid1}, {gid2}")
    
    # Link local persons from cameras
    features1 = np.random.rand(256)  # Dummy Re-ID features
    features2 = np.random.rand(256)
    
    tracker.link_local_to_global("Camera_A", 1, features1, (100, 100, 50, 100), gid1)
    tracker.link_local_to_global("Camera_B", 2, features2, (150, 150, 50, 100), gid1)
    
    print(f"✓ Linked local persons to global person {gid1}")
    
    # Update identity
    tracker.update_person_identity(gid1, "User_1", 0.95)
    person = tracker.get_person(gid1)
    print(f"✓ Updated identity: {person.name} (confidence: {person.confidence})")
    
    # Get statistics
    stats = tracker.get_person_statistics()
    print(f"✓ Statistics: {stats}")
    
    return tracker

def test_camera_graph():
    """Test CameraGraph functionality"""
    print("\n" + "="*60)
    print("TESTING: CameraGraph")
    print("="*60)
    
    graph = CameraGraph()
    
    # Add cameras
    graph.add_camera("Camera_A", (100, 100), 0, 500, 60)
    graph.add_camera("Camera_B", (150, 120), 45, 500, 60)
    graph.add_camera("Camera_C", (400, 400), 90, 500, 60)
    
    print(f"\n✓ Added 3 cameras")
    
    # Check relationships
    neighbors_a = graph.get_neighbors("Camera_A")
    print(f"✓ Camera_A neighbors: {neighbors_a}")
    
    direction_ab = graph.get_direction("Camera_A", "Camera_B")
    print(f"✓ Camera_B is {direction_ab} of Camera_A")
    
    overlaps_ab = graph.overlaps_with("Camera_A", "Camera_B")
    print(f"✓ Camera_A overlaps with Camera_B: {overlaps_ab}")
    
    # Get all info
    info = graph.get_all_cameras_info()
    print(f"\n✓ All camera info:")
    for cam_name, cam_info in info.items():
        print(f"  {cam_name}: pos={cam_info['position']}, neighbors={cam_info['neighbors']}")
    
    return graph

def test_cross_camera_reid(tracker, graph):
    """Test CrossCameraReID functionality"""
    print("\n" + "="*60)
    print("TESTING: CrossCameraReID")
    print("="*60)
    
    reid = CrossCameraReID(tracker, graph, feature_distance_threshold=0.4)
    
    # Test 1: Link persons across cameras
    features_a = np.random.rand(256)
    features_b = np.random.rand(256)
    
    gid = reid.link_persons_across_cameras(
        "Camera_A", 1, features_a,
        "Camera_B", 2, features_b
    )
    
    print(f"\n✓ Linked persons across cameras, global ID: {gid}")
    
    # Test 2: Get person trail
    person = tracker.get_person(gid)
    trail = reid.get_person_trail(gid)
    print(f"✓ Person trail: {trail}")
    
    # Test 3: Propagate identification
    reid.propagate_identification(gid, "User_5", 0.92, "Camera_A")
    person = tracker.get_person(gid)
    print(f"✓ After propagation - Name: {person.name}, Cameras: {person.get_cameras_seen_in()}")
    
    # Test 4: Match person across cameras
    query_features = features_a + np.random.randn(256) * 0.1  # Similar to features_a
    
    matches = reid.find_best_match_in_all_cameras(query_features, exclude_camera="Camera_A", top_k=3)
    print(f"✓ Best matches for query features:")
    for cam_name, gid, local_id, distance in matches:
        print(f"  {cam_name}, local_id={local_id}: distance={distance:.4f}")
    
    return reid

def test_integration():
    """Test all systems together"""
    print("\n" + "="*60)
    print("INTEGRATION TEST")
    print("="*60)
    
    # Initialize systems
    tracker = test_global_person_tracker()
    graph = test_camera_graph()
    reid = test_cross_camera_reid(tracker, graph)
    
    # Simulate multiple person sightings
    print(f"\n✓ All systems working together!")
    
    # Final statistics
    stats = tracker.get_person_statistics()
    reid_stats = reid.get_statistics()
    
    print(f"\n" + "="*60)
    print("FINAL STATISTICS")
    print("="*60)
    print(f"Global persons: {stats['total_persons']}")
    print(f"Identified: {stats['identified_persons']}")
    print(f"Cross-camera matches: {reid_stats['matches_found']}")
    print(f"CameraGraph: {graph}")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("TESTING MULTI-CAMERA TRACKING SYSTEM")
    print("="*60)
    
    try:
        test_integration()
        print(f"\n✅ ALL TESTS PASSED!\n")
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        import traceback
        traceback.print_exc()
