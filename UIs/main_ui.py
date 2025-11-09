# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main.ui'
##
## Created by: Qt User Interface Compiler version 6.10.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QGraphicsView, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QSizePolicy, QSpacerItem, QStackedWidget, QStatusBar,
    QVBoxLayout, QWidget)
import resources_rc

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(888, 655)
        MainWindow.setMinimumSize(QSize(1, 0))
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.centralwidget.setAutoFillBackground(True)
        self.horizontalLayout_2 = QHBoxLayout(self.centralwidget)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.Menubar = QWidget(self.centralwidget)
        self.Menubar.setObjectName(u"Menubar")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.Menubar.sizePolicy().hasHeightForWidth())
        self.Menubar.setSizePolicy(sizePolicy)
        self.Menubar.setSizeIncrement(QSize(1, 0))
        self.Menubar.setStyleSheet(u"background-color:rgb(60, 30, 65)")
        self.verticalLayout = QVBoxLayout(self.Menubar)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.cam_set_btn = QPushButton(self.Menubar)
        self.cam_set_btn.setObjectName(u"cam_set_btn")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(2)
        sizePolicy1.setHeightForWidth(self.cam_set_btn.sizePolicy().hasHeightForWidth())
        self.cam_set_btn.setSizePolicy(sizePolicy1)

        self.verticalLayout.addWidget(self.cam_set_btn)

        self.cam_feed_btn = QPushButton(self.Menubar)
        self.cam_feed_btn.setObjectName(u"cam_feed_btn")
        sizePolicy1.setHeightForWidth(self.cam_feed_btn.sizePolicy().hasHeightForWidth())
        self.cam_feed_btn.setSizePolicy(sizePolicy1)

        self.verticalLayout.addWidget(self.cam_feed_btn)

        self.db_btn = QPushButton(self.Menubar)
        self.db_btn.setObjectName(u"db_btn")
        sizePolicy1.setHeightForWidth(self.db_btn.sizePolicy().hasHeightForWidth())
        self.db_btn.setSizePolicy(sizePolicy1)

        self.verticalLayout.addWidget(self.db_btn)


        self.horizontalLayout_2.addWidget(self.Menubar)

        self.Content = QWidget(self.centralwidget)
        self.Content.setObjectName(u"Content")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizePolicy2.setHorizontalStretch(6)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.Content.sizePolicy().hasHeightForWidth())
        self.Content.setSizePolicy(sizePolicy2)
        self.Content.setSizeIncrement(QSize(100, 0))
        self.Content.setStyleSheet(u"background-color: rgb(39, 7, 40);")
        self.horizontalLayout = QHBoxLayout(self.Content)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.Content_stack = QStackedWidget(self.Content)
        self.Content_stack.setObjectName(u"Content_stack")
        self.cam_settings_page = QWidget()
        self.cam_settings_page.setObjectName(u"cam_settings_page")
        self.verticalLayout_2 = QVBoxLayout(self.cam_settings_page)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.label_2 = QLabel(self.cam_settings_page)
        self.label_2.setObjectName(u"label_2")
        self.label_2.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout_2.addWidget(self.label_2)

        self.widget = QWidget(self.cam_settings_page)
        self.widget.setObjectName(u"widget")
        self.widget.setMinimumSize(QSize(0, 10))
        self.horizontalLayout_5 = QHBoxLayout(self.widget)
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.add_camera_btn = QPushButton(self.widget)
        self.add_camera_btn.setObjectName(u"add_camera_btn")

        self.horizontalLayout_5.addWidget(self.add_camera_btn)

        self.horizontalSpacer_2 = QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_5.addItem(self.horizontalSpacer_2)

        self.add_wall_btn = QPushButton(self.widget)
        self.add_wall_btn.setObjectName(u"add_wall_btn")

        self.horizontalLayout_5.addWidget(self.add_wall_btn)

        self.horizontalSpacer_3 = QSpacerItem(100, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_5.addItem(self.horizontalSpacer_3)

        self.save_map_btn = QPushButton(self.widget)
        self.save_map_btn.setObjectName(u"save_map_btn")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.save_map_btn.sizePolicy().hasHeightForWidth())
        self.save_map_btn.setSizePolicy(sizePolicy3)

        self.horizontalLayout_5.addWidget(self.save_map_btn)

        self.horizontalSpacer = QSpacerItem(20, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_5.addItem(self.horizontalSpacer)


        self.verticalLayout_2.addWidget(self.widget)

        self.widget_2 = QWidget(self.cam_settings_page)
        self.widget_2.setObjectName(u"widget_2")
        self.horizontalLayout_7 = QHBoxLayout(self.widget_2)
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.drag_area = QGraphicsView(self.widget_2)
        self.drag_area.setObjectName(u"drag_area")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy4.setHorizontalStretch(5)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.drag_area.sizePolicy().hasHeightForWidth())
        self.drag_area.setSizePolicy(sizePolicy4)
        self.drag_area.setStyleSheet(u"background-color: rgb(44, 29, 44);\n"
"border-color: rgb(34, 34, 34);")

        self.horizontalLayout_7.addWidget(self.drag_area)

        self.cam_list = QListWidget(self.widget_2)
        self.cam_list.setObjectName(u"cam_list")
        sizePolicy5 = QSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Expanding)
        sizePolicy5.setHorizontalStretch(1)
        sizePolicy5.setVerticalStretch(0)
        sizePolicy5.setHeightForWidth(self.cam_list.sizePolicy().hasHeightForWidth())
        self.cam_list.setSizePolicy(sizePolicy5)
        self.cam_list.setMinimumSize(QSize(0, 0))

        self.horizontalLayout_7.addWidget(self.cam_list)


        self.verticalLayout_2.addWidget(self.widget_2)

        self.Content_stack.addWidget(self.cam_settings_page)
        self.cam_feed_page = QWidget()
        self.cam_feed_page.setObjectName(u"cam_feed_page")
        self.horizontalLayout_4 = QHBoxLayout(self.cam_feed_page)
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.label_3 = QLabel(self.cam_feed_page)
        self.label_3.setObjectName(u"label_3")

        self.horizontalLayout_4.addWidget(self.label_3)

        self.Content_stack.addWidget(self.cam_feed_page)
        self.database_page = QWidget()
        self.database_page.setObjectName(u"database_page")
        self.horizontalLayout_3 = QHBoxLayout(self.database_page)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.label_4 = QLabel(self.database_page)
        self.label_4.setObjectName(u"label_4")

        self.horizontalLayout_3.addWidget(self.label_4)

        self.Content_stack.addWidget(self.database_page)

        self.horizontalLayout.addWidget(self.Content_stack)


        self.horizontalLayout_2.addWidget(self.Content)

        MainWindow.setCentralWidget(self.centralwidget)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.retranslateUi(MainWindow)
        self.cam_set_btn.pressed.connect(self.Content_stack.lower)

        self.Content_stack.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.cam_set_btn.setText(QCoreApplication.translate("MainWindow", u"Camera settings", None))
        self.cam_feed_btn.setText(QCoreApplication.translate("MainWindow", u"Camera feed", None))
        self.db_btn.setText(QCoreApplication.translate("MainWindow", u"Database", None))
        self.label_2.setText(QCoreApplication.translate("MainWindow", u"Camera settings page", None))
        self.add_camera_btn.setText(QCoreApplication.translate("MainWindow", u"Add Camera", None))
        self.add_wall_btn.setText(QCoreApplication.translate("MainWindow", u"Add Wall", None))
        self.save_map_btn.setText(QCoreApplication.translate("MainWindow", u"Save Map", None))
        self.label_3.setText(QCoreApplication.translate("MainWindow", u"Cam Feed page", None))
        self.label_4.setText(QCoreApplication.translate("MainWindow", u"Database", None))
    # retranslateUi

