import os
import unittest
from types import SimpleNamespace
from unittest import mock

from util.llm.llm_client_pool import ClientPool
from util.llm.llm_constants import APIConfig
from util.llm.llm_processor import LLMProcessor
from util.llm.llm_role_config import RoleConfig


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='Cleaned.'))], usage=None),
                SimpleNamespace(choices=[], usage=SimpleNamespace(completion_tokens=3))]


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


class NebiusTests(unittest.TestCase):
    def test_provider_has_openai_endpoint_and_remote_timeout(self):
        self.assertEqual(APIConfig.DEFAULT_API_URLS['nebius'], 'https://api.tokenfactory.nebius.com/v1/')
        self.assertGreater(APIConfig.DEFAULT_TIMEOUTS['nebius'], APIConfig.DEFAULT_TIMEOUTS['openai'])

    def test_pool_reads_key_from_environment_without_logging_it(self):
        with mock.patch.dict(os.environ, {'NEBIUS_API_KEY': 'secret-test-key'}), \
             mock.patch('util.llm.llm_client_pool.OpenAI') as openai:
            ClientPool().get_client('nebius')
        self.assertEqual(openai.call_args.kwargs['api_key'], 'secret-test-key')

    def test_openai_compatible_request_streams_through_fake_client(self):
        client = FakeClient()
        role = RoleConfig(provider='nebius', model='nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B', max_tokens=12)
        text, tokens, _ = LLMProcessor(None)._stream_request(
            client, {'model': role.model, 'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 12},
            None, None, role, None, [{'role': 'user', 'content': 'hi'}])
        self.assertEqual((text, tokens), ('Cleaned.', 3))
        self.assertEqual(client.chat.completions.kwargs['model'], role.model)
        self.assertTrue(client.chat.completions.kwargs['stream'])

    def test_ollama_keep_alive_is_not_sent_as_openai_sdk_argument(self):
        client = FakeClient()
        role = RoleConfig(provider='nebius', model='nano', extra_options={'keep_alive': '1h'})
        params = LLMProcessor(None)._build_request_params(role, [{'role': 'user', 'content': 'hi'}])
        text, _, _ = LLMProcessor(None)._stream_request(
            client, params, None, None, role, None, [{'role': 'user', 'content': 'hi'}])
        self.assertEqual(text, 'Cleaned.')
        self.assertNotIn('keep_alive', client.chat.completions.kwargs)

    def test_nemotron3_nano_disables_thinking_and_preserves_other_extra_body_options(self):
        role = RoleConfig(
            provider='nebius',
            model='nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
            extra_options={'extra_body': {'top_k': 1, 'chat_template_kwargs': {'custom': True}}},
        )

        params = LLMProcessor(None)._build_request_params(role, [{'role': 'user', 'content': 'hi'}])

        self.assertEqual(params['extra_body'], {
            'top_k': 1,
            'chat_template_kwargs': {'custom': True, 'enable_thinking': False},
        })


if __name__ == '__main__':
    unittest.main()
