import logging
import sys
from pathlib import Path

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QThread,
    QTime,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QCloseEvent, QFont, QFontDatabase, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QStyle,
    QSystemTrayIcon,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings_store = get_settings_store()
        self.session_worker: SessionCaptureWorker | None = None
        self._allow_close = False

        self.setWindowTitle("Form Automation")
        self.setMinimumSize(780, 700)
        self.resize(930, 900)
        self.setObjectName("mainWindow")

        self._build_interface()
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
        self._refresh_session_status()
        self._setup_tray()
        self.power_event_filter = WindowsPowerEventFilter()
        QApplication.instance().installNativeEventFilter(self.power_event_filter)
        start_scheduler()

    def _build_interface(self) -> None:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("contentScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        page = QWidget()
        page.setObjectName("page")
        scroll_area.setWidget(page)
        self.setCentralWidget(scroll_area)

        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(40, 36, 40, 36)
        page_layout.setSpacing(20)

        header = QHBoxLayout()
        heading_group = QVBoxLayout()
        title = QLabel("Weekday form automation")
        title.setObjectName("pageTitle")
        subtitle = QLabel("A private, on-device routine for your daily form.")
        subtitle.setObjectName("pageSubtitle")
        heading_group.addWidget(title)
        heading_group.addWidget(subtitle)
        header.addLayout(heading_group)
        header.addStretch(1)

        local_badge = QLabel("●  LOCAL ONLY")
        local_badge.setObjectName("localBadge")
        header.addWidget(local_badge, 0, Qt.AlignmentFlag.AlignTop)
        page_layout.addLayout(header)

        account_card, account_layout = self._make_card()
        account_header = QHBoxLayout()
        account_title = QLabel("Google account")
        account_title.setObjectName("sectionTitle")
        account_header.addWidget(account_title)
        account_header.addStretch(1)
        self.session_badge = QLabel()
        self.session_badge.setObjectName("statusBadge")
        account_header.addWidget(self.session_badge)
        account_layout.addLayout(account_header)

        self.session_description = QLabel()
        self.session_description.setObjectName("sectionDescription")
        self.session_description.setWordWrap(True)
        account_layout.addWidget(self.session_description)

        account_actions = QHBoxLayout()
        self.connect_button = QPushButton("Connect Google account")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._connect_google_account)
        account_actions.addWidget(self.connect_button)
        self.disconnect_button = QPushButton("Remove saved session")
        self.disconnect_button.setObjectName("secondaryButton")
        self.disconnect_button.clicked.connect(self._remove_google_account)
        account_actions.addWidget(self.disconnect_button)
        account_actions.addStretch(1)
        account_layout.addLayout(account_actions)
        page_layout.addWidget(account_card)

        schedule_card, schedule_layout = self._make_card()
        schedule_title = QLabel("Submission schedule")
        schedule_title.setObjectName("sectionTitle")
        schedule_layout.addWidget(schedule_title)
        schedule_description = QLabel(
            "Choose the form answer and the local time this PC should submit it."
        )
        schedule_description.setObjectName("sectionDescription")
        schedule_description.setWordWrap(True)
        schedule_layout.addWidget(schedule_description)

        fields = QHBoxLayout()
        fields.setSpacing(18)
        workday_column = QVBoxLayout()
        workday_label = QLabel("Work-day type")
        workday_label.setObjectName("fieldLabel")
        workday_column.addWidget(workday_label)
        self.work_day_combo = QComboBox()
        self.work_day_combo.setObjectName("input")
        self.work_day_combo.setMaxVisibleItems(len(WORK_DAY_CHOICES))
        for label, value in WORK_DAY_CHOICES:
            self.work_day_combo.addItem(label, value)
        workday_column.addWidget(self.work_day_combo)
        fields.addLayout(workday_column, 2)

        time_column = QVBoxLayout()
        time_label = QLabel("Submission time")
        time_label.setObjectName("fieldLabel")
        time_column.addWidget(time_label)
        self.schedule_time = QTimeEdit()
        self.schedule_time.setObjectName("input")
        self.schedule_time.setDisplayFormat("HH:mm")
        self.schedule_time.setTime(QTime.currentTime())
        time_column.addWidget(self.schedule_time)
        fields.addLayout(time_column, 1)
        schedule_layout.addLayout(fields)

        self.active_checkbox = QCheckBox("Enable Monday to Friday automation")
        self.active_checkbox.setObjectName("activeCheckbox")
        schedule_layout.addWidget(self.active_checkbox)

        self.settings_message = QLabel()
        self.settings_message.setObjectName("inlineMessage")
        self.settings_message.setWordWrap(True)
        schedule_layout.addWidget(self.settings_message)
        page_layout.addWidget(schedule_card)

        response_card, response_layout = self._make_card()
        response_header = QHBoxLayout()
        response_title = QLabel("Your responses")
        response_title.setObjectName("sectionTitle")
        response_header.addWidget(response_title)
        response_header.addStretch(1)
        response_saved_label = QLabel("SAVED LOCALLY")
        response_saved_label.setObjectName("localBadge")
        response_header.addWidget(response_saved_label)
        response_layout.addLayout(response_header)

        response_description = QLabel(
            "Edit the four text answers the app fills in for each submission."
        )
        response_description.setObjectName("sectionDescription")
        response_description.setWordWrap(True)
        response_layout.addWidget(response_description)

        response_grid = QGridLayout()
        response_grid.setHorizontalSpacing(16)
        response_grid.setVerticalSpacing(12)
        self.form_response_editors: dict[str, QPlainTextEdit] = {}
        response_fields = [
            ("Key tasks", "key_tasks", "What did you work on today?"),
            ("Challenges", "challenges", "What challenges came up?"),
            (
                "How you handled them",
                "challenge_resolution",
                "How did you address those challenges?",
            ),
            ("Plan for tomorrow", "tomorrow_plan", "What will you work on next?"),
        ]
        for position, (label_text, key, placeholder) in enumerate(response_fields):
            field = QVBoxLayout()
            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            editor = QPlainTextEdit()
            editor.setObjectName("responseInput")
            editor.setAccessibleName(label_text)
            editor.setPlaceholderText(placeholder)
            editor.setFixedHeight(78)
            field.addWidget(label)
            field.addWidget(editor)
            self.form_response_editors[key] = editor
            response_grid.addLayout(field, position // 2, position % 2)
        response_layout.addLayout(response_grid)
        response_hint = QLabel("Changes save automatically on this PC.")
        response_hint.setObjectName("inlineMessage")
        response_layout.addWidget(response_hint)
        page_layout.addWidget(response_card)

        info_card, info_layout = self._make_card()
        info_title = QLabel("Runs from this computer")
        info_title.setObjectName("sectionTitle")
        info_layout.addWidget(info_title)
        info_text = QLabel(
            "Minimize to the system tray to keep the schedule active. "
            "At submission time, Chromium opens on this PC and completes the form. "
            "If the PC sleeps through the schedule, one queued task runs after wake "
            "if it is still the same day. After midnight, that task expires."
        )
        info_text.setObjectName("sectionDescription")
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        page_layout.addWidget(info_card)
        page_layout.addStretch(1)

        self.setStyleSheet(STYLESHEET)
        self.work_day_combo.view().setStyleSheet(
            "QListView { color: #202124; background-color: #ffffff; "
            "border: 1px solid #dadce0; outline: 0; font-family: 'Lebron', 'Segoe UI', sans-serif; font-size: 15px; } "
            "QListView::item { color: #202124; padding: 10px 14px; "
            "min-height: 28px; } "
            "QListView::item:selected { color: #ffffff; "
            "background-color: #1a73e8; }"
        )

    @staticmethod
    def _make_card() -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        card.setGraphicsEffect(shadow)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        return card, layout

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
        self.tray_icon.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        )
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


