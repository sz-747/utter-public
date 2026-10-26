# coding: utf-8
"""
Key emulator.

Sends emulated keyboard and mouse button presses.
"""

from pynput import keyboard, mouse
from . import logger
from util.client.shortcut.key_mapper import KeyMapper



class ShortcutEmulator:
    """
    Shortcut emulator.

    Keeps long-lived controller objects to avoid creating them repeatedly.
    """

    def __init__(self):
        """Set up the emulator."""
        self._keyboard_controller = keyboard.Controller()
        self._mouse_controller = mouse.Controller()
        self._emulating_keys = set()

    def is_emulating(self, key_name: str) -> bool:
        """Whether the given key is being emulated."""
        return key_name in self._emulating_keys

    def clear_emulating_flag(self, key_name: str) -> None:
        """Clear the emulating flag."""
        self._emulating_keys.discard(key_name)

    def emulate_key(self, key_name: str) -> None:
        """
        Emulate a keyboard key press.

        Args:
            key_name: key name (e.g. 'caps_lock', 'f12')
        """
        self._emulating_keys.add(key_name)

        key_obj = KeyMapper.name_to_key(key_name)
        if key_obj is not None:
            self._keyboard_controller.press(key_obj)
            self._keyboard_controller.release(key_obj)
            logger.debug(f"[{key_name}] Key replayed")
        else:
            logger.warning(f"[{key_name}] Unrecognized key, not replaying it")

    def emulate_mouse_click(self, button_name: str) -> None:
        """
        Emulate a mouse button press.

        Args:
            button_name: mouse button name ('x1' or 'x2')
        """
        self._emulating_keys.add(button_name)

        # pynput mouse button objects
        button_map = {
            'x1': mouse.Button.x1,
            'x2': mouse.Button.x2
        }

        if button_name in button_map:
            button = button_map[button_name]
            self._mouse_controller.press(button)
            self._mouse_controller.release(button)
            logger.debug(f"[{button_name}] Mouse button replayed")
        else:
            logger.warning(f"[{button_name}] Unrecognized mouse button, not replaying it")
