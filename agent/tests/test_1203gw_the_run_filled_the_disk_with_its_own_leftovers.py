"""#1203gw: every validation cycle orphaned an image per service and nothing took them back.

MEASURED on r172, attributed by creation time against a baseline taken at launch: 54 minutes
of running produced 25 dangling images totalling 17.5GB, while the 34 that predated the run
matched the pre-run baseline exactly — so all 25 were the run's. 15 builds, so ~1.7 images and
1.17GB per cycle, a rate near 19GB/hour. r171 ran 5h27m and a prune reclaimed 88.29GB from it:
the same rate, arrived at independently.

That garbage is what stopped the pipeline. With root at 0 bytes free, Postgres initdb failed on
`pg_wal: No space left on device`; the framework classified it as a HOST fault, filed no
application bug, and stopped for OPERATOR ACTION — waiting on a human to clear space the run
itself had consumed. `down -v` removes volumes, not images.

The safety property is the scope: only an ID that WAS one of this project's service images and
IS now dangling. On a shared host a global prune reaches other users' images, `--filter until=`
removes the older ones (the wrong direction), and a before/after diff of all dangling IDs
catches anyone's concurrent build. The test that matters most here is the one asserting a
stranger's dangling image is left alone.
"""
import ast
import subprocess
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import validation_runner as VR

RUNNER = (Path(__file__).resolve().parents[1]
          / "env_generator/llm_generator/multi_agent/runtime/validation_runner.py")


class _Calls:
    """Records every subprocess.run the pruner makes, and answers them."""

    def __init__(self, dangling, rmi_rc=0, dangling_rc=0):
        self.dangling = dangling
        self.rmi_rc = rmi_rc
        self.dangling_rc = dangling_rc
        self.removed = None
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        # argv[0] is whatever `runtime_bin()` resolved to (docker or podman) -- #961's ratchet
        # forbids hardcoding it in the product, so the test must not hardcode it either.
        if argv[1:2] == ["images"]:
            return subprocess.CompletedProcess(
                argv, self.dangling_rc, "\n".join(self.dangling) + "\n", "")
        if argv[1:2] == ["rmi"]:
            self.removed = list(argv[2:])
            return subprocess.CompletedProcess(argv, self.rmi_rc, "", "in use" if self.rmi_rc else "")
        raise AssertionError("unexpected command: %s" % argv)


def test_an_orphaned_project_image_is_reclaimed(monkeypatch):
    c = _Calls(dangling=["aaa111", "bbb222"])
    monkeypatch.setattr(VR.subprocess, "run", c)
    VR._prune_orphaned_images_1203gw(["aaa111"])
    assert c.removed == ["aaa111"], c.calls


def test_a_STRANGERS_dangling_image_is_never_touched(monkeypatch):
    """The safety property. On a shared host this is the whole reason for scoping by id."""
    c = _Calls(dangling=["aaa111", "someone_else", "concurrent_build"])
    monkeypatch.setattr(VR.subprocess, "run", c)
    VR._prune_orphaned_images_1203gw(["aaa111"])
    assert c.removed == ["aaa111"], (
        "only this project's prior image may be removed; got %s" % (c.removed,))


def test_a_project_image_still_in_use_is_left_alone(monkeypatch):
    """An id that is NOT dangling is still referenced — it is the image `up` is about to run."""
    c = _Calls(dangling=["someone_else"])
    monkeypatch.setattr(VR.subprocess, "run", c)
    VR._prune_orphaned_images_1203gw(["aaa111"])
    assert c.removed is None, c.calls


def test_nothing_runs_when_there_was_no_before_snapshot(monkeypatch):
    """A first cycle (or a stack that was already down) orphans nothing and must not shell out.

    RECORD the calls instead of raising inside the fake: the function wraps its docker calls in
    `except Exception`, which swallows AssertionError too, so a raising probe is invisible and
    the test passes whether or not the early return exists. A mutation proved that.
    """
    c = _Calls(dangling=["aaa111"])
    monkeypatch.setattr(VR.subprocess, "run", c)
    VR._prune_orphaned_images_1203gw([])
    assert c.calls == [], "docker must not be called with an empty snapshot: %s" % (c.calls,)
    assert c.removed is None


def test_a_failed_docker_listing_removes_nothing(monkeypatch):
    """A non-zero `docker images` must not be read as "nothing is dangling".

    The listing has to PRINT something while failing, or both branches agree on an empty set
    and the assertion cannot fail -- the first version of this test used `dangling=[]` and a
    mutation deleting the returncode check left it green.
    """
    c = _Calls(dangling=["aaa111"], dangling_rc=1)
    monkeypatch.setattr(VR.subprocess, "run", c)
    VR._prune_orphaned_images_1203gw(["aaa111"])
    assert c.removed is None, (
        "a failed listing was trusted; it named %s" % (c.removed,))


def test_an_rmi_refusal_is_reported_not_retried(monkeypatch):
    """Cleanup is not a verdict: a refusal is logged and the validation carries on."""
    c = _Calls(dangling=["aaa111"], rmi_rc=1)
    monkeypatch.setattr(VR.subprocess, "run", c)
    VR._prune_orphaned_images_1203gw(["aaa111"])          # must not raise
    assert len([x for x in c.calls if x[1:2] == ["rmi"]]) == 1, c.calls


def test_short_and_long_ids_still_match(monkeypatch):
    """`compose images -q` and `images -q` agree on width today; compare by prefix so a change
    in either cannot silently match nothing."""
    c = _Calls(dangling=["aaa111bbbccc"])
    monkeypatch.setattr(VR.subprocess, "run", c)
    VR._prune_orphaned_images_1203gw(["aaa111"])
    assert c.removed == ["aaa111"], c.calls


def test_the_snapshot_is_taken_BEFORE_down_v():
    """Position, not presence: `compose images -q` goes empty once the stack is down, so a
    snapshot taken after `down -v` would always be empty and the pruner would never fire."""
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_smoke_validation")
    snap = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and "_project_image_ids_1203gw" in ast.unparse(n.func)]
    # Read the ARGUMENTS, not the unparsed text: `ast.unparse` renders the literals with
    # single quotes, so a `'"down"' in ast.unparse(n)` test finds nothing and this assertion
    # would pass or fail for the wrong reason.
    def _literals(call):
        return [a.value for a in call.args if isinstance(a, ast.Constant)]

    downs = [n.lineno for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and "down" in _literals(n) and "-v" in _literals(n)]
    assert snap and downs, (snap, downs)
    assert min(snap) < min(downs), (
        "the image snapshot must precede `down -v` (%s vs %s)" % (snap, downs))


def test_the_prune_only_runs_after_a_successful_build():
    """#566l skips the rebuild when the source is unchanged, and a skipped build orphans
    nothing — so the prune must sit on the path that wrote a new build fingerprint."""
    src = RUNNER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_smoke_validation")
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        body = ast.unparse(node)
        if "_prune_orphaned_images_1203gw" in body and "_write_build_fingerprint" in body:
            return
    raise AssertionError(
        "the prune is not inside the branch that builds and records the fingerprint")