STYLESHEET = """
QMainWindow#mainWindow { background: #f8f9fa; }
QScrollArea#contentScroll, QWidget#page { background: #f8f9fa; }
QLabel#pageTitle {
    color: #202124; font-family: "Lebron", "Segoe UI", sans-serif; font-size: 28px; font-weight: 600;
}
QLabel#pageSubtitle { color: #5f6368; font-family: "Lebron", "Segoe UI", sans-serif; font-size: 15px; }
QLabel#localBadge {
    color: #188038; background: #e6f4ea; border: 1px solid #ceead6;
    border-radius: 12px; padding: 6px 12px; font-size: 12px; font-weight: bold;
    font-family: "Lebron", "Segoe UI", sans-serif;
}
QFrame#card {
    background: #ffffff; border: 1px solid #dadce0; border-radius: 12px;
}
QLabel#sectionTitle { color: #202124; font-size: 18px; font-weight: 600; font-family: "Lebron", "Segoe UI", sans-serif; }
QLabel#sectionDescription { color: #5f6368; font-size: 14px; line-height: 1.5; font-family: "Lebron", "Segoe UI", sans-serif; }
QLabel#fieldLabel { color: #3c4043; font-size: 14px; font-weight: 600; font-family: "Lebron", "Segoe UI", sans-serif; }
QLabel#statusBadge[connected="true"] {
    color: #188038; background: #e6f4ea; border-radius: 12px;
    padding: 6px 12px; font-size: 11px; font-weight: bold; font-family: "Lebron", "Segoe UI", sans-serif;
}
QLabel#statusBadge[connected="false"] {
    color: #b06000; background: #fef7e0; border-radius: 12px;
    padding: 6px 12px; font-size: 11px; font-weight: bold; font-family: "Lebron", "Segoe UI", sans-serif;
}
QComboBox#input, QTimeEdit#input {
    color: #202124; background: #ffffff; border: 1px solid #dadce0;
    border-radius: 6px; padding: 10px 14px; min-height: 24px; font-size: 15px; font-family: "Lebron", "Segoe UI", sans-serif;
}
QComboBox#input:focus, QTimeEdit#input:focus { border: 2px solid #1a73e8; padding: 9px 13px; outline: none; }
QPlainTextEdit#responseInput {
    color: #202124; background: #ffffff; border: 1px solid #dadce0;
    border-radius: 6px; padding: 12px; selection-background-color: #e8f0fe; font-size: 15px; font-family: "Lebron", "Segoe UI", sans-serif;
}
QPlainTextEdit#responseInput:focus { border: 2px solid #1a73e8; padding: 11px; outline: none; }
QCheckBox#activeCheckbox { color: #202124; font-size: 15px; spacing: 12px; font-family: "Lebron", "Segoe UI", sans-serif; }
QPushButton#primaryButton {
    color: white; background: #1a73e8; border: none; border-radius: 6px;
    padding: 12px 24px; font-size: 15px; font-weight: 600; font-family: "Lebron", "Segoe UI", sans-serif;
}
QPushButton#primaryButton:hover { background: #1765cc; }
QPushButton#primaryButton:focus { background: #1765cc; outline: 2px solid #185abc; outline-offset: 2px; }
QPushButton#primaryButton:disabled { color: #ffffff; background: #8ab4f8; }
QPushButton#secondaryButton {
    color: #1a73e8; background: #ffffff; border: 1px solid #dadce0;
    border-radius: 6px; padding: 11px 24px; font-size: 15px; font-weight: 600; font-family: "Lebron", "Segoe UI", sans-serif;
}
QPushButton#secondaryButton:hover { background: #f8f9fa; border: 1px solid #d2e3fc; }
QPushButton#secondaryButton:focus { background: #f8f9fa; outline: 2px solid #1a73e8; outline-offset: 2px; }
QPushButton#secondaryButton:disabled { color: #80868b; border: 1px solid #f1f3f4; }
QLabel#inlineMessage { color: #5f6368; font-size: 14px; font-family: "Lebron", "Segoe UI", sans-serif; }
QScrollBar:vertical { width: 12px; background: transparent; margin: 0px; }
QScrollBar::handle:vertical { background: #dadce0; border-radius: 6px; min-height: 40px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: #bdc1c6; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
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
    application.setApplicationName("Form Automation")
    application.setQuitOnLastWindowClosed(False)
    _configure_font(application)
    window = MainWindow()
    window.show()
    sys.exit(application.exec())


def _configure_font(application: QApplication) -> None:
    # Set to Lebron as requested, with fallback automatically handled by Qt
    application.setFont(QFont("Lebron", 11))


if __name__ == "__main__":
    main()
