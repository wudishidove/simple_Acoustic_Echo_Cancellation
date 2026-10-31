"""Atomic UTF-8 JSON snapshots shared by the UI and Windows worker processes."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time


def read_json(path):
    # Release the Windows read handle before parsing, minimizing the rename lock.
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value, *, retry_timeout=1.0):
    """Publish a complete snapshot, preserving the old file if replacement fails."""
    path = Path(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=f'.{path.stem}.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        deadline, pause = time.monotonic() + retry_timeout, .01
        while True:
            try:
                temporary.replace(path)
                return
            except OSError as exc:
                remaining = deadline - time.monotonic()
                if getattr(exc, 'winerror', None) not in (5, 32, 33) or remaining <= 0:
                    raise
                time.sleep(min(pause, remaining))
                pause = min(.05, pause * 2)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Preserve the original I/O error if an external program also locks the temp file.
