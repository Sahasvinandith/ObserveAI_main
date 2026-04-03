/**
 * LogsPage.tsx
 * Web equivalent of the PyQt6 Logs page (index 3).
 * Queries the SQLite logs.db via the /api/logs endpoint.
 * Shows: timestamp, type, person, camera, action, message, and evidence image.
 */

import React, { useState, useEffect } from 'react';
import type { LogEntry } from '../types';

const TYPE_COLORS: Record<string, string> = {
  action: '#ffaa00',
  detection: '#00ff88',
  entry: '#6699ff',
  exit: '#ff6666',
};

const S: Record<string, React.CSSProperties> = {
  page: { height: '100%', display: 'flex', flexDirection: 'column', background: '#0f0a14' },
  toolbar: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
    background: '#130a1a', borderBottom: '1px solid #2e1040', flexShrink: 0, flexWrap: 'wrap',
  },
  toolbarTitle: { fontWeight: 600, fontSize: 14, color: '#ddd' },
  input: {
    padding: '6px 10px', background: '#1a0f1f', border: '1px solid #2e1040',
    borderRadius: 6, color: '#fff', fontSize: 12, outline: 'none',
  },
  btn: {
    padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
    fontSize: 12, fontWeight: 600, background: '#7a3a8a', color: '#fff',
  },
  body: { flex: 1, display: 'flex', overflow: 'hidden' },
  logList: { flex: 1, overflowY: 'auto', padding: 8 },
  logContent: { flex: 1, minWidth: 0 },
  logMessage: { fontSize: 12, color: '#ccc', lineHeight: 1.4, wordBreak: 'break-word' },
  logMeta: { fontSize: 11, color: '#555', marginTop: 2 },
  evidencePanel: {
    width: 320, flexShrink: 0, borderLeft: '1px solid #2e1040',
    padding: 16, overflowY: 'auto',
  },
  evidenceTitle: { fontWeight: 700, fontSize: 13, color: '#e0c0f0', marginBottom: 10 },
  evidenceImg: { width: '100%', borderRadius: 6, marginBottom: 8 },
  noEvidence: { color: '#555', fontSize: 12, textAlign: 'center', marginTop: 40 },
  emptyState: {
    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: '#555', flexDirection: 'column', gap: 12,
  },
};

const logEntryStyle = (selected: boolean): React.CSSProperties => ({
  display: 'flex', gap: 12, alignItems: 'flex-start',
  padding: '8px 12px', marginBottom: 4, borderRadius: 6,
  background: '#0d0714',
  border: `1px solid ${selected ? '#7a3a8a' : '#1e1030'}`,
  cursor: 'pointer',
  transition: 'border-color 0.15s',
});

const typeBadgeStyle = (type: string): React.CSSProperties => ({
  flexShrink: 0, padding: '2px 7px', borderRadius: 4, fontSize: 10, fontWeight: 700,
  background: (TYPE_COLORS[type] || '#555') + '22',
  color: TYPE_COLORS[type] || '#888',
  border: `1px solid ${TYPE_COLORS[type] || '#555'}44`,
  minWidth: 60, textAlign: 'center',
  marginTop: 1,
});

function formatTs(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [person, setPerson] = useState('');
  const [selectedLog, setSelectedLog] = useState<LogEntry | null>(null);

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (person) params.set('person_name', person);
      const res = await fetch(`/api/logs?${params}`);
      const data: LogEntry[] = await res.json();
      setLogs(data);
    } catch {
      setLogs([]);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchLogs();
  }, []);

  const evidenceUrl = (log: LogEntry): string | null => {
    if (!log.evidence_path) return null;
    const filename = log.evidence_path.split('/').pop()!;
    return `/api/evidence/${encodeURIComponent(filename)}`;
  };

  return (
    <div style={S.page}>
      <div style={S.toolbar}>
        <span style={S.toolbarTitle}>Activity Logs</span>
        <input
          style={{ ...S.input, width: 160 }}
          placeholder="Filter by person..."
          value={person}
          onChange={(e) => setPerson(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && fetchLogs()}
        />
        <button style={S.btn} onClick={fetchLogs} disabled={loading}>
          {loading ? 'Loading...' : 'Search'}
        </button>
        <button
          style={{ ...S.btn, background: '#2a1535' }}
          onClick={() => { setPerson(''); setTimeout(fetchLogs, 50); }}
        >
          Clear
        </button>
        <span style={{ fontSize: 11, color: '#555', marginLeft: 'auto' }}>
          {logs.length} entries
        </span>
      </div>

      <div style={S.body}>
        <div style={S.logList}>
          {logs.length === 0 && !loading && (
            <div style={S.emptyState}>
              <span style={{ fontSize: 36 }}>📋</span>
              <div>No log entries found.</div>
            </div>
          )}

          {logs.map((log) => (
            <div
              key={log.id}
              style={logEntryStyle(selectedLog?.id === log.id)}
              onClick={() => setSelectedLog(log)}
            >
              <div style={typeBadgeStyle(log.type)}>{log.type}</div>
              <div style={S.logContent}>
                <div style={S.logMessage}>{log.message}</div>
                <div style={S.logMeta}>
                  {formatTs(log.timestamp)}
                  {log.person_name && ` · ${log.person_name}`}
                  {log.cameras && ` · ${log.cameras}`}
                  {log.action && ` · action: ${log.action}`}
                  {log.evidence_path && ' · 📷 has evidence'}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Evidence Panel */}
        <div style={S.evidencePanel}>
          <div style={S.evidenceTitle}>Evidence Viewer</div>
          {selectedLog ? (
            <>
              <div style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>
                {formatTs(selectedLog.timestamp)}
              </div>
              <div style={{ fontSize: 13, color: '#ccc', marginBottom: 12 }}>
                {selectedLog.message}
              </div>
              {evidenceUrl(selectedLog) ? (
                <img
                  style={S.evidenceImg}
                  src={evidenceUrl(selectedLog)!}
                  alt="Evidence"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = 'none';
                  }}
                />
              ) : (
                <div style={{ color: '#555', fontSize: 12 }}>
                  No evidence image for this entry.
                </div>
              )}
              {selectedLog.location_x !== null && (
                <div style={{ fontSize: 11, color: '#666', marginTop: 8 }}>
                  Location: ({selectedLog.location_x?.toFixed(1)}, {selectedLog.location_y?.toFixed(1)})
                </div>
              )}
            </>
          ) : (
            <div style={S.noEvidence}>
              <div style={{ fontSize: 28, marginBottom: 8 }}>🖼</div>
              <div>Select a log entry to view details and evidence.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
