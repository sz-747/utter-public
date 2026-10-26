from dataclasses import dataclass
from typing import Optional

@dataclass
class LLMResult:
    """LLM processing result"""
    result: str                    # Polished text
    role_name: Optional[str]       # Role name
    processed: bool                # Whether it was processed
    token_count: int               # Token count
    polish_time: float             # Total time (seconds)
    input_text: str                # Input text (role prefix removed)
    generation_time: float = 0.0   # Generation time (seconds, from the first token)


async def llm_process_text(text: str, paste: bool = None, matched_hotwords=None, prefix: str = '') -> Optional[LLMResult]:
    """Polish the text and output it (main external entry point - shim); prefix is typed before the default cleanup result and is not part of the result"""
    from util.llm.llm_handler import get_handler
    handler = get_handler()
    return await handler.process_and_output(text, paste, matched_hotwords, prefix)
