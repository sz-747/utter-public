import os

# Version of Utter's dictation client (forked from CapsWriter-Offline 2.5)
__version__ = '0.1.1'

# Project root
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# Client configuration
class ClientConfig:
    audio_input_device = None  # Preferred microphone name; None = automatic (headsets first, then USB, then the system default). Falls back when the preferred one is not connected
    addr = '127.0.0.1'          # Speech server address; another PC's Tailscale name (e.g. 'desktop.your-tailnet.ts.net') to use its server
    port = '6016'               # Speech server port

    # Shortcuts
    shortcuts = [
        {
            'key': 'ctrl_r',        # Right Ctrl
            'type': 'keyboard',     # keyboard shortcut
            'suppress': True,       # block the key (a short press is sent on after recording)
            'hold_mode': False,     # hold to record
            'enabled': True         # use this shortcut
        },
        {
            'key': 'x2',
            'type': 'mouse',
            'suppress': True,
            'hold_mode': False,
            'enabled': True
        },
    ]

    threshold    = 0.3          # Shortcut trigger threshold (seconds)

    paste        = False        # Output by writing to the clipboard and pressing Ctrl+V
    restore_clip = True         # Restore the clipboard after pasting
    copy_output_to_clipboard = True  # Keep the final text on the clipboard, so it can be pasted by hand if focus was lost
    join_dictations = True      # When a dictation follows the last one in place (no key or click between), add a full stop and capitalise

    save_audio = True           # Save recordings
    audio_name_len = 20         # How many characters of the recognised text go into the recording's file name (keep under 200)

    context = ''                # Context for the speech model (names, places, technical terms)

    trash_punc = ',.'           # Trailing punctuation removed from results

    hot = True                  # Dictionary replacement (RAG matching)
    hot_thresh = 0.85           # RAG threshold for replacing with a dictionary word (high, used for real replacements)
    hot_thresh_rare = 0.75      # Lower replacement threshold when what was heard has an uncommon English word
                                # ("Kodex", "Herda"); everyday words keep hot_thresh. On two weeks of real
                                # dictations 0.75 only fixed mishearings; 0.70 started replacing right words
    hot_similar = 0.6           # RAG threshold for similar dictionary words (low, used as AI polish context)
    hot_rectify = 0.6           # RAG threshold for correction history (low, used as AI polish context)
    hot_rule = True             # Custom regular-expression replacement rules
    auto_learn = True           # Watch your edits after output and add corrected names to the dictionary (hot-learned.txt)
    auto_review = False         # When idle, review finished dictations with the Codex CLI (ChatGPT login) and learn misheard words; transcript text is sent to OpenAI, so it is off until you turn it on
    review_codex_path = None    # Codex CLI path; None = find ~/.codex/packages/standalone/current/bin/codex.exe

    dictation_sounds = False        # Play a sound when recording starts and stops
    mute_while_dictating = False    # Quiet other apps while recording, restore afterwards
    quiet_mode = 'mute'             # 'mute', or 'lower' to 20% of their volume
    quiet_media_only = False        # Only quiet music and video apps (Spotify, players, browsers)

    # The Utter window's Settings can change all of the above; its overrides are saved in appdata/settings.json

    llm_enabled = False         # AI polish; needs a role file in LLM/
    llm_min_chars = 100         # Skip AI polish for text shorter than this (short sentences rarely need it, and it saves time)
    llm_stop_key = 'esc'        # Key that stops AI output

    llm_toggle_key = 'shift_r'              # Double-tap this key to turn AI polish on or off; Shift still works; None turns this off
    llm_toggle_double_tap_window = 0.4      # Two presses closer than this (seconds) count as a double tap

    enable_tray = True          # Tray icon; off keeps the console window open for live logs
    recording_status_bar = True # Show the status pill at the bottom of the screen
    recording_status_text = 'Dictating'          # Status pill text while recording (AI polish on)
    recording_status_text_fast = 'Dictating · fast'  # Status pill text while recording (AI polish off)
    thinking_status_text = 'Thinking'   # Status pill text during AI polish
    thinking_status_min_seconds = 0.3   # Show the thinking state at least this long so it does not flash (polish takes about 0.3-0.6 s)

    # Logging
    log_level = 'INFO'          # 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'

    mic_seg_duration = 60       # Microphone dictation segment length (seconds)
    mic_seg_overlap = 4         # Microphone dictation segment overlap (seconds)

    file_seg_duration = 60      # File transcription segment length
    file_seg_overlap = 4        # File transcription segment overlap

    file_save_srt = True        # File transcription: save .srt subtitles
    file_save_txt = True        # File transcription: save .txt split at punctuation
    file_save_json = True       # File transcription: save .json with raw timestamps
    file_save_merge = False     # File transcription: save merge.txt (one unsplit paragraph)

    udp_broadcast = False               # Broadcast results over UDP, for other programs on this PC to read
    udp_broadcast_targets = [           # UDP broadcast targets: (address, port)
        ('127.255.255.255', 6017),      # local loopback broadcast
        # ('192.168.1.255', 6017),      # LAN broadcast (example)
    ]

    udp_control = False             # Let other programs start and stop recording over UDP (START/STOP)
    udp_control_addr = '127.0.0.1'  # UDP control address ('0.0.0.0' allows other machines)
    udp_control_port = 6018         # UDP control port


# Shortcut settings
r"""
Shortcut fields:
  key        - key name (see the list below)
  type       - 'keyboard' or 'mouse'
  suppress   - block the key (True) or let it through (False)
  hold_mode  - True: hold to record, release to stop; False: press to start, press again to stop
  enabled    - use this shortcut

Blocking:
  - Blocking    : hold to record; a short press (< 0.3 s) is sent on, so the key still works
  - Non-blocking: toggle keys such as CapsLock/NumLock/ScrollLock are sent again on release to restore their state

Key names:

  Letters and digits: a - z, 0 - 9 (main keyboard), numpad0 - numpad9 (number pad)

  Symbols: , . / \ ` ' - = [ ] ; '

  Number pad:
      decimal, numpad_add(+), numpad_subtract(-),
      numpad_multiply(*), numpad_divide(/), numpad_enter

  Function keys: f1 - f24

  Modifiers:
      ctrl,   ctrl_r,
      shift,  shift_r,
      alt,    alt_r,
      cmd,    cmd_r

  Special keys:
      space, enter, tab, backspace, delete, insert, home, end
      page_up, page_down, esc, caps_lock, num_lock, scroll_lock
      print_screen, pause, menu

  Arrows: up, down, left, right

  Mouse buttons: x1, x2

Examples:
  {'key': 'caps_lock', 'type': 'keyboard', 'suppress': False, 'hold_mode': False, 'enabled': True},
  {'key': 'f12', 'type': 'keyboard', 'suppress': True, 'hold_mode': False, 'enabled': True},
  {'key': 'x2', 'type': 'mouse', 'suppress': True, 'hold_mode': False, 'enabled': True},
"""
