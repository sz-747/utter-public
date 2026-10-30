"""Status and control of the speech server and dictation client processes."""
from __future__ import annotations

import os
import re
import socket
import subprocess
import time
from pathlib import Path

from util import app_settings
from . import dictation

ROOT = dictation.ROOT                             # the dictation client's folder
APP_ICON = Path(__file__).resolve().parents[1] / 'assets' / 'utter.ico'
RUNTIME = ROOT / 'internal' / 'runtime'
CLIENT_SCRIPT = ROOT / 'core_client.py'
SERVER_EXE = RUNTIME / 'start_server.exe'
_STARTUP_DIR = Path(os.environ.get('APPDATA', '')) / 'Microsoft/Windows/Start Menu/Programs/Startup'
STARTUP_LINK = _STARTUP_DIR / 'Utter.lnk'
_STALE_SECONDS = 10
_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

MODEL_NAMES = {
    'qwen_asr': 'Qwen3-ASR 1.7B',
}


def _config_value(path: Path, name: str) -> str | None:
    try:
        match = re.search(rf"^\s*{name}\s*=\s*['\"]([^'\"]*)['\"]", path.read_text(encoding='utf-8'), re.M)
    except OSError:
        return None
    return match.group(1) if match else None


def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _listening_here(port: int) -> bool:
    """Whether something on this PC listens on `port`, read from Windows' socket table (~3 ms).
    Connecting instead made the speech server log a failed-handshake traceback per check, and the
    window checks every second."""
    import psutil
    try:
        return any(c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN
                   for c in psutil.net_connections('tcp'))
    except psutil.Error:
        return _port_open('127.0.0.1', port)


_remote_checks: dict = {}
_REMOTE_CHECK_SECONDS = 10


def _speech_server_answers(host: str, port: int, timeout: float = 0.8) -> bool:
    """Another PC's speech server, by a real websocket handshake (no traceback in its log),
    at most once per _REMOTE_CHECK_SECONDS."""
    cached = _remote_checks.get((host, port))
    if cached and time.monotonic() - cached[0] < _REMOTE_CHECK_SECONDS:
        return cached[1]
    try:
        from websockets.sync.client import connect
        with connect(f'ws://{host}:{port}', subprotocols=['binary'], open_timeout=timeout):
            answers = True
    except Exception:
        answers = False
    _remote_checks[(host, port)] = (time.monotonic(), answers)
    return answers


def _pid_alive(pid) -> bool:
    try:
        import psutil
        return bool(pid) and psutil.pid_exists(int(pid))
    except Exception:
        return False


def is_remote() -> bool:
    """A client-only install (e.g. a laptop) with no speech server; it uses another PC's over Tailscale."""
    return not SERVER_EXE.exists()


def server_status() -> dict:
    if is_remote():
        config = ROOT / 'config_client.py'
        addr = _config_value(config, 'addr') or '127.0.0.1'
        port = int(_config_value(config, 'port') or 6016)
        return {
            'installed': False,
            'remote': True,
            'host': addr if re.fullmatch(r'[\d.]+', addr) else addr.split('.')[0],  # desktop.your-tailnet.ts.net -> desktop
            'listening': _speech_server_answers(addr, port),
            'address': f'{addr}:{port}',
            'model': None,
        }
    config = RUNTIME / 'config_server.py'
    addr = _config_value(config, 'addr') or '127.0.0.1'
    port = int(_config_value(config, 'port') or 6016)
    model = _config_value(config, 'model_type')
    return {
        'installed': True,
        'remote': False,
        'listening': (_listening_here(port) if addr in ('0.0.0.0', *_LOCAL_HOSTS)
                      else _speech_server_answers(addr, port)),
        'address': f'{addr}:{port}',
        'model': MODEL_NAMES.get(model, model or 'unknown'),
    }


_process_cache = (0.0, [])


def _client_processes(max_age: float = 0.0) -> list:
    """Client processes by command line. Scanning every process is slow, so callers may reuse a recent scan."""
    global _process_cache
    if max_age and time.time() - _process_cache[0] < max_age:
        return _process_cache[1]
    try:
        import psutil
    except ImportError:
        return []
    found = []
    for process in psutil.process_iter(['pid', 'cmdline']):
        try:
            if str(CLIENT_SCRIPT) in ' '.join(process.info.get('cmdline') or []):
                found.append(process)
        except psutil.Error:
            continue
    _process_cache = (time.time(), found)
    return found


