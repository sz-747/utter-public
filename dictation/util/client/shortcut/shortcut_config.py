# coding: utf-8
"""
Shortcut configuration data class.

Defines the Shortcut data structure that configures how a shortcut behaves.
To avoid circular imports, this module does not depend on config.py.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class Shortcut:
    """
    Shortcut configuration.

    Attributes:
        key: key name (pynput format, e.g. 'caps_lock', 'a', 'f1', 'ctrl+shift+a')
        type: input type, 'keyboard' or 'mouse'
        suppress: whether to block the key event (other programs do not receive it)
        hold_mode: True = record while held, stop on release; False = click to start, click again to stop
        threshold: how long (seconds) the key must be held before recognition starts, to avoid accidental triggers. None means use Config.threshold
        enabled: whether this shortcut is enabled

    Notes:
        - In non-suppress mode, toggle keys (CapsLock/NumLock/ScrollLock) are pressed again automatically to restore their state
        - In suppress mode, a short press is replayed on release, so the key still works normally
    """
    key: str
    type: Literal['keyboard', 'mouse'] = 'keyboard'
    suppress: bool = False
    hold_mode: bool = True
    threshold: Optional[float] = None  # None means use Config.threshold
    enabled: bool = True

    # Mouse-specific setting
    mouse_button: Literal['x1', 'x2'] = 'x2'  # only used when type='mouse'

    def __post_init__(self):
        """Validate the configuration after creation."""
        # Normalize the key name
        if self.type == 'keyboard':
            self.key = self._normalize_key(self.key)
        elif self.type == 'mouse':
            self.key = self.mouse_button

    def get_threshold(self, default_threshold: float = 0.3) -> float:
        """
        Get this shortcut's threshold.

        Args:
            default_threshold: default threshold

        Returns:
            float: threshold in seconds
        """
        return self.threshold if self.threshold is not None else default_threshold

    @staticmethod
    def _normalize_key(key: str) -> str:
        """
        Normalize a key name.

        Args:
            key: raw key name

        Returns:
            str: normalized key name (pynput format)
        """
        # Lower-case
        key = key.lower().strip()

        # Replace common aliases
        aliases = {
            'capslock': 'caps_lock',
            'caps lock': 'caps_lock',
            ' ': 'space',
            'control': 'ctrl',
        }

        for old, new in aliases.items():
            key = key.replace(old, new)

        # Left/right modifier markers are left as is (pynput handles them),
        # so forms like 'left ctrl' are kept

        return key

    def is_toggle_key(self) -> bool:
        """
        Whether this is a toggle (lock) key that needs restoring.

        Returns:
            bool: True for a toggle key

        Note: the restorable keys are defined by the RESTORABLE_KEYS constant
        """
        from util.client.shortcut.key_mapper import RESTORABLE_KEYS

        # Check whether the key contains a restorable toggle key
        return any(toggle_key in self.key for toggle_key in RESTORABLE_KEYS)


# Common shortcut presets
@dataclass
class CommonShortcuts:
    """Common shortcut presets."""

    @staticmethod
    def caps_lock() -> Shortcut:
        """CapsLock (default)."""
        return Shortcut(
            key='caps_lock',
            type='keyboard',
            suppress=False,
            hold_mode=True,
            threshold=0.3
        )

    @staticmethod
    def mouse_x2() -> Shortcut:
        """Mouse X2 button (forward)."""
        return Shortcut(
            key='x2',
            type='mouse',
            suppress=True,
            hold_mode=True,
            threshold=0.3,
            mouse_button='x2'
        )

    @staticmethod
    def f12() -> Shortcut:
        """F12."""
        return Shortcut(
            key='f12',
            type='keyboard',
            suppress=False,
            hold_mode=True,
            threshold=0.3
        )

    @staticmethod
    def space() -> Shortcut:
        """Space bar."""
        return Shortcut(
            key='space',
            type='keyboard',
            suppress=False,
            hold_mode=True,
            threshold=0.3
        )
