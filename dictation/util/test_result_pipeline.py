import asyncio
import contextlib
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


class ResultPipelineTests(unittest.TestCase):
    def _run(self, typeable, locked=False, fail_output=False):
        """Process one final result; returns (typed texts, archive row, watcher calls, toasts).
        locked: every archive write fails as when another program holds the database.
        fail_output: typing raises before anything reaches the app."""
        from config_client import ClientConfig as Config
        from util.client.diary import archive
        from util.client.output import result_processor as rp
        from util.client.state import get_state

        typed, observed, toasts = [], [], []

        async def fake_output(self, text, paste=None):
            if fail_output:
                raise RuntimeError('output failed')
            typed.append(text)

        async def run(tmp):
            state = get_state()
            state.initialize()
            watcher = mock.Mock()
            watcher.observe.side_effect = lambda text, process: observed.append(text)
            stack = contextlib.ExitStack()
            if locked:
                for name in ('save_recognition', 'save_output', 'save_details'):
                    stack.enter_context(mock.patch.object(
                        rp, name, side_effect=sqlite3.OperationalError('database is locked')))
            with mock.patch.object(archive, 'ROOT', Path(tmp)), \
                    mock.patch.object(Config, 'save_audio', False), \
                    mock.patch.object(Config, 'llm_enabled', False), \
                    mock.patch.object(rp.TextOutput, 'output', fake_output), \
                    mock.patch.object(rp, 'get_active_window_info', return_value={'process_name': 'notepad.exe'}), \
                    mock.patch('util.client.output.target.check',
                               return_value=(True, '') if typeable else (False, 'a menu bar had focus, not a text box')), \
                    mock.patch('util.client.clipboard.safe_copy'), \
                    mock.patch('util.client.ui.toast', side_effect=lambda *a, **k: toasts.append(a[0])), \
                    mock.patch('util.client.learn.edit_watcher.get_edit_watcher', return_value=watcher), \
                    mock.patch('util.client.learn.reviewer.get_reviewer'), stack:
                processor = rp.ResultProcessor(state)
                now = time.time()
                await processor._handle_message(json.dumps({
                    'task_id': 'delivery-test', 'time_start': now, 'time_submit': now, 'time_complete': now + 0.1,
                    'is_final': True, 'duration': 1.0, 'text': 'Send the report today.'}))

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(run(tmp))
            row = None
            if (Path(tmp) / 'transcripts.sqlite3').exists():
                db = sqlite3.connect(Path(tmp) / 'transcripts.sqlite3')
                row = db.execute('SELECT output_text, delivery FROM dictations').fetchone()
                db.close()
        return typed, row, observed, toasts

    def test_a_locked_archive_still_types_the_dictation(self):
        # "database is locked" while another program read the archive once dropped a dictation.
        typed, row, _, _ = self._run(typeable=True, locked=True)
        self.assertEqual(typed, ['Send the report today'])
        self.assertIsNone(row)

    def test_an_error_before_typing_keeps_the_text_on_the_clipboard(self):
        typed, _, _, toasts = self._run(typeable=True, fail_output=True)   # no exception escapes
        self.assertEqual(typed, [])
        self.assertIn('something went wrong before it was typed', toasts[0])

    def test_nowhere_to_type_saves_instead_of_typing(self):
        typed, (output, delivery), observed, toasts = self._run(typeable=False)
        self.assertEqual(typed, [])
        self.assertEqual((output, delivery), ('Send the report today', 'saved'))
        self.assertEqual(observed, [])
        self.assertIn('Saved in Utter', toasts[0])

    def test_text_box_gets_typed_and_marked_typed(self):
        typed, (output, delivery), observed, toasts = self._run(typeable=True)
        self.assertEqual(typed, ['Send the report today'])
        self.assertEqual(delivery, 'typed')
        self.assertEqual(toasts, [])

    def test_final_result_records_fixes_app_and_starts_learning(self):
        from config_client import ClientConfig as Config
        from util.client.diary import archive
        from util.client.output import result_processor as rp
        from util.client.state import get_state
        from util.hotword import get_hotword_manager

        observed = []
        typed = []

        async def fake_output(self, text, paste=None):
            typed.append(text)

        async def run(tmp):
            state = get_state()
            state.initialize()
            manager = get_hotword_manager()
            manager.phoneme_corrector.update_hotwords('Brightloop\n')
            manager.rule_corrector.update_rules('Cud = Claude\n')
            watcher = mock.Mock()
            watcher.observe.side_effect = lambda text, process: observed.append((text, process))
            with mock.patch.object(archive, 'ROOT', Path(tmp)), \
                    mock.patch.object(Config, 'save_audio', False), \
                    mock.patch.object(Config, 'llm_enabled', False), \
                    mock.patch.object(rp.TextOutput, 'output', fake_output), \
                    mock.patch.object(rp, 'get_active_window_info',
                                      return_value={'process_name': 'notepad.exe', 'title': 'notes'}), \
                    mock.patch('util.client.output.target.check', return_value=(True, '')), \
                    mock.patch('util.client.learn.edit_watcher.get_edit_watcher', return_value=watcher), \
                    mock.patch('util.client.learn.reviewer.get_reviewer'):
                processor = rp.ResultProcessor(state)
                now = time.time()
                message = {'task_id': 'pipeline-test', 'time_start': now, 'time_submit': now,
                           'time_complete': now + 0.2, 'is_final': True, 'duration': 2.0,
                           'text': 'Ask Cud about bright loop.'}
                await processor._handle_message(json.dumps(message))

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(run(tmp))
            db = sqlite3.connect(Path(tmp) / 'transcripts.sqlite3')
            raw, output, app, fixes = db.execute(
                'SELECT raw_text, output_text, app_process, fixes FROM dictations').fetchone()
            db.close()

        self.assertEqual(raw, 'Ask Cud about bright loop.')
        self.assertEqual(typed, ['Ask Claude about Brightloop'])
        self.assertEqual(output, 'Ask Claude about Brightloop')
        self.assertEqual(app, 'notepad.exe')
        kinds = {(f['kind'], f['from'], f['to']) for f in json.loads(fixes)}
        self.assertIn(('rule', 'Cud', 'Claude'), kinds)
        self.assertIn(('dictionary', 'bright loop', 'Brightloop'), kinds)
        self.assertEqual(observed, [('Ask Claude about Brightloop', 'notepad.exe')])


if __name__ == '__main__':
    unittest.main()
