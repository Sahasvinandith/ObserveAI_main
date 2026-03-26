"""
AddCamera_Dialog.py - Dual-mode Add Camera dialog

Modes:
  • Local Camera  – auto-detects connected V4L2/USB cameras, user picks from a list
  • Network / URL – user types any URL or device path manually
"""

import subprocess
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QDoubleSpinBox, QDialogButtonBox, QTabWidget,
    QWidget, QPushButton, QListWidget, QListWidgetItem, QFrame
)
from DataModel.ActionManager import ActionManager
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

# ─────────────────────────── helpers ────────────────────────────

def detect_local_cameras() -> list[dict]:
    """
    Enumerate USB / V4L2 cameras using v4l2-ctl.
    Returns a list of dicts: {'name': str, 'device': str}
    Falls back to probing /dev/video0-9 with cv2 if v4l2-ctl is absent.
    """
    cameras = []

    # Try v4l2-ctl first (most reliable on Linux)
    try:
        output = subprocess.check_output(
            ["v4l2-ctl", "--list-devices"],
            stderr=subprocess.DEVNULL,
            timeout=3
        ).decode("utf-8", errors="ignore")

        current_name = None
        dev_re = re.compile(r"^\s+(/dev/video\d+)\s*$")
        for line in output.splitlines():
            dev_match = dev_re.match(line)
            if dev_match:
                dev = dev_match.group(1)
                # Only include the first (primary) node per camera
                if current_name and not any(c["device"] == dev for c in cameras):
                    cameras.append({"name": current_name, "device": dev})
                    current_name = None  # Reset so next node is skipped
            elif line.strip() and not line.startswith("\t") and not line.startswith(" "):
                # This is a camera name line
                current_name = line.strip().rstrip(":")
        return cameras

    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass

    # Fallback: try to open /dev/video0-9 and keep the ones that work
    import cv2
    for i in range(10):
        cap = cv2.VideoCapture(f"/dev/video{i}")
        if cap.isOpened():
            cameras.append({"name": f"Camera (video{i})", "device": f"/dev/video{i}"})
            cap.release()
    return cameras


