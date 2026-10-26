# coding: utf-8
"""
Shortcut manager.

Manages every configured shortcut and handles keyboard and mouse events:
1. Several shortcuts can be active at once
2. Different keys do not interfere with each other
3. Restoring a toggle key does not get captured by our own listener
4. Supports both hold_mode and click mode
"""
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Dict, List, Optional

from pynput import keyboard, mouse

from . import logger
from util.client.shortcut.key_mapper import *
from util.client.shortcut.key_mapper import KeyMapper
from util.client.shortcut.emulator import ShortcutEmulator
from util.client.shortcut.event_handler import ShortcutEventHandler
from util.client.shortcut.task import ShortcutTask
from util.client.output import joiner

if TYPE_CHECKING:
    from util.client.shortcut.shortcut_config import Shortcut
    from util.client.state import ClientState



class ShortcutManager:
    """
    Shortcut manager.

    Listens to keyboard and mouse events with pynput for all shortcuts.
    All event handling happens inside win32_event_filter to keep latency low.
    """

    def __init__(self, state: 'ClientState', shortcuts: List['Shortcut']):
        """
        Set up the shortcut manager.

        Args:
            state: client state instance
            shortcuts: list of shortcut configurations
        """
        self.state = state
        self.shortcuts = shortcuts

        # Listeners
        self.keyboard_listener: Optional[keyboard.Listener] = None
        self.mouse_listener: Optional[mouse.Listener] = None

        # Shortcut tasks (key -> ShortcutTask)
        self.tasks: Dict[str, ShortcutTask] = {}

        # Thread pool
        self._pool = ThreadPoolExecutor(max_workers=4)

        # Key emulator
        self._emulator = ShortcutEmulator()

        # Keys currently being restored
        self._restoring_keys = set()

        # Event handler
        self._event_handler = ShortcutEventHandler(self.tasks, self._pool, self._emulator)

        # Double-tap detection for the LLM cleanup toggle
        from config_client import ClientConfig as Config
        self._llm_toggle_key = getattr(Config, 'llm_toggle_key', None)
        self._llm_toggle_window = getattr(Config, 'llm_toggle_double_tap_window', 0.4)
        self._llm_toggle_last_press = 0.0
        self._llm_toggle_held = False  # tells auto-repeat KEYDOWN apart from a real new press

        # Create the shortcut tasks
        self._init_tasks()

    def _init_tasks(self) -> None:
        """Create a task for every enabled shortcut."""
        from config_client import ClientConfig as Config

        for shortcut in self.shortcuts:
            if not shortcut.enabled:
                continue

            task = ShortcutTask(shortcut, self.state)
            task._manager_ref = lambda: self  # back-reference for callbacks
            task.pool = self._pool
            task.threshold = shortcut.get_threshold(Config.threshold)
            self.tasks[shortcut.key] = task

    # ========== Listener creation ==========

    def create_keyboard_filter(self):
        """Create the keyboard event filter."""
        def win32_event_filter(msg, data):
            # Only handle KEYDOWN and KEYUP messages
            if msg not in KEYBOARD_MESSAGES:
                return True

            key_name = KeyMapper.vk_to_name(data.vkCode)

            # A real key press may have moved the cursor: the next dictation no longer continues the last one
            if msg in KEY_DOWN_MESSAGES and key_name not in self.tasks and not data.flags & LLKHF_INJECTED:
                joiner.note_user_input()

            # LLM cleanup toggle (double tap). Does not block the key, so it keeps its normal function
            if self._llm_toggle_key and key_name == self._llm_toggle_key:
                if msg in KEY_DOWN_MESSAGES:
                    if not self._llm_toggle_held:
                        # A real new press; auto-repeat KEYDOWNs arrive while held=True and are skipped
                        self._llm_toggle_held = True
                        self._handle_llm_toggle_press()
                elif msg in KEY_UP_MESSAGES:
                    self._llm_toggle_held = False

            # Ignore keys we are sending ourselves
            if self._check_emulating(key_name, msg):
                return True
            if self._check_restoring(key_name, msg):
                return True

            # Find the matching shortcut
            if key_name not in self.tasks:
                return True

            task = self.tasks[key_name]

            # Handle the key event
            if msg in KEY_DOWN_MESSAGES:
                self._event_handler.handle_keydown(key_name, task)
            elif msg in KEY_UP_MESSAGES:
                self._event_handler.handle_keyup(key_name, task)

            # Suppress the event
            if task.shortcut.suppress and self.keyboard_listener:
                self.keyboard_listener.suppress_event()

            return True

        return win32_event_filter

    def create_mouse_filter(self):
        """Create the mouse event filter."""
        def win32_event_filter(msg, data):
            if msg in CLICK_MESSAGES and not data.flags & LLMHF_INJECTED:
                joiner.note_user_input()

            # Only handle XBUTTON messages
            if msg not in MOUSE_MESSAGES:
                return True

            # Work out which button it is
            xbutton = (data.mouseData >> 16) & 0xFFFF
            button_name = 'x1' if xbutton == XBUTTON1 else 'x2'

            # Ignore buttons we are sending ourselves
            if self._check_emulating(button_name, msg, is_mouse=True):
                return True

            # Find the matching shortcut
            if button_name not in self.tasks:
                return True

            task = self.tasks[button_name]

            # Handle the mouse event
            if msg == WM_XBUTTONDOWN:
                self._event_handler.handle_keydown(button_name, task)
            elif msg == WM_XBUTTONUP:
                self._handle_mouse_keyup(button_name, task)

            # Suppress the event
            if task.shortcut.suppress and self.mouse_listener:
                self.mouse_listener.suppress_event()

            return True

        return win32_event_filter

    def _handle_mouse_keyup(self, button_name: str, task) -> None:
        """Handle a mouse button release."""
        # Click mode
        if not task.shortcut.hold_mode:
            if task.pressed:
                task.pressed = False
                task.released = True
                task.event.set()
            return

        # Hold mode
        if not task.is_recording:
            return

        duration = time.time() - task.recording_start_time
        logger.debug(f"[{button_name}] Released after {duration:.3f}s")

        if duration < task.threshold:
            task.cancel()
            if task.shortcut.suppress:
                logger.debug(f"[{button_name}] Scheduling a replay of the mouse button")
                self._pool.submit(self._emulator.emulate_mouse_click, button_name)
        else:
            task.finish()

    # ========== Key restore ==========

    def schedule_restore(self, key: str) -> None:
        """
        Schedule a key restore (delayed so it does not block event handling).

        Args:
            key: the key to restore

        Note: the flag is only cleared on the key-up event (_check_restoring),
        so clearing it early from the thread cannot cause duplicate messages.
        """
        from pynput import keyboard

        self._restoring_keys.add(key)

        def do_restore():
            import time
            time.sleep(0.05)  # 50 ms delay
            if key == 'caps_lock':
                controller = keyboard.Controller()
                controller.press(keyboard.Key.caps_lock)
                controller.release(keyboard.Key.caps_lock)

        self._pool.submit(do_restore)

    def is_restoring(self, key: str) -> bool:
        """Whether the given key is being restored."""
        return key in self._restoring_keys

    def clear_restoring_flag(self, key: str) -> None:
        """Clear the restore flag."""
        self._restoring_keys.discard(key)

    # ========== Self-capture checks ==========

    def _check_emulating(self, key_name: str, msg: int, is_mouse: bool = False) -> bool:
        """Whether this key is one we are emulating."""
        if not self._emulator.is_emulating(key_name):
            return False

        # Clear the flag on release
        if is_mouse:
            if msg == WM_XBUTTONUP:
                self._emulator.clear_emulating_flag(key_name)
        else:
            if msg in (WM_KEYUP, WM_SYSKEYUP):
                self._emulator.clear_emulating_flag(key_name)

        return True  # let it through

    def _check_restoring(self, key_name: str, msg: int) -> bool:
        """Whether this key is one we are restoring."""
        if not self.is_restoring(key_name):
            return False

        if msg in (WM_KEYUP, WM_SYSKEYUP):
            self.clear_restoring_flag(key_name)

        return True  # let it through

    # ========== Public interface ==========

    def start(self) -> None:
        """Start all listeners."""
        from config_client import ClientConfig as Config
        has_keyboard = any(s.type == 'keyboard' for s in self.shortcuts if s.enabled)
        has_mouse = any(s.type == 'mouse' for s in self.shortcuts if s.enabled)
        # Joining dictations needs to see both keyboard and mouse input to know the cursor has not moved
        if getattr(Config, 'join_dictations', True):
            has_keyboard = has_mouse = True
            joiner.watch()

        if has_keyboard:
            self.keyboard_listener = keyboard.Listener(
                win32_event_filter=self.create_keyboard_filter()
            )
            self.keyboard_listener.start()
            logger.info("Keyboard listener started")

        if has_mouse:
            self.mouse_listener = mouse.Listener(
                win32_event_filter=self.create_mouse_filter()
            )
            self.mouse_listener.start()
            logger.info("Mouse listener started")

        # Log every enabled shortcut
        for shortcut in self.shortcuts:
            if shortcut.enabled:
                mode = "hold" if shortcut.hold_mode else "click"
                toggle = "toggle key" if shortcut.is_toggle_key() else "normal key"
                logger.info(f"  [{shortcut.key}] {mode} mode, suppress: {shortcut.suppress}, {toggle}")

    def _handle_llm_toggle_press(self) -> None:
        """Handle a press of the LLM toggle key; a double tap flips the setting."""
        now = time.time()
        if (now - self._llm_toggle_last_press) <= self._llm_toggle_window:
            self._llm_toggle_last_press = 0.0  # reset so a triple tap does not toggle twice
            self._pool.submit(self._toggle_llm_enabled)
        else:
            self._llm_toggle_last_press = now

    @staticmethod
    def _toggle_llm_enabled() -> None:
        """Flip Config.llm_enabled, refresh the status bar text and log the change."""
        from config_client import ClientConfig as Config
        Config.llm_enabled = not Config.llm_enabled
        state_label = 'on' if Config.llm_enabled else 'off (fast path)'
        logger.info(f"LLM cleanup is {state_label} (double-tap {Config.llm_toggle_key} to switch)")
        try:
            from util.client.ui.recording_status_bar import update_recording_status_text
            update_recording_status_text()
        except Exception as e:
            logger.debug(f"Could not refresh the status bar: {e}")
        try:
            from util.client.runtime_status import get_runtime_status
            get_runtime_status().touch()
        except Exception as e:
            logger.debug(f"Could not refresh the desktop app status: {e}")

    def stop(self) -> None:
        """Stop all listeners and clean up."""
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            logger.debug("Keyboard listener stopped")

        if self.mouse_listener:
            self.mouse_listener.stop()
            logger.debug("Mouse listener stopped")

        # Cancel all tasks
        for task in self.tasks.values():
            if task.is_recording:
                task.cancel()

        # Shut down the thread pool
        self._pool.shutdown(wait=False)
        logger.debug("Shortcut manager thread pool shut down")
