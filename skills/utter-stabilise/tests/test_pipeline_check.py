"""Offline checks for pipeline_check.py: text comparison, local resources and doctor's verdicts.

Run from the repo root: .venv\Scripts\python.exe -B -m unittest discover -s skills/utter-stabilise/tests -v
"""
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pipeline_check as pc  # noqa: E402


class TextTests(unittest.TestCase):
    def test_punctuation_case_and_spacing_do_not_count(self):
        self.assertEqual(pc.cer('Hello, World!', 'hello world'), 0)

    def test_error_rate_counts_edits_against_the_reference(self):
        self.assertAlmostEqual(pc.cer('abcx', 'abcd'), 0.25)
        self.assertEqual(pc.cer('', 'abcd'), 1)

    def test_the_bundled_sample_exists(self):
        self.assertTrue(pc.SAMPLE.is_file())

    def test_sound_alike_verdict_checks_both_words(self):
        self.assertEqual(pc.verdict('Ask Codex today', 'codecs', 'Codex'), 'right')
        self.assertEqual(pc.verdict('Ask codecs today', 'codecs', 'Codex'), 'wrong')
        self.assertEqual(pc.verdict('Ask someone today', 'codecs', 'Codex'), 'other')

    def test_only_live_distinct_corrections_are_checked(self):
        pairs = [('codecs', 'Codex'), ('codecs', 'Codex'), ('scale', 'Scala'), ('word', 'word')]
        self.assertEqual(pc.live_pairs(pairs, {'Codex'}, []), [('codecs', 'Codex')])


FOREVER = '2319-02-09T10:56:52.774579607Z'      # what Ollama reports for keep_alive -1
PINNED = [{'name': 'other-job:4b', 'size_vram': 5722928578, 'expires_at': FOREVER},
          {'name': 'polish:latest', 'size_vram': 5344120012, 'expires_at': '2026-10-30T12:09:36Z'}]


class ResourceTests(unittest.TestCase):
    def test_a_full_gpu_fails_and_names_the_models_kept_forever(self):
        ok, detail = pc.resource_verdict((15255, 16303), PINNED)
        self.assertFalse(ok)
        self.assertIn('94%', detail)
        self.assertIn('other-job:4b 5.7 GB (kept forever)', detail)
        self.assertIn('`ollama stop other-job:4b`', detail)
        self.assertNotIn('ollama stop polish', detail)

    def test_room_on_the_gpu_passes(self):
        ok, detail = pc.resource_verdict((13985, 16303), PINNED)
        self.assertTrue(ok)
        self.assertIn('86%', detail)

    def test_no_nvidia_smi_is_a_skip(self):
        ok, detail = pc.resource_verdict(None, [])
        self.assertIsNone(ok)
        self.assertIn('Ollama holds nothing', detail)


def fake_client(reply, accepted=True):
    """The client modules doctor imports, with a polish model that returns `reply`."""
    role = types.SimpleNamespace(provider='openai', api_url='http://127.0.0.1:1/v1', model='m')
    handler = mock.Mock(**{'detect_role.return_value': (role, 'heard'), 'process.return_value': (reply, 1, 0.1)})
    pool = types.SimpleNamespace(api_url_for=lambda provider, url: url)
    guard = mock.Mock(return_value=types.SimpleNamespace(accepted=accepted, reason='too long'))
    return {
        'util': types.SimpleNamespace(app_settings=types.SimpleNamespace(load=lambda: {'llm_enabled': True})),
        'util.app_settings': types.SimpleNamespace(load=lambda: {'llm_enabled': True}),
        'config_client': types.SimpleNamespace(ClientConfig=types.SimpleNamespace(llm_enabled=True)),
        'util.llm.llm_client_pool': types.SimpleNamespace(ClientPool=pool, local_server_listening=lambda url: True),
        'util.llm.llm_cleanup_guard': types.SimpleNamespace(validate_cleanup_output=guard),
        'util.llm.llm_handler': types.SimpleNamespace(LLMHandler=lambda: handler),
    }


class DoctorTests(unittest.TestCase):
    def run_doctor(self, listening=True, heard=pc.SAMPLE_TEXT, reply='This is the check.', accepted=True,
                   gpu=(4000, 16303), recognition_seconds=0.0):
        server = mock.Mock(host='127.0.0.1', port=6016, **{'listening.return_value': listening})
        server.transcribe.side_effect = lambda pcm: (clock.append(clock[-1] + recognition_seconds), heard)[1]
        clock = [100.0]
        out = io.StringIO()
        with mock.patch.object(pc, 'Server', return_value=server), mock.patch.object(pc, 'read_wav', return_value=[]), \
                mock.patch.object(pc, 'gpu_memory', return_value=gpu), mock.patch.object(pc, 'ollama_loaded', return_value=PINNED), \
                mock.patch.object(pc.time, 'time', side_effect=lambda: clock[-1]), \
                mock.patch.dict(sys.modules, fake_client(reply, accepted)), redirect_stdout(out):
            code = pc.doctor()
        return code, out.getvalue()

    def test_a_healthy_pipeline_passes(self):
        code, out = self.run_doctor()
        self.assertEqual(code, 0, out)
        self.assertIn('Result: ok', out)

    def test_server_down_stops_before_recognition(self):
        code, out = self.run_doctor(listening=False)
        self.assertEqual(code, 1)
        self.assertIn('Result: server_down', out)

    def test_misrecognition_is_named(self):
        code, out = self.run_doctor(heard='completely different words')
        self.assertIn('Result: recognition_wrong', out)

    def test_slow_recognition_on_a_full_gpu_is_named(self):
        code, out = self.run_doctor(gpu=(15255, 16303), recognition_seconds=5.7)
        self.assertEqual(code, 1)
        self.assertIn('FAIL  recognition speed: 5.7 s', out)
        self.assertIn('FAIL  local resources', out)
        self.assertIn('Result: recognition_slow', out)

    def test_a_full_gpu_alone_is_named(self):
        code, out = self.run_doctor(gpu=(15255, 16303))
        self.assertIn('Result: resources_full', out)

    def test_an_empty_polish_reply_fails(self):
        # Qwen 3.5 on Ollama with think unset spent 11 s thinking and returned nothing.
        code, out = self.run_doctor(reply='')
        self.assertEqual(code, 1)
        self.assertIn('Result: polish_empty', out)

    def test_a_reply_the_guard_rejects_fails(self):
        code, out = self.run_doctor(accepted=False)
        self.assertIn('Result: polish_rejected', out)


if __name__ == '__main__':
    unittest.main()
