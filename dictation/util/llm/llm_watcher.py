"""
LLM settings file watcher

Features:
1. Watches the LLM/ folder for file changes
2. Reloads changed role settings automatically (debounced, delayed)
3. Prints role info

Decoupled design:
- Talks to the handler through callbacks rather than depending on its internals
"""

import time
import threading
from pathlib import Path
from typing import Callable, Dict, List, Any, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from util.llm.llm_constants import WatcherConstants
from util.llm.llm_role_formatter import RoleFormatter
from . import logger



class LLMFileWatcher(FileSystemEventHandler):
    """LLM settings file watcher

    Talks to the handler through callbacks, to keep them loosely coupled.
    """

    def __init__(
        self,
        on_roles_reload: Callable[[], None],
        get_roles: Callable[[], Dict[str, Any]],
    ):
        """Set up the file watcher

        Args:
            on_roles_reload: callback that reloads the role settings
            get_roles: callback that returns the current roles
        """
        # Callbacks
        self._on_roles_reload = on_roles_reload
        self._get_roles = get_roles

        self.observer = Observer()
        from config_client import BASE_DIR
        self.base_dir = Path(BASE_DIR)
        self.llm_dir = self.base_dir / 'LLM'

        # Debounce + delayed run
        self._last_event: Optional[tuple] = None  # (file_path, time)
        self._timer: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._debounce_delay = WatcherConstants.DEBOUNCE_DELAY

        # Settings files to watch and their handlers
        # Note: hot-rectify.txt is handled by the hotword watchdog, not by the LLM watcher
        self._watched_files = {}

        logger.debug("LLMFileWatcher ready")

    def _is_llm_py_file(self, file_path: str) -> bool:
        """Is this a valid .py file in the LLM folder?"""
        if not file_path.endswith(WatcherConstants.PY_EXTENSION):
            return False
        if WatcherConstants.CACHE_DIR in file_path:
            return False
        # Compare paths with Path to be strict
        try:
            path = Path(file_path).resolve()
            return path.parent == self.llm_dir.resolve()
        except Exception:
            return False

    def on_modified(self, event):
        """Called when a file changes"""
        if event.is_directory:
            return

        file_path = str(event.src_path)
        file_name = Path(file_path).name

        # Is it one of the watched settings files?
        if file_name in self._watched_files:
            self._watched_files[file_name]()
            return

        # Is it a .py file in the LLM folder?
        if not self._is_llm_py_file(file_path):
            return

        self._schedule_reload(file_path)

    def on_created(self, event):
        """Called when a file is created"""
        if event.is_directory:
            return

        file_path = str(event.src_path)

        if not self._is_llm_py_file(file_path):
            return

        # New file: reload all roles
        self._schedule_reload(WatcherConstants.RELOAD_ALL_MARKER)

    def on_deleted(self, event):
        """Called when a file is deleted"""
        if event.is_directory:
            return

        file_path = str(event.src_path)

        if not self._is_llm_py_file(file_path):
            return

        # File deleted: reload all roles
        self._schedule_reload(WatcherConstants.RELOAD_ALL_MARKER)

    def on_moved(self, event):
        """Called when a file is moved or renamed"""
        if event.is_directory:
            return

        src_path = str(event.src_path)
        dest_path = str(event.dest_path)

        # Does it involve a .py file?
        if not (self._is_llm_py_file(src_path) or self._is_llm_py_file(dest_path)):
            return

        # File renamed: reload all roles
        self._schedule_reload(WatcherConstants.RELOAD_ALL_MARKER)

    def _schedule_reload(self, file_path: str):
        """Schedule a reload (debounced)"""
        current_time = time.time()

        with self._lock:
            self._last_event = (file_path, current_time)

            # Start a timer if none is running
            if self._timer is None or not self._timer.is_alive():
                self._timer = threading.Thread(target=self._debounced_worker, daemon=True)
                self._timer.start()

    def _debounced_worker(self):
        """Debounce worker thread"""
        while True:
            with self._lock:
                if self._last_event is None:
                    break

                _, last_time = self._last_event
                current_time = time.time()

                # Not time yet: keep waiting
                if current_time - last_time < self._debounce_delay:
                    pass
                else:
                    # Time is up: reload
                    event_info = self._last_event
                    self._last_event = None
                    # Release the lock for the slow work
                    self._lock.release()
                    try:
                        self._do_reload(event_info[0])
                    finally:
                        self._lock.acquire()
                    break

            time.sleep(0.1)

    def _do_reload(self, file_path: str):
        """Run the reload"""
        if file_path == WatcherConstants.RELOAD_ALL_MARKER:
            logger.info("Files changed, reloading all roles...")
            print(f"\n[LLM watcher] Files changed, reloading all roles...")
            self._on_roles_reload()
            self._print_all_roles()
        else:
            file_name_stem = Path(file_path).stem
            module_name = f"LLM.{file_name_stem}"

            logger.debug(f"File changed: {Path(file_path).name}")
            self._on_roles_reload()

            # Find and print only the roles from that file
            roles = self._get_roles()
            found = False
            for role_name, role_config in roles.items():
                # Does module_name match?
                if role_config.module_name == module_name:
                    self._print_role_info(role_name, role_config)
                    found = True

            if not found:
                # The file name may not match the role.name inside it
                logger.debug(f"No role comes directly from file '{file_name_stem}', showing all roles")
                print(f"(No role comes directly from file '{file_name_stem}', showing all roles)")
                self._print_all_roles()

    def start(self):
        """Start watching"""
        # Watch the LLM folder
        self.observer.schedule(self, str(self.llm_dir), recursive=False)
        # Also watch the base folder (for the hot files), non-recursive
        self.observer.schedule(self, str(self.base_dir), recursive=False)

        self.observer.start()
        logger.info("LLM file watcher started")

        # Print all loaded roles
        self._print_all_roles()

    def stop(self):
        """Stop watching"""
        self.observer.stop()
        self.observer.join()
        logger.info("LLM file watcher stopped")

    def _print_all_roles(self):
        """Print all loaded roles"""
        print(f"\nLLM roles")

        roles = self._get_roles()

        if not roles:
            print("No roles loaded")
            return

        for role_name, role_config in roles.items():
            self._print_role_info(role_name, role_config)

        print(f"")

    def _print_role_info(self, role_name: str, role_config):
        """Print one role (Rich, with colors)"""
        RoleFormatter.print_status(role_name, role_config)
