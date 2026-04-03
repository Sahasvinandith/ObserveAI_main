/**
 * ActionsPage.tsx
 * Web equivalent of the PyQt6 Actions page (index 5).
 *
 * Left panel: list of pose actions (from Actions_db/)
 *   - Create (upload JSON), Delete actions
 * Right panel: camera-to-action assignment manager
 *   - Two-panel layout matching CameraActionManagerDialog.py
 *   - Live action log of recent detections from WebSocket
 *   - Evidence image preview
 */

import React, { useState, useEffect } from 'react';
import { useAppStore } from '../store/appStore';
import type { ActionDetectedEvent } from '../types';

const S: Record<string, React.CSSProperties> = {
  page: { height: '100%', display: 'flex', flexDirection: 'column', background: '#0f0a14' },
  toolbar: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    background: '#130a1a', borderBottom: '1px solid #2e1040', flexShrink: 0,
  },
  toolbarTitle: { fontWeight: 600, fontSize: 14, color: '#ddd', flex: 1 },
  body: { flex: 1, display: 'flex', overflow: 'hidden' },
  leftPanel: {
    width: 260, minWidth: 260, borderRight: '1px solid #2e1040',
    display: 'flex', flexDirection: 'column', background: '#0d0714',
  },
  panelTitle: { padding: '10px 14px', fontSize: 12, fontWeight: 700, color: '#9a50aa', borderBottom: '1px solid #1e1030' },
  actionList: { flex: 1, overflowY: 'auto' },
  deleteBtn: {
    background: 'none', border: 'none', color: '#ff6666', cursor: 'pointer',
    fontSize: 14, padding: '0 4px', opacity: 0.7, lineHeight: 1,
  },
  panelActions: {
    padding: '8px 14px', borderTop: '1px solid #1e1030',
    display: 'flex', gap: 8,
  },
  midPanel: {
    width: 300, minWidth: 300, borderRight: '1px solid #2e1040',
    display: 'flex', flexDirection: 'column', background: '#0f0a14',
  },
  assignGrid: { display: 'flex', gap: 8, padding: '0 14px 8px', flex: 1, overflow: 'hidden' },
  camList: { flex: 1, overflowY: 'auto' },
  checkList: { flex: 1.5, overflowY: 'auto', background: '#0d0714', borderRadius: 4 },
  checkItem: {
    display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px',
    cursor: 'pointer', fontSize: 12, color: '#bbb',
    borderBottom: '1px solid #1e1030',
  },
  rightPanel: { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  logList: { flex: 1, overflowY: 'auto', padding: 8 },
  evidenceWrap: {
    borderTop: '1px solid #2e1040', padding: 12, flexShrink: 0,
    display: 'flex', gap: 12, alignItems: 'flex-start',
  },
  evidenceImg: { width: 200, height: 150, objectFit: 'cover', borderRadius: 6, background: '#000' },
  evidenceMeta: { flex: 1, fontSize: 12, color: '#aaa', lineHeight: 1.7 },
};

const btn = (variant?: 'primary' | 'danger'): React.CSSProperties => ({
  padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
  fontSize: 12, fontWeight: 600,
  background: variant === 'primary' ? '#7a3a8a' : variant === 'danger' ? '#5a1020' : '#2a1535',
  color: variant === 'danger' ? '#ff8888' : '#fff',
});

const actionItem = (selected: boolean): React.CSSProperties => ({
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  padding: '8px 14px', cursor: 'pointer', fontSize: 13,
  background: selected ? 'rgba(122,58,138,0.25)' : 'transparent',
  color: selected ? '#fff' : '#bbb',
  borderLeft: selected ? '3px solid #7a3a8a' : '3px solid transparent',
});

const camItem = (selected: boolean): React.CSSProperties => ({
  padding: '8px 12px', cursor: 'pointer', fontSize: 12,
  background: selected ? 'rgba(122,58,138,0.2)' : 'transparent',
  color: selected ? '#fff' : '#bbb',
  borderBottom: '1px solid #1e1030',
});

const logItem = (selected: boolean): React.CSSProperties => ({
  padding: '7px 12px', marginBottom: 3, borderRadius: 6, cursor: 'pointer',
  background: selected ? 'rgba(122,58,138,0.2)' : '#0d0714',
  border: `1px solid ${selected ? '#7a3a8a' : '#1e1030'}`,
  fontSize: 12, color: '#00ff88', fontFamily: 'monospace',
});

function formatTs(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString();
}