def client_status() -> dict:
    status = app_settings.read_status()
    fresh = bool(status) and time.time() - status.get('updated_at', 0) < _STALE_SECONDS
    running = fresh and not status.get('stopped') and _pid_alive(status.get('pid'))
    result = {'running': running, **(status if running else {}), 'last_seen': status.get('updated_at')}
    # A client without a fresh status file is an older build or a stuck process.
    result['unreported'] = not running and bool(_client_processes(max_age=15))
    return result


_LOCAL_HOSTS = ('localhost', '127.0.0.1', '::1')
_LOCAL_SERVER_NAMES = {1234: 'LM Studio', 11434: 'Ollama'}


def llm_backend(config=None) -> dict:
    """Where AI polish would send text, and whether that backend answers.

    A server on this PC (Ollama, or an OpenAI-style server such as LM Studio)
    is checked by connecting to its port; online APIs are not probed.
    """
    config = config or ROOT / 'LLM' / 'default.py'
    provider = _config_value(config, 'provider') or 'ollama'
    model = _config_value(config, 'model') or ''
    url = _config_value(config, 'api_url') or ('http://127.0.0.1:11434' if provider == 'ollama' else '')
    match = re.match(r'https?://\[?([^\]/:]+)\]?(?::(\d+))?', url)
    host = match.group(1) if match else ''
    port = int(match.group(2)) if match and match.group(2) else (11434 if provider == 'ollama' else 443)
    local = host in _LOCAL_HOSTS
    label = _LOCAL_SERVER_NAMES.get(port, provider) if local else provider
    # Probe the IPv4 address directly: "localhost" makes Windows try IPv6 first and stall
    # for up to 2 s when the server only listens on 127.0.0.1 (LM Studio, Ollama).
    probe_host = '127.0.0.1' if host == 'localhost' else host
    return {'provider': provider, 'label': label, 'model': model, 'local': local,
            'reachable': _port_open(probe_host, port) if local else None,
            'slow_localhost': host == 'localhost'}


def _run_script(name: str, wait: bool = False):
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
               '-File', str(ROOT / name)]
    if wait:
        return subprocess.run(command, cwd=ROOT, creationflags=_NO_WINDOW, timeout=120,
                              capture_output=True, text=True)
    return subprocess.Popen(command, cwd=ROOT, creationflags=_NO_WINDOW)


def start_engine():
    """Start the server (if needed) and the client; returns immediately."""
    _run_script('start-client.ps1' if is_remote() else 'start-dictation.ps1')


def wait_until_idle(timeout: float = 60, poll: float = 0.5) -> bool:
    """Wait while a dictation is being recorded, then a moment for it to be typed.
    A restart in the middle of a recording lost it. False if still recording at timeout."""
    deadline = time.monotonic() + timeout
    was_recording = False
    while client_status().get('recording'):
        was_recording = True
        if time.monotonic() > deadline:
            return False
        time.sleep(poll)
    if was_recording:
        time.sleep(3)                        # recognition, polish and typing after the key is released
    return True


def stop_engine():
    wait_until_idle()
    _run_script('stop-dictation.ps1', wait=True)


def restart_client():
    """Stop only the dictation client and start it again (applies shortcut changes)."""
    import psutil
    wait_until_idle()
    for process in _client_processes():
        try:
            process.kill()
        except psutil.Error:
            pass
    time.sleep(1)
    _run_script('start-client.ps1')


# -- launch at login -------------------------------------------------------

def launch_at_login() -> bool:
    return STARTUP_LINK.exists()


def set_launch_at_login(enabled: bool) -> bool:
    if enabled and not launch_at_login():
        import win32com.client
        shell = win32com.client.Dispatch('WScript.Shell')
        link = shell.CreateShortcut(str(STARTUP_LINK))
        link.TargetPath = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
        link.Arguments = ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File '
                          f'"{ROOT / "start-at-login.ps1"}"')
        link.WorkingDirectory = str(ROOT)
        link.IconLocation = f'{APP_ICON},0'
        link.WindowStyle = 7
        link.Save()
    elif not enabled and STARTUP_LINK.exists():
        STARTUP_LINK.unlink()
    return launch_at_login()
