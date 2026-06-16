from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any


class ProcessingState(Enum):
    """Agent processing state - simplified."""

    IDLE = "idle"
    PROCESSING_TASK = "processing"
    ANSWERING_QUESTION = "answering"


def safe_json_dumps(obj: Any, indent: int = 2) -> str:
    """Safely serialize object to JSON."""

    def default_handler(o: Any) -> Any:
        if hasattr(o, "to_dict"):
            return o.to_dict()
        if hasattr(o, "__dict__"):
            return {k: v for k, v in o.__dict__.items() if not k.startswith("_")}
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Enum):
            return o.value
        return str(o)

    try:
        return json.dumps(obj, indent=indent, default=default_handler)
    except Exception:
        return str(obj)
