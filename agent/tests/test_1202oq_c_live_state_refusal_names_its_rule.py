"""#1202oq-c: the lane is told WHICH rule refused a live-state path, through the real stager.

`_stage_refusal_1202ml` exists solely so a lane is not told "dotfile not in allowlist" about
`shared/hubs/...`, a path with no dot in it. No test asserted its shared/ wording: flipping
`if first in _LIVE_RUN_STATE_TOP_1202ml:` to `if False:` (every live-state refusal says "dotfile"
again) left 11/11 of #1202ml's tests and test_auto_stage_filter.py green.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.agents.runtime.auto_commit import stage_file  # noqa: E402


def test_a_live_hub_ledger_is_refused_for_the_right_reason(tmp_path):
    f = tmp_path / "shared" / "hubs" / "workhub_tasks.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    ok, msg = stage_file(tmp_path, f, agent_id="frontend")
    assert ok is False
    assert "LIVE hub" in msg and "shared/" in msg, msg
    assert "dotfile" not in msg, msg


def test_a_real_dotfile_still_gets_the_dotfile_reason(tmp_path):
    f = tmp_path / ".gates" / "user_gates.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    ok, msg = stage_file(tmp_path, f, agent_id="frontend")
    assert ok is False and "dotfile" in msg, msg
