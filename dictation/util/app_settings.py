"""User settings shared by the dictation client and the Utter desktop app.

config_client.py keeps the defaults. The Utter window imports this
module and writes overrides to appdata/settings.json; the client applies
them at startup and live.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPDATA = ROOT / 'appdata'
SETTINGS_PATH = APPDATA / 'settings.json'
STATUS_PATH = APPDATA / 'status.json'

# Overrides the client applies to ClientConfig; values are coerced to these types.
CLIENT_KEYS = {
    'audio_input_device': 'optional_str',   # preferred microphone name; None = automatic
    'llm_enabled': bool,
    'llm_min_chars': int,
    'hot': bool,
    'hot_rule': bool,
    'dictionary_context': bool,
    'auto_learn': bool,
    'auto_review': bool,
    'paste': bool,
    'copy_output_to_clipboard': bool,
    'save_audio': bool,
    'recording_status_bar': bool,
    'dictation_sounds': bool,
    'mute_while_dictating': bool,
    'quiet_mode': ('mute', 'lower'),        # one of these values
    'quiet_media_only': bool,
    'shortcuts': list,
}

# Settings only the desktop app reads.
APP_KEYS = {
    'display_name': str,
    'theme': str,
    'start_engine_with_app': bool,
}

APP_DEFAULTS = {
    'display_name': '',
    'theme': 'light',
    'start_engine_with_app': True,
}

# Shortcut fields the app may change; key and type stay as configured.
_SHORTCUT_FIELDS = {'enabled', 'hold_mode'}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    """Write via a temporary file so readers never see half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def _coerce(key, value, kinds):
    kind = kinds[key]
    if kind == 'optional_str':
        return str(value).strip() or None if value is not None else None
    if isinstance(kind, tuple):
        if value not in kind:
            raise ValueError(f'{key} must be one of {", ".join(kind)}')
        return value
    if kind is bool:
        return bool(value)
    if kind is int:
        return int(value)
    if kind is str:
        return str(value)
    if kind is list and isinstance(value, list):
        return value
    raise ValueError(f'{key} must be {kind.__name__}')


def load(path=None):
    """Validated overrides only (unknown keys and bad values are dropped)."""
    raw = _read_json(path or SETTINGS_PATH)
    kinds = {**CLIENT_KEYS, **APP_KEYS}
    clean = {}
    for key, value in raw.items() if isinstance(raw, dict) else ():
        if key in kinds:
            try:
                clean[key] = _coerce(key, value, kinds)
            except (TypeError, ValueError):
                continue
    return clean


def update(changes, path=None):
    path = path or SETTINGS_PATH
    kinds = {**CLIENT_KEYS, **APP_KEYS}
    current = load(path)
    for key, value in changes.items():
        if key not in kinds:
            raise KeyError(f'Unknown setting: {key}')
        current[key] = _coerce(key, value, kinds)
    write_json(path, current)
    return current


def merge_shortcuts(configured, overrides):
    """Apply enabled/hold_mode overrides to the configured shortcuts, matched by key and type."""
    merged = [dict(item) for item in configured]
    for override in overrides or []:
        if not isinstance(override, dict):
            continue
        for item in merged:
            if item.get('key') == override.get('key') and item.get('type') == override.get('type'):
                item.update({k: bool(v) for k, v in override.items() if k in _SHORTCUT_FIELDS})
    return merged


def apply_to_config(config, overrides):
    """Set client overrides on ClientConfig; returns the keys that changed."""
    changed = []
    for key, value in overrides.items():
        if key not in CLIENT_KEYS:
            continue
        if key == 'shortcuts':
            value = merge_shortcuts(getattr(config, 'shortcuts', []), value)
        if getattr(config, key, None) != value:
            setattr(config, key, value)
            changed.append(key)
    return changed


def read_status(path=None):
    return _read_json(path or STATUS_PATH)
