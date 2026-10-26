"""The dictation client's folder (../dictation), which Utter shows and controls.

Utter has no dictation code of its own. The client writes the transcript archive,
the status and settings files and the dictionary files; Utter imports the
client's own modules for those formats (config_client, util.app_settings,
util.dictionary_files, util.text_metrics) so each format has one owner.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'dictation'


def attach() -> Path:
    """Make the client's modules importable; returns its folder."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return ROOT
