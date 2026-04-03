/**
 * CameraFeedPage.tsx
 * The main surveillance grid showing all camera feeds with AI overlays.
 * Equivalent to the "Camera Feed" page (index 1) in the original PyQt6 QStackedWidget.
 *
 * Each camera tile:
 *  - Title bar with camera name + status dot + action buttons
 *  - MJPEG <img> stream showing annotated frames from DetectionSystem
 *  - Fullscreen toggle (mirrors GridFeedWidget.handle_maximize_toggle)
 *  - Refresh / Configure buttons
 */

import React, { useState } from 'react';
import { useAppStore } from '../store/appStore';
import type { Camera } from '../types';
import AddCameraModal from './AddCameraModal';

const S: Record<string, React.CSSProperties> = {
  page: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    background: '#0f0a14',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 16px',
    background: '#130a1a',
    borderBottom: '1px solid #2e1040',
    flexShrink: 0,
  },
  toolbarTitle: { fontWeight: 600, fontSize: 14, color: '#ddd', flex: 1 },
  fullscreenGrid: {
    flex: 1,
    display: 'flex',
    padding: 0,
    overflow: 'hidden',
  },
  tile: {
    background: '#000',
    border: '1px solid #2e1040',
    borderRadius: 6,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    minHeight: 200,
    position: 'relative',
  },
  tileBar: {
    display: 'flex',
    alignItems: 'center',
    padding: '4px 8px',
    background: '#1a0f25',
    gap: 6,
    flexShrink: 0,
    height: 30,
  },
  cameraName: { flex: 1, fontSize: 12, fontWeight: 600, color: '#ddd', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  iconBtn: {
    background: 'none', border: 'none', cursor: 'pointer',
    color: '#888', fontSize: 14, padding: '2px 4px', borderRadius: 4,
    lineHeight: 1,
  },
  feed: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#000',
    overflow: 'hidden',
  },
  streamImg: {
    width: '100%', height: '100%',
    objectFit: 'contain',
  },
  noFeed: {
    color: '#444', fontSize: 13, textAlign: 'center',
    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
  },
  emptyState: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 16,
    color: '#555',
  },
  colSelector: {
    display: 'flex', gap: 4, alignItems: 'center',
  },
  aiTag: {
    padding: '1px 5px', background: '#00aa55', borderRadius: 3,
    fontSize: 10, color: '#fff', fontWeight: 700,
  },
};

const btnStyle = (variant?: 'primary' | 'danger'): React.CSSProperties => ({
  padding: '6px 14px',
  borderRadius: 6,
  border: 'none',
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 600,
  background:
    variant === 'primary' ? '#7a3a8a' :
    variant === 'danger' ? '#5a1020' : '#2a1535',
  color: variant === 'danger' ? '#ff8888' : '#fff',
});

const gridStyle = (cols: number): React.CSSProperties => ({
  flex: 1,
  display: 'grid',
  gridTemplateColumns: `repeat(${cols}, 1fr)`,
  gap: 8,
  padding: 8,
  overflow: 'auto',
  alignContent: 'start',
});

const statusDot = (status: string): React.CSSProperties => ({
  width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
  background:
    status === 'connected' ? '#00ff88' :
    status === 'connecting' ? '#ffaa00' : '#ff4444',
});

const colBtn = (active: boolean): React.CSSProperties => ({
  width: 28, height: 28, borderRadius: 4,
  background: active ? '#7a3a8a' : '#2a1535',
  border: '1px solid #4a1d5e',
  color: active ? '#fff' : '#aaa',
  cursor: 'pointer', fontSize: 12, fontWeight: 600,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
});

