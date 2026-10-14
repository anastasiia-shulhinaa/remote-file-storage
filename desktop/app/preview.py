"""FileViewer: metadata + content preview from GET /files/{id}/preview (same types as the web client).

text → code view with line numbers, image → picture, pdf → QtPdf viewer,
html (converted .docx) → QTextBrowser (no scripts, no network), unavailable → reason.
"""

import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app import theme
from app.i18n import format_datetime, format_size, tr
from app.widgets import button, label

CODE_BG = "#0f1222"
CODE_TEXT = "#e4e7f5"
CODE_MUTED = "#5d6585"


class _LineNumbers(QWidget):
    def __init__(self, editor: "CodeView"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.number_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_numbers(event)


class CodeView(QPlainTextEdit):
    """Read-only source view with line numbers (the web .code-view)."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.setStyleSheet(f"QPlainTextEdit {{ background: {CODE_BG}; color: {CODE_TEXT}; border: none; "
                           f"border-radius: 12px; padding: 8px; selection-background-color: #3b3f73; }}")
        self.numbers = _LineNumbers(self)
        self.blockCountChanged.connect(lambda _: self.setViewportMargins(self.number_width(), 0, 0, 0))
        self.updateRequest.connect(self._update_numbers)
        self.setViewportMargins(self.number_width(), 0, 0, 0)

    def number_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_numbers(self, rect, dy):
        if dy:
            self.numbers.scroll(0, dy)
        else:
            self.numbers.update(0, rect.y(), self.numbers.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        area = self.contentsRect()
        self.numbers.setGeometry(QRect(area.left(), area.top(), self.number_width(), area.height()))

    def paint_numbers(self, event):
        painter = QPainter(self.numbers)
        painter.fillRect(event.rect(), QColor(CODE_BG))
        painter.setPen(QColor(CODE_MUTED))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible():
                painter.drawText(0, top, self.numbers.width() - 10, height, Qt.AlignRight, str(number + 1))
            block = block.next()
            top += height
            number += 1


def _image_view(content: bytes) -> QWidget:
    pixmap = QPixmap()
    pixmap.loadFromData(content)
    picture = QLabel()
    picture.setAlignment(Qt.AlignCenter)
    if pixmap.isNull():
        picture.setText(tr("preview.unavailable.invalid_content"))
    else:
        picture.setPixmap(pixmap)
    area = QScrollArea()
    area.setWidget(picture)
    area.setWidgetResizable(True)
    area.setStyleSheet(f"QScrollArea {{ background: {theme.SURFACE_2}; border-radius: 12px; }}")
    return area


def _pdf_view(content: bytes, parent: QWidget) -> QWidget:
    try:
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
    except ImportError:
        return _message_view(tr("desktop.pdfUnavailable"))
    # the buffer must live as long as the document
    parent._pdf_bytes = QByteArray(content)
    parent._pdf_buffer = QBuffer(parent._pdf_bytes)
    parent._pdf_buffer.open(QIODevice.ReadOnly)
    document = QPdfDocument(parent)
    document.load(parent._pdf_buffer)
    if document.status() == QPdfDocument.Status.Error or document.pageCount() == 0:
        return _message_view(tr("preview.pdf.failed"))
    view = QPdfView(parent)
    view.setDocument(document)
    view.setPageMode(QPdfView.PageMode.MultiPage)
    view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
    view.setStyleSheet(f"background: {theme.SURFACE_2}; border-radius: 12px;")
    parent._pdf_document = document
    return view


def _html_view(html: str) -> QWidget:
    browser = QTextBrowser()
    browser.setOpenLinks(False)          # nothing inside the document is followed
    browser.setOpenExternalLinks(False)
    browser.setHtml(html)
    browser.setStyleSheet(f"QTextBrowser {{ background: white; border: 1px solid {theme.BORDER}; "
                          f"border-radius: 12px; padding: 24px; font-family: 'Times New Roman'; font-size: 11pt; }}")
    return browser


def _message_view(message: str, supported: bool = True) -> QWidget:
    box = QFrame()
    layout = QVBoxLayout(box)
    layout.addStretch(1)
    mark = QLabel()
    mark.setPixmap(theme.icon_pixmap("eye", theme.TEXT_3, 28))
    mark.setAlignment(Qt.AlignCenter)
    title = label(message, wrap=True)
    title.setAlignment(Qt.AlignCenter)
    title.setStyleSheet("font-weight: 700; font-size: 11pt;")
    layout.addWidget(mark)
    layout.addWidget(title)
    if supported:
        hint = label(tr("preview.supported"), "muted", wrap=True)
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)
    layout.addStretch(1)
    return box


class PreviewDialog(QDialog):

    def __init__(self, file: dict, preview: dict, parent=None, on_download=None):
        super().__init__(parent)
        self.setWindowTitle(f"{file['name']} · {tr('app.name')}")
        self.resize(900, 680)
        self.setStyleSheet(f"QDialog {{ background: {theme.SURFACE}; }}")

        icon_name, tone = theme.file_icon(file.get("extension") or "")
        head = QHBoxLayout()
        tile = QLabel()
        tile.setPixmap(theme.tile_icon(icon_name, tone).pixmap(32, 32))
        title = label(file["name"])
        title.setStyleSheet("font-size: 13pt; font-weight: 700;")
        head.addWidget(tile)
        head.addWidget(title, 1)

        meta = QGridLayout()
        meta.setHorizontalSpacing(28)
        items = [
            ("preview.size", format_size(file["size"])),
            ("preview.created", format_datetime(file["created_at"])),
            ("preview.modified", format_datetime(file["modified_at"])),
            ("preview.uploadedBy", file.get("uploaded_by_name") or file["uploaded_by"]),
            ("preview.modifiedBy", file.get("modified_by_name") or file["modified_by"]),
        ]
        for column, (key, value) in enumerate(items):
            meta.addWidget(label(tr(key).upper(), "sectionTitle"), 0, column)
            meta.addWidget(label(str(value)), 1, column)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close = button(tr("dialog.close"), "ghost")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        if on_download:
            download = button(tr("preview.download"), "primary", "download")
            download.clicked.connect(lambda: on_download(file))
            footer.addWidget(download)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        layout.addLayout(head)
        layout.addLayout(meta)
        layout.addWidget(self.content_widget(preview), 1)
        layout.addLayout(footer)

    def content_widget(self, preview: dict) -> QWidget:
        kind = preview.get("type")
        if kind == "text":
            box = QWidget()
            column = QVBoxLayout(box)
            column.setContentsMargins(0, 0, 0, 0)
            info = QHBoxLayout()
            chip = label(tr(f"preview.lang.{preview.get('language') or 'text'}"))
            chip.setStyleSheet(f"background: {theme.SURFACE_2}; color: {theme.TEXT_2}; border-radius: 9px; "
                               f"padding: 2px 9px; font-weight: 600;")
            info.addWidget(chip)
            if preview.get("truncated"):
                info.addWidget(label(tr("preview.truncated"), "muted"))
            info.addStretch(1)
            column.addLayout(info)
            column.addWidget(CodeView(preview.get("content") or ""), 1)
            return box
        if kind == "image":
            return _image_view(base64.b64decode(preview.get("content_base64") or ""))
        if kind == "pdf":
            return _pdf_view(base64.b64decode(preview.get("content_base64") or ""), self)
        if kind == "html":
            box = QWidget()
            column = QVBoxLayout(box)
            column.setContentsMargins(0, 0, 0, 0)
            column.addWidget(label(tr("preview.docx.note"), "muted"))
            column.addWidget(_html_view(preview.get("content") or ""), 1)
            return box
        reason = preview.get("reason") or "unsupported_type"
        return _message_view(tr(f"preview.unavailable.{reason}"))

