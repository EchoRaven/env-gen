r"""#1202zc: the un-allowlisted tool menu is rebuilt from the prompt on every round.

`rank_tool_names` is handed `query_text=prompt_text`, so WHICH ten of the ~154 candidates an
agent is offered changes with whatever the round happens to be about. The provider's prompt
cache is keyed on the tool list FIRST — #1202po measured that on this very gateway: same
messages + same tools with `tool_choice="none"` cached 5,632 of 6,411 prompt tokens, the same
messages with the tools REMOVED cached 0. So a rotated menu throws away the whole prefix
behind it, system prompt and conversation history included.

★ EVERY profile in agents_config.yaml carries a `stage_tool_allowlist` EXCEPT the
orchestrator — backend, frontend, verifier, debugger, design_analyst and the three test users
all have one, and an allowlisted stage takes the FIX #29 path that offers the WHOLE curated
set, i.e. a constant blob. The orchestrator is the one long-running agent left on the
query-ranked path, and it is 22% of calls and 46% of uncached tokens.

★ THE FIX NEVER OFFERS LESS THAN TODAY, which is why it is safe to land without a live run.
The first draft stated that as "it adds, it never removes" and #1202mx's test falsified it
within the hour: some tools are withdrawn ON PURPOSE and on a schedule — while a kickoff
meeting is open, the validation tools leave both the force-offer and the candidate pool for
every lane. So the union is INTERSECTED with what each call still permits, and the true
invariant is the weaker one: no call is offered less than today's ranker would have offered
it, and nothing remembered is handed back once a gate has taken it away. That direction also answers the crowd-out FIX #29 describes — measured over
the 50 corpus runs carrying stage-tool counts, the orchestrator INVOKES 13 (action), 17
(retrieve_context), 23 (communicate), 25 (run_checks) and 25 (deliver) distinct tools while
being offered ten at a time.

★ AND IT SHIPS WITH THE INSTRUMENT THAT WOULD FALSIFY IT. `stage_tools_1202cy` counts tools
INVOKED; nothing counted tools OFFERED, so "the menu rotates" has been an inference. The new
`stage_tool_sets_1202zc` reports calls / distinct_sets / union_size per label, so the next run
says whether distinct_sets really collapses toward 1 — and whether the cap binds.
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import utils.llm as LL  # noqa: E402
from multi_agent.agents.runtime.step_pipeline import tooling as T  # noqa: E402


class _Agent:
    agent_id = "orchestrator"


def _sticky(agent, ranked, always=(), phase="implementation", stage="action",
            permitted=None):
    """`permitted` defaults to NO GATE WITHDRAWING ANYTHING -- everything on offer plus
    everything already remembered. In production it is `candidate_names | always_include`,
    the whole ~154-tool surface, so "the ranker's ten" would be a far narrower default than
    reality and would make the cap and stage tests fail for a reason the code does not have.
    The gate tests below pass a narrower surface on purpose."""
    if permitted is None:
        perm = set(ranked) | set(always)
        perm |= set().union(*(getattr(agent, "_sticky_tools_1202zc", {}) or {}).values()) \
            if getattr(agent, "_sticky_tools_1202zc", None) else set()
    else:
        perm = set(permitted)
    return T._sticky_stage_tools_1202zc(
        agent, phase, stage, set(ranked), set(always), perm)


# ── the union ─────────────────────────────────────────────────────────────────────

def test_the_first_menu_is_passed_through():
    a = _Agent()
    assert _sticky(a, {"read", "write"}) == {"read", "write"}


def test_a_second_menu_is_unioned_not_replaced():
    a = _Agent()
    _sticky(a, {"read", "write"})
    assert _sticky(a, {"grep", "lint"}) == {"read", "write", "grep", "lint"}


def test_no_permitted_tool_is_ever_withdrawn():
    """★ The property that makes this safe to land unverified — stated correctly. The first
    version of this test was called `test_no_tool_is_ever_withdrawn`, and that claim was
    FALSE: some tools are withdrawn on purpose and on a schedule (see the gate tests below).
    What holds is the weaker, true form: a call is offered at least what today's ranker
    would have offered it, plus everything remembered that this call STILL PERMITS."""
    a = _Agent()
    seen = set()
    for menu in ({"a", "b"}, {"b", "c"}, {"d"}, {"a"}, {"e", "f"}):
        got = _sticky(a, menu, permitted={"a", "b", "c", "d", "e", "f"})
        assert menu <= got, (menu, got)
        assert seen <= got, "a previously offered tool disappeared while still permitted"
        seen = got


def test_a_tool_the_gate_has_withdrawn_is_not_handed_back():
    """★ #1202mx, which is what caught the first draft: while a kickoff meeting is open the
    validation tools are removed from BOTH the force-offer and the candidate pool, for every
    lane. Measured there: the verifier had called `run_validation` 300 times inside open
    kickoff windows across 63 runs, each one a teardown and rebuild of the shared stack. A
    union that remembers the tool from before the meeting must not resurrect it."""
    a = _Agent()
    _sticky(a, {"read", "run_validation"})
    during = _sticky(a, {"read"}, permitted={"read"})
    assert "run_validation" not in during, during
    assert "read" in during


def test_the_tool_returns_when_the_gate_lifts_without_being_re_ranked():
    """The union is stored WITHOUT the intersection, so the moment the meeting closes the
    tool is on the menu again rather than having to win a top-10 slot first."""
    a = _Agent()
    _sticky(a, {"read", "run_validation"})
    _sticky(a, {"read"}, permitted={"read"})
    after = _sticky(a, {"read"}, permitted={"read", "run_validation"})
    assert "run_validation" in after, after


def test_the_ranker_s_own_pick_is_never_intersected_away():
    """`ranked` is drawn from the permitted surface by construction; if a caller ever passes
    a `permitted` that does not contain it, the ranker's answer still wins — dropping it
    would offer LESS than today."""
    a = _Agent()
    _sticky(a, {"x"})
    got = _sticky(a, {"fresh"}, permitted=set())
    assert "fresh" in got, got


def test_a_repeated_menu_changes_nothing():
    """Convergence is the point: once the ranker stops finding anything new, the blob stops
    changing and the prefix behind it becomes cacheable."""
    a = _Agent()
    first = _sticky(a, {"read", "write"})
    for _ in range(5):
        assert _sticky(a, {"read", "write"}) == first


def test_stages_do_not_share_a_menu():
    a = _Agent()
    _sticky(a, {"read"}, stage="action")
    assert _sticky(a, {"lint"}, stage="run_checks") == {"lint"}
    assert _sticky(a, set(), stage="action") == {"read"}


def test_phases_do_not_share_a_menu():
    a = _Agent()
    _sticky(a, {"read"}, phase="kickoff")
    assert _sticky(a, {"lint"}, phase="implementation") == {"lint"}


# ── the cap ───────────────────────────────────────────────────────────────────────

def test_the_cap_bounds_the_MEMORY_not_the_ranker():
    """★ The cap and the safety property pull against each other, and the safety property
    wins. A tool the ranker picks RIGHT NOW is what today's code would offer, so withholding
    it would offer LESS than today — the one thing this change must never do. What the cap
    stops is REMEMBERING it: the blob cannot keep growing call after call.

    The first version of this test asserted the opposite (`"new_one" not in frozen`) and was
    simply wrong about which of the two rules gives way."""
    a = _Agent()
    cap = T._STICKY_STAGE_TOOL_CAP_1202ZC
    base = {"t%03d" % i for i in range(cap)}
    _sticky(a, base)
    offered = _sticky(a, {"new_one"})
    assert "new_one" in offered, "the ranker's own pick was withheld"
    assert base <= offered
    # ...and it was not remembered: a later call that does not rank it does not carry it.
    later = _sticky(a, {"t000"})
    assert "new_one" not in later, later
    assert len(later) == cap


def test_a_force_offered_tool_is_remembered_even_past_the_cap():
    """★ run bsb900gpt: the deliver-gate tools missing from a sub-stage menu meant
    `get_skill` was dispatched 0 times and the run was killed. Past the cap the union stops
    taking new entries, so a tool that becomes force-offered LATE — the deliver gate opens
    once the run is validation-ready — has to be admitted anyway, or it is offered on the one
    call that ranked it and then vanishes."""
    a = _Agent()
    cap = T._STICKY_STAGE_TOOL_CAP_1202ZC
    _sticky(a, {"t%03d" % i for i in range(cap)})
    _sticky(a, {"get_skill", "junk"}, always={"get_skill"})
    later = _sticky(a, {"t000"})
    assert "get_skill" in later, "a force-offered tool was forgotten at the cap"
    assert "junk" not in later, "the cap stopped applying to ordinary ranked tools"


def test_the_cap_sits_above_measured_usage():
    """★ The bound was derived from ONE agent and governs them all, which is how it came to
    be too weak. The first version asserted `> 25` on "the orchestrator's busiest stages" —
    but this constant is read for every agent, and re-measured across all 59 (agent:stage)
    combinations in the 50 runs carrying `stage_tools_1202cy` the busiest are

        verifier:run_checks 29    frontend:communicate 29    frontend:deliver 26
        backend:deliver 26        verifier:deliver 25        orchestrator:deliver 25

    so a cap of 26 would have passed the old assertion while freezing `verifier:run_checks`
    below the 29 tools it demonstrably invokes. None of the 59 exceeds 32.

    ★ AND THAT IS STILL A LOWER BOUND, so the margin is smaller than it looks. The cap
    bounds the union of OFFERED menus; `stage_tools_1202cy` records what was INVOKED, and
    offered ⊇ invoked. A long stage's union can pass 32 without any single tool being called,
    which is exactly why the fallback below the cap exists and why no offline artifact can
    retire it — see `test_a_force_offered_tool_is_remembered_even_past_the_cap`."""
    assert T._STICKY_STAGE_TOOL_CAP_1202ZC > 29, (
        "verifier:run_checks and frontend:communicate each invoke 29 distinct tools")
    assert T._STICKY_STAGE_TOOL_CAP_1202ZC <= 48, "FIX #29's bound for a curated set"


# ── the escape hatches ────────────────────────────────────────────────────────────

def test_the_switch_restores_todays_behaviour(monkeypatch):
    """This changes what every orchestrator call sees and no live run has exercised it."""
    monkeypatch.setenv("ENVGEN_STICKY_STAGE_TOOLS", "0")
    a = _Agent()
    assert _sticky(a, {"read"}) == {"read"}
    assert _sticky(a, {"lint"}) == {"lint"}, "the union was still applied"


def test_an_agent_that_cannot_hold_state_is_unchanged():
    class _Frozen:
        __slots__ = ()
        agent_id = "x"
    assert _sticky(_Frozen(), {"read"}) == {"read"}
    assert _sticky(_Frozen(), {"lint"}) == {"lint"}


# ── the wiring ────────────────────────────────────────────────────────────────────

def _fn_tree():
    return ast.parse(inspect.getsource(
        T.AgentStepToolingMixin._stage_tool_names).lstrip())


def test_the_union_is_applied_only_where_the_menu_can_rotate():
    """★ An allowlisted stage already offers a CONSTANT set (FIX #29 offers the whole
    allowlist), so applying this there would be pure cost. The call must sit under
    `if not stage_allow`."""
    tree = _fn_tree()
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_sticky_stage_tools_1202zc"]
    assert len(calls) == 1, "called %d times" % len(calls)
    # ...and it is handed the CURRENT permitted surface, not a stale or wider one. Fed
    # anything that outlives the gates, the union resurrects a withdrawn tool (#1202mx).
    _args = ast.dump(calls[0])
    assert "candidate_names" in _args, _args[:240]
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(c is calls[0] for c in ast.walk(node)):
            t = node.test
            if (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not)
                    and getattr(t.operand, "id", "") == "stage_allow"):
                guarded = True
    assert guarded, "the call is not guarded by `if not stage_allow`"


def test_the_instrument_records_what_was_actually_offered():
    """★ Fed `ranked` instead of `selected`, the ledger would measure the menu before the
    union and report a rotation that no longer happens — the instrument would then confirm
    the problem it was built to disprove."""
    tree = _fn_tree()
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "record_stage_tool_set_1202zc"]
    assert len(calls) == 1
    assert any(getattr(a, "id", "") == "selected" for a in calls[0].args), \
        ast.dump(calls[0])[:200]
    returns = [n for n in ast.walk(tree) if isinstance(n, ast.Return)]
    assert any(getattr(r.value, "id", "") == "selected" for r in returns), \
        "the function no longer returns the set it recorded"


# ── the instrument ────────────────────────────────────────────────────────────────

def _reset():
    LL._STAGE_TOOL_SETS_1202ZC.clear()


def test_the_same_menu_twice_is_one_distinct_set():
    _reset()
    LL.record_stage_tool_set_1202zc("orchestrator:action", ["read", "write"])
    LL.record_stage_tool_set_1202zc("orchestrator:action", ["read", "write"])
    d = LL.stage_tool_sets_1202zc()["orchestrator:action"]
    assert d["calls"] == 2 and d["distinct_sets"] == 1, d


def test_order_is_not_a_change():
    """The tool blob is a set; a reordering of the same tools is the same prefix."""
    _reset()
    LL.record_stage_tool_set_1202zc("l", ["a", "b"])
    LL.record_stage_tool_set_1202zc("l", ["b", "a"])
    assert LL.stage_tool_sets_1202zc()["l"]["distinct_sets"] == 1


def test_a_rotation_is_counted():
    _reset()
    for menu in (["a", "b"], ["b", "c"], ["c", "d"]):
        LL.record_stage_tool_set_1202zc("l", menu)
    d = LL.stage_tool_sets_1202zc()["l"]
    assert d["calls"] == 3 and d["distinct_sets"] == 3, d
    assert d["union_size"] == 4, d


def test_the_fingerprint_store_says_when_it_stops_counting():
    """#1202z7/#1202z8, one file over: a count that silently stops counting reads as a
    measurement."""
    _reset()
    cap = LL._STAGE_TOOL_SET_CAP_1202ZC
    for i in range(cap + 5):
        LL.record_stage_tool_set_1202zc("l", ["tool%d" % i])
    d = LL.stage_tool_sets_1202zc()["l"]
    assert d["calls"] == cap + 5
    assert d["distinct_sets"] == cap
    assert d["capped"] is True, d


def test_a_label_that_never_rotated_is_visible_as_such():
    _reset()
    for _ in range(9):
        LL.record_stage_tool_set_1202zc("backend:action", ["a", "b", "c"])
    d = LL.stage_tool_sets_1202zc()["backend:action"]
    assert d["distinct_sets"] == 1 and d["calls"] == 9 and d["union_size"] == 3


def test_a_bad_record_does_not_raise():
    _reset()
    LL.record_stage_tool_set_1202zc(None, None)
    LL.record_stage_tool_set_1202zc("l", 5)
    assert isinstance(LL.stage_tool_sets_1202zc(), dict)


def test_the_run_budget_writes_it(monkeypatch, tmp_path):
    """#947: a measurement that exists only in memory is not a measurement."""
    import json
    import logging
    import multi_agent.runtime.run_budget as RB
    _reset()
    LL.record_stage_tool_set_1202zc("orchestrator:action", ["a", "b"])
    LL.record_stage_tool_set_1202zc("orchestrator:action", ["b", "c"])
    monkeypatch.setattr(LL, "llm_usage", lambda: {"calls": 1, "usd": 0.0}, raising=False)
    b = RB.RunBudget(tmp_path, logging.getLogger("t1202zc"))
    b.write({"max_wall_sec": 1.0, "max_ticks": 1}, 1.0, 1.0, 1, "running")
    d = json.loads((tmp_path / "run_budget.json").read_text(encoding="utf-8"))
    assert "stage_tool_sets_1202zc" in d, sorted(d)
    assert d["stage_tool_sets_1202zc"]["orchestrator:action"]["distinct_sets"] == 2
