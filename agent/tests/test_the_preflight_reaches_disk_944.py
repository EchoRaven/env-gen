r"""#944: the environment diagnosis lived in memory and a logger, and nowhere a reader can find it.

`_preflight_check` answers the question you ask FIRST when a run produces a hollow app — was the
container runtime even there? — and its result went to `self.context.preflight` and a log line.
The string "preflight" appears in **zero** of r154's artifacts. Same erasure as #935's #769 line
and #932's findings, one layer out, and this one describes the MACHINE: unlike a code defect, a
reader cannot reconstruct it afterwards from the source.

★ And the advice was wrong for this host. "Start Docker Desktop" is not the fix on a podman box.
The real fix ships in this repo — `tools/podman_shim` maps `docker`/`docker compose` onto
`podman`/`podman-compose` — and nothing puts it on PATH (`tools/podman_setup.sh` tells a human to).
Without it every container call raises inside a `try`, the run continues to completion, and two
hours later there is nothing to show for a missing PATH entry.

No abort: whether a shim-less launch should FAIL rather than degrade is a real decision and not
mine. This only makes the state visible and names the remedy.
"""
import ast
import asyncio
import inspect
import json
import logging
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent import orchestrator as orc


def _run_preflight():
    """★ `_preflight_check` reads `self.context.api_port` for the port scan, so the stub needs one.
    Found by running it, not by reading it."""
    import types
    o = object.__new__(orc.Orchestrator)
    o._logger = logging.getLogger("t944")
    o.context = types.SimpleNamespace(api_port=8000, ui_port=3000, frontend_port=3000,
                                      db_port=5432)
    return asyncio.new_event_loop().run_until_complete(orc.Orchestrator._preflight_check(o))


# --------------------------------------------------------------------------- the probe itself

def test_the_preflight_reports_the_compose_provider():
    r = _run_preflight()
    assert set(r) >= {"docker", "node", "ports", "compose"}
    assert "provider" in r["compose"] and "service_ps" in r["compose"]


def test_on_this_host_it_names_podman_compose():
    """Measured, not assumed: this box runs podman-compose behind the shim."""
    r = _run_preflight()
    if r["compose"].get("provider") not in ("unknown", ""):
        assert isinstance(r["compose"]["service_ps"], bool)


# --------------------------------------------------------------------------- it reaches disk

def _enclosing(src, needle):
    tree = ast.parse(src)
    ln = next(i + 1 for i, l in enumerate(src.splitlines()) if needle in l)
    return max((n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.lineno <= ln <= (n.end_lineno or 0)),
               key=lambda n: n.lineno), ln


def test_the_result_is_written_to_the_run_directory():
    src = inspect.getsource(orc)
    fn, ln = _enclosing(src, 'logs" / "preflight.json"')
    assert fn.name, "the persist must live inside a function"
    writes = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", None) == "write_text"]
    assert writes, "preflight.json must be written, not just logged"


def test_the_remedy_is_computed_before_the_file_is_written():
    """★ The seam: I wrote the persist first, so the remedy the reader most needs was added to the
    dict AFTER it had already been serialised. Order is the whole point of the field."""
    src = inspect.getsource(orc)
    _, remedy_ln = _enclosing(src, '["remedy"] =')
    _, write_ln = _enclosing(src, 'logs" / "preflight.json"')
    assert remedy_ln < write_ln, (remedy_ln, write_ln)


def test_the_persist_is_not_inside_the_docker_failure_branch():
    """A clean host must get a preflight.json too — otherwise its absence is ambiguous between
    'not recorded' and 'nothing wrong' (#907)."""
    src = inspect.getsource(orc)
    tree = ast.parse(src)
    lines = src.splitlines()
    write_ln = next(i + 1 for i, l in enumerate(lines) if 'logs" / "preflight.json"' in l)
    # ★ measured by CONTAINMENT, not indentation: the first version compared the indent of the
    # assignment (inside a `try:`, 12 spaces) against the guard's (8), and failed on correct code.
    # ★ `ast.unparse` NORMALISES quotes: the source says `preflight["docker"]["available"]` and
    # unparse emits `preflight['docker']['available']`. Matching on the source spelling found
    # nothing and the test reported "the guard moved" — a locator failing open.
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.If)
              and "preflight['docker']['available']" in ast.unparse(n.test)]
    assert guards, "the docker guard moved; this test needs re-anchoring"
    for g in guards:
        inside = any(b.lineno <= write_ln <= (b.end_lineno or 0) for b in g.body)
        assert not inside, "a clean host must get a preflight.json too"


# --------------------------------------------------------------------------- the remedy

def test_the_shim_path_it_names_actually_exists():
    """★ A remedy that points at nothing is worse than none — the reader tries it and loses trust
    in the rest of the report. Resolved from __file__, so this asserts the arithmetic."""
    root = Path(inspect.getfile(orc)).resolve().parents[4]
    assert (root / "tools" / "podman_shim" / "docker").is_file(), root


def test_the_remedy_is_conditional_on_podman_being_present():
    src = inspect.getsource(orc)
    fn, _ = _enclosing(src, '["remedy"] =')
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "which"]
    assert calls, "the hint must depend on what is actually installed, not on a guess"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
