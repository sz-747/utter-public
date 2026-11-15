"""The Codex app server (`codex app-server`): the notetaker's online AI and the ChatGPT account it uses.

Utter has no ChatGPT login of its own. It uses whatever account the Codex CLI
is signed in to (its saved login in ~/.codex), the same one the Codex app and
the dictation client's AI dictionary review use. Switching the account from Utter signs
the CLI in to the new one; the old login stays until the new sign-in finishes.
"""
from __future__ import annotations

import collections
import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import tomllib
import urllib.parse
from pathlib import Path

from . import __version__


class CodexError(Exception):
    pass


class CodexStopped(CodexError):
    """The app server process ended (signed out, offline, timed out or killed)."""


def find_codex() -> str | None:
    candidates = [str(Path.home() / '.codex/packages/standalone/current/bin/codex.exe'), shutil.which('codex.exe')]
    return next((c for c in candidates if c and Path(c).exists()), None)


# Utter's asks are answered from the prompt alone, so its app server leaves out what the Codex CLI is set up with
# for coding: hooks (they would report Utter's asks as agent sessions), memories (a client's words must not become
# Codex memories), plugins, apps and MCP servers. Without them an ask starts answering about 1.5 s sooner.
# `-c features.<name>=false` is accepted even for a name the CLI does not know, unlike `--disable <name>`.
QUIET_FEATURES = ('hooks', 'memories', 'plugins', 'apps')


def codex_config() -> Path:
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml'


def quiet_args(config: Path | None = None, mcp: bool = True) -> list[str]:
    args = [arg for feature in QUIET_FEATURES for arg in ('-c', f'features.{feature}=false')]
    servers = {}
    if mcp:
        try:
            servers = tomllib.loads((config or codex_config()).read_text(encoding='utf-8')).get('mcp_servers') or {}
        except (OSError, ValueError):
            pass
    for name in servers:
        if re.fullmatch(r'[A-Za-z0-9_-]+', name):          # a bare TOML key; any other name keeps its server
            args += ['-c', f'mcp_servers.{name}.enabled=false']
    return args


def quiet_server(timeout: float = 300) -> AppServer:
    """An app server for answering from the prompt. Hooks and memories stay off even when it has to start
    with the MCP servers on (a server the CLI cannot read turned off stops Codex from starting)."""
    try:
        return AppServer(timeout, args=quiet_args())
    except CodexStopped:
        return AppServer(timeout, args=quiet_args(mcp=False))


