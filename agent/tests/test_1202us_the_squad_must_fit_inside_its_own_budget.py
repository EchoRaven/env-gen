r"""#1202us: the squad's per-agent timeout killed 92% of its agents, and could not just be raised.

`run_test_user_squad` carried two bare defaults with no rationale: `max_concurrent = 4` and
`per_agent_timeout = 180.0`.

MEASURED over 1,296 test-user agents in the run logs, spawn to `run_loop completed`:

    median 318s    p25 195s    p75 609s    p90 907s    max 3875s
    finished within the 180s timeout:  8%

So eleven of every twelve agents were terminated mid-work and their spend discarded, and the
squad's own report recorded 0-6 completions out of 12 in EVERY run in the corpus. That is the
evidence gap #1202ur had to route around -- and the two tickets are the same defect seen from
each end: one made the verdict honest about having no evidence, this one lets the evidence
exist.

THE TIMEOUT COULD NOT SIMPLY BE RAISED, which is the part worth keeping. `squad_release_decision`
preempts to RELEASE 900s after the first defer and is evaluated ABOVE the whole squad block, so
with 12 goals in waves of 4 -- three waves -- any larger timeout makes the squad outlive its own
budget and the milestone ships with NO verdict at all. Strictly worse than a thin one.

MEASURED over 83 squad runs: total wall clock median 616s, per wave median 187s -- only ~7s of
overhead above the timeout itself. Two waves therefore afford ~353s each inside the 900s escape.
12 goals in waves of SIX is two waves, and 300s leaves margin:

    2 x (300 + 7) + ~180s tail  =  ~794s  <  900s escape
    agents finishing within 300s:  48%   (up from 8%)

Six is half the headroom, not all of it: `dynamic_team_rules.yaml` sets
`max_active_per_parent: 8`, `E_PARENT_ACTIVE_CAP_REACHED` appears in ZERO run logs, and a spawn
refusal is caught per goal rather than failing the squad.

THE ASSERTIONS BELOW PIN THE RELATIONSHIP, NOT THE NUMBERS. Tuning either default is fine; what
must not happen again is a squad whose waves cannot finish inside the window that preempts it,
or a concurrency above the parent cap.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import inspect
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.test_user_squad import (  # noqa: E402
    run_test_user_squad,
    squad_release_decision,
)

_SIG = inspect.signature(run_test_user_squad)
CONCURRENCY = int(_SIG.parameters["max_concurrent"].default)
TIMEOUT = float(_SIG.parameters["per_agent_timeout"].default)

# The squad plans one goal per page/modality; 12 is what every run in the corpus produced.
GOALS = 12
# Measured: per-wave cost above the timeout itself, and the tail from the last wave to the
# verdict line.
WAVE_OVERHEAD_S = 7
TAIL_S = 180


def _escape_wall_s() -> float:
    return float(inspect.signature(squad_release_decision).parameters["wall_s"].default)


def test_the_waves_finish_inside_the_window_that_preempts_them():
    """★ THE INVARIANT. `squad_release_decision`'s wall-clock is evaluated ABOVE the squad
    block, so a squad that cannot finish inside it ships the milestone with no verdict."""
    waves = math.ceil(GOALS / CONCURRENCY)
    projected = waves * (TIMEOUT + WAVE_OVERHEAD_S) + TAIL_S
    assert projected < _escape_wall_s(), (
        f"{waves} waves x {TIMEOUT}s = {projected}s, escape is {_escape_wall_s()}s")


def test_the_old_settings_would_fail_that_invariant_if_the_timeout_alone_were_raised():
    """★ The reasoning, asserted rather than asserted-in-prose: raising the timeout WITHOUT
    cutting a wave breaks the budget. This is why the ticket touches both."""
    waves_at_4 = math.ceil(GOALS / 4)
    assert waves_at_4 * (TIMEOUT + WAVE_OVERHEAD_S) + TAIL_S > _escape_wall_s()


def test_the_timeout_covers_more_than_the_old_eighth_of_agents():
    """Measured durations: p25 195s, median 318s. A timeout at or below the old 180s puts the
    gate back where it was -- finishing 8% of what it spawns."""
    assert TIMEOUT >= 195, TIMEOUT      # p25 of 1,296 measured agents


def test_concurrency_stays_within_the_declared_parent_cap():
    """★ The risk this change introduces. The cap lives in the governance rules, so read it
    rather than repeating the number."""
    rules = (LLM_DIR / "multi_agent" / "docs" / "dynamic_team_rules.yaml").read_text()
    cap = None
    for line in rules.splitlines():
        if "max_active_per_parent" in line:
            cap = int(line.split(":")[1].strip())
            break
    assert cap, "max_active_per_parent is no longer declared in the governance rules"
    assert CONCURRENCY <= cap, (CONCURRENCY, cap)


def test_a_spawn_refusal_costs_one_goal_not_the_squad():
    """★ The failure mode of raising concurrency, asserted at the source: hitting the cap must
    degrade per goal, which is what makes 6 an acceptable risk rather than a gamble."""
    src = inspect.getsource(run_test_user_squad)
    assert 'rec["error"] = f"spawn failed:' in src, src[:400]


def test_the_defaults_are_what_the_callers_get():
    """#1202up's lesson about reachability: no caller overrides these, so the defaults ARE the
    behaviour. If one starts passing its own, this assertion should be what notices."""
    import subprocess

    out = subprocess.run(
        ["grep", "-rn", "run_test_user_squad(", "--include=*.py", str(LLM_DIR)],
        capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "def run_test_user_squad" in line:
            continue
        assert "max_concurrent" not in line and "per_agent_timeout" not in line, line
