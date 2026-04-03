/**
 * CameraMapPage.tsx
 * Replaces the PyQt6 QGraphicsScene floor map (page 0: "Camera Settings").
 *
 * Features:
 *  - HTML5 Canvas showing a grid floor plan
 *  - Draggable camera icons with FOV cone visualization
 *  - Wall placement (click-drag to draw walls)
 *  - Person position dots (received via WebSocket)
 *  - Save/Load layout via API
 *  - Camera position updates sent back to server
 */

import React, { useRef, useEffect, useState } from 'react';
import { useAppStore } from '../store/appStore';
import type { Camera } from '../types';

const GRID_SIZE = 30; // pixels per meter (matches settings default)
const DOT_COLORS = [
  '#ff6464', '#64ff64', '#6464ff', '#ffff64',
  '#ff64ff', '#64ffff', '#ffa500', '#9400d3',
];

interface CanvasCamera {
  name: string;
  x: number;
  y: number;
  rot: number; // degrees
  fov: number;
  view_range: number;
  url: string;
  actions: string[];
}

interface Wall {
  x: number; y: number; w: number; h: number; rot: number;
}

const S: Record<string, React.CSSProperties> = {
  page: { height: '100%', display: 'flex', flexDirection: 'column', background: '#0f0a14' },
  toolbar: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    background: '#130a1a', borderBottom: '1px solid #2e1040', flexShrink: 0,
  },
  toolbarTitle: { fontWeight: 600, fontSize: 14, color: '#ddd', flex: 1 },
  canvasWrap: { flex: 1, overflow: 'auto', cursor: 'crosshair' },
  hint: {
    position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)',
    background: 'rgba(19,10,26,0.85)', border: '1px solid #4a1d5e',
    color: '#aaa', fontSize: 11, padding: '4px 12px', borderRadius: 4,
    pointerEvents: 'none', whiteSpace: 'nowrap',
  },
  wrap: { flex: 1, position: 'relative', overflow: 'hidden' },
  legend: {
    position: 'absolute', top: 8, right: 8,
    background: 'rgba(19,10,26,0.9)', border: '1px solid #2e1040',
    borderRadius: 6, padding: '8px 12px', fontSize: 11, color: '#888', lineHeight: 1.8,
  },
};

const btnStyle = (active?: boolean): React.CSSProperties => ({
  padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
  fontSize: 12, fontWeight: 600,
  background: active ? '#7a3a8a' : '#2a1535',
  color: active ? '#fff' : '#ccc',
});

function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number) {
  ctx.strokeStyle = '#1e1430';
  ctx.lineWidth = 0.5;
  for (let x = 0; x < w; x += GRID_SIZE) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = 0; y < h; y += GRID_SIZE) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  // Meter labels every 5 grid cells
  ctx.fillStyle = '#2a1840';
  ctx.font = '9px monospace';
  for (let x = 0; x < w; x += GRID_SIZE * 5) {
    ctx.fillText(`${x / GRID_SIZE}m`, x + 2, 10);
  }
}

