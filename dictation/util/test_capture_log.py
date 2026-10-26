import json
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from util.client.audio import capture_log

BLOCK = np.zeros((2400, 1), dtype=np.float32)   # 50 ms at 48 kHz


def capture(seconds_held, first_block_after, recognised):
    """Simulate a recording: blocks start late, the recorder reports what it sent."""
    start = time.time() - seconds_held
    capture_log.begin(start, ['Headset (AirPods Pro)', 'MME'])
    cap = capture_log._current
    t = start + first_block_after
    while t < start + seconds_held:
        cap['times'].append(t)
        cap['blocks'].append(BLOCK[:, 0])
        cap['rate'] = 48000
        t += 0.05
    cap['ended'] = start + seconds_held
    cap['recorder_seconds'] = recognised
    return cap


class CaptureLogTests(unittest.TestCase):
    def test_late_microphone_is_blamed_on_the_device(self):
        report = capture_log.analyse(capture(21.5, 15.0, 6.45))
        self.assertEqual(report['first_audio_after'], 15.0)
        self.assertIn('device', report['verdict'])
        self.assertEqual(report['gaps'][0][0], 0.0)

    def test_audio_lost_after_capture_is_blamed_on_the_client(self):
        report = capture_log.analyse(capture(21.5, 0.05, 6.45))
        self.assertIn('client bug', report['verdict'])

    def test_complete_recording_is_ok(self):
        report = capture_log.analyse(capture(10.0, 0.05, 9.95))
        self.assertEqual(report['verdict'], 'ok')
        self.assertEqual(report['gaps'], [])

    def test_writes_wav_and_report_and_keeps_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(capture_log, 'CAPTURE_DIR', Path(tmp)), \
                    mock.patch.object(capture_log, '_notify') as notify:
                cap = capture(2.0, 0.05, 0.5)
                capture_log._write(cap)
                stem = Path(tmp) / Path(sorted(p.name for p in Path(tmp).glob('*.json'))[0]).stem
                report = json.loads(stem.with_suffix('.json').read_text(encoding='utf-8'))
                with wave.open(str(stem.with_suffix('.wav'))) as w:
                    self.assertEqual(w.getframerate(), 16000)
                    self.assertAlmostEqual(w.getnframes() / 16000, report['delivered'], places=1)
                notify.assert_called_once()                 # 1.45 s lost -> the person is told

    def test_tap_is_discarded(self):
        capture_log.begin(time.time(), None)
        capture_log.end(cancelled=True)
        self.assertIsNone(capture_log._current)


if __name__ == '__main__':
    unittest.main()
