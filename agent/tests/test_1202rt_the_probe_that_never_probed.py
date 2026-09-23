r"""#1202rt: the realism judge is dispatched, on a schedule, against a stack that answers.

`#1202rh` built the judge -- the `realism_judge` profile with edit/write/apply_patch denied, the
M1/M2 prompts, the realism contract in every lane's definition. It built no caller. A mechanism
nobody calls is this session's most-repeated defect class, and it was sitting in my own work.

Both halves of the first draft were silent no-ops of exactly the kind the judge exists to catch:

  * it called `_delivery_inputs(orch)`, which does not exist. The NameError landed in the
    function's own `except Exception`, which turns anything it catches into a `reason` string
    on an advisory report nobody reads. Every run would have reported "no app address resolved"
    while the stack sat there answering.
  * it then called `stack_lease_1202nx` bare. That name is local to `run_squad_for_delivery`,
    not module scope, so the same except would have swallowed the same class of error one line
    further in.

So these tests assert the SPAWN HAPPENED, not that the call returned. A probe is proven by the
request that reaches the spawn service; `ran: True` is what both broken drafts also produced on
the paths they did reach.

The deadline is the third half. This runs at the release point holding the stack lease, so a
judge that hangs would hold that lease against the release it was only meant to observe.
"""
import asyncio

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_squad as sq
from env_generator.llm_generator.multi_agent.runtime import compose_mutex as cm


_UI, _API = "http://localhost:8081", "http://localhost:3000"


class _Res:
    def __init__(self, ev):
        self.task_done_event = ev


class _Spawn:
    """Records what was asked for, and finishes immediately unless told to hang."""

    def __init__(self, hang=False):
        self.requests = []
        self.hang = hang

    async def spawn(self, req):
        self.requests.append(req)
        ev = asyncio.Event()
        if not self.hang:
            ev.set()
        return _Res(ev)


class _Orch:
    def __init__(self, hang=False, tmp="."):
        self.spawn_service = _Spawn(hang=hang)
        self._logger = None
        self.output_dir = str(tmp)


@pytest.fixture()
def serving(monkeypatch, tmp_path):
    """A stack that answers, a lease that is free, and no real waiting."""
    monkeypatch.setattr(sq, "gather_squad_inputs",
                        lambda orch: {"ui_base": _UI, "api_base": _API})
    monkeypatch.setattr(sq, "targets_reachable_625",
                        lambda ui, api, **kw: {"ui": True, "api": True})

    import contextlib

    @contextlib.contextmanager
    def _lease(path, holder):
        yield

    monkeypatch.setattr(cm, "stack_lease_1202nx", _lease)
    return tmp_path


# --- when it runs -------------------------------------------------------------------

def test_the_first_milestone_is_always_sampled():
    """v1.0.0's seed, copy and imagery are what every later milestone inherits."""
    assert sq.realism_probe_due_1202rt(0) is True


def test_it_samples_every_nth_and_skips_between():
    due = [i for i in range(10) if sq.realism_probe_due_1202rt(i, every_n=3)]
    assert due == [0, 3, 6, 9]


def test_an_operator_can_turn_it_off():
    assert sq.realism_probe_due_1202rt(0, enabled_env={"ENVGEN_REALISM_PROBE": "0"}) is False
    assert sq.realism_probe_due_1202rt(0, enabled_env={"ENVGEN_REALISM_PROBE": "1"}) is True


def test_unreadable_input_is_not_a_reason_to_run():
    for bad in (None, "x", object(), -1):
        assert sq.realism_probe_due_1202rt(bad) is False


# --- that it actually dispatches ----------------------------------------------------

def test_the_probe_reaches_the_spawn_service(serving):
    """The counter-proof for both no-ops: a request, not a return value."""
    orch = _Orch(tmp=serving)
    report = asyncio.run(sq.run_realism_probe_1202rt(orch, version="1.0.0"))
    assert report["ran"] is True, report
    assert len(orch.spawn_service.requests) == 1, "the judge was never dispatched"


def test_the_dispatched_judge_is_unprimed_and_is_the_judge_profile(serving):
    orch = _Orch(tmp=serving)
    asyncio.run(sq.run_realism_probe_1202rt(orch))
    req = orch.spawn_service.requests[0]
    assert req.agent_type == "realism_judge" and req.config_key == "realism_judge"
    assert req.metadata.get("regime") == "unprimed"
    assert req.metadata.get("ui_base") == _UI and req.metadata.get("api_base") == _API


