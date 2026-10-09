import ctypes
from collections.abc import Callable

WM_POWERBROADCAST = 0x0218
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMESUSPEND = 0x0007


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _WindowsMessage(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt", _Point),
    ]


def notify_scheduler_on_resume(
    message_pointer: object, wake_scheduler: Callable[[], None]
) -> bool:
    """Wake APScheduler when Windows reports that the computer resumed."""
    message = ctypes.cast(
        ctypes.c_void_p(int(message_pointer)), ctypes.POINTER(_WindowsMessage)
    ).contents
    if message.message != WM_POWERBROADCAST or message.wParam not in (
        PBT_APMRESUMEAUTOMATIC,
        PBT_APMRESUMESUSPEND,
    ):
        return False

    wake_scheduler()
    return True
