import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from mcp import Client

from tests.test_api import archive
from utter import agents, google_calendar, lmstudio, local_state, mcp_server, stats

T0 = 1792809542.0   # 2026-10-25 local, any zone


def _save(transcripts, task, start, text, process='Code.exe', delivery='typed'):
    with mock.patch.object(archive, 'ROOT', transcripts):
        message = {'task_id': task, 'time_start': start, 'is_final': True, 'text': text, 'duration': 1.0}
        archive.save_recognition(message)
        archive.save_details(message, {'process_name': process}, [], delivery)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(local_state, 'STATE_DIR', Path(self.tmp.name) / 'state')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_json_and_secrets_round_trip(self):
        self.assertEqual(local_state.read_json('x.json'), {})
        local_state.write_json('x.json', {'a': 'é'})
        self.assertEqual(local_state.read_json('x.json'), {'a': 'é'})
        name = 'Utter/unit-test-secret'
        self.addCleanup(local_state.secret_delete, name)
        local_state.secret_set(name, 'sk-test-ü')
        self.assertEqual(local_state.secret_get(name), 'sk-test-ü')
        local_state.secret_delete(name)
        self.assertIsNone(local_state.secret_get(name))

    def test_google_client_file_must_be_a_desktop_client(self):
        web = Path(self.tmp.name) / 'web.json'
        web.write_text(json.dumps({'web': {'client_id': 'x'}}))
        with self.assertRaisesRegex(ValueError, 'Desktop app'):
            google_calendar.set_client_file(web)
        desktop = Path(self.tmp.name) / 'desktop.json'
        desktop.write_text(json.dumps({'installed': {'client_id': 'x', 'client_secret': 'y'}}))
        google_calendar.set_client_file(desktop)
        with mock.patch.object(google_calendar, 'SECRET', 'Utter/unit-test-google'):
            status = google_calendar.status()
        self.assertEqual((status['has_client'], status['connected']), (True, False))

    def test_lmstudio_entry_keeps_other_servers(self):
        config = Path(self.tmp.name) / '.lmstudio' / 'mcp.json'
        with mock.patch.object(lmstudio, 'CONFIG', config):
            self.assertFalse(lmstudio.status()['installed'])
            with self.assertRaisesRegex(RuntimeError, 'not installed'):
                lmstudio.add()
            config.parent.mkdir()
            config.write_text(json.dumps({'mcpServers': {'other': {'url': 'https://x'}}}))
            lmstudio.add()
            servers = json.loads(config.read_text())['mcpServers']
            self.assertEqual(servers['other'], {'url': 'https://x'})
            self.assertEqual(servers['utter']['args'], ['-m', 'utter.mcp_server'])
            self.assertEqual(servers['utter']['env']['UTTER_MCP_CLIENT'], 'lmstudio')
            with mock.patch.object(lmstudio, '_app_running', return_value=False):
                status = lmstudio.status()
            self.assertEqual({k: status[k] for k in ('installed', 'added', 'up_to_date', 'error', 'running', 'models')},
                             {'installed': True, 'added': True, 'up_to_date': True, 'error': None,
                              'running': False, 'models': None})
            lmstudio.remove()
            self.assertEqual(json.loads(config.read_text())['mcpServers'], {'other': {'url': 'https://x'}})
            config.write_text('{broken')
            self.assertIn('not valid JSON', lmstudio.status()['error'])
            with self.assertRaisesRegex(ValueError, 'not valid JSON'):
                lmstudio.add()
            self.assertEqual(config.read_text(), '{broken')

    def test_lmstudio_loaded_models_only_while_the_app_runs(self):
        ps = json.dumps([{'type': 'llm', 'modelKey': 'qwen', 'displayName': 'Qwen 9B', 'contextLength': 8192,
                          'trainedForToolUse': True}, {'type': 'embedding', 'modelKey': 'nomic'}])
        lms = Path(self.tmp.name) / 'lms.exe'
        lms.write_text('')
        with mock.patch.object(lmstudio, 'LMS', lms), mock.patch.object(lmstudio, '_models_cache', (0.0, None)), \
                mock.patch.object(lmstudio.subprocess, 'run') as run:
            run.return_value = mock.Mock(stdout=ps)
            with mock.patch.object(lmstudio, '_app_running', return_value=False):
                self.assertIsNone(lmstudio.loaded_models(max_age=0))
            run.assert_not_called()   # lms would start LM Studio's service
            with mock.patch.object(lmstudio, '_app_running', return_value=True):
                self.assertEqual(lmstudio.loaded_models(max_age=0),
                                 [{'name': 'Qwen 9B', 'key': 'qwen', 'context': 8192, 'tools': True}])

    def test_agents_status_reads_each_generated_config(self):
        home = Path(self.tmp.name)
        codex_cfg, claude_cfg, pi_cfg = home / 'config.toml', home / '.claude.json', home / 'mcp.json'
        fake = [('codex', 'Codex', codex_cfg, 'mcp_servers'), ('claude', 'Claude Code', claude_cfg, 'mcpServers'),
                ('pi', 'Pi', pi_cfg, 'mcpServers')]
        python = str(local_state.python_exe())
        utter = {'command': python, 'args': ['-m', 'utter.mcp_server']}
        with mock.patch.object(agents, 'AGENTS', fake):
            self.assertEqual([a['added'] for a in agents.status()], [False, False, False])
            codex_cfg.write_text('[mcp_servers.utter]\ncommand = "{}"\nargs = ["-m", "utter.mcp_server"]\n'
                                 .format(python.replace('\\', '\\\\')))
            claude_cfg.write_text(json.dumps({'mcpServers': {'utter': utter}, 'other': 1}))
            pi_cfg.write_text(json.dumps({'mcpServers': {'utter': {**utter, 'command': 'C:\\other\\python.exe',
                                                                   'enabled': False}}}))
            codex, claude, pi = agents.status()
            self.assertEqual((codex['added'], codex['up_to_date'], claude['up_to_date']), (True, True, True))
            self.assertEqual((pi['added'], pi['enabled'], pi['up_to_date']), (True, False, False))
            pi_cfg.write_text('{broken')
            self.assertIn('could not be read', agents.status()[2]['error'])

    def test_simplify_event(self):
        event = google_calendar.simplify_event({
            'summary': 'Design review', 'start': {'dateTime': '2026-10-25T14:00:00+00:00'},
            'end': {'dateTime': '2026-10-25T15:00:00+00:00'},
            'attendees': [{'email': 'sam@example.com', 'displayName': 'Sam'}, {'email': 'room@x', 'resource': True}],
            'hangoutLink': 'https://meet.google.com/abc'}, 'Work')
        self.assertEqual(event['attendees'], ['Sam'])
        self.assertFalse(event['all_day'])
        self.assertEqual(event['calendar'], 'Work')
        all_day = google_calendar.simplify_event({'start': {'date': '2026-10-25'}, 'end': {'date': '2026-10-26'}}, 'x')
        self.assertTrue(all_day['all_day'])
        self.assertEqual(all_day['title'], '(no title)')


class McpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'hot.txt').write_text('Claude\n', encoding='utf-8')
        (root / 'hot-rule.txt').write_text('cloud = Claude\n', encoding='utf-8')
        transcripts = root / 'transcripts'
        _save(transcripts, 'a', T0, 'ask cloud about 100% done')
        _save(transcripts, 'b', T0 + 600, 'second note', 'notepad.exe', 'saved')
        _save(transcripts, 'c', T0 + 7200, 'much later')
        for target, value in ((mcp_server, ('DB_PATH', transcripts / 'transcripts.sqlite3')),
                              (mcp_server, ('DICTIONARY_ROOT', root)),
                              (local_state, ('STATE_DIR', root / 'state')),
                              (google_calendar, ('SECRET', 'Utter/unit-test-google'))):
            patcher = mock.patch.object(target, *value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def call(self, tool, args=None):
        async def run():
            async with Client(mcp_server.server) as client:
                result = await client.call_tool(tool, args or {})
                self.assertFalse(result.is_error, result.content)
                return json.loads(result.content[0].text)
        return asyncio.run(run())

    def test_tools_are_all_read_only(self):
        async def run():
            async with Client(mcp_server.server) as client:
                return (await client.list_tools()).tools
        tools = asyncio.run(run())
        self.assertEqual({t.name for t in tools}, {'search_dictations', 'get_insights', 'get_dictionary', 'list_meetings'})
        self.assertTrue(all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools))

    def test_search_by_text_and_time(self):
        everything = self.call('search_dictations')
        self.assertEqual([d['text'] for d in everything['dictations']], ['much later', 'second note', 'ask cloud about 100% done'])
        self.assertEqual(everything['dictations'][1], {**everything['dictations'][1], 'typed': False, 'app': 'Notepad'})
        self.assertEqual(self.call('search_dictations', {'query': '100%'})['count'], 1)
        self.assertEqual(self.call('search_dictations', {'query': '_'})['count'], 0)   # LIKE wildcards are literal
        start = datetime.fromtimestamp(T0 + 300).astimezone().isoformat()
        end = datetime.fromtimestamp(T0 + 3600).astimezone().isoformat()
        self.assertEqual([d['text'] for d in self.call('search_dictations', {'start': start, 'end': end})['dictations']],
                         ['second note'])
        self.assertEqual(self.call('search_dictations', {'limit': 1})['count'], 1)
        self.assertTrue((Path(self.tmp.name) / 'state' / 'mcp-activity-other.json').exists())
        with mock.patch.dict('os.environ', {'UTTER_MCP_CLIENT': 'lmstudio'}), \
                mock.patch.object(lmstudio, 'loaded_models', return_value=[{'name': 'Qwen 9B'}]):
            self.call('get_dictionary')
        self.assertEqual(local_state.last_mcp_use('lmstudio')['models'], ['Qwen 9B'])

    def test_insights_and_dictionary(self):
        insights = self.call('get_insights')
        self.assertEqual(insights['dictations'], 3)
        self.assertIn('words_per_day', insights)
        dictionary = self.call('get_dictionary')
        self.assertEqual(dictionary['words'], [{'word': 'Claude', 'source': 'manual'}])
        self.assertEqual(dictionary['replacements'][0]['heard'], 'cloud')

    def test_meetings_need_the_calendar_and_include_dictations(self):
        self.assertIn('not connected', self.call('list_meetings')['error'])
        start = datetime.fromtimestamp(T0 - 60, timezone.utc)
        meetings = [{'title': 'Standup', 'all_day': False, 'start': start.isoformat(),
                     'end': (start + timedelta(minutes=5)).isoformat()},
                    {'title': 'Holiday', 'all_day': True, 'start': '2026-10-25', 'end': '2026-10-26'}]
        mcp_server.attach_dictations(meetings)
        self.assertEqual([d['text'] for d in meetings[0]['dictations']], ['ask cloud about 100% done'])
        self.assertNotIn('dictations', meetings[1])

    def test_stats_dictations_without_an_archive(self):
        self.assertEqual(stats.dictations(Path(self.tmp.name) / 'missing.sqlite3'), [])


if __name__ == '__main__':
    unittest.main()
