"""
System Metrics Tools — replaces crdt_metrics_tools.py

SystemMetrics wraps the JSON stores under shared/hubs/ directly (no hub runtime
dependency) for token-usage, performance, and retry tracking.

LLM tool classes expose these to agents.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from ._base import BaseTool, ToolResult as _BaseToolResult, create_tool_param

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing table
# ---------------------------------------------------------------------------
# Prices are USD per 1K tokens (cost calc divides token count by 1000).
TOKEN_PRICING: dict = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
    # Claude 4.x family (2026 list prices: $15/$75, $3/$15, $1/$5 per 1M tokens)
    "claude-opus-4-7":     {"input": 0.015,  "output": 0.075},
    "claude-opus-4-6":     {"input": 0.015,  "output": 0.075},
    "claude-sonnet-4-6":   {"input": 0.003,  "output": 0.015},
    "claude-haiku-4-5":    {"input": 0.001,  "output": 0.005},
    # GPT-5 family (2026 list prices: $5/$20, $1/$4 per 1M tokens)
    "gpt-5":               {"input": 0.005,  "output": 0.020},
    "gpt-5-mini":          {"input": 0.001,  "output": 0.004},
    "default": {"input": 0.005, "output": 0.015},
}


# ---------------------------------------------------------------------------
# SystemMetrics — thin JSON-store wrapper
# ---------------------------------------------------------------------------

class SystemMetrics:
    """
    Manages system-level metrics JSON stores located in <output_dir>/shared/hubs/.

    Stores:
      - system_token_usage.json
      - system_performance.json
      - system_retries.json
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self._store_dir = self.output_dir / "shared" / "hubs"
        self._store_dir.mkdir(parents=True, exist_ok=True)

        self._token_file = self._store_dir / "system_token_usage.json"
        self._perf_file = self._store_dir / "system_performance.json"
        self._retry_file = self._store_dir / "system_retries.json"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self, path: Path) -> dict:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.debug("SystemMetrics._load %s: %s", path, e)
        return {}

    def _save(self, path: Path, data: dict) -> None:
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("SystemMetrics._save %s: %s", path, e)

    # ------------------------------------------------------------------
    # Token usage
    # ------------------------------------------------------------------

    def record_token_usage(
        self,
        agent_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        request_type: str = "chat",
    ) -> dict:
        data = self._load(self._token_file)
        entry = data.get(agent_id) or {
            "total_input": 0,
            "total_output": 0,
            "total_cost": 0.0,
            "requests": 0,
            "by_model": {},
        }
        entry["total_input"] += input_tokens
        entry["total_output"] += output_tokens
        entry["requests"] += 1

        model_entry = entry.setdefault("by_model", {}).get(model, {
            "input": 0, "output": 0, "requests": 0
        })
        model_entry["input"] += input_tokens
        model_entry["output"] += output_tokens
        model_entry["requests"] += 1
        entry["by_model"][model] = model_entry

        pricing = TOKEN_PRICING.get(model, TOKEN_PRICING["default"])
        cost = (input_tokens / 1000 * pricing["input"] +
                output_tokens / 1000 * pricing["output"])
        entry["total_cost"] = entry.get("total_cost", 0.0) + cost

        data[agent_id] = entry
        self._save(self._token_file, data)
        return entry

    def get_token_usage(self, agent_id: Optional[str] = None) -> dict:
        data = self._load(self._token_file)
        if agent_id:
            return data.get(agent_id, {})

        total_input = sum(u.get("total_input", 0) for u in data.values() if isinstance(u, dict))
        total_output = sum(u.get("total_output", 0) for u in data.values() if isinstance(u, dict))
        total_cost = sum(u.get("total_cost", 0.0) for u in data.values() if isinstance(u, dict))
        total_requests = sum(u.get("requests", 0) for u in data.values() if isinstance(u, dict))
        return {
            "by_agent": data,
            "total": {
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_input + total_output,
                "estimated_cost": round(total_cost, 4),
                "total_requests": total_requests,
            },
        }

    def get_token_budget_status(self, budget_usd: float = 10.0) -> dict:
        usage = self.get_token_usage()
        total_cost = usage["total"]["estimated_cost"]
        return {
            "budget": budget_usd,
            "spent": total_cost,
            "remaining": max(0.0, budget_usd - total_cost),
            "percent_used": min(100, int(total_cost / budget_usd * 100)) if budget_usd else 0,
            "over_budget": total_cost > budget_usd,
        }

    # ------------------------------------------------------------------
    # Performance
    # ------------------------------------------------------------------

    def record_operation_time(
        self,
        operation: str,
        duration_ms: float,
        agent_id: str = "",
    ) -> dict:
        data = self._load(self._perf_file)
        entry = data.get(operation) or {
            "count": 0,
            "total_ms": 0.0,
            "min_ms": None,
            "max_ms": None,
        }
        entry["count"] += 1
        entry["total_ms"] = entry.get("total_ms", 0.0) + duration_ms
        entry["min_ms"] = min(entry["min_ms"], duration_ms) if entry["min_ms"] is not None else duration_ms
        entry["max_ms"] = max(entry["max_ms"], duration_ms) if entry["max_ms"] is not None else duration_ms
        entry["last_recorded_by"] = agent_id
        entry["last_recorded_at"] = time.time()
        data[operation] = entry
        self._save(self._perf_file, data)
        return entry

    def get_performance_stats(self, operation: Optional[str] = None) -> dict:
        data = self._load(self._perf_file)
        if operation:
            return data.get(operation, {})
        result = {}
        for op, entry in data.items():
            count = entry.get("count", 0)
            result[op] = {
                **entry,
                "avg_ms": round(entry.get("total_ms", 0.0) / count, 2) if count else None,
            }
        return result

    # ------------------------------------------------------------------
    # Retries
    # ------------------------------------------------------------------

    def record_retry(
        self,
        operation: str,
        agent_id: str = "",
        reason: str = "",
    ) -> dict:
        data = self._load(self._retry_file)
        entry = data.get(operation) or {"count": 0, "by_agent": {}, "reasons": []}
        entry["count"] += 1
        agent_counts = entry.setdefault("by_agent", {})
        agent_counts[agent_id] = agent_counts.get(agent_id, 0) + 1
        if reason:
            reasons = entry.setdefault("reasons", [])
            reasons.append(reason)
            entry["reasons"] = reasons[-50:]  # keep last 50
        entry["last_recorded_at"] = time.time()
        data[operation] = entry
        self._save(self._retry_file, data)
        return entry

    def get_retry_stats(self, operation: Optional[str] = None) -> dict:
        data = self._load(self._retry_file)
        if operation:
            return data.get(operation, {})
        return data


# ---------------------------------------------------------------------------
# ToolResult compat wrapper
# ---------------------------------------------------------------------------

