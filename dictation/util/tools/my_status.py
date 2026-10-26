# coding: utf-8
"""
Rich Status extension

An extended Status class that tracks whether it is running.
"""

from rich.console import RenderableType
from rich.style import StyleType
from rich.status import Status as RichStatus


class Status(RichStatus):
    """
    Extended Rich Status

    Extends rich.status.Status with a started attribute that tracks its state,
    so the animation is never started or stopped twice.

    Attributes:
        started: whether the animation is running
    """

    def __init__(
        self,
        status: RenderableType,
        *,
        spinner: str = "dots",
        spinner_style: StyleType = "status.spinner",
        speed: float = 1.0,
        refresh_per_second: float = 12.5
    ):
        """
        Set up the Status

        Args:
            status: status text to show
            spinner: spinner name
            spinner_style: spinner style
            speed: animation speed
            refresh_per_second: refresh rate
        """
        super().__init__(
            status,
            console=None,
            spinner=spinner,
            spinner_style=spinner_style,
            speed=speed,
            refresh_per_second=refresh_per_second,
        )
        self.started = False

    def start(self) -> None:
        """Start the animation (if not already running)"""
        if not self.started:
            self.started = True
            super().start()

    def stop(self) -> None:
        """Stop the animation (if running)"""
        if self.started:
            self.started = False
            super().stop()
