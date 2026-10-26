# coding: utf-8
"""
Status bar at the bottom of the screen (no text, just a waveform).

The shape comes from the Utter logo: a small fixed u in the middle with three
short bars on each side, shorter towards the outside.

- Recording: when quiet, a clear wave flows slowly through the side bars to show
  it is listening; while speaking, the side bars follow the mic (loudness sets the
  height, outer bars are higher frequencies)
- Processing: as soon as the shortcut is released it switches to a faster teal
  wave until the text is typed, with no gap in between
- Processing shows for at most _thinking_timeout seconds, so no error can leave
  the bar stuck on screen
"""

from __future__ import annotations

import math
import queue
import threading
import time
from typing import Optional

from config_client import ClientConfig as Config
from .. import logger


class RecordingStatusBar:
    """A small pill shown at the bottom of the screen."""

    _instance: Optional['RecordingStatusBar'] = None
    _lock = threading.Lock()
    _transparent_color = '#00ff00'
    _height = 44
    _bands = 5                  # matches util.client.audio.levels.BANDS
    _bar_count = 9              # 9 slots: the middle 3 hold the u, 3 bars each side (outer = higher pitch)
    _bar_width = 4
    _bar_gap = 5
    _bar_min = 4
    _bar_max = 28               # the pill is 36 high inside, with 4 spare top and bottom
    _side_padding = 22          # at least the corner radius, so the wave stays inside the pill
    _rest = (7, 11, 15)         # side bar lengths when quiet, outer -> inner, like the bars beside the logo's u
    _u_size = 6                 # half-width of the u, also arm top and bottom to the centre line; small so it doesn't read as a letter
    _SIDE_BANDS = {2: (0, 1), 3: (2,), 4: (3, 4)}   # distance from the middle -> bands: inner low, outer high
    _frame_ms = 40
    _thinking_timeout = 20.0
    _idle_color = '#f8fafc'
    _stall_color = '#f5a524'         # amber: the mic briefly sent no sound (e.g. a Bluetooth dropout), so the user should pause
    _think_color = (127, 216, 195)   # Utter teal

    def __new__(cls) -> 'RecordingStatusBar':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._queue: 'queue.Queue[tuple]' = queue.Queue()
        self._ready = threading.Event()
        self._available = False
        self._root = None
        self._window = None
        self._canvas = None
        self._bars = []             # [(slot, bar)], side bars only
        self._u = None
        self._heights = [float(self._bar_min)] * self._bar_count
        self._mode = None           # 'recording' / 'thinking' / None
        self._mode_since = 0.0
        self._width = self._side_padding * 2 + self._bar_count * self._bar_width + (self._bar_count - 1) * self._bar_gap
        self._thread = threading.Thread(target=self._run, daemon=True, name='RecordingStatusBarThread')
        self._thread.start()

    # -- API (any thread) -------------------------------------------------

    def show(self, mode: str) -> None:
        if not getattr(Config, 'recording_status_bar', True):
            return
        self._queue.put(('show', mode))

    def hide(self) -> None:
        self._queue.put(('hide',))

    # -- Tk thread -----------------------------------------------------

    def _run(self) -> None:
        try:
            import tkinter as tk  # noqa: F401
        except Exception as e:
            logger.warning(f"Status bar unavailable: {e}")
            self._ready.set()
            return
        try:
            import tkinter as tk
            self._root = tk.Tk()
            self._root.withdraw()
            self._available = True
            self._ready.set()
            self._poll()
            self._root.mainloop()
        except Exception as e:
            logger.warning(f"Status bar failed to start: {e}", exc_info=True)
            self._ready.set()

    def _poll(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                if item[0] == 'show':
                    self._show_window(item[1])
                else:
                    self._hide_window()
        except queue.Empty:
            pass
        except Exception as e:
            logger.warning(f"Status bar event handling failed: {e}", exc_info=True)
            self._safe_hide()

        try:
            if self._mode == 'thinking' and time.monotonic() - self._mode_since > self._thinking_timeout:
                self._hide_window()          # fallback: never leave the bar up if processing goes wrong
            elif self._mode:
                self._animate()
        except Exception as e:
            logger.warning(f"Status bar refresh failed: {e}", exc_info=True)
            self._safe_hide()

        if self._root is not None:
            self._root.after(self._frame_ms if self._mode else 150, self._poll)

    def _safe_hide(self) -> None:
        try:
            self._hide_window()
        except Exception:
            pass

    def _show_window(self, mode: str) -> None:
        if not self._available or self._root is None:
            return
        import tkinter as tk

        if mode == 'recording':
            from util.client.audio import levels
            levels.reset()
            self._heights = [float(self._bar_min)] * self._bar_count
        self._mode = mode
        self._mode_since = time.monotonic()

        if self._window is None or not self._window.winfo_exists():
            self._window = tk.Toplevel(self._root)
            self._window.overrideredirect(True)
            self._window.attributes('-topmost', True)
            self._window.configure(bg=self._transparent_color)
            try:
                self._window.attributes('-transparentcolor', self._transparent_color)
                canvas_bg = self._transparent_color
            except Exception:
                canvas_bg = '#101010'
            self._canvas = tk.Canvas(self._window, width=self._width, height=self._height,
                                     highlightthickness=0, bd=0, bg=canvas_bg)
            self._canvas.pack(fill=tk.BOTH, expand=True)
            self._draw_frame()
            self._position_window()
        self._window.deiconify()
        self._animate()

    def _hide_window(self) -> None:
        self._mode = None
        if self._window is not None:
            try:
                self._window.withdraw()
                self._window.destroy()
            except Exception:
                pass
        self._window = None
        self._canvas = None
        self._bars = []
        self._u = None

    def _slot_x(self, i: int) -> float:
        return self._side_padding + i * (self._bar_width + self._bar_gap) + self._bar_width / 2

    def _draw_frame(self) -> None:
        import tkinter as tk
        margin, radius = 4, 18
        self._round_rect(margin, margin, self._width - margin, self._height - margin, radius, fill='#101010', outline='')
        center_y = self._height / 2
        middle = self._bar_count // 2
        self._bars = []
        for i in range(self._bar_count):
            if abs(i - middle) <= 1:
                continue
            x = self._slot_x(i)
            self._bars.append((i, self._canvas.create_line(x, center_y, x, center_y, fill=self._idle_color,
                                                           width=self._bar_width, capstyle=tk.ROUND)))
        # The u stays still: left arm top -> bottom half-circle -> right arm top, symmetric about the centre line
        cx, cy, s = self._slot_x(middle), center_y, self._u_size
        points = [cx - s, cy - s, cx - s, cy]
        for step in range(1, 12):
            a = math.pi * step / 12
            points += [cx - s * math.cos(a), cy + s * math.sin(a)]
        self._u = self._canvas.create_line(*points, cx + s, cy, cx + s, cy - s, fill=self._idle_color,
                                           width=self._bar_width, capstyle=tk.ROUND, joinstyle=tk.ROUND)

    @staticmethod
    def _wave(x: float, t: float) -> float:
        """A wave flowing across the slots, -1..1; two sines added so it doesn't look mechanical (same as the logo animation on the Utter home page)."""
        return math.sin(t - x * 0.6) * 0.7 + math.sin(t * 1.6 + x * 0.35) * 0.3

    def _animate(self) -> None:
        if self._canvas is None or not self._bars:
            return
        center_y = self._height / 2
        span = self._bar_max - self._bar_min
        middle = self._bar_count // 2
        now = time.monotonic()
        bands = [0.0] * self._bands
        if self._mode == 'recording':
            from util.client.audio import levels
            stalled = levels.stalled()
            if not stalled:                                  # no fresh audio: don't freeze the last level
                bands = [float(v) for v in levels.get()]
            color = self._stall_color if stalled else self._idle_color
            t, swing = now * 2.6, 0.6                        # a clear wave even when quiet: shows it is listening
        else:
            fade = min(1.0, (now - self._mode_since) / 0.25)
            r, g, b = (int(248 + (c - 248) * fade) for c in self._think_color)
            color = f'#{r:02x}{g:02x}{b:02x}'
            t, swing = now * 5.0, 0.6

        targets = list(self._heights)
        for i, _ in self._bars:
            d = abs(i - middle)
            idle = self._rest[middle - d] * (1 + swing * self._wave(i - middle, t))
            voice = self._bar_min + span * max(bands[b] for b in self._SIDE_BANDS[d])
            targets[i] = max(self._bar_min, idle, voice)
        # Rise fast, fall slow: jump up as soon as there is sound, ease down in pauses
        self._heights = [t if t > h else h + (t - h) * 0.25 for h, t in zip(self._heights, targets)]

        for i, item in self._bars:
            half = max(0.5, (self._heights[i] - self._bar_width) / 2)   # round caps add half a line width at each end
            x = self._slot_x(i)
            self._canvas.coords(item, x, center_y - half, x, center_y + half)
            self._canvas.itemconfigure(item, fill=color)
        self._canvas.itemconfigure(self._u, fill=color)

    def _round_rect(self, x1, y1, x2, y2, radius, **kwargs) -> None:
        points = [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius, x2, y2 - radius, x2, y2,
                  x2 - radius, y2, x1 + radius, y2, x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]
        self._canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _position_window(self) -> None:
        if self._window is None:
            return
        x = (self._window.winfo_screenwidth() - self._width) // 2
        y = self._window.winfo_screenheight() - self._height - 56
        self._window.geometry(f'{self._width}x{self._height}+{x}+{y}')


def show_recording_status(start_time: Optional[float] = None) -> None:
    """Recording started: show the wave that follows the voice."""
    RecordingStatusBar().show('recording')


def update_recording_status_text() -> None:
    """The bar no longer shows text; kept because the LLM toggle still calls it."""


def show_thinking_status() -> None:
    """Recording ended, waiting for recognition or AI polish: switch to the processing wave at once."""
    RecordingStatusBar().show('thinking')


def hide_recording_status() -> None:
    """Text typed (or cancelled or failed): hide the bar."""
    RecordingStatusBar().hide()
