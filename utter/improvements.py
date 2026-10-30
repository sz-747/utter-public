"""Read-only view of the bundled client's learning receipts."""
from pathlib import Path

def status(root: Path) -> dict:
    from util import learning_status
    return learning_status.snapshot(Path(root) / 'appdata' / 'learning')
