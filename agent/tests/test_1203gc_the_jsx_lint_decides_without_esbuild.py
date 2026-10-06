"""#1203gc -- `_esbuild_syntax_check`'s decision rule, tested where esbuild is absent.

#165 made every `.jsx`/`.tsx` write go through `npx --no-install esbuild`, because a .jsx
truncated to a missing `}` used to sail through every write and only surface at the docker build
(gmrun8: SearchPage.jsx 331 `{` vs 330 `}` -> post-delivery docker_up wedge -> stuck_abort).

The check works in production: across the 4911 run log/jsonl files on this host there are 330
write refusals, 56 of them naming a `.jsx` (145 .py, 64 .js, 31 .yml, 34 unattributable), so
esbuild really is cached in the run environment and really does block broken JSX.

It is not cached on THIS host. `test_jsx_write_lint.py` gates all four of its cases on
`_probe_esbuild()`, so the only tests of this path never execute here, and a regression in the
decision rule would be invisible to the suite. The rule itself needs no esbuild -- it is a
decision about a CompletedProcess -- and that is what this file pins:

    returncode 0                     -> allow
    nonzero AND stderr names my file -> BLOCK (a real syntax error)
    nonzero but names something else  -> allow (npm/npx resolution noise, not my file)
    FileNotFoundError / timeout       -> allow

The asymmetry is the point: a missing or slow tool must never block a write (#1202qm/qn: no
fallback that masks a failure, and equally no tool outage that masquerades as one), while a
genuine parse error must always block it. Inverting either direction is a shipped bug -- the
first wedges every lane behind a tool problem, the second is #165 regressed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tools.file_tools as ft  # noqa: E402

FILE = Path("/w/app/frontend/src/Card.jsx")


class _Completed:
    def __init__(self, returncode, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


@pytest.fixture
def fake_run(monkeypatch):
    """Replace only the subprocess call; the decision rule under test stays real."""
    def _install(outcome):
        def _run(*a, **k):
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        monkeypatch.setattr(ft.subprocess, "run", _run)
    return _install


def test_a_clean_parse_allows_the_write(fake_run):
    fake_run(_Completed(0))
    assert ft._esbuild_syntax_check(FILE) == (True, "")


def test_a_syntax_error_that_names_the_file_blocks_the_write(fake_run):
    fake_run(_Completed(1, '/w/app/frontend/src/Card.jsx:12:3: ERROR: Expected "}" but found "<"'))
    ok, err = ft._esbuild_syntax_check(FILE)
    assert ok is False
    assert "Card.jsx:12:3" in err, err


def test_an_npx_resolution_failure_does_not_block_the_write(fake_run):
    """esbuild not cached: npm complains without ever parsing the file."""
    fake_run(_Completed(1, "npm ERR! could not determine executable to run"))
    assert ft._esbuild_syntax_check(FILE) == (True, "")


def test_an_error_about_a_different_file_does_not_block_this_one(fake_run):
    fake_run(_Completed(1, "/w/app/frontend/src/other.js:1:1: ERROR: boom"))
    assert ft._esbuild_syntax_check(FILE) == (True, "")


@pytest.mark.parametrize("exc", [
    FileNotFoundError("npx"),
    subprocess.TimeoutExpired("npx", 25),
    OSError("exec format error"),
])
def test_a_tool_outage_never_blocks_a_write(fake_run, exc):
    fake_run(exc)
    assert ft._esbuild_syntax_check(FILE) == (True, "")


def test_the_error_is_capped_and_the_cut_is_declared(fake_run):
    """#1034: a truncated message must say it was truncated."""
    long = "/w/app/frontend/src/Card.jsx:1:1: ERROR: " + ("x" * 2000)
    fake_run(_Completed(1, long))
    ok, err = ft._esbuild_syntax_check(FILE)
    assert ok is False
    assert len(err) <= 520, len(err)
    assert err.endswith("..."), err[-40:]


def test_jsx_and_tsx_both_route_to_the_esbuild_check():
    """The suffix routing, so this file's subject is the one run_lint actually reaches.
    `node --check` cannot parse JSX and `tsc` false-positives a config-less file -- the reason
    #165 picked esbuild in the first place."""
    import ast
    src = Path(ft.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "run_lint")
    branch = next(
        b for b in ast.walk(fn)
        if isinstance(b, ast.If) and "'.jsx'" in ast.unparse(b.test).replace('"', "'"))
    assert "'.tsx'" in ast.unparse(branch.test).replace('"', "'")
    assert "_esbuild_syntax_check" in ast.unparse(branch.body)
