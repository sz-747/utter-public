import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from utter import engine
from util import app_settings


class ConfigValueTests(unittest.TestCase):
    def test_reads_quoted_assignments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.py'
            path.write_text("class C:\n    model_type = 'qwen_asr'   # comment\n    port = \"6016\"\n", encoding='utf-8')
            self.assertEqual(engine._config_value(path, 'model_type'), 'qwen_asr')
            self.assertEqual(engine._config_value(path, 'port'), '6016')
            self.assertIsNone(engine._config_value(path, 'missing'))
            self.assertIsNone(engine._config_value(Path(tmp) / 'absent.py', 'port'))

    def test_llm_backend_names_local_servers_and_skips_online_probes(self):
        cases = [
            ("provider = 'openai'\napi_url = 'http://localhost:1234/v1'\nmodel = 'qwen'\n", ('LM Studio', True)),
            ("provider = 'ollama'\napi_url = ''\nmodel = 'qwen3:8b'\n", ('Ollama', True)),
            ("provider = 'deepseek'\napi_url = 'https://api.deepseek.com'\nmodel = 'x'\n", ('deepseek', False)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'default.py'
            for text, (label, local) in cases:
                path.write_text(text, encoding='utf-8')
                with mock.patch.object(engine, '_port_open', return_value=True) as probe:
                    backend = engine.llm_backend(path)
                self.assertEqual((backend['label'], backend['local']), (label, local))
                self.assertEqual(probe.called, local)
                if probe.called:   # never "localhost": Windows stalls ~2 s trying IPv6 first
                    self.assertEqual(probe.call_args[0][0], '127.0.0.1')
                self.assertEqual(backend['reachable'], True if local else None)

    def test_server_on_all_interfaces_is_probed_on_loopback(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'config_server.py').write_text("addr = '0.0.0.0'\nport = '6016'\n", encoding='utf-8')
            with mock.patch.object(engine, 'RUNTIME', Path(tmp)), \
                 mock.patch.object(engine, 'is_remote', return_value=False), \
                 mock.patch.object(engine, '_listening_here', return_value=True) as probe, \
                 mock.patch.object(engine, '_port_open') as connect:
                status = engine.server_status()
        # Read from the socket table: a connection would log a failed-handshake traceback each second.
        probe.assert_called_once_with(6016)
        connect.assert_not_called()
        self.assertEqual((status['listening'], status['address']), (True, '0.0.0.0:6016'))

    def test_the_local_check_sees_a_listening_port_without_connecting(self):
        import socket
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            port = server.getsockname()[1]
            self.assertFalse(engine._listening_here(port))
            server.listen()
            self.assertTrue(engine._listening_here(port))

    def test_a_remote_server_is_checked_by_handshake_at_most_every_few_seconds(self):
        engine._remote_checks.clear()
        with mock.patch('websockets.sync.client.connect') as connect:
            self.assertTrue(engine._speech_server_answers('desktop', 6016))
            self.assertTrue(engine._speech_server_answers('desktop', 6016))
        connect.assert_called_once()
        self.assertEqual(connect.call_args.kwargs['subprotocols'], ['binary'])
        engine._remote_checks.clear()

    def test_client_only_install_uses_the_clients_server_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'config_client.py').write_text(
                "    addr = 'desktop.example-tailnet.ts.net'\n    port = '6016'\n", encoding='utf-8')
            with mock.patch.object(engine, 'ROOT', Path(tmp)), \
                 mock.patch.object(engine, 'SERVER_EXE', Path(tmp) / 'start_server.exe'), \
                 mock.patch.object(engine, '_speech_server_answers', return_value=False) as probe, \
                 mock.patch.object(engine, '_run_script') as run:
                status = engine.server_status()
                engine.start_engine()
        probe.assert_called_once_with('desktop.example-tailnet.ts.net', 6016)
        self.assertEqual((status['remote'], status['host'], status['listening']), (True, 'desktop', False))
        run.assert_called_once_with('start-client.ps1')   # no local server to start

    def test_install_reports_a_model_and_llm_backend(self):
        self.assertIn('model', engine.server_status())
        self.assertIn('provider', engine.llm_backend())


class ClientStatusTests(unittest.TestCase):
    def _status(self, payload, processes=()):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'status.json'
            if payload is not None:
                path.write_text(json.dumps(payload), encoding='utf-8')
            with mock.patch.object(app_settings, 'STATUS_PATH', path), \
                    mock.patch.object(engine, '_client_processes', return_value=list(processes)):
                return engine.client_status()

    def test_fresh_status_from_a_live_process_is_running(self):
        status = self._status({'pid': os.getpid(), 'updated_at': time.time(), 'microphone': {'name': 'Mic'}})
        self.assertTrue(status['running'])
        self.assertEqual(status['microphone'], {'name': 'Mic'})

    def test_stale_or_stopped_status_is_not_running(self):
        self.assertFalse(self._status({'pid': os.getpid(), 'updated_at': time.time() - 60})['running'])
        self.assertFalse(self._status({'pid': os.getpid(), 'updated_at': time.time(), 'stopped': True})['running'])

    def test_stopping_waits_for_a_dictation_in_progress(self):
        # A restart during a recording lost it.
        states = iter([{'recording': True}, {'recording': True}, {'recording': False}])
        with mock.patch.object(engine, 'client_status', side_effect=lambda: next(states)), \
                mock.patch.object(engine.time, 'sleep') as sleep, \
                mock.patch.object(engine, '_run_script') as run:
            engine.stop_engine()
        run.assert_called_once_with('stop-dictation.ps1', wait=True)
        self.assertEqual(sleep.call_args_list[-1], mock.call(3))       # time to type what was said

    def test_waiting_gives_up_on_a_stuck_recording(self):
        with mock.patch.object(engine, 'client_status', return_value={'recording': True}), \
                mock.patch.object(engine.time, 'sleep'):
            self.assertFalse(engine.wait_until_idle(timeout=0))

    def test_client_without_status_is_reported_as_unreported(self):
        status = self._status(None, processes=[object()])
        self.assertFalse(status['running'])
        self.assertTrue(status['unreported'])


if __name__ == '__main__':
    unittest.main()
