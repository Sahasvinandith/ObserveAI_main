---
name: PyQt6 to Web Widget Mappings
description: Mapping of every major PyQt6 widget/pattern to its web equivalent, with gotchas
type: project
---

# PyQt6 to Web Widget Mappings

## Core Layout
- QMainWindow + QStackedWidget (6 pages) → Sidebar nav + React router state (no URL routing needed)
- QGridLayout (camera grid) → CSS Grid with auto-fill columns, GridFeedWidget → CameraFeed React component
- QListWidget (cam_list) → Sidebar thumbnail list with MJPEG img tag
- QGraphicsScene (floor map, drag_area) → HTML5 Canvas with pan/zoom

## Camera Feed
- GridFeedWidget (PyQt6) → CameraFeed.tsx: <img> tag pointed at /api/cameras/{name}/stream (MJPEG)
- AI-annotated frames come from DetectionSystem output_callback — server encodes and streams via MJPEG
- The output_callback in DetectionSystem already receives annotated numpy frames — perfect for MJPEG encoding
- GOTCHA: CameraWorker uses Qt threads and QThread.msleep — must be adapted to pure Python threading

## Dialogs
- AddCameraDialog → Modal overlay component with Local/Network/Image tabs
- CameraActionManagerDialog → Modal with two-panel layout
- ImageClickDialog (calibration) → Canvas-based click capture in modal

## Forms
- QDoubleSpinBox → <input type="number" step="0.01">
- QSlider → <input type="range">
- QComboBox → <select>
- QListWidget with checkboxes → Checkbox list component

## Database Viewer
- DatabaseViewer (QWidget) → FaceDatabase.tsx: left panel (person list), right panel (image gallery)
- Gallery thumbnails: served from /api/faces/{person}/images
- Rename via PATCH /api/faces/{person}/rename

## Logs Page  
- QDateTimeEdit → <input type="datetime-local">
- QTextBrowser → <pre> or scrollable div with log entries

## Actions Page
- actions_list (QListWidget) → Simple ul/li list
- action_log_list (QListWidget with evidence) → List with clickable rows showing preview image
- Recent detections preview → <img> tag in right panel

## Floor Map (Camera Settings page)
- QGraphicsScene with CameraItems (FOV cones), WallItems, person dots → HTML5 Canvas
- Camera icon + FOV polygon ray casting → Canvas drawing with JavaScript geometry
- Person dots (QGraphicsEllipseItem) → canvas fillArc with colors
- Wall items → canvas fillRect with rotation transform
- Drag/drop cameras → mousedown/mousemove/mouseup on canvas
- Ctrl+wheel rotate → wheel event with ctrlKey modifier
- GOTCHA: Ray casting FOV is complex — replicate the exact algorithm in JS for visual parity

## TypeScript Gotchas (React inline styles)
- GOTCHA: TypeScript strict mode rejects `flexDirection: 'column'` as string (not FlexDirection type)
- Fix: Annotate style const as `Record<string, React.CSSProperties>` or individual functions return `React.CSSProperties`
- Fix: Move dynamic style functions (those taking parameters) OUT of the S object — TypeScript can't type-check mixed plain object + function types in a Record<string, CSSProperties>
- GOTCHA: `position: 'fixed'` and `overflowY: 'auto'` also fail without explicit typing
- Pattern used: `const S: Record<string, React.CSSProperties> = { ... }` for static styles + separate typed functions for dynamic ones
- GOTCHA: `title` is not a valid React.CSSProperties key — must use HTML attribute on the element, not in the style object
