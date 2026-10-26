"""
Toast constants

All constants for toast windows in one place.
"""
import tkinter as tk

# ============================================================
# Font and style
# ============================================================

DEFAULT_FONT_FAMILY = 'Segoe UI'
DEFAULT_PADDING_X = 20
DEFAULT_PADDING_Y = 15

# ============================================================
# Window size
# ============================================================

MIN_WINDOW_HEIGHT = 60  # Minimum window height

# Text widget only
STREAMING_TEXT_HEIGHT = 5  # Preset line count when streaming, so the first window isn't too big
NON_STREAMING_TEXT_HEIGHT = 1  # Initial line count when not streaming
HEIGHT_PADDING = 40  # Extra margin added to the Text window height
TEXT_WRAP_MODE = tk.WORD  # Text widget wrap mode (WORD wraps at word boundaries)

# Label widget only
LABEL_HEIGHT_PADDING = 30  # Extra margin added to the Label window height

# Markdown rendering only
MARKDOWN_MIN_HEIGHT = 50  # Minimum Markdown window height

# ============================================================
# Interaction
# ============================================================

SCROLL_STEP = 60  # Pixels moved per mouse wheel step
DESTROY_DELAY_MS = 100  # Delay before closing while dragging (milliseconds)

# ============================================================
# Defaults
# ============================================================

DEFAULT_DURATION_MS = 2000  # Default display time
DEFAULT_INITIAL_WIDTH = 0.5  # Default width (50% of the screen)

# ============================================================
# Internal
# ============================================================

QUEUE_POLL_INTERVAL_MS = 100  # Queue polling interval (milliseconds)
STREAM_CHAR_DELAY_S = 0.0001  # Delay per character when simulating streaming (seconds)
TK_SCALING_FACTOR = 2  # Tkinter DPI scaling factor (for high-DPI screens)
