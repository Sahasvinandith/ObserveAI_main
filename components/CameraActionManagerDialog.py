"""
CameraActionManagerDialog.py

Lets users add or remove actions on any camera that has already been created —
including cameras whose AI thread is already running (uses reload_actions() for
hot-reload with no restart required).
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QDialogButtonBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from DataModel.ActionManager import ActionManager
from DataModel.SettingsManager import get_settings


_STYLE = """
QDialog {
    background-color: rgb(39, 7, 40);
    color: white;
}
QLabel {
    color: white;
    background-color: transparent;
    border: none;
}
QListWidget {
    background-color: rgb(50, 20, 55);
    color: white;
    border: 1px solid #7a3a8a;
    border-radius: 4px;
}
QListWidget::item:selected {
    background-color: rgb(100, 50, 110);
}
QPushButton {
    background-color: rgb(80, 30, 90);
    color: white;
    border: 1px solid rgb(130, 60, 150);
    padding: 6px 16px;
    border-radius: 4px;
}
QPushButton:hover { background-color: rgb(120, 50, 130); }
QPushButton:pressed { background-color: rgb(60, 20, 70); }
QFrame#divider {
    background-color: #7a3a8a;
    max-height: 1px;
}
"""


class CameraActionManagerDialog(QDialog):
    """
    Two-panel dialog:
      Left  – camera list (select which camera to configure)
      Right – action checklist (check / uncheck to assign / remove actions)

    On OK:
      1. Saves `camera_actions` back to settings.json
      2. Calls `detection_system.reload_actions()` on every running AI instance
         so changes take effect immediately without restarting the app.

    Parameters
    ----------
    camera_names : list[str]
        Names of all cameras currently configured in MainWindow.
    ai_instances : dict[str, DetectionSystem]
        Live DetectionSystem objects keyed by camera name.
    parent : QWidget, optional
    """

    def __init__(self, camera_names: list, ai_instances: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Camera Actions")
        self.setMinimumSize(540, 380)
        self.setStyleSheet(_STYLE)

        self._camera_names = camera_names
        self._ai_instances = ai_instances
        self._action_manager = ActionManager()
        self._settings = get_settings()

        # In-memory working copy of assignments so we can edit freely
        stored = self._settings.get("camera_actions", {}) or {}
        # Deep-copy to avoid mutating settings in place until OK is pressed
        self._assignments: dict[str, list] = {cam: list(stored.get(cam, [])) for cam in camera_names}

        self._build_ui()
        # Select the first camera by default
        if self._camera_names:
            self.camera_list.setCurrentRow(0)
            self._on_camera_selected(self.camera_list.currentItem())

    # ─────────────── UI construction ────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(18, 18, 18, 16)

        # Title
        title = QLabel("Manage Camera Actions")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        divider = QFrame()
        divider.setObjectName("divider")
        root.addWidget(divider)

        hint = QLabel("Select a camera on the left, then check the actions you want to enable for it.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaa; font-size: 10pt;")
        root.addWidget(hint)

        # Main two-panel area
        panels = QHBoxLayout()
        panels.setSpacing(16)

        # Left — cameras
        left_col = QVBoxLayout()
        left_col.addWidget(QLabel("Cameras"))
        self.camera_list = QListWidget()
        for name in self._camera_names:
            self.camera_list.addItem(QListWidgetItem(name))
        self.camera_list.currentItemChanged.connect(self._on_camera_selected)
        left_col.addWidget(self.camera_list)
        panels.addLayout(left_col, stretch=2)

        # Right — actions
        right_col = QVBoxLayout()
        right_col.addWidget(QLabel("Actions"))
        self.action_list = QListWidget()
        right_col.addWidget(self.action_list)
        panels.addLayout(right_col, stretch=3)

        root.addLayout(panels)

        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_ok)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    # ─────────────── Interaction ─────────────────────────────────

    def _on_camera_selected(self, item):
        """Populate the action checklist for the selected camera."""
        if item is None:
            return
        cam_name = item.text()
        assigned = self._assignments.get(cam_name, [])
        all_actions = self._action_manager.get_action_list()

        # Save current checklist state before switching (if another camera was selected)
        prev_item = self.camera_list.currentItem()
        if prev_item and prev_item.text() != cam_name:
            self._save_current_checklist(prev_item.text())

        # Rebuild checklist for the newly selected camera
        self.action_list.blockSignals(True)
        self.action_list.clear()
        for act in all_actions:
            list_item = QListWidgetItem(act)
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            state = Qt.CheckState.Checked if act in assigned else Qt.CheckState.Unchecked
            list_item.setCheckState(state)
            self.action_list.addItem(list_item)
        self.action_list.blockSignals(False)

        self._current_camera = cam_name

    def _save_current_checklist(self, cam_name: str):
        """Read the current checklist state into _assignments for cam_name."""
        selected = []
        for i in range(self.action_list.count()):
            it = self.action_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                selected.append(it.text())
        self._assignments[cam_name] = selected

    # ─────────────── OK handler ───────────────────────────────────

    def _on_ok(self):
        # Flush the currently displayed checklist
        if hasattr(self, '_current_camera'):
            self._save_current_checklist(self._current_camera)

        # 1. Persist to settings
        cam_actions = self._settings.get("camera_actions", {}) or {}
        for cam, actions in self._assignments.items():
            cam_actions[cam] = actions
        self._settings.set("camera_actions", cam_actions)
        self._settings.save()
        print(f"[ACTION MANAGER] Saved camera actions: {self._assignments}")

        # 2. Hot-reload each affected running DetectionSystem
        for cam_name, detection_system in self._ai_instances.items():
            if cam_name in self._assignments:
                try:
                    detection_system.reload_actions()
                    print(f"[ACTION MANAGER] Hot-reloaded actions for camera '{cam_name}'")
                except Exception as e:
                    print(f"[ACTION MANAGER] Failed to reload actions for '{cam_name}': {e}")

        self.accept()
