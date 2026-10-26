"""Offline checks for mic_diag.py: log parsing, capture matching, event parsing, classification.

Run from the repo root: .venv\Scripts\python.exe -B -m unittest discover -s skills/utter-stabilise/tests -v
"""
import array
import json
import sys
import tempfile
import unittest
import wave
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import mic_diag  # noqa: E402

LOG = """\
23:30:34.000 - client - INFO - [task.py:68] - [ctrl_r] Pressed: recording started
23:30:42.000 - client - INFO - [task.py:133] - [ctrl_r] Released: recording finished
23:30:43.142 - client - WARNING - [capture_log.py:131] - Audio lost: held 4.4s, mic delivered 2.25s, recognizer received 2.25s, first audio after 0.7s: microphone delivered no audio for part of the recording (device/Bluetooth)
23:30:43.500 - client - INFO - [result_processor.py:232] - Final result: Hello there, delay: 0.30s
23:50:21.000 - client - INFO - [task.py:68] - [ctrl_r] Pressed: recording started
23:50:25.000 - client - INFO - [task.py:133] - [ctrl_r] Released: recording finished
23:50:25.050 - client - WARNING - [capture_log.py:131] - Audio lost: held 3.14s, mic delivered 0.0s, recognizer received 0.0s, first audio after Nones: microphone delivered no audio for part of the recording (device/Bluetooth)
23:50:25.051 - client - WARNING - [recorder.py:204] - Skipping empty recording task, task_id=x
01:01:19.676 - client - INFO - [task.py:68] - [ctrl_r] Pressed: recording started
01:01:22.236 - client - INFO - [task.py:133] - [ctrl_r] Released: recording finished
01:01:22.428 - client - INFO - [result_processor.py:232] - Final result: , delay: 0.18s
01:02:00.000 - client - INFO - [task.py:68] - [ctrl_r] Pressed: recording started
01:02:02.000 - client - INFO - [task.py:133] - [ctrl_r] Released: recording finished
01:02:02.100 - client - WARNING - [capture_log.py:131] - Audio lost: held 2.0s, mic delivered 2.0s, recognizer received 0.5s, first audio after 0.05s: audio arrived but did not reach recognition (client bug); the full audio is in this capture
01:02:02.300 - client - INFO - [result_processor.py:232] - Final result: ok, delay: 0.18s
"""

EVENTS = """<Events>
<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><TimeCreated SystemTime='2026-10-25T23:29:30.1234567Z'/></System>
<EventData><Data Name='DeviceName'>AirPods Pro Hands-Free</Data><Data Name='flow'>1</Data><Data Name='NewState'>8</Data></EventData></Event>
<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><TimeCreated SystemTime='2026-10-25T23:29:30.5Z'/></System>
<EventData><Data Name='DeviceName'>AirPods Pro Hands-Free</Data><Data Name='Flow'>1</Data><Data Name='NewState'>1</Data></EventData></Event>
<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><TimeCreated SystemTime='2026-10-25T23:29:50Z'/></System>
<EventData><Data Name='DeviceName'>AirPods Pro Hands-Free</Data><Data Name='flow'>1</Data><Data Name='NewState'>1</Data></EventData></Event>
<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><TimeCreated SystemTime='2026-10-25T23:29:51Z'/></System>
<EventData><Data Name='DeviceName'>AirPods Pro</Data><Data Name='flow'>0</Data><Data Name='NewState'>1</Data></EventData></Event>
</Events>"""


def write_wav(path, samples):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(array.array('h', samples).tobytes())


class MicDiagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'logs').mkdir()
        (self.root / 'logs' / 'client_20261025.log').write_text(LOG, encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_parsing_rolls_over_midnight(self):
        recs = mic_diag.parse_logs(self.root / 'logs', date(2026, 10, 25))
        self.assertEqual([r.start for r in recs][2], datetime(2026, 10, 26, 1, 1, 19, 676000))
        self.assertEqual((recs[0].held, recs[0].delivered, recs[0].text), (4.4, 2.25, 'Hello there'))
        self.assertTrue(recs[1].skipped)
        self.assertEqual(recs[2].text, '')

    def test_classification_including_silent_capture(self):
        captures = self.root / 'appdata' / 'captures'
        captures.mkdir(parents=True)
        (captures / '20261026-010119.json').write_text(json.dumps({'held': 2.56, 'delivered': 2.55, 'verdict': 'ok'}))
        write_wav(captures / '20261026-010119.wav', [100, -150, 200] * 1000)       # peak ~0.006: silence
        recs = mic_diag.parse_logs(self.root / 'logs', date(2026, 10, 25))
        mic_diag.attach_captures(recs, captures)
        kinds = [mic_diag.classify(r) for r in recs]
        self.assertEqual(kinds, ['partial_audio', 'no_audio', 'silent_mic', 'client_bug'])
        self.assertLess(recs[2].peak, mic_diag.SILENT_PEAK)

    def test_empty_result_without_capture_is_unknown(self):
        rec = mic_diag.Recording(start=datetime(2026, 10, 26), text='')
        self.assertEqual(mic_diag.classify(rec), 'empty_result')
        rec.peak = 0.3
        self.assertEqual(mic_diag.classify(rec), 'empty_result')

    def test_endpoint_events_connects_and_activity(self):
        events = mic_diag.parse_endpoint_events(EVENTS)
        self.assertEqual(len(events), 4)
        self.assertEqual({e['flow'] for e in events}, {'1', '0'})       # 'Flow' and 'flow' both read
        connects = mic_diag.mic_connects(events, 'airpods')
        self.assertEqual(len(connects), 1)                               # one burst within a minute
        self.assertEqual(connects[0], events[2]['time'])
        after = events[0]['time'].replace(second=40)
        self.assertTrue(mic_diag.mic_active_at(events, 'AirPods', events[1]['time']))
        self.assertTrue(mic_diag.mic_active_at(events, 'AirPods', after))
        self.assertIsNone(mic_diag.mic_active_at(events, 'Jabra', after))

    def test_report_runs_without_event_log(self):
        original = mic_diag.read_endpoint_events
        mic_diag.read_endpoint_events = lambda: None
        try:
            self.assertEqual(mic_diag.report(self.root, days=10000, device='AirPods'), 0)
        finally:
            mic_diag.read_endpoint_events = original

    def test_missing_client_folder_is_blocked(self):
        self.assertEqual(mic_diag.main(['report', '--client', str(self.root / 'missing')]), 2)

    def test_patterns_match_the_clients_own_log_messages(self):
        # Fails if the client's wording changes without this script.
        client = Path(__file__).resolve().parents[3] / 'dictation' / 'util' / 'client'
        sources = {name: (client / path).read_text(encoding='utf-8') for name, path in (
            ('task', 'shortcut/task.py'), ('capture', 'audio/capture_log.py'), ('result', 'output/result_processor.py'))}
        self.assertIn('Pressed: recording started', sources['task'])
        self.assertIn('Released: recording finished', sources['task'])
        self.assertIn('Audio lost: held ', sources['capture'])
        self.assertIn('Final result: ', sources['result'])


if __name__ == '__main__':
    unittest.main()
