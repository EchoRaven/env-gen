"""#1202nx: a validation or lane teardown waits while the framework is using the running stack.

tiktok-r126 (resume ab2): the 12-agent test-user squad tested the app 15:32-15:44 while validations
ran `down -v` at 15:31:56, 15:34:21, 15:36:50, 15:38:25 and 15:40:24 (all validation_runner, all on
the run's own compose project). The squad filed "Backend API unreachable" / "API base unreachable"
P0s and delivery deferred on them. The squad, the browser walk and the visual capture now hold a
stack lease; the validation fresh boot/teardown and the lane `docker_up(fresh)`/`docker_down` wait
for it, bounded so a lease can never wedge a run.
"""
import ast
import asyncio
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import compose_mutex as CM  # noqa: E402
from multi_agent.runtime import test_user_squad as SQ  # noqa: E402
from multi_agent.runtime import validation_runner as VR  # noqa: E402


def test_a_teardown_waits_until_the_holder_releases(tmp_path):
    released = {}

    def _hold():
        with CM.stack_lease_1202nx(tmp_path, "test-user squad"):
            time.sleep(0.6)
            released["at"] = time.time()

    t = threading.Thread(target=_hold)
    t.start()
    time.sleep(0.1)
    assert CM.active_stack_leases_1202nx(tmp_path) == ["test-user squad"]
    assert CM.wait_for_stack_leases_1202nx(tmp_path, "run_validation", timeout_s=10, poll_s=0.05)
    done = time.time()
    t.join()
    assert done >= released["at"]
    assert CM.active_stack_leases_1202nx(tmp_path) == []


def test_the_wait_is_bounded_and_other_stacks_are_not_blocked(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    with CM.stack_lease_1202nx(tmp_path, "visual capture"):
        t0 = time.time()
        assert CM.wait_for_stack_leases_1202nx(tmp_path, "docker_down", timeout_s=0.3,
                                               poll_s=0.05) is False
        assert time.time() - t0 < 2
        assert CM.wait_for_stack_leases_1202nx(other, "docker_down", timeout_s=0) is True
        # the same project spelled differently is the same stack
        assert CM.active_stack_leases_1202nx(str(tmp_path / "x" / "..")) == ["visual capture"]


def test_an_expired_lease_is_a_crashed_holder(tmp_path):
    with CM.stack_lease_1202nx(tmp_path, "browser test-user walk", ttl_s=1.0):
        time.sleep(1.1)
        assert CM.wait_for_stack_leases_1202nx(tmp_path, "run_validation", timeout_s=0) is True


def test_the_squad_holds_the_lease_while_it_tests(tmp_path, monkeypatch):
    seen = {}

    async def _impl(orch, version="", *, max_concurrent=4):
        seen["held"] = CM.active_stack_leases_1202nx(tmp_path)
        return {"ok": True}

    monkeypatch.setattr(SQ, "_run_squad_for_delivery_impl", _impl)
    out = asyncio.run(SQ.run_squad_for_delivery(SimpleNamespace(output_dir=str(tmp_path)), "1.0.0"))
    assert out == {"ok": True}
    assert seen["held"] == ["test-user squad"]
    assert CM.active_stack_leases_1202nx(tmp_path) == []


def test_r126_validation_does_not_down_the_stack_under_the_squad(tmp_path, monkeypatch):
    """Behavioural: the validation's `down -v` happens only after the squad's lease is gone."""
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n")
    events = []

    def _compose(compose_file, *args, cwd, timeout=300):
        if args[:1] == ("down",):
            events.append(("down", CM.active_stack_leases_1202nx(tmp_path), time.time()))
        raise RuntimeError("stop after the recycle")   # nothing past the teardown is under test

    monkeypatch.setattr(VR, "_compose", _compose)
    monkeypatch.setenv("ENVGEN_STACK_LEASE_WAIT_SEC", "20")
    released = {}

    def _squad():
        with CM.stack_lease_1202nx(tmp_path, "test-user squad"):
            time.sleep(1.0)
            released["at"] = time.time()

    t = threading.Thread(target=_squad)
    t.start()
    time.sleep(0.1)
    try:
        VR.run_smoke_validation(tmp_path, [], teardown=False)
    except Exception:
        pass
    t.join()
    downs = [e for e in events if e[0] == "down"]
    assert downs, "the validation never reached its fresh-boot recycle"
    assert downs[0][1] == [] and downs[0][2] >= released["at"]


def _calls_in_order(fn_node):
    names = []
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            names.append((node.lineno, name, ast.unparse(node)))
    return [n for n in sorted(names)]


def _method(path, cls, meth):
    tree = ast.parse(Path(path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.AsyncFunctionDef) and item.name == meth:
                    return item
    raise AssertionError(f"{cls}.{meth} not found")


def test_lane_teardowns_wait_before_they_down_the_stack():
    tools = LLM / "tools" / "docker_tools.py"
    for cls, marker in (("DockerUpTool", "'down', '-v'"), ("DockerDownTool", "subprocess.run(")):
        calls = _calls_in_order(_method(tools, cls, "execute"))
        wait = [ln for ln, name, _ in calls if name == "_await_stack_leases_1202nx"]
        down = [ln for ln, _, src in calls if marker in src]
        assert wait and down, (cls, wait, down)
        assert min(wait) < min(down), cls


def test_the_walk_and_the_visual_capture_hold_the_lease():
    heal = (LLM / "multi_agent" / "runtime" / "heal_pipeline.py").read_text()
    walk = heal[heal.index("def _walk():"):]
    walk = walk[:walk.index("report = _walk()")]
    assert 'stack_lease_1202nx(proj, "browser test-user walk")' in walk
    assert walk.index("stack_lease_1202nx") < walk.index("run_browser_test_user(")
    vf = (LLM / "multi_agent" / "runtime" / "visual_fidelity.py").read_text()
    i = vf.index('_lease_1202nx(orch.output_dir, "visual capture")')
    assert vf.index("result = await run_visual_fidelity(orch.output_dir", i) > i
