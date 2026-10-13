"""Small JSON helpers with atomic writes and stable formatting."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def dumps(data: Any, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def write_json(path: Path, data: Any, *, pretty: bool = False) -> None:
    write_text(path, dumps(data, pretty=pretty))


def write_text(path: Path, text: str) -> None:
    write_bytes(path, text.encode("utf-8"))


FILE_MODE = 0o644  # mkstemp creates 0600; published files must be readable by the web server


def write_bytes(path: Path, payload: bytes) -> None:
    """Write through a temporary file and rename, so readers never see half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
