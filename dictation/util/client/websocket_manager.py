# coding: utf-8
"""
WebSocket connection management

Provides the WebSocketManager class, which manages the WebSocket connection
to the server: connecting, reconnecting, sending messages and checking the
connection state.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from config_client import ClientConfig as Config
from . import logger

if TYPE_CHECKING:
    from util.client.state import ClientState



class WebSocketManager:
    """
    WebSocket connection manager

    Manages the WebSocket connection to the recognition server, with
    automatic retries and error handling.

    Attributes:
        state: Client state instance
        max_retries: Maximum number of retries
    """

    def __init__(self, state: 'ClientState', max_retries: int = 3):
        """
        Initialize the WebSocket manager

        Args:
            state: Client state instance
            max_retries: Maximum retries when connecting fails
        """
        self.state = state
        self.max_retries = max_retries

    @property
    def is_connected(self) -> bool:
        """Whether the connection is open"""
        return self.state.is_connected

    async def connect(self) -> bool:
        """
        Open the WebSocket connection

        Connects to the configured server address, retrying on failure.

        Returns:
            Whether the connection succeeded
        """
        # Already connected
        if self.is_connected:
            return True

        # Drop the old connection
        if self.state.websocket is not None:
            self.state.websocket = None

        url = f"ws://{Config.addr}:{Config.port}"

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"Connecting to server {url} (attempt {attempt}/{self.max_retries})")

                self.state.websocket = await websockets.connect(
                    url,
                    subprotocols=["binary"],
                    max_size=None
                )

                logger.info(f"WebSocket connected: {url}")
                return True

            except ConnectionRefusedError:
                logger.warning(f"Connection refused (attempt {attempt}/{self.max_retries})")
            except TimeoutError:
                logger.warning(f"Connection timed out (attempt {attempt}/{self.max_retries})")
            except Exception as e:
                logger.error(f"Connection failed: {e} (attempt {attempt}/{self.max_retries})")

        logger.error(f"Could not connect to server {url} after {self.max_retries} attempts")
        return False

    async def send(self, message: dict) -> bool:
        """
        Send a message to the server

        Args:
            message: Message dict, serialized to JSON

        Returns:
            Whether sending succeeded
        """
        if not self.is_connected:
            logger.warning("Cannot send message: WebSocket not connected")
            return False

        try:
            await self.state.websocket.send(json.dumps(message))
            return True

        except ConnectionClosedError:
            logger.error("Send failed: connection lost")
            self.state.websocket = None
            return False

        except ConnectionClosedOK:
            logger.info("Send failed: connection closed normally")
            self.state.websocket = None
            return False

        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)
            return False

    async def receive(self) -> Optional[dict]:
        """
        Receive a message from the server

        Returns:
            The parsed message dict, or None on failure
        """
        if not self.is_connected:
            logger.warning("Cannot receive message: WebSocket not connected")
            return None

        try:
            message = await self.state.websocket.recv()
            return json.loads(message)

        except ConnectionClosedError:
            logger.error("Receive failed: connection lost")
            self.state.websocket = None
            return None

        except ConnectionClosedOK:
            logger.info("Receive failed: connection closed normally")
            self.state.websocket = None
            return None

        except json.JSONDecodeError as e:
            logger.error(f"Could not parse message: {e}")
            return None

        except Exception as e:
            logger.error(f"Error receiving message: {e}", exc_info=True)
            return None

    async def close(self) -> None:
        """Close the WebSocket connection"""
        if self.state.websocket is not None:
            try:
                await self.state.websocket.close()
                logger.info("WebSocket connection closed")
            except Exception as e:
                logger.debug(f"Error closing the connection: {e}")
            finally:
                self.state.websocket = None
