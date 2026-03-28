import sqlite3
import os
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple

class LogManager:
    """
    Manages persistent logging for ObserveAI using SQLite.
    Tracks person detections, actions, and movement events.
    """
    def __init__(self, db_path="logs.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the database and create tables if they don't exist."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    type TEXT,
                    person_name TEXT,
                    cameras TEXT,
                    location_x REAL,
                    location_y REAL,
                    action TEXT,
                    message TEXT
                )
            """)
            conn.commit()

    def add_log(self, log_type: str, person_name: str, cameras: List[str], 
                location: Optional[Tuple[float, float]] = None, 
                action: Optional[str] = None, 
                message: Optional[str] = None):
        """
        Add a new log entry.
        
        Args:
            log_type: 'detection', 'action', 'entry', 'exit'
            person_name: Name of the person (e.g., 'User_1')
            cameras: List of camera names
            location: (x, y) coordinates
            action: Action detected (e.g., 'right_smoke')
            message: Custom log message
        """
        timestamp = time.time()
        cameras_str = ",".join(cameras)
        loc_x = location[0] if location else None
        loc_y = location[1] if location else None
        
        # Build default message if none provided
        if not message:
            if log_type == 'detection':
                loc_str = f"({loc_x:.1f}, {loc_y:.1f})" if location else "unknown"
                message = f"{person_name} detected in {cameras_str}. Stereo vision estimated location {loc_str}"
            elif log_type == 'entry':
                message = f"{person_name} entered camera feed {cameras_str}"
            elif log_type == 'exit':
                message = f"{person_name} left camera feed {cameras_str}"
            elif log_type == 'action':
                message = f"{person_name} did {action} at {datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}"

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO logs (timestamp, type, person_name, cameras, location_x, location_y, action, message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (timestamp, log_type, person_name, cameras_str, loc_x, loc_y, action, message))
            conn.commit()

    def get_logs(self, start_time: Optional[float] = None, end_time: Optional[float] = None, 
                 person_name: Optional[str] = None) -> List[Dict]:
        """Query logs with optional filters."""
        query = "SELECT * FROM logs WHERE 1=1"
        params = []
        
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)
        if person_name:
            query += " AND person_name LIKE ?"
            params.append(f"%{person_name}%")
            
        query += " ORDER BY timestamp DESC"
        
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_person_activity_summary(self, person_name: str) -> str:
        """
        Generates a summary of a person's past actions and activities.
        Format:
        User_1 was visible from [time] to [time] in [camera]
        User_1 did [action] at [time].
        User_1 is visible from [time] to now in [camera]
        """
        logs = self.get_logs(person_name=person_name)
        if not logs:
            return f"No records found for {person_name}."
        
        summary_lines = []
        
        # Group by visibility sessions (entry to exit)
        sessions = []
        current_session = None
        
        # Logs are sorted by timestamp DESC, so process in reverse for session building
        for log in reversed(logs):
            lt = log['type']
            ts = log['timestamp']
            time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            cams = log['cameras']
            
            if lt == 'entry':
                current_session = {'start': time_str, 'cameras': cams, 'actions': []}
            elif lt == 'exit':
                if current_session:
                    current_session['end'] = time_str
                    # Check if this exit was due to system shutdown
                    if log['message'] and "system shut down" in log['message']:
                        current_session['shutdown'] = True
                    sessions.append(current_session)
                    current_session = None
            elif lt == 'action':
                action_entry = f"{person_name} did {log['action']} at {time_str}"
                if current_session:
                    current_session['actions'].append(action_entry)
                else:
                    # Action without explicit entry record
                    summary_lines.append(action_entry)
                    
        # Handle currently active session
        if current_session:
            current_session['end'] = 'now'
            sessions.append(current_session)
            
        # Format sessions into summary
        for s in sessions:
            status = "is visible" if s['end'] == 'now' else "was visible"
            # Special mention for system shutdown as requested
            end_msg = " as system shut down" if s.get('shutdown') else ""
            summary_lines.append(f"{person_name} {status} from [{s['start']}] to [{s['end']}]{end_msg} in {s['cameras']} camera feeds")
            for action in s['actions']:
                summary_lines.append(action)
                
        return "\n".join(summary_lines)

# Singleton access
_instance = None
def get_log_manager(db_path="logs.db"):
    global _instance
    if _instance is None:
        _instance = LogManager(db_path)
    return _instance
