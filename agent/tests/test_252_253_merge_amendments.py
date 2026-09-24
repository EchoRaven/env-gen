"""#252/#253 — amendments to the other session's merged fixes (NR1/F1 and F2b).

Both amended fixes had the RIGHT intent and a default that was unsafe outside the one
model they were observed on:

  #252 (amends NR1 + F1): design_analyst default-OFF, and a 600s backstop, were derived
  from GPT-5.6 runs on a compat gateway whose tool-call translation is independently known
  broken. On the validated Gemini path the analyst converges in 3/3 observed runs at
  354s / 420s / 1419s — so 600s would have killed r51's analyst at 42% of its real work,
  and default-OFF removes the ONLY producer of per-component MEASURED design facts.
  Silent visual-fidelity downgrade with no error anywhere = exactly the class of default
  a model-specific observation must never set.

  #253 (amends F2b): the suppression's own comment scopes it to the orchestrator ("it can
  take no kickoff action then"), but the code had no agent restriction — so a WORKING LANE
  also stopped waking on 'answer' pre-finalize, which is the youtube#12 Defect-C shape the
  surrounding block exists to prevent.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.agents.runtime.messaging import (  # noqa: E402
    AgentMessaging,
)


# ---------------------------------------------------------------- #252 (NR1/F1)
class _RecLogger:
    def __init__(self):
        self.lines = []

    def _rec(self, msg, *a, **k):
        self.lines.append(str(msg))

    info = warning = debug = error = _rec


def _run_analyst(monkeyenv):
    """Call the real method with spawn_service=None; the DISABLED branch is
    distinguishable from the enabled branch by its log line (both return False)."""
    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch._logger = _RecLogger()
    orch.spawn_service = None
    old = {k: os.environ.get(k) for k in monkeyenv}
    os.environ.update({k: v for k, v in monkeyenv.items() if v is not None})
    for k, v in monkeyenv.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        asyncio.run(orch._spawn_design_analyst({}))
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return "\n".join(orch._logger.lines)


def test_252_design_analyst_is_ON_by_default():
    """The default must NOT disable the only per-component measurement producer."""
    out = _run_analyst({"ENVGEN_DESIGN_ANALYST": None})
    assert "disabled" not in out, out


def test_252_explicit_off_still_honoured():
    """The GPT-5.6 path keeps its knob — the fix stays available, just not as the default."""
    for val in ("0", "false", "no", "off", "OFF"):
        out = _run_analyst({"ENVGEN_DESIGN_ANALYST": val})
        assert "disabled" in out, (val, out)


def test_252_explicit_on_is_a_noop():
    out = _run_analyst({"ENVGEN_DESIGN_ANALYST": "1"})
    assert "disabled" not in out, out


def test_252_timeout_default_sits_above_observed_converging_max():
    """r51's analyst converged at 1419s. A backstop inside that window silently truncates
    real work, so the default must sit ABOVE the observed converging maximum."""
    src = (ROOT / "env_generator/llm_generator/multi_agent/orchestrator.py").read_text()
    line = [l for l in src.splitlines()
            if "ENVGEN_DESIGN_ANALYST_TIMEOUT" in l and "os.environ.get(" in l][0]
    default = float(line.split('"')[-2])
    assert default > 1419, f"backstop {default}s would truncate r51's converging analyst"


# ------------------------------------------------------------------- #253 (F2b)
class _FakeHubs:
    """Pre-finalize: no endpoints, no tasks — kickoff_finalized_signal() is False."""
    class _RH:
        def get_endpoints(self):
            return {}

    class _WH:
        def list_tasks(self):
            return []

    registryhub = _RH()
    workhub = _WH()


def _suppressed_by_f2b(agent_id, msg_type, finalized=False):
    """True iff the F2b guard swallowed the message (it logs a '(F2b)' line and returns).

    Probing the guard directly — rather than the far end of the wakeup path — keeps the
    test about the one behaviour #253 changes and immune to unrelated policy plumbing.
    """
    m = AgentMessaging.__new__(AgentMessaging)
    m.agent_id = agent_id
    m._logger = _RecLogger()
    m._is_resident_lane = True
    m._hubs = _FakeHubs()
    if finalized:
        m._hubs.registryhub.get_endpoints = lambda: {"GET /api/x": {}}

    class _Msg:  # not a TaskMessage
        pass

    try:
        asyncio.run(AgentMessaging._maybe_schedule_resident_message_wakeup(
            m, _Msg(), {"type": msg_type, "from": "backend"}))
    except Exception:
        pass  # downstream plumbing is irrelevant; the guard already ran or did not
    return any("(F2b)" in line for line in m._logger.lines)


def test_253_working_lane_still_wakes_on_answer_during_kickoff():
    """The youtube#12 Defect-C regression F2b introduced: a lane idle-waiting on an answer."""
    assert _suppressed_by_f2b("backend", "answer") is False
    assert _suppressed_by_f2b("frontend", "update") is False


def test_253_orchestrator_suppression_preserved():
    """F2b's actual win is kept: no idle coordinator wakes pre-finalize."""
    assert _suppressed_by_f2b("orchestrator", "answer") is True
    assert _suppressed_by_f2b("orchestrator", "update") is True


def test_253_orchestrator_wakes_again_once_kickoff_finalized():
    """Scoped to pre-finalize — post-kickoff handling must be unchanged."""
    assert _suppressed_by_f2b("orchestrator", "answer", finalized=True) is False


def test_253_actionable_types_never_suppressed_for_anyone():
    for aid in ("orchestrator", "backend"):
        for t in ("issue", "question", "task_ready", "blocker"):
            assert _suppressed_by_f2b(aid, t) is False, (aid, t)
