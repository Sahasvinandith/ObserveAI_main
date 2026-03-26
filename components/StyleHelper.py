"""
StyleHelper.py - Centralized styling for the ObserveAI application.
"""

def apply_global_style(app):
    """
    Apply a global dark purple theme to the QApplication instance.
    This ensures all standard dialogs (QInputDialog, QMessageBox, QFileDialog) 
    and child widgets follow the app's aesthetic.
    """
    app.setStyleSheet("""
        QMainWindow, QDialog, QMessageBox, QInputDialog, QColorDialog, QFileDialog {
            background-color: rgb(39, 7, 40);
            color: white;
        }
        
        /* Catch-all for dialog backgrounds and their immediate children */
        QDialog QWidget {
            background-color: rgb(39, 7, 40);
            color: white;
        }
        
        QLabel { 
            background-color: transparent;
            color: white;
        }
        
        QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QAbstractItemView, QListWidget, QListView, QTextEdit, QPlainTextEdit {
            background-color: rgb(60, 30, 65);
            color: white;
            border: 1px solid #7a3a8a;
            padding: 4px;
            border-radius: 4px;
        }
        
        /* Specific overrides for controls inside dialogs to ensure they are visible against the dark background */
        QDialog QLineEdit, QDialog QDoubleSpinBox, QDialog QSpinBox, QDialog QComboBox, QDialog QListWidget, QDialog QListView {
            background-color: rgb(60, 30, 65);
        }
        
        QComboBox QAbstractItemView {
            background-color: rgb(60, 30, 65);
            selection-background-color: rgb(100, 50, 110);
        }
        
        QPushButton {
            background-color: rgb(80, 40, 95);
            color: white;
            border: 1px solid #7a3a8a;
            padding: 5px 15px;
            border-radius: 4px;
            min-width: 80px;
        }
        
        QDialog QPushButton {
            background-color: rgb(80, 40, 95);
        }
        
        QPushButton:hover {
            background-color: rgb(110, 60, 130);
        }
        
        QPushButton:pressed {
            background-color: rgb(130, 70, 150);
        }
        
        /* Menus */
        QMenu {
            background-color: rgb(60, 30, 65);
            color: white;
            border: 1px solid #7a3a8a;
        }
        QMenu::item:selected {
            background-color: rgb(100, 50, 110);
        }
        
        /* Tabs */
        QTabWidget::pane {
            border: 1px solid #7a3a8a;
            background-color: rgb(39, 7, 40);
        }
        QTabBar::tab {
            background-color: rgb(50, 20, 55);
            color: #aaa;
            padding: 8px 12px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }
        QTabBar::tab:selected {
            background-color: rgb(80, 40, 95);
            color: white;
        }
        
        /* ScrollBars */
        QScrollBar:vertical {
            border: none;
            background: rgb(30, 10, 30);
            width: 10px;
            margin: 0px 0px 0px 0px;
        }
        QScrollBar::handle:vertical {
            background: rgb(80, 40, 95);
            min-height: 20px;
            border-radius: 5px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            border: none;
            background: none;
        }
        
        QScrollBar:horizontal {
            border: none;
            background: rgb(30, 10, 30);
            height: 10px;
            margin: 0px 0px 0px 0px;
        }
        QScrollBar::handle:horizontal {
            background: rgb(80, 40, 95);
            min-width: 20px;
            border-radius: 5px;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            border: none;
            background: none;
        }
    """)
