/**
 * AddCameraModal.tsx
 * Web equivalent of AddCameraDialog.py.
 * Three tabs: Local Camera | Network/URL | Static Image
 * Shows available actions for assignment.
 */

import React, { useState, useEffect } from 'react';
import { useAppStore } from '../store/appStore';
import type { Camera } from '../types';

interface Props {
  camera?: Camera;  // If provided, we are in edit mode
  onClose: () => void;
  onSave: (data: Partial<Camera>) => void;
}

type Tab = 'local' | 'url' | 'image';

interface LocalCamera {
  name: string;
  device: string;
}

const S: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed', inset: 0,
    background: 'rgba(0,0,0,0.75)',
    zIndex: 1000,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  modal: {
    background: '#1a0f1f',
    border: '1px solid #4a1d5e',
    borderRadius: 12,
    width: 480,
    maxHeight: '90vh',
    overflow: 'auto',
    padding: 24,
    color: '#fff',
  },
  title: { fontSize: 18, fontWeight: 700, marginBottom: 16, color: '#e0c0f0' },
  label: { fontSize: 12, color: '#aaa', marginBottom: 4, display: 'block' },
  input: {
    width: '100%', padding: '8px 10px',
    background: '#2a1535', border: '1px solid #4a1d5e',
    borderRadius: 6, color: '#fff', fontSize: 13,
    marginBottom: 12, outline: 'none',
  },
  tabs: { display: 'flex', borderBottom: '1px solid #4a1d5e', marginBottom: 12 },
  row: { display: 'flex', gap: 12 },
  camList: {
    maxHeight: 140, overflowY: 'auto',
    background: '#0f0a14', border: '1px solid #4a1d5e',
    borderRadius: 6, marginBottom: 12,
  },
  checkList: {
    background: '#0f0a14', border: '1px solid #4a1d5e',
    borderRadius: 6, padding: '4px 0', maxHeight: 120, overflowY: 'auto',
    marginBottom: 12,
  },
  checkItem: {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '5px 12px', cursor: 'pointer', fontSize: 12, color: '#bbb',
  },
  divider: { height: 1, background: '#2e1040', margin: '12px 0' },
  hint: { fontSize: 11, color: '#666', marginTop: -8, marginBottom: 12, lineHeight: 1.5 },
  refreshBtn: {
    padding: '6px 12px', background: '#2a1535', border: '1px solid #4a1d5e',
    borderRadius: 4, color: '#ccc', cursor: 'pointer', fontSize: 12, marginBottom: 8,
  },
};

const tabStyle = (active: boolean): React.CSSProperties => ({
  padding: '8px 16px', cursor: 'pointer', fontSize: 13,
  color: active ? '#fff' : '#888',
  background: active ? 'rgba(122,58,138,0.3)' : 'transparent',
  borderBottom: active ? '2px solid #7a3a8a' : '2px solid transparent',
  userSelect: 'none',
});

const camItemStyle = (selected: boolean): React.CSSProperties => ({
  padding: '8px 12px', cursor: 'pointer', fontSize: 12,
  background: selected ? 'rgba(122,58,138,0.3)' : 'transparent',
  color: selected ? '#fff' : '#bbb',
  borderBottom: '1px solid #1a0f25',
});

const btnStyle = (primary?: boolean): React.CSSProperties => ({
  padding: '9px 20px', borderRadius: 6, cursor: 'pointer',
  fontSize: 13, fontWeight: 600, border: 'none',
  background: primary ? '#7a3a8a' : '#2a1535',
  color: primary ? '#fff' : '#ccc',
  flex: 1,
});

