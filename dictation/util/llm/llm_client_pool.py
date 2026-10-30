"""
LLM client pool

Features:
1. Caches OpenAI client instances
2. Creates and returns clients by provider and api_url
"""
import os
import socket
from urllib.parse import urlparse
from openai import OpenAI
from typing import Dict, Any, Union
from ollama import Client as OllamaClient
from util.llm.llm_constants import APIConfig


LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def local_server_listening(url: str, timeout: float = 0.25) -> bool:
    """False only when url points at this PC and nothing listens on its port.

    Windows takes about 2 s to refuse a connection to a closed local port and the OpenAI client
    tries three times, so a stopped LM Studio added about 7 s to every polished dictation.
    A listening local server accepts well within the timeout.
    """
    parsed = urlparse(url or '')
    if parsed.hostname not in LOOPBACK_HOSTS:
        return True
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


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
            final_url = self.api_url_for(provider, api_url)

            # api_key
            final_key = api_key or (os.environ.get('NEBIUS_API_KEY', '') if provider == 'nebius'
                                    else APIConfig.DEFAULT_API_KEYS.get(provider, ''))

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

    @staticmethod
    def api_url_for(provider: str, api_url: str = '') -> str:
        """The URL a client for this provider talks to: the configured one, else the provider's default."""
        return api_url or APIConfig.DEFAULT_API_URLS.get(provider, '')

    def clear(self):
        """Clear the client cache"""
        self._clients.clear()
