# coding: utf-8
"""
UDP control.

Starts and stops recording on UDP commands, so other programs can trigger dictation.

Command protocol:
- START: start recording
- STOP: stop recording
"""

from __future__ import annotations

import socket
import threading
from typing import TYPE_CHECKING

from config_client import ClientConfig as Config
from . import logger

if TYPE_CHECKING:
    from util.client.shortcut.shortcut_manager import ShortcutManager



class UDPController:
    """
    UDP controller.

    Listens on a UDP port in a background thread for commands that start/stop recording.
    """

    def __init__(self, shortcut_manager: ShortcutManager):
        """
        Set up the UDP controller.

        Args:
            shortcut_manager: shortcut manager instance, used to control recording
        """
        self.manager = shortcut_manager
        self.running = False
        self._thread = None
        self._sock = None

    def start(self) -> None:
        """Start listening."""
        if self.running:
            return

        self.running = True
        self._thread = threading.Thread(target=self._listen, daemon=True, name="UDPController")
        self._thread.start()
        logger.info(f"UDP controller started on port {Config.udp_control_port}")

    def stop(self) -> None:
        """Stop listening."""
        self.running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        logger.info("UDP controller stopped")

    def _listen(self) -> None:
        """Listen loop."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((Config.udp_control_addr, Config.udp_control_port))
            self._sock.settimeout(0.5)

            logger.debug(f"UDP controller bound to {Config.udp_control_addr}:{Config.udp_control_port}")

            while self.running:
                try:
                    data, addr = self._sock.recvfrom(1024)
                    command = data.decode('utf-8').strip().upper()
                    self._handle_command(command, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        logger.error(f"UDP controller receive error: {e}")

        except Exception as e:
            logger.error(f"UDP controller failed to start: {e}")
        finally:
            if self._sock:
                self._sock.close()

    def _handle_command(self, command: str, addr: tuple) -> None:
        """
        Handle a received command.

        Args:
            command: command string (START/STOP)
            addr: sender address
        """
        state = self.manager.state

        if command == 'START':
            if not state.recording:
                logger.info(f"UDP control: start recording (from {addr[0]}:{addr[1]})")
                # Start recording with the first available shortcut task
                if self.manager.tasks:
                    first_task = next(iter(self.manager.tasks.values()))
                    first_task.launch()
            else:
                logger.debug("UDP control: ignoring START (already recording)")

        elif command == 'STOP':
            if state.recording:
                logger.info(f"UDP control: stop recording (from {addr[0]}:{addr[1]})")
                # Stop every recording task
                for task in self.manager.tasks.values():
                    if task.is_recording:
                        task.finish()
            else:
                logger.debug("UDP control: ignoring STOP (not recording)")

        else:
            logger.warning(f"UDP control: unknown command '{command}' (from {addr[0]}:{addr[1]})")
