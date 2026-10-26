
import os
from pathlib import Path
from platform import system
from util.client.state import get_state
from . import logger
from config_client import ClientConfig as Config
from util.client.cleanup import request_exit_from_tray
from util.client.ui import TipsDisplay
from util.hotword import get_hotword_manager
from util.llm.llm_handler import init_llm_system
from util.client.audio import AudioStreamManager
from util.client.shortcut.shortcut_config import Shortcut
from util.client.shortcut.shortcut_manager import ShortcutManager
from util.tools.empty_working_set import empty_current_working_set



def _setup_tray(state, base_dir):
    """
    Set up the tray icon (imported lazily so it works without a GUI)
    """
    try:
        from util.client.ui import enable_min_to_tray
    except ImportError as e:
        logger.warning(f"Could not import the tray module, skipping the tray: {e}")
        return

    def restart_audio():
        if state.stream_manager:
            state.stream_manager.reopen()
            logger.info("User asked to restart audio")

    def clear_memory():
        from util.llm.llm_handler import clear_llm_history
        clear_llm_history()
        from util.client.ui import toast
        toast("Cleared: conversation history for all roles has been deleted", duration=3000, bg="#075077")

    def add_hotword():
        try:
            from util.client.ui import on_add_hotword
            on_add_hotword()
        except ImportError as e:
            logger.warning(f"Could not import the hotword menu handler: {e}")

    def add_rectify():
        try:
            from util.client.ui import on_add_rectify_record
            on_add_rectify_record()
        except ImportError as e:
            logger.warning(f"Could not import the correction menu handler: {e}")

    def add_context():
        try:
            from util.client.ui import on_edit_context
            on_edit_context()
        except ImportError as e:
            logger.warning(f"Could not import the context menu handler: {e}")

    def copy_last_result():
        text = state.last_output_text
        if text:
            from util.llm.llm_clipboard import copy_to_clipboard
            copy_to_clipboard(text)

    import os
    icon_path = os.path.join(base_dir, os.pardir, 'assets', 'utter.ico')   # Utter's icon, in the repo's assets/
    enable_min_to_tray(
        'Utter dictation',
        icon_path,
        exit_callback=request_exit_from_tray,
        more_options=[
            ('📋 Copy result', copy_last_result),
            ('📝 Context', add_context),
            ('✨ Add dictionary word', add_hotword),
            ('🛠️ Add correction', add_rectify),
            ('🧹 Clear memory', clear_memory),
            ('🔄 Restart audio', restart_audio),
        ]
    )
    logger.info("Tray icon enabled")

def setup_client_components(base_dir):
    """
    Set up the client's components

    Args:
        base_dir: Project root folder

    Returns:
        ClientState: The initialized global state object
    """
    state = get_state()
    state.initialize()

    # 0. Desktop app settings overrides (must apply before shortcuts and other components are created)
    from util.client.runtime_status import get_runtime_status
    runtime_status = get_runtime_status()
    runtime_status.apply_settings_at_startup()

    # 1. Tray
    if Config.enable_tray:
        _setup_tray(state, base_dir)

    # 2. UI tips
    TipsDisplay.show_mic_tips()

    # 3. Hotwords
    logger.info("Loading hotwords...")
    hotword_files = {
        'hot': Path('hot.txt'),
        'rule': Path('hot-rule.txt'),
        'rectify': Path('hot-rectify.txt'),
        'learned': Path('hot-learned.txt'),
        'rule_learned': Path('hot-rule-learned.txt'),
    }
    hotword_manager = get_hotword_manager(
        hotword_files=hotword_files,
        threshold=Config.hot_thresh,
        similar_threshold=Config.hot_similar,
        rectify_threshold=Config.hot_rectify
    )
    hotword_manager.load_all()
    hotword_manager.start_file_watcher()

    # 4. LLM
    logger.info("Initializing the LLM system...")
    init_llm_system()
    logger.info("LLM system initialized")

    # 5. Audio stream
    logger.info("Opening the audio stream...")
    stream_manager = AudioStreamManager(state)
    state.stream_manager = stream_manager
    stream_manager.open()
    stream_manager.start_monitor()

    # 6. Shortcut manager (handles both keyboard and mouse shortcuts)
    # Build Shortcut objects from the Config.shortcuts list
    shortcuts = [Shortcut(**sc) for sc in Config.shortcuts]
    logger.info(f"Initializing the shortcut manager with {len(shortcuts)} shortcuts")

    shortcut_manager = ShortcutManager(state, shortcuts)
    state.shortcut_manager = shortcut_manager
    shortcut_manager.start()

    # Keep the old shortcut_handler reference for compatibility
    state.shortcut_handler = shortcut_manager

    # 7. UDP control (optional)
    if Config.udp_control:
        from util.client.udp.udp_control import UDPController
        logger.info(f"Enabling UDP control on port {Config.udp_control_port}")
        udp_controller = UDPController(shortcut_manager)
        state.udp_controller = udp_controller
        udp_controller.start()

    # 8. Sound cue / muting worker, and live status for the desktop app
    from util.client.audio.feedback import get_feedback
    get_feedback()
    from util.client.learn.edit_watcher import get_edit_watcher
    get_edit_watcher()
    from util.client.learn.reviewer import get_reviewer
    get_reviewer().nudge()        # review any backlog of dictations after startup
    runtime_status.start()

    # 9. Memory cleanup
    if system() == 'Windows':
        empty_current_working_set()

    logger.info("Client initialized, waiting for speech...")
    return state

