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
import sys

import pytest


# #802b: the first version scanned `runtime/` only -- 235 of the tree's 364 function-level
# framework imports, i.e. 64%. It excluded `agents/` (35) and the package top level (94), and the
# top level is `orchestrator.py`, where #793 had just ADDED a lazy import. A guard that omits the
# file whose defect motivated it is the #804 gap again: coverage narrower than the name implies,
# from the moment it was written.
_ROOT = (pathlib.Path(__file__).resolve().parents[1]
         / "env_generator/llm_generator/multi_agent")
_PKG_ROOT = "env_generator.llm_generator.multi_agent"
_LG = _ROOT.parent

# #1203n6: AND THE IDIOM THAT ACTUALLY WORKS. The skip below read
#
#     if node.level == 0 and not node.module.startswith("env_generator"): continue
#
# so `from tools.browser._manager import ...` -- level 0, module `tools...` -- was filed as
# third-party and never checked. But `tools` is not third-party: `orchestrator.py` and
# `_paths.setup_paths()` put LLM_GENERATOR_DIR on sys.path deliberately ("memory, tools, etc.
# (from LLM_GENERATOR_DIR)"), which is what makes `from tools.X` resolve, and it is the form
# 20+ call sites in this tree use. MEASURED: 105 function-level imports of this tree's OWN
# modules, in 34 files, had never been checked -- 42 `utils`, 34 `tools`, 26 `multi_agent`
# (the dual-root form), 2 `progress`, 1 `checkpoint` -- against 840 that were. All 105 resolve
# today, so this widening is coverage, not a repair.
#
# This is the hole #1203iu fell through from the other side: its comment said "#802 checks that
# this very import resolves", and #802 did -- under THIS root. The relative form it used goes
# above the top level under the runtime's root (`multi_agent.runtime`), so the real import
# raised in r189/r190/r191 while this guard stayed green. The escape ratchet lives in
# test_1203n6_the_import_that_could_not_resolve.py; this is the other half: once the form is
# absolute, something has to still be checking it.
#
# The owned-name set is read off the filesystem, never listed -- item 110's `_OWNER_FK_NAMES`
# trap is the reason this file discovers by AST in the first place.
_OWNED_TOPS = {p.name for p in _LG.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
_OWNED_TOPS |= {p.stem for p in _LG.iterdir() if p.suffix == ".py"}
_OWNED_TOPS.add("utils")          # AGENTS_DIR-rooted, per _paths' own docstring

# The two roots must BE on sys.path for the absolute form to resolve, exactly as the runtime
# puts them there. Done explicitly so this test does not depend on which module some earlier
# test happened to import first.
if str(_LG) not in sys.path:
    sys.path.insert(0, str(_LG))
if str(_LG.parent.parent) not in sys.path:
    sys.path.insert(0, str(_LG.parent.parent))


def _is_ours(module: str, level: int) -> bool:
    if level != 0:
        return True
    return module.startswith("env_generator") or module.split(".")[0] in _OWNED_TOPS


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
                if not _is_ours(node.module, node.level):
                    continue                      # third-party / stdlib: not ours to police
                out.append((rel, node.lineno, node.module, node.level,
                            tuple(a.name for a in node.names)))
    return out


_IMPORTS = _function_level_imports()


def test_the_scan_finds_something():
    """Non-vacuity. If a refactor moves these, this test must fail rather than silently pass —
    the sixth instrument-zero of this session is why that sentence is here."""
    assert len(_IMPORTS) >= 300, len(_IMPORTS)   # 364 at the time of writing


def test_the_tree_internal_absolute_imports_are_in_scope_1203n6():
    """Separate from the floor above, because they are a separate claim. Dropping the widening
    would leave the count above satisfied while 105 imports went back to being invisible."""
    abs_ours = [i for i in _IMPORTS
                if i[3] == 0 and not i[2].startswith("env_generator")]
    assert len(abs_ours) >= 50, len(abs_ours)    # 105 at the time of writing
    tops = {i[2].split(".")[0] for i in abs_ours}
    assert {"tools", "utils"} <= tops, sorted(tops)


def test_the_owned_set_is_read_off_the_filesystem_1203n6():
    """It must contain the tree's real top levels and nothing stdlib-shaped."""
    assert {"tools", "multi_agent", "checkpoint"} <= _OWNED_TOPS, sorted(_OWNED_TOPS)
    assert not ({"json", "pathlib", "collections", "PIL"} & _OWNED_TOPS)


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
