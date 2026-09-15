"""#1202mx: validation and delivery tools are withheld while ANY milestone's kickoff is open.

PROPOSAL #28 F2 defers `_KICKOFF_DEFER_TOOLS` (the validation flow + delivery) "during kickoff",
keyed for non-orchestrator lanes on `kickoff_finalized_signal` — "any endpoint or any task
exists", true from the end of M1 for the rest of the run. And it only drops the force-offer, so
the tools stay rankable.

Across the run logs, inside open kickoff windows, the verifier called `run_validation` 300 times
in 63 runs (181 in M2+ kickoffs), each a `down -v` / build / up of the shared stack, plus ~650
verification-chain registrations. tiktok-r125's M2 kickoff: the verifier's corrective turn for
its predicates section spent its ten steps registering chains and running `run_validation`, and a
second corrective loop followed; the meeting waited on the verifier for minutes.

The signal is the NEWEST kickoff meeting being open: a run killed mid-kickoff leaves an older
meeting open forever, and counting that would withhold the verifier's tools for good.
"""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.agents.runtime import preconditions as PC  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.kickoff import run_kickoff as RK  # noqa: E402
from test_kickoff_run_kickoff import ATTENDEES, _all_clean_decisions  # noqa: E402


def _hubs(tmp):
    root = Path(tmp)
    (root / "shared").mkdir()
    return HubRegistry(root)


def _open(hubs, ms=1):
    h = RK.start_kickoff(hubs=hubs, milestone_index=ms, requirements=[f"M{ms}"],
                         attendees=ATTENDEES)
    for d in _all_clean_decisions():
        hubs.workhub.add_meeting_decision(h["meeting_id"], decision=d,
                                          agent=d.get("agent") or d["section"], milestone_index=ms)
    return h


def _close(hubs, h):
    s = RK.try_synthesize(hubs, h)
    RK.finalize_kickoff(hubs=hubs, kickoff_handle=h, synthesis=s)


def test_open_while_a_kickoff_is_in_progress_and_not_after():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        assert PC.latest_kickoff_open_1202mx(hubs) is False
        h1 = _open(hubs)
        assert PC.latest_kickoff_open_1202mx(hubs) is True
        _close(hubs, h1)
        assert PC.latest_kickoff_open_1202mx(hubs) is False


def test_a_second_milestones_kickoff_counts_even_though_contract_surface_exists():
    """The case `kickoff_finalized_signal` cannot see: M1's surface is there, M2 is open."""
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _close(hubs, _open(hubs, 1))
        assert PC.kickoff_finalized_signal(hubs) is True
        _open(hubs, 2)
        assert PC.latest_kickoff_open_1202mx(hubs) is True


def test_an_abandoned_older_meeting_does_not_hold_the_tools_forever():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _open(hubs, 1)                   # killed mid-kickoff: never closed
        _close(hubs, _open(hubs, 1))     # the resume's meeting, finalized
        assert PC.latest_kickoff_open_1202mx(hubs) is False


def test_no_workhub_means_no_withholding():
    assert PC.latest_kickoff_open_1202mx(SimpleNamespace()) is False
    assert PC.latest_kickoff_open_1202mx(None) is False


# ── the tool surface ───────────────────────────────────────────────────────────────────────

def _stub_lane(hubs, agent_id="verifier"):
    import multi_agent.agents.base as B
    from multi_agent.agents.runtime.step_pipeline.tooling import AgentStepToolingMixin
    real = B.EnvGenAgent

    class _Lane(AgentStepToolingMixin):
        ACTION_STAGE_ALWAYS_INCLUDE = real.ACTION_STAGE_ALWAYS_INCLUDE
        _KICKOFF_DEFER_TOOLS = real._KICKOFF_DEFER_TOOLS
        ACTION_INTERNAL_STAGES = getattr(real, "ACTION_INTERNAL_STAGES", ())
        ACTION_STAGE_CATEGORY_HINTS = getattr(real, "ACTION_STAGE_CATEGORY_HINTS", {})
        TEAM_TOOL_NAMES = ()
        TEAM_MODE_SUPPORT_TOOLS = ()
        _active_phase = None
        _is_final_milestone = True

    lane = _Lane()
    lane.agent_id = agent_id
    lane._hubs = hubs
    lane._kickoff_bootstrapped = True      # M1's contract exists: the old signal is True
    # Real tool objects as far as the ranker cares: it only ranks names it has instances for.
    lane._tool_instances = {n: SimpleNamespace(DESCRIPTION=f"{n} run validation api smoke chains",
                                               _tool_surface_categories=set())
                            for n in NAMES}
    return lane


NAMES = {"run_validation", "registryhub_register_verification_chain", "read",
         "workhub_add_meeting_decision", "finish"}


def _offered(lane):
    # The prompt names the validation tools, so the ranker WOULD pick them from the
    # candidate pool — the test must see the pool, not only the force-offer.
    schema = {n: {"name": n, "description": f"{n} run validation api smoke chains",
                  "parameters": {}} for n in NAMES}
    return lane._stage_tool_names(
        schema, "run_checks", set(NAMES),
        "call run_validation and registryhub_register_verification_chain now", limit=10)


def test_a_verifier_in_an_m2_kickoff_is_not_offered_validation_tools():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _close(hubs, _open(hubs, 1))
        lane = _stub_lane(hubs)
        before = _offered(lane)
        assert {"run_validation", "registryhub_register_verification_chain"} <= before
        _open(hubs, 2)
        during = _offered(lane)
        assert "run_validation" not in during
        assert "registryhub_register_verification_chain" not in during
        assert "workhub_add_meeting_decision" in during     # the kickoff's own tool stays


def test_the_tools_come_back_when_the_kickoff_closes():
    with tempfile.TemporaryDirectory() as tmp:
        hubs = _hubs(tmp)
        _close(hubs, _open(hubs, 1))
        h2 = _open(hubs, 2)
        lane = _stub_lane(hubs)
        assert "run_validation" not in _offered(lane)
        _close(hubs, h2)
        assert "run_validation" in _offered(lane)