def test_the_briefing_never_says_what_it_is_looking_for(serving):
    """M1 measures what surfaces WHILE WORKING. Priming over-detects by ~4x."""
    orch = _Orch(tmp=serving)
    asyncio.run(sq.run_realism_probe_1202rt(orch))
    task = (orch.spawn_service.requests[0].task or "").lower()
    assert task, "dispatched with no briefing at all"
    for primed in ("realism", "realistic", "fake", "synthetic", "placeholder", "authentic"):
        assert primed not in task, "the briefing primes the judge with %r" % primed


# --- and that it never blocks anything ----------------------------------------------

def test_a_hanging_judge_does_not_hold_the_release(serving, monkeypatch):
    monkeypatch.setattr(sq, "_REALISM_DEADLINE_1202RT", 0.01)
    orch = _Orch(hang=True, tmp=serving)
    report = asyncio.run(sq.run_realism_probe_1202rt(orch))
    assert report.get("timed_out") is True
    assert report["ran"] is True, "a deadline is not a failure to run"


def test_a_stack_that_does_not_answer_is_not_judged(serving, monkeypatch):
    """There is nothing to notice against a stack that does not serve."""
    monkeypatch.setattr(sq, "targets_reachable_625",
                        lambda ui, api, **kw: {"ui": True, "api": False})
    orch = _Orch(tmp=serving)
    report = asyncio.run(sq.run_realism_probe_1202rt(orch))
    assert report["ran"] is False
    assert "env_unavailable" in report["reason"]
    assert orch.spawn_service.requests == []


def test_no_address_means_no_probe_and_no_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(sq, "gather_squad_inputs", lambda orch: {})
    orch = _Orch(tmp=tmp_path)
    report = asyncio.run(sq.run_realism_probe_1202rt(orch))
    assert report["ran"] is False and orch.spawn_service.requests == []


def test_a_spawn_that_explodes_is_advisory_not_fatal(serving):
    """Advisory means advisory: nothing here may take a release down with it."""
    orch = _Orch(tmp=serving)

    async def _boom(req):
        raise RuntimeError("judge unavailable")

    orch.spawn_service.spawn = _boom
    report = asyncio.run(sq.run_realism_probe_1202rt(orch))
    assert report["ran"] is False and "judge unavailable" in report["reason"]


# --- the ratchet --------------------------------------------------------------------

