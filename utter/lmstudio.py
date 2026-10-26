"""Add the Utter MCP to LM Studio, which starts it on this PC over stdio.

No tunnel and no key: LM Studio runs `python -m utter.mcp_server` itself, so dictations
only reach the local model. Utter owns one entry ("utter") in LM Studio's mcp.json and
leaves every other server in that file alone.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from . import local_state

NAME = 'utter'
CONFIG = Path.home() / '.lmstudio' / 'mcp.json'
LMS = Path.home() / '.lmstudio' / 'bin' / 'lms.exe'
DOWNLOAD_URL = 'https://lmstudio.ai/download'
_APP_PROCESSES = {'lm studio.exe', 'llmster.exe'}     # the app, or its headless service
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_models_cache = (0.0, None)


def entry() -> dict:
    return {'command': str(local_state.python_exe()), 'args': ['-m', 'utter.mcp_server'],
            'env': {'PYTHONPATH': str(local_state.BASE_DIR), 'PYTHONIOENCODING': 'utf-8',
                    'UTTER_MCP_CLIENT': 'lmstudio'}}


def _read() -> dict:
    if not CONFIG.exists():
        return {'mcpServers': {}}
    try:
        data = json.loads(CONFIG.read_text(encoding='utf-8') or '{}')
    except ValueError:
        raise ValueError(f'{CONFIG} is not valid JSON, so Utter left it alone. Fix it in LM Studio first.')
    data.setdefault('mcpServers', {})
    return data


def _write(data: dict) -> None:
    tmp = CONFIG.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(tmp, CONFIG)


def _app_running() -> bool:
    import psutil
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').lower() in _APP_PROCESSES:
            return True
    return False


def loaded_models(max_age: float = 5.0) -> list[dict] | None:
    """Chat models LM Studio has in memory now, or None while LM Studio is closed.

    LM Studio picks the model per chat, not per MCP server, so the loaded model is the one
    that answers. `lms` would start LM Studio's service if it were closed, so it is only
    asked while the app runs.
    """
    global _models_cache
    if time.time() - _models_cache[0] < max_age:
        return _models_cache[1]
    models = None
    if LMS.exists() and _app_running():
        try:
            result = subprocess.run([str(LMS), 'ps', '--json'], capture_output=True, text=True, encoding='utf-8',
                                    timeout=8, creationflags=_NO_WINDOW)
            models = [{'name': m.get('displayName') or m.get('modelKey'), 'key': m.get('modelKey'),
                       'context': m.get('contextLength'), 'tools': bool(m.get('trainedForToolUse'))}
                      for m in json.loads(result.stdout) if m.get('type') == 'llm']
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            models = None
    _models_cache = (time.time(), models)
    return models


def status() -> dict:
    installed = CONFIG.parent.exists()
    try:
        current = _read()['mcpServers'].get(NAME) if installed else None
        error = None
    except ValueError as e:
        current, error = None, str(e)
    last = local_state.last_mcp_use('lmstudio')
    return {'installed': installed, 'added': current is not None, 'up_to_date': current == entry(),
            'error': error, 'last_used': last.get('at'), 'last_models': last.get('models'),
            'running': installed and _app_running(), 'models': loaded_models() if current else None}


def add() -> None:
    if not CONFIG.parent.exists():
        raise RuntimeError('LM Studio is not installed. Install it, open it once, then add Utter.')
    data = _read()
    data['mcpServers'][NAME] = entry()
    _write(data)


def remove() -> None:
    data = _read()
    if data['mcpServers'].pop(NAME, None) is not None:
        _write(data)
