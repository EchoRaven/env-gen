"""L3b — consult telemetry: skill_consulted events surface in log aggregation.

Per docs/superpowers/plans/2026-06-03-skill-mandatory-trigger.md Task 5.
The L3a skill_consulted event (emitted at the tool chokepoint) flows into
aggregate_logs as a first-class consult_count plus the generic
event_type_counts.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class ConsultTelemetry(unittest.TestCase):
    def test_skill_consulted_counted(self):
        from multi_agent.runtime.observability.log_parser import aggregate_logs
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            agent_dir = logs_dir / "Backend"
            agent_dir.mkdir(parents=True, exist_ok=True)
            with (agent_dir / "run.jsonl").open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"event_type": "skill_consulted", "agent": "backend", "skill": "api-contract-guard"}) + "\n")
                fh.write(json.dumps({"event_type": "skill_consulted", "agent": "backend", "skill": "release-readiness"}) + "\n")
                fh.write(json.dumps({"event_type": "tool_call", "content": "read"}) + "\n")
            stats = aggregate_logs(logs_dir)
            backend = stats.per_agent["Backend"]
            self.assertEqual(backend.consult_count, 2)
            self.assertEqual(dict(backend.event_type_counts).get("skill_consulted"), 2)
            self.assertEqual(backend.tool_call_count, 1)


if __name__ == "__main__":
    unittest.main()
