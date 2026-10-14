"""My Drive: subfolders and files of the current folder in one table, like the web DrivePage."""

import json
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import theme
from app.column_settings import COLUMN_LABELS, ColumnVisibilitySettings
from app.folder_upload import collect_paths, upload_selection
from app.folders import breadcrumbs, folder_label
from app.i18n import describe_error, format_datetime, format_size, tr
from app.widgets import DropOverlay, Segmented, ask_text, button, card, confirm, icon_button, label
from app.worker import run_task

# (column key, label key); Name is always visible
COLUMNS = [
    ("name", "columns.name"),
    ("size", "columns.size"),
    ("created_at", "columns.created_at"),
    ("modified_at", "columns.modified_at"),
    ("uploaded_by", "columns.uploaded_by"),
    ("modified_by", "columns.modified_by"),
]
ACTIONS_COLUMN = len(COLUMNS)
SORT_FIELDS = ["created_at", "modified_at", "name"]


class ColumnsController(QObject):
    """Column visibility per user: server (GET/PATCH /settings/columns) is the source of truth,
    QSettings keeps the last known value for offline use. Lives as long as the main window,
    so navigating between folders never resets it."""

    changed = Signal()
    problem = Signal(str)  # "load" | "save"

    def __init__(self, api, settings: QSettings, parent=None):
        super().__init__(parent)
        self.api = api
        self.settings = settings
        self.local_only = False
        self.saving = False
        self.dirty = False
        self.columns = ColumnVisibilitySettings.from_dict(json.loads(self.settings.value("columns", "{}") or "{}"))
        run_task(self.api.get_column_settings, on_success=self._loaded, on_error=lambda _: self._failed("load"))

    def _loaded(self, data: dict) -> None:
        self.columns = ColumnVisibilitySettings.from_dict(data)
        self.local_only = False
        self._cache()
        self.changed.emit()

    def _failed(self, kind: str) -> None:
        self.local_only = True
        self.problem.emit(kind)
        self.changed.emit()

    def _cache(self) -> None:
        self.settings.setValue("columns", json.dumps(self.columns.to_dict()))

    def toggle(self, key: str) -> None:
        self.columns.toggle_column(key)
        self._cache()
        self.changed.emit()  # the table updates immediately
        self._save()

    def all_visible(self) -> bool:
        return all(self.columns.is_visible(key) for key in COLUMN_LABELS)

    def set_all(self, visible: bool) -> None:
        """"All" in the columns menu: show or hide every optional column (Name always stays)."""
        self.columns = ColumnVisibilitySettings.from_dict({key: visible for key in COLUMN_LABELS})
        self._cache()
        self.changed.emit()
        self._save()

    def _save(self) -> None:
        """One request at a time, always with the latest state: quick toggles can never
        reach the server out of order and leave an older state behind."""
        if self.saving:
            self.dirty = True
            return
        self.saving, self.dirty = True, False

        def finished(ok: bool):
            self.saving = False
            if ok:
                self.local_only = False
            else:
                self._failed("save")
            if self.dirty:
                self._save()

        run_task(self.api.update_column_settings, self.columns.to_dict(),
                 on_success=lambda _: finished(True), on_error=lambda _: finished(False))


