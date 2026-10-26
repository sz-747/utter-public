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
                 mock.patch.object(engine, '_port_open', return_value=True) as probe:
                status = engine.server_status()
        # 0.0.0.0 is where a server listens, not an address Windows can connect to.
        probe.assert_called_once_with('127.0.0.1', 6016)
        self.assertEqual((status['listening'], status['address']), (True, '0.0.0.0:6016'))

    def test_client_only_install_uses_the_clients_server_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'config_client.py').write_text(
                "    addr = 'desktop.example-tailnet.ts.net'\n    port = '6016'\n", encoding='utf-8')
            with mock.patch.object(engine, 'ROOT', Path(tmp)), \
                 mock.patch.object(engine, 'SERVER_EXE', Path(tmp) / 'start_server.exe'), \
                 mock.patch.object(engine, '_port_open', return_value=False) as probe, \
                 mock.patch.object(engine, '_run_script') as run:
                status = engine.server_status()
                engine.start_engine()
        probe.assert_called_once_with('desktop.example-tailnet.ts.net', 6016, timeout=0.8)
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

    def test_client_without_status_is_reported_as_unreported(self):
        status = self._status(None, processes=[object()])
        self.assertFalse(status['running'])
        self.assertTrue(status['unreported'])


if __name__ == '__main__':
    unittest.main()
