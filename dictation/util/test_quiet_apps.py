import tempfile
import unittest
from pathlib import Path
from unittest import mock

from util import app_settings
from util.client.audio import feedback


class FakeVolume:
    def __init__(self, level=1.0, muted=False):
        self.level, self.muted = level, muted

    def GetMute(self):
        return self.muted

    def SetMute(self, value, _):
        self.muted = bool(value)

    def GetMasterVolume(self):
        return self.level

    def SetMasterVolume(self, level, _):
        self.level = level


class FakeSession:
    def __init__(self, pid, name, volume):
        self.ProcessId = pid
        self.Process = mock.Mock(**{'name.return_value': name})
        self.SimpleAudioVolume = volume


class QuietAppsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.marker = Path(self.tmp.name) / 'muted.json'
        self.spotify = FakeVolume(0.8)
        self.discord = FakeVolume(1.0)
        self.already_muted = FakeVolume(1.0, muted=True)
        self.sessions = [FakeSession(10, 'Spotify.exe', self.spotify), FakeSession(11, 'Discord.exe', self.discord),
                         FakeSession(12, 'chrome.exe', self.already_muted)]
        patches = [mock.patch.object(feedback, 'MUTED_PATH', self.marker),
                   mock.patch('pycaw.pycaw.AudioUtilities.GetAllSessions', return_value=self.sessions)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mute_all_and_restore_only_what_was_changed(self):
        muter = feedback._Muter()
        muter.mute('mute', media_only=False)
        self.assertTrue(self.spotify.muted and self.discord.muted)
        muter.restore()
        self.assertFalse(self.spotify.muted or self.discord.muted)
        self.assertTrue(self.already_muted.muted)          # was muted before; left alone
        self.assertFalse(self.marker.exists())

    def test_lower_keeps_music_playing_quietly_and_restores_its_level(self):
        muter = feedback._Muter()
        muter.mute('lower', media_only=False)
        self.assertAlmostEqual(self.spotify.level, 0.8 * feedback.LOWERED_LEVEL)
        self.assertFalse(self.spotify.muted)
        muter.restore()
        self.assertAlmostEqual(self.spotify.level, 0.8)

    def test_media_only_leaves_other_apps_alone(self):
        muter = feedback._Muter()
        muter.mute('mute', media_only=True)
        self.assertTrue(self.spotify.muted)
        self.assertFalse(self.discord.muted)

    def test_crash_recovery_restores_volume_and_mute(self):
        feedback._Muter().mute('lower', media_only=False)
        self.assertTrue(self.marker.exists())
        feedback._Muter.restore_after_crash()                # a new client after the old one died
        self.assertAlmostEqual(self.spotify.level, 0.8)
        self.assertFalse(self.marker.exists())

    def test_old_marker_format_still_unmutes(self):
        self.spotify.muted = True
        self.marker.write_text('[10]', encoding='utf-8')
        feedback._Muter.restore_after_crash()
        self.assertFalse(self.spotify.muted)


class QuietSettingTests(unittest.TestCase):
    def test_quiet_mode_only_accepts_known_values(self):
        kinds = {**app_settings.CLIENT_KEYS, **app_settings.APP_KEYS}
        self.assertEqual(app_settings._coerce('quiet_mode', 'lower', kinds), 'lower')
        with self.assertRaises(ValueError):
            app_settings._coerce('quiet_mode', 'loud', kinds)


if __name__ == '__main__':
    unittest.main()
