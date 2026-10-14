"""Synchronization page (same flow and wording as the web client):

local folder + remote folder + mode → scan → POST /sync → (confirm deletions) → execute
with progress and a cancel button. Cancel = stop + restore the previous state
(server reverses remote changes, the desktop reverses local ones from its journal).
"""

import socket
import threading
import time
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QBoxLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import theme
from app.folders import folder_paths
from app.i18n import describe_code, describe_error, format_datetime, format_size, tr
from app.sync.executor import UNCHANGED, SyncExecutor
from app.sync.journal import LocalJournal
from app.sync.scanner import LocalFolderScanner, ScanCancelled
from app.sync.session import cancel_and_rollback, pending_recoveries, request_cancel, rollback_synchronization
from app.widgets import Alert, button, card, confirm, icon_button, label, restyle
from app.worker import run_task

MODES = [("two_way", "sync"), ("mirror_local", "upload"), ("mirror_remote", "download")]
KIND_STYLE = {
    "UPLOAD_LOCAL": ("upload", theme.INFO),
    "DOWNLOAD_REMOTE": ("download", theme.SUCCESS),
    "DELETE_REMOTE": ("trash", theme.DANGER),
    "DELETE_LOCAL": ("trash", theme.DANGER),
    "UNCHANGED": ("equal", theme.TEXT_3),
}
STATUS_COLORS = {
    "PENDING": theme.TEXT_2, "RUNNING": theme.INFO, "CANCEL_REQUESTED": theme.WARNING,
    "ROLLING_BACK": theme.WARNING, "CANCELLED": theme.TEXT_2, "ROLLBACK_FAILED": theme.DANGER,
    "COMPLETED": theme.SUCCESS, "FAILED": theme.DANGER,
}
COUNT_KEYS = {"UPLOAD_LOCAL": "uploaded", "DOWNLOAD_REMOTE": "downloaded",
              "DELETE_LOCAL": "deleted_local", "DELETE_REMOTE": "deleted_remote"}
SUMMARY_KEYS = ["uploaded", "downloaded", "deleted_remote", "deleted_local", "unchanged", "failed"]
HEARTBEAT = 3.0


def summarize(counts: dict) -> str:
    parts = [tr(f"sync.summary.{k}", n=counts.get(k, 0)) for k in SUMMARY_KEYS if counts.get(k, 0)]
    return " · ".join(parts) if parts else tr("sync.summary.nothing")


def device_name() -> str:
    """This computer's network name, shown in the synchronization history."""
    try:
        return socket.gethostname()[:100]
    except OSError:
        return ""


def operation_label(operation: str) -> str:
    text = tr(f"sync.op.{operation}")
    return text if not text.startswith("sync.op.") else operation


def two_lines(title: str) -> str:
    """'ВЕРСІЯ НА ДИСКУ' becomes two lines: a header no wider than the dates below it."""
    spaces = [i for i, ch in enumerate(title) if ch == " "]
    if not spaces:
        return title
    middle = min(spaces, key=lambda i: abs(i - len(title) / 2))
    return title[:middle] + "\n" + title[middle + 1:]


class PlanTable(QTableWidget):
    """Plan table: action / versions / state sized to their contents; the path takes the rest
    (at least PATH_MIN, elided in the middle) so nothing is cut off; it scrolls only below that."""

    PATH_MIN = 140

    def fit_path(self) -> None:
        others = sum(self.columnWidth(column) for column in range(1, self.columnCount()))
        self.setColumnWidth(0, max(self.PATH_MIN, self.viewport().width() - others))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_path()


