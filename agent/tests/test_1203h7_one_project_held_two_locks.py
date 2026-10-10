r"""#1203h7: the compose mutex keyed its lock on the caller's cwd, so one project had two.

#1202hn exists to stop exactly one thing: RunHub's `up -d --remove-orphans` and
`validation_runner`'s landing on the same compose project at once, one removing a
container the other had just created, RunHub then recording `aborted` with
`Error response from daemon: No such container` over a stack that was healthy.
Its cure is a POSIX file lock on `<cwd>/.compose.lock`.

Its two callers pass different cwds for the same project:
    RunHub            service.py -> ComposeLifecycle(cwd=<env_root>)
    validation_runner _compose(..., cwd=<env_root>/docker)
Both then run `-f <env_root>/docker/docker-compose.yml` -- the framework-wide
convention `_resolve_compose_file` documents. So each took a lock the other never
looked at, and the mutex serialized nothing between the only two callers it was
written for.

MEASURED on disk: 63 runs carry `<run>/.compose.lock` and 66 carry
`<run>/docker/.compose.lock`. instagram-core-r175 carries BOTH, created 37 seconds
apart (12:02:32 and 12:03:09). r175 then reproduced r105's signature verbatim at
12:27:22: runhub `compose up FAILED ... (rc=1)` with `No such container`, while
`validation_runner` logged `up -d --remove-orphans -> rc=0 in 5s` for the same
window and the run read live seed counts off the stack five seconds later.

★ WHY A GREEN SUITE SAID NOTHING. Every existing #1202hn test drives the mutex
through ONE call shape. A lock excludes a second holder perfectly as long as both
holders agree on the path, and a single-caller test can never disagree. The
decisive test here is the one that holds the lock as one caller and then asks for
it as the OTHER -- see `test_the_two_callers_contend_for_the_same_lock`.
"""
import ast
import fcntl
import inspect
import os
import sys
from pathlib import Path

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.compose_mutex import (  # noqa: E402
    compose_file_from_args_1203h7, compose_mutex_1202hn, project_lock_dir_1203h7)


def _project(tmp_path):
    """The framework's layout: the compose file under <env_root>/docker/."""
    root = tmp_path / "instagram-core-rTEST"
    (root / "docker").mkdir(parents=True)
    cf = root / "docker" / "docker-compose.yml"
    cf.write_text("services: {}\n")
    return root, cf


# ------------------------------------------------------------- the derivation
def test_the_two_callers_agree_on_one_lock_directory(tmp_path):
    """★ THE defect, stated as an equality. Before this patch these were
    <env_root> and <env_root>/docker."""
    root, cf = _project(tmp_path)
    runhub_args = ["docker", "compose", "-f", str(cf), "up", "-d", "--remove-orphans"]
    runhub = project_lock_dir_1203h7(root, compose_file_from_args_1203h7(runhub_args))
    validation = project_lock_dir_1203h7(root / "docker", cf)
    assert runhub == validation == (root / "docker").resolve()


def test_the_lock_dir_is_the_compose_files_parent(tmp_path):
    root, cf = _project(tmp_path)
    assert project_lock_dir_1203h7("/some/unrelated/cwd", cf) == cf.parent.resolve()


def test_without_a_compose_file_the_cwd_is_the_project(tmp_path):
    """Compose itself assumes this when `-f` is absent, so the fallback must match
    it rather than invent a path."""
    root, _cf = _project(tmp_path)
    assert project_lock_dir_1203h7(root, None) == root.resolve()


def test_a_relative_and_an_absolute_spelling_land_together(tmp_path, monkeypatch):
    """The same trap one level down: two spellings of one path are two locks."""
    root, cf = _project(tmp_path)
    monkeypatch.chdir(root / "docker")
    assert (project_lock_dir_1203h7(".", "docker-compose.yml")
            == project_lock_dir_1203h7(root, cf))


