import sys
from PyQt6.QtWidgets import QApplication
from main.MainWindow import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.setWindowTitle("ObserveAI")
    # window.showMaximized()
    window.showMinimized()
    sys.exit(app.exec())
