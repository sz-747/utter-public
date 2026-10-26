import unittest

from util import app_settings
from util.client.audio.devices import available_names, matches_preferred, rank


def _choice(name, api='MME'):
    return (0, 0, 0, {'name': name}, api)


class RankTests(unittest.TestCase):
    def test_automatic_prefers_any_headphones_then_usb_then_default(self):
        self.assertEqual(rank('Headset (AirPods Pro)', False), 1)
        self.assertEqual(rank('Headset Microphone (Jabra Evolve2)', False), 1)
        self.assertEqual(rank('Microphone (Galaxy Buds2 Pro Hands-Free)', False), 1)
        self.assertEqual(rank('Microphone (USB Audio Device)', False), 2)
        self.assertEqual(rank('Microphone Array (Realtek)', True), 3)
        self.assertEqual(rank('Microphone Array (Realtek)', False), 4)

    def test_preferred_mic_wins_even_over_headphones(self):
        self.assertEqual(rank('Microphone (USB Audio Device)', False, 'Microphone (USB Audio Device)'), 0)
        self.assertLess(rank('Microphone (Yeti)', False, 'Microphone (Yeti)'), rank('Headset (AirPods Pro)', False, 'Microphone (Yeti)'))

    def test_missing_preferred_mic_falls_back_to_automatic(self):
        self.assertEqual(rank('Headset (AirPods Pro)', False, 'Microphone (Yeti)'), 1)

    def test_truncated_mme_names_match_the_full_name(self):
        self.assertTrue(matches_preferred('Headset Microphone (Jabra Evolv', 'Headset Microphone (Jabra Evolve2 65)'))
        self.assertFalse(matches_preferred('Microphone (Yeti)', 'Headset (AirPods Pro)'))

    def test_one_entry_per_physical_mic_with_the_full_name(self):
        names = available_names([
            _choice('Headset (AirPods Pro)'), _choice('Headset (AirPods Pro)', 'Windows DirectSound'),
            _choice('Headset Microphone (Jabra Evolv'), _choice('Headset Microphone (Jabra Evolve2 65)', 'Windows WASAPI'),
            _choice('Microsoft Sound Mapper - Input'), _choice('Primary Sound Capture Driver', 'Windows DirectSound'),
        ])
        self.assertEqual(names, ['Headset (AirPods Pro)', 'Headset Microphone (Jabra Evolve2 65)'])


class PreferredMicSettingTests(unittest.TestCase):
    def test_empty_or_missing_means_automatic(self):
        kinds = {**app_settings.CLIENT_KEYS, **app_settings.APP_KEYS}
        self.assertIsNone(app_settings._coerce('audio_input_device', None, kinds))
        self.assertIsNone(app_settings._coerce('audio_input_device', '  ', kinds))
        self.assertEqual(app_settings._coerce('audio_input_device', ' Headset (AirPods Pro) ', kinds),
                         'Headset (AirPods Pro)')


if __name__ == '__main__':
    unittest.main()
