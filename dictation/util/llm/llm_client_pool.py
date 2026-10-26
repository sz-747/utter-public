"""
LLM client pool

Features:
1. Caches OpenAI client instances
2. Creates and returns clients by provider and api_url
"""
from openai import OpenAI
from typing import Dict, Any, Union
from ollama import Client as OllamaClient
from util.llm.llm_constants import APIConfig


class ClientPool:
    """OpenAI client pool"""

    def __init__(self):
        self._clients: Dict[str, Any] = {}

    def get_client(self, provider: str, api_url: str = '', api_key: str = '') -> Any:
        """Return an LLM client (cached)

        Args:
            provider: API provider (e.g. 'ollama', 'openai')
            api_url: API URL (optional; used first when set)
            api_key: API key (optional)

        Returns:
            An OpenAI or ollama.Client instance
        """
        cache_key = f"{provider}_{api_url}"

        if cache_key not in self._clients:
            # api_url: the configured URL first, otherwise the default
            final_url = api_url or APIConfig.DEFAULT_API_URLS.get(provider)

            # api_key
            final_key = api_key or APIConfig.DEFAULT_API_KEYS.get(provider, '')

            # Timeout by provider, or the default when not listed
            timeout = APIConfig.DEFAULT_TIMEOUTS.get(provider, APIConfig.DEFAULT_TIMEOUT)

            # Create the client
            if provider == 'ollama':
                self._clients[cache_key] = OllamaClient(
                    host=final_url,
                    timeout=timeout,
                )
            else:
                self._clients[cache_key] = OpenAI(
                    base_url=final_url,
                    api_key=final_key,
                    timeout=timeout,
                )

        return self._clients[cache_key]

    def clear(self):
        """Clear the client cache"""
        self._clients.clear()
