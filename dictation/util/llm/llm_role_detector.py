"""
LLM role detector

Features:
1. Checks whether the text starts with a role prefix
2. Returns that role's settings and the text without the prefix
"""
from typing import Tuple, Optional
from util.llm.llm_role_config import RoleConfig
from util.llm.llm_interfaces import IRoleLoader
from . import logger


class RoleDetector:
    """Role detector - finds the role in the input text"""

    def __init__(self, role_loader: IRoleLoader):
        """
        Args:
            role_loader: role loader
        """
        self.role_loader = role_loader

    def detect(self, text: str) -> Tuple[Optional[RoleConfig], str]:
        """
        Check whether the text starts with a role prefix

        Args:
            text: input text

        Returns:
            (role_config, content) - role_config is a RoleConfig,
            content is the text without the prefix
        """
        # logger.debug(f"Detecting role, input: {text[:50]}...")

        for role_name, role_config in self.role_loader.get_roles().items():
            if role_name == RoleConfig.DEFAULT_ROLE_NAME or role_name == '':
                continue

            # Is prefix matching enabled?
            if not role_config.match:
                continue

            if role_name and text.startswith(role_name):
                remaining_text = text[len(role_name):]
                remaining_text = remaining_text.lstrip(',. ')

                # logger.debug(f"Matched role: {role_name}, without prefix: {remaining_text[:50]}...")
                return role_config, remaining_text

        # No match: use the default role
        default_role = self.role_loader.get_default_role()
        if default_role.process:
            # logger.debug(f"No role prefix matched, using the default role, process: {default_role.process}")
            return default_role, text

        # logger.debug("No role matched and the default role does not process; returning the original text")
        return None, text
