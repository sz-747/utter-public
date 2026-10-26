"""
LLM: read the selected text

Steps:
1. Save the current clipboard (to restore it later)
2. Simulate Ctrl+C to copy the selected text
3. Read the new clipboard
4. Restore the original clipboard
5. If the clipboard changed, return the selected text
"""
import time
import pyclip
import keyboard
from . import logger
from .llm_clipboard import safe_paste
from util.client.state import get_state
state = get_state()


# Global: the last selected text each role used
_last_selection_by_role = {}


def get_selected_text(role_config) -> str:
    """
    Return the text the user has selected (by simulating Ctrl+C)

    Args:
        role_config: the RoleConfig

    Returns:
        The selected text, or an empty string when it should not be used
    """
    global _last_selection_by_role

    # Is reading the selection enabled?
    if not role_config.enable_read_selection:
        return ""

    role_name = role_config.name

    try:
        # Save the current clipboard
        original_clipboard = safe_paste()

        # Simulate Ctrl+C to copy the selection
        keyboard.press_and_release('ctrl+c')

        # Wait for the copy to finish
        time.sleep(0.1)

        # Read the new clipboard
        selected_text = safe_paste()

        # Restore the original clipboard
        pyclip.copy(original_clipboard)

        # Unchanged clipboard means nothing was selected
        if selected_text == original_clipboard or selected_text == state.last_output_text:
            return ""

        # Length limit
        max_length = getattr(role_config, 'selection_max_length', 1000)
        if len(selected_text) > max_length:
            selected_text = selected_text[:max_length]

        # With history on, skip a selection that is the same as the last one used
        if role_config.enable_history:
            last_selection = _last_selection_by_role.get(role_name, "")
            if selected_text == last_selection:
                # Same selection, already used last time: do not add it to the context again
                return ""

        # Whitespace only (spaces, tabs, newlines and so on)
        if not selected_text.strip():
            return ""

        return selected_text

    except Exception as e:
        logger.warning(f"Could not read the selected text: {e}")
        return ""


def record_selection_usage(role_config, selection_text: str):
    """
    Record the selected text a role used (to detect repeats next time)

    Args:
        role_config: the RoleConfig
        selection_text: the selected text used (empty string means none)
    """
    global _last_selection_by_role
    role_name = role_config.name
    _last_selection_by_role[role_name] = selection_text