def test_every_name_the_probe_calls_actually_resolves():
    """The defect in one line: both no-ops were names that do not exist at that scope.

    Compile-checking is not enough -- Python resolves globals at call time, and the function's
    own except turns every NameError into a quiet reason string. So resolve them here.
    """
    import ast
    import builtins
    import inspect

    import textwrap

    src = textwrap.dedent(inspect.getsource(sq.run_realism_probe_1202rt))
    tree = ast.parse(src)
    local = {a.arg for a in tree.body[0].args.args}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.For, ast.With)):
            for t in ast.walk(node):
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store):
                    local.add(t.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                local.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            local.add(node.name)

    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    unresolved = sorted(n for n in called - local
                        if not hasattr(sq, n) and not hasattr(builtins, n))
    assert not unresolved, "calls names that resolve nowhere: %s" % unresolved
    # and the ratchet must FAIL on the code it was written against, or it proves nothing
    assert "_delivery_inputs" not in called and "_delivery_inputs" not in dir(sq)
    assert not hasattr(sq, "_delivery_inputs") and not hasattr(builtins, "_delivery_inputs"), \
        "the name from the broken draft exists now, so this ratchet no longer sees it"


# --- the caller ---------------------------------------------------------------------

def _bound(**attrs):
    """The orchestrator method under test, bound to a stand-in with just what it reads."""
    import logging
    import types

    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator

    class _O:
        pass

    o = _O()
    o._logger = logging.getLogger("t1202rt")
    for k, v in attrs.items():
        setattr(o, k, v)
    o._maybe_realism_probe_1202rt = types.MethodType(
        Orchestrator._maybe_realism_probe_1202rt, o)
    return o


def _capture(monkeypatch):
    calls = []

    async def _run(orch, version=""):
        calls.append(version)
        return {"ran": True}

    monkeypatch.setattr(sq, "run_realism_probe_1202rt", _run)
    return calls


def test_the_release_point_actually_awaits_the_probe():
    """The defect class this fix exists to close: a mechanism with no caller.

    #1202rh built the judge and shipped zero dispatches. Grep the release path, not the module.
    """
    import inspect

    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator

    src = inspect.getsource(Orchestrator._maybe_framework_deliver)
    # anchored on the decision it must follow, not on a line number (#943)
    pass_branch = src.split("self._tu_squad_passed = True", 1)
    assert len(pass_branch) == 2, "the squad-pass release point moved; re-anchor this test"
    assert "await self._maybe_realism_probe_1202rt()" in pass_branch[1], \
        "the realism probe is no longer dispatched when the squad passes"


def test_the_first_milestone_is_probed(monkeypatch):
    calls = _capture(monkeypatch)
    o = _bound(_milestone_index_1202rt=1, _current_milestone_version="1.0.0")
    asyncio.run(o._maybe_realism_probe_1202rt())
    assert calls == ["1.0.0"]


def test_an_unsampled_milestone_is_not_probed(monkeypatch):
    calls = _capture(monkeypatch)
    o = _bound(_milestone_index_1202rt=2, _current_milestone_version="1.1.0")
    asyncio.run(o._maybe_realism_probe_1202rt())
    assert calls == []


def test_the_same_milestone_is_not_probed_twice(monkeypatch):
    """A deferred tick can reach the release point again; the second look costs a deadline."""
    calls = _capture(monkeypatch)
    o = _bound(_milestone_index_1202rt=1, _current_milestone_version="1.0.0")
    asyncio.run(o._maybe_realism_probe_1202rt())
    asyncio.run(o._maybe_realism_probe_1202rt())
    assert calls == ["1.0.0"]
    # ...but the NEXT sampled milestone is a different app, and is probed
    o._milestone_index_1202rt, o._current_milestone_version = 4, "1.3.0"
    asyncio.run(o._maybe_realism_probe_1202rt())
    assert calls == ["1.0.0", "1.3.0"]


def test_a_probe_that_explodes_does_not_reach_the_release(monkeypatch):
    async def _boom(orch, version=""):
        raise RuntimeError("judge exploded")

    monkeypatch.setattr(sq, "run_realism_probe_1202rt", _boom)
    o = _bound(_milestone_index_1202rt=1, _current_milestone_version="1.0.0")
    asyncio.run(o._maybe_realism_probe_1202rt())  # must not raise


# --- the prompt the judge actually receives -------------------------------------------

def _realism_task_macro():
    import jinja2

    root = (__import__("pathlib").Path(__file__).resolve().parents[1]
            / "env_generator" / "llm_generator" / "multi_agent" / "prompts")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(root)))
    module = env.get_template("v3/test_user_agent.j2").module
    return getattr(module, "realism_judge_task_prompt")


@pytest.mark.parametrize("task_data", [
    {"description": "x"},                      # what a STRING payload becomes
    {"description": "x", "regime": ""},
    {"description": "x", "regime": "unprimed"},
    {"description": "x", "regime": "something-else"},
])
def test_only_an_explicit_primed_regime_primes_the_judge(task_data):
    """The load-bearing default, and it is load-bearing by accident unless pinned here.

    `#1202rt` dispatches with `metadata={"regime": "unprimed"}`, but the macro branches on
    `task_data`, and task_data is the TASK PAYLOAD -- a string payload becomes
    `{"description": ...}` (agents/base.py), so that metadata never reaches the template.
    What actually keeps the measurement honest is that UNPRIMED IS THE DEFAULT: priming has
    to be asked for. If that ever inverts, every M1 number silently becomes an M2 number,
    and M2 over-detects by roughly 4x.
    """
    rendered = str(_realism_task_macro()(task_data=task_data)).lower()
    assert "p_real" not in rendered, "an unprimed dispatch was handed the primed prompt"


def test_the_primed_regime_is_still_reachable():
    """The M2 branch must exist, or the adversarial ceiling can never be measured."""
    rendered = str(_realism_task_macro()(task_data={"description": "x",
                                                    "regime": "primed"})).lower()
    assert "p_real" in rendered


def test_the_system_prompt_renders_at_all():
    """A profile whose prompt fails to render is a judge that runs with nothing to do --
    the same class of dead mechanism this whole ticket exists to close."""
    import jinja2

    root = (__import__("pathlib").Path(__file__).resolve().parents[1]
            / "env_generator" / "llm_generator" / "multi_agent" / "prompts")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(root)))
    macro = getattr(env.get_template("v3/test_user_agent.j2").module,
                    "realism_judge_system_prompt")
    out = str(macro(workspace_dir="/w", role="realism_judge"))
    assert len(out) > 2000, "the realism judge's system prompt rendered to nothing"
    assert "p_real" not in out.lower(), "the system prompt primes every regime"
