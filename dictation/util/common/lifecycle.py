import time
import os
import asyncio
import signal
import sys
import threading
import atexit
import logging
from typing import List, Callable, Optional

class LifecycleManager:
    """
    Application lifecycle manager (singleton)

    Handles in one place:
    1. Signal handling
    2. Shutdown requests
    3. Resource cleanup
    4. Shutdown state
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(LifecycleManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._is_shutting_down = False
        self._shutdown_event = None  # created later, in initialize
        self._cleanup_callbacks: List[Callable] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Default logger (console); initialize can replace it
        self.logger = logging.getLogger('lifecycle')
        self._exit_on_signal = False
        self._last_sigint_time = 0.0

        # Register with atexit as the last line of defence
        atexit.register(self._atexit_handler)

    def initialize(self,
                   loop: asyncio.AbstractEventLoop = None,
                   logger: logging.Logger = None,
                   exit_on_signal: bool = False):
        """
        Initialize the manager

        Args:
            loop: Event loop
            logger: The client's logger
            exit_on_signal: Whether to exit immediately when a signal arrives (used by the client)
        """
        if loop:
            self._loop = loop
        else:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

        # Create the Event in the current event loop
        if self._loop and not self._shutdown_event:
            self._shutdown_event = asyncio.Event()

        if logger:
            self.logger = logger

        self._exit_on_signal = exit_on_signal

        self._register_signals()
        self.logger.debug("LifecycleManager initialized")

    def _register_signals(self):
        """Register the SIGINT and SIGTERM handlers"""
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            self.logger.debug("Signal handlers registered (LifecycleManager)")
        except Exception as e:
            self.logger.warning(f"Failed to register signal handlers: {e}")

    def _signal_handler(self, signum, frame):
        """Signal callback"""
        signal_name = signal.Signals(signum).name

        # Guard against an accidental press (SIGINT / Ctrl+C only)
        if signum == signal.SIGINT:
            current_time = time.time()
            if current_time - self._last_sigint_time > 1.0:
                self._last_sigint_time = current_time
                print(f"\nReceived {signal_name}. Press again within 1 second to exit...")
                # Log it too, at debug rather than info so it does not flood the log
                self.logger.debug(f"Received {signal_name}, waiting for confirmation...")
                return
            else:
                print(f"Exiting...")

        self.logger.info(f"LifecycleManager received signal: {signal_name} ({signum})")
        self.request_shutdown(reason=f"Signal {signal_name}")

        if self._exit_on_signal:
            self.logger.debug("Exit on signal is on, forcing exit...")
            try:
                self.cleanup()
            finally:
                self.logger.debug("Calling os._exit(0) to stop immediately")
                os._exit(0)

    def register_on_shutdown(self, callback: Callable):
        """Register a cleanup function (run in LIFO order)"""
        if callback not in self._cleanup_callbacks:
            self._cleanup_callbacks.insert(0, callback) # last registered runs first

    def request_shutdown(self, reason="Unknown"):
        """Ask the application to exit"""
        if self._is_shutting_down:
            self.logger.debug(f"Already shutting down, ignoring repeat request (Reason: {reason})")
            return

        self._is_shutting_down = True
        self.logger.info(f"Shutdown requested (Reason: {reason}), shutting down...")

        # 1. Set the asyncio event so the main loop exits
        if self._loop and not self._loop.is_closed() and self._shutdown_event:
            try:
                self._loop.call_soon_threadsafe(self._shutdown_event.set)
            except RuntimeError:
                # The loop may already be closed
                pass

        # 2. Without a running asyncio loop, or when cleanup must happen at once (a non-async
        # program), synchronous work could go here. To be safe we normally rely on the main
        # loop calling cleanup after it sees the event.

    async def wait_for_shutdown(self):
        """Wait for the shutdown signal (coroutine)"""
        if not self._shutdown_event:
            self.logger.warning("Shutdown event not initialized, creating...")
            if not self._loop:
                self._loop = asyncio.get_running_loop()
            self._shutdown_event = asyncio.Event()

        await self._shutdown_event.wait()
        self.logger.info("Shutdown event set, resuming execution...")

    def cleanup(self):
        """Run all cleanup callbacks (only once)"""
        if hasattr(self, '_cleanup_done') and self._cleanup_done:
            return
        self._cleanup_done = True
        self._is_shutting_down = True  # mark as shutting down

        self.logger.debug("LifecycleManager running cleanup callbacks...")
        for callback in self._cleanup_callbacks:
            try:
                name = getattr(callback, '__name__', str(callback))
                self.logger.debug(f"Running cleanup: {name}")
                callback()
            except Exception as e:
                self.logger.error(f"Cleanup callback failed: {e}", exc_info=True)
        self.logger.debug("LifecycleManager cleanup finished")

    def _atexit_handler(self):
        """atexit handler, so cleanup runs last"""
        if not self._is_shutting_down:
            # The logger may already be closed here, so output is unreliable,
            # but try to clean up anyway
            try:
                self.logger.debug("atexit triggered, cleaning up...")
                self.cleanup()
            except:
                pass

    @property
    def is_shutting_down(self) -> bool:
        return self._is_shutting_down

# Global instance
lifecycle = LifecycleManager()
