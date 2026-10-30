"""The Codex app server (`codex app-server`): the notetaker's online AI and the ChatGPT account it uses.

Utter has no ChatGPT login of its own. It uses whatever account the Codex CLI
is signed in to (its saved login in ~/.codex), the same one the Codex app and
the dictation client's AI dictionary review use. Switching the account from Utter signs
the CLI in to the new one; the old login stays until the new sign-in finishes.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import tempfile
import threading
import urllib.parse
from pathlib import Path


class CodexError(Exception):
    pass


def find_codex() -> str | None:
    candidates = [str(Path.home() / '.codex/packages/standalone/current/bin/codex.exe'), shutil.which('codex.exe')]
    return next((c for c in candidates if c and Path(c).exists()), None)


class AppServer:
    """One `codex app-server` process in a throwaway folder, spoken to in JSON-RPC lines over stdio.

    Requests from the server (approvals) are always declined. close() also stops
    the helper processes it starts; it runs by itself after `timeout` seconds.
    """

    def __init__(self, timeout: float = 300, codex: str | None = None):
        codex = codex or find_codex()
        if not codex:
            raise CodexError('The Codex CLI was not found on this PC.')
        # Codex's helper processes may still hold the folder for a moment after they are killed.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.cwd = self._tmp.name
        env = {k: v for k, v in os.environ.items() if k != 'CODEX_API_KEY'}   # use the saved ChatGPT login
        self.process = subprocess.Popen([codex, 'app-server'], cwd=self.cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self._ids = itertools.count(1)
        self._closed = False
        self._timer = threading.Timer(timeout, self.close)
        self._timer.daemon = True
        self._timer.start()
        try:
            self.request('initialize', {'clientInfo': {'name': 'utter', 'title': 'Utter', 'version': '0.2.0'}})
            self.send({'method': 'initialized'})
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def send(self, message: dict):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def messages(self):
        """Responses and notifications, in order."""
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if 'method' in message and 'id' in message:      # a request to us: approve nothing
                self.send({'id': message['id'], 'result': {'decision': 'decline'}})
                continue
            yield message
        raise CodexError('Codex stopped before it answered (signed out, offline or timed out).')

    def request(self, method: str, params: dict) -> dict:
        request_id = next(self._ids)
        self.send({'id': request_id, 'method': method, 'params': params})
        for message in self.messages():
            if message.get('id') == request_id and 'method' not in message:
                if 'error' in message:
                    raise CodexError(f'Codex {method} failed: {message["error"].get("message")}')
                return message.get('result') or {}

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
        timeout: float = 300) -> str:
    """One turn in an ephemeral, read-only thread; Codex can only answer from the prompt."""
    with AppServer(timeout) as server:
        start = {'cwd': server.cwd, 'ephemeral': True, 'sandbox': 'read-only', 'approvalPolicy': 'never'}
        if model:
            start['model'] = model
        thread = server.request('thread/start', start)['thread']['id']
        turn = {'threadId': thread, 'input': [{'type': 'text', 'text': prompt}]}
        if effort:
            turn['effort'] = effort
        if schema:
            turn['outputSchema'] = schema
        server.request('turn/start', turn)
        answer = ''
        for message in server.messages():
            params = message.get('params') or {}
            if message.get('method') == 'item/completed' and params.get('item', {}).get('type') == 'agentMessage':
                answer = params['item'].get('text', '')
            elif message.get('method') == 'turn/completed':
                result = params.get('turn') or {}
                if result.get('status') == 'failed':
                    raise CodexError(f'Codex failed: {(result.get("error") or {}).get("message", "unknown error")}')
                return answer
            elif message.get('method') == 'error' and not params.get('willRetry'):
                raise CodexError(f'Codex failed: {(params.get("error") or {}).get("message", "unknown error")}')


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
