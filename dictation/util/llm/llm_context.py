"""
LLM context manager

Features:
1. Keeps the conversation history
2. Clears out old conversations automatically
3. Trims the history to fit
"""

import time
from typing import Dict, List
from threading import Lock
from util.llm.llm_constants import ContextConstants, estimate_tokens
from . import logger


class ContextManager:
    """Conversation context manager"""

    def __init__(self, max_length: int = 2000):
        self.max_length = max_length
        self.history = []
        self.last_interaction = None
        self._lock = Lock()

    def add_message(self, role: str, content: str):
        """Add a message to the history"""
        with self._lock:
            timestamp = time.time()
            self.history.append({
                'timestamp': timestamp,
                'role': role,
                'content': content,
            })
            self.last_interaction = timestamp
            self._trim_history()

    def clear(self):
        """Clear the conversation history"""
        with self._lock:
            self.history = []
            self.last_interaction = None
            logger.info("Conversation history cleared")

    def get_history(self) -> List[Dict]:
        """Return the conversation history"""
        with self._lock:
            return [
                {'role': msg['role'], 'content': msg['content']}
                for msg in self.history
            ]

    def _estimate_tokens(self, text: str) -> int:
        """Estimate the token count of a text (uses the shared constants)"""
        return estimate_tokens(text)

    def _trim_history(self):
        """Trim the history by token count

        Strategy:
        1. Trim as soon as it passes 80% of the limit
        2. Leave 20% for the model's output
        3. Delete from the oldest message first, keeping the most recent conversation
        """
        if not self.history:
            return

        # Total tokens in the current history
        total_tokens = sum(
            self._estimate_tokens(msg['content'])
            for msg in self.history
        )

        # Use the configured threshold, leaving room for the model's output
        target_tokens = int(self.max_length * ContextConstants.TRIM_THRESHOLD_RATIO)

        # Within the threshold: nothing to trim
        if total_tokens <= target_tokens:
            return

        threshold_percent = int(ContextConstants.TRIM_THRESHOLD_RATIO * 100)
        logger.info(f"[Context trim] {total_tokens} tokens now ({total_tokens/self.max_length*100:.1f}%), trimming (threshold: {target_tokens} tokens, {threshold_percent}%)")

        # Delete from the front (oldest messages) until under the threshold
        removed_count = 0
        while self.history and total_tokens > target_tokens:
            # Delete the oldest message
            removed_msg = self.history.pop(0)
            removed_tokens = self._estimate_tokens(removed_msg['content'])
            total_tokens -= removed_tokens
            removed_count += 1

        # Debug info: log the trim result
        if len(self.history) > 0:
            final_tokens = sum(self._estimate_tokens(msg['content']) for msg in self.history)
            logger.info(f"[Context trim] Removed {removed_count} old messages, kept {len(self.history)}")
            logger.info(f"[Context trim] About {final_tokens} tokens now ({final_tokens/self.max_length*100:.1f}%), {self.max_length - final_tokens} tokens left")
