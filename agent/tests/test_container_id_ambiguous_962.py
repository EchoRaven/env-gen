"""#962 — two stacks, one name filter: answer "unknown" rather than about the wrong app.

Every run's compose project is named ``docker`` — podman/compose derive the project from the
compose file's parent directory, and that is always ``<run>/docker/``. So containers are named
``docker_backend_1`` with no run identity in them, and ``ps --filter name=backend`` matches EVERY
run's stack that happens to be up.

Measured on 2026-08-18: a probe stack from 01:03 was still running at 09:54 holding the next run's
ports, with a named volume (``docker_app_auth_keys``, containing a JWT private key) that the next
run would have mounted. Under that state the pre-#962 fallback returned ``ids[0]`` — an arbitrary
run's container — to every staleness probe.

`""` is recoverable (callers already treat it as "unknown"); a confident wrong container is not.
"""
from __future__ import annotations

import subprocess
import types

import pytest

from env_generator.llm_generator.multi_agent.runtime import container_runtime as cr


def _fake_run(mapping):
    """Build a subprocess.run stand-in dispatching on a distinctive argv fragment."""
    def _run(argv, **kw):
        key = next((k for k in mapping if k in " ".join(str(a) for a in argv)), None)
        return types.SimpleNamespace(returncode=0, stdout=mapping.get(key, ""), stderr="")
    return _run


def test_single_match_is_returned(monkeypatch):
    monkeypatch.setattr(cr, "runtime_bin", lambda: "podman")
    monkeypatch.setattr(subprocess, "run", _fake_run({
        "compose": "",                       # podman-compose: no service positional -> empty
        "--filter": "abc123\n",
    }))
    assert cr.container_id("/r155/docker/docker-compose.yml", "backend") == "abc123"


def test_ambiguous_is_disambiguated_by_compose_file(monkeypatch):
    """Two stacks up; the one whose config_files label names OUR compose file wins."""
    monkeypatch.setattr(cr, "runtime_bin", lambda: "podman")

    def _run(argv, **kw):
        s = " ".join(str(a) for a in argv)
        if "compose" in s and "ps" in s:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "--filter" in s:
            return types.SimpleNamespace(returncode=0, stdout="old111\nnew222\n", stderr="")
        if "inspect" in s:
            cid = argv[2]
            lbl = ("/r154/docker/docker-compose.yml" if cid == "old111"
                   else "/r155/docker/docker-compose.yml")
            return types.SimpleNamespace(returncode=0, stdout=lbl + "\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    got = cr.container_id("/r155/docker/docker-compose.yml", "backend")
    assert got == "new222", f"picked {got!r} — a probe would report about another run's container"


def test_ambiguous_and_indistinguishable_returns_empty(monkeypatch):
    """★ The whole point: when it cannot tell, it must NOT guess.

    Pre-#962 this returned ids[0]. `""` makes the caller's probe report "did not run", which is
    the honest answer and the one the codebase already handles (see
    an-unwatched-check-reports-did-not-run).
    """
    monkeypatch.setattr(cr, "runtime_bin", lambda: "podman")

    def _run(argv, **kw):
        s = " ".join(str(a) for a in argv)
        if "compose" in s and "ps" in s:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if "--filter" in s:
            return types.SimpleNamespace(returncode=0, stdout="old111\nnew222\n", stderr="")
        if "inspect" in s:      # neither carries a usable label
            return types.SimpleNamespace(returncode=0, stdout="\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    assert cr.container_id("/r155/docker/docker-compose.yml", "backend") == "", (
        "returned a container id it could not justify — this is how a staleness probe reports "
        "confidently about the wrong app")


def test_compose_ps_still_wins_when_it_works(monkeypatch):
    """A real Compose v2 host never reaches the fallback, so #962 cannot change its behaviour."""
    monkeypatch.setattr(cr, "runtime_bin", lambda: "docker")
    monkeypatch.setattr(subprocess, "run", _fake_run({
        "compose": "fromcompose\n",
        "--filter": "shouldnotbeused\n",
    }))
    assert cr.container_id("/r155/docker/docker-compose.yml", "backend") == "fromcompose"


def test_no_match_is_empty(monkeypatch):
    monkeypatch.setattr(cr, "runtime_bin", lambda: "podman")
    monkeypatch.setattr(subprocess, "run", _fake_run({"compose": "", "--filter": ""}))
    assert cr.container_id("/r155/docker/docker-compose.yml", "backend") == ""
