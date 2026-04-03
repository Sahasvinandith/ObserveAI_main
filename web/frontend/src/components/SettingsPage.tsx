/**
 * SettingsPage.tsx
 * Web equivalent of the PyQt6 Settings page (index 4).
 * Maps every QDoubleSpinBox/QSpinBox from MainWindow.setup_settings_page()
 * to a labeled number input with real-time preview and save/reset buttons.
 */

import React, { useState, useEffect } from 'react';
import { useAppStore } from '../store/appStore';
import type { AppSettings } from '../types';

const S: Record<string, React.CSSProperties> = {
  page: { height: '100%', display: 'flex', flexDirection: 'column', background: '#0f0a14' },
  toolbar: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    background: '#130a1a', borderBottom: '1px solid #2e1040', flexShrink: 0,
  },
  toolbarTitle: { fontWeight: 600, fontSize: 14, color: '#ddd', flex: 1 },
  body: { flex: 1, overflowY: 'auto', padding: 24 },
  section: { marginBottom: 32 },
  sectionTitle: {
    fontSize: 13, fontWeight: 700, color: '#9a50aa',
    textTransform: 'uppercase', letterSpacing: 1,
    borderBottom: '1px solid #2e1040', paddingBottom: 6, marginBottom: 16,
  },
  grid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16,
  },
  field: {},
  label: { fontSize: 12, color: '#aaa', marginBottom: 4, display: 'block' },
  hint: { fontSize: 10, color: '#555', marginTop: 2 },
  input: {
    width: '100%', padding: '8px 10px',
    background: '#1a0f1f', border: '1px solid #2e1040',
    borderRadius: 6, color: '#fff', fontSize: 13, outline: 'none',
  },
  rangeWrap: { display: 'flex', alignItems: 'center', gap: 8 },
  range: { flex: 1 },
  rangeValue: { color: '#9a50aa', fontSize: 13, minWidth: 40, textAlign: 'right' },
};

const btnStyle = (variant?: 'primary' | 'danger'): React.CSSProperties => ({
  padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
  fontSize: 12, fontWeight: 600,
  background: variant === 'primary' ? '#7a3a8a' : variant === 'danger' ? '#5a1020' : '#2a1535',
  color: variant === 'danger' ? '#ff8888' : '#fff',
});

interface FieldDef {
  key: keyof AppSettings;
  label: string;
  hint?: string;
  min?: number;
  max?: number;
  step?: number;
  useSlider?: boolean;
}

