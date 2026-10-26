# coding: utf-8
"""
Client package

All the dictation client's functional modules.

Layout:
- state: client state
- websocket_manager: WebSocket connection management
- audio/: audio (recording, stream, file management, capture reports)
- shortcut/, global_hotkey/: shortcut handling
- output/: result processing and typing
- clipboard/: clipboard helpers
- learn/: learning from your edits and the AI dictionary review
- udp/: UDP control
- transcribe/: file transcription
- diary/: diary and transcript archive
- ui/: status pill and startup tips
"""

from util import get_logger
logger = get_logger('client')

# Core
from util.client.state import ClientState, get_state, console
from util.client.websocket_manager import WebSocketManager

# Audio
from util.client.audio import AudioRecorder, AudioStreamManager, AudioFileManager

# Shortcuts
from util.client.shortcut import Shortcut, ShortcutManager

# Output
from util.client.output import ResultProcessor, TextOutput

# Transcription
from util.client.transcribe import FileTranscriber, SrtAdjuster

# Diary
from util.client.diary import DiaryWriter

# UI
from util.client.ui import TipsDisplay

__all__ = [
    # Core
    'ClientState',
    'get_state',
    'console',
    'WebSocketManager',

    # Audio
    'AudioRecorder',
    'AudioStreamManager',
    'AudioFileManager',

    # Shortcuts
    'Shortcut',
    'ShortcutManager',

    # Output
    'ResultProcessor',
    'TextOutput',

    # Transcription
    'FileTranscriber',
    'SrtAdjuster',

    # Diary
    'DiaryWriter',

    # UI
    'TipsDisplay',
]