# ─────────────────────────── dialog ─────────────────────────────

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
QLineEdit, QDoubleSpinBox, QComboBox {
    background-color: rgb(60, 30, 65);
    color: white;
    border: 1px solid #7a3a8a;
    padding: 5px;
    border-radius: 4px;
}
QComboBox QAbstractItemView {
    background-color: rgb(60, 30, 65);
    color: white;
    selection-background-color: rgb(100, 50, 110);
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
QTabWidget::pane {
    border: 1px solid #7a3a8a;
    background-color: rgb(50, 10, 55);
    border-radius: 4px;
}
QTabBar::tab {
    background-color: rgb(60, 20, 70);
    color: #ccc;
    padding: 6px 18px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected {
    background-color: rgb(100, 50, 110);
    color: white;
}
QFrame#divider {
    background-color: #7a3a8a;
    max-height: 1px;
}
QDialogButtonBox QPushButton {
    min-width: 80px;
}
"""


class AddCameraDialog(QDialog):
    """
    Add Camera dialog with two modes:
      • Local Camera tab – auto-detect USB/V4L2 devices
      • Network / URL tab – manual URL / device path entry
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Camera")
        self.setMinimumWidth(420)
        self.setStyleSheet(_STYLE)

        self._detected_cameras: list[dict] = []

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(18, 18, 18, 16)

        # ── Title ──────────────────────────────────────────────
        title = QLabel("Add a Camera")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        divider = QFrame()
        divider.setObjectName("divider")
        root.addWidget(divider)

        # ── Camera Name ─────────────────────────────────────────
        root.addWidget(QLabel("Camera Name"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Lobby Camera")
        root.addWidget(self.name_input)

        # ── Tabs ────────────────────────────────────────────────
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self._build_local_tab()
        self._build_url_tab()

        # ── FOV + Range row ─────────────────────────────────────
        fov_row = QHBoxLayout()
        fov_row.setSpacing(12)

        fov_col = QVBoxLayout()
        fov_col.addWidget(QLabel("View Angle (FOV)"))
        self.fov_input = QDoubleSpinBox()
        self.fov_input.setRange(10, 180)
        self.fov_input.setSingleStep(5)
        self.fov_input.setValue(70)
        self.fov_input.setSuffix("°")
        fov_col.addWidget(self.fov_input)
        fov_row.addLayout(fov_col)

        rng_col = QVBoxLayout()
        rng_col.addWidget(QLabel("View Range (px)"))
        self.view_range_input = QDoubleSpinBox()
        self.view_range_input.setRange(50, 1000)
        self.view_range_input.setSingleStep(10)
        self.view_range_input.setValue(200)
        self.view_range_input.setSuffix(" px")
        rng_col.addWidget(self.view_range_input)
        fov_row.addLayout(rng_col)

        root.addLayout(fov_row)

        # ── Actions Selection ───────────────────────────────────
        self.action_manager = ActionManager()
        custom_actions = self.action_manager.get_action_list()

        actions_col = QVBoxLayout()
        actions_col.addWidget(QLabel("Select Actions to Track:"))
        self.actions_list_widget = QListWidget()
        self.actions_list_widget.setMaximumHeight(80)
        for act in custom_actions:
            item = QListWidgetItem(act)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.actions_list_widget.addItem(item)
        actions_col.addWidget(self.actions_list_widget)
        root.addLayout(actions_col)

        # ── Buttons ─────────────────────────────────────────────
        self.buttonBox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        root.addWidget(self.buttonBox)

    # ── Local Camera Tab ────────────────────────────────────────

    def _build_local_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)

        info = QLabel("Select a connected camera from the list below:")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.camera_list = QListWidget()
        self.camera_list.setMinimumHeight(100)
        layout.addWidget(self.camera_list)

        refresh_btn = QPushButton("🔄  Refresh Camera List")
        refresh_btn.clicked.connect(self._refresh_local_cameras)
        layout.addWidget(refresh_btn)

        self.tabs.addTab(widget, "📷  Local Camera")
        self._refresh_local_cameras()

    def _refresh_local_cameras(self):
        self.camera_list.clear()
        self._detected_cameras = detect_local_cameras()

        if not self._detected_cameras:
            item = QListWidgetItem("⚠  No local cameras detected")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.camera_list.addItem(item)
        else:
            for cam in self._detected_cameras:
                label = f"{cam['name']}   [{cam['device']}]"
                self.camera_list.addItem(QListWidgetItem(label))
            self.camera_list.setCurrentRow(0)

            # Auto-fill the name field if it's still empty
            if not self.name_input.text().strip():
                self.name_input.setText(self._detected_cameras[0]["name"].split(":")[0].strip())

    # ── URL / Network Tab ───────────────────────────────────────

    def _build_url_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Camera URL, IP stream, or device path:"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("rtsp://192.168.1.x:554/stream  or  /dev/video2")
        layout.addWidget(self.url_input)

        hint = QLabel(
            "Examples:\n"
            "• rtsp://user:pass@192.168.1.10/stream\n"
            "• http://192.168.1.10:8080/video\n"
            "• /dev/video2  (Linux device path)\n"
            "• 0  (first webcam by index)"
        )
        hint.setStyleSheet("color: #aaa; font-size: 10pt;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()
        self.tabs.addTab(widget, "🌐  Network / URL")

    # ── Public API ──────────────────────────────────────────────

    def get_details(self) -> tuple:
        """
        Returns (name, url_or_device, fov, view_range, selected_actions).
        Works regardless of which tab is active.
        """
        name = self.name_input.text().strip() or "Camera"
        fov = self.fov_input.value()
        rng = self.view_range_input.value()

        selected_actions = []
        for i in range(self.actions_list_widget.count()):
            item = self.actions_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_actions.append(item.text())

        if self.tabs.currentIndex() == 0:
            # Local Camera tab
            row = self.camera_list.currentRow()
            if 0 <= row < len(self._detected_cameras):
                device = self._detected_cameras[row]["device"]
            else:
                device = ""
            return (name, device, fov, rng, selected_actions)
        else:
            # URL tab
            return (name, self.url_input.text().strip(), fov, rng, selected_actions)
