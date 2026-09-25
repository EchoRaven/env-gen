r"""#1202ur: the post-gate quality gate passed when the quality check never ran.

`squad_gate_outcome` read the P0 count and nothing else:

    verdict = "PASS" if bugs.get("p0", 0) == 0 else "DEFECTS"

so a squad where NO agent finished filed no P0 and therefore PASSED. `report["completed"]` is
computed, incremented per wave, and logged at every wave -- and never consulted. The per-goal
ledger three lines away DOES require it: `"passed": bool(completed and mod_p0 == 0)`.

MEASURED over 30 squad verdicts across 21 run logs:

    completion is 0-6 of 12 agents, median ~2, never above 6
    2 verdicts were PASS with ZERO agents completed (r120 and r135)

r135, live while this was written:

    15:06:53  spawning 12 agents
    15:09:58  wave 1: 0 completed / 4 spawned
    15:14:36  wave 2: 0 completed / 8 spawned
    15:18:23  wave 3: 0 completed / 12 spawned
    15:21:23  verdict=PASS: 0 open P0 (0 from test-users) / 0 P1  by-source={}

Fourteen and a half minutes, twelve agents, nothing finished, and the gate that exists to test
the built app let the milestone through. It is rare only because some OTHER source usually has
an open P0 (#630 widened `p0` beyond test-users); when the app is otherwise clean, this passes
having tested nothing. The user's standing rule is that a fallback which masks a failure should
not exist, and a PASS from no evidence is exactly that.

'retry' IS THE SAFE MAPPING, and that was checked rather than assumed: it defers WITHOUT
burning an escape attempt, and `squad_release_decision` (900s wall-clock from the first defer,
or 3 attempts) is evaluated ABOVE the whole squad block and preempts to RELEASE regardless. So
a squad that never completes costs one bounded deferral, not a deadlock -- which matters,
because on these numbers zero-completion is not exotic.

`completed=None` means UNKNOWN and keeps the previous behaviour: a restored or older result
carries no report, and #1202tn's rule is that a fault-tolerant helper's 0 cannot be used as a
fact. Only an EXPLICIT zero routes to 'retry'.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.test_user_squad import squad_gate_outcome  # noqa: E402


def test_zero_completed_agents_is_not_a_pass():
    """★ The defect, in r135's exact shape: 12 spawned, 0 finished, 0 P0."""
    assert squad_gate_outcome(ran=True, p0=0, completed=0) == "retry"


def test_one_completed_agent_with_no_defects_still_passes():
    """The bar is evidence, not a quota. #630's own numbers show completion never exceeds 6
    of 12, so anything stricter would block every run."""
    assert squad_gate_outcome(ran=True, p0=0, completed=1) == "pass"
    assert squad_gate_outcome(ran=True, p0=0, completed=6) == "pass"


def test_filed_defects_win_over_zero_completion():
    """★ P0s that WERE filed are real evidence. Routing them to 'retry' would stop burning the
    escape attempt that bounds the defect loop, which is the opposite of the intent."""
    assert squad_gate_outcome(ran=True, p0=1, completed=0) == "defect"
    assert squad_gate_outcome(ran=True, p0=19, completed=0) == "defect"


def test_unknown_completion_keeps_the_old_behaviour():
    """★ #1202tn's rule applied to this change itself: a missing report reads as UNKNOWN, not
    as zero. A restored result carries no `report`, and defaulting that to 0 would turn every
    resumed run's clean squad into an endless deferral."""
    assert squad_gate_outcome(ran=True, p0=0, completed=None) == "pass"
    assert squad_gate_outcome(ran=True, p0=0) == "pass"


def test_a_squad_that_could_not_run_is_unchanged():
    """#179's original case must still map to 'retry' whatever the completion count says."""
    assert squad_gate_outcome(ran=False, p0=0, completed=5) == "retry"
    assert squad_gate_outcome(ran=False, p0=3, completed=5) == "retry"


def test_the_orchestrator_passes_the_count_it_has():
    """★ #947/reachability: the rule is only real if the caller feeds it. The orchestrator
    reads `completed` off the squad's own report, and must use `.get` so a report-less result
    stays None rather than raising or reading as zero."""
    import inspect

    from multi_agent import orchestrator as orch

    src = inspect.getsource(orch)
    assert '_tu_completed = (_tu_result.get("report") or {}).get("completed")' in src
    assert "completed=_tu_completed" in src


def test_the_escape_backstop_still_bounds_it():
    """★ The risk this change introduces, asserted directly: zero-completion is common, so
    'retry' must not be able to wedge a release. The wall-clock/attempt escape is evaluated
    above the squad block and releases regardless."""
    from multi_agent.runtime.test_user_squad import squad_release_decision

    assert squad_release_decision(0.0, 0, 901.0) == "release"       # wall-clock
    assert squad_release_decision(None, 3, 1.0) == "release"        # attempt cap
    assert squad_release_decision(0.0, 0, 10.0) == "defer"          # neither yet
