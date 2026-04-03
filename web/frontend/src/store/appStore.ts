/**
 * store/appStore.ts
 * Global application state using Zustand.
 * Manages cameras, WebSocket connection, toasts, current page, and person positions.
 */

import { create } from 'zustand';
import type {
  Camera, AppSettings, LogEntry, Page, PersonDot, Toast, WsEvent,
  ActionDetectedEvent, SystemStatus
} from '../types';

const API_BASE = '/api';
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/events`;

interface AppState {
  // Navigation
  currentPage: Page;
  setPage: (page: Page) => void;

  // Cameras
  cameras: Camera[];
  fetchCameras: () => Promise<void>;
  addCamera: (data: Partial<Camera>) => Promise<void>;
  updateCamera: (name: string, data: Partial<Camera>) => Promise<void>;
  deleteCamera: (name: string) => Promise<void>;
  restartCamera: (name: string) => Promise<void>;
  finishSetup: () => Promise<void>;

  // Settings
  settings: AppSettings | null;
  fetchSettings: () => Promise<void>;
  saveSettings: (partial: Partial<AppSettings>) => Promise<void>;
  resetSettings: () => Promise<void>;

  // Person tracking (floor map)
  personDots: Map<number, PersonDot>;
  updatePersonDot: (global_id: number, x: number, y: number, camera: string) => void;

  // System status
  systemStatus: SystemStatus | null;

  // Recent action detections
  recentDetections: ActionDetectedEvent[];
  addDetection: (ev: ActionDetectedEvent) => void;

  // Toasts
  toasts: Toast[];
  addToast: (message: string, type?: Toast['type']) => void;
  removeToast: (id: string) => void;

  // Actions
  actions: string[];
  fetchActions: () => Promise<void>;
  deleteAction: (name: string) => Promise<void>;
  cameraActions: Record<string, string[]>;
  fetchCameraActions: () => Promise<void>;
  saveCameraActions: (mapping: Record<string, string[]>) => Promise<void>;

  // WebSocket
  wsConnected: boolean;
  connectWs: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  // ── Navigation ──────────────────────────────────────
  currentPage: 'camera-feed',
  setPage: (page) => set({ currentPage: page }),

  // ── Cameras ─────────────────────────────────────────
  cameras: [],
  fetchCameras: async () => {
    try {
      const res = await fetch(`${API_BASE}/cameras`);
      const cameras: Camera[] = await res.json();
      set({ cameras });
    } catch (e) {
      console.error('fetchCameras', e);
    }
  },
  addCamera: async (data) => {
    const res = await fetch(`${API_BASE}/cameras`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to add camera');
    }
    await get().fetchCameras();
    get().addToast(`Camera "${data.name}" added`, 'success');
  },
  updateCamera: async (name, data) => {
    const res = await fetch(`${API_BASE}/cameras/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to update camera');
    await get().fetchCameras();
  },
  deleteCamera: async (name) => {
    await fetch(`${API_BASE}/cameras/${encodeURIComponent(name)}`, { method: 'DELETE' });
    await get().fetchCameras();
    get().addToast(`Camera "${name}" removed`, 'info');
  },
  restartCamera: async (name) => {
    await fetch(`${API_BASE}/cameras/${encodeURIComponent(name)}/restart`, { method: 'POST' });
    get().addToast(`Camera "${name}" reconnecting...`, 'info');
  },
  finishSetup: async () => {
    await fetch(`${API_BASE}/cameras/finish-setup`, { method: 'POST' });
    get().addToast('AI started for all cameras', 'success');
  },

  // ── Settings ────────────────────────────────────────
  settings: null,
  fetchSettings: async () => {
    try {
      const res = await fetch(`${API_BASE}/settings`);
      const settings: AppSettings = await res.json();
      set({ settings });
    } catch (e) {
      console.error('fetchSettings', e);
    }
  },
  saveSettings: async (partial) => {
    const res = await fetch(`${API_BASE}/settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(partial),
    });
    if (!res.ok) throw new Error('Failed to save settings');
    await get().fetchSettings();
    get().addToast('Settings saved', 'success');
  },
  resetSettings: async () => {
    const res = await fetch(`${API_BASE}/settings/reset`, { method: 'POST' });
    const defaults: AppSettings = await res.json();
    set({ settings: defaults });
    get().addToast('Settings reset to defaults', 'info');
  },

  // ── Person Tracking ─────────────────────────────────
  personDots: new Map(),
  updatePersonDot: (global_id, x, y, camera) => {
    set((state) => {
      const dots = new Map(state.personDots);
      dots.set(global_id, { global_id, x, y, camera, lastSeen: Date.now() });
      return { personDots: dots };
    });
  },

  // ── System Status ───────────────────────────────────
  systemStatus: null,

  // ── Detections ──────────────────────────────────────
  recentDetections: [],
  addDetection: (ev) => {
    set((state) => ({
      recentDetections: [ev, ...state.recentDetections].slice(0, 100),
    }));
  },

  // ── Toasts ──────────────────────────────────────────
  toasts: [],
  addToast: (message, type = 'info') => {
    const id = `${Date.now()}-${Math.random()}`;
    set((state) => ({ toasts: [...state.toasts, { id, message, type }] }));
    setTimeout(() => get().removeToast(id), 5000);
  },
  removeToast: (id) => {
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },

  // ── Actions ─────────────────────────────────────────
  actions: [],
  fetchActions: async () => {
    try {
      const res = await fetch(`${API_BASE}/actions`);
      const actions: string[] = await res.json();
      set({ actions });
    } catch (e) {
      console.error('fetchActions', e);
    }
  },
  deleteAction: async (name) => {
    await fetch(`${API_BASE}/actions/${encodeURIComponent(name)}`, { method: 'DELETE' });
    await get().fetchActions();
    get().addToast(`Action "${name}" deleted`, 'info');
  },
  cameraActions: {},
  fetchCameraActions: async () => {
    try {
      const res = await fetch(`${API_BASE}/camera-actions`);
      const cameraActions: Record<string, string[]> = await res.json();
      set({ cameraActions });
    } catch (e) {
      console.error('fetchCameraActions', e);
    }
  },
  saveCameraActions: async (mapping) => {
    await fetch(`${API_BASE}/camera-actions`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ camera_actions: mapping }),
    });
    await get().fetchCameraActions();
    get().addToast('Camera actions updated', 'success');
  },

  // ── WebSocket ────────────────────────────────────────
  wsConnected: false,
  connectWs: () => {
    let ws: WebSocket;
    let reconnectTimeout: ReturnType<typeof setTimeout>;

    const connect = () => {
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        set({ wsConnected: true });
        console.log('[WS] Connected');
      };

      ws.onmessage = (ev) => {
        try {
          const data: WsEvent = JSON.parse(ev.data);
          const store = get();

          switch (data.type) {
            case 'init':
              set({ cameras: data.cameras, settings: data.settings });
              break;
            case 'system_status':
              set({ systemStatus: data });
              // Update individual camera statuses
              set((state) => ({
                cameras: state.cameras.map((c) => {
                  const s = data.cameras[c.name];
                  return s ? { ...c, status: s.status as Camera['status'], ai_running: s.ai_running } : c;
                }),
              }));
              break;
            case 'action_detected':
              store.addDetection(data);
              store.addToast(`${data.action} detected on ${data.camera} (${data.person})`, 'warning');
              break;
            case 'person_update':
              store.updatePersonDot(data.global_id, data.x, data.y, data.camera);
              break;
            case 'camera_status':
              set((state) => ({
                cameras: state.cameras.map((c) =>
                  c.name === data.camera ? { ...c, status: data.status as Camera['status'] } : c
                ),
              }));
              if (data.status === 'error') {
                store.addToast(`Camera "${data.camera}": ${data.message}`, 'error');
              }
              break;
            case 'ping':
              ws.send(JSON.stringify({ type: 'pong' }));
              break;
          }
        } catch (e) {
          console.error('[WS] Parse error', e);
        }
      };

      ws.onclose = () => {
        set({ wsConnected: false });
        console.log('[WS] Disconnected. Reconnecting in 3s...');
        reconnectTimeout = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();
  },
}));
