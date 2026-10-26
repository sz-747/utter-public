"""UI utilities

Provides floating toast notifications and the system tray icon.
The client injects its logger when it loads them.
"""
import logging
from typing import Any

# ============================================================
# Logger proxy
# ============================================================

class _LoggerProxy:
    """
    Logger proxy (forwards attribute access with __getattr__).
    Lets modules import the logger now and receive the real one later.
    """
    def __init__(self):
        self._target = logging.getLogger('util.ui')  # Default logger

    def set_target(self, logger):
        """Inject the real logger"""
        self._target = logger

    def __getattr__(self, name):
        """Forward every attribute access to the real logger"""
        return getattr(self._target, name)

# 1. Create the proxy instance
logger = _LoggerProxy()

def set_ui_logger(real_logger):
    """Set the logger the UI modules use"""
    logger.set_target(real_logger)

# ============================================================
# Exports
# ============================================================

from .toast import toast, toast_stream, ToastMessage, ToastMessageManager
from .tray import enable_min_to_tray, stop_tray

__all__ = [
    'logger',
    'set_ui_logger',
    'toast',
    'toast_stream',
    'ToastMessage',
    'ToastMessageManager',
    'enable_min_to_tray',
    'stop_tray',
]
