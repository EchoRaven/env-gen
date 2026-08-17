r"""#802: every function-level import in the runtime must actually resolve.

A module-level import fails loudly at startup. A **function-level** one fails only when that branch
runs — and the branches that carry them are, by construction, the rare ones: error handlers,
fallbacks, and guards. This session hit both halves of that:

  * #794's first cut used `Mapping` without importing it — a `NameError` on the release path,
    inside a branch that only fires after a check has already failed twice. `ast.parse` said the
    file was fine; importing the module found it.
  * #789's whole subject IS a lazy import failing: `from ..agents.runtime.auto_commit import
    _OWNERSHIP` raising turned the write guard off, silently and permanently.

So the failure mode is not hypothetical, and it is the worst-placed kind: the code that only runs
when something has already gone wrong.

This test **discovers** the imports by AST rather than listing them. A hand-maintained list is the
`_OWNER_FK_NAMES` trap from item 110 — a curated set standing in for a semantic question, which
goes stale the moment someone adds the tenth entry and does not update it. Discovery means the
next lazy import added anywhere in `runtime/` is covered without anyone remembering to.
"""
import ast
import importlib
import pathlib

import pytest


# #802b: the first version scanned `runtime/` only -- 235 of the tree's 364 function-level
# framework imports, i.e. 64%. It excluded `agents/` (35) and the package top level (94), and the
# top level is `orchestrator.py`, where #793 had just ADDED a lazy import. A guard that omits the
# file whose defect motivated it is the #804 gap again: coverage narrower than the name implies,
# from the moment it was written.
_ROOT = (pathlib.Path(__file__).resolve().parents[1]
         / "env_generator/llm_generator/multi_agent")
_PKG_ROOT = "env_generator.llm_generator.multi_agent"


def _function_level_imports():
    """(file, lineno, module, names) for every import nested inside a function/method."""
    out = []
    for f in sorted(_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                       # not this test's business
            continue
        rel = f.relative_to(_ROOT).as_posix()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if node.level == 0 and not node.module.startswith("env_generator"):
                    continue                      # third-party / stdlib: not ours to police
                out.append((rel, node.lineno, node.module, node.level,
                            tuple(a.name for a in node.names)))
    return out


_IMPORTS = _function_level_imports()


def test_the_scan_finds_something():
    """Non-vacuity. If a refactor moves these, this test must fail rather than silently pass —
    the sixth instrument-zero of this session is why that sentence is here."""
    assert len(_IMPORTS) >= 300, len(_IMPORTS)   # 364 at the time of writing


def _resolve(rel, module, level):
    if level == 0:
        return importlib.import_module(module)
    # relative: `level` dots up from the importing file's package
    pkg = _PKG_ROOT if "/" not in rel else _PKG_ROOT + "." + rel.rsplit("/", 1)[0].replace("/", ".")
    parts = pkg.split(".")
    base = ".".join(parts[:len(parts) - (level - 1)]) if level > 1 else pkg
    return importlib.import_module(f"{base}.{module}" if module else base)


@pytest.mark.parametrize("rel,lineno,module,level,names", _IMPORTS,
                         ids=[f"{r}:{l}" for r, l, _, _, _ in _IMPORTS])
def test_every_lazy_import_resolves(rel, lineno, module, level, names):
    try:
        mod = _resolve(rel, module, level)
    except Exception as exc:                      # pragma: no cover - the failure IS the report
        pytest.fail(f"{rel}:{lineno} cannot import {'.' * level}{module}: "
                    f"{type(exc).__name__}: {exc}")
    for n in names:
        if n == "*":
            continue
        if not hasattr(mod, n):
            # a submodule imported by name is legitimate and has no attribute on the parent
            try:
                importlib.import_module(f"{mod.__name__}.{n}")
                continue
            except Exception:
                pass
            pytest.fail(f"{rel}:{lineno} imports `{n}` from {'.' * level}{module}, "
                        f"which does not define it — a NameError waiting for that branch to run")


# --- what widening the scan found -------------------------------------------------------------

def test_the_profile_keyword_map_names_real_agent_types():
    """#802b. Widening the scan past `runtime/` immediately found a broken lazy import in
    `team_runtime/parallel_runtime/profiled.py`: `from ..agents.configurable_agent import ...`
    resolves to `team_runtime.agents`, which does not exist. It was wrapped in
    `except Exception: available = set()`, so it raised on EVERY call, `available` was always
    empty, and the guard below it — `if not available or candidate in available` — always took
    its first branch and returned the first keyword match unvalidated.

    A dead validation. With it alive, two of the eight keyword targets turn out never to have
    been registered agent types at all: `database` and `design`. They had been shipping a name
    nothing resolves, which is exactly what that check existed to prevent."""
    import re
    from env_generator.llm_generator.multi_agent.agents.configurable_agent import (
        list_available_agents)
    src = (_ROOT / "team_runtime/parallel_runtime/profiled.py").read_text(encoding="utf-8")
    i = src.index("keyword_candidates")
    block = src[i:src.index("]", src.index("[", i)) + 1]
    targets = sorted(set(re.findall(r'\("[^"]+",\s*"([^"]+)"\)', block)))
    assert len(targets) >= 6, f"non-vacuity: the map should have several targets, got {targets}"
    available = set(list_available_agents())
    assert available, "non-vacuity: the registry really does list agent types"
    assert not (set(targets) - available), sorted(set(targets) - available)


def test_the_validation_can_actually_run_now():
    """The import that was broken. If it breaks again the map silently stops being checked."""
    from env_generator.llm_generator.multi_agent.agents.configurable_agent import (
        list_available_agents)
    assert len(list_available_agents()) >= 5


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
