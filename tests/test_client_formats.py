"""The dictation client's file formats Utter depends on, checked against the client's own code in ../dictation.

The archive format is exercised with the client's own writer in test_api.py and test_stats.py.
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from utter import dictation, engine, meeting, summary

# Every setting the Utter page can save, with a value it really sends (app.js saveSetting / saveShortcuts).
UTTER_WRITES = {
    'display_name': 'Alex', 'theme': 'dark', 'start_engine_with_app': True,
    'audio_input_device': 'AirPods Pro', 'llm_enabled': True, 'llm_min_chars': 40, 'hot': True, 'hot_rule': True,
    'dictionary_context': False, 'auto_learn': True, 'auto_review': False, 'paste': True, 'copy_output_to_clipboard': False, 'save_audio': True,
    'recording_status_bar': True, 'dictation_sounds': False, 'mute_while_dictating': True, 'quiet_mode': 'lower',
    'quiet_media_only': True,
}
# Live status fields Utter reads (engine.client_status, the Home banner, Settings, the Notetaker).
STATUS_FIELDS = {'pid': int, 'updated_at': float, 'started_at': float, 'stopped': bool, 'recording': bool,
                 'connected': bool, 'microphone': dict, 'microphones': list, 'last_output_at': float,
                 'shortcuts': list, 'llm_enabled': bool, 'review': dict}


class SettingsFormatTests(unittest.TestCase):
    def setUp(self):
        from util import app_settings
        self.settings = app_settings
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'settings.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_setting_utter_saves_is_accepted_and_read_back(self):
        for key, value in UTTER_WRITES.items():
            with self.subTest(key=key):
                self.settings.update({key: value}, path=self.path)
                self.assertEqual(self.settings.load(self.path)[key], value)

    def test_shortcut_switches_round_trip_onto_the_configured_shortcuts(self):
        from config_client import ClientConfig
        configured = ClientConfig.shortcuts
        self.assertTrue(configured and all({'key', 'type'} <= set(s) for s in configured))
        change = [{'key': s['key'], 'type': s['type'], 'enabled': False, 'hold_mode': True} for s in configured]
        self.settings.update({'shortcuts': change}, path=self.path)
        merged = self.settings.merge_shortcuts(configured, self.settings.load(self.path)['shortcuts'])
        self.assertTrue(all(s['enabled'] is False and s['hold_mode'] is True for s in merged))

    def test_app_defaults_and_client_keys_utter_relies_on(self):
        self.assertLessEqual({'display_name', 'theme', 'start_engine_with_app'}, set(self.settings.APP_DEFAULTS))
        self.assertLessEqual(set(UTTER_WRITES) - set(self.settings.APP_DEFAULTS), set(self.settings.CLIENT_KEYS))


class StatusFormatTests(unittest.TestCase):
    """The client's real RuntimeStatus.snapshot(), with the live client state stood in."""

    def snapshot(self):
        state = types.SimpleNamespace(
            stream_manager=types.SimpleNamespace(selected_device=('AirPods Pro', 'WASAPI'), available_devices=['AirPods Pro']),
            is_connected=True, recording=False, last_output_time=1792809542.5)
        stubs = {
            'util.client': types.SimpleNamespace(logger=mock.Mock(), __path__=[]),
            'util.client.state': types.SimpleNamespace(get_state=lambda: state),
            'util.hotword': types.SimpleNamespace(get_hotword_manager=mock.Mock(side_effect=RuntimeError)),
            'util.client.learn': types.SimpleNamespace(__path__=[]),
            'util.client.learn.reviewer': types.SimpleNamespace(status={'last_run': None, 'error': None}),
        }
        with mock.patch.dict(sys.modules, stubs):
            spec = importlib.util.spec_from_file_location(
                'util.client.runtime_status', dictation.ROOT / 'util' / 'client' / 'runtime_status.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.RuntimeStatus().snapshot()

    def test_snapshot_has_every_field_utter_reads(self):
        snap = self.snapshot()
        for field, kind in STATUS_FIELDS.items():
            with self.subTest(field=field):
                self.assertIn(field, snap)
                self.assertIsInstance(snap[field], kind)
        self.assertEqual(snap['microphone']['name'], 'AirPods Pro')
        self.assertEqual(snap['pid'], os.getpid())

    def test_utter_reads_a_written_status_as_running(self):
        from util import app_settings
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'status.json'
            app_settings.write_json(path, self.snapshot())
            with mock.patch.object(app_settings, 'STATUS_PATH', path):
                client = engine.client_status()
        self.assertTrue(client['running'])
        self.assertEqual(client['microphone']['name'], 'AirPods Pro')


class DictionaryFormatTests(unittest.TestCase):
    def test_files_and_entries_utter_lists_and_edits(self):
        from util import dictionary_files as d
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = d.paths(root)
            self.assertLessEqual({'words', 'rules', 'learned_words', 'learned_rules'}, set(paths))
            d.add_word(paths['words'], 'Brightloop')
            self.assertTrue(d.add_rule(paths['rules'], 'cloud code', 'Claude Code'))
            self.assertIn('Brightloop', d.read_words(paths['words']))
            rule = d.read_rules(paths['rules'])[0]
            self.assertLessEqual({'heard', 'replacement', 'pattern'}, set(rule))
            self.assertEqual((rule['heard'], rule['replacement']), ('cloud code', 'Claude Code'))
            self.assertIn('Brightloop', d.all_words(root))
            self.assertTrue(d.remove_word(paths['words'], 'Brightloop'))
            self.assertTrue(d.remove_rule(paths['rules'], rule['pattern']))


class WordCountTests(unittest.TestCase):
    def test_word_counts_for_insights(self):
        from util.text_metrics import count_words
        self.assertEqual(count_words('ask cloud'), 2)
        self.assertEqual(count_words("we're shipping the project"), 4)


class SpeechServerMessageTests(unittest.TestCase):
    """The Notetaker talks to the speech server directly, with the dictation client's messages."""

    def test_notetaker_message_is_what_the_server_reads(self):
        from util.protocol import AudioMessage, RecognitionResult
        sent = []

        class FakeSocket:
            def send(self, raw):
                sent.append(json.loads(raw))

            def recv(self, timeout=None):
                result = RecognitionResult(task_id=sent[-1]['task_id'], is_final=True, duration=1.0, time_start=0,
                                           time_submit=0, time_complete=0, text=' hello ')
                return result.to_json()

        transcriber = meeting.Transcriber.__new__(meeting.Transcriber)
        transcriber.context = 'Jordan Lee'
        text = transcriber._recognize(FakeSocket(), np.zeros(1600, dtype=np.float32))
        self.assertEqual(text, 'hello')
        message = AudioMessage.from_dict(sent[0])            # the client's own parser accepts it
        self.assertTrue(message.is_final)
        self.assertEqual(message.source, 'mic')
        # the speech server reads these fields directly
        self.assertLessEqual({'task_id', 'source', 'is_final', 'data', 'time_start', 'seg_duration', 'seg_overlap',
                              'context'}, set(sent[0]))


class LocalAIConfigTests(unittest.TestCase):
    def test_ai_polish_config_has_what_the_local_summarizer_uses(self):
        config = summary.local_config()
        for name in ('provider', 'model', 'api_url', 'api_key', 'extra_options'):
            with self.subTest(name=name):
                self.assertTrue(hasattr(config, name))


if __name__ == '__main__':
    unittest.main()
