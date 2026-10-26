
# coding: utf-8
"""
LLM message building

Assembles the full context of an LLM request:
1. System prompt
2. Conversation history
3. Hotword list (RAG search)
4. Correction history (RAG search)
5. User input
6. Image data (optional)
"""

from __future__ import annotations

import json
from typing import List, Dict, Optional, Tuple, Any

from util.llm.llm_role_config import RoleConfig
from util.llm.llm_constants import estimate_tokens
from . import logger


class MessageBuilder:
    """LLM message builder"""

    def __init__(self):
        """
        Set up the message builder
        """
        # Imports are deferred to avoid circular dependencies
        pass

    def _get_rectify_rag(self):
        """Get the RectificationRAG from the HotwordManager"""
        from util.hotword import get_hotword_manager
        manager = get_hotword_manager()
        return manager.get_rectify_rag()

    def build_messages(
        self,
        role_config: RoleConfig,
        user_content: str,
        context_manager: Any = None,
        image_data: Optional[str] = None,
        hotwords: Optional[List[Tuple[str, float]]] = None,
        selection_text: str = ""
    ) -> List[Dict]:
        """
        Build the LLM request messages

        Args:
            role_config: role settings
            user_content: the user's input
            context_manager: context manager (history)
            image_data: image data (base64)
            hotwords: matching hotwords [(hotword, score), ...]
            selection_text: the text the user selected

        Returns:
            The full message list
        """
        messages = []

        # 1. System prompt
        if role_config.system_prompt:
            messages.append({
                "role": "system",
                "content": role_config.system_prompt
            })

        # 2. Conversation history
        if context_manager:
            if hasattr(context_manager, 'history') and isinstance(context_manager.history, list):
                messages.extend(context_manager.history)
            elif isinstance(context_manager, list):
                messages.extend(context_manager)

        # 3. User content (built in one place so the format is easy to manage)
        context_parts = []

        # 3.1 Hotword list
        if role_config.enable_hotwords and hotwords:
            logger.debug(f"[DEBUG] hotwords type={type(hotwords)}, len={len(hotwords)}")
            if hotwords:
                logger.debug(f"[DEBUG] hotwords[0] type={type(hotwords[0])}, value={hotwords[0]}")
            try:
                # hotwords look like [(source, match, score), ...]
                words = [item[1] for item in hotwords]

                if words:
                    context_parts.append(f"{role_config.prompt_prefix_hotwords}[{', '.join(words)}]")
                    logger.debug(f"[Message builder] Added the hotword list")
            except Exception as e:
                logger.error(f"[ERROR] Failed to process hotwords: {e}")
                logger.error(f"[ERROR] hotwords details: {[(type(hw), hw) for hw in hotwords[:5]]}")
                raise

        # 3.2 Correction history (raw data from the RAG, formatted here)
        if role_config.enable_rectify:
            rectify_rag = self._get_rectify_rag()
            if rectify_rag:
                matches = rectify_rag.search(user_content)
                if matches:
                    lines = [role_config.prompt_prefix_rectify]
                    for wrong, right, _ in matches:
                        lines.append(f"- {wrong} => {right}")
                    context_parts.append("\n".join(lines))
                    logger.debug(f"[Message builder] Added {len(matches)} correction history entries from the RAG")

        # 3.3 Selected text
        if selection_text:
             context_parts.append(f"{role_config.prompt_prefix_selection}{selection_text}")
             logger.debug(f"[Message builder] Added the selected text")

        # 3.4 Final assembly
        context_str = "\n\n".join(context_parts)
        context_str = context_str + "\n\n" if context_str else ""

        user_content = f"{context_str}{role_config.prompt_prefix_input}{user_content}"

        # Build the final user message
        final_user_msg = {"role": "user", "content": user_content}

        # Image data (note: with an image, content becomes a list)
        if image_data:
             final_user_msg["content"] = [
                 {"type": "text", "text": user_content},
                 {"type": "image_url", "image_url": {"url": image_data}}
             ]

        messages.append(final_user_msg)

        # Log the full context
        self._debug_print_messages(role_config.name, role_config, messages)

        return messages

    def _debug_print_messages(
        self,
        role_name: str,
        role_config: RoleConfig,
        messages: List[Dict]
    ):
        """Log debug info (context stats and the full messages)"""
        try:
            # Context stats
            total_tokens = sum(
                estimate_tokens(msg['content'])
                for msg in messages
            )
            history_count = len([m for m in messages if m['role'] in ['user', 'assistant']])
            max_context = role_config.max_context_length
            usage_percent = (total_tokens / max_context * 100) if max_context > 0 else 0

            debug_msg = [
                f"\n{'='*70}",
                f"[LLM request] Role: {role_name if role_name else RoleConfig.DEFAULT_ROLE_NAME}",
                f"  Context stats:",
                f"    History messages: {history_count}",
                f"    Total tokens: {total_tokens} / {max_context} ({usage_percent:.1f}%)",
                f"    Space left: {max_context - total_tokens} tokens",
                f"    Trim threshold: 80% (about {int(max_context * 0.8)} tokens)"
            ]

            if usage_percent > 80:
                debug_msg.append(f"    ⚠️  Warning: context is over 80%, automatic trimming has started")
            elif usage_percent > 60:
                debug_msg.append(f"    ⚡ Note: context use is over 60%")

            debug_msg.append(f"{'='*70}")

            # 1. Detailed stats at DEBUG level
            logger.debug("\n".join(debug_msg))

            # 2. Only the latest user message at INFO level
            last_msg = messages[-1]
            content = last_msg.get('content', '')
            if isinstance(content, list):
                # Multimodal format: extract the text
                content = "\n".join([item.get('text', '') for item in content if item.get('type') == 'text'])

            info_msg = [
                f"\n{'='*70}",
                f"[LLM request] Role: {role_name if role_name else RoleConfig.DEFAULT_ROLE_NAME}",
                f"{content}",
                f"{'='*70}\n"
            ]
            logger.info("\n".join(info_msg))

        except Exception as e:
            logger.error(f"Failed to log the messages: {e}")
