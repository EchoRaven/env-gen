"""Pure per-agent reasoning_effort resolution (no LLM, no global state, no I/O cache).

Runtime source of truth: a per-run ``reasoning_effort.json`` (lane -> effort) in the
workspace base_dir, writable live by live_monitor. Resolution falls back to the agent's
per-profile default, then the global :data:`DEFAULT_EFFORT`.

The file is read fresh on every resolve (it is tiny and read at most once per multi-second
LLM call), so a live edit is picked up on the agent's next call with no caching/mtime games.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

VALID_EFFORTS = ("minimal", "low", "medium", "high")
DEFAULT_EFFORT = "medium"
_FILENAME = "reasoning_effort.json"


def normalize_effort(value: Optional[str]) -> str:
    """Return a valid effort, fail-soft to DEFAULT_EFFORT on anything unrecognized."""
    if isinstance(value, str) and value.strip().lower() in VALID_EFFORTS:
        return value.strip().lower()
    if value is not None:
        logger.warning("reasoning_effort: unknown value %r -> %s", value, DEFAULT_EFFORT)
    return DEFAULT_EFFORT


def _path(base_dir) -> Path:
    return Path(base_dir) / _FILENAME


def read_effort_map(base_dir) -> Dict[str, str]:
    """Read the lane->effort map; missing/malformed file yields an empty map."""
    try:
        data = json.loads(_path(base_dir).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_effort_map(base_dir, mapping: Dict[str, str]) -> None:
    """Atomically write the lane->effort map (values coerced to str)."""
    path = _path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({str(k): str(v) for k, v in mapping.items()}, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def resolve_effort(base_dir, lane: str, profile_default: Optional[str]) -> str:
    """Resolve effort for ``lane``: live file > profile default > global default."""
    file_map = read_effort_map(base_dir)
    if lane in file_map:
        return normalize_effort(file_map[lane])
    if profile_default is not None:
        return normalize_effort(profile_default)
    return DEFAULT_EFFORT
