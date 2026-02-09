"""
SettingsManager - Persistent Settings for ObserveAI

Handles loading and saving application settings to a JSON file.
Settings are loaded on startup and can be modified at runtime.
"""

import json
import os
from typing import Any, Dict, Optional


class SettingsManager:
    """
    Manages application settings with JSON persistence.
    
    Usage:
        settings = SettingsManager()
        threshold = settings.get("feature_threshold")
        settings.set("feature_threshold", 0.6)
        settings.save()
    """
    
    SETTINGS_FILE = "settings.json"
    
    # Default values for all settings
    DEFAULTS: Dict[str, Any] = {
        # Global Tracker Settings
        "feature_threshold": 0.5,
        "reid_weight": 0.7,
        "spatial_weight": 0.3,
        "default_fov": 70,
        "dot_radius": 8,
        # Face Quality Settings
        "min_quality_threshold": 50,
        "max_faces_per_user": 5,
        # Identity Verification Settings
        "identity_confirm_frames": 3,       # Frames to confirm identity before locking
        "identity_confidence_threshold": 0.6,  # Min confidence to accept recognition
        "identity_change_margin": 0.15,      # How much better new match must be to change
        # Face Validation Settings (to filter bad detections)
        "min_face_width": 70,               # Minimum face width in pixels
        "min_face_height": 90,              # Minimum face height in pixels  
        "min_face_confidence": 0.5          # Minimum YOLO face detection confidence
    }
    
    def __init__(self, settings_file: Optional[str] = None):
        """
        Initialize the settings manager.
        
        Args:
            settings_file: Optional custom path for settings file
        """
        self.settings_file = settings_file or self.SETTINGS_FILE
        self._settings: Dict[str, Any] = self.DEFAULTS.copy()
        self.load()
    
    def load(self) -> Dict[str, Any]:
        """
        Load settings from JSON file. Uses defaults if file doesn't exist.
        
        Returns:
            The loaded settings dictionary
        """
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults (in case new settings were added)
                    self._settings = {**self.DEFAULTS, **loaded}
                    print(f"[SETTINGS] Loaded settings from {self.settings_file}")
            except Exception as e:
                print(f"[SETTINGS] Error loading settings: {e}")
                self._settings = self.DEFAULTS.copy()
        else:
            print(f"[SETTINGS] No settings file found, using defaults")
            self._settings = self.DEFAULTS.copy()
        
        return self._settings
    
    def save(self) -> bool:
        """
        Save current settings to JSON file.
        
        Returns:
            True if save was successful, False otherwise
        """
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self._settings, f, indent=4)
            print(f"[SETTINGS] Saved settings to {self.settings_file}")
            return True
        except Exception as e:
            print(f"[SETTINGS] Error saving settings: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Args:
            key: Setting key
            default: Default value if key not found
            
        Returns:
            The setting value or default
        """
        return self._settings.get(key, default if default is not None else self.DEFAULTS.get(key))
    
    def set(self, key: str, value: Any) -> None:
        """
        Set a setting value (does not auto-save).
        
        Args:
            key: Setting key
            value: Setting value
        """
        self._settings[key] = value
    
    def get_all(self) -> Dict[str, Any]:
        """Get all current settings as a dictionary."""
        return self._settings.copy()
    
    def reset_defaults(self) -> Dict[str, Any]:
        """
        Reset all settings to defaults (does not auto-save).
        
        Returns:
            The default settings dictionary
        """
        self._settings = self.DEFAULTS.copy()
        print("[SETTINGS] Reset to defaults")
        return self._settings
    
    def __repr__(self) -> str:
        return f"SettingsManager({self._settings})"


# Global singleton instance (optional, can also create instances as needed)
_global_settings: Optional[SettingsManager] = None


def get_settings() -> SettingsManager:
    """Get the global settings manager instance."""
    global _global_settings
    if _global_settings is None:
        _global_settings = SettingsManager()
    return _global_settings
