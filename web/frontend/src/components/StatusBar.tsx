/**
 * StatusBar.tsx
 * Top bar showing system stats (CPU/Memory) and quick camera status overview.
 */

import React from 'react';
import { useAppStore } from '../store/appStore';

const S: Record<string, React.CSSProperties> = {
  bar: {
    height: 36,
    background: '#0d0714',
    borderBottom: '1px solid #2e1040',
    display: 'flex',
    alignItems: 'center',
    padding: '0 16px',
    gap: 24,
    fontSize: 12,
    color: '#888',
    flexShrink: 0,
  },
  stat: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  statLabel: {
    color: '#555',
  },
  camDots: {
    display: 'flex',
    gap: 6,
    marginLeft: 'auto',
    alignItems: 'center',
  },
  camLabel: {
    fontSize: 11,
    color: '#555',
  },
};

const meterStyle = (): React.CSSProperties => ({
  display: 'inline-block',
  width: 60,
  height: 6,
  borderRadius: 3,
  background: '#222',
  position: 'relative',
  overflow: 'hidden',
});

const meterFillStyle = (value: number): React.CSSProperties => ({
  position: 'absolute',
  left: 0,
  top: 0,
  height: '100%',
  width: `${value}%`,
  background: value > 85 ? '#ff4444' : value > 65 ? '#ffaa00' : '#00ff88',
  borderRadius: 3,
  transition: 'width 0.5s ease',
});

const camDotStyle = (status: string): React.CSSProperties => ({
  width: 8,
  height: 8,
  borderRadius: '50%',
  background:
    status === 'connected' ? '#00ff88' :
    status === 'connecting' ? '#ffaa00' : '#ff4444',
});

function Meter({ value }: { value: number }) {
  return (
    <div style={meterStyle()}>
      <div style={meterFillStyle(value)} />
    </div>
  );
}

export default function StatusBar() {
  const { systemStatus, cameras } = useAppStore();

  const cpu = systemStatus?.cpu_percent ?? 0;
  const mem = systemStatus?.memory_percent ?? 0;

  return (
    <div style={S.bar}>
      <div style={S.stat}>
        <span style={S.statLabel}>CPU</span>
        <Meter value={cpu} />
        <span style={{ color: cpu > 85 ? '#ff4444' : '#888' }}>{cpu.toFixed(0)}%</span>
      </div>
      <div style={S.stat}>
        <span style={S.statLabel}>MEM</span>
        <Meter value={mem} />
        <span style={{ color: mem > 85 ? '#ff4444' : '#888' }}>{mem.toFixed(0)}%</span>
      </div>

      <div style={S.camDots}>
        <span style={S.camLabel}>Cameras:</span>
        {cameras.map((cam) => (
          <div
            key={cam.name}
            style={camDotStyle(cam.status)}
            title={`${cam.name}: ${cam.status}`}
          />
        ))}
        {cameras.length === 0 && <span style={{ color: '#444', fontSize: 11 }}>none</span>}
      </div>
    </div>
  );
}
