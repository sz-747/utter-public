import unittest

import numpy as np

from util.client.audio import levels


def tone(freq, amplitude, rate=48000, seconds=0.05):
    t = np.arange(int(rate * seconds)) / rate
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32).reshape(-1, 1)


class LevelsTests(unittest.TestCase):
    def setUp(self):
        levels.reset(voice=True)

    def test_silence_keeps_bars_flat(self):
        levels.update(np.zeros((2400, 1), dtype=np.float32), 48000)
        self.assertTrue(np.all(levels.get() < 0.01))

    def test_louder_voice_raises_the_bars(self):
        levels.update(tone(200, 0.01), 48000)
        quiet = levels.get().max()
        levels.update(tone(200, 0.3), 48000)
        self.assertGreater(levels.get().max(), quiet)

    def _settle(self, freq, amplitude, blocks=5):
        for _ in range(blocks):
            levels.update(tone(freq, amplitude), 48000)
        return levels.get().max()

    def test_a_slightly_raised_voice_clearly_lifts_the_bars(self):
        normal = self._settle(120, 0.02)          # headset-level normal speech, about -37 dBFS
        raised = levels.update(tone(120, 0.04), 48000) or levels.get().max()   # +6 dB: raised, not a shout
        self.assertGreater(normal, 0.3)           # normal speech is visible, not a sliver
        self.assertGreater(raised - normal, 0.25)

    def test_a_higher_pitch_lifts_the_bars_at_the_same_loudness(self):
        usual = self._settle(110, 0.02)
        higher = levels.update(tone(170, 0.02), 48000) or levels.get().max()
        self.assertGreater(higher - usual, 0.2)

    def test_pitch_moves_which_bars_rise(self):
        levels.update(tone(150, 0.3), 48000)
        low = levels.get()
        levels.reset()
        levels.update(tone(2500, 0.3), 48000)
        high = levels.get()
        self.assertEqual(int(np.argmax(low)), 0)                 # low voice: first band (middle bars)
        self.assertEqual(int(np.argmax(high)), levels.BANDS - 1)  # high pitch: last band (outer bars)


class StallTests(unittest.TestCase):
    def test_slow_start_and_dropouts_count_as_stalled(self):
        import time
        levels.reset()
        self.assertFalse(levels.stalled(threshold=0.2))            # just pressed: give it a moment
        time.sleep(0.25)
        self.assertTrue(levels.stalled(threshold=0.2))             # nothing arrived yet: slow start
        levels.update(tone(200, 0.1), 48000)
        self.assertFalse(levels.stalled(threshold=0.2))            # audio flowing
        time.sleep(0.25)
        self.assertTrue(levels.stalled(threshold=0.2))             # Bluetooth dropout


class TypingTargetTests(unittest.TestCase):
    def test_only_clear_non_text_focus_counts_as_nowhere(self):
        from util.client.output.target import classify
        self.assertEqual(classify('Progman', None)[0], False)              # desktop
        self.assertEqual(classify('Shell_TrayWnd', 50000)[0], False)       # taskbar
        self.assertEqual(classify('Notepad', 50010)[0], False)             # Alt -> menu bar
        self.assertIn('menu bar', classify('Notepad', 50010)[1])
        self.assertEqual(classify('Notepad', 50004)[0], True)              # edit box
        self.assertEqual(classify('CASCADIA_HOSTING_WINDOW_CLASS', 50033)[0], True)  # terminal pane
        self.assertEqual(classify('Chrome_WidgetWin_1', 50030)[0], True)   # browser document
        self.assertEqual(classify(None, None)[0], True)                    # unknown: type as before


if __name__ == '__main__':
    unittest.main()
