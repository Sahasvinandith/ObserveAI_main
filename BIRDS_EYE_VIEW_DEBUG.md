# Birds Eye View - Debug Mode Explanation

## Normal Mode (Debug OFF)
When you click the **"🐛 Debug: OFF"** button:
- **Shows**: Single **green circle** with label (e.g., "G:1 John")
- **Represents**: The final stereo-vision calculated position of the person
- **Calculation**: Position computed from triangulating detections across multiple cameras
- **Best for**: Seeing the overall person location in the space

## Debug Mode (Debug ON)
When you click the **"🐛 Debug: ON"** button:
- **Shows**: Multiple colored circles + lines + final green circle
- **Each colored circle**:
  - Represents how ONE camera independently sees the person
  - Color indicates which camera (Red=Cam1, Blue=Cam2, Yellow=Cam3, etc.)
  - **Position**: Where that camera's homography projects the person to world coordinates

- **Dashed lines**:
  - Connect each camera position to its projected person position
  - Shows the "sightline" from camera to detected person
  - Helps visualize the triangulation geometry

- **Final green circle**:
  - Still shown even in debug mode
  - Larger than individual camera circles
  - This is the STEREO result (consensus position from all cameras)
  - Ideally should be near the center of the colored circles (good triangulation)

## What Debug Mode Helps You See

### Good Triangulation
- All colored circles clustered close together
- Green circle in the center of the cluster
- Lines from all cameras converge nicely
- **Means**: Cameras agree on person position ✓

### Poor Triangulation
- Colored circles far apart
- Green circle outside the cluster
- Lines don't converge
- **Means**: Cameras disagree (calibration issue or occlusion) ✗

### Camera Issues
- One camera's circle is always off
- That camera's line points in wrong direction
- **Means**: That camera might be miscalibrated

## Camera Visualization

Each camera icon shows:
- **Yellow circle**: Camera position on the map
- **Yellow arrow**: Direction the camera is pointing (0° = North/Up)
- **Cyan dashed cone**: Camera's field of view (FOV) - the area it can see
- **Camera label**: The camera name (e.g., "Cheap", "HD")

The arrow and FOV cone help you understand each camera's view orientation.
