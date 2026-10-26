"""Whether the coding agents (Codex, Claude Code, Pi) can use the Utter MCP.

Each starts `python -m utter.mcp_server` on this PC over stdio, so there is no tunnel or key.
Utter only reads their configs; adding or removing Utter happens in each agent's own MCP config.
"""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from . import local_state

# (key, name, config file, where the servers live). The key matches UTTER_MCP_CLIENT.
AGENTS = [
    ('codex', 'Codex', Path.home() / '.codex' / 'config.toml', 'mcp_servers'),
    ('claude', 'Claude Code', Path.home() / '.claude.json', 'mcpServers'),
    ('pi', 'Pi', Path.home() / '.pi' / 'agent' / 'mcp.json', 'mcpServers'),
]


def _servers(path: Path, table: str) -> dict:
    text = path.read_text(encoding='utf-8')
    data = tomllib.loads(text) if path.suffix == '.toml' else json.loads(text)
    return data.get(table) or {}


def status() -> list[dict]:
    python = os.path.normcase(str(local_state.python_exe()))
    found = []
    for key, name, path, table in AGENTS:
        try:
            entry, error = _servers(path, table).get('utter'), None
        except FileNotFoundError:
            entry, error = None, None
        except (OSError, ValueError) as e:   # TOMLDecodeError and JSONDecodeError are ValueErrors
            entry, error = None, f'{path.name} could not be read: {e}'
        found.append({
            'key': key, 'name': name, 'added': entry is not None, 'error': error,
            'enabled': bool(entry) and entry.get('enabled', True) is not False,
            'up_to_date': bool(entry) and os.path.normcase(entry.get('command', '')) == python
                          and entry.get('args') == ['-m', 'utter.mcp_server'],
            'last_used': local_state.last_mcp_use(key).get('at'),
        })
    return found
