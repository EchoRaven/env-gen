"""Pure log parser + aggregator for .agent_logs/<Agent>/<timestamp>.jsonl files."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


_TOOL_NAME_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def extract_tool_name(content: str) -> Optional[str]:
    if not isinstance(content, str):
        return None
    m = _TOOL_NAME_RE.match(content)
    return m.group(1) if m else None


def parse_log_file(path: Path) -> Iterable[Dict]:
    """Yield parsed event dicts; silently skip malformed lines."""
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict):
                yield ev


def _parse_ts(ts: str) -> Optional[float]:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None


@dataclass
class AgentStats:
    name: str
    total_events: int = 0
    prompt_count: int = 0
    tool_call_count: int = 0
    consult_count: int = 0  # skill-trigger L3b: get_skill consults (skill_consulted events)
    top_tools: List[Tuple[str, int]] = field(default_factory=list)
    first_event_ts: Optional[float] = None
    last_event_ts: Optional[float] = None
    span_seconds: float = 0.0
    event_type_counts: List[Tuple[str, int]] = field(default_factory=list)


@dataclass
class LogStats:
    per_agent: Dict[str, AgentStats] = field(default_factory=dict)
    top_tools_across_agents: List[Tuple[str, int]] = field(default_factory=list)
    event_type_counts: List[Tuple[str, int]] = field(default_factory=list)
    total_agents: int = 0
    total_events: int = 0


def aggregate_logs(logs_dir: Path) -> LogStats:
    """Walk logs_dir/<Agent>/*.jsonl and aggregate stats."""
    logs_dir = Path(logs_dir)
    if not logs_dir.exists():
        return LogStats()

    per_agent: Dict[str, AgentStats] = {}
    cross_tools: Counter = Counter()
    cross_types: Counter = Counter()
    total_events = 0

    for agent_dir in sorted(p for p in logs_dir.iterdir() if p.is_dir()):
        name = agent_dir.name
        a = AgentStats(name=name)
        agent_tools: Counter = Counter()
        agent_types: Counter = Counter()
        timestamps: List[float] = []
        for jsonl in sorted(agent_dir.glob("*.jsonl")):
            for ev in parse_log_file(jsonl):
                a.total_events += 1
                total_events += 1
                et = ev.get("event_type", "")
                agent_types[et] += 1
                cross_types[et] += 1
                if et == "prompt":
                    a.prompt_count += 1
                if et == "tool_call":
                    a.tool_call_count += 1
                    tool = extract_tool_name(ev.get("content", ""))
                    if tool:
                        agent_tools[tool] += 1
                        cross_tools[tool] += 1
                if et == "skill_consulted":
                    a.consult_count += 1
                ts = _parse_ts(ev.get("timestamp"))
                if ts is not None:
                    timestamps.append(ts)
        if timestamps:
            a.first_event_ts = min(timestamps)
            a.last_event_ts = max(timestamps)
            a.span_seconds = a.last_event_ts - a.first_event_ts
        a.top_tools = agent_tools.most_common(10)
        a.event_type_counts = sorted(agent_types.items(),
                                       key=lambda kv: -kv[1])
        per_agent[name] = a

    return LogStats(
        per_agent=per_agent,
        top_tools_across_agents=cross_tools.most_common(20),
        event_type_counts=sorted(cross_types.items(), key=lambda kv: -kv[1]),
        total_agents=len(per_agent),
        total_events=total_events,
    )


__all__ = ["LogStats", "AgentStats", "parse_log_file", "aggregate_logs",
            "extract_tool_name"]
