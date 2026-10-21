import calendar
import logging
import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QByteArray,
    QDate,
    QObject,
    QSize,
    QSettings,
    QThread,
    QTime,
    QTimer,
    Qt,
    QPoint,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from .local_auth_state import (
    clear_local_auth_profile,
    has_local_auth_profile,
)
from .local_credentials import (
    CredentialStoreError,
    clear_google_password,
    get_google_password,
    save_google_password,
)
from .local_paths import APP_DATA_DIRECTORY, LOCAL_PROFILE_ID
from .local_settings import get_settings_store
from .power_events import notify_scheduler_on_resume
from .runtime import configure_playwright_browser_path
from .scheduler import (
    run_automation,
    start_scheduler,
    stop_scheduler,
    sync_schedule,
    wakeup_scheduler,
)
from .scripts.automation import test_form_connection
from .scripts.save_auth import save_auth_for_user
from .startup import enable_windows_startup

WORK_DAY_CHOICES = [
    ("Choose a work-day type", None),
    ("Campus holiday", 1),
    ("Working day · present", 2),
    ("Working day · leave or absent", 3),
]

FACE = "#D4D0C8"
WHITE = "#FFFFFF"
BLACK = "#000000"
UI_FONT_FAMILY = "Tahoma"


def draw_bevel(
    painter: QPainter, rect, *, sunken: bool, button: bool = False
) -> None:
    """Draw the paired one-pixel light and shadow lines used by classic controls."""
    rect = rect.adjusted(0, 0, -1, -1)
    if rect.width() < 4 or rect.height() < 4:
        return

    if sunken:
        upper_outer, upper_inner = "#808080", "#404040"
        lower_inner, lower_outer = FACE, WHITE
    else:
        upper_outer, upper_inner = WHITE, FACE
        lower_inner, lower_outer = "#808080", "#0A0A0A" if button else "#404040"

    def edges(area, color, top_left: bool) -> None:
        painter.setPen(QPen(QColor(color), 1))
        if top_left:
            painter.drawLine(area.left(), area.bottom(), area.left(), area.top())
            painter.drawLine(area.left(), area.top(), area.right(), area.top())
        else:
            painter.drawLine(area.right(), area.top(), area.right(), area.bottom())
            painter.drawLine(area.right(), area.bottom(), area.left(), area.bottom())

    edges(rect, upper_outer, True)
    edges(rect.adjusted(1, 1, -1, -1), upper_inner, True)
    edges(rect.adjusted(1, 1, -1, -1), lower_inner, False)
    edges(rect, lower_outer, False)


class ClassicBevelFrame(QFrame):
    def __init__(
        self,
        *,
        sunken: bool,
        fill: str = FACE,
        preferred_height: int | None = None,
        minimum_height: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.sunken = sunken
        self.fill = fill
        self.preferred_height = preferred_height
        self.minimum_height = minimum_height
        self.setFrameShape(QFrame.Shape.NoFrame)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API name
        size = super().sizeHint()
        if self.preferred_height is not None:
            size.setHeight(self.preferred_height)
        return size

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API name
        size = super().minimumSizeHint()
        if self.minimum_height is not None:
            size.setHeight(max(size.height(), self.minimum_height))
        return size

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.fill))
        draw_bevel(painter, self.rect(), sunken=self.sunken)


