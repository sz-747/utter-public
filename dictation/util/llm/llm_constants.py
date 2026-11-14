"""
LLM constants

All magic numbers, defaults and settings constants in one place
"""

# ==================== Context ====================
class ContextConstants:
    """Context management constants"""

    # Token trim threshold (trim at 80%, leaving 20% for the model's output)
    TRIM_THRESHOLD_RATIO = 0.8

    # Token estimate: about 4 characters = 1 token
    CHARS_PER_TOKEN = 4.0


# ==================== RAG ====================
class RAGConstants:
    """Hotword RAG constants"""

    # Search parameters
    DEFAULT_TOP_K = 5              # Return the top 5 hotwords by default
    DEFAULT_THRESHOLD = 0.4        # Default similarity threshold


# ==================== File watching ====================
class WatcherConstants:
    """File watcher constants"""

    # Debounce delay (seconds)
    DEBOUNCE_DELAY = 3

    # File filters
    PY_EXTENSION = '.py'
    INIT_FILE = '__init__.py'
    CACHE_DIR = '__pycache__'

    # Reload marker
    RELOAD_ALL_MARKER = '__reload_all__'


# ==================== Role defaults ====================


# ==================== API ====================
class APIConfig:
    """API provider settings"""

    # Default API URLs
    DEFAULT_API_URLS = {
        'ollama': 'http://127.0.0.1:11434',   # not localhost: Windows tries IPv6 first and stalls ~2 s per connection
        'openai': 'https://api.openai.com/v1',
        'deepseek': 'https://api.deepseek.com/v1',
        'cerebras': 'https://api.cerebras.ai/v1',
        'claude': 'https://api.anthropic.com/v1/',                                # OpenAI-compatible endpoint
        'gemini': 'https://generativelanguage.googleapis.com/v1beta/openai/',     # OpenAI-compatible endpoint
    }

    # Default API keys
    DEFAULT_API_KEYS = {
        'ollama': 'ollama',
        'openai': '',
        'deepseek': '',
        'cerebras': '',
    }

    # Request timeouts (seconds)
    # A local model may need to load on first use, so it gets longer
    # More than 10 seconds usually means a network problem
    DEFAULT_TIMEOUTS = {
        'ollama': 20.0,       # Local model
        'openai': 10.0,       # OpenAI API
        'deepseek': 10.0,     # DeepSeek API
        'cerebras': 10.0,     # Cerebras API
        'claude': 10.0,       # Claude API
        'gemini': 10.0,       # Gemini API
    }

    # Default timeout (for providers not listed)
    DEFAULT_TIMEOUT = 10.0


# ==================== Token estimate ====================
def estimate_tokens(text: str) -> int:
    """
    Estimate the number of tokens in a text

    Args:
        text: text to estimate

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    # About 4 characters = 1 token
    tokens = int(len(text) / ContextConstants.CHARS_PER_TOKEN)

    return max(tokens, 1)  # At least 1 token