function CameraTile({
  camera,
  fullscreen,
  onToggleFullscreen,
  onConfigure,
}: {
  camera: Camera;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onConfigure: (cam: Camera) => void;
}) {
  const { restartCamera } = useAppStore();
  const streamUrl = `/api/cameras/${encodeURIComponent(camera.name)}/stream`;

  const tileStyle: React.CSSProperties = {
    ...S.tile,
    ...(fullscreen ? { flex: 1, borderRadius: 0, minHeight: 0 } : {}),
  };

  return (
    <div style={tileStyle}>
      <div style={S.tileBar}>
        <div style={statusDot(camera.status)} title={camera.status} />
        <span style={S.cameraName} title={camera.name}>{camera.name}</span>
        {camera.ai_running && <span style={S.aiTag}>AI</span>}
        <button
          style={S.iconBtn}
          title="Restart camera connection"
          onClick={() => restartCamera(camera.name)}
        >
          ↻
        </button>
        <button
          style={S.iconBtn}
          title="Configure camera"
          onClick={() => onConfigure(camera)}
        >
          ⚙
        </button>
        <button
          style={S.iconBtn}
          title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          onClick={onToggleFullscreen}
        >
          {fullscreen ? '⊡' : '⊞'}
        </button>
      </div>

      <div style={S.feed}>
        {camera.status === 'connected' || camera.status === 'connecting' ? (
          <img
            style={S.streamImg}
            src={streamUrl}
            alt={camera.name}
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
        ) : (
          <div style={S.noFeed}>
            <span style={{ fontSize: 32 }}>📡</span>
            <div>{camera.status === 'error' ? 'Connection Error' : 'Disconnected'}</div>
            <button
              style={{ ...btnStyle(), fontSize: 11 }}
              onClick={() => restartCamera(camera.name)}
            >
              Retry
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function CameraFeedPage() {
  const { cameras, addCamera, updateCamera, deleteCamera, finishSetup, addToast } = useAppStore();
  const [showAdd, setShowAdd] = useState(false);
  const [editCamera, setEditCamera] = useState<Camera | null>(null);
  const [fullscreenCam, setFullscreenCam] = useState<string | null>(null);
  const [cols, setCols] = useState(3);
  const [setupMode, setSetupMode] = useState(false);

  const handleSaveCamera = async (data: Partial<Camera>) => {
    try {
      if (editCamera) {
        await updateCamera(editCamera.name, data);
      } else {
        await addCamera(data);
      }
    } catch (e: unknown) {
      const err = e as Error;
      addToast(err.message || 'Failed to save camera', 'error');
    }
    setShowAdd(false);
    setEditCamera(null);
  };

  const handleFinishSetup = async () => {
    await finishSetup();
    setSetupMode(false);
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete camera "${name}"?`)) return;
    await deleteCamera(name);
    if (fullscreenCam === name) setFullscreenCam(null);
  };

  const isFullscreen = !!fullscreenCam;
  const displayCams = isFullscreen
    ? cameras.filter((c) => c.name === fullscreenCam)
    : cameras;

  return (
    <div style={S.page}>
      {/* Toolbar */}
      <div style={S.toolbar}>
        <span style={S.toolbarTitle}>Camera Feed</span>

        {!isFullscreen && (
          <>
            <div style={S.colSelector}>
              <span style={{ fontSize: 11, color: '#666', marginRight: 2 }}>Cols:</span>
              {[1, 2, 3, 4].map((n) => (
                <button key={n} style={colBtn(cols === n)} onClick={() => setCols(n)}>
                  {n}
                </button>
              ))}
            </div>

            {setupMode ? (
              <button style={btnStyle('primary')} onClick={handleFinishSetup}>
                Start AI
              </button>
            ) : (
              <button style={btnStyle()} onClick={() => setSetupMode(true)}>
                Configure Cameras
              </button>
            )}
            <button style={btnStyle('primary')} onClick={() => setShowAdd(true)}>
              + Add Camera
            </button>
          </>
        )}

        {isFullscreen && (
          <button style={btnStyle()} onClick={() => setFullscreenCam(null)}>
            Exit Fullscreen
          </button>
        )}
      </div>

      {/* Grid or empty state */}
      {cameras.length === 0 ? (
        <div style={S.emptyState}>
          <span style={{ fontSize: 48 }}>📹</span>
          <div style={{ fontSize: 16, fontWeight: 600 }}>No cameras configured</div>
          <div style={{ fontSize: 13, color: '#666' }}>
            Click "Add Camera" to get started.
          </div>
          <button style={btnStyle('primary')} onClick={() => setShowAdd(true)}>
            + Add Camera
          </button>
        </div>
      ) : isFullscreen ? (
        <div style={S.fullscreenGrid}>
          {displayCams.map((cam) => (
            <CameraTile
              key={cam.name}
              camera={cam}
              fullscreen={true}
              onToggleFullscreen={() => setFullscreenCam(null)}
              onConfigure={setEditCamera}
            />
          ))}
        </div>
      ) : (
        <div style={gridStyle(Math.min(cols, cameras.length || 1))}>
          {displayCams.map((cam) => (
            <div key={cam.name} style={{ position: 'relative' }}>
              <CameraTile
                camera={cam}
                fullscreen={false}
                onToggleFullscreen={() =>
                  setFullscreenCam(fullscreenCam === cam.name ? null : cam.name)
                }
                onConfigure={setEditCamera}
              />
              {setupMode && (
                <button
                  style={{
                    ...btnStyle('danger'),
                    position: 'absolute', top: 35, right: 8, fontSize: 11, zIndex: 5,
                  }}
                  onClick={() => handleDelete(cam.name)}
                >
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Add / Edit Modal */}
      {(showAdd || editCamera) && (
        <AddCameraModal
          camera={editCamera ?? undefined}
          onClose={() => { setShowAdd(false); setEditCamera(null); }}
          onSave={handleSaveCamera}
        />
      )}
    </div>
  );
}