class ClassicButton(QPushButton):
    def __init__(self, text: str, parent=None, *, glyph: bool = False) -> None:
        super().__init__(text, parent)
        self.glyph = glyph
        self.setFont(QFont(UI_FONT_FAMILY, 8))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMinimumWidth(75)
        self.setFixedHeight(23)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        painter.fillRect(self.rect(), QColor(FACE))

        outline = self.rect().adjusted(0, 0, -1, -1)
        if self.isDefault() and not self.glyph:
            painter.setPen(QPen(QColor(BLACK), 1))
            painter.drawRect(outline)
            outline = outline.adjusted(1, 1, -1, -1)
        draw_bevel(painter, outline, sunken=self.isDown(), button=True)

        text_rect = self.rect().adjusted(12, 2, -12, -2)
        if self.isDown():
            text_rect.translate(1, 1)
        flags = int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextShowMnemonic)
        if self.glyph:
            shift = 1 if self.isDown() else 0
            name = self.accessibleName()
            painter.setPen(QPen(QColor(BLACK), 1))
            if name == "Minimize":
                painter.fillRect(5 + shift, 9 + shift, 6, 2, QColor(BLACK))
            elif name == "Maximize":
                painter.fillRect(3 + shift, 2 + shift, 9, 2, QColor(BLACK))
                painter.fillRect(3 + shift, 2 + shift, 1, 9, QColor(BLACK))
                painter.fillRect(11 + shift, 2 + shift, 1, 9, QColor(BLACK))
                painter.fillRect(3 + shift, 10 + shift, 9, 1, QColor(BLACK))
            elif name == "Close":
                painter.setPen(QPen(QColor(BLACK), 2))
                painter.drawLine(4 + shift, 3 + shift, 11 + shift, 9 + shift)
                painter.drawLine(11 + shift, 3 + shift, 4 + shift, 9 + shift)
            elif name in ("Open work-day choices", "Increase submission time", "Decrease submission time"):
                if name == "Increase submission time":
                    points = [(5, 5), (10, 5), (7, 2)]
                elif name == "Decrease submission time":
                    points = [(5, 3), (10, 3), (7, 6)]
                else:
                    points = [(4, 6), (11, 6), (7, 10)]
                points = [QPoint(x + shift, y + shift) for x, y in points]
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(BLACK))
                painter.drawPolygon(points)
            elif name == "Previous month":
                painter.setPen(QPen(QColor(BLACK), 1))
                painter.drawLine(9 + shift, 4 + shift, 5 + shift, 7 + shift)
                painter.drawLine(5 + shift, 7 + shift, 9 + shift, 10 + shift)
            elif name == "Next month":
                painter.setPen(QPen(QColor(BLACK), 1))
                painter.drawLine(5 + shift, 4 + shift, 9 + shift, 7 + shift)
                painter.drawLine(9 + shift, 7 + shift, 5 + shift, 10 + shift)
        elif self.isEnabled():
            painter.setPen(QColor(BLACK))
            painter.drawText(text_rect, flags, self.text())
        else:
            painter.setPen(QColor(WHITE))
            painter.drawText(text_rect.translated(1, 1), flags, self.text())
            painter.setPen(QColor("#808080"))
            painter.drawText(text_rect, flags, self.text())

        if self.hasFocus() and self.isEnabled() and not self.glyph:
            metrics = painter.fontMetrics()
            visible_text = self.text().replace("&", "")
            width = metrics.horizontalAdvance(visible_text)
            height = metrics.height()
            focus_rect = self.rect().adjusted(
                max(4, (self.width() - width) // 2 - 2),
                max(3, (self.height() - height) // 2 - 1),
                -max(4, (self.width() - width) // 2 - 2),
                -max(3, (self.height() - height) // 2 - 1),
            )
            painter.setPen(QPen(QColor(BLACK), 1, Qt.PenStyle.DotLine))
            painter.drawRect(focus_rect)


class AutomaticReconnectDialog(QDialog):
    """Configure the optional password that is held by Credential Manager."""

    def __init__(self, account_email: str, password_saved: bool, parent=None) -> None:
        super().__init__(parent)
        self.remove_requested = False
        self.setWindowTitle("Automatic reconnect")
        self.setModal(True)
        self.setFixedWidth(430)
        self.setStyleSheet(CLASSIC_STYLESHEET.replace("MS Sans Serif", UI_FONT_FAMILY))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(8)
        message = QLabel(
            "When Google signs this profile out, Form Automation can select this "
            "account and enter its saved password. Google verification, CAPTCHA, and "
            "two-step prompts will still require you to reconnect manually."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        layout.addWidget(QLabel("Google account email:"))
        self.email_edit = QLineEdit(account_email)
        self.email_edit.setFixedHeight(22)
        self.email_edit.setPlaceholderText("name@example.com")
        layout.addWidget(self.email_edit)
        layout.addWidget(QLabel("Password:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setFixedHeight(22)
        self.password_edit.setPlaceholderText(
            "A password is already saved" if password_saved else "Enter password"
        )
        layout.addWidget(self.password_edit)
        status = "Password is stored in Windows Credential Manager." if password_saved else "No password is saved yet."
        self.storage_status = QLabel(status)
        self.storage_status.setObjectName("accountMessage")
        layout.addWidget(self.storage_status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.remove_button = ClassicButton("Remove password")
        self.remove_button.setFixedWidth(118)
        self.remove_button.setEnabled(password_saved)
        self.remove_button.clicked.connect(self._remove)
        buttons.addWidget(self.remove_button)
        self.cancel_button = ClassicButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.save_button = ClassicButton("Save password")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._accept_save)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

    def _accept_save(self) -> None:
        if not self.email_edit.text().strip():
            QMessageBox.warning(self, "Automatic reconnect", "Enter the Google account email.")
            return
        if not self.password_edit.text():
            QMessageBox.warning(self, "Automatic reconnect", "Enter the account password.")
            return
        self.accept()

    def _remove(self) -> None:
        self.remove_requested = True
        self.accept()


class ClassicRadioButton(QRadioButton):
    """A reliable Windows-2000 radio indicator across Qt platform themes."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setFont(QFont(UI_FONT_FAMILY, 8))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMinimumHeight(20)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        indicator = self.rect()
        indicator.setLeft(2)
        indicator.setTop((self.height() - 13) // 2)
        indicator.setWidth(13)
        indicator.setHeight(13)
        painter.fillRect(indicator, QColor(WHITE))
        painter.setPen(QPen(QColor("#404040"), 1))
        painter.drawEllipse(indicator)
        if self.isChecked():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(BLACK))
            painter.drawEllipse(indicator.adjusted(4, 4, -4, -4))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        text_rect = self.rect().adjusted(22, 0, -1, 0)
        painter.setPen(QColor(BLACK if self.isEnabled() else "#808080"))
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextShowMnemonic),
            self.text(),
        )
        if self.hasFocus() and self.isEnabled():
            painter.setPen(QPen(QColor(BLACK), 1, Qt.PenStyle.DotLine))
            painter.drawRect(text_rect.adjusted(0, 2, -2, -3))


class ClassicCheckBox(QCheckBox):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setFont(QFont(UI_FONT_FAMILY, 8))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
        indicator = self.rect().adjusted(0, 0, 0, 0)
        indicator.setTop((self.height() - 13) // 2)
        indicator.setSize(indicator.size().boundedTo(self.rect().size()))
        indicator.setWidth(13)
        indicator.setHeight(13)
        painter.fillRect(indicator, QColor(WHITE))
        draw_bevel(painter, indicator, sunken=True)
        if self.isChecked():
            painter.setPen(QPen(QColor(BLACK), 1))
            x, y = indicator.left(), indicator.top()
            painter.drawLine(x + 3, y + 6, x + 5, y + 8)
            painter.drawLine(x + 5, y + 8, x + 9, y + 4)

        metrics = painter.fontMetrics()
        label_rect = self.rect().adjusted(19, 0, -1, 0)
        painter.setPen(QColor(BLACK if self.isEnabled() else "#808080"))
        painter.drawText(
            label_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextShowMnemonic),
            self.text(),
        )
        if self.hasFocus() and self.isEnabled():
            width = metrics.horizontalAdvance(self.text().replace("&", ""))
            focus_rect = label_rect.adjusted(0, 3, -(label_rect.width() - width), -3)
            painter.setPen(QPen(QColor(BLACK), 1, Qt.PenStyle.DotLine))
            painter.drawRect(focus_rect)


class EtchedGroupBox(QGroupBox):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(title, parent)
        self.setFont(QFont(UI_FONT_FAMILY, 8))
        self.setStyleSheet("QGroupBox { border: none; margin: 0; padding: 0; }")

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(FACE))
        title_metrics = painter.fontMetrics()
        line_y = max(8, title_metrics.height() // 2 + 1)
        title_width = title_metrics.horizontalAdvance(self.title())
        gap_start = 5
        gap_end = 11 + title_width

        painter.setPen(QPen(QColor("#808080"), 1))
        painter.drawLine(0, line_y, gap_start, line_y)
        painter.drawLine(gap_end, line_y, self.width() - 1, line_y)
        painter.drawLine(0, line_y, 0, self.height() - 1)
        painter.drawLine(0, self.height() - 1, self.width() - 1, self.height() - 1)
        painter.drawLine(self.width() - 1, line_y, self.width() - 1, self.height() - 1)

        painter.setPen(QPen(QColor(WHITE), 1))
        painter.drawLine(gap_start + 1, line_y + 1, gap_end + 1, line_y + 1)
        painter.drawLine(1, line_y + 1, 1, self.height() - 2)
        painter.drawLine(1, self.height() - 2, self.width() - 2, self.height() - 2)
        painter.drawLine(self.width() - 2, line_y + 1, self.width() - 2, self.height() - 2)

        painter.setPen(QColor(BLACK))
        title_rect = self.rect().adjusted(8, line_y - title_metrics.height() // 2, -8, 0)
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            self.title(),
        )


class WindowBorder(ClassicBevelFrame):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(sunken=False, fill=FACE, parent=window)
        self.window = window

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            edges = Qt.Edge(0)
            if point.x() <= 5:
                edges |= Qt.Edge.LeftEdge
            elif point.x() >= self.width() - 6:
                edges |= Qt.Edge.RightEdge
            if point.y() <= 5:
                edges |= Qt.Edge.TopEdge
            elif point.y() >= self.height() - 6:
                edges |= Qt.Edge.BottomEdge
            handle = self.window.windowHandle()
            if edges and handle and handle.startSystemResize(edges):
                event.accept()
                return
        super().mousePressEvent(event)


class ClassicTitleBar(QWidget):
    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self.window = window
        self.setFixedHeight(20)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 2, 2, 2)
        layout.setSpacing(2)

        self.app_icon = QLabel()
        self.app_icon.setFixedSize(16, 16)
        self.app_icon.setPixmap(make_app_icon().pixmap(16, 16))
        layout.addWidget(self.app_icon)

        title = QLabel("Weekday Form Automation")
        title_font = QFont(UI_FONT_FAMILY, 8, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: white; font-size: 11px; font-weight: bold;")
        layout.addWidget(title)
        layout.addStretch(1)

        self.minimize_button = ClassicButton("_", self, glyph=True)
        self.minimize_button.setAccessibleName("Minimize")
        self.minimize_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.minimize_button.setFixedSize(16, 14)
        self.minimize_button.clicked.connect(window.showMinimized)
        layout.addWidget(self.minimize_button)

        self.maximize_button = ClassicButton("\u25a1", self, glyph=True)
        self.maximize_button.setAccessibleName("Maximize")
        self.maximize_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.maximize_button.setProperty("restoreGlyph", False)
        self.maximize_button.setFixedSize(16, 14)
        self.maximize_button.clicked.connect(self._toggle_maximize)
        layout.addWidget(self.maximize_button)

        self.close_button = ClassicButton("X", self, glyph=True)
        self.close_button.setAccessibleName("Close")
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setFixedSize(16, 14)
        self.close_button.clicked.connect(window.close)
        layout.addWidget(self.close_button)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        from PySide6.QtGui import QLinearGradient

        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0, QColor("#0A246A"))
        gradient.setColorAt(1, QColor("#A6CAF0"))
        painter.fillRect(self.rect(), gradient)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if event.button() == Qt.MouseButton.LeftButton and not self.window.isMaximized():
            handle = self.window.windowHandle()
            if handle:
                handle.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()

    def _toggle_maximize(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
            self.maximize_button.setProperty("restoreGlyph", False)
        else:
            self.window.showMaximized()
            self.maximize_button.setProperty("restoreGlyph", True)
        self.maximize_button.update()


APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<defs><linearGradient id="title" x1="0" y1="0" x2="1" y2="0">
<stop offset="0" stop-color="#0A246A"/><stop offset="1" stop-color="#A6CAF0"/>
</linearGradient></defs>
<g shape-rendering="crispEdges">
<rect x="1" y="1" width="28" height="28" fill="#0A0A0A"/>
<rect x="1" y="1" width="27" height="27" fill="#FFFFFF"/>
<rect x="2" y="2" width="26" height="26" fill="#808080"/>
<rect x="2" y="2" width="25" height="25" fill="#D4D0C8"/>
<rect x="4" y="4" width="21" height="5" fill="url(#title)"/>
<rect x="21" y="5" width="2" height="3" fill="#D4D0C8"/>
<rect x="23" y="5" width="1" height="3" fill="#FFFFFF"/>
<rect x="4" y="11" width="21" height="14" fill="#808080"/>
<rect x="5" y="12" width="20" height="13" fill="#FFFFFF"/>
<rect x="6" y="14" width="9" height="2" fill="#808080"/>
<rect x="6" y="18" width="10" height="2" fill="#808080"/>
<rect x="6" y="22" width="8" height="2" fill="#808080"/>
</g>
<polyline points="17,14.5 19,16.5 23,12.5" fill="none" stroke="#008000"
stroke-width="2" stroke-linecap="square" stroke-linejoin="miter"/>
<circle cx="24" cy="24" r="7" fill="#FFFFFF" stroke="#0A0A0A" stroke-width="1.5"/>
<circle cx="24" cy="24" r="5.4" fill="none" stroke="#D4D0C8" stroke-width="0.8"/>
<g stroke="#404040" stroke-width="0.9" stroke-linecap="butt">
<line x1="24" y1="19.2" x2="24" y2="20"/><line x1="24" y1="28" x2="24" y2="28.8"/>
<line x1="19.2" y1="24" x2="20" y2="24"/><line x1="28" y1="24" x2="28.8" y2="24"/>
</g>
<line x1="24" y1="24" x2="20.8" y2="24" stroke="#0A0A0A" stroke-width="1.4"/>
<line x1="24" y1="24" x2="25.2" y2="20.4" stroke="#0A246A" stroke-width="1"/>
<circle cx="24" cy="24" r="0.9" fill="#0A0A0A"/>
</svg>"""


@lru_cache(maxsize=1)
def make_app_icon() -> QIcon:
    renderer = QSvgRenderer(QByteArray(APP_ICON_SVG.encode("utf-8")))
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class StatusPanel(QWidget):
    def __init__(self, text: str, *, grip: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("statusPanel")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 2 if grip else 8, 2)
        layout.setSpacing(2)
        self.label = QLabel(text)
        self.label.setObjectName("statusText")
        layout.addWidget(self.label, 1)
        self.size_grip = SizeGrip(self) if grip else None
        if self.size_grip:
            layout.addWidget(self.size_grip, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

    def setText(self, text: str) -> None:  # noqa: N802 - status-panel convenience
        self.label.setText(text)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(FACE))
        painter.setPen(QPen(QColor("#808080"), 1))
        painter.drawLine(0, 0, self.width() - 1, 0)
        painter.drawLine(0, 0, 0, self.height() - 1)
        painter.setPen(QPen(QColor(WHITE), 1))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height() - 1)
        painter.drawLine(0, self.height() - 1, self.width() - 1, self.height() - 1)


class SizeGrip(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API name
        painter = QPainter(self)
        for offset in (8, 5, 2):
            painter.setPen(QPen(QColor("#808080"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(11 - offset, 11, 11, 11 - offset)
            painter.setPen(QPen(QColor(WHITE), 1, Qt.PenStyle.DotLine))
            painter.drawLine(12 - offset, 11, 11, 12 - offset)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API name
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle and handle.startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
                event.accept()
                return
        super().mousePressEvent(event)


class SessionCaptureWorker(QThread):
    succeeded = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            save_auth_for_user(LOCAL_PROFILE_ID)
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.succeeded.emit()


class SubmissionWorker(QThread):
    completed = Signal()

    def __init__(self, retry: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.retry = retry

    def run(self) -> None:
        run_automation(retry=self.retry)
        self.completed.emit()


class ConnectionTestWorker(QThread):
    progressed = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, account_email: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.account_email = account_email

    def run(self) -> None:
        try:
            message = test_form_connection(
                LOCAL_PROFILE_ID,
                self.account_email,
                self.progressed.emit,
            )
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.succeeded.emit(message)


class WindowsPowerEventFilter(QAbstractNativeEventFilter):
    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            notify_scheduler_on_resume(message, wakeup_scheduler)
        return False, 0


class OutlookCalendarWidget(QWidget):
    """Classic month grid with per-day work-day badges."""

    dateSelected = Signal(QDate)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._selected_date = QDate.currentDate()
        self._overrides: dict[str, int] = {}
        self._default_work_day: int | None = None
        self._cell_dates: dict[tuple[int, int], QDate] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        toolbar.addWidget(QLabel("Month:"))
        self.month_combo = QComboBox()
        for month in range(1, 13):
            self.month_combo.addItem(calendar.month_name[month], month)
        self.month_combo.setFixedWidth(105)
        toolbar.addWidget(self.month_combo)
        toolbar.addWidget(QLabel("Year:"))
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setFixedWidth(92)
        toolbar.addWidget(self.year_spin)
        self.previous_button = ClassicButton("< Prev")
        self.previous_button.setFixedSize(58, 23)
        toolbar.addWidget(self.previous_button)
        self.next_button = ClassicButton("Next >")
        self.next_button.setFixedSize(58, 23)
        toolbar.addWidget(self.next_button)
        toolbar.addStretch(1)
        self.today_button = ClassicButton("Today")
        self.today_button.setFixedSize(52, 23)
        toolbar.addWidget(self.today_button)
        layout.addLayout(toolbar)

        self.grid = QTableWidget(5, 8)
        self.grid.setObjectName("outlookCalendarGrid")
        self.grid.setHorizontalHeaderLabels(["Wk", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
        self.grid.verticalHeader().hide()
        self.grid.horizontalHeader().setFixedHeight(22)
        self.grid.setShowGrid(True)
        self.grid.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.grid.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.grid.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid.setFixedHeight(282)
        self.grid.setColumnWidth(0, 28)
        for column in range(1, 8):
            self.grid.horizontalHeader().setSectionResizeMode(
                column, self.grid.horizontalHeader().ResizeMode.Stretch
            )
        self.grid.verticalHeader().setSectionResizeMode(
            self.grid.verticalHeader().ResizeMode.Fixed
        )
        layout.addWidget(self.grid, 1)

        self.month_combo.currentIndexChanged.connect(self._render)
        self.year_spin.valueChanged.connect(self._render)
        self.previous_button.clicked.connect(lambda: self._move_month(-1))
        self.next_button.clicked.connect(lambda: self._move_month(1))
        self.today_button.clicked.connect(lambda: self.set_selected_date(QDate.currentDate()))
        self.grid.cellClicked.connect(self._select_cell)
        self.set_selected_date(self._selected_date)

    def selectedDate(self) -> QDate:  # noqa: N802 - Qt API compatibility
        return self._selected_date

    def set_selected_date(self, selected_date: QDate) -> None:
        self._selected_date = selected_date
        self.month_combo.blockSignals(True)
        self.year_spin.blockSignals(True)
        self.month_combo.setCurrentIndex(selected_date.month() - 1)
        self.year_spin.setValue(selected_date.year())
        self.month_combo.blockSignals(False)
        self.year_spin.blockSignals(False)
        self._render()

    def set_work_days(self, overrides: dict[str, int], default_work_day: int | None) -> None:
        self._overrides = overrides
        self._default_work_day = default_work_day
        self._render()

    def _move_month(self, offset: int) -> None:
        month = self.month_combo.currentData() + offset
        year = self.year_spin.value()
        if month == 0:
            month, year = 12, year - 1
        elif month == 13:
            month, year = 1, year + 1
        self.month_combo.setCurrentIndex(month - 1)
        self.year_spin.setValue(year)

    def _select_cell(self, row: int, column: int) -> None:
        selected_date = self._cell_dates.get((row, column))
        if selected_date is None:
            return
        self._selected_date = selected_date
        self._render()
        self.dateSelected.emit(selected_date)

    def _render(self) -> None:
        if not hasattr(self, "grid"):
            return
        year = self.year_spin.value()
        month = self.month_combo.currentData()
        month_days = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
        self.grid.setRowCount(len(month_days))
        self.grid.setFixedHeight(22 + len(month_days) * 49 + 2)
        for row in range(len(month_days)):
            self.grid.setRowHeight(row, 49)
        self._cell_dates.clear()
        for row, week in enumerate(month_days):
            week_item = QTableWidgetItem(str(week[0].isocalendar().week))
            week_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            week_item.setForeground(QColor("#404040"))
            week_item.setBackground(QColor("#ECE9D8"))
            self.grid.setItem(row, 0, week_item)
            for column, current_day in enumerate(week, start=1):
                current_date = QDate(current_day.year, current_day.month, current_day.day)
                self._cell_dates[(row, column)] = current_date
                self.grid.setCellWidget(row, column, self._day_cell(current_date, month))

    def _day_cell(self, current_date: QDate, displayed_month: int) -> QWidget:
        current_day = current_date.toPython()
        override = self._overrides.get(current_day.isoformat())
        work_day = override if override is not None else self._default_work_day
        cell = QFrame()
        inactive = current_date.month() != displayed_month
        selected = current_date == self._selected_date
        background = "#FBFBF9" if inactive else "#FFFFFF"
        header = "#F4F3EE" if inactive else "#E0DED9"
        text = "#808080" if inactive else ("#990000" if current_day.weekday() >= 5 else "#000000")
        if selected:
            header, text = "#0A246A", "#FFFFFF"
        cell.setStyleSheet(
            f"QFrame {{ background: {background}; border: {'1px dotted #000000' if selected else '0px'}; }}"
        )
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header_label = QLabel(str(current_date.day()))
        header_label.setStyleSheet(
            f"background: {header}; color: {text}; padding: 1px 4px; border-bottom: 1px solid #E0E0E0;"
        )
        layout.addWidget(header_label)
        if not inactive and current_day.weekday() < 5 and override in (1, 2, 3):
            labels = {1: ("Holiday", "#FFFF99", "#403000"), 2: ("Present", "#D1F2D2", "#0B4F10"), 3: ("Absent", "#FFD0D0", "#600000")}
            label, badge_background, badge_text = labels[work_day]
            badge = QLabel(label)
            badge.setStyleSheet(
                f"background: {badge_background}; color: {badge_text}; border: 1px solid rgba(0,0,0,0.15); padding: 1px 3px; margin: 3px 4px;"
            )
            layout.addWidget(badge)
        layout.addStretch(1)
        return cell


class _MainWindowBehavior(QMainWindow):
    def _load_settings(self) -> None:
        settings = self.settings_store.get_settings()
        index = self.work_day_combo.findData(settings["work_day"])
        self.work_day_combo.setCurrentIndex(max(index, 0))
        self.active_checkbox.setChecked(settings["automation_active"])
        if settings["schedule_time"]:
            hour, minute = map(int, settings["schedule_time"].split(":"))
            self.schedule_time.setTime(QTime(hour, minute))
        for key, editor in self.form_response_editors.items():
            editor.setPlainText(settings["form_responses"][key])
        self._load_calendar_work_day()

    def _selected_calendar_date(self):
        return self.calendar_view.selectedDate().toPython()

    def _refresh_calendar_marks(self) -> None:
        settings = self.settings_store.get_settings()
        self.calendar_view.set_work_days(
            settings["calendar_work_days"], settings["work_day"]
        )

    def _load_calendar_work_day(self) -> None:
        selected_date = self._selected_calendar_date()
        override = self.settings_store.get_settings()["calendar_work_days"].get(
            selected_date.isoformat()
        )
        self.calendar_work_day_buttons.button(override or 0).setChecked(True)
        self.calendar_selected_date_label.setText(
            selected_date.strftime("%A, %d %B %Y")
        )
        default_label = self.work_day_combo.currentText()
        if override is None:
            self.calendar_override_status.setText(
                f"Uses app default: {default_label}"
            )
        else:
            self.calendar_override_status.setText("Date-specific work-day type saved.")
        self._refresh_calendar_marks()

    def _save_calendar_work_day(self) -> None:
        selected_date = self._selected_calendar_date()
        work_day = self.calendar_work_day_buttons.checkedId()
        if work_day in (1, 2, 3):
            self.settings_store.set_calendar_work_day(selected_date, work_day)
        else:
            self.settings_store.clear_calendar_work_day(selected_date)
        sync_schedule()
        self._load_calendar_work_day()

    def _clear_calendar_work_day(self) -> None:
        self.settings_store.clear_calendar_work_day(self._selected_calendar_date())
        sync_schedule()
        self._load_calendar_work_day()

    def _queue_form_response_save(self) -> None:
        self.response_save_timer.start()

    def _save_form_responses(self) -> None:
        responses = {
            key: editor.toPlainText()
            for key, editor in self.form_response_editors.items()
        }
        self.settings_store.update_form_responses(responses)

    def _refresh_session_status(self) -> None:
        connected = self._has_valid_session()

        if connected:
            self.session_badge.setText("●  SESSION SAVED")
            self.session_badge.setProperty("connected", True)
            self.session_description.setText(
                "The encrypted Google session is saved in this PC’s local app data."
            )
            self.connect_button.setText("Change Google account")
            self.disconnect_button.setEnabled(True)
        else:
            self.session_badge.setText("●  NOT CONNECTED")
            self.session_badge.setProperty("connected", False)
            self.session_description.setText(
                "Connect the Google account that should be included with form responses."
            )
            self.connect_button.setText("Connect Google account")
            self.disconnect_button.setEnabled(False)

        self.session_badge.style().unpolish(self.session_badge)
        self.session_badge.style().polish(self.session_badge)

    @staticmethod
    def _has_valid_session() -> bool:
        return has_local_auth_profile(LOCAL_PROFILE_ID)

    def _connect_google_account(self) -> None:
        if self.session_worker and self.session_worker.isRunning():
            return

        self.connect_button.setEnabled(False)
        self.session_description.setText(
            "A Chromium window is opening. Sign in to the account you want to use; "
            "the session saves automatically when the form loads."
        )
        self.session_worker = SessionCaptureWorker(self)
        self.session_worker.succeeded.connect(self._session_capture_succeeded)
        self.session_worker.failed.connect(self._session_capture_failed)
        self.session_worker.finished.connect(self._session_capture_finished)
        self.session_worker.start()

    def _test_form_connection(self) -> None:
        if (
            self.connection_test_worker
            and self.connection_test_worker.isRunning()
        ) or (self.session_worker and self.session_worker.isRunning()):
            return
        if not self._has_valid_session():
            QMessageBox.warning(
                self,
                "Test form connection",
                "Connect a Google account before testing the form connection.",
            )
            return

        self.connection_test_button.setEnabled(False)
        self.ready_status.setText("Starting form connection test...")
        self.settings_message.setText("Starting form connection test...")
        account_email = self.settings_store.get_settings()["google_account_email"]
        self.connection_test_worker = ConnectionTestWorker(account_email, self)
        self.connection_test_worker.progressed.connect(self._connection_test_progress)
        self.connection_test_worker.succeeded.connect(self._connection_test_succeeded)
        self.connection_test_worker.failed.connect(self._connection_test_failed)
        self.connection_test_worker.finished.connect(
            lambda: self.connection_test_button.setEnabled(True)
        )
        self.connection_test_worker.start()

    def _connection_test_progress(self, message: str) -> None:
        self.ready_status.setText(message)
        self.settings_message.setText(message)

    def _connection_test_succeeded(self, message: str) -> None:
        self.ready_status.setText(message)
        self.settings_message.setText(message)
        if self.tray_icon:
            self.tray_icon.showMessage(
                "Form connection test",
                message,
                QSystemTrayIcon.MessageIcon.Information,
            )

    def _connection_test_failed(self, message: str) -> None:
        self.ready_status.setText(message)
        self.settings_message.setText(message)
        if self.tray_icon:
            self.tray_icon.showMessage(
                "Form connection test failed",
                message,
                QSystemTrayIcon.MessageIcon.Warning,
            )
        QMessageBox.warning(self, "Form connection test failed", message)

    def _configure_automatic_reconnect(self) -> None:
        settings = self.settings_store.get_settings()
        try:
            password_saved = get_google_password(LOCAL_PROFILE_ID) is not None
        except CredentialStoreError as error:
            QMessageBox.warning(self, "Automatic reconnect", str(error))
            return
        dialog = AutomaticReconnectDialog(
            settings["google_account_email"], password_saved, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if dialog.remove_requested:
                clear_google_password(LOCAL_PROFILE_ID)
                self.settings_store.update_google_account_email("")
                self.session_description.setText(
                    "Automatic reconnect password removed from Windows Credential Manager."
                )
            else:
                self.settings_store.update_google_account_email(dialog.email_edit.text())
                save_google_password(LOCAL_PROFILE_ID, dialog.password_edit.text())
                self.session_description.setText(
                    "Automatic reconnect is ready. Its password is stored in Windows Credential Manager."
                )
        except (CredentialStoreError, ValueError) as error:
            QMessageBox.warning(self, "Automatic reconnect", str(error))

    def _session_capture_succeeded(self) -> None:
        self.settings_store.set_automation_status(
            "succeeded",
            "reconnected",
            "Google account reconnected. Retry the pending task if it is due.",
        )
        sync_schedule()
        self._refresh_session_status()
        self.session_description.setText(
            "Google is connected. The dedicated Chromium profile is saved locally on this PC."
        )

    def _session_capture_failed(self, message: str) -> None:
        self.session_description.setText("Could not save the Google session.")
        QMessageBox.warning(self, "Google sign-in failed", message)

    def _session_capture_finished(self) -> None:
        self.connect_button.setEnabled(True)

    def _remove_google_account(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Remove saved session?")
        dialog.setText(
            "This removes the dedicated Google Chromium profile from this PC. "
            "It does not affect your Google account."
        )
        remove_button = dialog.addButton(
            "Remove session", QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is not remove_button:
            return

        clear_local_auth_profile(LOCAL_PROFILE_ID)
        try:
            clear_google_password(LOCAL_PROFILE_ID)
        except CredentialStoreError:
            # The profile is still safely removed.  A later reconnect setup can
            # remove any remaining credential if Windows was temporarily busy.
            pass
        self.settings_store.update_google_account_email("")
        self.settings_store.clear_automation_status()
        if self.active_checkbox.isChecked():
            self.active_checkbox.setChecked(False)
        else:
            sync_schedule()
        self._refresh_session_status()

    def _save_settings(self, *_args) -> None:
        work_day = self.work_day_combo.currentData()
        automation_active = self.active_checkbox.isChecked()
        validation_message = ""

        if automation_active and work_day not in (1, 2, 3):
            validation_message = "Choose a work-day type before enabling automation."
            automation_active = False
        elif automation_active and not self._has_valid_session():
            validation_message = "Connect a Google account before enabling automation."
            automation_active = False

        if automation_active != self.active_checkbox.isChecked():
            self.active_checkbox.blockSignals(True)
            self.active_checkbox.setChecked(automation_active)
            self.active_checkbox.blockSignals(False)

        time_value = self.schedule_time.time()
        schedule_time = f"{time_value.hour():02d}:{time_value.minute():02d}"
        self.settings_store.update_automation_settings(
            work_day=work_day if work_day in (1, 2, 3) else None,
            automation_active=automation_active,
        )
        self.settings_store.update_schedule_time(schedule_time)
        sync_schedule()

        if validation_message:
            self.settings_message.setText(validation_message)
        elif automation_active:
            self.settings_message.setText(
                f"Saved. Weekday submissions are scheduled at {schedule_time}."
            )
        else:
            self.settings_message.setText(
                "Settings saved. Automatic submission is paused."
            )

    def _setup_tray(self) -> None:
        self.tray_icon: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(make_app_icon())
        self.tray_icon.setToolTip("Form Automation")

        menu = QMenu()
        show_action = QAction("Open Form Automation", self)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_application)
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()

    def _show_window(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()

    def _quit_application(self) -> None:
        self._allow_close = True
        if self.tray_icon:
            self.tray_icon.hide()
        self.close()

    def _retry_pending_task(self) -> None:
        if self.submission_worker and self.submission_worker.isRunning():
            return
        self.retry_button.setEnabled(False)
        self.ready_status.setText("Submitting pending form...")
        self.submission_worker = SubmissionWorker(retry=True, parent=self)
        self.submission_worker.completed.connect(self._refresh_runtime_status)
        self.submission_worker.finished.connect(
            lambda: self.retry_button.setEnabled(True)
        )
        self.submission_worker.start()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        if self.tray_icon and self.tray_icon.isVisible() and not self._allow_close:
            self.hide()
            self.tray_icon.showMessage(
                "Form Automation is still running",
                "The local schedule remains active in the system tray.",
            )
            event.ignore()
            return

        stop_scheduler()
        self.response_save_timer.stop()
        self._save_form_responses()
        event.accept()
        if self._allow_close or not self.tray_icon:
            QApplication.quit()


class MainWindow(_MainWindowBehavior):
    """Classic Windows desktop window, sharing the existing app actions."""

    def __init__(self) -> None:
        QMainWindow.__init__(self)
        self.settings_store = get_settings_store()
        self.session_worker: SessionCaptureWorker | None = None
        self.submission_worker: SubmissionWorker | None = None
        self.connection_test_worker: ConnectionTestWorker | None = None
        self._last_notified_status = None
        self._allow_close = False
        self.setWindowTitle("Weekday Form Automation")
        self.setWindowIcon(make_app_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(820, 640)
        self.resize(940, 720)
        self.setObjectName("mainWindow")
        self.ui_settings = QSettings(
            str(APP_DATA_DIRECTORY / "ui.ini"), QSettings.Format.IniFormat
        )

        self._build_interface()
        self._restore_window_geometry()
        self._load_settings()

        self.response_save_timer = QTimer(self)
        self.response_save_timer.setSingleShot(True)
        self.response_save_timer.setInterval(450)
        self.response_save_timer.timeout.connect(self._save_form_responses)
        for editor in self.form_response_editors.values():
            editor.textChanged.connect(self._queue_form_response_save)
        self.work_day_combo.currentIndexChanged.connect(self._save_settings)
        self.schedule_time.timeChanged.connect(self._save_settings)
        self.active_checkbox.toggled.connect(self._save_settings)
        self.settings_tabs.currentChanged.connect(self._adjust_window_for_tab)
        self._update_settings_message()

        self.geometry_save_timer = QTimer(self)
        self.geometry_save_timer.setSingleShot(True)
        self.geometry_save_timer.setInterval(300)
        self.geometry_save_timer.timeout.connect(self._save_window_geometry)
        self.escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.escape_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.escape_shortcut.activated.connect(self.close)

        self._refresh_session_status()
        self._refresh_status_bar()
        self._setup_tray()
        self.status_refresh_timer = QTimer(self)
        self.status_refresh_timer.setInterval(2000)
        self.status_refresh_timer.timeout.connect(self._refresh_runtime_status)
        self.status_refresh_timer.start()
        self.power_event_filter = WindowsPowerEventFilter()
        QApplication.instance().installNativeEventFilter(self.power_event_filter)
        start_scheduler()

    def _adjust_window_for_tab(self, index: int) -> None:
        # Calendar settings are saved per date by its own Save button.  Hiding
        # the global save there avoids two unrelated Save actions on one view.
        self.action_row.setVisible(index != 1)
        self.save_button.setVisible(index != 1)
        self.save_button.setDefault(index != 1)
        if self.isMaximized():
            return
        if index == 1:
            self.setMinimumSize(820, 480)
            self.resize(960, 500)
        else:
            self.setMinimumSize(820, 640)
            if self.height() < 640:
                self.resize(max(self.width(), 940), 720)

    def _build_interface(self) -> None:
        border = WindowBorder(self)
        self.setCentralWidget(border)
        border_layout = QVBoxLayout(border)
        border_layout.setContentsMargins(3, 3, 3, 3)
        border_layout.setSpacing(0)

        self.title_bar = ClassicTitleBar(self)
        border_layout.addWidget(self.title_bar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 6)
        content_layout.setSpacing(0)
        border_layout.addWidget(content, 1)

        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("settingsTabs")

        home_tab = QWidget()
        home_layout = QVBoxLayout(home_tab)
        home_layout.setContentsMargins(0, 0, 0, 0)
        home_layout.setSpacing(12)
        self._build_account_group(home_layout)
        self._build_schedule_group(home_layout)
        self._build_responses_group(home_layout)
        self.settings_tabs.addTab(home_tab, "Home")

        calendar_tab = QWidget()
        calendar_layout = QVBoxLayout(calendar_tab)
        calendar_layout.setContentsMargins(0, 0, 0, 0)
        self._build_calendar_group(calendar_layout)
        self.settings_tabs.addTab(calendar_tab, "Calendar")

        content_layout.addWidget(self.settings_tabs, 1)
        content_layout.addSpacing(8)
        self._build_action_row(content_layout)
        status_inset = QWidget()
        status_inset_layout = QHBoxLayout(status_inset)
        status_inset_layout.setContentsMargins(2, 2, 2, 2)
        status_inset_layout.setSpacing(0)
        self._build_status_bar(status_inset_layout)
        border_layout.addWidget(status_inset)
        self.setStyleSheet(CLASSIC_STYLESHEET.replace("MS Sans Serif", UI_FONT_FAMILY))

    def _build_account_group(self, parent_layout: QVBoxLayout) -> None:
        group = EtchedGroupBox("Google account")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(10, 23, 10, 10)
        layout.setSpacing(7)

        self.session_indicator = QFrame()
        self.session_indicator.setObjectName("sessionIndicator")
        self.session_indicator.setFixedSize(12, 12)
        layout.addWidget(self.session_indicator, 0, Qt.AlignmentFlag.AlignVCenter)

        self.session_description = QLabel()
        self.session_description.setObjectName("accountMessage")
        self.session_description.setWordWrap(True)
        layout.addWidget(self.session_description, 1)

        self.connect_button = ClassicButton("&Change Google Account...")
        self.connect_button.setAccessibleName("Change Google Account")
        self.connect_button.setFixedSize(154, 23)
        self.connect_button.clicked.connect(self._connect_google_account)
        layout.addWidget(self.connect_button)

        self.disconnect_button = ClassicButton("&Remove Saved Session")
        self.disconnect_button.setAccessibleName("Remove Saved Session")
        self.disconnect_button.setFixedSize(145, 23)
        self.disconnect_button.clicked.connect(self._remove_google_account)
        layout.addWidget(self.disconnect_button)
        self.automatic_reconnect_button = ClassicButton("Automatic reconnect...")
        self.automatic_reconnect_button.setAccessibleName("Configure automatic reconnect")
        self.automatic_reconnect_button.setFixedSize(151, 23)
        self.automatic_reconnect_button.clicked.connect(self._configure_automatic_reconnect)
        layout.addWidget(self.automatic_reconnect_button)
        self.connection_test_button = ClassicButton("Test connection")
        self.connection_test_button.setAccessibleName("Test form connection")
        self.connection_test_button.setFixedSize(118, 23)
        self.connection_test_button.clicked.connect(self._test_form_connection)
        layout.addWidget(self.connection_test_button)
        self.retry_button = ClassicButton("&Retry Pending Task")
        self.retry_button.setAccessibleName("Retry pending task")
        self.retry_button.setFixedSize(130, 23)
        self.retry_button.clicked.connect(self._retry_pending_task)
        self.retry_button.setEnabled(False)
        layout.addWidget(self.retry_button)
        parent_layout.addWidget(group)

    def _build_schedule_group(self, parent_layout: QVBoxLayout) -> None:
        group = EtchedGroupBox("Submission schedule")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 23, 10, 10)
        layout.setSpacing(10)

        description = QLabel(
            "Choose the form answer and the local time this PC should submit it."
        )
        layout.addWidget(description)

        fields = QHBoxLayout()
        fields.setSpacing(16)
        workday_column = QVBoxLayout()
        workday_column.setSpacing(3)
        self.work_day_label = QLabel("&Work-day type:")
        workday_column.addWidget(self.work_day_label)

        combo_frame = ClassicBevelFrame(sunken=True, fill=WHITE)
        combo_frame.setFixedHeight(21)
        combo_layout = QHBoxLayout(combo_frame)
        combo_layout.setContentsMargins(2, 2, 2, 2)
        combo_layout.setSpacing(0)
        self.work_day_combo = QComboBox()
        self.work_day_combo.setObjectName("workDayCombo")
        self.work_day_combo.setFrame(False)
        self.work_day_combo.setFixedHeight(17)
        self.work_day_combo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        combo_palette = self.work_day_combo.palette()
        combo_palette.setColor(combo_palette.ColorRole.Highlight, QColor("#0A246A"))
        combo_palette.setColor(combo_palette.ColorRole.HighlightedText, QColor(WHITE))
        self.work_day_combo.setPalette(combo_palette)
        self.work_day_combo.setMaxVisibleItems(len(WORK_DAY_CHOICES))
        for label, value in WORK_DAY_CHOICES:
            self.work_day_combo.addItem(label, value)
        self.work_day_combo.view().setStyleSheet(
            "QListView { color: #000000; background: #FFFFFF; "
            "border: 1px solid #404040; outline: none; padding: 1px; } "
            "QListView::item { min-height: 17px; padding: 1px 4px; } "
            "QListView::item:selected { color: #FFFFFF; "
            "background: #0A246A; }"
        )
        combo_layout.addWidget(self.work_day_combo, 1)
        self.work_day_arrow = ClassicButton("▼", glyph=True)
        self.work_day_arrow.setAccessibleName("Open work-day choices")
        self.work_day_arrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.work_day_arrow.setFixedSize(16, 17)
        self.work_day_arrow.clicked.connect(self.work_day_combo.showPopup)
        combo_layout.addWidget(self.work_day_arrow)
        workday_column.addWidget(combo_frame)
        self.work_day_label.setBuddy(self.work_day_combo)
        fields.addLayout(workday_column, 1)

        time_column = QVBoxLayout()
        time_column.setSpacing(3)
        self.schedule_time_label = QLabel("S&ubmission time:")
        time_column.addWidget(self.schedule_time_label)
        time_frame = ClassicBevelFrame(sunken=True, fill=WHITE)
        time_frame.setFixedSize(170, 21)
        time_layout = QHBoxLayout(time_frame)
        time_layout.setContentsMargins(2, 2, 2, 2)
        time_layout.setSpacing(1)
        self.schedule_time = QTimeEdit()
        self.schedule_time.setObjectName("scheduleTime")
        self.schedule_time.setButtonSymbols(QTimeEdit.ButtonSymbols.NoButtons)
        self.schedule_time.setFrame(False)
        self.schedule_time.setDisplayFormat("HH:mm")
        self.schedule_time.setTime(QTime.currentTime())
        self.schedule_time.setEnabled(True)
        self.schedule_time.setReadOnly(False)
        self.schedule_time.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        time_palette = self.schedule_time.palette()
        time_palette.setColor(time_palette.ColorRole.Base, QColor(WHITE))
        time_palette.setColor(time_palette.ColorRole.Text, QColor(BLACK))
        time_palette.setColor(time_palette.ColorRole.Window, QColor(WHITE))
        time_palette.setColor(time_palette.ColorRole.WindowText, QColor(BLACK))
        self.schedule_time.setPalette(time_palette)
        self.schedule_time.lineEdit().setPalette(time_palette)
        self.schedule_time.setMinimumWidth(80)
        self.schedule_time.setFixedHeight(17)
        time_layout.addWidget(self.schedule_time, 1)
        spin_column = QVBoxLayout()
        spin_column.setContentsMargins(0, 0, 0, 0)
        spin_column.setSpacing(0)
        self.time_up_button = ClassicButton("▲", glyph=True)
        self.time_up_button.setAccessibleName("Increase submission time")
        self.time_up_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.time_up_button.setFixedSize(15, 8)
        self.time_up_button.clicked.connect(lambda: self.schedule_time.stepBy(1))
        self.time_down_button = ClassicButton("▼", glyph=True)
        self.time_down_button.setAccessibleName("Decrease submission time")
        self.time_down_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.time_down_button.setFixedSize(15, 9)
        self.time_down_button.clicked.connect(lambda: self.schedule_time.stepBy(-1))
        spin_column.addWidget(self.time_up_button)
        spin_column.addWidget(self.time_down_button)
        time_layout.addLayout(spin_column)
        time_column.addWidget(time_frame)
        self.schedule_time_label.setBuddy(self.schedule_time)
        fields.addLayout(time_column)
        layout.addLayout(fields)

        self.active_checkbox = ClassicCheckBox(
            "&Enable Monday to Friday automation"
        )
        self.active_checkbox.setObjectName("activeCheckbox")
        layout.addWidget(self.active_checkbox)

        self.settings_message = QLabel()
        self.settings_message.setObjectName("settingsMessage")
        layout.addWidget(self.settings_message)
        parent_layout.addWidget(group)

    def _build_calendar_group(self, parent_layout: QVBoxLayout) -> None:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        calendar_group = EtchedGroupBox("Calendar overrides")
        calendar_layout = QVBoxLayout(calendar_group)
        calendar_layout.setContentsMargins(10, 23, 10, 10)
        calendar_layout.setSpacing(8)
        calendar_layout.addWidget(
            QLabel("Select a weekday to view or change its work-day type.")
        )
        self.calendar_view = OutlookCalendarWidget()
        self.calendar_view.setObjectName("calendarView")
        self.calendar_view.setMinimumSize(470, 330)
        self.calendar_view.dateSelected.connect(self._load_calendar_work_day)
        calendar_layout.addWidget(self.calendar_view, 0)
        calendar_layout.addWidget(
            QLabel("Yellow: campus holiday   Green: present   Red: leave or absent")
        )
        layout.addWidget(calendar_group, 1)

        details_group = EtchedGroupBox("Day details")
        details_group.setFixedWidth(290)
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(10, 23, 10, 10)
        details_layout.setSpacing(9)
        self.calendar_selected_date_label = QLabel()
        self.calendar_selected_date_label.setWordWrap(True)
        details_layout.addWidget(self.calendar_selected_date_label)
        details_layout.addWidget(QLabel("Work-day type:"))
        self.calendar_work_day_buttons = QButtonGroup(self)
        calendar_choices = [
            ("Use Home default", 0),
            ("Campus holiday", 1),
            ("Working day · present", 2),
            ("Working day · leave or absent", 3),
        ]
        for label, work_day in calendar_choices:
            radio = ClassicRadioButton(label)
            radio.setObjectName("calendarWorkDayOption")
            self.calendar_work_day_buttons.addButton(radio, work_day)
            details_layout.addWidget(radio)
        details_layout.addSpacing(6)
        details_layout.addWidget(QLabel("The Home tab is used when no override is saved."))
        details_layout.addStretch(1)

        actions = QHBoxLayout()
        self.save_calendar_override_button = ClassicButton("Save")
        self.save_calendar_override_button.setAccessibleName("Save calendar date")
        self.save_calendar_override_button.clicked.connect(self._save_calendar_work_day)
        actions.addWidget(self.save_calendar_override_button)
        self.clear_calendar_override_button = ClassicButton("Clear")
        self.clear_calendar_override_button.setAccessibleName("Clear calendar date")
        self.clear_calendar_override_button.clicked.connect(self._clear_calendar_work_day)
        actions.addWidget(self.clear_calendar_override_button)
        details_layout.addLayout(actions)

        self.calendar_override_status = QLabel()
        self.calendar_override_status.setObjectName("calendarOverrideStatus")
        self.calendar_override_status.setWordWrap(True)
        details_layout.addWidget(self.calendar_override_status)
        layout.addWidget(details_group)
        parent_layout.addLayout(layout)
        parent_layout.addStretch(1)

    def _build_responses_group(self, parent_layout: QVBoxLayout) -> None:
        group = EtchedGroupBox("Your responses")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 23, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(
            QLabel("Edit the four text answers the app fills in for each submission.")
        )

        response_grid = QGridLayout()
        response_grid.setHorizontalSpacing(16)
        response_grid.setVerticalSpacing(10)
        response_grid.setRowStretch(0, 1)
        response_grid.setRowStretch(1, 1)
        self.form_response_editors: dict[str, QPlainTextEdit] = {}
        self.form_response_labels: dict[str, QLabel] = {}
        response_fields = [
            ("&Key tasks:", "key_tasks"),
            ("&Challenges:", "challenges"),
            ("&How you handled them:", "challenge_resolution"),
            ("&Plan for tomorrow:", "tomorrow_plan"),
        ]
        for position, (label_text, key) in enumerate(response_fields):
            field = QWidget()
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(3)
            field.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            label = QLabel(label_text)
            label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            editor_frame = ClassicBevelFrame(
                sunken=True,
                fill=WHITE,
                preferred_height=72,
                minimum_height=52,
            )
            editor_frame.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            editor_layout = QVBoxLayout(editor_frame)
            editor_layout.setContentsMargins(2, 2, 2, 2)
            editor = QPlainTextEdit()
            editor.setObjectName("responseInput")
            editor.setAccessibleName(label_text.replace("&", "").rstrip(":"))
            editor.setFrameShape(QFrame.Shape.NoFrame)
            editor.setTabChangesFocus(False)
            editor.setMinimumHeight(48)
            editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            editor_layout.addWidget(editor)
            label.setBuddy(editor)
            field_layout.addWidget(label)
            field_layout.addWidget(editor_frame)
            field_layout.setStretch(1, 1)
            self.form_response_editors[key] = editor
            self.form_response_labels[key] = label
            response_grid.addWidget(field, position // 2, position % 2)
        layout.addLayout(response_grid)
        parent_layout.addWidget(group, 1)

    def _build_action_row(self, parent_layout: QVBoxLayout) -> None:
        self.action_row = QWidget()
        actions = QHBoxLayout(self.action_row)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        self.save_button = ClassicButton("&Save")
        self.save_button.setAccessibleName("Save settings")
        self.save_button.setMinimumSize(80, 23)
        self.save_button.setMaximumSize(80, 23)
        self.save_button.setDefault(True)
        self.save_button.setAutoDefault(True)
        self.save_button.clicked.connect(self._save_all)
        actions.addWidget(self.save_button)
        self.close_button = ClassicButton("&Close")
        self.close_button.setAccessibleName("Close window")
        self.close_button.setMinimumSize(80, 23)
        self.close_button.setMaximumSize(80, 23)
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        parent_layout.addWidget(self.action_row)

    def _build_status_bar(self, parent_layout: QVBoxLayout) -> None:
        status = QWidget()
        status.setFixedHeight(22)
        layout = QHBoxLayout(status)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.ready_status = StatusPanel("Ready")
        layout.addWidget(self.ready_status, 1)
        self.automation_status = StatusPanel("Automation: Paused")
        self.automation_status.setMinimumWidth(130)
        layout.addWidget(self.automation_status)
        self.local_status = StatusPanel("Local only")
        self.local_status.setMinimumWidth(75)
        layout.addWidget(self.local_status)
        self.session_status = StatusPanel("Session not saved", grip=True)
        self.session_status.setMinimumWidth(120)
        layout.addWidget(self.session_status)
        parent_layout.addWidget(status)

    def _refresh_session_status(self) -> None:
        runtime_status = self.settings_store.get_settings()["automation_status"]
        session_error = runtime_status and runtime_status["code"] in (
            "session_expired",
            "session_required",
        )
        connected = self._has_valid_session() and not session_error
        self.session_indicator.setStyleSheet(
            "background-color: #008000; border: 1px solid #004000;"
            if connected
            else "background-color: #800000; border: 1px solid #400000;"
        )
        if connected:
            self.session_description.setText(
                "Google account connected. The dedicated Chromium profile is stored locally on this PC."
            )
            self.disconnect_button.setEnabled(True)
        elif session_error:
            self.session_description.setText(runtime_status["message"])
            self.disconnect_button.setEnabled(self._has_valid_session())
        else:
            self.session_description.setText(
                "No connected Google profile. Change Google Account to connect."
            )
            self.disconnect_button.setEnabled(False)
        self._refresh_status_bar()

    def _refresh_status_bar(self) -> None:
        active = self.active_checkbox.isChecked()
        runtime_status = self.settings_store.get_settings()["automation_status"]
        if runtime_status:
            state_text = {
                "submitting": "Submitting...",
                "succeeded": "Submitted",
                "error": "Needs attention",
            }[runtime_status["state"]]
            self.automation_status.setText(f"Automation: {state_text}")
            self.ready_status.setText(runtime_status["message"])
        else:
            self.automation_status.setText(
                "Automation: Active" if active else "Automation: Paused"
            )
        self.session_status.setText(
            "Reconnect required"
            if runtime_status and runtime_status["code"] in ("session_expired", "session_required")
            else "Profile saved" if self._has_valid_session() else "Session not saved"
        )
        self.retry_button.setEnabled(
            bool(
                runtime_status
                and runtime_status["code"]
                in ("session_expired", "form_error", "submission_error", "reconnected")
                and self._has_valid_session()
                and self.settings_store.get_settings()["pending_task"]
            )
        )

    def _refresh_runtime_status(self) -> None:
        runtime_status = self.settings_store.get_settings()["automation_status"]
        status_key = (
            runtime_status["state"],
            runtime_status["code"],
            runtime_status["updated_at"],
        ) if runtime_status else None
        self._refresh_session_status()
        if runtime_status and runtime_status["state"] == "error":
            self.settings_message.setText(runtime_status["message"])
            if status_key != self._last_notified_status and self.tray_icon:
                self.tray_icon.showMessage(
                    "Form Automation needs attention",
                    runtime_status["message"],
                    QSystemTrayIcon.MessageIcon.Warning,
                )
        self._last_notified_status = status_key

    def _save_settings(self, *_args) -> None:
        super()._save_settings(*_args)
        if not (
            self.settings_message.text().startswith("Choose a work-day")
            or self.settings_message.text().startswith("Connect a Google")
        ):
            self._update_settings_message()
        self._refresh_status_bar()

    def _save_form_responses(self) -> None:
        responses = {
            key: editor.toPlainText()
            for key, editor in self.form_response_editors.items()
        }
        self.settings_store.update_form_responses(responses)
        self._update_settings_message()

    def _save_all(self) -> None:
        self.response_save_timer.stop()
        self._save_form_responses()
        self._save_settings()
        self.ready_status.setText("Ready")

    def _update_settings_message(self) -> None:
        runtime_status = self.settings_store.get_settings()["automation_status"]
        if runtime_status and runtime_status["state"] == "error":
            self.settings_message.setText(runtime_status["message"])
            return
        time_value = self.schedule_time.time()
        schedule_time = f"{time_value.hour():02d}:{time_value.minute():02d}"
        if self.active_checkbox.isChecked():
            self.settings_message.setText(
                f"Settings saved. Weekday submissions are scheduled at {schedule_time}."
            )
        else:
            self.settings_message.setText(
                "Settings saved. Automatic submission is paused."
            )

    def _restore_window_geometry(self) -> None:
        geometry = self.ui_settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def _save_window_geometry(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.ui_settings.setValue("window/geometry", self.saveGeometry())
            self.ui_settings.sync()

    def moveEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().moveEvent(event)
        if hasattr(self, "geometry_save_timer"):
            self.geometry_save_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        if hasattr(self, "geometry_save_timer"):
            self.geometry_save_timer.start()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API name
        self._save_window_geometry()
        if self.tray_icon and self.tray_icon.isVisible() and not self._allow_close:
            self.hide()
            self.tray_icon.showMessage(
                "Form Automation is still running",
                "The local schedule remains active in the system tray.",
            )
            event.ignore()
            return

        stop_scheduler()
        self.response_save_timer.stop()
        self._save_form_responses()
        event.accept()
        if self._allow_close or not self.tray_icon:
            QApplication.quit()


CLASSIC_STYLESHEET = """
QMainWindow#mainWindow, QWidget { color: #000000; background-color: #D4D0C8;
    font-family: "MS Sans Serif", "Microsoft Sans Serif", Arial, sans-serif; font-size: 8pt;
}
QLabel { background: transparent; }
QGroupBox { color: #000000; }
QComboBox#workDayCombo {
    color: #000000; background: #FFFFFF; border: none;
    padding-left: 4px; padding-right: 0px;
    selection-background-color: #0A246A; selection-color: #FFFFFF;
}
QComboBox#workDayCombo::drop-down {
    width: 0px; border: none; subcontrol-origin: padding;
}
QComboBox#workDayCombo::down-arrow {
    image: none; width: 0px; height: 0px;
}
QPlainTextEdit#responseInput {
    color: #000000; background: #FFFFFF; border: none; padding: 2px;
    selection-background-color: #000080; selection-color: #FFFFFF;
}
QComboBox#workDayCombo QAbstractItemView {
    color: #000000; background: #FFFFFF; border: 1px solid #404040;
    selection-color: #FFFFFF; selection-background-color: #0A246A;
    outline: none; padding: 1px;
}
QLabel#statusText {
    color: #000000; background: transparent; padding: 0px;
}
QTabWidget#settingsTabs::pane {
    border-top: 1px solid #FFFFFF; border-left: 1px solid #FFFFFF;
    border-right: 1px solid #404040; border-bottom: 1px solid #404040;
    background: #D4D0C8; top: -1px;
}
QTabWidget#settingsTabs QTabBar::tab {
    background: #D4D0C8; color: #000000; min-width: 52px;
    padding: 3px 12px 4px 12px; margin-right: 2px;
    border-top: 1px solid #FFFFFF; border-left: 1px solid #FFFFFF;
    border-right: 1px solid #404040;
}
QTabWidget#settingsTabs QTabBar::tab:selected {
    font-weight: bold; padding-top: 5px; margin-top: -2px;
    border-bottom: 1px solid #D4D0C8;
}
QTableWidget#outlookCalendarGrid {
    background: #FFFFFF; color: #000000;
    border-top: 2px solid #404040; border-left: 2px solid #404040;
    border-right: 2px solid #FFFFFF; border-bottom: 2px solid #FFFFFF;
    gridline-color: #D4D0C8;
}
QTableWidget#outlookCalendarGrid QHeaderView::section {
    background: #D4D0C8; color: #000000; padding: 3px 2px;
    border-top: 1px solid #FFFFFF; border-left: 1px solid #FFFFFF;
    border-right: 1px solid #808080; border-bottom: 1px solid #808080;
}
"""


def main() -> None:
    APP_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=APP_DATA_DIRECTORY / "form-automation.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )
    configure_playwright_browser_path()
    try:
        enable_windows_startup()
    except OSError:
        logging.getLogger(__name__).exception(
            "Could not register Form Automation to start at Windows sign-in"
        )

    application = QApplication(sys.argv)
    application.setApplicationName("Weekday Form Automation")
    application.setWindowIcon(make_app_icon())
    application.setQuitOnLastWindowClosed(False)
    _configure_font(application)
    window = MainWindow()
    window.show()
    sys.exit(application.exec())


def _configure_font(application: QApplication) -> None:
    global UI_FONT_FAMILY
    available = set(QFontDatabase.families())
    for preferred in ("MS Sans Serif", "Microsoft Sans Serif", "Arial"):
        if preferred in available:
            UI_FONT_FAMILY = preferred
            break
    else:
        microsoft_sans = Path("C:/Windows/Fonts/micross.ttf")
        if microsoft_sans.is_file():
            font_id = QFontDatabase.addApplicationFont(str(microsoft_sans))
            loaded_families = QFontDatabase.applicationFontFamilies(font_id)
            if loaded_families:
                UI_FONT_FAMILY = loaded_families[0]
        elif "Arial" in available:
            UI_FONT_FAMILY = "Arial"
        else:
            UI_FONT_FAMILY = "MS Sans Serif"

    font = QFont(UI_FONT_FAMILY)
    font.setPointSize(8)
    application.setFont(font)


if __name__ == "__main__":
    main()
