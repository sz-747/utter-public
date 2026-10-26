import json
import queue
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from utter import codex, summary
from utter.api import Api


class FakeAppServerProcess:
    """Answers JSON-RPC lines like `codex app-server`; `script` maps a method to the messages it replies with."""

    def __init__(self, script):
        self.script = script
        self.sent = []
        self.out = queue.Queue()
        self.stdin = self
        self.stdout = self
        self.pid = 0

    def write(self, line):
        message = json.loads(line)
        self.sent.append(message)
        method, rid = message.get('method'), message.get('id')
        if rid is not None and method:
            for reply in self.script.get(method, [{'result': {}}]):
                self.out.put({'id': rid, **reply} if 'result' in reply or 'error' in reply else reply)

    def flush(self):
        pass

    def end(self):
        self.out.put(None)

    def __iter__(self):
        while True:
            message = self.out.get(timeout=5)
            if message is None:
                return
            yield json.dumps(message) + '\n'


def patched(process):
    return mock.patch.multiple(codex, find_codex=mock.Mock(return_value='codex.exe'),
                               _kill_tree=mock.Mock(side_effect=lambda p: p.end()),
                               subprocess=mock.Mock(Popen=mock.Mock(return_value=process), CREATE_NO_WINDOW=0))


class AppServerTests(unittest.TestCase):
    def test_a_turn_returns_the_final_message_and_declines_approvals(self):
        process = FakeAppServerProcess({
            'thread/start': [{'result': {'thread': {'id': 'th1'}}}],
            'turn/start': [{'result': {'turn': {'id': 'tu1'}}},
                           {'id': 99, 'method': 'item/commandExecution/requestApproval', 'params': {}},
                           {'method': 'item/completed', 'params': {'item': {'type': 'agentMessage', 'text': '{"ok": 1}'}}},
                           {'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}}],
        })
        with patched(process):
            self.assertEqual(summary.ask_codex('prompt', summary.SCHEMA), '{"ok": 1}')
        turn = next(m for m in process.sent if m.get('method') == 'turn/start')['params']
        thread = next(m for m in process.sent if m.get('method') == 'thread/start')['params']
        self.assertEqual((turn['outputSchema'], turn['effort']), (summary.SCHEMA, 'medium'))
        self.assertEqual((thread['sandbox'], thread['ephemeral'], thread['model']), ('read-only', True, 'gpt-6-luna'))
        self.assertIn({'id': 99, 'result': {'decision': 'decline'}}, process.sent)

    def test_a_failed_turn_is_a_summary_error(self):
        process = FakeAppServerProcess({
            'thread/start': [{'result': {'thread': {'id': 'th1'}}}],
            'turn/start': [{'result': {}}, {'method': 'turn/completed',
                                            'params': {'turn': {'status': 'failed', 'error': {'message': 'usage limit'}}}}],
        })
        with patched(process), self.assertRaisesRegex(summary.SummaryError, 'usage limit'):
            summary.ask_codex('prompt')

    def test_account_email(self):
        process = FakeAppServerProcess({'account/read': [{'result': {'account': {
            'type': 'chatgpt', 'email': 'someone@example.com', 'planType': 'pro'}, 'requiresOpenaiAuth': True}}]})
        with patched(process):
            self.assertEqual(codex.account_email(), 'someone@example.com')
        process = FakeAppServerProcess({'account/read': [{'result': {'account': None, 'requiresOpenaiAuth': True}}]})
        with patched(process):
            self.assertIsNone(codex.account_email())


class FakeLoginServer:
    def __init__(self, timeout=None):
        self.closed = threading.Event()
        self.finish = queue.Queue()

    def request(self, method, params):
        assert (method, params) == ('account/login/start', {'type': 'chatgpt'})
        return {'type': 'chatgpt', 'loginId': 'l1',
                'authUrl': 'https://auth.openai.com/oauth/authorize?client_id=x&redirect_uri=http%3A%2F%2F127.0.0.1%3A1455%2Fauth%2Fcallback'}

    def messages(self):
        while not self.closed.is_set():
            try:
                yield self.finish.get(timeout=0.05)
            except queue.Empty:
                continue
        raise codex.CodexError('closed')

    def close(self):
        self.closed.set()


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.servers = []
        self.opened = []

        def factory(timeout):
            self.servers.append(FakeLoginServer(timeout))
            return self.servers[-1]

        self.login = codex.Login(server_factory=factory, open_url=self.opened.append)

    def wait_for(self, state):
        for _ in range(100):
            if self.login.state == state:
                return
            time.sleep(0.02)
        self.fail(f'login state stayed {self.login.state}')

    def test_sign_in_opens_the_account_picker_and_finishes(self):
        self.login.start()
        self.assertEqual(self.login.state, 'waiting')
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.opened[0]).query)
        self.assertEqual((query['prompt'], query['client_id']), (['login'], ['x']))
        with self.assertRaises(codex.CodexError):
            self.login.start()                      # one sign-in at a time
        self.servers[0].finish.put({'method': 'account/login/completed', 'params': {'success': True, 'loginId': 'l1'}})
        self.wait_for('done')
        self.assertTrue(self.servers[0].closed.is_set())

    def test_failed_sign_in_reports_why(self):
        self.login.start()
        self.servers[0].finish.put({'method': 'account/login/completed', 'params': {'success': False, 'error': 'denied'}})
        self.wait_for('failed')
        self.assertEqual(self.login.error, 'denied')

    def test_cancel_keeps_the_current_login(self):
        self.login.start()
        self.login.cancel()
        self.assertEqual(self.login.state, 'idle')
        self.assertTrue(self.servers[0].closed.is_set())
        time.sleep(0.1)
        self.assertEqual(self.login.state, 'idle')     # the closed server does not turn into 'failed'


class ApiAccountTests(unittest.TestCase):
    def test_email_is_cached_and_reread_after_a_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            api = Api(notes_path=Path(tmp) / 'n.sqlite3')
            with mock.patch.object(codex, 'find_codex', return_value='codex.exe'), \
                 mock.patch.object(codex, 'account_email', side_effect=['a@example.com', 'b@example.com']) as read:
                self.assertEqual(api.get_codex_account()['email'], 'a@example.com')
                self.assertEqual(api.get_codex_account()['email'], 'a@example.com')
                self.assertEqual(read.call_count, 1)
                api._codex_login.state = 'done'
                result = api.get_codex_account()
            self.assertEqual((result['email'], result['login']), ('b@example.com', 'idle'))


if __name__ == '__main__':
    unittest.main()
