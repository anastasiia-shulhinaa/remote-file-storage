"""MiniDrive visual style for the desktop: the same palette, shapes and icons as the web client."""

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer

# design tokens (web/src/styles.css, light theme)
BG = "#f6f7fb"
SURFACE = "#ffffff"
SURFACE_2 = "#f1f3f9"
SURFACE_HOVER = "#eef0fb"
BORDER = "#e3e6ef"
BORDER_STRONG = "#cfd4e2"
TEXT = "#171a26"
TEXT_2 = "#5b6176"
TEXT_3 = "#8a90a3"
PRIMARY = "#4f46e5"
PRIMARY_HOVER = "#4338ca"
PRIMARY_SOFT = "#eceafe"
SUCCESS = "#15803d"
SUCCESS_SOFT = "#e5f6eb"
DANGER = "#dc2626"
DANGER_SOFT = "#fdecec"
WARNING = "#b45309"
WARNING_SOFT = "#fdf3e2"
INFO = "#2563eb"
INFO_SOFT = "#e8f0fe"
TONE_CODE = "#7c3aed"
TONE_IMAGE = "#0d9488"
TONE_FILE = "#64748b"

# the same 24×24 stroke icons as web/src/components/Icon.tsx
ICON_PATHS = {
    "cloud": "M7 18a4.5 4.5 0 0 1-.6-8.96A6.5 6.5 0 0 1 18.9 8.5 4.75 4.75 0 0 1 18.25 18H7z",
    "folder": "M3 7.5A1.5 1.5 0 0 1 4.5 6h4.38l2 2h8.62A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
    "folderPlus": "M3 7.5A1.5 1.5 0 0 1 4.5 6h4.38l2 2h8.62A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5zM12 11v5M9.5 13.5h5",
    "file": "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
    "code": "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M10 12l-2 2 2 2M14 12l2 2-2 2",
    "image": "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM4 16l4.5-4.5 3.5 3.5 2.5-2.5L20 18M15.5 9.5h.01",
    "upload": "M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
    "download": "M12 4v12M7 11l5 5 5-5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
    "trash": "M4 7h16M10 11v6M14 11v6M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12M9 7V4h6v3",
    "eye": "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "sync": "M20 11a8 8 0 0 0-14.9-3.5M4 4v4h4M4 13a8 8 0 0 0 14.9 3.5M20 20v-4h-4",
    "history": "M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 7v5l3 2",
    "plus": "M12 5v14M5 12h14",
    "chevronRight": "M9 6l6 6-6 6",
    "columns": "M4 5h16v14H4zM9.5 5v14M14.5 5v14",
    "arrowUp": "M12 19V5M6 11l6-6 6 6",
    "arrowDown": "M12 5v14M6 13l6 6 6-6",
    "logout": "M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H4",
    "check": "M5 12.5l4.5 4.5L19 7.5",
    "x": "M6 6l12 12M18 6L6 18",
    "alert": "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
    "info": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01",
    "laptop": "M4 6a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v9H4zM2 18h20",
    "refresh": "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
    "filter": "M4 5h16l-6 7.5V19l-4-2v-4.5z",
    "equal": "M5 9h14M5 15h14",
    "hardDrive": "M3 13h18v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zM5.5 5h13l2.5 8H3zM7 16h.01M11 16h.01",
    "eraser": "M8 20h12M4.6 13.6l8.8-8.8a2 2 0 0 1 2.8 0l3 3a2 2 0 0 1 0 2.8L12 17.8 8.2 20H6.8l-2.2-2.2a2 2 0 0 1 0-2.8zM9 9.2l5.8 5.8",
    "eyeOff": "M3 3l18 18M10.6 5.1A9.8 9.8 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7a9.4 9.4 0 0 0 4.3-1M9.9 9.9a3 3 0 0 0 4.2 4.2",
}

CODE_EXT = {".c", ".cpp", ".h", ".hpp", ".py", ".ts", ".js", ".java"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".jfif", ".jpe", ".gif", ".svg", ".webp", ".bmp"}


@lru_cache(maxsize=512)
def icon_pixmap(name: str, color: str = TEXT_2, size: int = 18, ratio: float = 2.0) -> QPixmap:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="{ICON_PATHS[name]}"/></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def icon(name: str, color: str = TEXT_2, size: int = 18) -> QIcon:
    return QIcon(icon_pixmap(name, color, size))


def file_icon(extension: str) -> tuple[str, str]:
    """(icon name, tone color) by extension, like the web file table."""
    extension = (extension or "").lower()
    if extension in CODE_EXT:
        return "code", TONE_CODE
    if extension in IMAGE_EXT:
        return "image", TONE_IMAGE
    return "file", TONE_FILE


