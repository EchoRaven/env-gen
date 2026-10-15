"""#1203kl: the regression pass was applied after the cut, so the cut could defeat it.

`order_replay_first` exists to re-test previously-FAILED flows first (design §3.5). It was
applied to the plan the cap had ALREADY produced, so it could only reorder the survivors. When
the cap dropped a previously-failed goal, the regression pass was defeated silently — the flow
that failed last cycle was not in the plan at all.

Measured over the modern era: 29 goals dropped across 10 of 35 runs, 24 of them never spawned
in their run. 5 of those, in r183 / r173 / r171 — every one a run with THREE OR MORE cycles,
which is exactly where a regression pass is supposed to matter — were marked open failures in
that run's OWN ledger while being cut from its plan: `page_profile_own_page`,
`page_messages_dm_empty_page`, `page_settings_more_menu[_page]`.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_squad import (  # noqa: E402
    plan_test_user_goals as PLAN, goal_ledger_key_1203kl as KEY, FailureLedger)

_EPS = [{"method": "GET", "path": "/api/a", "status": "implemented"},
        {"method": "POST", "path": "/api/a", "status": "implemented"}]
_PAGES = [{"name": "p%d" % i, "route": "/p%d" % i} for i in range(20)]


def _plan(**kw):
    return PLAN(business_eps=_EPS, ui_pages=_PAGES, **kw)


def _dropped(cap):
    kept = {KEY(g) for g in _plan(max_goals=cap)}
    return [g for g in _plan(max_goals=99) if KEY(g) not in kept]


def test_a_dropped_goal_survives_the_cap_when_it_is_an_open_failure_1203kl():
    victim = _dropped(6)[0]
    assert victim is not None
    plan = _plan(max_goals=6, replay_first=[KEY(victim)])
    assert KEY(victim) in {KEY(g) for g in plan}, (
        "this is the defect: a goal the ledger marks failed was cut from the plan, so the "
        "regression pass could never reach it", [g["name"] for g in plan])


def test_it_does_not_raise_the_cap_1203kl():
    """The cap is the cost bound and is untouched — this decides WHICH goals it keeps."""
    victim = _dropped(6)[0]
    assert len(_plan(max_goals=6, replay_first=[KEY(victim)])) == len(_plan(max_goals=6))


def test_an_empty_replay_set_is_byte_identical_1203kl():
    base = [g["name"] for g in _plan(max_goals=6)]
    for empty in ([], None, set(), ()):
        assert [g["name"] for g in _plan(max_goals=6, replay_first=empty)] == base, empty


def test_an_unknown_key_changes_nothing_1203kl():
    base = [g["name"] for g in _plan(max_goals=6)]
    got = [g["name"] for g in _plan(max_goals=6, replay_first=["browser::not_a_goal"])]
    assert got == base, got


def test_the_partition_is_stable_1203kl():
    """Relative order inside each half is preserved, so the plan stays predictable and
    `_cap_by_kind_1203go`'s own per-kind fairness still composes on top (#1203go)."""
    full = _plan(max_goals=99)
    keys = [KEY(g) for g in full]
    picked = {keys[5], keys[9]}
    out = [KEY(g) for g in _plan(max_goals=99, replay_first=picked)]
    assert out[:2] == [keys[5], keys[9]], out[:3]
    assert out[2:] == [k for k in keys if k not in picked], "the tail must keep its order"


def test_every_kind_still_gets_a_slot_1203kl():
    """#1203go's fairness must survive: replaying a page goal cannot starve api/ui kinds."""
    victim = _dropped(6)[0]
    plan = _plan(max_goals=6, replay_first=[KEY(victim)])
    kinds = {g.get("kind") for g in plan}
    assert len(kinds) >= 2, kinds


def test_the_key_has_one_owner_1203kl():
    """The planner cannot import the ledger class, so the format would have been duplicated
    (#1032). `FailureLedger._key` delegates to the same function."""
    g = {"modality": "browser", "name": "page_x"}
    assert KEY(g) == "browser::page_x"
    assert FailureLedger._key(g) == KEY(g)
    for junk in (None, 7, "x", {}):
        assert isinstance(KEY(junk), str)


def test_the_planner_is_called_with_the_ledger_before_the_cap_1203kl():
    """The wiring, by AST: the ledger must be built BEFORE `plan_test_user_goals` and its open
    failures passed in — after the plan, `replay_first` could not affect which goals survive.
    """
    import ast
    src = (LLM / "multi_agent" / "runtime" / "test_user_squad.py").read_text("utf-8")
    tree = ast.parse(src)
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
              and f.name == "_run_squad_for_delivery_impl")
    body = ast.unparse(fn)
    i_ledger = body.index("FailureLedger(")
    i_plan = body.index("plan_test_user_goals(")
    assert i_ledger < i_plan, "the ledger must be read before the plan is capped"
    # The plan call itself, from the AST — NOT a byte window around the index. #943's ratchet
    # caught the first version of this line (`body[i_plan:i_plan + 300]`) and was right to:
    # a window sized in bytes breaks when a comment above it grows.
    _plan_calls = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Call)
                   and ast.unparse(n.func) == "plan_test_user_goals"]
    assert any("replay_first=_replay1203kl" in c for c in _plan_calls), _plan_calls
    # Found by mutation: the name surviving while the VALUE goes empty passed every check
    # above. The set has to come from the ledger, not from a literal.
    assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "_replay1203kl" for t in n.targets)]
    assert len(assigns) == 1, [ast.unparse(a) for a in assigns]
    value = ast.unparse(assigns[0].value)
    assert value == "ledger.open_failures()", (
        "#1203kl's set must be the ledger's open failures — a literal would silently disable "
        "the whole patch: " + value)
    assert body.count("FailureLedger(") == 1, (
        "one ledger object, or the set that shaped the plan is not the one that records the "
        "cycle")
