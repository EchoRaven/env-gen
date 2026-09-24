"""Tests for observability log parser + aggregator (Cutover 17)."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.observability.log_parser import (  # noqa: E402
    LogStats, AgentStats, parse_log_file, aggregate_logs, extract_tool_name,
)


def _write_jsonl(path: Path, events: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


_EVENT_PROMPT = {
    "timestamp": "2026-05-20T18:00:00.000000",
    "event_type": "prompt", "content": "system", "metadata": {"model": "gpt-5.4"},
}
_EVENT_TOOL_QUERY = {
    "timestamp": "2026-05-20T18:00:05.000000",
    "event_type": "tool_call",
    "content": "query_knowledge({'query': 'x'})",
    "metadata": {},
}
_EVENT_TOOL_STORE = {
    "timestamp": "2026-05-20T18:00:10.000000",
    "event_type": "tool_call",
    "content": "store_knowledge({'title': 'x'})",
    "metadata": {},
}
_EVENT_RESULT = {
    "timestamp": "2026-05-20T18:00:12.000000",
    "event_type": "tool_result", "content": "ok", "metadata": {},
}


class ExtractToolNameTests(unittest.TestCase):
    def test_extract_from_tool_call_content(self) -> None:
        self.assertEqual(extract_tool_name("query_knowledge({'q': 'x'})"),
                          "query_knowledge")

    def test_extract_returns_none_for_non_call(self) -> None:
        self.assertIsNone(extract_tool_name("free-form prose"))

    def test_extract_handles_whitespace(self) -> None:
        self.assertEqual(extract_tool_name("  store_knowledge (...)"),
                          "store_knowledge")


class ParseLogFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="obs_parse_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parse_empty_file_yields_nothing(self) -> None:
        f = self.tmp / "empty.jsonl"
        f.touch()
        self.assertEqual(list(parse_log_file(f)), [])

    def test_parse_skips_malformed_json_lines(self) -> None:
        f = self.tmp / "bad.jsonl"
        f.write_text("not json\n" + json.dumps(_EVENT_PROMPT) + "\n")
        events = list(parse_log_file(f))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "prompt")

    def test_parse_returns_all_valid_events(self) -> None:
        f = self.tmp / "good.jsonl"
        _write_jsonl(f, [_EVENT_PROMPT, _EVENT_TOOL_QUERY, _EVENT_RESULT])
        events = list(parse_log_file(f))
        self.assertEqual(len(events), 3)


class AggregateLogsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="obs_agg_"))
        self.logs = self.tmp / "logs"
        # Agent A: 1 prompt + 2 tool calls (1 query, 1 store) + 1 result
        _write_jsonl(self.logs / "Agent A" / "session1.jsonl",
                     [_EVENT_PROMPT, _EVENT_TOOL_QUERY, _EVENT_TOOL_STORE, _EVENT_RESULT])
        # Agent B: 1 prompt + 1 tool call (query) — same tool as A
        _write_jsonl(self.logs / "Agent B" / "session1.jsonl",
                     [_EVENT_PROMPT, _EVENT_TOOL_QUERY])

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_aggregate_returns_logstats(self) -> None:
        stats = aggregate_logs(self.logs)
        self.assertIsInstance(stats, LogStats)
        self.assertEqual(set(stats.per_agent.keys()), {"Agent A", "Agent B"})

    def test_per_agent_event_count(self) -> None:
        stats = aggregate_logs(self.logs)
        self.assertEqual(stats.per_agent["Agent A"].total_events, 4)
        self.assertEqual(stats.per_agent["Agent B"].total_events, 2)

    def test_per_agent_prompt_count(self) -> None:
        stats = aggregate_logs(self.logs)
        self.assertEqual(stats.per_agent["Agent A"].prompt_count, 1)
        self.assertEqual(stats.per_agent["Agent B"].prompt_count, 1)

    def test_per_agent_tool_call_count(self) -> None:
        stats = aggregate_logs(self.logs)
        self.assertEqual(stats.per_agent["Agent A"].tool_call_count, 2)
        self.assertEqual(stats.per_agent["Agent B"].tool_call_count, 1)

    def test_per_agent_top_tools(self) -> None:
        stats = aggregate_logs(self.logs)
        a_top = dict(stats.per_agent["Agent A"].top_tools)
        self.assertEqual(a_top["query_knowledge"], 1)
        self.assertEqual(a_top["store_knowledge"], 1)

    def test_cross_agent_top_tools(self) -> None:
        stats = aggregate_logs(self.logs)
        top = dict(stats.top_tools_across_agents)
        # query_knowledge: A=1 + B=1 = 2; store_knowledge: 1
        self.assertEqual(top["query_knowledge"], 2)
        self.assertEqual(top["store_knowledge"], 1)

    def test_event_type_breakdown(self) -> None:
        stats = aggregate_logs(self.logs)
        types = dict(stats.event_type_counts)
        self.assertEqual(types["prompt"], 2)
        self.assertEqual(types["tool_call"], 3)
        self.assertEqual(types["tool_result"], 1)

    def test_total_agents_and_events(self) -> None:
        stats = aggregate_logs(self.logs)
        self.assertEqual(stats.total_agents, 2)
        self.assertEqual(stats.total_events, 6)

    def test_per_agent_span(self) -> None:
        stats = aggregate_logs(self.logs)
        a = stats.per_agent["Agent A"]
        # span between first prompt (18:00:00) and result (18:00:12) = 12s
        self.assertAlmostEqual(a.span_seconds, 12.0, places=1)

    def test_aggregate_handles_missing_dir_gracefully(self) -> None:
        stats = aggregate_logs(self.tmp / "nonexistent")
        self.assertEqual(stats.total_agents, 0)
        self.assertEqual(stats.total_events, 0)


if __name__ == "__main__":
    unittest.main()
