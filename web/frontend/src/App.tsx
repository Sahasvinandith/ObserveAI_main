/**
 * App.tsx — Root component.
 * Sets up layout: fixed sidebar + scrollable main content area.
 * Initializes WebSocket and fetches initial data on mount.
 */

import { useEffect } from 'react';
import { useAppStore } from './store/appStore';
import Sidebar from './components/Sidebar';
import CameraFeedPage from './components/CameraFeedPage';
import CameraMapPage from './components/CameraMapPage';
import FaceDatabasePage from './components/FaceDatabasePage';
import LogsPage from './components/LogsPage';
import SettingsPage from './components/SettingsPage';
import ActionsPage from './components/ActionsPage';
import ToastContainer from './components/ToastContainer';
import StatusBar from './components/StatusBar';

const styles: Record<string, React.CSSProperties> = {
  layout: {
    display: 'flex',
    width: '100vw',
    height: '100vh',
    background: '#0f0a14',
    overflow: 'hidden',
  },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    minWidth: 0,
  },
  content: {
    flex: 1,
    overflow: 'auto',
    padding: '0',
  },
};

export default function App() {
  const { currentPage, connectWs, fetchCameras, fetchSettings, fetchActions, fetchCameraActions } =
    useAppStore();

  useEffect(() => {
    // Connect WebSocket for real-time events
    connectWs();
    // Fetch initial data
    fetchCameras();
    fetchSettings();
    fetchActions();
    fetchCameraActions();
  }, []);

  return (
    <div style={styles.layout}>
      <Sidebar />
      <div style={styles.main}>
        <StatusBar />
        <div style={styles.content}>
          {currentPage === 'camera-feed' && <CameraFeedPage />}
          {currentPage === 'camera-map' && <CameraMapPage />}
          {currentPage === 'database' && <FaceDatabasePage />}
          {currentPage === 'logs' && <LogsPage />}
          {currentPage === 'settings' && <SettingsPage />}
          {currentPage === 'actions' && <ActionsPage />}
        </div>
      </div>
      <ToastContainer />
    </div>
  );
}