class SyncPage(QWidget):
    synced = Signal()

    def __init__(self, api, toast, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.api = api
        self.toast = toast
        self.settings = QSettings("MiniDrive", "Desktop")
        self.folders: list[dict] = []
        self.plan: dict | None = None
        self.journal: LocalJournal | None = None
        self.phase = "idle"
        self.stop_event = threading.Event()
        self.row_of_change: dict[int, int] = {}
        self.done_count = 0
        self._build()
        self.refresh_history()
        self.check_recoveries()

    # --- construction -----------------------------------------------------------------------

    def _build(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("page")
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(label(tr("sync.title"), "pageTitle"))
        intro = label(tr("desktop.syncIntro"), "muted", wrap=True)
        layout.addWidget(intro)

        self.recoveries = QVBoxLayout()
        layout.addLayout(self.recoveries)

        # side by side on wide pages; stacked when the plan would be too narrow (the web breakpoint)
        grid = self.grid = QBoxLayout(QBoxLayout.LeftToRight)
        grid.setSpacing(16)
        grid.addWidget(self._setup_card(), 2)
        grid.addWidget(self._result_card(), 3)
        layout.addLayout(grid)
        layout.addWidget(self._history_card())
        layout.addStretch(1)

    STACK_BELOW = 1016  # page width (without the sidebar) of the web's 1280 px breakpoint
    SETUP_MAX = 350

    def resizeEvent(self, event):
        super().resizeEvent(event)
        direction = QBoxLayout.TopToBottom if self.width() < self.STACK_BELOW else QBoxLayout.LeftToRight
        if self.grid.direction() != direction:
            self.grid.setDirection(direction)
            stacked = direction == QBoxLayout.TopToBottom
            self.setup_frame.setMaximumWidth(16777215 if stacked else self.SETUP_MAX)

    def _step(self, number: int, title: str) -> tuple[QHBoxLayout, QVBoxLayout]:
        row = QHBoxLayout()
        badge = QLabel(str(number))
        badge.setObjectName("stepNo")
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignCenter)
        body = QVBoxLayout()
        body.setSpacing(6)
        body.addWidget(label(title, "cardTitle"))
        row.addWidget(badge, 0, Qt.AlignTop)
        row.addLayout(body, 1)
        return row, body

    def _setup_card(self) -> QWidget:
        frame = self.setup_frame = card()
        frame.setMaximumWidth(self.SETUP_MAX)  # like the web (minmax(280px, 360px)): the plan gets the rest
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)

        row, body = self._step(1, tr("sync.step.local"))
        picker = QHBoxLayout()
        self.local_edit = QLineEdit(self.settings.value("sync_local_folder", ""))
        self.local_edit.setFixedHeight(theme.BUTTON_HEIGHT)
        self.local_edit.setPlaceholderText(tr("sync.noFolder"))
        self.browse_button = button(tr("desktop.browse"), "secondary")
        self.browse_button.clicked.connect(self.choose_local_folder)
        picker.addWidget(self.local_edit, 1)
        picker.addWidget(self.browse_button)
        body.addLayout(picker)
        body.addWidget(label(tr("sync.privacy"), "hint", wrap=True))
        layout.addLayout(row)

        row, body = self._step(2, tr("sync.step.remote"))
        self.remote_box = QComboBox()
        self.remote_box.setFixedHeight(theme.BUTTON_HEIGHT)
        body.addWidget(self.remote_box)
        layout.addLayout(row)

        row, body = self._step(3, tr("sync.step.mode"))
        self.mode_group = QButtonGroup(self)
        self.mode_cards: dict[str, QFrame] = {}
        for index, (mode, icon_name) in enumerate(MODES):
            mode_card = QFrame()
            mode_card.setObjectName("modeCard")
            card_layout = QGridLayout(mode_card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            radio = QRadioButton()
            radio.setProperty("mode", mode)
            radio.setChecked(index == 0)
            self.mode_group.addButton(radio)
            mark = QLabel()
            mark.setPixmap(theme.icon_pixmap(icon_name, theme.PRIMARY, 18))
            title = label(tr(f"sync.mode.{mode}.title"))
            title.setStyleSheet("font-weight: 700; background: transparent;")
            text = label(tr(f"sync.mode.{mode}.text"), "hint", wrap=True)
            card_layout.addWidget(radio, 0, 0, Qt.AlignTop)
            card_layout.addWidget(mark, 0, 1, Qt.AlignTop)
            card_layout.addWidget(title, 0, 2)
            card_layout.addWidget(text, 1, 2)
            card_layout.setColumnStretch(2, 1)
            mode_card.mousePressEvent = lambda _e, r=radio: r.setChecked(True)
            self.mode_cards[mode] = mode_card
            body.addWidget(mode_card)
        self.mode_group.buttonToggled.connect(lambda *_: self._style_modes())
        self._style_modes()
        layout.addLayout(row)

        self.start_button = button(tr("sync.start"), "primary", "sync", height=44)
        self.start_button.clicked.connect(self.start)
        layout.addWidget(self.start_button)
        rule = label(tr("sync.conflictRule"), "hint", wrap=True)
        rule.setAlignment(Qt.AlignCenter)
        layout.addWidget(rule)
        return frame

    def _style_modes(self) -> None:
        current = self.mode()
        for mode, mode_card in self.mode_cards.items():
            mode_card.setProperty("active", "true" if mode == current else "false")
            restyle(mode_card)

    def _result_card(self) -> QWidget:
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(label(tr("sync.result.title"), "cardTitle"))

        self.run_panel = QFrame()
        self.run_panel.setObjectName("runPanel")
        run = QVBoxLayout(self.run_panel)
        run.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        self.run_title = label("")
        self.run_title.setStyleSheet("font-weight: 700; background: transparent;")
        self.run_percent = label("", "muted")
        head.addWidget(self.run_title, 1)
        head.addWidget(self.run_percent)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.run_current = label("", "muted", wrap=True)
        self.cancel_button = button(tr("sync.cancel"), "dangerOutline", "x")
        self.cancel_button.clicked.connect(self.cancel)
        run.addLayout(head)
        run.addWidget(self.progress)
        run.addWidget(self.run_current)
        run.addWidget(self.cancel_button, 0, Qt.AlignLeft)
        self.run_panel.hide()
        layout.addWidget(self.run_panel)

        self.alert = Alert("info")
        self.alert.hide()
        layout.addWidget(self.alert)

        self.plan_table = PlanTable(0, 5)
        self.plan_table.setObjectName("planTable")
        self.plan_table.setHorizontalHeaderLabels([two_lines(tr(k).upper()) for k in (
            "sync.col.path", "sync.col.action", "sync.col.local", "sync.col.remote", "sync.col.status")])
        self.plan_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.plan_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.verticalHeader().setDefaultSectionSize(46)
        self.plan_table.setShowGrid(False)
        header = self.plan_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # the path gives way first (elided in the middle, full path in the tooltip), so the action,
        # versions and state always fit in the panel, like the web
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        self.plan_table.setTextElideMode(Qt.ElideMiddle)
        self.plan_table.setMinimumHeight(260)
        self.plan_table.hide()  # shown once there is a plan
        layout.addWidget(self.plan_table, 1)

        # empty state like the web: icon, title, hint
        self.empty_box = QWidget()
        empty = QVBoxLayout(self.empty_box)
        empty.addStretch(1)
        mark = QLabel()
        mark.setPixmap(theme.icon_pixmap("sync", theme.PRIMARY, 30))
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(68, 68)
        mark.setStyleSheet(f"background: {theme.PRIMARY_SOFT}; border-radius: 20px;")
        empty.addWidget(mark, 0, Qt.AlignCenter)
        self.empty_title = label(tr("sync.empty.title"))
        self.empty_title.setStyleSheet("font-weight: 700; font-size: 11pt;")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty.addWidget(self.empty_title)
        self.empty_plan = label(tr("sync.empty.text"), "muted", wrap=True)
        self.empty_plan.setAlignment(Qt.AlignCenter)
        empty.addWidget(self.empty_plan)
        empty.addStretch(1)
        self.empty_box.setMinimumHeight(260)
        layout.addWidget(self.empty_box, 1)
        return frame

    def _history_card(self) -> QWidget:
        frame = card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 16)
        head = QHBoxLayout()
        title_icon = QLabel()
        title_icon.setPixmap(theme.icon_pixmap("history", theme.TEXT, 18))
        head.addWidget(title_icon)
        head.addWidget(label(tr("history.title"), "cardTitle"), 1)
        refresh = icon_button("refresh", tr("history.refresh"))
        refresh.clicked.connect(self.refresh_history)
        head.addWidget(refresh)
        layout.addLayout(head)
        self.history_alert = Alert("error")
        self.history_alert.hide()
        layout.addWidget(self.history_alert)
        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels([tr(k).upper() for k in (
            "history.col.started", "history.col.client", "history.col.device", "history.col.folder", "history.col.mode",
            "history.col.status", "history.col.summary")])
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setShowGrid(False)
        self.history_table.verticalHeader().setDefaultSectionSize(40)
        header = self.history_table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for column in range(6):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        self.history_table.setMinimumHeight(220)
        layout.addWidget(self.history_table)
        self.history_empty = label(tr("history.empty"), "muted")
        layout.addWidget(self.history_empty)
        return frame

    # --- data -------------------------------------------------------------------------------

    def set_folders(self, folders: list[dict], current_folder_id: str | None) -> None:
        self.folders = folders
        selected = self.remote_box.currentData() or current_folder_id
        self.remote_box.blockSignals(True)
        self.remote_box.clear()
        for folder_id, path in sorted(folder_paths(folders).items(), key=lambda item: item[1].lower()):
            self.remote_box.addItem(theme.icon("cloud", theme.TEXT_3, 15), path, folder_id)
        index = self.remote_box.findData(selected)
        self.remote_box.setCurrentIndex(max(index, 0))
        self.remote_box.blockSignals(False)

    def mode(self) -> str:
        checked = self.mode_group.checkedButton()
        return checked.property("mode") if checked else "two_way"

    def is_busy(self) -> bool:
        return self.phase in ("scanning", "running", "cancelling", "restoring")

    def _set_inputs_enabled(self, enabled: bool) -> None:
        for widget in (self.local_edit, self.browse_button, self.remote_box, self.start_button):
            widget.setEnabled(enabled)
        for radio in self.mode_group.buttons():
            radio.setEnabled(enabled)

    def choose_local_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("desktop.chooseLocal"), self.local_edit.text())
        if directory:
            self.local_edit.setText(directory)

    # --- history ---------------------------------------------------------------------------------

    def refresh_history(self) -> None:
        def show(rows: list[dict]):
            self.history_alert.hide()
            paths = folder_paths(self.folders)
            self.history_table.setRowCount(len(rows))
            for row, h in enumerate(rows):
                status = h["status"]
                summary = summarize(h)
                if status == "CANCELLED":
                    done = any(h.get(k) for k in SUMMARY_KEYS if k != "unchanged")
                    restored = tr("history.rolledBack")
                    summary = f"{summary} · {restored}" if done else restored[:1].upper() + restored[1:]
                elif status == "ROLLBACK_FAILED":
                    report = h.get("rollback_report") or {}
                    count = len(report.get("remote_failures", [])) + len(report.get("local_failures", []))
                    summary += f" · {tr('history.notRestored', count=count)}"
                client = h.get("client", "")
                values = [
                    format_datetime(h.get("started_at")),
                    tr(f"history.client.{client}") if client in ("desktop", "web", "api") else client,
                    h.get("device") or tr("history.deviceUnknown"),
                    paths.get(h.get("remote_folder_id") or "", tr("history.deletedFolder")),
                    tr(f"sync.mode.{h['mode']}.title"),
                    tr(f"history.status.{status}"),
                    summary,
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 5:
                        item.setForeground(QColor(STATUS_COLORS.get(status, theme.TEXT_2)))
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        item.setData(Qt.UserRole, status)
                    elif column in (0, 6):
                        item.setForeground(QColor(theme.TEXT_2))
                    self.history_table.setItem(row, column, item)
            self.history_empty.setVisible(not rows)
            self.history_table.setVisible(bool(rows))

        def failed(exc):
            # the details are in the server log; the UI names the cause only when the administrator
            # must fix it (database migration missing), otherwise a friendly message
            schema = getattr(exc, "code", None) == "schema_outdated"
            self.history_alert.show_message("error", tr("error.schema_outdated" if schema else "history.error"))

        run_task(self.api.get_synchronizations, 15, on_success=show, on_error=failed)

    # --- recovery of interrupted synchronizations ----------------------------------------------------

    def check_recoveries(self) -> None:
        run_task(pending_recoveries, self.api, on_success=self._show_recoveries, on_error=lambda _: None)

    def _show_recoveries(self, found: list) -> None:
        while self.recoveries.count():
            item = self.recoveries.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for journal, status in found:
            failed = status == "ROLLBACK_FAILED"
            banner = Alert("error" if failed else "warning")
            banner.setProperty("status", status)
            folder = Path(journal.data.local_root).name
            banner.show_message(
                "error" if failed else "warning",
                tr("sync.recovery.failedTitle" if failed else "sync.recovery.title"),
                tr("sync.recovery.failedText" if failed else "sync.recovery.text", folder=folder),
            )
            restore = button(tr("sync.rollbackRetry" if failed else "sync.recovery.action"), "primary")
            restore.clicked.connect(lambda _=False, j=journal: self.resume(j, True))
            banner.actions.addWidget(restore)
            if failed:
                dismiss = button(tr("sync.recovery.dismiss"), "ghost")
                dismiss.clicked.connect(lambda _=False, j=journal, b=banner: (j.discard(), b.deleteLater()))
                banner.actions.addWidget(dismiss)
            else:
                remote_only = button(tr("sync.recovery.remoteOnly"), "ghost")
                remote_only.clicked.connect(lambda _=False, j=journal: self.resume(j, False))
                banner.actions.addWidget(remote_only)
            banner.actions.addStretch(1)
            self.recoveries.addWidget(banner)

    def resume(self, journal: LocalJournal, with_local: bool) -> None:
        if self.is_busy():
            return
        self.plan, self.journal = None, journal
        self.plan_table.setRowCount(0)
        self._enter_rollback_phase("cancelling")

        def work(report):
            return cancel_and_rollback(self.api, journal.data.synchronization_id, journal,
                                       on_restoring=lambda: report("restoring"), restore_local=with_local)

        run_task(work, on_progress=self._enter_rollback_phase, on_success=self._rollback_done,
                 on_error=self._rollback_error)

    # --- step 1: scan + plan ----------------------------------------------------------------------------

    def start(self) -> None:
        root = Path(self.local_edit.text().strip())
        if not self.local_edit.text().strip() or not root.is_dir():
            self.alert.show_message("error", tr("desktop.notAFolder"))
            return
        remote_folder_id = self.remote_box.currentData()
        mode = self.mode()
        self.settings.setValue("sync_local_folder", str(root))
        self.alert.hide()
        self.alert.clear_actions()
        self.plan_table.setRowCount(0)
        self.phase = "scanning"
        self.stop_event.clear()
        stop = self.stop_event
        self._set_inputs_enabled(False)
        self._show_preparing(tr("sync.scanning", count=0))
        device = device_name()

        def build_plan(report):
            manifest = LocalFolderScanner().scan(root, should_stop=stop.is_set)
            if stop.is_set():  # cancelled right as the scan finished: no session is created at all
                raise ScanCancelled()
            report(("planning", len(manifest)))
            plan = self.api.post_sync(remote_folder_id, manifest, mode, device)
            if stop.is_set():
                # cancelled while the plan was being prepared: close the (empty) session properly
                return "cancelled", cancel_and_rollback(self.api, plan["synchronization_id"], None)
            journal = None
            if plan.get("synchronization_id") and any(c["kind"] != UNCHANGED for c in plan["changes"]):
                journal = LocalJournal.create(plan["synchronization_id"], plan["remote_folder_id"], root)
            return "plan", (plan, journal)

        def ready(result):
            kind, value = result
            if kind == "cancelled":
                self._rollback_done(value)
            else:
                self.plan_ready(*value, root)

        run_task(build_plan,
                 on_progress=lambda event: self._show_preparing(tr("sync.planning")),
                 on_success=ready,
                 on_error=self._plan_failed)

    def _show_preparing(self, title: str) -> None:
        """Scanning / planning: a large folder can take a while, so it can be cancelled too."""
        self.run_panel.show()
        self.run_title.setText(title)
        self.run_percent.setText("")
        self.run_current.setText("")
        self.progress.setRange(0, 0)
        self.cancel_button.show()
        self.cancel_button.setEnabled(True)

    def _plan_failed(self, exc) -> None:
        self.phase = "idle"
        self.run_panel.hide()
        self._set_inputs_enabled(True)
        self.start_button.setText(tr("sync.start"))
        if isinstance(exc, ScanCancelled):
            self.alert.show_message("success", tr("sync.cancelledBeforeStart"))
            return
        self.alert.show_message("error", tr("sync.failed", error=describe_error(exc)))

    def plan_ready(self, plan: dict, journal: LocalJournal | None, root: Path) -> None:
        # Scanning is over: declining the deletion confirmation must cancel this session
        # (the "nothing executed yet" branch of cancel), not wait for a scan that already
        # finished — that left the UI stuck in "cancelling" and the folder locked.
        self.phase = "planned"
        self.run_panel.hide()
        self.plan, self.journal = plan, journal
        self.show_plan(plan)
        deletions = [c for c in plan["changes"] if c["kind"] in ("DELETE_LOCAL", "DELETE_REMOTE")]
        if deletions:
            local = sum(1 for c in deletions if c["kind"] == "DELETE_LOCAL")
            remote = len(deletions) - local
            text = tr("sync.confirm.text", count=len(deletions))
            if local:
                text += " " + tr("sync.confirm.local", count=local)
            if remote:
                text += " " + tr("sync.confirm.remote", count=remote)
            text += " " + tr("sync.confirm.continue")
            if not confirm(self, tr("sync.confirm.title"), text, tr("sync.confirm.action"), tr("dialog.cancel")):
                self.cancel()  # nothing executed yet: cancel + (empty) rollback
                return
        self.execute(plan, journal, root)

    def show_plan(self, plan: dict) -> None:
        visible = [(i, c) for i, c in enumerate(plan["changes"]) if c["kind"] != UNCHANGED]
        self.row_of_change = {index: row for row, (index, _) in enumerate(visible)}
        self.plan_table.setRowCount(len(visible))
        for row, (_, change) in enumerate(visible):
            icon_name, color = KIND_STYLE[change["kind"]]
            path = QTableWidgetItem(change["relative_path"])
            path.setToolTip(change["relative_path"])
            action = QTableWidgetItem(theme.icon(icon_name, color, 14), tr(f"sync.kind.{change['kind']}"))
            action.setForeground(QColor(color))
            local = (f"{format_datetime(change.get('local_modified_at'), short=True)}\n{format_size(change.get('local_size'))}"
                     if change.get("local_modified_at") else "-")
            remote = (f"{format_datetime(change.get('remote_modified_at'), short=True)}\n{format_size(change.get('remote_size'))}"
                      if change.get("remote_modified_at") else "-")
            items = [path, action, QTableWidgetItem(local), QTableWidgetItem(remote), QTableWidgetItem(tr("sync.state.pending"))]
            for column, item in enumerate(items):
                if column in (2, 3, 4):
                    item.setForeground(QColor(theme.TEXT_2))
                self.plan_table.setItem(row, column, item)
        self.plan_table.setVisible(bool(visible))
        self.plan_table.resizeColumnsToContents()
        self.plan_table.fit_path()
        self.empty_box.setVisible(not visible)
        if not visible:
            self.empty_title.setText(tr("sync.upToDate"))
            self.empty_plan.setText("")

    # --- step 2: execute with cancel ----------------------------------------------------------------------

    def execute(self, plan: dict, journal: LocalJournal | None, root: Path) -> None:
        sync_id = plan.get("synchronization_id")
        actionable = [c for c in plan["changes"] if c["kind"] != UNCHANGED]
        self.phase = "running"
        self.done_count = 0
        self.stop_event.clear()
        self.run_panel.show()
        self.cancel_button.setVisible(bool(sync_id))
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, max(len(actionable), 1))
        self.progress.setValue(0)
        self._update_run_title(len(actionable))
        if not sync_id:
            self.run_current.setText(tr("sync.cancelUnavailable"))

        stop = self.stop_event
        executor = SyncExecutor(self.api, root, plan["remote_folder_id"], sync_id, journal, should_stop=stop.is_set)

        def work(report):
            counts = {k: 0 for k in SUMMARY_KEYS}
            last_beat = [time.monotonic()]

            def beat():
                if sync_id and time.monotonic() - last_beat[0] > HEARTBEAT:
                    last_beat[0] = time.monotonic()
                    try:
                        self.api.report_synchronization(sync_id, "RUNNING", counts)
                    except Exception as exc:
                        if getattr(exc, "code", None) == "sync_cancelled":
                            stop.set()  # cancelled from another client: stop and roll back

            def on_start(index, change):
                report(("start", index, change))

            def on_progress(index, change, error):
                key = COUNT_KEYS.get(change["kind"])
                if error is None and key:
                    counts[key] += 1
                elif error is not None:
                    counts["failed"] += 1
                report(("done", index, executor.last_exception if error is not None else None))
                beat()

            if sync_id and actionable:
                try:
                    self.api.report_synchronization(sync_id, "RUNNING")
                except Exception as exc:
                    if getattr(exc, "code", None) == "sync_cancelled":
                        stop.set()
            result = executor.execute(plan, on_progress=on_progress, on_start=on_start)

            if (result.stopped or stop.is_set()) and sync_id:
                report(("cancelling",))
                return "rollback", cancel_and_rollback(self.api, sync_id, journal,
                                                       on_restoring=lambda: report(("restoring",)),
                                                       counts=result.history_counts())
            if sync_id and actionable:
                errors = "\n".join(f"{p}: {m}" for p, m in result.errors)[:2000] or None
                try:
                    self.api.report_synchronization(sync_id, "FAILED" if result.errors else "COMPLETED",
                                                    result.history_counts(), errors)
                except Exception as exc:
                    if getattr(exc, "code", None) == "sync_cancelled":
                        report(("cancelling",))
                        return "rollback", cancel_and_rollback(self.api, sync_id, journal,
                                                               on_restoring=lambda: report(("restoring",)),
                                                               counts=result.history_counts())
                    result.history_error = describe_error(exc)
            if journal is not None:
                journal.discard()
            return "done", result

        run_task(work, on_progress=self._progress, on_success=self._finished, on_error=self._rollback_error)

    def _update_run_title(self, total: int) -> None:
        percent = int(self.done_count * 100 / total) if total else 0
        self.run_title.setText(tr("sync.running", done=self.done_count, total=total))
        self.run_percent.setText(tr("sync.progress", percent=percent, done=self.done_count, total=total))

    def _set_row_state(self, index: int, text: str, color: str) -> None:
        row = self.row_of_change.get(index)
        if row is None:
            return
        item = QTableWidgetItem(text)
        item.setForeground(QColor(color))
        item.setToolTip(text)
        self.plan_table.setItem(row, 4, item)
        self.plan_table.fit_path()

    def _progress(self, event: tuple) -> None:
        kind = event[0]
        total = self.progress.maximum()
        if kind == "start":
            _, index, change = event
            self._set_row_state(index, tr("sync.state.running"), theme.INFO)
            self.run_current.setText(tr(f"sync.current.{change['kind']}", name=change["relative_path"]))
        elif kind == "done":
            _, index, exc = event
            self.done_count += 1
            self.progress.setValue(self.done_count)
            self._update_run_title(total)
            if exc is None:
                self._set_row_state(index, "✓ " + tr("sync.state.done"), theme.SUCCESS)
            else:
                self._set_row_state(index, "⚠ " + describe_error(exc), theme.DANGER)
        elif kind in ("cancelling", "restoring"):
            self._enter_rollback_phase(kind)

    def _enter_rollback_phase(self, kind: str) -> None:
        self.phase = kind
        self._set_inputs_enabled(False)
        self.run_panel.show()
        self.cancel_button.hide()
        self.run_title.setText(tr("sync.cancelling") if kind == "cancelling" else tr("sync.restoring"))
        self.run_percent.setText("")
        self.run_current.setText("")
        self.progress.setRange(0, 0)  # busy indicator

    def cancel(self) -> None:
        """Stop + restore. During execution the worker stops after the current change and rolls back."""
        if self.phase == "scanning":
            # the scanning worker stops; a plan that is already being created is cancelled there
            self.stop_event.set()
            self._enter_rollback_phase("cancelling")
            return
        sync_id = (self.plan or {}).get("synchronization_id")
        if not sync_id:
            return
        if self.phase == "running":
            self.stop_event.set()
            self._enter_rollback_phase("cancelling")
            # the server stops accepting changes at once (the worker does the rollback)
            run_task(request_cancel, self.api, sync_id, on_error=lambda _: None)
            return
        # nothing executed yet (deletion confirmation declined)
        journal = self.journal
        self._enter_rollback_phase("cancelling")

        def work(report):
            return cancel_and_rollback(self.api, sync_id, journal, on_restoring=lambda: report("restoring"))

        run_task(work, on_progress=self._enter_rollback_phase, on_success=self._rollback_done,
                 on_error=self._rollback_error)

    # --- results -------------------------------------------------------------------------------------------

    def _finished(self, outcome: tuple) -> None:
        kind, value = outcome
        if kind == "rollback":
            self._rollback_done(value)
            return
        self.phase = "done"
        self.run_panel.hide()
        self._set_inputs_enabled(True)
        self.start_button.setText(tr("sync.start"))
        failed = bool(value.errors)
        self.alert.show_message("error" if failed else "success",
                                tr("sync.result.errors" if failed else "sync.result.ok"),
                                summarize(value.history_counts()) +
                                (("\n" + tr("sync.historySaveFailed", error=value.history_error)) if value.history_error else ""))
        self.plan, self.journal = None, None
        self.refresh_history()
        self.synced.emit()

    def _rollback_done(self, outcome) -> None:
        self.phase = "cancelled" if outcome.status == "CANCELLED" else "rollback_failed"
        self.run_panel.hide()
        self._set_inputs_enabled(True)
        self.start_button.setText(tr("sync.start"))
        self.alert.clear_actions()
        if outcome.status == "CANCELLED":
            self.alert.show_message("success", tr("sync.cancelledRestored"))
            self.plan, self.journal = None, None
        else:
            lines = [
                f"• {f.get('relative_path') or '-'} · {tr('sync.side.' + f['side'])} · {operation_label(f['operation'])}: "
                f"{describe_code(f['code'])}"
                for f in outcome.failures
            ]
            self.alert.show_message("error", tr("sync.rollbackFailed"),
                                    (tr("sync.rollbackFailed.list") + "\n" + "\n".join(lines)) if lines else "")
            retry = button(tr("sync.rollbackRetry"), "secondary")
            retry.clicked.connect(self.retry_rollback)
            self.alert.actions.addWidget(retry)
            self.alert.actions.addStretch(1)
        self.refresh_history()
        self.check_recoveries()
        self.synced.emit()

    def _rollback_error(self, exc) -> None:
        self.phase = "rollback_failed"
        self.run_panel.hide()
        self._set_inputs_enabled(True)
        self.start_button.setText(tr("sync.start"))
        self.alert.clear_actions()
        self.alert.show_message("error", tr("sync.rollbackFailed"), describe_error(exc))
        if (self.plan or {}).get("synchronization_id"):
            retry = button(tr("sync.rollbackRetry"), "secondary")
            retry.clicked.connect(self.retry_rollback)
            self.alert.actions.addWidget(retry)
            self.alert.actions.addStretch(1)
        self.refresh_history()

    def retry_rollback(self) -> None:
        sync_id = (self.plan or {}).get("synchronization_id") or (
            self.journal.data.synchronization_id if self.journal else None)
        if not sync_id:
            return
        journal = self.journal
        self._enter_rollback_phase("restoring")

        def work(report):
            return rollback_synchronization(self.api, sync_id, journal)

        run_task(work, on_success=self._rollback_done, on_error=self._rollback_error)
