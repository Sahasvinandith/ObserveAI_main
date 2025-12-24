# Camera Refresh Implementation Guide

## Overview
A new refresh mechanism has been implemented to allow users to retry camera connections without restarting the entire application. This implementation uses the existing worker thread for minimum CPU cost.

## How It Works

### 1. **CameraWorker Enhancement** (`components/Camera_worker.py`)
- **New Flag**: `self.should_reconnect` - Set to trigger reconnection
- **New Method**: `restart()` - Called when refresh is requested
  - Sets the `should_reconnect` flag to True
  - The worker picks up this flag on its next iteration
  
- **Modified `run()` Loop**:
  - Checks for the `should_reconnect` flag at each iteration
  - If True:
    - Releases the old connection
    - Attempts to reconnect to the camera
    - Emits appropriate `connectionSuccess` or `connectionFailed` signals
  - If disconnected, waits 500ms before attempting reconnection (prevents CPU spinning)

### 2. **CameraFeedWidget** (`components/Camera_list_widget.py`)
- **New Attribute**: `self.worker` - Reference to the CameraWorker
- **New Method**: `on_refresh_clicked()` 
  - Called when the refresh button (in camera_feed_widget.ui) is clicked
  - Calls `worker.restart()` to trigger reconnection
  - Updates UI based on connection signals

### 3. **GridFeedWidget** (`components/Grid_feed_widget.py`)
- **New Attribute**: `self.worker` - Reference to the CameraWorker
- **New UI Element**: Refresh button (↻) in the title bar
- **New Method**: `on_refresh_clicked()`
  - Same functionality as CameraFeedWidget
  - Allows refresh from the grid view

### 4. **MainWindow Integration** (`main/MainWindow.py`)
- **Modified `create_camera_items()`**:
  - After creating widgets, passes the worker reference to both widgets:
    ```python
    list_widget.worker = worker
    grid_widget.worker = worker
    ```
  - This enables both widgets to trigger reconnection via refresh buttons

## Signal Flow on Refresh

```
User clicks Refresh Button
    ↓
on_refresh_clicked() calls worker.restart()
    ↓
worker.should_reconnect flag is set to True
    ↓
Worker thread detects flag on next iteration
    ↓
Releases old connection and attempts new one
    ↓
Emits connectionSuccess or connectionFailed signal
    ↓
UI is updated (frameReady shows video, or error message shown)
```

## Key Features

✅ **Minimum CPU Cost**
- Reuses existing thread and worker
- No new thread creation
- Worker sleeps 500ms during disconnected state

✅ **Clean UI Updates**
- Uses existing signals (connectionSuccess, connectionFailed)
- Both CameraFeedWidget and GridFeedWidget updated simultaneously
- Error messages clear on successful reconnection

✅ **No Thread Recreation**
- Existing QThread is reused
- Avoids overhead of thread creation/destruction
- Worker continues running in the same thread

## Usage

### For List View (Camera List)
1. Camera feed shows error message
2. Click the refresh button on the camera feed widget
3. System attempts to reconnect
4. UI updates with result

### For Grid View
1. Camera feed shows error message
2. Click the ↻ refresh button in the title bar
3. System attempts to reconnect
4. UI updates with result

## Testing

To test the refresh functionality:

1. Add a camera with an invalid/unavailable URL
2. Observe the error message in both list and grid views
3. Click the refresh button
4. When the camera becomes available, the feed should appear

Or:

1. Disconnect the camera physically/network while running
2. The error message appears automatically
3. Click refresh to retry connection once camera is back online

## Files Modified

1. `components/Camera_worker.py`
   - Added `should_reconnect` flag
   - Modified `run()` method to handle reconnection
   - Added `restart()` method

2. `components/Camera_list_widget.py`
   - Added `worker` attribute
   - Added `on_refresh_clicked()` method
   - Connected refresh button to the slot

3. `components/Grid_feed_widget.py`
   - Added `worker` attribute
   - Added refresh button (↻) to title bar
   - Added `on_refresh_clicked()` method

4. `main/MainWindow.py`
   - Modified `create_camera_items()` to pass worker references to widgets
