import ctypes
import unittest
from unittest.mock import Mock

from shiboken6 import VoidPtr

from form_automation.power_events import (
    PBT_APMRESUMEAUTOMATIC,
    PBT_APMRESUMESUSPEND,
    WM_POWERBROADCAST,
    _WindowsMessage,
    notify_scheduler_on_resume,
)


class PowerEventTests(unittest.TestCase):
    def make_message(self, message_id: int, event_code: int) -> _WindowsMessage:
        message = _WindowsMessage()
        message.message = message_id
        message.wParam = event_code
        return message

    def test_resume_event_wakes_scheduler(self) -> None:
        wake_scheduler = Mock()
        message = self.make_message(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC)

        handled = notify_scheduler_on_resume(
            VoidPtr(ctypes.addressof(message)), wake_scheduler
        )

        self.assertTrue(handled)
        wake_scheduler.assert_called_once_with()

    def test_user_resume_event_wakes_scheduler(self) -> None:
        wake_scheduler = Mock()
        message = self.make_message(WM_POWERBROADCAST, PBT_APMRESUMESUSPEND)

        handled = notify_scheduler_on_resume(
            ctypes.addressof(message), wake_scheduler
        )

        self.assertTrue(handled)
        wake_scheduler.assert_called_once_with()

    def test_non_resume_power_event_does_not_wake_scheduler(self) -> None:
        wake_scheduler = Mock()
        message = self.make_message(WM_POWERBROADCAST, 0x0004)

        handled = notify_scheduler_on_resume(
            ctypes.addressof(message), wake_scheduler
        )

        self.assertFalse(handled)
        wake_scheduler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
