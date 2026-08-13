r"""#678: the framework-owned denial was already well written — the agent just kept trying.

Last entry in the wasted-STEPS ranking (#674-#677). Unlike the others, this message needs no
rewording: it already names the cause and the authoring surface.

    "Write denied: ['app/backend/main.py'] are FRAMEWORK-OWNED files. The framework generates +
     overwrites them deterministically from the registered contract ... Author your business
     logic in custom_routes.py (backend) or src/pages/*.jsx + App.jsx (frontend)"

Measured over the 249 run logs:

    1546 framework-owned denials across 133 runs
    61 (run, file) pairs hit the SAME file 5+ times
    worst case 52 attempts on one Dockerfile in a single run

So the fix is not new wording, it is noticing the repeat — and saying plainly that the answer
cannot change.

#664's lesson applies with one difference worth stating. There the counter had to accumulate
across calls to reach its threshold, so instance churn reset it to zero permanently and the
escalation fired 4 times in 4928; persisting it was the whole fix. Here two attempts on one
surviving instance is enough, and if a lane IS respawned the worst case is the base message —
which is exactly today's behaviour. Instance state is sufficient; no store is needed.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.agents.runtime import tooling


def _block():
    """The denial branch, bounded by the construct that follows it."""
    src = inspect.getsource(tooling)
    i = src.index("#678: THE MESSAGE IS GOOD")
    return src[i:src.index("LANE-OWNED application code", i)]


# --- the escalation exists and is second-strike ---------------------------------------------

def test_the_first_denial_carries_no_escalation():
    body = _block()
    assert '_escalate_678 = "" if _repeat_n < 2 else (' in body


def test_the_counter_is_per_path():
    body = _block()
    assert '_fw_seen[str(_p)] = _fw_seen.get(str(_p), 0) + 1' in body


def test_it_reports_how_many_times():
    body = _block()
    assert "{_repeat_n} times" in body


def _escalation_text():
    """The escalation's assembled literal — source lines split mid-sentence."""
    import re
    body = _block()
    i = body.index("_escalate_678 = ")
    lit = body[i:body.index("\n                )", i)]
    return "".join(re.findall(r'"([^"]*)"', lit))


def test_it_says_the_answer_cannot_change():
    """The behaviour the 52-attempt run needed corrected."""
    assert "The answer will not change" in _escalation_text()


def test_it_rules_out_the_three_things_an_agent_would_try_next():
    assert "no retry, rewording or different tool will make it writable" in _escalation_text()


def test_it_still_points_at_the_way_forward():
    txt = _escalation_text()
    assert "authoring surface named above" in txt
    assert "register the contract" in txt


# --- the original message is intact ---------------------------------------------------------

def test_the_base_message_is_unchanged():
    src = inspect.getsource(tooling)
    assert "are FRAMEWORK-OWNED files. The framework " in src
    assert "custom_routes.py (backend) or src/pages/*.jsx + App.jsx (frontend)" in src


def test_the_escalation_is_appended_not_substituted():
    src = inspect.getsource(tooling)
    assert "+ _tw_hint + _escalate_678" in src


def test_the_tailwind_hint_still_precedes_it():
    """#36's tailwind.theme.js guidance must not be pushed out by the new clause."""
    src = inspect.getsource(tooling)
    i = src.index("+ _tw_hint + _escalate_678")
    assert "tailwind.theme.js" in src[:i]


# --- the state is lazily created and cannot crash the denial ----------------------------------

def test_the_store_is_created_on_first_use():
    body = _block()
    assert 'getattr(self, "_fw_denied_678", None)' in body
    assert "self._fw_denied_678 = _fw_seen" in body


def test_it_keys_on_the_path_string():
    """Path objects and strings for the same file must not count separately."""
    body = _block()
    assert "str(_p)" in body


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    flat = " ".join(_block().replace("#", " ").split())
    assert "1546 framework-owned denials across 133 runs" in flat
    assert "52 attempts on one Dockerfile" in flat


def test_why_instance_state_suffices_here_is_recorded():
    """#664 needed a store; this does not, and the difference must be written down."""
    flat = " ".join(_block().replace("#", " ").split())
    assert "664's lesson applies with one difference" in flat
    assert "instance state is sufficient" in flat.lower()


def test_the_degraded_case_is_named():
    flat = " ".join(_block().split())
    assert "worst case is the base message" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