class AppServer:
    """One `codex app-server` process in a throwaway folder, spoken to in JSON-RPC lines over stdio.

    Requests from the server (approvals) are always declined. close() also stops
    the helper processes it starts; it runs by itself after `timeout` seconds.
    """

    def __init__(self, timeout: float = 300, codex: str | None = None, args: list[str] = ()):
        codex = codex or find_codex()
        if not codex:
            raise CodexError('The Codex CLI was not found on this PC.')
        # Codex's helper processes may still hold the folder for a moment after they are killed.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.cwd = self._tmp.name
        env = {k: v for k, v in os.environ.items() if k != 'CODEX_API_KEY'}   # use the saved ChatGPT login
        self.process = subprocess.Popen([codex, 'app-server', *args], cwd=self.cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self._ids = itertools.count(1)
        self._pending = collections.deque()      # notifications that arrived while request() waited
        self._closed = False
        self._timer = threading.Timer(timeout, self.close)
        self._timer.daemon = True
        self._timer.start()
        try:
            self.request('initialize', {'clientInfo': {'name': 'utter', 'title': 'Utter', 'version': __version__}})
            self.send({'method': 'initialized'})
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def send(self, message: dict):
        try:
            self.process.stdin.write(json.dumps(message) + '\n')
            self.process.stdin.flush()
        except (OSError, ValueError):              # the process has ended and its input is closed
            raise CodexStopped('Codex stopped before it answered (signed out, offline or timed out).') from None

    def messages(self):
        """Responses and notifications, in order."""
        while self._pending:
            yield self._pending.popleft()
        yield from self._read()

    def _read(self):
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if 'method' in message and 'id' in message:      # a request to us: approve nothing
                self.send({'id': message['id'], 'result': {'decision': 'decline'}})
                continue
            yield message
        raise CodexStopped('Codex stopped before it answered (signed out, offline or timed out).')

    def request(self, method: str, params: dict) -> dict:
        request_id = next(self._ids)
        self.send({'id': request_id, 'method': method, 'params': params})
        for message in self._read():
            if message.get('id') == request_id and 'method' not in message:
                if 'error' in message:
                    raise CodexError(f'Codex {method} failed: {message["error"].get("message")}')
                return message.get('result') or {}
            if (message.get('params') or {}).get('threadId'):
                self._pending.append(message)       # e.g. the first words of a turn, before turn/start answers

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._timer.cancel()
        _kill_tree(self.process)
        self._tmp.cleanup()


def _kill_tree(process):
    """The app server starts helper processes; stop them with it."""
    import psutil
    try:
        children = psutil.Process(process.pid).children(recursive=True)
    except psutil.Error:
        children = []
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass
    process.kill()
    process.wait()
    psutil.wait_procs(children, timeout=3)


def ask(prompt: str, schema: dict | None = None, model: str | None = None, effort: str | None = None,
        timeout: float = 300, on_text=None) -> str:
    """One turn in an ephemeral, read-only thread; Codex can only answer from the prompt.

    on_text(answer_so_far) is called while the answer is being written."""
    with quiet_server(timeout) as server:
        return _turn(server, _thread(server, model), prompt, schema, effort, on_text)


def _thread(server: AppServer, model: str | None) -> str:
    start = {'cwd': server.cwd, 'ephemeral': True, 'sandbox': 'read-only', 'approvalPolicy': 'never'}
    if model:
        start['model'] = model
    return server.request('thread/start', start)['thread']['id']


def _turn(server: AppServer, thread: str, prompt: str, schema: dict | None, effort: str | None, on_text=None) -> str:
    turn = {'threadId': thread, 'input': [{'type': 'text', 'text': prompt}]}
    if effort:
        turn['effort'] = effort
    if schema:
        turn['outputSchema'] = schema
    server.request('turn/start', turn)
    answer = written = ''
    for message in server.messages():
        params = message.get('params') or {}
        if params.get('threadId', thread) != thread:          # a late message about an earlier ask
            continue
        if message.get('method') == 'item/started' and params.get('item', {}).get('type') == 'agentMessage':
            written = ''                                       # only the newest message is the answer
        elif message.get('method') == 'item/agentMessage/delta' and on_text:
            written += params.get('delta') or ''
            on_text(written)
        elif message.get('method') == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
            answer = params['item'].get('text', '')
        elif message.get('method') == 'turn/completed':
            result = params.get('turn') or {}
            if result.get('status') == 'failed':
                raise CodexError(f'Codex failed: {(result.get("error") or {}).get("message", "unknown error")}')
            return answer
        elif message.get('method') == 'error' and not params.get('willRetry'):
            raise CodexError(f'Codex failed: {(params.get("error") or {}).get("message", "unknown error")}')


class Warm:
    """An app server kept running with a thread already open, so an ask answers about 3 s sooner than ask().

    For asks that cannot wait, like advice during a call: keep one while the call is recorded and close() it
    after. One ask runs at a time, each in its own new thread; the next thread opens once one is used.
    """

    def __init__(self, model: str | None = None, server_factory=quiet_server, lifetime: float = 6 * 3600):
        self._model = model
        self._factory = server_factory
        self._lifetime = lifetime            # the server stops itself after this, even if close() is never called
        self._lock = threading.Lock()        # one ask or preparation at a time
        self._server = None
        self._thread = None
        self._closed = False
        self._prepare_later()

    def _prepare_later(self):
        threading.Thread(target=self._prepare, daemon=True, name='codex-warm').start()

    def _prepare(self):
        with self._lock:
            if self._closed or self._thread:
                return
            try:
                self._open()
                self._thread = _thread(self._server, self._model)
            except Exception:                    # offline or signed out: the next ask starts afresh and says why
                self._drop()

    def _open(self) -> bool:
        """Start the server if it is not running; True when it was running already."""
        if self._server and self._server.process.poll() is not None:
            self._drop()
        if self._server:
            return True
        self._server = self._factory(self._lifetime)
        return False

    def _drop(self):
        server, self._server, self._thread = self._server, None, None
        if server:
            server.close()

    def ask(self, prompt: str, schema: dict | None = None, effort: str | None = None, timeout: float = 300,
            on_text=None) -> str:
        written = []

        def wrote(text):
            written.append(True)
            if on_text:
                on_text(text)
        with self._lock:
            try:
                for retry in (False, True):
                    if self._closed:
                        raise CodexError('Codex was closed before it answered.')
                    reused = self._open()
                    server, thread, self._thread = self._server, self._thread, None
                    expired = []
                    timer = threading.Timer(timeout, lambda: (expired.append(True), server.close()))
                    timer.daemon = True
                    timer.start()
                    try:
                        return _turn(server, thread or _thread(server, self._model), prompt, schema, effort, wrote)
                    except CodexError as e:
                        stopped = isinstance(e, CodexStopped) or bool(expired)
                        if stopped:
                            self._drop()           # otherwise the server is fine (e.g. a usage limit) and stays
                        # A server that stopped while it waited (sleep, sign-out, a crash) gets one fresh try.
                        if not stopped or retry or not reused or written or expired or self._closed:
                            raise
                    finally:
                        timer.cancel()
            finally:
                if not self._closed:
                    self._prepare_later()

    def close(self):
        """Stop the server; an ask still running fails."""
        self._closed = True
        server = self._server
        if server:
            server.close()                       # without the lock, so a running ask stops now
        with self._lock:
            self._drop()


# -- the ChatGPT account -----------------------------------------------------------

def account_email() -> str | None:
    """The email of the ChatGPT account the Codex CLI is signed in to, or None when signed out."""
    with AppServer(timeout=30) as server:
        account = server.request('account/read', {}).get('account') or {}
    return account.get('email') if account.get('type') == 'chatgpt' else None


def choose_account(auth_url: str) -> str:
    """Ask the browser to show the sign-in page even when it is already signed in, so another account can be picked."""
    parts = urllib.parse.urlsplit(auth_url)
    query = urllib.parse.parse_qsl(parts.query)
    if not any(key == 'prompt' for key, _ in query):
        query.append(('prompt', 'login'))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


class Login:
    """Sign the Codex CLI in to a ChatGPT account from Utter, in the browser.

    state: 'idle', 'waiting' (browser open), 'done' or 'failed'. The current
    login is replaced only when the new sign-in finishes; cancelling keeps it.
    """

    WAIT_SECONDS = 600

    def __init__(self, server_factory=AppServer, open_url=os.startfile):
        self._server_factory = server_factory
        self._open_url = open_url
        self._lock = threading.Lock()
        self._server = None
        self.state = 'idle'
        self.error = None

    def start(self):
        with self._lock:
            if self.state == 'waiting':
                raise CodexError('Finish or cancel the sign-in that is already open.')
            server = self._server_factory(timeout=self.WAIT_SECONDS)
            try:
                result = server.request('account/login/start', {'type': 'chatgpt'})
            except Exception:
                server.close()
                raise
            self._server, self.state, self.error = server, 'waiting', None
        threading.Thread(target=self._wait, args=(server,), daemon=True, name='codex-login').start()
        self._open_url(choose_account(result['authUrl']))

    def _wait(self, server):
        state, error = 'failed', 'The sign-in timed out.'
        try:
            for message in server.messages():
                if message.get('method') == 'account/login/completed':
                    params = message.get('params') or {}
                    state, error = ('done', None) if params.get('success') else ('failed', params.get('error') or 'The sign-in did not finish.')
                    break
        except CodexError:
            pass
        finally:
            server.close()
            with self._lock:
                if self._server is server:          # not cancelled meanwhile
                    self._server, self.state, self.error = None, state, error

    def cancel(self):
        with self._lock:
            server, self._server = self._server, None
            self.state, self.error = 'idle', None
        if server:
            server.close()      # its sign-in page stops answering, so the current login stays