@pytest.mark.parametrize("args,want", [
    (["compose", "-f", "/p/docker-compose.yml", "up"], "/p/docker-compose.yml"),
    (["compose", "--file", "/q/dc.yml", "down"], "/q/dc.yml"),
    (["compose", "up", "-d"], None),
    (["compose", "-f"], None),
    ([], None),
    (None, None),
])
def test_the_compose_file_is_read_out_of_the_args(args, want):
    assert compose_file_from_args_1203h7(args) == want


# --------------------------------------------------------- the actual exclusion
def test_the_two_callers_contend_for_the_same_lock(tmp_path):
    """★ THE TEST THAT WOULD HAVE FAILED. Hold the lock the way validation_runner
    does (cwd=<env_root>/docker) and then ask for it the way RunHub does
    (cwd=<env_root>): the wait must expire, which is the mutex reporting that
    someone else holds this project. Before #1203h7 RunHub would have opened a
    different file and been granted the lock instantly."""
    root, cf = _project(tmp_path)
    held_dir = project_lock_dir_1203h7(root / "docker", cf)
    fd = os.open(str(held_dir / ".compose.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with compose_mutex_1202hn(root, "up", timeout_s=0.2, compose_file=cf) as held:
            assert held is False, (
                "RunHub was granted a lock validation_runner is holding")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_the_lock_is_still_granted_when_the_project_is_free(tmp_path):
    """The negative control: without a holder the same call must succeed, so the
    test above is measuring contention and not a broken path."""
    root, cf = _project(tmp_path)
    with compose_mutex_1202hn(root, "up", timeout_s=0.2, compose_file=cf) as held:
        assert held is True


def test_two_different_projects_do_not_block_each_other(tmp_path):
    """★ The over-match guard. This machine runs containers for many environments;
    the module's docstring is explicit that serializing every generation against
    every other would be worse than the race."""
    root_a, cf_a = _project(tmp_path / "a")
    root_b, cf_b = _project(tmp_path / "b")
    fd = os.open(str(project_lock_dir_1203h7(root_a, cf_a) / ".compose.lock"),
                 os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with compose_mutex_1202hn(root_b, "up", timeout_s=0.2,
                                  compose_file=cf_b) as held:
            assert held is True, "an unrelated project was serialized against this one"
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_the_lock_file_lands_in_the_project_dir_only(tmp_path):
    """One lock per project on disk, which is the corpus observation inverted: no
    run should end up carrying both spellings again."""
    root, cf = _project(tmp_path)
    with compose_mutex_1202hn(root, "up", timeout_s=0.2, compose_file=cf):
        pass
    assert (root / "docker" / ".compose.lock").exists()
    assert not (root / ".compose.lock").exists(), (
        "the env root grew its own second lock again")


# ------------------------------------------------------- both callers are wired
def _call_arg_names(path, fname):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == fname):
            out.append({kw.arg for kw in node.keywords})
    return out


@pytest.mark.parametrize("rel", [
    "env_generator/llm_generator/multi_agent/runtime/hubs/runhub/compose.py",
    "env_generator/llm_generator/multi_agent/runtime/validation_runner.py",
])
def test_every_call_site_names_the_project(rel):
    """★ Structural, because "fixing one reader is worse than none" is exactly how
    this defect was born: #1202hn landed the lock at both sites and let each one
    name the project its own way."""
    calls = _call_arg_names(os.path.join(_AGENT, rel), "compose_mutex_1202hn")
    assert calls, f"{rel} no longer takes the compose lock"
    for kwargs in calls:
        assert "compose_file" in kwargs, (
            f"{rel} calls compose_mutex_1202hn without naming the project")


def test_the_mutex_no_longer_keys_on_the_bare_cwd():
    """The old line was `d = Path(str(cwd))`. If it comes back, so does the defect."""
    src = inspect.getsource(compose_mutex_1202hn)
    assert "project_lock_dir_1203h7" in src, src
    assert "Path(str(cwd))" not in src, src
