"""Small reusable widgets that mirror the web client's components (buttons, segmented
controls, alerts, cards, toasts, flow layout for folder cards)."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import theme


def restyle(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def button(text: str, variant: str | None = None, icon: str | None = None, icon_color: str | None = None,
           height: int = theme.BUTTON_HEIGHT) -> QPushButton:
    widget = QPushButton(text)
    widget.setFixedHeight(height)
    if variant:
        widget.setProperty("variant", variant)
    if icon:
        color = icon_color or {"primary": "#ffffff", "danger": "#ffffff", "dangerOutline": theme.DANGER,
                               "dangerText": theme.DANGER}.get(variant or "", theme.TEXT_2)
        widget.setIcon(theme.icon(icon, color, 16))
    widget.setCursor(Qt.PointingHandCursor)
    return widget


def icon_button(icon: str, tooltip: str, color: str = theme.TEXT_2, danger: bool = False) -> QToolButton:
    widget = QToolButton()
    widget.setFixedSize(theme.CONTROL_HEIGHT, theme.CONTROL_HEIGHT)
    if danger:
        widget.setProperty("danger", "true")
    widget.setIcon(theme.icon(icon, color, 18))
    widget.setIconSize(theme.ICON_SIZE)
    widget.setToolTip(tooltip)
    widget.setAccessibleName(tooltip)
    widget.setCursor(Qt.PointingHandCursor)
    return widget


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


class Segmented(QFrame):
    """Every option stays clickable (the web Segmented control)."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], value: str, parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.setFixedHeight(theme.CONTROL_HEIGHT)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in options:
            item = QPushButton(text)
            item.setFixedHeight(theme.CONTROL_HEIGHT - 6)
            item.setCheckable(True)
            item.setChecked(key == value)
            item.setCursor(Qt.PointingHandCursor)
            item.setProperty("value", key)
            self.group.addButton(item)
            self.buttons[key] = item
            layout.addWidget(item)
        self.group.buttonClicked.connect(lambda b: self.changed.emit(b.property("value")))

    def value(self) -> str:
        checked = self.group.checkedButton()
        return checked.property("value") if checked else ""

    def set_value(self, value: str) -> None:
        if value in self.buttons:
            self.buttons[value].setChecked(True)


class Alert(QFrame):
    """Colored message box (error / success / warning / info) with an icon."""

    ICONS = {"error": ("alert", theme.DANGER), "success": ("check", theme.SUCCESS),
             "warning": ("alert", theme.WARNING), "info": ("info", theme.INFO)}

    def __init__(self, tone: str = "info", parent=None):
        super().__init__(parent)
        self.setObjectName("alert")
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: 700;")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        for text_label in (self.title, self.body):
            text_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        from PySide6.QtWidgets import QGridLayout

        layout = self.grid = QGridLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(4)
        layout.addWidget(self.icon, 0, 0, Qt.AlignTop)
        layout.addWidget(self.title, 0, 1)
        layout.addWidget(self.body, 1, 1)
        layout.addLayout(self.actions, 2, 1)
        layout.setColumnStretch(1, 1)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        name, color = self.ICONS[tone]
        self.icon.setPixmap(theme.icon_pixmap(name, color, 18))
        restyle(self)
        for child in (self.title, self.body):  # the tone colors the text too
            restyle(child)

    def show_message(self, tone: str, title: str, body: str = "") -> None:
        self.set_tone(tone)
        self.title.setText(title)
        self.title.setVisible(bool(title))
        self.body.setText(body)
        self.body.setVisible(bool(body))
        # without a title the body starts next to the icon instead of under an empty row
        self.grid.removeWidget(self.body)
        self.grid.addWidget(self.body, 1 if title else 0, 1)
        self.show()

    def clear_actions(self) -> None:
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


