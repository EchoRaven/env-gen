r"""#637: the twelfth no-op step looked exactly like the first.

Sweeping the 565 agent trajectories (`.agent_logs/*/*.jsonl`, which record each call WITH its
arguments — I had wrongly noted this needed a future run):

    9602 finish() calls;  3810 (40%) report idleness
    3614 of those 3810 (95%) are the ORCHESTRATOR
    median 63 idle steps per run, max 295

Each is a full model call. Using `metadata.tokens` (usage.total_tokens) on the response events:

    IDLE steps     n=3614   952.1M tokens   median 121,793
    WORKING steps  n=3982  1805.8M tokens   median 164,355
    -> idle work is 35% of the orchestrator's entire token spend

The agent has no idea it is repeating itself — this is #617's finding in a second place, where
every remediation round announced itself as "attempt 1".

Only the COUNTER is added. The obvious next move is to stop calling the model during a long idle
streak, and the data says where that is safe:

    after k consecutive idles   P(next step does real work)   tokens in those idles
        k=1                              53%                        168M
        k=2                              40%                         90M
        k=6+                              8%                        199M

but that is a scheduling change in the coordination loop; it can only POSTPONE work, never drop
it, and its cost is not measurable from any artifact on disk. Recording the streak makes it
decidable on the next run rather than guessed at now — the #621 move. A line of prompt cannot
delay anything.
"""
import pytest

from env_generator.llm_generator.multi_agent.agents.runtime.hub_pulse import (
    _idle_streak_lines_637 as lines,
    build_hub_pulse_prompt,
    note_finish_637 as note,
)


class _Agent:
    pass


# --- counting --------------------------------------------------------------------------------

@pytest.mark.parametrize("reason", [
    "Idle.", "Cold start idle.", "Awaiting kickoff", "nothing to do",
    "Idle; kickoff still in flight.", "No new work",
])
def test_the_measured_idle_phrasings_all_count(reason):
    """Every one of these is a real `finish()` reason from the corpus."""
    a = _Agent()
    note(a, reason)
    assert a._idle_streak_637 == 1


def test_consecutive_idles_accumulate():
    a = _Agent()
    for _ in range(4):
        note(a, "Idle.")
    assert a._idle_streak_637 == 4


def test_real_work_resets_it():
    a = _Agent()
    note(a, "Idle.")
    note(a, "Idle.")
    note(a, "Dispatched 3 failing checks to the frontend lane")
    assert a._idle_streak_637 == 0


def test_it_never_raises_on_an_odd_agent_or_reason():
    note(object(), "Idle.")          # attribute assignment may fail — must not propagate
    a = _Agent()
    note(a, None)
    assert a._idle_streak_637 == 0


# --- what the agent is shown --------------------------------------------------------------------

def test_a_short_streak_says_nothing():
    """One or two quiet steps are normal; the prompt must not nag."""
    assert lines({"idle_streak": 0}) == []
    assert lines({"idle_streak": 2}) == []


def test_from_three_it_states_the_count():
    out = lines({"idle_streak": 3})
    assert out and "3 consecutive steps with no action" in out[0]


def test_from_six_it_asks_for_something_different():
    """k>=6 is where P(work) collapses to 8% — the point at which repeating is least useful."""
    out = lines({"idle_streak": 7})
    assert "Nothing has changed" in out[0]
    assert "who owns it" in out[0]


def test_a_missing_or_bogus_value_is_ignored():
    assert lines({}) == []
    assert lines({"idle_streak": "many"}) == []


def test_it_renders_on_an_OTHERWISE_EMPTY_pulse():
    """The whole point: an idle step has an empty pulse, which is exactly when it must show."""
    out = build_hub_pulse_prompt({"idle_streak": 8})
    assert out and "8 consecutive steps" in out


def test_it_leads_the_prompt():
    out = build_hub_pulse_prompt({"idle_streak": 8, "phase": {"phase": "VALIDATION"}})
    assert out.index("consecutive steps") < out.index("VALIDATION")


def test_a_working_agent_sees_no_change():
    assert build_hub_pulse_prompt({"idle_streak": 0}) in (None, "")


# --- wiring ----------------------------------------------------------------------------------

def test_the_counter_is_fed_from_the_finish_tool():
    import inspect
    from env_generator.llm_generator.multi_agent.agents.runtime import tooling
    src = inspect.getsource(tooling)
    i = src.index('if tool_name == "finish":')
    assert "note_finish_637" in src[i:src.index("self.log_tool_call", i)]


def test_the_pulse_carries_it():
    import inspect
    from env_generator.llm_generator.multi_agent.agents.runtime import hub_pulse
    src = inspect.getsource(hub_pulse.collect_hub_pulse)
    assert 'report["idle_streak"] = _idle_streak' in src


def test_why_the_verdict_is_structural_is_recorded():
    """#967 supersedes this test's original form.

    It used to be ``test_why_it_is_only_a_counter_is_recorded`` and asserted the docstring
    still explained that a backoff "was measured and deliberately deferred". That deferral
    was LIFTED by #639, which shipped ``_idle_backoff_639`` — so from that day the assertion
    pinned a rationale the code had already abandoned, and stayed green only because nobody
    rewrote the prose. It is the trap this suite exists to avoid: a passing test guarding a
    stale claim.

    What a future reader now needs is the cost evidence (unchanged, still the justification)
    and why the verdict reads the tool ledger instead of the model's own summary.
    """
    import inspect
    from env_generator.llm_generator.multi_agent.agents.runtime import hub_pulse
    flat = " ".join(inspect.getsource(hub_pulse.note_finish_637).split())
    assert "952M of the orchestrator's 2.76B total tokens (35%)" in flat, (
        "the measured cost is the whole justification — it must survive rewrites")
    assert "structural" in flat.lower(), "the reader must learn what the verdict reads"
    assert "reason" in flat and "message" in flat, (
        "the field-name defect that made this dead code for months must stay recorded")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
