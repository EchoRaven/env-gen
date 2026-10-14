r"""#1203jd: FIX #155's pre-cut guard was on one of the two release paths.

`_maybe_framework_deliver` runs `ensure_fresh_smoke_before_cut` before its cut — "if the
committed backend differs from what the last passing api_smoke validated, run ONE fresh
smoke on the exact release tree and HOLD the cut on failure" — because gmrun3's broken
custom_routes middleware landed 2min before a cut and shipped unvalidated, and the
delivered archive 500'd on every request. The post-loop FINAL cut, which ships the run's
HIGHEST tag, never called it.

★ THE WINDOW IS REAL. For each of the four most recent runs that took the final path, the
last CLEAN RunHub smoke before the cut, and what git says landed in between:

    r185  smoke 19:00:23  cut 19:05:46  backend→integration 19:04:33, frontend 19:03:02
    r184  smoke 11:09:58  cut 11:11:12  fix(frontend) nav fidelity 11:11:02
    r177  smoke 01:21:36  cut 01:27:16  SIX lane merges, incl. "complete signup flow to
                                        authenticated feed" 01:26:01
    r173  smoke 09:54:54  cut 09:55:52  frontend→integration 09:55:44

Four of four ship lane code no api_smoke ever saw.

★ The asymmetry that matters for the FIX: the per-milestone site may return False and wait,
because its loop retries next tick. Here the run is ENDING, so False is permanent — "the
app was never tested" (a host fault) must not be treated like "the app was tested and
failed". The guard now NAMES which, structurally, instead of leaving this caller to parse
its prose; `test_every_false_exit_names_a_kind` is why that stays true.
"""
import ast
import asyncio
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.orchestrator as ORCH               # noqa: E402
import multi_agent.runtime.framework_validation as FV  # noqa: E402

_FV_SRC = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent",
                       "runtime", "framework_validation.py")


class _Log:
    def __init__(self):
        self.lines = []

    def _add(self, fmt, *a):
        try:
            self.lines.append(str(fmt) % a if a else str(fmt))
        except Exception:
            self.lines.append(str(fmt))

    warning = error = info = debug = _add


def _orch(kind="", reason="because"):
    o = types.SimpleNamespace(_logger=_Log())
    o._fresh_smoke_hold_kind_1203jd = kind
    o._fresh_smoke_hold_reason_1202wc = reason
    return o


def _ask(monkeypatch, orch, guard):
    monkeypatch.setattr(FV, "ensure_fresh_smoke_before_cut", guard, raising=False)
    holds = []
    monkeypatch.setattr(ORCH, "_note_delivery_hold_1202tk",
                        lambda o, hold, detail="": holds.append((hold, detail)),
                        raising=False)
    ok = asyncio.run(ORCH.Orchestrator._final_fresh_smoke_ok_1203jd(orch, "1.3.0"))
    return ok, holds


def test_a_clean_tree_cuts(monkeypatch):
    """The common case, and the one that must stay free: the guard returns immediately
    when the tree signature already matches a passing smoke."""
    async def _g(_o):
        return True
    ok, holds = _ask(monkeypatch, _orch(), _g)
    assert ok is True and holds == []


def test_an_app_fault_holds_the_final_cut(monkeypatch):
    """★ THE TICKET. The exact tree this tag would ship has been tested and failed —
    `decision == "hold"` is only reachable after the smoke actually ran, so this is never
    a guess about an untested tree."""
    async def _g(_o):
        return False
    ok, holds = _ask(monkeypatch, _orch(kind="app", reason="2 failing check(s): x"), _g)
    assert ok is False, "a tree that failed a fresh smoke is still being released"
    assert holds and holds[0][0] == "fresh_smoke_final_1203jd", holds
    assert "failing check" in holds[0][1], holds


