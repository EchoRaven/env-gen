"""#1161: "not retrying" bounded one call, not the run.

#1159 made the classification right — netflix-local-r16 logged "TERMINAL
provider error — not retrying, run should abort" 939 times where r15 logged it
0 — but that only stops ONE call's retries. Every agent step opens a NEW call,
so r16 kept issuing them: 12 minutes and 2136 x 429 in design-prep/kickoff
without stopping.

The orchestrator DOES poll terminal_llm_error() and abort (#326), but only
inside `while not _project_delivered_event.is_set()` — the main delivery loop,
which starts AFTER kickoff. Design-prep and kickoff run before it and had no
check at all, which is exactly where a run spends its first ~15 minutes.

Measured A/B on three real runs against an exhausted account:

  r15  no #1159            2h50m, 322 x 429, terminal classified 0 times
  r16  #1159               12+ min (killed by hand), 2136 x 429, classified 1092
  r17  #1159 + #1161       272s, SELF-EXITED, 200 x 429, 24 lane stops
"""
import re
from pathlib import Path

from env_generator.llm_generator.multi_agent.agents.runtime import step_runner

SRC = Path(step_runner.__file__).read_text(encoding="utf-8")


def _guard():
    """Anchor on the ticket, stop at the condensation comment it precedes (#943)."""
    i = SRC.index("# #1161: STOP STEPPING WHEN THE PROVIDER IS TERMINALLY DEAD.")
    return SRC[i:SRC.index("# Condense at EVERY step boundary", i)]


def test_the_check_is_inside_the_per_step_loop():
    """One check here covers design-prep, kickoff and the main loop, because this
    is where every agent in every phase takes a step."""
    loop = SRC.index("for step in range(max_steps):")
    assert loop < SRC.index("# #1161: STOP STEPPING")


def test_it_runs_before_the_step_does_any_work():
    """Checking after the LLM call would still spend the call."""
    g = _guard()
    assert "terminal_llm_error" in g
    body = SRC[SRC.index("for step in range(max_steps):"):]
    assert body.index("#1161") < body.index("Condense at EVERY step boundary")


def test_it_returns_rather_than_raises():
    """Same shape as the _shutdown_requested guard above it: a lane that stops
    cleanly still lets the orchestrator write its run record."""
    g = _guard()
    assert "return {" in g
    # a `raise` STATEMENT, not the word — the comment above says "do not raise"
    assert not [l for l in g.splitlines() if l.strip().startswith("raise ")]


def test_it_carries_files_created_like_the_sibling_guard():
    g = _guard()
    assert "files_created" in g


def test_the_import_failure_cannot_wedge_a_lane():
    g = _guard()
    assert "except Exception" in g and "_t1161 = None" in g


def test_the_message_names_the_real_fix():
    """Raising ENVGEN_MAX_* is the wrong lever and a reader will try it."""
    g = _guard()
    assert "budget increase" in g or "fresh key" in g
    assert "ENVGEN_MAX_" in g


def test_the_shutdown_guard_is_still_first():
    """#1161 must not displace the shutdown path."""
    body = SRC[SRC.index("for step in range(max_steps):"):]
    assert body.index("_shutdown_requested") < body.index("#1161")