export default function AddCameraModal({ camera, onClose, onSave }: Props) {
  const { actions } = useAppStore();
  const isEdit = !!camera;

  const [name, setName] = useState(camera?.name ?? '');
  const [tab, setTab] = useState<Tab>(isEdit ? 'url' : 'local');
  const [urlInput, setUrlInput] = useState(camera?.url ?? '');
  const [imageInput, setImageInput] = useState('');
  const [fov, setFov] = useState(camera?.fov ?? 70);
  const [viewRange, setViewRange] = useState(camera?.view_range ?? 200);
  const [selectedActions, setSelectedActions] = useState<string[]>(camera?.actions ?? []);
  const [localCams, setLocalCams] = useState<LocalCamera[]>([]);
  const [selectedLocal, setSelectedLocal] = useState<number>(-1);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (tab === 'local') {
      refreshLocalCams();
    }
  }, [tab]);

  const refreshLocalCams = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/detect-cameras');
      const cams: LocalCamera[] = await res.json();
      setLocalCams(cams);
      if (cams.length > 0 && selectedLocal < 0) {
        setSelectedLocal(0);
        if (!name) setName(cams[0].name.split(':')[0].trim());
      }
    } catch {
      setLocalCams([]);
    }
    setLoading(false);
  };

  const toggleAction = (action: string) => {
    setSelectedActions((prev) =>
      prev.includes(action) ? prev.filter((a) => a !== action) : [...prev, action]
    );
  };

  const getUrl = (): string => {
    if (tab === 'local') {
      if (selectedLocal >= 0 && selectedLocal < localCams.length)
        return localCams[selectedLocal].device;
      return '';
    }
    if (tab === 'url') return urlInput.trim();
    if (tab === 'image') return imageInput ? `image://${imageInput}` : '';
    return '';
  };

  const handleSave = () => {
    const url = getUrl();
    if (!name.trim()) { alert('Camera name is required.'); return; }
    if (!url) { alert('Please specify a camera source.'); return; }
    onSave({
      name: name.trim(),
      url,
      fov,
      view_range: viewRange,
      actions: selectedActions,
    });
  };

  return (
    <div style={S.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={S.modal}>
        <div style={S.title}>{isEdit ? `Configure: ${camera!.name}` : 'Add Camera'}</div>

        <label style={S.label}>Camera Name</label>
        <input
          style={S.input}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Lobby Camera"
        />

        <div style={S.tabs}>
          <div style={tabStyle(tab === 'local')} onClick={() => setTab('local')}>Local Camera</div>
          <div style={tabStyle(tab === 'url')} onClick={() => setTab('url')}>Network / URL</div>
          <div style={tabStyle(tab === 'image')} onClick={() => setTab('image')}>Static Image</div>
        </div>

        {tab === 'local' && (
          <>
            <button style={S.refreshBtn} onClick={refreshLocalCams} disabled={loading}>
              {loading ? 'Detecting...' : 'Refresh Camera List'}
            </button>
            <div style={S.camList}>
              {localCams.length === 0 && (
                <div style={{ padding: '10px 12px', color: '#666', fontSize: 12 }}>
                  {loading ? 'Scanning...' : 'No local cameras detected.'}
                </div>
              )}
              {localCams.map((cam, i) => (
                <div
                  key={cam.device}
                  style={camItemStyle(selectedLocal === i)}
                  onClick={() => {
                    setSelectedLocal(i);
                    if (!name) setName(cam.name.split(':')[0].trim());
                  }}
                >
                  {cam.name} [{cam.device}]
                </div>
              ))}
            </div>
          </>
        )}

        {tab === 'url' && (
          <>
            <label style={S.label}>Camera URL or device path</label>
            <input
              style={S.input}
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="rtsp://192.168.1.10/stream  or  /dev/video2  or  0"
            />
            <div style={S.hint}>
              Examples: rtsp://user:pass@host/stream · http://host:8080/video · /dev/video2 · 0
            </div>
          </>
        )}

        {tab === 'image' && (
          <>
            <label style={S.label}>Image file path (absolute)</label>
            <input
              style={S.input}
              value={imageInput}
              onChange={(e) => setImageInput(e.target.value)}
              placeholder="/path/to/image.jpg"
            />
            <div style={S.hint}>
              The image will be looped as a static feed — useful for debugging detection.
            </div>
          </>
        )}

        <div style={S.divider} />

        <div style={S.row}>
          <div style={{ flex: 1 }}>
            <label style={S.label}>View Angle (FOV)</label>
            <input
              type="number" min={10} max={180} step={5}
              style={S.input} value={fov}
              onChange={(e) => setFov(Number(e.target.value))}
            />
          </div>
          <div style={{ flex: 1 }}>
            <label style={S.label}>View Range (px)</label>
            <input
              type="number" min={50} max={1000} step={10}
              style={S.input} value={viewRange}
              onChange={(e) => setViewRange(Number(e.target.value))}
            />
          </div>
        </div>

        {actions.length > 0 && (
          <>
            <label style={S.label}>Actions to Track</label>
            <div style={S.checkList}>
              {actions.map((action) => (
                <label key={action} style={S.checkItem}>
                  <input
                    type="checkbox"
                    checked={selectedActions.includes(action)}
                    onChange={() => toggleAction(action)}
                  />
                  {action}
                </label>
              ))}
            </div>
          </>
        )}

        <div style={S.row}>
          <button style={btnStyle(false)} onClick={onClose}>Cancel</button>
          <button style={btnStyle(true)} onClick={handleSave}>
            {isEdit ? 'Update' : 'Add Camera'}
          </button>
        </div>
      </div>
    </div>
  );
}