class Toaster(QWidget):
    """Short notifications in the bottom-right corner of a window (the web toasts)."""

    WIDTH = 384

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(8)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):  # keep the stack in the corner when the window resizes
        if event.type() == event.Type.Resize:
            self._place()
        return False

    def _place(self) -> None:
        """Cover exactly the visible notifications, so nothing underneath is blocked."""
        if self.box.count() == 0:
            self.hide()
            return
        parent = self.parentWidget()
        height = min(self.box.sizeHint().height(), parent.height() - 20)
        self.setGeometry(parent.width() - self.WIDTH - 16, parent.height() - height - 16, self.WIDTH, height)
        self.raise_()

    def _remove(self, toast: QWidget) -> None:
        self.box.removeWidget(toast)
        toast.deleteLater()
        self._place()

    def show_toast(self, message: str, tone: str = "info") -> None:
        toast = QFrame()
        toast.setObjectName("toast")
        toast.setProperty("tone", tone)
        layout = QHBoxLayout(toast)
        layout.setContentsMargins(12, 10, 8, 10)
        name, color = Alert.ICONS["error" if tone == "error" else "success" if tone == "success" else "info"]
        mark = QLabel()
        mark.setPixmap(theme.icon_pixmap(name, color, 16))
        text = QLabel(message)
        text.setWordWrap(True)
        close = icon_button("x", "", theme.TEXT_3)
        close.clicked.connect(lambda: self._remove(toast))
        layout.addWidget(mark, 0, Qt.AlignTop)
        layout.addWidget(text, 1)
        layout.addWidget(close, 0, Qt.AlignTop)
        toast.setFixedWidth(self.WIDTH)
        self.box.addWidget(toast)
        self.show()
        self._place()
        QTimer.singleShot(7000 if tone == "error" else 4000,
                          lambda: self._remove(toast) if self.box.indexOf(toast) >= 0 else None)


class DropOverlay(QFrame):
    """Dashed overlay shown while files/folders are dragged over the drive page."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("dropOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        self.icon = QLabel()
        self.icon.setPixmap(theme.icon_pixmap("upload", theme.PRIMARY, 36))
        self.icon.setAlignment(Qt.AlignCenter)
        self.text = QLabel()
        self.text.setAlignment(Qt.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(self.icon)
        layout.addWidget(self.text)
        layout.addStretch(1)
        self.hide()

    def show_over(self, text: str) -> None:
        self.text.setText(text)
        self.setGeometry(self.parentWidget().rect().adjusted(8, 8, -8, -8))
        self.raise_()
        self.show()


class FlowLayout(QLayout):
    """Wrapping layout for folder cards (like the web CSS grid with auto-fill)."""

    def __init__(self, parent=None, spacing: int = 10):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect: QRect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self.items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line > 0:
                x, y, line = rect.x(), y + line + self.spacing(), 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line = max(line, hint.height())
        return y + line - rect.y()


def expanding(widget: QWidget) -> QWidget:
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return widget


# --- dialogs with translated buttons (Qt's standard ones would say OK / Cancel) -------------


def _dialog_shell(parent, title: str):
    from PySide6.QtWidgets import QDialog

    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setMinimumWidth(440)
    dialog.setStyleSheet(f"QDialog {{ background: {theme.SURFACE}; }}")
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(22, 20, 22, 18)
    layout.setSpacing(12)
    heading = QLabel(title)
    heading.setStyleSheet("font-size: 13pt; font-weight: 700;")
    layout.addWidget(heading)
    return dialog, layout


def confirm(parent, title: str, text: str, confirm_text: str, cancel_text: str, danger: bool = True) -> bool:
    from PySide6.QtWidgets import QDialog

    dialog, layout = _dialog_shell(parent, title)
    message = QLabel(text)
    message.setWordWrap(True)
    message.setStyleSheet(f"color: {theme.TEXT_2};")
    layout.addWidget(message)
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = button(cancel_text, "ghost")
    ok = button(confirm_text, "danger" if danger else "primary")
    cancel.clicked.connect(dialog.reject)
    ok.clicked.connect(dialog.accept)
    buttons.addWidget(cancel)
    buttons.addWidget(ok)
    layout.addLayout(buttons)
    ok.setDefault(True)
    return dialog.exec() == QDialog.Accepted


def ask_text(parent, title: str, field: str, hint: str, ok_text: str, cancel_text: str) -> str | None:
    from PySide6.QtWidgets import QDialog, QLineEdit

    dialog, layout = _dialog_shell(parent, title)
    layout.addWidget(label(field, "fieldLabel"))
    edit = QLineEdit()
    edit.setMaxLength(255)
    layout.addWidget(edit)
    layout.addWidget(label(hint, "hint", wrap=True))
    buttons = QHBoxLayout()
    buttons.addStretch(1)
    cancel = button(cancel_text, "ghost")
    ok = button(ok_text, "primary")
    cancel.clicked.connect(dialog.reject)
    ok.clicked.connect(dialog.accept)
    buttons.addWidget(cancel)
    buttons.addWidget(ok)
    layout.addLayout(buttons)
    ok.setDefault(True)
    edit.setFocus()
    if dialog.exec() == QDialog.Accepted and edit.text().strip():
        return edit.text().strip()
    return None
