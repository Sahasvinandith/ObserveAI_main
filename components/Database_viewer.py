import os
from PyQt6.QtWidgets import QWidget, QLabel, QListWidgetItem, QHBoxLayout, QSizePolicy, QMenu, QInputDialog, QMessageBox
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtCore import Qt, QSize
from PyQt6.uic import loadUi

class DatabaseViewer(QWidget):
    def __init__(self, db_path="Faces_db", tracker=None):
        super().__init__()
        self.db_path = db_path
        self.tracker = tracker
        
        # Load the new UI file
        loadUi("./UIs/database_viewer.ui", self)
        # Inherits style from StyleHelper
        
        # Internal data storage
        self.all_ids = [] # List of folder names
        
        # Connect Signals
        self.person_list.itemClicked.connect(self.load_person_details)
        self.search_bar.textChanged.connect(self.filter_list)
        
        # Context menu for renaming
        self.person_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.person_list.customContextMenuRequested.connect(self.show_context_menu)
        
        # Initial Load
        self.refresh_database()

    def show_context_menu(self, pos):
        """Shows context menu for the person list."""
        item = self.person_list.itemAt(pos)
        if not item:
            return
            
        menu = QMenu(self)
        rename_action = menu.addAction("Rename Person")
        
        # Execute menu
        action = menu.exec(self.person_list.viewport().mapToGlobal(pos))
        
        if action == rename_action:
            self.rename_current_person(item)

    def rename_current_person(self, item):
        """Triggers the renaming mechanism."""
        old_name = item.text()
        
        new_name, ok = QInputDialog.getText(
            self, "Rename Person", 
            f"Enter new name for '{old_name}':",
            text=old_name
        )
        
        if not ok or not new_name.strip():
            return
            
        new_name = new_name.strip()
        
        if new_name == old_name:
            return
            
        # Validation: check if new name already exists
        if new_name in self.all_ids:
            QMessageBox.warning(self, "Rename Error", f"A person named '{new_name}' already exists.")
            return

        # Perform rename via tracker if available, otherwise fallback to cache
        success = False
        if self.tracker:
            success = self.tracker.rename_user(old_name, new_name)
        else:
            # Fallback for standalone use
            try:
                from DataModel.EmbeddingCache import get_embedding_cache
                success = get_embedding_cache().rename_user(old_name, new_name)
            except Exception as e:
                print(f"[DB VIEWER] Error in standalone rename: {e}")
                
        if success:
            # Refresh list
            self.refresh_database()
            # Select the new name
            items = self.person_list.findItems(new_name, Qt.MatchFlag.MatchExactly)
            if items:
                self.person_list.setCurrentItem(items[0])
                self.load_person_details(items[0])
            QMessageBox.information(self, "Success", f"Person renamed to '{new_name}'")
        else:
            QMessageBox.critical(self, "Error", "Failed to rename person. Check logs for details.")

    def resizeEvent(self, event):

        """
        Auto-scales the main image when the window is resized.
        """
        # If a person is currently selected (we check if we stored the current path)
        if hasattr(self, 'current_image_path') and self.current_image_path:
            self.set_main_image(self.current_image_path)
        
        super().resizeEvent(event)

    def refresh_database(self):
        """Scans the Faces_db directory and populates the list."""
        self.person_list.clear()
        self.all_ids = []
        
        if not os.path.exists(self.db_path):
            os.makedirs(self.db_path)
            return

        # Get all subdirectories (which represent Person IDs)
        dirs = sorted([d for d in os.listdir(self.db_path) if os.path.isdir(os.path.join(self.db_path, d))])
        
        for d in dirs:
            self.all_ids.append(d)
            self.add_item_to_list(d)

    def add_item_to_list(self, name):
        item = QListWidgetItem(name)
        # You could add an icon here if you want
        # item.setIcon(QIcon("path/to/icon.png"))
        self.person_list.addItem(item)

    def filter_list(self, text):
        """Filters the QListWidget based on search text."""
        self.person_list.clear()
        search_text = text.lower()
        
        for name in self.all_ids:
            if search_text in name.lower():
                self.add_item_to_list(name)

    def load_person_details(self, item):
        """When a name is clicked, load their images."""
        person_id = item.text()
        folder_path = os.path.join(self.db_path, person_id)
        
        self.person_name_lbl.setText(f"Person ID: {person_id}")
        
        # Get all images in that folder
        valid_extensions = ('.jpg', '.jpeg', '.png')
        images = [f for f in os.listdir(folder_path) if f.lower().endswith(valid_extensions)]
        images.sort() # Ensure order
        
        if not images:
            self.main_image_lbl.setText("No Images Found")
            self.clear_gallery()
            return

        # 1. Set Main Image (First one)
        main_img_path = os.path.join(folder_path, images[0])
        self.set_main_image(main_img_path)
        
        # 2. Populate Gallery (Rest of them)
        self.clear_gallery()
        for img_file in images: # Show all, including first, in gallery
            img_path = os.path.join(folder_path, img_file)
            self.add_to_gallery(img_path)

    def set_main_image(self, path):
        self.current_image_path = path
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            # Scale while keeping aspect ratio
            scaled_pixmap = pixmap.scaled(
                self.main_image_lbl.size(), 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.main_image_lbl.setPixmap(scaled_pixmap)
        else:
            self.main_image_lbl.setText("Invalid Image")

    def clear_gallery(self):
        """Removes all widgets from the gallery layout."""
        layout = self.gallery_layout
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def add_to_gallery(self, path):
        """Adds a small clickable thumbnail to the gallery."""
        lbl = QLabel()
        lbl.setFixedSize(100, 100)
        lbl.setStyleSheet("border: 1px solid #555; background-color: black;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            lbl.setPixmap(scaled)
            
            # Make the label clickable (Basic way: MouseReleaseEvent)
            # We bind the current path to the lambda so clicking it updates the main view
            lbl.mouseReleaseEvent = lambda e: self.set_main_image(path)
            
        self.gallery_layout.addWidget(lbl)