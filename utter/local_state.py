"""Utter's own state: connector settings in state/*.json, secrets in Windows Credential Manager.

The dictation client owns the dictation files; these files belong to Utter alone (connectors and MCP
activity). Tokens never go to disk in plain text.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = Path(os.environ.get('UTTER_STATE_DIR') or BASE_DIR / 'state')


def python_exe() -> Path:
    """python.exe beside the running interpreter, for apps that start the Utter MCP over stdio
    (pythonw, which runs the window, has no stdio)."""
    candidate = Path(sys.executable).with_name('python.exe')
    return candidate if candidate.exists() else Path(sys.executable)


def last_mcp_use(client: str) -> dict:
    """{'tool', 'at'} of the last MCP call from one app (codex, claude, pi, lmstudio); written by utter.mcp_server."""
    return read_json(f'mcp-activity-{client}.json')


def read_json(name: str) -> dict:
    try:
        return json.loads((STATE_DIR / name).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_json(name: str, data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / name
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def remove(name: str) -> None:
    try:
        (STATE_DIR / name).unlink()
    except FileNotFoundError:
        pass


# -- secrets (Windows Credential Manager, current user) -------------------------

def secret_get(name: str) -> str | None:
    import pywintypes
    import win32cred
    try:
        blob = win32cred.CredRead(name, win32cred.CRED_TYPE_GENERIC)['CredentialBlob']
    except pywintypes.error:
        return None
    return blob.decode('utf-16-le') if isinstance(blob, bytes) else blob


def secret_set(name: str, value: str) -> None:
    import win32cred
    win32cred.CredWrite({'Type': win32cred.CRED_TYPE_GENERIC, 'TargetName': name, 'UserName': 'Utter',
                         'CredentialBlob': value, 'Persist': win32cred.CRED_PERSIST_LOCAL_MACHINE}, 0)


def secret_delete(name: str) -> None:
    import pywintypes
    import win32cred
    try:
        win32cred.CredDelete(name, win32cred.CRED_TYPE_GENERIC)
    except pywintypes.error:
        pass