def test_a_host_fault_does_not_cost_the_release(monkeypatch):
    """★ WITHOUT THIS THE FIX IS WORSE THAN THE DEFECT: a full disk or a busy port means
    the app was never asked, and this cut has no next tick to retry on, so holding would
    be permanent. #1203d5 parks it on a timer precisely because the host clears without
    any source change (r149: an operator reclaimed 90GB)."""
    async def _g(_o):
        return False
    ok, holds = _ask(monkeypatch, _orch(kind="host", reason="HOST FAULT (ENOSPC)"), _g)
    assert ok is True, "a host fault permanently cost the final release"
    assert holds == [], "a host fault was recorded as a delivery hold about the app"


def test_a_framework_fault_cuts(monkeypatch):
    """The guard's own rule — "any internal fault returns True, infra must never block
    delivery" — has to hold for a fault in the CALL too, or this method becomes a new way
    to lose a release the objective gate declared clear."""
    async def _g(_o):
        raise RuntimeError("boom")
    ok, holds = _ask(monkeypatch, _orch(kind="app"), _g)
    assert ok is True and holds == []


def test_an_unknown_kind_is_treated_as_the_apps(monkeypatch):
    """Fail CLOSED on the classification: if a future exit forgets to name itself, the
    safe reading is "the app was tested and failed", because the alternative ships a tag
    whose tree failed. `test_every_false_exit_names_a_kind` keeps that case empty."""
    async def _g(_o):
        return False
    ok, _ = _ask(monkeypatch, _orch(kind=""), _g)
    assert ok is False


def _guard_node():
    with open(_FV_SRC, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "ensure_fresh_smoke_before_cut"):
            return n, src.splitlines()
    raise AssertionError("ensure_fresh_smoke_before_cut is gone")


def test_every_false_exit_names_a_kind():
    """★ THE RATCHET. This caller's decision is only as good as the guard's answer, and a
    False exit that names nothing reads as "the app's" above — correct but silent. Four
    exits carry it today; a fifth must too."""
    node, lines = _guard_node()
    missing = []
    for n in ast.walk(node):
        if (isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
                and n.value.value is False):
            if not any("_fresh_smoke_hold_kind_1203jd" in lines[n.lineno - 1 - k]
                       for k in range(1, 4)):
                missing.append(n.lineno)
    assert not missing, (
        "these `return False` exits do not say whether the hold is the host's or the "
        "app's: %s" % missing)


def test_the_kind_is_reset_on_entry():
    """WITHOUT THIS IT IS A STALE-STATE BUG: the attribute lives on the orchestrator for
    the whole run, so a "host" left by an earlier tick would let a later app fault cut,
    and an "app" would hold on a host fault. The reset must precede every exit."""
    node, lines = _guard_node()
    resets = [n.lineno for n in ast.walk(node)
              if isinstance(n, ast.Assign)
              and getattr(n.targets[0], "attr", "") == "_fresh_smoke_hold_kind_1203jd"
              and isinstance(n.value, ast.Constant) and n.value.value == ""]
    assert resets, "nothing resets the hold kind on entry"
    exits = [n.lineno for n in ast.walk(node) if isinstance(n, ast.Return)]
    assert min(resets) < min(exits), (
        "the reset at %s does not precede the first exit at %s" % (resets, min(exits)))


def test_the_final_cut_is_gated_on_this_method():
    """The method is useless if `run` does not consult it. Located by the call, not by a
    line number (#943)."""
    p = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent",
                     "orchestrator.py")
    with open(p, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    runs = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "run"]
    assert runs, "`run` is gone"
    called = [n for r in runs for n in ast.walk(r)
              if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "_final_fresh_smoke_ok_1203jd"]
    assert called, "the post-loop final cut no longer consults the fresh-smoke guard"
    # …and the create_release below it must be inside a branch that tests the result
    gates = [n for r in runs for n in ast.walk(r)
             if isinstance(n, ast.If)
             and "_cut_ok_1203jd" in ast.dump(n.test)
             and any(isinstance(c, ast.Call)
                     and getattr(c.func, "attr", "") == "create_release"
                     for c in ast.walk(n))]
    assert gates, "create_release at the final site is not gated on the guard's verdict"
