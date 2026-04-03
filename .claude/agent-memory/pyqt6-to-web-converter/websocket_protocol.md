---
name: WebSocket Protocol Schemas
description: Message schemas for all WebSocket connections in the web migration
type: project
---

# WebSocket Protocol Schemas

## Unified Endpoint: /ws/events
Single WebSocket endpoint that broadcasts all event types to all connected clients.
Connection URL: `ws://localhost:8000/ws/events` (production) or proxied via Vite dev server.

### Server → Client messages:

**Init** (sent on connect):
```json
{
  "type": "init",
  "cameras": [...Camera objects...],
  "settings": {...AppSettings...}
}
```

**Action Detected**:
```json
{
  "type": "action_detected",
  "camera": "HD Webcam",
  "person": "User_1",
  "action": "right_check_smoke",
  "timestamp": 1711234567.89,
  "evidence_url": "/api/evidence/act_1711234567_HD_Webcam.jpg"
}
```

**Person Position Update** (from GlobalPersonTracker.position_callback):
```json
{
  "type": "person_update",
  "global_id": 3,
  "camera": "HD Webcam",
  "x": 450.5,
  "y": 320.1
}
```

**Camera Status Change**:
```json
{
  "type": "camera_status",
  "camera": "HD Webcam",
  "status": "connected" | "disconnected" | "error",
  "message": "Failed to open: /dev/video0"
}
```

**System Status** (broadcast every 3 seconds):
```json
{
  "type": "system_status",
  "cpu_percent": 45.2,
  "memory_percent": 67.1,
  "cameras": {
    "HD Webcam": {"status": "connected", "ai_running": true}
  }
}
```

**Keepalive Ping**:
```json
{"type": "ping"}
```

### Client → Server messages:
```json
{"type": "ping"}   → server replies with {"type": "pong"}
```

## MJPEG Stream
- Endpoint: GET /api/cameras/{name}/stream
- Content-Type: `multipart/x-mixed-replace; boundary=frame`
- Each frame boundary: `--frame\r\nContent-Type: image/jpeg\r\n\r\n{jpeg_bytes}\r\n`
- Used via: `<img src="/api/cameras/{name}/stream">` in React (browser handles MJPEG natively)
- The DetectionSystem output_callback receives annotated BGR numpy arrays
- Server encodes to JPEG (quality=75) and pushes into per-camera asyncio.Queue(maxsize=2)
- Thread-safe handoff via call_soon_threadsafe(_push_frame_sync)
- Queue drain: old frames dropped if queue full (latency over completeness)
- Keepalive: empty boundary sent every 5s timeout to prevent connection drop

## Frontend WebSocket Client (appStore.ts)
- Automatic reconnect: 3-second delay on disconnect
- ping/pong handled inline
- `init` event populates cameras + settings immediately on connect
- `system_status` updates camera statuses in real time
- `action_detected` shows toast + appends to recentDetections[]
- `person_update` updates personDots Map<global_id, PersonDot> for CameraMapPage canvas
