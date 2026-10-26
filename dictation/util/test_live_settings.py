import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from util import app_settings


class FakeConfig:
    llm_enabled = False
    hot = True
    dictation_sounds = False
    shortcuts = [
        {'key': 'ctrl_r', 'type': 'keyboard', 'suppress': True, 'hold_mode': False, 'enabled': True},
        {'key': 'x2', 'type': 'mouse', 'suppress': True, 'hold_mode': False, 'enabled': True},
    ]


class AppSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'settings.json'

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_validates_and_persists(self):
        app_settings.update({'llm_enabled': 1, 'display_name': 'Alex'}, self.path)
        self.assertEqual(app_settings.load(self.path), {'llm_enabled': True, 'display_name': 'Alex'})
        with self.assertRaises(KeyError):
            app_settings.update({'addr': '0.0.0.0'}, self.path)

    def test_load_drops_unknown_and_invalid_values(self):
        self.path.write_text(json.dumps({'llm_min_chars': 'many', 'hot': False, 'addr': 'x'}), encoding='utf-8')
        self.assertEqual(app_settings.load(self.path), {'hot': False})

    def test_missing_or_broken_file_means_no_overrides(self):
        self.assertEqual(app_settings.load(self.path), {})
        self.path.write_text('{broken', encoding='utf-8')
        self.assertEqual(app_settings.load(self.path), {})

    def test_shortcut_overrides_only_change_enabled_and_hold_mode(self):
        merged = app_settings.merge_shortcuts(FakeConfig.shortcuts, [
            {'key': 'x2', 'type': 'mouse', 'enabled': False, 'suppress': False},
            {'key': 'f12', 'type': 'keyboard', 'enabled': True},
        ])
        self.assertEqual([s['enabled'] for s in merged], [True, False])
        self.assertTrue(merged[1]['suppress'])
        self.assertEqual(len(merged), 2)

    def test_apply_to_config_reports_changes(self):
        config = type('Config', (FakeConfig,), {})
        changed = app_settings.apply_to_config(config, {'llm_enabled': True, 'hot': True, 'display_name': 'x'})
        self.assertEqual(changed, ['llm_enabled'])
        self.assertTrue(config.llm_enabled)


class RuntimeSettingsTests(unittest.TestCase):
    def test_only_keys_changed_in_file_are_applied(self):
        from util.client import runtime_status
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            config = type('Config', (FakeConfig,), {})
            with mock.patch.object(app_settings, 'SETTINGS_PATH', path), \
                    mock.patch.object(runtime_status, 'Config', config):
                status = runtime_status.RuntimeStatus()
                app_settings.update({'llm_enabled': False}, path)
                status.apply_settings_at_startup()
                config.llm_enabled = True          # runtime double-tap toggle
                time.sleep(0.02)
                app_settings.update({'llm_enabled': False, 'dictation_sounds': True}, path)
                self.assertTrue(status._check_settings())
                self.assertTrue(config.dictation_sounds)
                self.assertTrue(config.llm_enabled)  # untouched: not changed in the file
                self.assertFalse(status._check_settings())


class FeedbackTests(unittest.TestCase):
    def _run_events(self, recording_after_threshold, events):
        from util.client.audio import feedback
        from util.client.state import get_state
        state = get_state()
        played, muted = [], []
        fake_muter = mock.Mock()
        fake_muter.mute.side_effect = lambda *args: muted.append('mute')
        fake_muter.restore.side_effect = lambda: muted.append('restore')
        config = type('Config', (), {'dictation_sounds': True, 'mute_while_dictating': True})
        with mock.patch.object(feedback, '_play', played.append), \
                mock.patch.object(feedback, '_Muter', return_value=fake_muter), \
                mock.patch.object(feedback, 'Config', config):
            fb = feedback.DictationFeedback()
            start = time.time()
            state.recording, state.recording_start_time = True, start
            fb.started(start, 0.05)
            if not recording_after_threshold:
                state.recording = False
            time.sleep(0.2)
            for event in events:
                getattr(fb, event)()
            fb.shutdown()
        state.recording, state.recording_start_time = False, 0.0
        return played, muted

    def test_confirmed_recording_plays_sounds_and_restores_audio(self):
        from util.client.audio import feedback
        played, muted = self._run_events(True, ['stopped'])
        self.assertEqual(played, [feedback.START_SOUND, feedback.STOP_SOUND])
        self.assertEqual(muted[0], 'mute')
        self.assertIn('restore', muted)

    def test_key_tap_cancelled_before_threshold_is_silent(self):
        played, muted = self._run_events(False, ['cancelled'])
        self.assertEqual(played, [])
        self.assertNotIn('mute', muted)


if __name__ == '__main__':
    unittest.main()
