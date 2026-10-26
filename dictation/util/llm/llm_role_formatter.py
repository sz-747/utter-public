"""
LLM role info formatter

Features:
1. Formats the role status line
2. Shared Rich rendering
"""
from rich.text import Text
from rich.console import Console
from util.llm.llm_role_config import RoleConfig


class RoleFormatter:
    """Role info formatter - formats how roles are shown"""

    @staticmethod
    def format_status(role_name: str, role_config: RoleConfig) -> Text:
        """
        Format the role status line

        Args:
            role_name: role name
            role_config: role settings (RoleConfig)

        Returns:
            A Text object (for Rich rendering)
        """
        text = Text()

        # Role name, padded to at least 8 characters
        padding = " " * max(0, 8 - len(role_name))
        text.append(f"{role_name}{padding}: ", style="bold cyan")

        # Match
        match = role_config.match
        text.append("Match ", style="green" if match else "dim")

        # Process
        process = role_config.process
        text.append("Process ", style="green" if process else "dim")

        # Output mode
        output_mode = role_config.output_mode
        if output_mode == 'typing':
            text.append("Typing ", style="green")
        elif output_mode == 'toast':
            text.append("Toast ", style="blue")
        else:
            text.append("Typing ", style="dim")

        # Thinking
        thinking = role_config.enable_thinking
        text.append("Thinking ", style="green" if thinking else "dim")

        # History
        history = role_config.enable_history
        text.append("History ", style="green" if history else "dim")

        # Hotwords
        hotwords = role_config.enable_hotwords
        text.append("Hotwords ", style="green" if hotwords else "dim")

        # Corrections
        rectify = role_config.enable_rectify
        text.append("Corrections ", style="green" if rectify else "dim")

        # Read the selected text
        read_selection = role_config.enable_read_selection
        text.append("Selection ", style="green" if read_selection else "dim")


        # Model info
        text.append(f"  ({role_config.model} from {role_config.provider})", style="dim")

        return text

    @staticmethod
    def print_status(role_name: str, role_config: RoleConfig, prefix: str = "  "):
        """
        Print the role status (with a prefix)

        Args:
            role_name: role name
            role_config: role settings
            prefix: prefix text (two spaces by default)
        """
        console = Console()
        status_line = RoleFormatter.format_status(role_name, role_config)

        text = Text(prefix)
        text.append(status_line)
        console.print(text)

    @staticmethod
    def print_update(role_name: str, role_config: RoleConfig):
        """
        Print a role update

        Args:
            role_name: role name
            role_config: role settings
        """
        console = Console()
        status_line = RoleFormatter.format_status(role_name, role_config)

        # "Role updated  " prefix + status line
        prefix = Text("\nRole updated  ")
        prefix.append(status_line)
        console.print(prefix + "\n")
