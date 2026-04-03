/**
 * Sidebar.tsx
 * Fixed left navigation sidebar. Maps to the button panel in the original PyQt6 main.ui.
 * Pages: Camera Feed | Camera Map | Database | Logs | Settings | Actions
 */

import React from 'react';
import { useAppStore } from '../store/appStore';
import type { Page } from '../types';

interface NavItem {
  id: Page;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'camera-feed', label: 'Camera Feed', icon: '📹' },
  { id: 'camera-map', label: 'Camera Map', icon: '🗺️' },
  { id: 'database', label: 'Face Database', icon: '👤' },
  { id: 'logs', label: 'Logs', icon: '📋' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
  { id: 'actions', label: 'Actions', icon: '🎯' },
];

const S: Record<string, React.CSSProperties> = {
  sidebar: {
    width: 200,
    minWidth: 200,
    height: '100vh',
    background: '#130a1a',
    borderRight: '1px solid #2e1040',
    display: 'flex',
    flexDirection: 'column',
    zIndex: 10,
  },
  logo: {
    padding: '20px 16px 12px',
    fontSize: 18,
    fontWeight: 700,
    color: '#9a50aa',
    letterSpacing: 1,
    borderBottom: '1px solid #2e1040',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    userSelect: 'none',
  },
  logoIcon: {
    fontSize: 24,
  },
  nav: {
    flex: 1,
    padding: '8px 0',
    overflowY: 'auto',
  },
  icon: {
    fontSize: 16,
    width: 20,
    textAlign: 'center',
  },
  footer: {
    padding: '12px 16px',
    borderTop: '1px solid #2e1040',
    fontSize: 11,
    color: '#555',
  },
};

const navItemStyle = (active: boolean): React.CSSProperties => ({
  display: 'flex',
  alignItems: 'center',
  gap: 10,
  padding: '11px 16px',
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: active ? 600 : 400,
  color: active ? '#fff' : '#aaa',
  background: active ? 'rgba(122, 58, 138, 0.25)' : 'transparent',
  borderLeft: active ? '3px solid #7a3a8a' : '3px solid transparent',
  transition: 'all 0.15s',
  userSelect: 'none',
});

const wsStatusStyle = (connected: boolean): React.CSSProperties => ({
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  color: connected ? '#00ff88' : '#ff4444',
  fontSize: 11,
  marginTop: 4,
});

const dotStyle = (connected: boolean): React.CSSProperties => ({
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: connected ? '#00ff88' : '#ff4444',
  flexShrink: 0,
});

export default function Sidebar() {
  const { currentPage, setPage, wsConnected } = useAppStore();

  return (
    <aside style={S.sidebar}>
      <div style={S.logo}>
        <span style={S.logoIcon}>👁</span>
        ObserveAI
      </div>

      <nav style={S.nav}>
        {NAV_ITEMS.map((item) => (
          <div
            key={item.id}
            style={navItemStyle(currentPage === item.id)}
            onClick={() => setPage(item.id)}
            onMouseEnter={(e) => {
              if (currentPage !== item.id) {
                (e.currentTarget as HTMLDivElement).style.background = 'rgba(122,58,138,0.12)';
                (e.currentTarget as HTMLDivElement).style.color = '#ddd';
              }
            }}
            onMouseLeave={(e) => {
              if (currentPage !== item.id) {
                (e.currentTarget as HTMLDivElement).style.background = 'transparent';
                (e.currentTarget as HTMLDivElement).style.color = '#aaa';
              }
            }}
          >
            <span style={S.icon}>{item.icon}</span>
            {item.label}
          </div>
        ))}
      </nav>

      <div style={S.footer}>
        <div>v2.0.0 Web UI</div>
        <div style={wsStatusStyle(wsConnected)}>
          <div style={dotStyle(wsConnected)} />
          {wsConnected ? 'Live' : 'Reconnecting...'}
        </div>
      </div>
    </aside>
  );
}
