"""
Lightweight structured debug logger used by BaseAgent.

Writes one JSON object per line (jsonl) so logs are easy to parse.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class StructuredLogger:
    """Minimal JSONL logger with a stable `.log(...)` interface."""

    def __init__(self, log_file: str):
        self._path = Path(log_file)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, event_type: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        record = {
            "timestamp": datetime.now().isoformat(),
            "event_type": str(event_type or ""),
            "content": str(content or ""),
            "metadata": metadata or {},
        }
        line = json.dumps(record, ensure_ascii=True, default=str)
        with self._lock:
            # Defensive: if parent dir was deleted/never existed at this exact path
            # (e.g. workspace relocated by _relocate_debug_log_to, a different code
            # path retained a stale Path reference, or external cleanup removed it
            # mid-run), re-create it before opening. Without this, log() raises
            # FileNotFoundError and the calling task fails — observed in
            # `resident_coordination_tick` during 2026-05-31 validation #2 where
            # the orchestrator stalled with 49 such errors over ~5 minutes.
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")

