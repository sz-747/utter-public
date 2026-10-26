# coding: utf-8
"""
Dictionary manager

HotwordManager loads the dictionary files, applies replacements and watches the files for changes.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Dict, Callable, Optional, TYPE_CHECKING, Any, Tuple

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from rich.console import Console

from .hot_rule import RuleCorrector
from .hot_phoneme import PhonemeCorrector
from .hot_rectification import RectificationRAG

# Use the client's settings when available, else local defaults (standalone use)
try:
    from config_client import ClientConfig
    HOT_THRESH = ClientConfig.hot_thresh
    HOT_SIMILAR = ClientConfig.hot_similar
    RECTIFY_THRESH = ClientConfig.hot_rectify
    HOT_THRESH_RARE = getattr(ClientConfig, 'hot_thresh_rare', None)
except ImportError:
    HOT_THRESH = 0.8
    HOT_SIMILAR = 0.6
    RECTIFY_THRESH = 0.5
    HOT_THRESH_RARE = None

from . import logger

try:
    from util.client.state import console
except ImportError:
    try:
        from rich.console import Console
        console = Console(highlight=False)
    except ImportError:
        class MockConsole:
            def print(self, *args, **kwargs):
                # drop rich markup and print the text
                msg = str(args[0]) if args else ""
                print(msg.replace('[cyan]', '').replace('[/]', '').replace('[green4]', ''))
            def line(self): print()
        console = MockConsole()

# Singleton
_manager: Optional[HotwordManager] = None

class HotwordManager:
    """Dictionary manager: loads the dictionary files and reloads them when they change"""

    def __init__(self,
                 hotword_files: Optional[Dict[str, Path]] = None,
                 threshold: float = 0.7,
                 similar_threshold: Optional[float] = None,
                 rectify_threshold: float = 0.5):
        """
        Args:
            hotword_files: file map {'hot': Path, 'rule': Path, 'rectify': Path}
            threshold: replacement threshold
            similar_threshold: similarity threshold
        """
        self.files = hotword_files or {
            'hot': Path('hot.txt'),
            'rule': Path('hot-rule.txt'),
            'rectify': Path('hot-rectify.txt'),
        }

        self.threshold = threshold
        self.similar_threshold = similar_threshold
        self.rectify_threshold = rectify_threshold

        self.phoneme_corrector = PhonemeCorrector(threshold=threshold, similar_threshold=similar_threshold,
                                                  rare_threshold=HOT_THRESH_RARE)
        self.rule_corrector = RuleCorrector()
        self.rectify_rag = RectificationRAG(
            str(self.files.get('rectify', 'hot-rectify.txt')),
            threshold=rectify_threshold
        )

        self._observer: Optional[Observer] = None

    def _format_msg(self, label: str, filename: str, count: int) -> str:
        """An aligned load message."""
        return f"[bold cyan]{label:<12}: [/][cyan]{filename:<16}[/] loaded [green]{count:3d}[/]"

    def load_all(self) -> None:
        """Load everything for the first time."""
        logger.info("Loading dictionary files...")
        self._load_hot()
        self._load_rule()
        self._load_rectify()
        logger.info("Dictionary files loaded")

    def _read_file(self, key: str) -> str:
        """Read one dictionary file."""
        path = self.files.get(key)
        if not path: return ""
        try:
            if not path.exists():
                # The learned files are created by Utter or the edit watcher when needed
                if key in ('learned', 'rule_learned'):
                    return ""
                # Start a missing file from its example (hot.example.txt for hot.txt), else empty
                path.parent.mkdir(parents=True, exist_ok=True)
                example = path.with_name(path.stem + '.example' + path.suffix)
                text = example.read_text(encoding='utf-8') if example.exists() else "# One dictionary word per line\n"
                path.write_text(text, encoding='utf-8')
                return text
            return path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"Reading {path} failed: {e}")
            return ""

    def _load_hot(self) -> None:
        # Your own words and the learned words (hot-learned.txt) form one dictionary
        content = self._read_file('hot') + '\n' + self._read_file('learned')
        num = self.phoneme_corrector.update_hotwords(content)
        console.print(self._format_msg("Dictionary", "hot.txt", num))

    def _load_rule(self) -> None:
        content = self._read_file('rule') + '\n' + self._read_file('rule_learned')
        num = self.rule_corrector.update_rules(content)
        console.print(self._format_msg("Rules", "hot-rule.txt", num))

    def _load_rectify(self) -> None:
        # RectificationRAG loads its own file
        self.rectify_rag.load_history()
        count = len(self.rectify_rag.records) if hasattr(self.rectify_rag, 'records') else 0
        console.print(self._format_msg("Corrections", "hot-rectify.txt", count))

    def get_phoneme_corrector(self) -> PhonemeCorrector:
        return self.phoneme_corrector

    def get_rule_corrector(self) -> RuleCorrector:
        return self.rule_corrector

    def get_rectify_rag(self) -> RectificationRAG:
        return self.rectify_rag

    def start_file_watcher(self) -> Any:
        """Start watching the files."""
        if self._observer: return

        self._observer = Observer()
        handler = _HotwordFileHandler(self)

        # Watch each file's folder (once per folder)
        watched_dirs = {p.parent.absolute() for p in self.files.values()}
        for d in watched_dirs:
            self._observer.schedule(handler, path=str(d), recursive=False)

        self._observer.start()
        logger.debug(f"Watching dictionary files in: {watched_dirs}")
        return self._observer

    def stop_file_watcher(self) -> None:
        """Stop watching the files."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.debug("Stopped watching dictionary files")


