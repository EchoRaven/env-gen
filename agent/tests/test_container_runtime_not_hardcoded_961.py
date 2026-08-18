"""#961 — the container CLI is resolved, not spelled `docker` in an argv list.

This host has no `docker` binary. Every compose call worked only because `tools/podman_shim` is
hand-added to PATH, and NOTHING guarantees that (#936/#945). Seven argv lists across four modules
still began with the literal, including the generated app's whole up/down lifecycle.

The assertions are deliberately BEHAVIOURAL — patch the PATH probe, read the argv that comes out.
A test that greps for `_rt936(` would forbid renaming the helper, which is the failure mode that
kept #782 alive for 122 runs (see: a-green-suite-can-pin-the-defect).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_LLM = pathlib.Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"

# The argv sites converted by #961. Listed as paths, not as source text, so a rename of the
# resolver does not break the test.
_CONVERTED = [
    _LLM / "multi_agent" / "runtime" / "hubs" / "runhub" / "compose.py",
    _LLM / "multi_agent" / "runtime" / "validation_runner.py",
    _LLM / "tools" / "docker_tools.py",
    _LLM / "tools" / "database_tools.py",
]

#: second element of an argv list that makes it a real command rather than a keyword/tag list.
#: memory_bank.py:997 is ["docker","compose","port","url",...] — a KEYWORD list, and it is exactly
#: the false positive #936b's locator produced. The discriminator is a `-f`/`str(...)` argument,
#: not the subcommand alone.
_SUBCMDS = {"compose", "ps", "port", "exec", "logs", "build", "run", "inspect",
            "cp", "rm", "stop", "start", "images", "container", "system", "info"}


def _argv_docker_literals(path: pathlib.Path):
    """List literals that START a container command with the hardcoded string."""
    found = []
    tree = ast.parse(path.read_text())
    for n in ast.walk(tree):
        if not isinstance(n, ast.List) or not n.elts:
            continue
        first = n.elts[0]
        if not (isinstance(first, ast.Constant) and first.value == "docker"):
            continue
        rest = n.elts[1:]
        if not rest:
            continue
        second = rest[0]
        if not (isinstance(second, ast.Constant) and second.value in _SUBCMDS):
            continue
        # A real argv either carries a non-constant (str(compose_file), *args) or a flag, OR is
        # the bare two-element base ["docker", "compose"]. A keyword list is three-or-more plain
        # words with no flag.
        #
        # ★ The two-element case was MISSING until the planted control caught it: reverting
        # _base_args to ["docker", "compose"] left this locator green while only the behavioural
        # test went red. A locator validated solely against the shapes that motivated it is a
        # restatement of those shapes (item 333).
        has_dynamic = any(not isinstance(e, ast.Constant) for e in rest)
        has_flag = any(isinstance(e, ast.Constant) and str(e.value).startswith("-") for e in rest)
        is_bare_base = len(rest) == 1
        if has_dynamic or has_flag or is_bare_base:
            found.append((n.lineno, ast.unparse(n)[:90]))
    return found


@pytest.mark.parametrize("path", _CONVERTED, ids=lambda p: p.name)
def test_no_hardcoded_docker_argv(path):
    """No converted module still begins an argv with the literal."""
    leftovers = _argv_docker_literals(path)
    assert not leftovers, (
        f"{path.name} still hardcodes the container CLI: {leftovers}. "
        "Use the resolver so a podman host works without tools/podman_shim.")


def test_locator_is_not_vacuous():
    """PLANTED CONTROL — the locator must FAIL on the pre-#961 shape.

    Three of seven instruments failed on 2026-08-18 by matching nothing and passing forever
    (a-bare-name-search-is-never-a-locator). Prove this one bites before trusting a pass.
    """
    import tempfile
    # BOTH pre-#961 shapes: the flagged argv and the bare two-element base.
    src = ('cmd = ["docker", "compose", "-f", str(f), "up"]\n'
           'base = ["docker", "compose"]\n')
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(src)
        tmp = pathlib.Path(fh.name)
    try:
        assert _argv_docker_literals(tmp), "locator does not detect the very shape #961 removed"
    finally:
        tmp.unlink()


def test_keyword_list_is_not_flagged():
    """The known false positive stays negative: a tag list is not an argv."""
    import tempfile
    src = 'KEYWORDS = ["docker", "compose", "port", "url", "vite", "postgres"]\n'
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(src)
        tmp = pathlib.Path(fh.name)
    try:
        assert not _argv_docker_literals(tmp), (
            "a keyword list was flagged as argv — this is the memory_bank.py:997 false positive "
            "that #936b's locator produced")
    finally:
        tmp.unlink()


def test_lifecycle_uses_podman_when_docker_absent(monkeypatch):
    """BEHAVIOURAL: with no `docker` on PATH, the app's up/down argv must say podman."""
    from env_generator.llm_generator.multi_agent.runtime import container_runtime
    from env_generator.llm_generator.multi_agent.runtime.hubs.runhub import compose as _c

    monkeypatch.setattr(container_runtime.shutil, "which",
                        lambda b: None if b == "docker" else f"/usr/bin/{b}")
    args = _c.ComposeLifecycle(cwd="/tmp", compose_file="docker/docker-compose.yml")._base_args()
    assert args[0] == "podman", f"lifecycle still invokes {args[0]!r} on a docker-less host"
    assert args[1] == "compose"


def test_lifecycle_prefers_docker_when_present(monkeypatch):
    """A docker host must behave EXACTLY as before #961 — no silent switch to podman."""
    from env_generator.llm_generator.multi_agent.runtime import container_runtime
    from env_generator.llm_generator.multi_agent.runtime.hubs.runhub import compose as _c

    monkeypatch.setattr(container_runtime.shutil, "which", lambda b: f"/usr/bin/{b}")
    assert _c.ComposeLifecycle(cwd="/tmp")._base_args()[0] == "docker"


def test_resolver_falls_back_to_docker_on_import_failure(monkeypatch):
    """If the resolver cannot be imported at all, behaviour is the pre-#961 literal — never a
    crash in the lifecycle, which `down()` in particular must never raise from."""
    import builtins
    from env_generator.llm_generator.multi_agent.runtime.hubs.runhub import compose as _c

    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if "container_runtime" in name:
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert _c._runtime_bin_961() == "docker"
