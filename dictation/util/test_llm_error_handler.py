import importlib
import socket
import time
import unittest
from unittest import mock

from util.llm import llm_error_handler
from util.llm.llm_client_pool import local_server_listening
from util.llm.llm_exceptions import ConnectionErrorWrapper, AuthenticationErrorWrapper, TimeoutErrorWrapper
from util.llm.llm_processor import LLMProcessor
from util.llm.llm_role_config import RoleConfig

toast = importlib.import_module('util.ui.toast')   # util.ui exports a toast() function under the same name


class LLMErrorHandlerTests(unittest.TestCase):
    def setUp(self):
        # Autospec: calling a method the real manager lacks raises, as it does in the client.
        self.manager = mock.create_autospec(toast.ToastMessageManager, instance=True)
        patcher = mock.patch.object(toast, 'ToastMessageManager', return_value=self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logger = mock.patch.object(llm_error_handler, 'logger').start()
        self.addCleanup(mock.patch.stopall)
        llm_error_handler.note_llm_success()

    def test_connection_error_keeps_the_dictation_and_shows_the_error(self):
        error = ConnectionErrorWrapper(Exception('Connection error.'), 'openai')

        text, ok = llm_error_handler.handle_llm_error(error, 'the original dictation', '')

        self.assertEqual((text, ok), ('the original dictation', False))
        self.manager.add_message.assert_called_once()
        shown = self.manager.add_message.call_args.args[0].text
        self.assertIn("AI polish: Can't reach the model server", shown)
        self.logger.error.assert_not_called()   # no "Could not show the toast"

    def test_connection_error_is_shown_once_until_a_request_succeeds(self):
        error = ConnectionErrorWrapper(Exception('Connection error.'), 'openai')

        llm_error_handler.handle_llm_error(error, 'one')
        text, _ = llm_error_handler.handle_llm_error(error, 'two')
        self.assertEqual(text, 'two')
        self.assertEqual(self.manager.add_message.call_count, 1)

        llm_error_handler.note_llm_success()
        llm_error_handler.handle_llm_error(error, 'three')
        self.assertEqual(self.manager.add_message.call_count, 2)

    def test_auth_error_uses_the_fallback_text_when_given(self):
        error = AuthenticationErrorWrapper(Exception('bad key'), 'openai')

        text, _ = llm_error_handler.handle_llm_error(error, 'raw', fallback_text='fallback')

        self.assertEqual(text, 'fallback')
        self.manager.add_message.assert_called_once()

    def test_timeout_falls_back_quietly(self):
        error = TimeoutErrorWrapper(Exception('timed out'), 'openai')

        text, _ = llm_error_handler.handle_llm_error(error, 'raw')

        self.assertEqual(text, 'raw')
        self.manager.add_message.assert_not_called()


def _closed_local_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class LocalServerCheckTests(unittest.TestCase):
    def test_listening_local_server_passes(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            port = server.getsockname()[1]
            self.assertTrue(local_server_listening(f'http://127.0.0.1:{port}/v1'))

    def test_stopped_local_server_fails_fast(self):
        start = time.monotonic()
        self.assertFalse(local_server_listening(f'http://127.0.0.1:{_closed_local_port()}/v1'))
        self.assertLess(time.monotonic() - start, 1.0)   # Windows takes ~2 s to refuse otherwise

    def test_remote_servers_are_not_checked(self):
        with mock.patch('socket.create_connection') as connect:
            self.assertTrue(local_server_listening('https://api.openai.com/v1'))
        connect.assert_not_called()

    def test_processor_skips_the_request_when_the_local_server_is_off(self):
        pool = mock.Mock()
        role = RoleConfig(provider='openai', api_url=f'http://127.0.0.1:{_closed_local_port()}/v1', model='m')

        with self.assertRaises(ConnectionErrorWrapper):
            LLMProcessor(pool).process(role, [{'role': 'user', 'content': 'hi'}])
        pool.get_client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
