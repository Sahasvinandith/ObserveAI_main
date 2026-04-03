// Types matching the FastAPI response models and WebSocket message schemas

export interface Camera {
  name: string;
  url: string;
  fov: number;
  view_range: number;
  pos: [number, number];
  rot: number;
  actions: string[];
  status: 'connected' | 'connecting' | 'error' | 'disconnected';
  ai_running: boolean;
}

export interface SystemStatus {
  type: 'system_status';
  cpu_percent: number;
  memory_percent: number;
  cameras: Record<string, { status: string; ai_running: boolean }>;
}

export interface ActionDetectedEvent {
  type: 'action_detected';
  camera: string;
  person: string;
  action: string;
  timestamp: number;
  evidence_url: string | null;
}

export interface PersonUpdateEvent {
  type: 'person_update';
  global_id: number;
  camera: string;
  x: number;
  y: number;
}

export interface CameraStatusEvent {
  type: 'camera_status';
  camera: string;
  status: string;
  message: string;
}

export type WsEvent =
  | SystemStatus
  | ActionDetectedEvent
  | PersonUpdateEvent
  | CameraStatusEvent
  | { type: 'init'; cameras: Camera[]; settings: AppSettings }
  | { type: 'ping' | 'pong' };

export interface AppSettings {
  feature_threshold: number;
  reid_weight: number;
  color_weight: number;
  spatial_weight: number;
  spatial_region_weight: number;
  spatial_depth_weight: number;
  ref_human_height_px: number;
  default_fov: number;
  dot_radius: number;
  min_quality_threshold: number;
  max_faces_per_user: number;
  identity_confirm_frames: number;
  identity_confidence_threshold: number;
  identity_change_margin: number;
  min_face_width: number;
  min_face_height: number;
  min_face_confidence: number;
  camera_actions: Record<string, string[]>;
}

export interface LogEntry {
  id: number;
  timestamp: number;
  type: string;
  person_name: string;
  cameras: string;
  location_x: number | null;
  location_y: number | null;
  action: string | null;
  message: string;
  evidence_path: string | null;
}

export interface Toast {
  id: string;
  message: string;
  type: 'info' | 'success' | 'warning' | 'error';
}

export type Page = 'camera-map' | 'camera-feed' | 'database' | 'logs' | 'settings' | 'actions';

export interface PersonDot {
  global_id: number;
  x: number;
  y: number;
  camera: string;
  lastSeen: number;
}

export interface WallData {
  x: number;
  y: number;
  width: number;
  height: number;
  rot: number;
}