class NameDelegate(QStyledItemDelegate):
    """Name cell like the web: icon tile, bold name, small extension badge."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        file = index.data(Qt.UserRole)
        if not file:
            return super().paint(painter, option, index)
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text, background.icon = "", background.icon.__class__()
        option.widget.style().drawControl(QStyle.CE_ItemViewItem, background, painter, option.widget)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(12, 0, -10, 0)
        is_folder = bool(file.get("is_folder"))
        icon_name, tone = ("folder", theme.PRIMARY) if is_folder else theme.file_icon(file.get("extension") or "")
        tile = theme.tile_icon(icon_name, tone)
        tile.paint(painter, rect.left(), rect.center().y() - 16, 32, 32)
        x = rect.left() + 32 + 14

        # a filtered result that includes subfolders: the file's folder under its name
        location = file.get("location") or ""
        if location:
            small = QFont(option.font)
            small.setPointSizeF(max(6.5, option.font.pointSizeF() * 0.82))
            painter.setFont(small)
            painter.setPen(QColor(theme.TEXT_3))
            small_metrics = QFontMetrics(small)
            text = small_metrics.elidedText("📁 " + location, Qt.ElideMiddle, max(20, rect.right() - x))
            painter.drawText(x, rect.center().y() + 1, rect.right() - x, rect.height() // 2 - 2,
                             Qt.AlignTop | Qt.AlignLeft, text)
            rect = QRectF(rect.left(), rect.top(), rect.width(), rect.height() / 2 + 3).toRect()

        badge = "" if is_folder else (file.get("extension") or "").lstrip(".").upper()
        badge_font = QFont(option.font)
        badge_font.setPointSizeF(max(6.5, option.font.pointSizeF() * 0.72))
        badge_font.setWeight(QFont.Weight.Bold)
        badge_width = QFontMetrics(badge_font).horizontalAdvance(badge) + 10 if badge else 0

        name_font = QFont(option.font)
        name_font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetrics(name_font)
        available = rect.right() - x - (badge_width + 8 if badge else 0)
        name = metrics.elidedText(file["name"], Qt.ElideMiddle, max(20, available))
        painter.setFont(name_font)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(x, rect.top(), metrics.horizontalAdvance(name) + 2, rect.height(),
                         Qt.AlignVCenter | Qt.AlignLeft, name)
        if badge:
            bx = x + metrics.horizontalAdvance(name) + 8
            box = QRectF(bx, rect.center().y() - 9, badge_width, 18)
            path = QPainterPath()
            path.addRoundedRect(box, 5, 5)
            painter.fillPath(path, QColor(theme.SURFACE_2))
            painter.setFont(badge_font)
            painter.setPen(QColor(theme.TEXT_3))
            painter.drawText(box, Qt.AlignCenter, badge)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(260, 52)


class FileTable(QTableWidget):
    """Subfolders (first rows) and files of the current folder, like the web table."""

    preview_requested = Signal(dict)
    download_requested = Signal(dict)
    delete_requested = Signal(dict)
    open_folder_requested = Signal(str)       # a folder row, or the location of a filtered file
    clear_folder_requested = Signal(dict)
    delete_folder_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS) + 1, parent)
        self.setObjectName("fileTable")
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setIconSize(theme.ICON_SIZE * 1.8)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(50)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setTextElideMode(Qt.ElideMiddle)
        header = self.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(90)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(COLUMNS) + 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.setItemDelegateForColumn(0, NameDelegate(self))
        self.retranslate()
        self.doubleClicked.connect(lambda index: self._activate(index.row()))

    NAME_MIN_WIDTH = 260

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_name_column()

    def _fit_name_column(self) -> None:
        """Stretch the name column, but never below NAME_MIN_WIDTH (then the table scrolls)."""
        header = self.horizontalHeader()
        others = sum(header.sectionSize(c) for c in range(1, self.columnCount()) if not self.isColumnHidden(c))
        if self.viewport().width() - others >= self.NAME_MIN_WIDTH:
            header.setSectionResizeMode(0, QHeaderView.Stretch)
        else:
            header.setSectionResizeMode(0, QHeaderView.Interactive)
            header.resizeSection(0, self.NAME_MIN_WIDTH)

    def retranslate(self) -> None:
        self.setHorizontalHeaderLabels([tr(key).upper() for _, key in COLUMNS] + [""])

    def _activate(self, row: int) -> None:
        item = self.item(row, 0)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if data.get("is_folder"):
            self.open_folder_requested.emit(data["id"])
        else:
            self.preview_requested.emit(data)

    def show_files(self, files: list[dict], folders: list[dict] | None = None,
                   location_of=None) -> None:
        """folders: subfolder rows shown first; location_of(file) → text under the file name
        (filtered results that include subfolders)."""
        folders = folders or []
        self.setRowCount(len(folders) + len(files))
        for row, folder in enumerate(folders):
            self._set_name(row, {**folder, "is_folder": True})
            for column, value in enumerate(["—", format_datetime(folder["created_at"]), "—", "—", "—"], start=1):
                self._set_cell(row, column, value)
            self.setCellWidget(row, ACTIONS_COLUMN, self._folder_actions(folder))
        for row, f in enumerate(files, start=len(folders)):
            location = location_of(f) if location_of else ""
            self._set_name(row, {**f, "location": location})
            values = [
                format_size(f["size"]),
                format_datetime(f["created_at"]),
                format_datetime(f["modified_at"]),
                f.get("uploaded_by_name") or f["uploaded_by"],
                f.get("modified_by_name") or f["modified_by"],
            ]
            for column, value in enumerate(values, start=1):
                self._set_cell(row, column, value)
            self.setCellWidget(row, ACTIONS_COLUMN, self._actions(f, bool(location)))
        self._fit_name_column()

    def _set_name(self, row: int, data: dict) -> None:
        name = QTableWidgetItem(data["name"])  # painted by NameDelegate (icon tile, name, badge)
        name.setData(Qt.UserRole, data)
        name.setToolTip(f"{data['name']}\n📁 {data['location']}" if data.get("location") else data["name"])
        font = name.font()
        font.setWeight(font.Weight.DemiBold)
        name.setFont(font)
        self.setItem(row, 0, name)

    def _set_cell(self, row: int, column: int, value: str) -> None:
        item = QTableWidgetItem(value)
        item.setForeground(Qt.GlobalColor.darkGray)
        if column == 1:
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(row, column, item)

    @staticmethod
    def _action_box(buttons: list[QWidget]) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(4, 0, 8, 0)
        layout.setSpacing(2)
        for widget in buttons:
            layout.addWidget(widget)
        return box

    def _actions(self, f: dict, with_location: bool = False) -> QWidget:
        buttons = []
        if with_location:
            show = icon_button("folder", tr("file.openLocation"), theme.TEXT_3)
            show.clicked.connect(lambda _=False: self.open_folder_requested.emit(f["folder_id"]))
            buttons.append(show)
        for icon_name, key, signal, danger in (
            ("eye", "file.preview", self.preview_requested, False),
            ("download", "file.download", self.download_requested, False),
            ("trash", "file.delete", self.delete_requested, True),
        ):
            # like the web: gray icons; delete turns red on hover
            action = icon_button(icon_name, tr(key, name=f["name"]), theme.TEXT_3, danger=danger)
            action.clicked.connect(lambda _=False, s=signal: s.emit(f))
            buttons.append(action)
        return self._action_box(buttons)

    def _folder_actions(self, folder: dict) -> QWidget:
        clear = icon_button("eraser", tr("folder.clear", name=folder["name"]), theme.TEXT_3)
        clear.clicked.connect(lambda _=False: self.clear_folder_requested.emit(folder))
        delete = icon_button("trash", tr("folder.delete", name=folder["name"]), theme.TEXT_3, danger=True)
        delete.clicked.connect(lambda _=False: self.delete_folder_requested.emit(folder))
        return self._action_box([clear, delete])

    def apply_visibility(self, visibility: ColumnVisibilitySettings) -> None:
        for column, (key, _) in enumerate(COLUMNS):
            self.setColumnHidden(column, not visibility.is_visible(key))
        self._fit_name_column()

    def selected_files(self) -> list[dict]:
        rows = sorted({index.row() for index in self.selectedIndexes()})
        items = [self.item(row, 0).data(Qt.UserRole) for row in rows if self.item(row, 0)]
        return [data for data in items if not data.get("is_folder")]

    def visible_headers(self) -> list[str]:
        return [self.horizontalHeaderItem(c).text() for c in range(len(COLUMNS)) if not self.isColumnHidden(c)]


class UploadPanel(QFrame):
    """Progress + result of a file/folder upload; failures are listed, never skipped silently."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 12, 12)
        head = QHBoxLayout()
        self.mark = QLabel()
        self.title = label("")
        self.title.setStyleSheet("font-weight: 700;")
        self.counter = label("", "muted")
        self.close_button = icon_button("x", tr("drive.uploadPanel.close"))
        self.close_button.clicked.connect(self.hide)
        head.addWidget(self.mark)
        head.addWidget(self.title, 1)
        head.addWidget(self.counter)
        head.addWidget(self.close_button)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.current = label("", "muted", wrap=True)
        self.summary = label("", wrap=True)
        self.failures = label("", wrap=True)
        self.failures.setTextFormat(Qt.RichText)
        self.failures.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addLayout(head)
        layout.addWidget(self.progress)
        layout.addWidget(self.current)
        layout.addWidget(self.summary)
        layout.addWidget(self.failures)
        self.hide()

    def start(self, title: str, total: int) -> None:
        self.title.setText(title)
        self.mark.setPixmap(theme.icon_pixmap("upload", theme.PRIMARY, 18))
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(0)
        self.counter.setText(tr("drive.uploadPanel.progress", done=0, total=total))
        self.current.show()
        self.summary.hide()
        self.failures.hide()
        self.close_button.hide()
        self.show()

    def step(self, done: int, total: int, current: str | None) -> None:
        self.progress.setValue(done)
        self.counter.setText(tr("drive.uploadPanel.progress", done=done, total=total))
        self.current.setText(tr("drive.uploadPanel.current", name=current) if current else "")

    def finish(self, outcome) -> None:
        failed = bool(outcome.failures)
        self.mark.setPixmap(theme.icon_pixmap("alert" if failed else "check", theme.DANGER if failed else theme.SUCCESS, 18))
        self.progress.setValue(self.progress.maximum())
        self.current.hide()
        self.summary.setText(tr("drive.uploadPanel.done", uploaded=outcome.uploaded, folders=outcome.folders_created))
        self.summary.show()
        if failed:
            rows = "".join(f"<li><b>{path}</b>: {describe_error(exc)}</li>" for path, exc in outcome.failures)
            self.failures.setText(f"<span style='color:{theme.DANGER};font-weight:700'>"
                                  f"{tr('drive.uploadPanel.failed', count=len(outcome.failures))}</span><ul>{rows}</ul>")
            self.failures.show()
        self.close_button.show()