@lru_cache(maxsize=64)
def tile_icon(name: str, color: str, size: int = 32) -> QIcon:
    """File icon on a soft rounded tile (the web .file-icon)."""
    ratio = 2.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    tint = QColor(color)
    tint.setAlpha(30)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size * ratio, size * ratio), 9 * ratio, 9 * ratio)
    painter.fillPath(path, tint)
    inner = icon_pixmap(name, color, 17, ratio)
    side = 17 * ratio  # explicit target size: the inner pixmap's device pixel ratio must not shrink it
    offset = (size * ratio - side) / 2
    painter.drawPixmap(QRectF(offset, offset, side, side), inner, QRectF(inner.rect()))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return QIcon(pixmap)


def brand_mark(size: int = 34, on_color: bool = False) -> QPixmap:
    """Purple gradient square with the cloud (the web .brand-mark); translucent white on colored backgrounds."""
    ratio = 2.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    gradient = QLinearGradient(0, 0, size * ratio, size * ratio)
    gradient.setColorAt(0, QColor("#4f46e5"))
    gradient.setColorAt(1, QColor("#7c3aed"))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size * ratio, size * ratio), 10 * ratio, 10 * ratio)
    painter.fillPath(path, QColor(255, 255, 255, 46) if on_color else gradient)
    cloud = icon_pixmap("cloud", "#ffffff", int(size * 0.6), ratio)
    side = int(size * 0.6) * ratio
    offset = (size * ratio - side) / 2
    painter.drawPixmap(QRectF(offset, offset, side, side), cloud, QRectF(cloud.rect()))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def avatar(letter: str, size: int = 34) -> QPixmap:
    ratio = 2.0
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    gradient = QLinearGradient(0, 0, size * ratio, size * ratio)
    gradient.setColorAt(0, QColor("#6366f1"))
    gradient.setColorAt(1, QColor("#a855f7"))
    painter.setBrush(gradient)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(0, 0, size * ratio, size * ratio))
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setPixelSize(int(size * ratio * 0.42))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, size * ratio, size * ratio), Qt.AlignCenter, letter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


ICON_SIZE = QSize(18, 18)
# the web's sizes: page buttons 38 px, toolbar controls 34 px (inner segment buttons 28 px)
BUTTON_HEIGHT = 38
CONTROL_HEIGHT = 34

STYLESHEET = f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QDialog, #page, #content {{ background: {BG}; }}
QToolTip {{ background: {TEXT}; color: white; border: none; padding: 4px 8px; border-radius: 6px; }}

/* sidebar */
#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
#brand {{ font-size: 13pt; font-weight: 700; }}
#sidebarLabel {{ color: {TEXT_3}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; padding: 6px 10px 2px 10px; }}
QPushButton[nav="true"] {{
    text-align: left; padding: 8px 12px; border: none; border-radius: 10px;
    color: {TEXT_2}; font-weight: 600; background: transparent;
}}
QPushButton[nav="true"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton[nav="true"]:checked {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}
#folderTree {{ border: none; background: transparent; outline: 0; show-decoration-selected: 1; }}
#folderTree::item {{ padding: 5px 4px; border-radius: 8px; color: {TEXT_2}; }}
#folderTree::item:hover {{ background: {SURFACE_HOVER}; }}
#folderTree::item:selected {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; }}

/* top bar */
#topbar {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
#userName {{ font-weight: 700; }}
#userSub {{ color: {TEXT_3}; font-size: 8.5pt; }}

/* segmented controls (language, filter) */
#segmented {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; }}
#segmented QPushButton {{
    border: none; border-radius: 7px; padding: 0 12px; background: transparent;
    color: {TEXT_2}; font-weight: 600; min-height: 0;
}}
#segmented QPushButton:hover {{ color: {TEXT}; }}
#segmented QPushButton:checked {{ background: {SURFACE}; color: {PRIMARY}; }}