function drawFOVCone(
  ctx: CanvasRenderingContext2D,
  x: number, y: number,
  rotDeg: number, fovDeg: number, range: number
) {
  const startAngle = ((rotDeg - fovDeg / 2) * Math.PI) / 180;
  const endAngle = ((rotDeg + fovDeg / 2) * Math.PI) / 180;

  ctx.save();
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.arc(x, y, range, startAngle, endAngle);
  ctx.closePath();
  ctx.fillStyle = 'rgba(255, 255, 0, 0.08)';
  ctx.strokeStyle = 'rgba(255, 255, 0, 0.4)';
  ctx.lineWidth = 1;
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function drawCamera(
  ctx: CanvasRenderingContext2D,
  cam: CanvasCamera,
  selected: boolean
) {
  const { x, y } = cam;

  // FOV cone
  drawFOVCone(ctx, x, y, cam.rot - 90, cam.fov, cam.view_range);

  // Camera icon (circle + dot)
  ctx.save();
  ctx.beginPath();
  ctx.arc(x, y, 10, 0, Math.PI * 2);
  ctx.fillStyle = selected ? '#9a50aa' : '#5a2070';
  ctx.fill();
  ctx.strokeStyle = selected ? '#dda0ff' : '#7a3a8a';
  ctx.lineWidth = selected ? 2 : 1.5;
  ctx.stroke();

  // Direction indicator
  const dirX = x + 12 * Math.cos(((cam.rot - 90) * Math.PI) / 180);
  const dirY = y + 12 * Math.sin(((cam.rot - 90) * Math.PI) / 180);
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(dirX, dirY);
  ctx.strokeStyle = '#ffdd00';
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.restore();

  // Label
  ctx.font = '11px system-ui';
  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'center';
  ctx.fillText(cam.name, x, y + 22);
}

function drawWall(ctx: CanvasRenderingContext2D, wall: Wall) {
  ctx.save();
  ctx.translate(wall.x + wall.w / 2, wall.y + wall.h / 2);
  ctx.rotate((wall.rot * Math.PI) / 180);
  ctx.fillStyle = 'rgba(200,200,200,0.3)';
  ctx.strokeStyle = '#888';
  ctx.lineWidth = 1;
  ctx.fillRect(-wall.w / 2, -wall.h / 2, wall.w, wall.h);
  ctx.strokeRect(-wall.w / 2, -wall.h / 2, wall.w, wall.h);
  ctx.restore();
}

export default function CameraMapPage() {
  const { cameras, updateCamera, addToast } = useAppStore();
  const personDots = useAppStore((s) => s.personDots);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [canvasCams, setCanvasCams] = useState<CanvasCamera[]>([]);
  const [walls, setWalls] = useState<Wall[]>([]);
  const [selectedCam, setSelectedCam] = useState<string | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState({ ox: 0, oy: 0 });
  const [addWallMode, setAddWallMode] = useState(false);
  const [wallStart, setWallStart] = useState<{ x: number; y: number } | null>(null);
  const [wallPreview, setWallPreview] = useState<Wall | null>(null);

  const CANVAS_W = 1400;
  const CANVAS_H = 900;

  // Sync cameras from store to local canvas state
  useEffect(() => {
    setCanvasCams(
      cameras.map((c) => ({
        name: c.name,
        x: c.pos[0],
        y: c.pos[1],
        rot: c.rot,
        fov: c.fov,
        view_range: c.view_range,
        url: c.url,
        actions: c.actions,
      }))
    );
  }, [cameras]);

  // Redraw canvas whenever state changes
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);
    ctx.fillStyle = '#0f0a14';
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);

    drawGrid(ctx, CANVAS_W, CANVAS_H);

    walls.forEach((w) => drawWall(ctx, w));
    if (wallPreview) drawWall(ctx, wallPreview);

    canvasCams.forEach((cam) => drawCamera(ctx, cam, cam.name === selectedCam));

    // Person position dots
    const now = Date.now();
    personDots.forEach((dot) => {
      if (now - dot.lastSeen > 10000) return; // Hide stale dots after 10s
      const color = DOT_COLORS[dot.global_id % DOT_COLORS.length];
      ctx.save();
      ctx.beginPath();
      ctx.arc(dot.x, dot.y, 8, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = '#000';
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.font = '10px monospace';
      ctx.fillStyle = '#fff';
      ctx.textAlign = 'center';
      ctx.fillText(`G${dot.global_id}`, dot.x, dot.y + 3);
      ctx.restore();
    });
  }, [canvasCams, walls, wallPreview, selectedCam, personDots]);

  const getCanvasPos = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };
  };

  const hitTestCamera = (x: number, y: number): string | null => {
    for (const cam of canvasCams) {
      const dx = cam.x - x;
      const dy = cam.y - y;
      if (dx * dx + dy * dy <= 12 * 12) return cam.name;
    }
    return null;
  };

  const onMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const pos = getCanvasPos(e);

    if (addWallMode) {
      setWallStart(pos);
      return;
    }

    const hit = hitTestCamera(pos.x, pos.y);
    if (hit) {
      const cam = canvasCams.find((c) => c.name === hit)!;
      setDragging(hit);
      setDragOffset({ ox: pos.x - cam.x, oy: pos.y - cam.y });
      setSelectedCam(hit);
    } else {
      setSelectedCam(null);
    }
  };

  const onMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const pos = getCanvasPos(e);

    if (addWallMode && wallStart) {
      const x = Math.min(wallStart.x, pos.x);
      const y = Math.min(wallStart.y, pos.y);
      const w = Math.abs(pos.x - wallStart.x);
      const h = Math.abs(pos.y - wallStart.y);
      setWallPreview({ x, y, w: Math.max(w, 10), h: Math.max(h, 10), rot: 0 });
      return;
    }

    if (dragging) {
      setCanvasCams((prev) =>
        prev.map((c) =>
          c.name === dragging
            ? { ...c, x: pos.x - dragOffset.ox, y: pos.y - dragOffset.oy }
            : c
        )
      );
    }
  };

  const onMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const pos = getCanvasPos(e);

    if (addWallMode && wallStart) {
      if (wallPreview) {
        setWalls((prev) => [...prev, wallPreview]);
        setWallPreview(null);
      }
      setWallStart(null);
      return;
    }

    if (dragging) {
      // Push updated position to server
      const cam = canvasCams.find((c) => c.name === dragging)!;
      updateCamera(dragging, { pos: [cam.x, cam.y] }).catch(() => {});
      setDragging(null);
    }
  };

  const onWheel = (e: React.WheelEvent<HTMLCanvasElement>) => {
    if (e.ctrlKey && selectedCam) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 5 : -5;
      setCanvasCams((prev) =>
        prev.map((c) => (c.name === selectedCam ? { ...c, rot: c.rot + delta } : c))
      );
    }
  };

  const handleSaveLayout = async () => {
    try {
      const res = await fetch('/api/layout/save', { method: 'POST' });
      if (!res.ok) throw new Error();
      addToast('Layout saved', 'success');
    } catch {
      addToast('Failed to save layout', 'error');
    }
  };

  const handleLoadLayout = async () => {
    try {
      const res = await fetch('/api/layout/load', { method: 'POST' });
      if (!res.ok) throw new Error();
      addToast('Layout loaded', 'success');
    } catch {
      addToast('No saved layout found or load failed', 'error');
    }
  };

  const updateSelectedRot = (delta: number) => {
    if (!selectedCam) return;
    setCanvasCams((prev) =>
      prev.map((c) => (c.name === selectedCam ? { ...c, rot: c.rot + delta } : c))
    );
    const cam = canvasCams.find((c) => c.name === selectedCam);
    if (cam) {
      updateCamera(selectedCam, { rot: cam.rot + delta }).catch(() => {});
    }
  };

  const selectedCamData = canvasCams.find((c) => c.name === selectedCam);

  return (
    <div style={S.page}>
      <div style={S.toolbar}>
        <span style={S.toolbarTitle}>Camera Map</span>
        <button style={btnStyle(addWallMode)} onClick={() => setAddWallMode((v) => !v)}>
          {addWallMode ? 'Cancel Wall' : '+ Add Wall'}
        </button>
        {walls.length > 0 && (
          <button style={btnStyle()} onClick={() => setWalls([])}>
            Clear Walls
          </button>
        )}
        <button style={btnStyle()} onClick={handleSaveLayout}>Save Layout</button>
        <button style={btnStyle()} onClick={handleLoadLayout}>Load Layout</button>
      </div>

      <div style={S.wrap}>
        <div style={S.canvasWrap}>
          <canvas
            ref={canvasRef}
            width={CANVAS_W}
            height={CANVAS_H}
            style={{ display: 'block', cursor: addWallMode ? 'crosshair' : (dragging ? 'grabbing' : 'default') }}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onWheel={onWheel}
          />
        </div>

        {/* Selected camera panel */}
        {selectedCamData && (
          <div style={{
            position: 'absolute', top: 8, left: 8,
            background: 'rgba(19,10,26,0.95)', border: '1px solid #4a1d5e',
            borderRadius: 8, padding: 14, color: '#ddd', fontSize: 12, minWidth: 200,
          }}>
            <div style={{ fontWeight: 700, marginBottom: 8, color: '#e0c0f0' }}>
              {selectedCamData.name}
            </div>
            <div>Pos: ({selectedCamData.x.toFixed(0)}, {selectedCamData.y.toFixed(0)})</div>
            <div>Rotation: {selectedCamData.rot.toFixed(0)}°</div>
            <div>FOV: {selectedCamData.fov}°</div>
            <div>Range: {selectedCamData.view_range}px</div>
            <div style={{ marginTop: 10, display: 'flex', gap: 6 }}>
              <button style={btnStyle()} onClick={() => updateSelectedRot(-5)}>↺ -5°</button>
              <button style={btnStyle()} onClick={() => updateSelectedRot(5)}>↻ +5°</button>
            </div>
            <div style={{ marginTop: 4, fontSize: 10, color: '#666' }}>
              Ctrl+Scroll to rotate
            </div>
          </div>
        )}

        <div style={S.legend}>
          <div>Drag camera icon to reposition</div>
          <div>Ctrl+Scroll to rotate selected camera</div>
          <div style={{ color: '#ffdd00', marginTop: 2 }}>► Direction indicator</div>
          <div style={{ color: 'rgba(255,255,0,0.6)' }}>◐ FOV cone</div>
          <div style={{ color: '#ff6464', marginTop: 2 }}>● Person dot (from AI)</div>
        </div>

        {addWallMode && (
          <div style={S.hint}>
            Click and drag to draw a wall. Release to place.
          </div>
        )}
      </div>
    </div>
  );
}
