"""#1202no: a kickoff section loop ends once its meeting is closed, and writes no stub into it.

tiktok-r125 M4 (resume on #1202nl): the meeting stall-finalized from the registry at 11:11:32,
the meeting doc closed at ~11:14, and the frontend's section loop kept stepping — 7/12 at 11:15:08,
8/12 at 11:15:54 — while #1202nl held the lane's resident wakeup behind it. Across the run logs,
189 kickoff-budget steps ran after their meeting finalized, in 42 logs.

The section guarantee that runs after the loop also wrote an auto-backup stub into the closed
meeting; #1202mv carries a closed meeting's sections into a resume, so a stub written after the
close would be carried as if it were settled.
"""
from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.runtime import preconditions as PC  # noqa: E402
from multi_agent.agents.runtime.messaging import AgentMessaging  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.kickoff import run_kickoff as RK  # noqa: E402
from test_kickoff_run_kickoff import ATTENDEES  # noqa: E402

STEP_RUNNER = LLM / "multi_agent" / "agents" / "runtime" / "step_runner.py"


def _hubs(tmp):
    (Path(tmp) / "shared").mkdir()
    return HubRegistry(Path(tmp))


def _meeting(hubs):
    return RK.start_kickoff(hubs=hubs, milestone_index=4, requirements=["M4"],
                            attendees=ATTENDEES, broadcast=False)["meeting_id"]


def test_the_helper_follows_the_meeting_status():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        mid = _meeting(hubs)
        assert PC.kickoff_meeting_closed_1202no(hubs, mid) is False
        hubs.workhub.close_meeting(mid, produced_artifacts=["contract"], agent="orchestrator")
        assert PC.kickoff_meeting_closed_1202no(hubs, mid) is True
        assert PC.kickoff_meeting_closed_1202no(hubs, "doc_nope") is False
        assert PC.kickoff_meeting_closed_1202no(hubs, None) is False
        assert PC.kickoff_meeting_closed_1202no(SimpleNamespace(), mid) is False


def _section_decisions(hubs, mid, agent):
    doc = hubs.workhub.stores.documents.value()[mid]
    return [d for d in (doc.get("metadata") or {}).get("decisions") or []
            if (d.get("recorded_by") or d.get("agent")) == agent]


class _Log:
    def warning(self, *a, **k):
        pass

    error = info = debug = warning


def _guarantee(hubs, mid):
    lane = SimpleNamespace(_hubs=hubs, agent_id="frontend", _logger=_Log())
    AgentMessaging._ensure_initial_section_decision(
        lane, meeting_id=mid, milestone_index=4, expected_section="frontend")


def test_r125_no_stub_is_written_into_a_closed_meeting():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        mid = _meeting(hubs)
        hubs.workhub.close_meeting(mid, produced_artifacts=["contract"], agent="orchestrator")
        _guarantee(hubs, mid)
        assert _section_decisions(hubs, mid, "frontend") == []


def test_an_open_meeting_still_gets_its_stub():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        mid = _meeting(hubs)
        _guarantee(hubs, mid)
        assert len(_section_decisions(hubs, mid, "frontend")) == 1


def test_the_step_loop_checks_before_it_takes_a_step():
    """The guard must sit in the step loop ahead of the step's LLM work, keyed on the
    authoring marker so no other loop is affected."""
    src = STEP_RUNNER.read_text(encoding="utf-8")
    loop = src.index("for step in range(max_steps):")
    guard = src.index('_mtg_1202no = getattr(self, "_kickoff_authoring_1202ms", None)', loop)
    call = src.index("kickoff_meeting_closed_1202no(", guard)
    ret = src.index('"kickoff_meeting_closed_1202no": True', call)
    step_log = src.index('Step {step + 1}/{max_steps}', loop)
    assert loop < guard < call < ret < step_log
