"""CLI: python -m multi_agent.runtime.observability --logs-dir X --output Y."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dashboard import render_dashboard
from .log_parser import aggregate_logs


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Render agent observability dashboard.")
    p.add_argument("--logs-dir", required=True, help="Path to agent/.agent_logs/")
    p.add_argument("--output", required=True, help="Output HTML path")
    args = p.parse_args(argv)

    stats = aggregate_logs(Path(args.logs_dir))
    render_dashboard(stats, output_path=Path(args.output))
    print(f"Dashboard written to {args.output} "
          f"(agents={stats.total_agents}, events={stats.total_events})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
