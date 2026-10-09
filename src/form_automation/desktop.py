import logging
import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QByteArray,
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
    QComboBox,
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
    QSystemTrayIcon,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from .local_auth_state import (
    clear_local_auth_state,
    get_local_auth_state,
    has_local_auth_state,
)
from .local_paths import APP_DATA_DIRECTORY, LOCAL_PROFILE_ID
from .local_settings import get_settings_store
from .power_events import notify_scheduler_on_resume
from .runtime import configure_playwright_browser_path
from .scheduler import (
    start_scheduler,
    stop_scheduler,
    sync_schedule,
    wakeup_scheduler,
)
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
UI_FONT_FAMILY = "MS Sans Serif"


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


class WindowsPowerEventFilter(QAbstractNativeEventFilter):
    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            notify_scheduler_on_resume(message, wakeup_scheduler)
        return False, 0


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
        if not has_local_auth_state(LOCAL_PROFILE_ID):
            return False
        try:
            return get_local_auth_state(LOCAL_PROFILE_ID) is not None
        except RuntimeError:
            return False

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

    def _session_capture_succeeded(self) -> None:
        self._refresh_session_status()
        self.session_description.setText(
            "Google is connected. The encrypted session is saved locally on this PC."
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
            "This removes the encrypted Google session from this PC. "
            "It does not affect your Google account."
        )
        remove_button = dialog.addButton(
            "Remove session", QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is not remove_button:
            return

        clear_local_auth_state(LOCAL_PROFILE_ID)
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
        self.power_event_filter = WindowsPowerEventFilter()
        QApplication.instance().installNativeEventFilter(self.power_event_filter)
        start_scheduler()

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

        self._build_account_group(content_layout)
        content_layout.addSpacing(12)
        self._build_schedule_group(content_layout)
        content_layout.addSpacing(12)
        self._build_responses_group(content_layout)
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
        actions = QHBoxLayout()
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
        parent_layout.addLayout(actions)

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
        connected = self._has_valid_session()
        self.session_indicator.setStyleSheet(
            "background-color: #008000; border: 1px solid #004000;"
            if connected
            else "background-color: #808080; border: 1px solid #404040;"
        )
        if connected:
            self.session_description.setText(
                "Session saved. The encrypted Google session is stored in this PC's local app data."
            )
            self.disconnect_button.setEnabled(True)
        else:
            self.session_description.setText(
                "No saved Google session. Change Google Account to connect."
            )
            self.disconnect_button.setEnabled(False)
        self._refresh_status_bar()

    def _refresh_status_bar(self) -> None:
        active = self.active_checkbox.isChecked()
        connected = self._has_valid_session()
        self.automation_status.setText(
            "Automation: Active" if active else "Automation: Paused"
        )
        self.session_status.setText(
            "Session saved" if connected else "Session not saved"
        )

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