class DrivePage(QWidget):
    open_folder = Signal(str)
    folders_changed = Signal(str)  # select this folder after reloading the tree

    def __init__(self, api, columns: ColumnsController, toast, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.api = api
        self.columns = columns
        self.toast = toast
        self.settings = QSettings("MiniDrive", "Desktop")
        self.folders: list[dict] = []
        self.folder_id: str | None = None
        self.files: list[dict] = []
        self.request = 0
        self.uploading = False
        self.setAcceptDrops(True)
        self._build()
        self.columns.changed.connect(self.apply_columns)
        self.apply_columns()

    # --- construction -------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)

        head = QHBoxLayout()
        self.crumbs = QHBoxLayout()
        self.crumbs.setSpacing(2)
        head.addLayout(self.crumbs, 1)
        self.clear_folder_button = button(tr("drive.clearFolder"), "dangerText", "eraser")
        self.clear_folder_button.clicked.connect(lambda: self.clear_folder(self.current_folder()))
        self.delete_folder_button = button(tr("drive.deleteFolder"), "dangerText", "trash")
        self.delete_folder_button.clicked.connect(lambda: self.delete_folder(self.current_folder()))
        new_folder = button(tr("drive.newFolder"), "secondary", "folderPlus")
        new_folder.clicked.connect(self.create_folder)
        add_folder = button(tr("drive.uploadFolder"), "secondary", "folder")
        add_folder.clicked.connect(self.choose_folder_to_upload)
        add_files = button(tr("drive.upload"), "primary", "upload")
        add_files.clicked.connect(self.choose_files_to_upload)
        self.upload_buttons = [add_folder, add_files]
        for widget in (self.clear_folder_button, self.delete_folder_button, new_folder, add_folder, add_files):
            head.addWidget(widget)
        layout.addLayout(head)

        self.upload_panel = UploadPanel()
        layout.addWidget(self.upload_panel)

        # files toolbar
        self.files_title = label(tr("drive.files").upper(), "sectionTitle")
        self.title_row = QHBoxLayout()
        self.title_row.addWidget(self.files_title)
        layout.addLayout(self.title_row)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.toolbar = toolbar
        self.filter = Segmented([("", tr("filter.all")), (".c", ".c"), (".jpg", ".jpg")],
                                self.settings.value("filter", ""))
        self.filter.setAccessibleName(tr("filter.label"))
        self.filter.changed.connect(self._filter_changed)
        toolbar.addWidget(self.filter)
        self.sort_box = QComboBox()
        for field in SORT_FIELDS:
            self.sort_box.addItem(theme.icon("filter", theme.TEXT_3, 15), tr(f"sort.{field}"), field)
        self.sort_box.setCurrentIndex(max(0, SORT_FIELDS.index(self.settings.value("sort", "created_at"))))
        self.sort_box.setToolTip(tr("sort.label"))
        self.sort_box.setFixedHeight(theme.CONTROL_HEIGHT)
        self.sort_box.currentIndexChanged.connect(self._sort_changed)
        toolbar.addWidget(self.sort_box)
        self.order = self.settings.value("order", "desc")
        self.order_button = QToolButton()
        self.order_button.setProperty("variant", "text")
        self.order_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.order_button.setFixedHeight(theme.CONTROL_HEIGHT)
        self.order_button.setToolTip(tr("sort.toggle"))
        self.order_button.clicked.connect(self._toggle_order)
        toolbar.addWidget(self.order_button)
        self.columns_button = QToolButton()
        self.columns_button.setProperty("variant", "text")
        self.columns_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.columns_button.setFixedHeight(theme.CONTROL_HEIGHT)
        self.columns_button.setIcon(theme.icon("columns", theme.TEXT_2, 15))
        self.columns_button.setText(tr("columns.button"))
        self.columns_button.setPopupMode(QToolButton.InstantPopup)
        self.columns_menu = QMenu(self.columns_button)
        self.columns_button.setMenu(self.columns_menu)
        self.columns_menu.aboutToShow.connect(self._fill_columns_menu)
        toolbar.addWidget(self.columns_button)
        refresh = icon_button("refresh", tr("drive.refresh"))
        # folders too: picks up changes made elsewhere (web client, another computer)
        refresh.clicked.connect(lambda: self.folders_changed.emit(self.folder_id or ""))
        toolbar.addWidget(refresh)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        self._update_order_button()

        # files table / empty state
        self.table = FileTable()
        self.table.preview_requested.connect(self.preview)
        self.table.download_requested.connect(self.download)
        self.table.delete_requested.connect(self.delete_file)
        self.table.open_folder_requested.connect(self.open_folder.emit)
        self.table.clear_folder_requested.connect(self.clear_folder)
        self.table.delete_folder_requested.connect(self.delete_folder)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch(1)
        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignCenter)
        self.empty_title = label("")
        self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_title.setStyleSheet("font-size: 11pt; font-weight: 700;")
        self.empty_text = label("", "muted")
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.show_all = button(tr("drive.showAll"), "ghost")
        self.show_all.clicked.connect(lambda: (self.filter.set_value(""), self._filter_changed("")))
        for widget in (self.empty_icon, self.empty_title, self.empty_text):
            empty_layout.addWidget(widget)
        empty_layout.addWidget(self.show_all, 0, Qt.AlignCenter)
        empty_layout.addStretch(1)
        empty_card = card()
        QVBoxLayout(empty_card).addWidget(self.empty)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(empty_card)
        layout.addWidget(self.stack, 1)

        self.hint = label(tr("drive.hint"), "hint", wrap=True)
        layout.addWidget(self.hint)
        self.overlay = DropOverlay(self)

    # --- state ------------------------------------------------------------------------------

    def set_folder(self, folders: list[dict], folder_id: str) -> None:
        self.folders = folders
        self.folder_id = folder_id
        self._render_header()
        self.load_files()

    def current_folder(self) -> dict | None:
        return next((f for f in self.folders if f["id"] == self.folder_id), None)

    def _render_header(self) -> None:
        while self.crumbs.count():
            item = self.crumbs.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        chain = breadcrumbs(self.folders, self.folder_id)
        for index, crumb in enumerate(chain):
            if index < len(chain) - 1:
                link = QPushButton(folder_label(crumb))
                link.setObjectName("crumbLink")
                link.setProperty("variant", "ghost")
                link.setCursor(Qt.PointingHandCursor)
                link.clicked.connect(lambda _=False, fid=crumb["id"]: self.open_folder.emit(fid))
                self.crumbs.addWidget(link)
                arrow = QLabel()
                arrow.setPixmap(theme.icon_pixmap("chevronRight", theme.TEXT_3, 14))
                self.crumbs.addWidget(arrow)
            else:
                self.crumbs.addWidget(label(folder_label(crumb), "pageTitle"))
        self.crumbs.addStretch(1)
        folder = self.current_folder()
        self.clear_folder_button.setVisible(folder is not None)
        self.delete_folder_button.setVisible(bool(folder and folder.get("parent_folder_id")))

    def subfolders(self) -> list[dict]:
        """Subfolder rows, in the chosen sort (folders have no modification time: creation time)."""
        children = [f for f in self.folders if f.get("parent_folder_id") == self.folder_id]
        if self.sort_box.currentData() == "name":
            def key(f):
                return f["name"].lower()
        else:
            def key(f):
                return f["created_at"], f["name"].lower()
        return sorted(children, key=key, reverse=self.order == "desc")

    def recursive(self) -> bool:
        """A type filter searches this folder and all its subfolders."""
        return bool(self.filter.value())

    def apply_columns(self) -> None:
        self.table.apply_visibility(self.columns.columns)

    def _fill_columns_menu(self) -> None:
        self.columns_menu.clear()
        self.columns_menu.addSection(tr("columns.title"))
        every = self.columns_menu.addAction(tr("columns.all"))
        every.setCheckable(True)
        every.setChecked(self.columns.all_visible())
        every.toggled.connect(self.columns.set_all)
        self.columns_menu.addSeparator()
        name = self.columns_menu.addAction(f"{tr('columns.name')}  ·  {tr('columns.always')}")
        name.setCheckable(True)
        name.setChecked(True)
        name.setEnabled(False)
        name.setToolTip(tr("columns.nameAlways"))
        for key in COLUMN_LABELS:
            action = self.columns_menu.addAction(tr(f"columns.{key}"))
            action.setCheckable(True)
            action.setChecked(self.columns.columns.is_visible(key))
            action.setData(key)
            action.toggled.connect(lambda _checked, k=key: self.columns.toggle(k))
        if self.columns.local_only:
            note = self.columns_menu.addAction(tr("columns.savedLocally"))
            note.setEnabled(False)

    # --- loading -------------------------------------------------------------------------------

    def _filter_changed(self, value: str) -> None:
        self.settings.setValue("filter", value)
        self.load_files()

    def _sort_changed(self, _index: int) -> None:
        self.settings.setValue("sort", self.sort_box.currentData())
        self._update_order_button()
        self.load_files()

    def _toggle_order(self) -> None:
        self.order = "asc" if self.order == "desc" else "desc"
        self.settings.setValue("order", self.order)
        self._update_order_button()
        self.load_files()

    def _update_order_button(self) -> None:
        ascending = self.order == "asc"
        if self.sort_box.currentData() == "name":
            text = tr("sort.az" if ascending else "sort.za")
        else:
            text = tr("sort.oldest" if ascending else "sort.newest")
        self.order_button.setText(text)
        self.order_button.setIcon(theme.icon("arrowUp" if ascending else "arrowDown", theme.TEXT_2, 15))

    def load_files(self) -> None:
        if not self.folder_id:
            return
        self.request += 1
        request, folder_id = self.request, self.folder_id

        recursive = self.recursive()
        folder = self.current_folder()
        here = folder_label(folder) if folder else ""

        def location_of(f: dict) -> str:
            return f"{here}/{f['folder_path']}" if f.get("folder_path") else here

        def show(files: list[dict]):
            if request != self.request:
                return  # a newer filter/sort/folder request is on its way
            self.files = files
            if recursive:
                self.table.show_files(files, location_of=location_of)
            else:
                self.table.show_files(files, folders=self.subfolders())
            self.hint.setText(tr("drive.hintRecursive" if recursive else "drive.hint"))
            self._update_empty_state()

        def failed(exc):
            if request == self.request:
                self.files = []
                self.table.show_files([])
                self._update_empty_state()
                self.toast(describe_error(exc), "error")

        run_task(self.api.get_files, folder_id, self.filter.value() or None,
                 self.sort_box.currentData(), self.order, recursive, on_success=show, on_error=failed)

    def _update_empty_state(self) -> None:
        if self.files or (not self.recursive() and self.subfolders()):
            self.stack.setCurrentIndex(0)
            return
        filtered = bool(self.filter.value())
        self.empty_icon.setPixmap(theme.icon_pixmap("filter" if filtered else "cloud", theme.PRIMARY, 34))
        if filtered:
            self.empty_title.setText(tr("drive.emptyFiltered.title", filter=self.filter.value()))
            self.empty_text.setText("")
        else:
            self.empty_title.setText(tr("drive.empty.title"))
            self.empty_text.setText(tr("drive.empty.text"))
        self.empty_text.setVisible(bool(self.empty_text.text()))
        self.show_all.setVisible(filtered)
        self.stack.setCurrentIndex(1)

    # --- upload (files, folders, drag-and-drop) -------------------------------------------------

    def choose_files_to_upload(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("desktop.chooseFiles"))
        if paths:
            self.upload_paths([Path(p) for p in paths])

    def choose_folder_to_upload(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("desktop.chooseFolder"))
        if directory:
            self.upload_paths([Path(directory)])

    def upload_paths(self, paths: list[Path]) -> None:
        if self.uploading or not self.folder_id:
            return
        selection = collect_paths(paths)
        if not selection.items and not selection.dirs and not selection.problems:
            return
        folder_id = self.folder_id
        existing = {f["name"] for f in self.files}
        title = (tr("drive.uploadPanel.folder", name=", ".join(selection.roots)) if selection.is_folder
                 else tr("drive.uploadPanel.files"))
        self.uploading = True
        for widget in self.upload_buttons:
            widget.setEnabled(False)
        self.upload_panel.start(title, len(selection.items))

        def work(report):
            return upload_selection(self.api, selection, folder_id, lambda d, t, c: report((d, t, c)))

        def done(outcome):
            self.uploading = False
            for widget in self.upload_buttons:
                widget.setEnabled(True)
            single = not selection.is_folder and len(selection.items) == 1 and not outcome.failures
            if single:
                name = selection.items[0].path.name
                self.upload_panel.hide()
                self.toast(tr("drive.toast.replaced" if name in existing else "drive.toast.uploaded", name=name), "success")
            else:
                self.upload_panel.finish(outcome)
            if selection.is_folder:
                self.folders_changed.emit(folder_id)
            else:
                self.load_files()

        def failed(exc):
            self.uploading = False
            for widget in self.upload_buttons:
                widget.setEnabled(True)
            self.upload_panel.hide()
            self.toast(describe_error(exc), "error")

        run_task(work, on_progress=lambda p: self.upload_panel.step(*p), on_success=done, on_error=failed)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.uploading:
            event.acceptProposedAction()
            folder = self.current_folder()
            self.overlay.show_over(tr("drive.drop", folder=folder_label(folder) if folder else ""))
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.overlay.hide()

    def dropEvent(self, event):
        self.overlay.hide()
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        event.acceptProposedAction()
        if paths:
            self.upload_paths(paths)

    WIDE = 1000

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # wide windows: "FILES" and the controls share one row, like the web; narrow: two rows
        wide = self.width() >= self.WIDE
        in_toolbar = self.toolbar.indexOf(self.files_title) >= 0
        if wide and not in_toolbar:
            self.title_row.removeWidget(self.files_title)
            self.toolbar.insertWidget(0, self.files_title)
            self.toolbar.insertStretch(1, 1)
        elif not wide and in_toolbar:
            self.toolbar.removeWidget(self.files_title)
            self.toolbar.takeAt(0)  # the stretch after the title
            self.title_row.addWidget(self.files_title)
        if self.overlay.isVisible():
            self.overlay.setGeometry(self.rect().adjusted(8, 8, -8, -8))

    # --- file / folder actions -------------------------------------------------------------------

    def preview(self, file: dict) -> None:
        from app.preview import PreviewDialog

        def show(preview: dict):
            PreviewDialog(file, preview, self, on_download=self.download).exec()

        run_task(self.api.get_preview, file["id"], on_success=show,
                 on_error=lambda exc: self.toast(tr("preview.failed", error=describe_error(exc)), "error"))

    def download(self, file: dict) -> None:
        target, _ = QFileDialog.getSaveFileName(self, tr("desktop.saveFile"), file["name"])
        if not target:
            return

        def save():
            Path(target).write_bytes(self.api.download_file(file["id"]))

        run_task(save, on_success=lambda _: self.toast(tr("desktop.downloaded", name=file["name"]), "success"),
                 on_error=lambda exc: self.toast(tr("drive.toast.downloadFailed", error=describe_error(exc)), "error"))

    def delete_file(self, file: dict) -> None:
        if not confirm(self, tr("dialog.deleteFile.title"), tr("dialog.deleteFile.text", name=file["name"]),
                       tr("dialog.deleteFile.confirm"), tr("dialog.cancel")):
            return

        def done(_):
            self.toast(tr("drive.toast.deleted", name=file["name"]), "success")
            self.load_files()

        run_task(self.api.delete_file, file["id"], on_success=done,
                 on_error=lambda exc: self.toast(
                     tr("drive.toast.deleteFailed", name=file["name"], error=describe_error(exc)), "error"))

    def delete_selected(self) -> None:
        files = self.table.selected_files()
        if len(files) == 1:
            self.delete_file(files[0])

    def create_folder(self) -> None:
        folder = self.current_folder()
        name = ask_text(self, tr("dialog.newFolder.title"), tr("dialog.newFolder.name"),
                        tr("dialog.newFolder.inside", parent=folder_label(folder) if folder else ""),
                        tr("dialog.newFolder.create"), tr("dialog.cancel"))
        if not name:
            return

        def done(created: dict):
            self.toast(tr("drive.toast.folderCreated", name=created["name"]), "success")
            self.folders_changed.emit(self.folder_id)

        run_task(self.api.create_folder, name, self.folder_id, on_success=done,
                 on_error=lambda exc: self.toast(describe_error(exc), "error"))

    def clear_folder(self, folder: dict | None) -> None:
        """Delete everything inside the folder; the folder itself stays (empty)."""
        if not folder:
            return
        name = folder_label(folder)
        if not confirm(self, tr("dialog.clearFolder.title"), tr("dialog.clearFolder.text", name=name),
                       tr("dialog.clearFolder.confirm"), tr("dialog.cancel")):
            return

        def done(result: dict):
            self.toast(tr("drive.toast.folderCleared", name=name, files=result["deleted_files"],
                          folders=result["deleted_folders"]), "success")
            self.folders_changed.emit(self.folder_id or "")

        run_task(self.api.clear_folder, folder["id"], on_success=done,
                 on_error=lambda exc: self.toast(tr("drive.toast.folderClearFailed", error=describe_error(exc)), "error"))

    def delete_folder(self, folder: dict | None) -> None:
        if not folder or not folder.get("parent_folder_id"):
            return
        if not confirm(self, tr("dialog.deleteFolder.title"), tr("dialog.deleteFolder.text", name=folder["name"]),
                       tr("dialog.deleteFolder.confirm"), tr("dialog.cancel")):
            return
        # deleting the open folder goes up to its parent; deleting a subfolder row stays here
        stay = folder["id"] != self.folder_id

        def done(_):
            self.toast(tr("drive.toast.folderDeleted", name=folder["name"]), "success")
            self.folders_changed.emit(self.folder_id if stay else folder["parent_folder_id"])

        run_task(self.api.delete_folder, folder["id"], on_success=done,
                 on_error=lambda exc: self.toast(tr("drive.toast.folderDeleteFailed", error=describe_error(exc)), "error"))