export default function ActionsPage() {
  const { actions, cameras, cameraActions, fetchActions, deleteAction, saveCameraActions, recentDetections, addToast } = useAppStore();
  const [selectedAction, setSelectedAction] = useState<string | null>(null);
  const [selectedCam, setSelectedCam] = useState<string | null>(cameras[0]?.name ?? null);
  const [localAssign, setLocalAssign] = useState<Record<string, string[]>>({});
  const [selectedDetection, setSelectedDetection] = useState<ActionDetectedEvent | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    fetchActions();
  }, []);

  useEffect(() => {
    if (cameras.length > 0 && !selectedCam) setSelectedCam(cameras[0].name);
  }, [cameras]);

  useEffect(() => {
    setLocalAssign({ ...cameraActions });
  }, [cameraActions]);

  const handleUpload = async () => {
    const name = prompt('Enter action name:');
    if (!name?.trim()) return;
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async () => {
      if (!input.files?.length) return;
      setUploading(true);
      const form = new FormData();
      form.append('file', input.files[0]);
      form.append('name', name.trim());
      try {
        const res = await fetch(`/api/actions/upload`, { method: 'POST', body: form });
        if (!res.ok) throw new Error();
        await fetchActions();
        addToast(`Action "${name}" created`, 'success');
      } catch {
        addToast('Failed to upload action', 'error');
      }
      setUploading(false);
    };
    input.click();
  };

  const handleDeleteAction = async (name: string) => {
    if (!confirm(`Delete action "${name}"?`)) return;
    await deleteAction(name);
    if (selectedAction === name) setSelectedAction(null);
  };

  const toggleActionForCam = (action: string) => {
    if (!selectedCam) return;
    setLocalAssign((prev) => {
      const current = prev[selectedCam] ?? [];
      const updated = current.includes(action)
        ? current.filter((a) => a !== action)
        : [...current, action];
      return { ...prev, [selectedCam]: updated };
    });
  };

  const handleSaveAssignments = async () => {
    await saveCameraActions(localAssign);
  };

  return (
    <div style={S.page}>
      <div style={S.toolbar}>
        <span style={S.toolbarTitle}>Actions</span>
        <button style={btn()} onClick={handleUpload} disabled={uploading}>
          {uploading ? 'Uploading...' : '+ Create Action'}
        </button>
        <button style={btn('primary')} onClick={handleSaveAssignments}>
          Save Assignments
        </button>
      </div>

      <div style={S.body}>
        {/* Left: Action Library */}
        <div style={S.leftPanel}>
          <div style={S.panelTitle}>Action Library ({actions.length})</div>
          <div style={S.actionList}>
            {actions.map((act) => (
              <div
                key={act}
                style={actionItem(selectedAction === act)}
                onClick={() => setSelectedAction(act)}
              >
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {act}
                </span>
                <button
                  style={S.deleteBtn}
                  onClick={(e) => { e.stopPropagation(); handleDeleteAction(act); }}
                  title="Delete action"
                >
                  ×
                </button>
              </div>
            ))}
            {actions.length === 0 && (
              <div style={{ padding: 16, color: '#555', fontSize: 12 }}>
                No actions defined. Click "Create Action" to upload a pose JSON.
              </div>
            )}
          </div>
        </div>

        {/* Middle: Camera-Action Assignments */}
        <div style={S.midPanel}>
          <div style={S.panelTitle}>Camera Assignments</div>
          {cameras.length === 0 ? (
            <div style={{ padding: 16, color: '#555', fontSize: 12 }}>
              No cameras configured. Add cameras first.
            </div>
          ) : (
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <div style={{ padding: '6px 14px', fontSize: 11, color: '#666', flexShrink: 0 }}>
                Select camera → check actions to assign
              </div>
              <div style={{ ...S.assignGrid, flexDirection: 'column' }}>
                {/* Camera list */}
                <div style={{ ...S.camList, background: '#0d0714', borderRadius: 4, maxHeight: 150, flexShrink: 0 }}>
                  {cameras.map((cam) => (
                    <div
                      key={cam.name}
                      style={camItem(selectedCam === cam.name)}
                      onClick={() => setSelectedCam(cam.name)}
                    >
                      {cam.name}
                      {(localAssign[cam.name]?.length ?? 0) > 0 && (
                        <span style={{ color: '#9a50aa', marginLeft: 6, fontSize: 10 }}>
                          ({localAssign[cam.name].length} actions)
                        </span>
                      )}
                    </div>
                  ))}
                </div>

                {/* Action checklist for selected camera */}
                {selectedCam && (
                  <div style={S.checkList}>
                    {actions.map((act) => {
                      const checked = (localAssign[selectedCam] ?? []).includes(act);
                      return (
                        <label key={act} style={S.checkItem} onClick={() => toggleActionForCam(act)}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleActionForCam(act)}
                            style={{ cursor: 'pointer' }}
                          />
                          <span style={{ color: checked ? '#fff' : '#bbb' }}>{act}</span>
                        </label>
                      );
                    })}
                    {actions.length === 0 && (
                      <div style={{ padding: 10, color: '#555', fontSize: 11 }}>
                        No actions in library yet.
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right: Recent Detections */}
        <div style={S.rightPanel}>
          <div style={S.panelTitle}>Recent Detections ({recentDetections.length})</div>

          <div style={S.logList}>
            {recentDetections.length === 0 && (
              <div style={{ padding: 20, color: '#555', fontSize: 12, textAlign: 'center' }}>
                No action detections yet. Detections will appear here in real time.
              </div>
            )}
            {recentDetections.map((det, i) => (
              <div
                key={i}
                style={logItem(selectedDetection === det)}
                onClick={() => setSelectedDetection(det)}
              >
                [{det.camera}] {det.person} → {det.action} at {formatTs(det.timestamp)}
              </div>
            ))}
          </div>

          {selectedDetection && (
            <div style={S.evidenceWrap}>
              {selectedDetection.evidence_url ? (
                <img
                  style={S.evidenceImg}
                  src={selectedDetection.evidence_url}
                  alt="Evidence"
                  onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
                />
              ) : (
                <div style={{ ...S.evidenceImg, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#555' }}>
                  No frame
                </div>
              )}
              <div style={S.evidenceMeta}>
                <div><strong style={{ color: '#9a50aa' }}>Action:</strong> {selectedDetection.action}</div>
                <div><strong style={{ color: '#9a50aa' }}>Camera:</strong> {selectedDetection.camera}</div>
                <div><strong style={{ color: '#9a50aa' }}>Person:</strong> {selectedDetection.person}</div>
                <div><strong style={{ color: '#9a50aa' }}>Time:</strong> {new Date(selectedDetection.timestamp * 1000).toLocaleString()}</div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
