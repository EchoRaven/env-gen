"""#967: the idle verdict is structural, not a pattern match on the model's prose.

`#639` shipped a working backoff and `#637` shipped the streak it reads, and the pair
never fired once in production. Two independent reasons:

  1. `note_finish_637` was handed `tool_args.get("reason") or tool_args.get("summary")`,
     but the `finish` tool's schema is `message` / `notify` / `notify_content` /
     `outputs`. Every call received "" and took the else branch, resetting the streak.
  2. Even with the right field, the regex missed two of the three phrasings actually
     observed: r156 "Cold-start M1 kickoff **remains** in flight" (regex wants "still in
     flight") and r155 "no new **actionable event** was supplied" (regex wants
     work/tasks). Matching free-form model text is a treadmill.

The verdict now reads the per-step tool ledger: a step whose only action tool was
`finish` did nothing, whatever it called that. Deliberately conservative — read-only
pollers are not counted (see the docstring).
"""

import re

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.hub_pulse import (
    _IDLE_STREAK_RE_637, note_finish_637)


class _Agent:
    """Minimal host: the streak counter plus the per-step action-tool ledger."""

    def __init__(self, acted=0):
        self._idle_streak_637 = 0
        self._step_action_tools_637 = acted


def test_a_finish_only_step_counts_as_idle():
    agent = _Agent(acted=0)
    for expected in (1, 2, 3):
        note_finish_637(agent, "anything at all")
        assert agent._idle_streak_637 == expected


def test_a_step_that_did_work_resets_the_streak():
    agent = _Agent(acted=0)
    note_finish_637(agent, "")
    note_finish_637(agent, "")
    assert agent._idle_streak_637 == 2
    agent._step_action_tools_637 = 1          # a real tool ran this step
    note_finish_637(agent, "")
    assert agent._idle_streak_637 == 0, (
        "a productive step must clear the streak, or the backoff would eventually pace a "
        "lane that is actually working")


@pytest.mark.parametrize("prose", [
    "Cold-start M1 kickoff remains in flight with no actionable event supplied.",
    "ACTION_STATUS: stop — no new actionable event was supplied after the cold-start check.",
])
def test_the_verdict_survives_prose_the_old_regex_missed(prose):
    """Both strings are verbatim from netflix r155/r156 and both defeat the regex."""
    assert not _IDLE_STREAK_RE_637.search(prose), (
        "this string was chosen BECAUSE the old regex misses it; if the regex now matches, "
        "the parametrisation no longer demonstrates the treadmill")
    agent = _Agent(acted=0)
    note_finish_637(agent, prose)
    assert agent._idle_streak_637 == 1, (
        "the structural verdict must not depend on how the model phrased its summary")


def test_prose_still_decides_when_no_ledger_exists():
    """Fallback for callers that predate the ledger — absence of the attribute, not zero."""
    class _NoLedger:
        def __init__(self):
            self._idle_streak_637 = 0

    agent = _NoLedger()
    note_finish_637(agent, "nothing to do")
    assert agent._idle_streak_637 == 1
    note_finish_637(agent, "wrote the backend skeleton")
    assert agent._idle_streak_637 == 0


def test_the_call_site_passes_a_field_finish_actually_has():
    """The original defect was a field-name mismatch, invisible to every unit test because
    both sides were internally consistent. Pin the two together."""
    import inspect

    from env_generator.llm_generator.multi_agent.agents.runtime import tooling
    from env_generator.llm_generator.tools import agent_interaction_tools

    src = inspect.getsource(tooling)
    call = re.search(r"note_finish_637\(self,\s*(.+?)\)\n", src, re.S)
    assert call, "the #637 call site moved; this test can no longer verify it"
    passed = call.group(1)
    assert "tool_args.get(\"reason\")" not in passed, (
        "`reason` is not a parameter of the finish tool — this is the original defect")

    finish_src = inspect.getsource(agent_interaction_tools)
    for field in re.findall(r'tool_args\.get\("(\w+)"\)', passed):
        assert f'"{field}"' in finish_src, (
            f"the call site reads finish arg '{field}', which the tool schema never defines")


def test_the_control_is_defeated_by_prose():
    """Planted control: the PRE-FIX shape (regex over the model's summary) must fail on the
    observed text. Synthetic, so fixing the real code cannot turn this red."""
    def _pre_fix(agent, reason):
        if _IDLE_STREAK_RE_637.search(str(reason or "")):
            agent._idle_streak_637 += 1
        else:
            agent._idle_streak_637 = 0

    agent = _Agent()
    for _ in range(6):
        _pre_fix(agent, "Cold-start M1 kickoff remains in flight with no actionable event.")
    assert agent._idle_streak_637 == 0, (
        "the control was supposed to never accumulate a streak on this text; if it does, "
        "the prose test was adequate and #967 is unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
