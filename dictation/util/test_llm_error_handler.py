import importlib
import unittest
from unittest import mock

from util.llm import llm_error_handler
from util.llm.llm_exceptions import ConnectionErrorWrapper, AuthenticationErrorWrapper, TimeoutErrorWrapper

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

    def test_connection_error_keeps_the_dictation_and_shows_the_error(self):
        error = ConnectionErrorWrapper(Exception('Connection error.'), 'openai')

        text, ok = llm_error_handler.handle_llm_error(error, 'the original dictation')

        self.assertEqual((text, ok), ('the original dictation', False))
        self.manager.add_message.assert_called_once()
        self.assertIn('Could not connect to the API', self.manager.add_message.call_args.args[0].text)
        self.logger.error.assert_not_called()   # no "Could not show the toast"

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


if __name__ == '__main__':
    unittest.main()
