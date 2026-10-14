"""MiniDrive main window: sidebar (navigation + folder tree), top bar (language, user,
logout) and the pages — the same structure as the web client."""

import time

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import theme
from app.api_client import ApiClient
from app.drive_page import ColumnsController, DrivePage
from app.folders import folder_label
from app.i18n import describe_error, language, tr
from app.sync.sync_page import SyncPage
from app.widgets import Segmented, Toaster, button, label
from app.worker import run_task


class MainWindow(QMainWindow):
    logout_requested = Signal()
    language_change_requested = Signal(str, str)  # language, current folder id

    def __init__(self, api: ApiClient, folder_id: str | None = None):
        super().__init__()
        self.api = api
        self.settings = QSettings("MiniDrive", "Desktop")
        self.folders: list[dict] = []
        self.current_folder_id: str | None = folder_id
        self.logging_out = False
        self.replacing = False
        user = api.user or {}
        self.setWindowTitle(tr("app.name"))
        self.resize(1320, 820)
        self.setMinimumSize(QSize(980, 620))

        self.toaster = None
        self.columns = ColumnsController(api, self.settings, self)
        self._build(user)
        # parented to the window: a child of the splitter would become an extra splitter pane
        self.toaster = Toaster(self)
        self.columns.problem.connect(
            lambda kind: self.toast(tr("columns.savedLocally" if kind == "save" else "columns.loadFailed"), "error"))
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        QShortcut(QKeySequence.Delete, self, activated=self.drive.delete_selected)
        self.load_folders(select_id=folder_id or user.get("root_folder_id"))

    # --- construction -------------------------------------------------------------------

    def _build(self, user: dict) -> None:
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        splitter.addWidget(self._sidebar())
        splitter.addWidget(self._main_column(user))
        splitter.setSizes([264, 1056])
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

    def _sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(380)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(theme.brand_mark(34))
        brand.addWidget(mark)
        brand.addWidget(label(tr("app.name"), "brand"))
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_drive = self._nav_button("hardDrive", tr("nav.myDrive"))
        self.nav_sync = self._nav_button("sync", tr("nav.sync"))
        self.nav_drive.setChecked(True)
        self.nav_drive.clicked.connect(lambda: self.show_page("drive"))
        self.nav_sync.clicked.connect(lambda: self.show_page("sync"))
        layout.addWidget(self.nav_drive)
        layout.addWidget(self.nav_sync)
        layout.addSpacing(16)
        layout.addWidget(label(tr("nav.folders").upper(), "sidebarLabel"))

        self.tree = QTreeWidget()
        self.tree.setObjectName("folderTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setRootIsDecorated(False)  # like the web: "My Drive" without an expander
        self.tree.setFocusPolicy(Qt.NoFocus)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setTextElideMode(Qt.ElideRight)
        self.tree.itemClicked.connect(lambda item, _col: self.open_folder(item.data(0, Qt.UserRole)))
        layout.addWidget(self.tree, 1)
        return sidebar

    def _nav_button(self, icon_name: str, text: str) -> QPushButton:
        nav = QPushButton(text)
        nav.setFixedHeight(38)
        nav.setProperty("nav", "true")
        nav.setCheckable(True)
        nav.setIcon(theme.icon(icon_name, theme.TEXT_2, 18))
        nav.setIconSize(theme.ICON_SIZE)
        nav.setCursor(Qt.PointingHandCursor)
        self.nav_group.addButton(nav)
        return nav

    def _main_column(self, user: dict) -> QWidget:
        column = QWidget()
        column.setObjectName("content")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        topbar = QFrame()
        topbar.setObjectName("topbar")
        topbar.setFixedHeight(60)
        bar = QHBoxLayout(topbar)
        bar.setContentsMargins(24, 0, 20, 0)
        bar.setSpacing(12)
        bar.addStretch(1)
        self.lang = Segmented([("uk", "UA"), ("en", "EN")], language())
        self.lang.setAccessibleName(tr("lang.label"))
        self.lang.changed.connect(self.change_language)
        bar.addWidget(self.lang)
        name = user.get("display_name") or user.get("email", "")
        avatar = QLabel()
        avatar.setPixmap(theme.avatar((name or "?")[:1].upper(), 34))
        bar.addWidget(avatar)
        who = QVBoxLayout()
        who.setSpacing(0)
        who.addWidget(label(name, "userName"))
        who.addWidget(label(f"@{user['username']}" if user.get("username") else user.get("email", ""), "userSub"))
        bar.addLayout(who)
        logout = button(tr("auth.logout"), "ghost", "logout", height=theme.CONTROL_HEIGHT)
        logout.clicked.connect(self.logout)
        bar.addWidget(logout)
        layout.addWidget(topbar)

        self.pages = QStackedWidget()
        self.drive = DrivePage(self.api, self.columns, self.toast)
        self.drive.open_folder.connect(self.open_folder)
        self.drive.folders_changed.connect(lambda fid: self.load_folders(select_id=fid))
        self.sync = SyncPage(self.api, self.toast)
        self.sync.synced.connect(lambda: self.load_folders())
        self.pages.addWidget(self.drive)
        self.pages.addWidget(self.sync)
        layout.addWidget(self.pages, 1)
        return column

    # --- helpers -----------------------------------------------------------------------------

    def toast(self, message: str, tone: str = "info") -> None:
        if self.toaster is not None:
            self.toaster.show_toast(message, tone)

    def show_page(self, page: str) -> None:
        if page == "sync":
            self.nav_sync.setChecked(True)
            self.sync.set_folders(self.folders, self.current_folder_id)
            self.sync.refresh_history()
            self.pages.setCurrentWidget(self.sync)
        else:
            self.nav_drive.setChecked(True)
            self.pages.setCurrentWidget(self.drive)

    def change_language(self, lang: str) -> None:
        if self.sync.is_busy() or self.drive.uploading:
            self.lang.set_value(language())
            self.toast(tr("desktop.closeWhileSync"), "error")
            return
        self.settings.setValue("language", lang)
        self.replacing = True
        self.language_change_requested.emit(lang, self.current_folder_id or "")

    # --- folders ----------------------------------------------------------------------------------

    def load_folders(self, select_id: str | None = None) -> None:
        select_id = select_id or self.current_folder_id

        def show(folders: list[dict]):
            self.folders = folders
            self._render_tree()
            ids = {f["id"] for f in folders}
            root = next((f["id"] for f in folders if not f.get("parent_folder_id")), None)
            # reloading the tree never switches pages (e.g. after a sync the result stays visible)
            self.select_folder(select_id if select_id in ids else root)
            self.sync.set_folders(folders, self.current_folder_id)

        def failed(exc):
            if getattr(exc, "status_code", None) == 401:
                self.toast(tr("error.session_expired"), "error")
                self.logout()
                return
            self.toast(describe_error(exc), "error")

        run_task(self.api.get_folders, on_success=show, on_error=failed)

    def _render_tree(self) -> None:
        self.tree.clear()
        self.tree_items: dict[str, QTreeWidgetItem] = {}
        for f in self.folders:
            item = QTreeWidgetItem([folder_label(f)])
            item.setData(0, Qt.UserRole, f["id"])
            item.setToolTip(0, folder_label(f))
            root = not f.get("parent_folder_id")
            item.setIcon(0, theme.icon("hardDrive" if root else "folder", theme.TEXT_2, 16))
            self.tree_items[f["id"]] = item
        for f in sorted(self.folders, key=lambda x: x["name"].lower()):
            parent = self.tree_items.get(f.get("parent_folder_id") or "")
            if parent is None:
                self.tree.addTopLevelItem(self.tree_items[f["id"]])
            else:
                parent.addChild(self.tree_items[f["id"]])
        for item in self.tree_items.values():
            if item.parent() is None:
                item.setExpanded(True)

    def open_folder(self, folder_id: str | None) -> None:
        """User navigation: select the folder and show the drive page."""
        if not folder_id:
            return
        self.select_folder(folder_id)
        self.show_page("drive")

    def select_folder(self, folder_id: str | None) -> None:
        if not folder_id:
            return
        self.current_folder_id = folder_id
        item = getattr(self, "tree_items", {}).get(folder_id)
        if item is not None:
            parent = item.parent()
            while parent is not None:  # always reveal the active folder
                parent.setExpanded(True)
                parent = parent.parent()
            self.tree.setCurrentItem(item)
        self.drive.set_folder(self.folders, folder_id)

    def refresh(self) -> None:
        self.load_folders()

    REFRESH_ON_RETURN = 5.0  # seconds: coming back to the window reloads folders and files

    def changeEvent(self, event) -> None:
        """Back in this window (e.g. after deleting something in the browser): reload the view."""
        super().changeEvent(event)
        if event.type() != QEvent.ActivationChange or not self.isActiveWindow():
            return
        if self.sync.is_busy() or self.drive.uploading:
            return
        now = time.monotonic()
        if now - getattr(self, "_last_refresh", 0.0) >= self.REFRESH_ON_RETURN:
            self._last_refresh = now
            self.load_folders()

    # --- session -------------------------------------------------------------------------------------

    def logout(self) -> None:
        if self.sync.is_busy():
            self.toast(tr("desktop.closeWhileSync"), "error")
            return
        self.logging_out = True
        run_task(self.api.logout)
        self.logout_requested.emit()

    def closeEvent(self, event) -> None:
        if self.sync.is_busy() and not self.replacing:
            # leaving now would leave half-applied changes; the journal would allow a later restore
            self.toast(tr("desktop.closeWhileSync"), "error")
            event.ignore()
            return
        super().closeEvent(event)
        if not self.logging_out and not self.replacing:
            QApplication.quit()
