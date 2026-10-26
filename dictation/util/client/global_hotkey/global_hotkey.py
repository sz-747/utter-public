# coding: utf-8
"""
Global hotkey manager.

Listens for global hotkeys with pynput GlobalHotKeys, replacing the keyboard library.

Example:
    from util.client.global_hotkey import GlobalHotkeyManager

    manager = GlobalHotkeyManager()
    manager.register('<esc>', lambda: print('ESC pressed'))
    manager.start()
"""
from __future__ import annotations

import threading
from typing import Callable, Dict, Optional

from pynput import keyboard

from . import logger



class GlobalHotkeyManager:
    """
    Global hotkey manager.

    Built on pynput GlobalHotKeys; hotkeys can be registered and unregistered at runtime.

    Advantages over the keyboard library:
    - Works alongside the rest of pynput
    - No extra dependency
    - Better cross-platform support
    """

    # Singleton instance
    _instance: Optional['GlobalHotkeyManager'] = None
    _lock = threading.Lock()

    def __new__(cls) -> 'GlobalHotkeyManager':
        """Singleton."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._hotkeys: Dict[str, Callable] = {}
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self._running = False
        self._initialized = True
        logger.debug("GlobalHotkeyManager initialized")

    def register(self, key_str: str, callback: Callable) -> None:
        """
        Register a global hotkey.

        Args:
            key_str: hotkey string in pynput format, e.g. '<esc>', '<ctrl>+<alt>+h'
            callback: function called when the hotkey is pressed
        """
        self._hotkeys[key_str] = callback
        logger.debug(f"Registered global hotkey: {key_str}")

        # If already running, restart the listener to apply the new hotkey
        if self._running:
            self._restart_listener()

    def unregister(self, key_str: str) -> bool:
        """
        Unregister a global hotkey.

        Args:
            key_str: hotkey string

        Returns:
            whether the hotkey was unregistered
        """
        if key_str in self._hotkeys:
            del self._hotkeys[key_str]
            logger.debug(f"Unregistered global hotkey: {key_str}")

            if self._running:
                self._restart_listener()
            return True
        return False

    def start(self) -> None:
        """Start listening for hotkeys."""
        if self._running:
            logger.debug("GlobalHotkeyManager is already running")
            return

        if not self._hotkeys:
            logger.warning("No hotkeys registered, not starting")
            return

        self._running = True
        self._start_listener()
        logger.info(f"GlobalHotkeyManager started with {len(self._hotkeys)} hotkey(s)")

    def stop(self) -> None:
        """Stop listening for hotkeys."""
        self._running = False
        if self._listener:
            try:
                self._listener.stop()
            except Exception as e:
                logger.warning(f"Error stopping the GlobalHotKeys listener: {e}")
            self._listener = None
        logger.info("GlobalHotkeyManager stopped")

    def _start_listener(self) -> None:
        """Start the listener."""
        if not self._hotkeys:
            return

        try:
            self._listener = keyboard.GlobalHotKeys(self._hotkeys)
            self._listener.start()
            logger.debug(f"GlobalHotKeys listener started: {list(self._hotkeys.keys())}")
        except Exception as e:
            logger.error(f"Could not start the GlobalHotKeys listener: {e}")
            self._listener = None

    def _restart_listener(self) -> None:
        """Restart the listener (after the hotkeys change)."""
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

        if self._running and self._hotkeys:
            self._start_listener()


# Global singleton
_global_hotkey_manager: Optional[GlobalHotkeyManager] = None


def get_global_hotkey_manager() -> GlobalHotkeyManager:
    """Get the global hotkey manager singleton."""
    global _global_hotkey_manager
    if _global_hotkey_manager is None:
        _global_hotkey_manager = GlobalHotkeyManager()
    return _global_hotkey_manager
