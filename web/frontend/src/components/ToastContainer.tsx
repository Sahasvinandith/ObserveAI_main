/**
 * ToastContainer.tsx
 * Displays toast notifications in the top-right corner.
 * Matches the original PyQt6 _show_notification() behavior:
 * dark background, green text, purple border.
 */

import React from 'react';
import { useAppStore } from '../store/appStore';
import type { Toast } from '../types';

const TOAST_COLORS: Record<Toast['type'], { bg: string; border: string; text: string }> = {
  info: { bg: 'rgba(19, 10, 26, 0.95)', border: '#7a3a8a', text: '#ccc' },
  success: { bg: 'rgba(19, 10, 26, 0.95)', border: '#00aa55', text: '#00ff88' },
  warning: { bg: 'rgba(19, 10, 26, 0.95)', border: '#aa6600', text: '#ffaa00' },
  error: { bg: 'rgba(19, 10, 26, 0.95)', border: '#aa1111', text: '#ff6666' },
};

const S: Record<string, React.CSSProperties> = {
  container: {
    position: 'fixed',
    top: 16,
    right: 16,
    zIndex: 9999,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    maxWidth: 360,
    pointerEvents: 'none',
  },
};

const toastStyle = (type: Toast['type']): React.CSSProperties => ({
  background: TOAST_COLORS[type].bg,
  border: `1.5px solid ${TOAST_COLORS[type].border}`,
  color: TOAST_COLORS[type].text,
  borderRadius: 8,
  padding: '10px 16px',
  fontSize: 13,
  lineHeight: 1.5,
  boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
  animation: 'fadeIn 0.2s ease',
  pointerEvents: 'auto',
  cursor: 'pointer',
  userSelect: 'none',
});

export default function ToastContainer() {
  const { toasts, removeToast } = useAppStore();

  return (
    <div style={S.container}>
      <style>{`
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: none; } }
      `}</style>
      {toasts.map((toast) => (
        <div
          key={toast.id}
          style={toastStyle(toast.type)}
          onClick={() => removeToast(toast.id)}
          title="Click to dismiss"
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