class _HotwordFileHandler(FileSystemEventHandler):
    """Reloads a dictionary file when it changes"""

    _debounce_delay = 3

    def __init__(self, manager: HotwordManager):
        super().__init__()
        self.manager = manager
        self._pending = set()
        self._last_event = 0.0
        self._timer = None
        self._lock = threading.Lock()

        # File name -> load function, kept in step with manager.files
        self._update_mapping()

    def _update_mapping(self):
        m = self.manager
        self._file_mapping = {
            m.files['hot'].name: m._load_hot,
            m.files['rule'].name: m._load_rule,
            m.files['rectify'].name: m._load_rectify,
        }
        if 'learned' in m.files:
            self._file_mapping[m.files['learned'].name] = m._load_hot
        if 'rule_learned' in m.files:
            self._file_mapping[m.files['rule_learned'].name] = m._load_rule

    def on_created(self, event):
        """The learned files also need loading when first created."""
        self.on_modified(event)

    def on_moved(self, event):
        """Atomic writes (temporary file, then rename) count under the target name."""
        if not event.is_directory:
            self._handle(Path(event.dest_path).name)

    def on_modified(self, event):
        if event.is_directory: return
        self._handle(Path(event.src_path).name)

    def _handle(self, filename: str):
        if filename not in self._file_mapping:
            return

        logger.debug(f"[watchdog] dictionary file changed: {filename}")

        with self._lock:
            # Keep every pending file, so several changes close together all reload
            self._pending.add(filename)
            self._last_event = time.time()
            if self._timer is None or not self._timer.is_alive():
                self._timer = threading.Thread(target=self._debounced_worker, daemon=True)
                self._timer.start()

    def _debounced_worker(self):
        """Debounce worker."""
        while True:
            time.sleep(self._debounce_delay)

            with self._lock:
                if not self._pending:
                    break
                if time.time() - self._last_event < self._debounce_delay:
                    continue
                filenames, self._pending = self._pending, set()

            # Run each load function once
            handlers = {}
            for filename in filenames:
                handler = self._file_mapping.get(filename)
                if handler:
                    handlers.setdefault(handler, filename)
            for handler, filename in handlers.items():
                try:
                    handler()
                    logger.info(f"Dictionary file reloaded: {filename}")
                except Exception as e:
                    console.print(f'Reloading the dictionary failed: {e}', style='bright_red')
                    logger.error(f"Reloading the dictionary failed: {e}", exc_info=True)
            break


# ======================================================================
# --- Singleton access ---

def get_hotword_manager(hotword_files: Optional[Dict[str, Path]] = None,
                        threshold: float = 0.7,
                        similar_threshold: Optional[float] = None,
                        rectify_threshold: float = 0.5) -> HotwordManager:
    """
    The dictionary manager singleton.
    The first call may pass settings; later calls return the same instance.
    """
    global _manager
    if _manager is None:
        _manager = HotwordManager(
            hotword_files=hotword_files,
            threshold=threshold,
            similar_threshold=similar_threshold,
            rectify_threshold=rectify_threshold
        )
    return _manager