/* buttons */
QPushButton {{
    border-radius: 10px; padding: 0 14px; font-weight: 600;
    border: 1px solid {BORDER_STRONG}; background: {SURFACE};
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton:disabled {{ color: {TEXT_3}; background: {SURFACE_2}; border-color: {BORDER}; }}
QPushButton[variant="primary"] {{ background: {PRIMARY}; color: white; border: 1px solid {PRIMARY}; }}
QPushButton[variant="primary"]:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton[variant="primary"]:disabled {{ background: #a5a1f2; border-color: #a5a1f2; color: white; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {TEXT_2}; }}
QPushButton[variant="ghost"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton[variant="danger"] {{ background: {DANGER}; color: white; border: 1px solid {DANGER}; }}
QPushButton[variant="dangerOutline"] {{ background: {SURFACE}; color: {DANGER}; border: 1px solid #f0a3a3; }}
QPushButton[variant="dangerOutline"]:hover {{ background: {DANGER_SOFT}; }}
QPushButton[variant="dangerText"] {{ background: transparent; color: {DANGER}; border: 1px solid transparent; }}
QPushButton[variant="dangerText"]:hover {{ background: {DANGER_SOFT}; }}
QPushButton[card="folder"] {{
    text-align: left; padding: 0 14px; border: 1px solid {BORDER}; border-radius: 12px;
    background: {SURFACE}; font-weight: 600;
}}
QPushButton[card="folder"]:hover {{ border-color: {PRIMARY}; background: {SURFACE}; }}
QToolButton {{ border: none; border-radius: 9px; padding: 0; background: transparent; }}
QToolButton:hover {{ background: {SURFACE_HOVER}; }}
QToolButton[danger="true"]:hover {{ background: {DANGER_SOFT}; }}
QToolButton[variant="text"] {{ padding: 0 10px; color: {TEXT_2}; font-weight: 600; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* inputs */
QLineEdit, QComboBox {{
    border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 0 10px; background: {SURFACE};
    selection-background-color: {PRIMARY_SOFT}; selection-color: {TEXT};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {PRIMARY}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ border: 1px solid {BORDER}; border-radius: 8px; background: {SURFACE};
    selection-background-color: {PRIMARY_SOFT}; selection-color: {PRIMARY}; padding: 4px; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}

/* typography */
#pageTitle {{ font-size: 18pt; font-weight: 700; }}
#crumbLink {{ color: {TEXT_2}; font-size: 12pt; font-weight: 600; }}
#sectionTitle {{ color: {TEXT_3}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; }}
#muted, QLabel[muted="true"] {{ color: {TEXT_2}; }}
#hint {{ color: {TEXT_3}; font-size: 8.5pt; }}
#cardTitle {{ font-size: 11pt; font-weight: 700; }}

/* cards */
#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#runPanel {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 12px; }}
#modeCard {{ border: 1px solid {BORDER}; border-radius: 10px; background: {SURFACE}; }}
#modeCard[active="true"] {{ border-color: {PRIMARY}; background: {PRIMARY_SOFT}; }}
#stepNo {{ background: {PRIMARY_SOFT}; color: {PRIMARY}; font-weight: 700; border-radius: 14px; }}

/* alerts */
#alert {{ border-radius: 10px; padding: 10px 12px; }}
#alert[tone="error"] {{ background: {DANGER_SOFT}; }}
#alert[tone="error"] QLabel {{ color: {DANGER}; }}
#alert[tone="success"] {{ background: {SUCCESS_SOFT}; }}
#alert[tone="success"] QLabel {{ color: {SUCCESS}; }}
#alert[tone="warning"] {{ background: {WARNING_SOFT}; }}
#alert[tone="warning"] QLabel {{ color: {WARNING}; }}
#alert[tone="info"] {{ background: {INFO_SOFT}; }}
#alert[tone="info"] QLabel {{ color: {INFO}; }}

/* tables */
QTableWidget {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; gridline-color: transparent;
    selection-background-color: {SURFACE_HOVER}; selection-color: {TEXT}; outline: 0;
}}
QTableWidget::item {{ border-bottom: 1px solid {BORDER}; padding: 0 10px; }}
QTableWidget::item:selected {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QHeaderView::section {{
    background: {SURFACE_2}; color: {TEXT_2}; border: none; border-bottom: 1px solid {BORDER};
    padding: 9px 10px; font-size: 8.5pt; font-weight: 700;
}}
QTableCornerButton::section {{ background: {SURFACE_2}; border: none; }}
/* the sync plan sits in a narrower card: tighter cells, like the web's .plan-table */
#planTable::item {{ padding: 0 6px; }}
#planTable QHeaderView::section {{ padding: 9px 6px; }}

/* progress */
QProgressBar {{ background: {SURFACE_2}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 4px; }}

/* menus */
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 7px 14px 7px 10px; border-radius: 8px; }}
QMenu::item:selected {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QMenu::item:disabled {{ color: {TEXT_2}; }}
QMenu::section {{ color: {TEXT_3}; font-size: 8pt; font-weight: 700; padding: 6px 10px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}

/* toasts / overlay */
#toast {{ background: {SURFACE}; border: 1px solid {BORDER}; border-left: 4px solid {INFO}; border-radius: 8px; }}
#toast[tone="success"] {{ border-left-color: {SUCCESS}; }}
#toast[tone="error"] {{ border-left-color: {DANGER}; }}
#dropOverlay {{ background: rgba(79, 70, 229, 30); border: 3px dashed {PRIMARY}; border-radius: 14px; }}
#dropOverlay QLabel {{ color: {PRIMARY}; font-size: 13pt; font-weight: 700; background: transparent; }}

/* login */
#hero {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4f46e5, stop:0.55 #7c3aed, stop:1 #0ea5e9); }}
#hero QLabel {{ color: white; background: transparent; }}
#authScroll, #authPanel {{ background: {BG}; }}
#heroTitle {{ font-size: 20pt; font-weight: 700; }}
#heroText {{ font-size: 12pt; }}
#authTitle {{ font-size: 18pt; font-weight: 700; }}
#fieldLabel {{ font-weight: 600; font-size: 9pt; }}
QTabWidget::pane {{ border: none; }}
"""
