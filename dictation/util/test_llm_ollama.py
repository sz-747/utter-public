import unittest
from types import SimpleNamespace

from util.llm.llm_processor import LLMProcessor
from util.llm.llm_role_config import RoleConfig


class FakeOllama:
    """Has the real SDK's think and keep_alive keywords, so the processor's signature check passes."""

    def __init__(self):
        self.kwargs = None

    def chat(self, model, messages, stream=False, options=None, think=None, keep_alive=None):
        self.kwargs = dict(model=model, stream=stream, options=options, think=think, keep_alive=keep_alive)
        return [SimpleNamespace(message=SimpleNamespace(content='Sure.'), done=False),
                SimpleNamespace(message=SimpleNamespace(content=''), done=True, eval_count=2)]


class OllamaRequestTests(unittest.TestCase):
    def _send(self, role):
        client = FakeOllama()
        text, _, _ = LLMProcessor(None)._process_ollama_stream(client, role, [{'role': 'user', 'content': 'hi'}], None, None)
        return text, client.kwargs

    def test_thinking_off_is_sent_explicitly(self):
        # Unset, Qwen 3.5 thinks by default: 11 s of thinking and an empty reply.
        text, sent = self._send(RoleConfig(provider='ollama', model='m', enable_thinking=False))
        self.assertEqual(text, 'Sure.')
        self.assertIs(sent['think'], False)

    def test_thinking_on_is_sent(self):
        _, sent = self._send(RoleConfig(provider='ollama', model='m', enable_thinking=True))
        self.assertIs(sent['think'], True)

    def test_keep_alive_goes_to_the_request_not_the_model_options(self):
        _, sent = self._send(RoleConfig(provider='ollama', model='m', extra_options={'keep_alive': '1h'}))
        self.assertEqual(sent['keep_alive'], '1h')
        self.assertNotIn('keep_alive', sent['options'])

    def test_keep_alive_is_left_to_ollama_when_unset(self):
        _, sent = self._send(RoleConfig(provider='ollama', model='m'))
        self.assertIsNone(sent['keep_alive'])


if __name__ == '__main__':
    unittest.main()
