r"""#895: `from ..progress import` killed r152 at 30 minutes, inside the delivery gate.

r152 — the first run after ~40 unverified fixes — ended with:

    generation_error | attempted relative import beyond top-level package
    File "orchestrator.py", line 3998, in _validate_delivery_gate
        from ..progress import EventType as _ProgressEventType

`progress`, `checkpoint` and `context` are **top-level modules on the path**, not siblings of
`llm_generator`. Line 48 of that same file already imports `progress` correctly. The bad line was
added the same day, and because it sits in `_validate_delivery_gate`, **the delivery gate could
never pass on any run** from the moment it landed.

★ The suite did not catch it: nothing drives `_validate_delivery_gate` far enough to execute a
function-local import. `compile()` cannot either — a deferred import is only a syntax-valid
statement until it runs. This is the same lesson #894 learned an hour earlier, from a bug of mine
in the same shape: **an import inside a function is not checked by importing the module.**

### what made it a 30-second diagnosis instead of an archaeology dig

`progress_events.jsonl` for r152 read:

    generation_start / phase_start Agent Workflow / stage: milestone_plan /
    Kickoff M1 / stage: database_scaffold ×2 / phase_error / generation_error <the message>

#894's stage timeline said how far it got, #863 said kickoff booted, and #876's terminal
`generation_error` carried the reason. For the 7 runs of item 190 the same file held **two lines**
and answering the same question took an artifact-tree census.
"""
import ast
import pathlib
import re

import pytest


_ROOT = (pathlib.Path(__file__).resolve().parents[1] / "env_generator/llm_generator")
_TOP_LEVEL = ("progress", "checkpoint", "context", "utils")


def _offenders():
    """Relative imports of a TOP-LEVEL module, from real code — comments do not count.

    Parsed with `ast` rather than grepped, because this file and the fix's own comment both quote
    the forbidden form; #847c is the same lesson (a heading inside a code fence is a quotation,
    not a declaration)."""
    out, files = [], 0
    for f in sorted(_ROOT.rglob("*.py")):
        if f.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except Exception:
            continue
        files += 1
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.level and n.level >= 2:
                root = (n.module or "").split(".")[0]
                if root in _TOP_LEVEL:
                    out.append(f"{f.relative_to(_ROOT)}:{n.lineno} "
                               f"from {'.' * n.level}{n.module} import ...")
    return out, files


def test_the_scan_sees_the_tree():
    """Non-vacuity with a denominator."""
    _, files = _offenders()
    assert files >= 100, files


def test_no_top_level_module_is_imported_relatively():
    bad, _ = _offenders()
    assert not bad, (
        "a top-level module imported as a package-relative sibling — this raises "
        "'attempted relative import beyond top-level package' the first time the line RUNS, and "
        "if it is inside a function neither the test suite nor compile() will notice:\n"
        + "\n".join(bad))


def test_the_scanner_would_catch_the_r152_line():
    """★ Non-vacuity for the detector, on the exact statement that killed the run."""
    tree = ast.parse("def f():\n    from ..progress import EventType\n")
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.level >= 2
             and (n.module or "").split(".")[0] in _TOP_LEVEL]
    assert len(found) == 1


def test_a_legitimate_sibling_relative_import_is_not_flagged():
    """`from .runtime.x import y` and `from ..agents.z import w` are normal and must stay."""
    tree = ast.parse("from .runtime.delivery_gate import validate_delivery_gate\n"
                     "from ..agents.base import Agent\n")
    found = [n for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.level >= 2
             and (n.module or "").split(".")[0] in _TOP_LEVEL]
    assert not found


def test_the_delivery_gate_import_actually_resolves():
    """★ The check that would have caught it: EXECUTE the statement, do not read it. A deferred
    import is syntax-valid until it runs, which is why the suite was green while the gate could
    never pass."""
    import inspect
    from env_generator.llm_generator.multi_agent.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator._validate_delivery_gate)
    stmts = re.findall(r"^\s*(from [.\w]+ import [^\n#]+)", src, re.M)
    assert stmts, "non-vacuity: the method must still carry function-local imports"
    # the method's real package context — a RELATIVE import needs `__package__`, and running the
    # statement without it fails for a reason that has nothing to do with the bug being guarded.
    ctx = {"__name__": "env_generator.llm_generator.multi_agent.orchestrator",
           "__package__": "env_generator.llm_generator.multi_agent"}
    for st in stmts:
        exec(compile(st.strip(), "<gate-import>", "exec"), dict(ctx))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
