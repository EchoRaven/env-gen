"""HTML dashboard renderer for LogStats (Cutover 17)."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Optional

from .log_parser import LogStats


_STYLE = """
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       margin: 24px; color: #1a1a1a; }
h1 { font-size: 22px; margin-bottom: 4px; }
h2 { font-size: 16px; margin-top: 32px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
h3 { font-size: 14px; margin-top: 16px; }
table { border-collapse: collapse; width: 100%; max-width: 900px; margin: 8px 0; }
th, td { padding: 4px 10px; border-bottom: 1px solid #eee; text-align: left; font-size: 13px; }
th { background: #f5f5f5; }
.summary { color: #555; font-size: 13px; margin-bottom: 16px; }
.agent { background: #fafafa; padding: 12px 16px; margin: 12px 0; border-left: 3px solid #4a90e2; }
.tool-count { color: #888; font-variant-numeric: tabular-nums; }
.empty { color: #999; font-style: italic; }
</style>
"""


def _fmt_ts(ts: Optional[float]) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _fmt_duration(s: float) -> str:
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{s/60:.1f}m"
    return f"{s/3600:.2f}h"


def _table_rows(items, columns):
    rows = []
    for item in items:
        cells = "".join(f"<td>{html.escape(str(c))}</td>" for c in item)
        rows.append(f"<tr>{cells}</tr>")
    header = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def render_dashboard(stats: LogStats, output_path: Optional[Path] = None) -> str:
    parts = []
    parts.append("<!doctype html><html><head><meta charset='utf-8'>")
    parts.append("<title>Agent Observability Dashboard</title>")
    parts.append(_STYLE)
    parts.append("</head><body>")
    parts.append("<h1>Agent Observability Dashboard</h1>")
    parts.append(f"<div class='summary'>Generated: {datetime.now().isoformat(timespec='seconds')} - "
                  f"total agents: {stats.total_agents} - total events: {stats.total_events}</div>")

    parts.append("<h2>Top tools across all agents</h2>")
    if stats.top_tools_across_agents:
        parts.append(_table_rows(
            stats.top_tools_across_agents, ["Tool", "Count"]))
    else:
        parts.append("<div class='empty'>No tool calls observed.</div>")

    parts.append("<h2>Event type breakdown</h2>")
    if stats.event_type_counts:
        parts.append(_table_rows(stats.event_type_counts,
                                  ["Event type", "Count"]))
    else:
        parts.append("<div class='empty'>No events observed.</div>")

    parts.append("<h2>Per-agent</h2>")
    if not stats.per_agent:
        parts.append("<div class='empty'>No agents observed.</div>")
    for name, a in sorted(stats.per_agent.items()):
        parts.append("<div class='agent'>")
        parts.append(f"<h3>{html.escape(name)}</h3>")
        parts.append(
            f"<div class='summary'>events: {a.total_events} - "
            f"prompts: {a.prompt_count} - tool calls: {a.tool_call_count} - "
            f"span: {_fmt_duration(a.span_seconds)} "
            f"({_fmt_ts(a.first_event_ts)} -> {_fmt_ts(a.last_event_ts)})</div>")
        if a.top_tools:
            parts.append("<h3>Top tools</h3>")
            parts.append(_table_rows(a.top_tools, ["Tool", "Count"]))
        if a.event_type_counts:
            parts.append("<h3>Event types</h3>")
            parts.append(_table_rows(a.event_type_counts, ["Type", "Count"]))
        parts.append("</div>")

    parts.append("</body></html>")
    rendered = "".join(parts)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered)

    return rendered


__all__ = ["render_dashboard"]
