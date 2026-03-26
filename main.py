import os
import sys
os.environ["TF_USE_LEGACY_KERAS"] = "1"
import tensorflow
from PyQt6.QtWidgets import QApplication
from main.MainWindow import MainWindow
from components.StyleHelper import apply_global_style

if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_global_style(app)
    
    window = MainWindow()
    window.setWindowTitle("ObserveAI")
    # window.showMaximized()
    window.showMinimized()
    sys.exit(app.exec())