const SECTIONS: { title: string; fields: FieldDef[] }[] = [
  {
    title: 'Re-ID & Matching Thresholds',
    fields: [
      { key: 'feature_threshold', label: 'Feature Threshold', hint: 'Min similarity to match a person (0-1)', min: 0, max: 1, step: 0.01, useSlider: true },
      { key: 'reid_weight', label: 'Re-ID Weight', hint: 'Weight for appearance features', min: 0, max: 1, step: 0.01, useSlider: true },
      { key: 'color_weight', label: 'Color Weight', hint: 'Weight for color histogram matching', min: 0, max: 1, step: 0.01, useSlider: true },
      { key: 'spatial_weight', label: 'Spatial Weight', hint: 'Weight for spatial position matching', min: 0, max: 1, step: 0.01, useSlider: true },
      { key: 'spatial_region_weight', label: 'Spatial Region Weight', hint: 'Weight for region matching within spatial score', min: 0, max: 1, step: 0.01, useSlider: true },
      { key: 'spatial_depth_weight', label: 'Spatial Depth Weight', hint: 'Weight for depth consistency', min: 0, max: 1, step: 0.01, useSlider: true },
    ],
  },
  {
    title: 'Camera & Map Settings',
    fields: [
      { key: 'default_fov', label: 'Default FOV (degrees)', hint: 'Default camera field of view', min: 10, max: 180, step: 1 },
      { key: 'dot_radius', label: 'Person Dot Radius (px)', hint: 'Size of person indicator dots on floor map', min: 2, max: 20, step: 1 },
      { key: 'ref_human_height_px', label: 'Reference Human Height (px)', hint: 'Height of a human at 5m for depth estimation', min: 50, max: 500, step: 5 },
    ],
  },
  {
    title: 'Face Quality & Database',
    fields: [
      { key: 'min_quality_threshold', label: 'Min Face Quality Score', hint: 'Minimum quality score to save a face', min: 0, max: 100, step: 1 },
      { key: 'max_faces_per_user', label: 'Max Faces Per Person', hint: 'Maximum stored face images per person', min: 1, max: 20, step: 1 },
      { key: 'min_face_width', label: 'Min Face Width (px)', hint: 'Minimum pixel width for valid face detection', min: 10, max: 200, step: 1 },
      { key: 'min_face_height', label: 'Min Face Height (px)', hint: 'Minimum pixel height for valid face detection', min: 10, max: 200, step: 1 },
      { key: 'min_face_confidence', label: 'Min Face Confidence', hint: 'Minimum YOLO confidence for face detection', min: 0, max: 1, step: 0.01, useSlider: true },
    ],
  },
  {
    title: 'Identity Verification',
    fields: [
      { key: 'identity_confirm_frames', label: 'Identity Confirm Frames', hint: 'Frames required to lock an identity', min: 1, max: 30, step: 1 },
      { key: 'identity_confidence_threshold', label: 'Identity Confidence Threshold', hint: 'Min confidence to accept recognition result', min: 0, max: 1, step: 0.01, useSlider: true },
      { key: 'identity_change_margin', label: 'Identity Change Margin', hint: 'How much better a new match must be to override', min: 0, max: 1, step: 0.01, useSlider: true },
    ],
  },
];

export default function SettingsPage() {
  const { settings, saveSettings, resetSettings, addToast } = useAppStore();
  const [local, setLocal] = useState<Partial<AppSettings>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings) setLocal({ ...settings });
  }, [settings]);

  const handleChange = (key: keyof AppSettings, value: number) => {
    setLocal((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await saveSettings(local);
    } catch {
      addToast('Failed to save settings', 'error');
    }
    setSaving(false);
  };

  const handleReset = async () => {
    if (!confirm('Reset all settings to defaults?')) return;
    await resetSettings();
  };

  if (!settings || Object.keys(local).length === 0) {
    return (
      <div style={{ ...S.page, alignItems: 'center', justifyContent: 'center', color: '#555' }}>
        Loading settings...
      </div>
    );
  }

  return (
    <div style={S.page}>
      <div style={S.toolbar}>
        <span style={S.toolbarTitle}>Settings</span>
        <button style={btnStyle()} onClick={handleReset}>Reset Defaults</button>
        <button style={btnStyle('primary')} onClick={handleSave} disabled={saving}>
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>

      <div style={S.body}>
        {SECTIONS.map((section) => (
          <div key={section.title} style={S.section}>
            <div style={S.sectionTitle}>{section.title}</div>
            <div style={S.grid}>
              {section.fields.map((field) => {
                const val = (local[field.key] as number) ?? 0;
                return (
                  <div key={field.key} style={S.field}>
                    <label style={S.label}>{field.label}</label>
                    {field.useSlider ? (
                      <div style={S.rangeWrap}>
                        <input
                          type="range"
                          style={S.range}
                          min={field.min ?? 0}
                          max={field.max ?? 1}
                          step={field.step ?? 0.01}
                          value={val}
                          onChange={(e) => handleChange(field.key, parseFloat(e.target.value))}
                        />
                        <span style={S.rangeValue}>{val.toFixed(2)}</span>
                      </div>
                    ) : (
                      <input
                        type="number"
                        style={S.input}
                        min={field.min}
                        max={field.max}
                        step={field.step ?? 1}
                        value={val}
                        onChange={(e) => handleChange(field.key, parseFloat(e.target.value))}
                      />
                    )}
                    {field.hint && <div style={S.hint}>{field.hint}</div>}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
