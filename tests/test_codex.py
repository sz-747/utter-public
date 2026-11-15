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


class QuietServerTests(unittest.TestCase):
    def test_hooks_memories_plugins_and_mcp_servers_are_left_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.toml'
            config.write_text('[mcp_servers.blender]\ncommand = "b"\n[mcp_servers.forge-mcp]\nurl = "u"\n'
                              '[mcp_servers."odd name"]\ncommand = "o"\n', encoding='utf-8')
            args = codex.quiet_args(config)
            features = ['-c', 'features.hooks=false', '-c', 'features.memories=false',
                        '-c', 'features.plugins=false', '-c', 'features.apps=false']
            self.assertEqual(codex.quiet_args(Path(tmp) / 'missing.toml'), features)
            self.assertEqual(codex.quiet_args(config, mcp=False), features)
            with mock.patch.dict('os.environ', {'CODEX_HOME': tmp}):
                self.assertEqual(codex.codex_config(), config)
        self.assertIn('mcp_servers.blender.enabled=false', args)
        self.assertIn('mcp_servers.forge-mcp.enabled=false', args)
        self.assertFalse(any('odd' in a for a in args))           # not a bare TOML key: left as it is

    def test_mcp_servers_that_cannot_be_turned_off_stay_on_but_hooks_and_memories_do_not(self):
        server = object()
        with mock.patch.object(codex, 'AppServer', side_effect=[codex.CodexError('stopped'), server]) as start, \
             mock.patch.object(codex, 'quiet_args', side_effect=lambda mcp=True: ['mcp'] if mcp else ['features']):
            self.assertIs(codex.quiet_server(30), server)
        self.assertEqual([c.kwargs['args'] for c in start.call_args_list], [['mcp'], ['features']])

    def test_the_answer_is_passed_on_while_written(self):
        process = FakeAppServerProcess({
            'thread/start': [{'result': {'thread': {'id': 'th1'}}}],
            'turn/start': [{'method': 'item/agentMessage/delta', 'params': {'threadId': 'th1', 'delta': 'Let me see.'}},
                           {'result': {}},              # the first words can come before turn/start is answered
                           {'method': 'item/agentMessage/delta', 'params': {'threadId': 'old', 'delta': 'late'}},
                           {'method': 'item/started', 'params': {'threadId': 'th1', 'item': {'type': 'agentMessage'}}},
                           {'method': 'item/agentMessage/delta', 'params': {'threadId': 'th1', 'delta': '{"a":'}},
                           {'method': 'item/agentMessage/delta', 'params': {'threadId': 'th1', 'delta': '1}'}},
                           {'method': 'item/completed', 'params': {'item': {'type': 'agentMessage', 'text': '{"a":1}'}}},
                           {'method': 'turn/completed', 'params': {'turn': {'status': 'completed'}}}],
        })
        written = []
        with patched(process):
            self.assertEqual(codex.ask('prompt', on_text=written.append), '{"a":1}')
        self.assertEqual(written, ['Let me see.', '{"a":', '{"a":1}'])     # a second message starts afresh


class FakeServer:
    """What codex.Warm uses of an AppServer; `dies` makes it stop before it answers, `fails` fail the turn."""

    def __init__(self, dies=False, fails=False):
        self.cwd, self.dies, self.fails, self.closed = 'x', dies, fails, False
        self.process = mock.Mock(poll=mock.Mock(return_value=None))
        self.threads, self.turns = 0, []

    def request(self, method, params):
        if method == 'thread/start':
            self.threads += 1
            return {'thread': {'id': f't{self.threads}'}}
        self.turns.append(params)
        return {}

    def messages(self):
        if self.dies:
            raise codex.CodexStopped('Codex stopped before it answered')
        thread = self.turns[-1]['threadId']
        if self.fails:
            yield {'method': 'turn/completed', 'params': {'threadId': thread, 'turn': {'status': 'failed', 'error': {'message': 'usage limit'}}}}
        for delta in ('{"a":', '1}'):
            yield {'method': 'item/agentMessage/delta', 'params': {'threadId': thread, 'delta': delta}}
        yield {'method': 'item/completed', 'params': {'threadId': thread, 'item': {'type': 'agentMessage', 'text': '{"a":1}'}}}
        yield {'method': 'turn/completed', 'params': {'threadId': thread, 'turn': {'status': 'completed'}}}

    def close(self):
        self.closed = True


def wait_for(check):
    for _ in range(200):
        if check():
            return
        time.sleep(0.01)
    raise AssertionError('timed out')


class WarmTests(unittest.TestCase):
    def warm(self, *servers):
        made = []

        def factory(lifetime):
            made.append(servers[len(made)])
            return made[-1]
        return codex.Warm('gpt-6-luna', server_factory=factory), made

    def test_an_ask_uses_the_thread_opened_ahead_and_the_next_one_opens(self):
        warm, made = self.warm(FakeServer())
        wait_for(lambda: made and made[0].threads == 1)
        written = []
        self.assertEqual(warm.ask('p', None, 'low', 5, written.append), '{"a":1}')
        self.assertEqual((made[0].turns[0]['threadId'], made[0].turns[0]['effort']), ('t1', 'low'))
        self.assertEqual(written, ['{"a":', '{"a":1}'])
        wait_for(lambda: made[0].threads == 2)
        warm.close()
        self.assertTrue(made[0].closed)
        with self.assertRaisesRegex(codex.CodexError, 'closed'):
            warm.ask('p')
        self.assertEqual(len(made), 1)

    def test_a_server_that_stopped_while_waiting_gets_one_fresh_try(self):
        warm, made = self.warm(FakeServer(dies=True), FakeServer())
        wait_for(lambda: made and made[0].threads == 1)
        self.assertEqual(warm.ask('p'), '{"a":1}')
        self.assertTrue(made[0].closed)
        warm.close()

    def test_only_one_fresh_try(self):
        warm, made = self.warm(FakeServer(dies=True), FakeServer(dies=True), FakeServer())
        wait_for(lambda: made and made[0].threads == 1)
        with self.assertRaisesRegex(codex.CodexError, 'stopped'):
            warm.ask('p')
        self.assertEqual(len(made), 2)
        warm.close()

    def test_a_failed_turn_is_not_retried_and_keeps_the_server(self):
        warm, made = self.warm(FakeServer(fails=True))
        wait_for(lambda: made and made[0].threads == 1)
        with self.assertRaisesRegex(codex.CodexError, 'usage limit'):
            warm.ask('p')
        self.assertEqual((len(made), made[0].closed, len(made[0].turns)), (1, False, 1))
        wait_for(lambda: made[0].threads == 2)             # the next thread opens on the same server
        warm.close()

    def test_writing_to_a_server_that_ended_is_codex_stopped(self):
        process = FakeAppServerProcess({})
        with patched(process):
            server = codex.AppServer(30)
        process.write = mock.Mock(side_effect=OSError(22, 'Invalid argument'))
        with self.assertRaises(codex.CodexStopped):
            server.request('thread/start', {})


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
