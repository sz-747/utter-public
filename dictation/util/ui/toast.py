"""
Toast notification module

Shows simple floating notifications.

Usage:
    # Plain toast
    toast("Message text", duration=3000)

    # Streaming toast (for testing)
    toast_stream("Message text", markdown=False)
"""
import time
import logging
import threading
from typing import Union, Literal
import sys
import os

# When run directly, add the project root to sys.path
if __name__ == "__main__":
    file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(file_dir))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from util.ui.toast_manager import ToastMessageManager, ToastMessage
    from util.ui.toast_constants import (
        DEFAULT_DURATION_MS,
        DEFAULT_INITIAL_WIDTH,
        STREAM_CHAR_DELAY_S,
    )
else:
    from .toast_manager import ToastMessageManager, ToastMessage
    from .toast_constants import (
        DEFAULT_DURATION_MS,
        DEFAULT_INITIAL_WIDTH,
        STREAM_CHAR_DELAY_S,
    )


from . import logger


# ============================================================
# Public API
# ============================================================

def toast(
    text: str,
    font_size: int = 14,
    bg: str = "#C41529",
    fg: str = 'white',
    duration: int = DEFAULT_DURATION_MS,
    initial_width: Union[float, int] = DEFAULT_INITIAL_WIDTH,
    initial_height: int = 0,
    streaming: bool = False,
    window_type: Literal['text', 'label'] = 'text',
    markdown: bool = False
) -> None:
    """Show a floating notification

    Args:
        text: Message text
        font_size: Font size
        bg: Background color
        fg: Text color
        duration: How long to show it (milliseconds)
        initial_width: Initial width; 0-1 is a fraction of the screen, >1 is pixels
        initial_height: Initial height; 0 means calculate it automatically
        streaming: Whether the text streams in
        window_type: Window type ('text' or 'label')
        markdown: Whether to render Markdown
    """
    manager = ToastMessageManager()
    msg = ToastMessage(
        text=text,
        font_size=font_size,
        bg=bg,
        fg=fg,
        duration=duration,
        initial_width=initial_width,
        initial_height=initial_height,
        streaming=streaming,
        window_type=window_type,
        markdown=markdown
    )
    manager.add_message(msg)


def toast_stream(
    text: str,
    font_size: int = 14,
    bg: str = "#C41529",
    fg: str = 'white',
    duration: int = DEFAULT_DURATION_MS,
    initial_width: Union[float, int] = DEFAULT_INITIAL_WIDTH,
    initial_height: int = 0,
    window_type: Literal['text', 'label'] = 'text',
    markdown: bool = False
) -> None:
    """Toast that simulates streaming input (for testing streamed output)

    Args:
        text: Message text
        font_size: Font size
        bg: Background color
        fg: Text color
        duration: How long to show it (milliseconds)
        initial_width: Initial width
        initial_height: Initial height
        window_type: Window type ('text' or 'label')
        markdown: Whether to render Markdown
    """
    manager = ToastMessageManager()

    # Create the streaming toast
    msg = ToastMessage(
        text="",
        font_size=font_size,
        bg=bg,
        fg=fg,
        duration=duration,
        initial_width=initial_width,
        initial_height=initial_height,
        streaming=True,
        window_type=window_type,
        markdown=markdown
    )
    msg_id = manager.add_message(msg)

    # Simulate streamed output
    def simulate_streaming():
        for i in range(len(text) + 1):
            if i > 0:
                manager.update_toast(msg_id, text[:i])
            time.sleep(STREAM_CHAR_DELAY_S)
        manager.finish_toast(msg_id)

    stream_thread = threading.Thread(
        target=simulate_streaming,
        daemon=True,
        name="StreamSimulationThread"
    )
    stream_thread.start()


# ============================================================
# Test code
# ============================================================

if __name__ == "__main__":
    # Enable logging for the test, saved next to this module
    log_file = os.path.join(os.path.dirname(__file__), 'toast_debug.log')

    # Configure the root logger (running standalone)
    from util.ui.toast_logger import configure_toast_logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8', mode='w'),
            # logging.StreamHandler()  # Also log to the console
        ],
        force=True  # Force reconfiguration
    )

    logger.info(f"Log file: {log_file}")

    print("=" * 60)
    print("Full toast test")
    print("=" * 60)
    print("\nRuns 8 test cases:")
    print("1. Text window - plain text - not streamed")
    print("2. Text window - plain text - streamed")
    print("3. Text window - Markdown - not streamed")
    print("4. Text window - Markdown - streamed")
    print("5. Label window - plain text - not streamed")
    print("6. Label window - plain text - streamed")
    print("7. Label window - Markdown - not streamed")
    print("8. Label window - Markdown - streamed")
    print("=" * 60)

    # Test text
    plain_text = 5*"""This is a long sample paragraph for testing how the toast window wraps and scrolls plain text. It has several sentences of ordinary length, some short words and some longer ones, so line breaks land in different places. """

    markdown_text = """# Markdown test

## Features

This is an example of **bold text** and *italic text*.

### Code example
```python
def hello():
    print("Hello, World!")
```

### List
- First item
- Second item
- Third item

> This is a quotation"""*1

    # ========== Text window tests ==========

    # print("\n[Test 1] Text window - plain text - not streamed (3 s)")
    # toast(plain_text, bg="#075077", fg='white', duration=3000, window_type='text', initial_width=800)
    # time.sleep(4)

    # print("[Test 2] Text window - plain text - streamed (5 s)")
    # toast_stream(plain_text, bg="#2E7D32", fg='white', duration=5000, window_type='text', initial_width=800, markdown=False)
    # time.sleep(7)

    # print("[Test 3] Text window - Markdown - not streamed (3 s)")
    # toast(markdown_text, bg="#1565C0", fg='white', duration=3000, window_type='text', initial_width=800, markdown=True)
    # time.sleep(4)

    # print("[Test 4] Text window - Markdown - streamed (5 s)")
    # toast_stream(markdown_text, bg="#C62828", fg='white', duration=5000, window_type='text', initial_width=800, markdown=True)
    # time.sleep(7)

    # ========== Label window tests ==========

    # print("[Test 5] Label window - plain text - not streamed (3 s)")
    # toast(plain_text, bg="#F57C00", fg='white', duration=3000, window_type='label', initial_width=800)
    # time.sleep(4)

    # print("[Test 6] Label window - plain text - streamed (5 s)")
    # toast_stream(plain_text, bg="#7B1FA2", fg='white', duration=5000, window_type='label', initial_width=800, markdown=False)
    # time.sleep(7)

    print("[Test 7] Label window - Markdown - not streamed (3 s)")
    toast(markdown_text, bg="#00796B", fg='white', duration=3000, window_type='label', initial_width=800, markdown=True)
    time.sleep(4)

    # print("[Test 8] Label window - Markdown - streamed (5 s)")
    # toast_stream(markdown_text, bg="#5D4037", fg='white', duration=5000, window_type='label', initial_width=800, markdown=True)
    # time.sleep(7)

    print("\n" + "=" * 60)
    print("All tests done. Press Ctrl+C to exit")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting")
