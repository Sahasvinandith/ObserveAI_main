from PyQt6.QtWidgets import (QDialog,QLabel, QVBoxLayout, QLineEdit, QDialogButtonBox)

# --- AddCameraDialog class (no changes) ---
class AddCameraDialog(QDialog):
    """
    A simple popup dialog to get a camera name and IP/URL.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Camera")
        
        self.layout = QVBoxLayout(self)
        # Camera Name Entry
        self.name_label = QLabel("Camera Name:")
        self.name_input = QLineEdit("Lobby Camera")
        self.layout.addWidget(self.name_label)
        self.layout.addWidget(self.name_input)
        
        # Camera URL/IP Entry
        self.url_label = QLabel("Camera URL (or 0 for webcam):")
        self.url_input = QLineEdit("0")
        self.layout.addWidget(self.url_label)
        self.layout.addWidget(self.url_input)
        
        # OK and Cancel Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)

    def get_details(self):
        """Helper function to return the entered text."""
        return self.name_input.text(), self.url_input.text()
