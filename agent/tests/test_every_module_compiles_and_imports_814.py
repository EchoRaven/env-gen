r"""#814: `compile()` and `import`, as a standing gate — because `ast.parse` was not one.

#813's method correction, made durable. `ast.parse` was my syntax check throughout this session
and it **passed** a file that Python itself refuses: the first cut of #813 placed `import logging`
above `from __future__ import annotations`. `ast.parse` builds a tree; it does not enforce
`__future__` placement. `compile()` does. Importing does more still — it runs module-level code,
which is where a bad decorator, a missing name at class-definition time or a circular import shows
up.

Re-checked the whole session's diff after finding the hole: 18 changed files all `compile()`, and
all 15 changed framework modules import. Nothing was left behind. But a one-off check guards
nothing (#786/#793), so it is a test.

The whole tree is **154 modules in 0.6s**, which is cheap enough that there is no reason to scope
it to changed files and re-introduce the coverage-narrower-than-its-name problem (#802b/#809).

★ Note what this does NOT claim. Importing proves a module loads, not that it works — and this
session's defects were overwhelmingly behavioural, not import-time. Its value is narrow and real:
it closes one specific hole, in the gate I was actually using.
"""
import compileall  # noqa: F401  (documents intent; the explicit loop below is the check)
import importlib
import pathlib
import sys

import pytest


_ROOT = (pathlib.Path(__file__).resolve().parents[1]
         / "env_generator/llm_generator/multi_agent")
_PKG = "env_generator.llm_generator.multi_agent"

_FILES = sorted(p for p in _ROOT.rglob("*.py"))
_MODULES = [
    _PKG + "." + p.relative_to(_ROOT).as_posix()[:-3].replace("/", ".")
    for p in _FILES if p.name != "__init__.py"
]


def test_the_scan_finds_the_tree():
    """Non-vacuity: a moved package would otherwise make every check below vacuously pass — the
    instrument-zero rule, applied to this file."""
    assert len(_MODULES) >= 100, len(_MODULES)


@pytest.mark.parametrize("path", _FILES, ids=[p.name for p in _FILES])
def test_every_file_compiles(path):
    """Stricter than `ast.parse`: this rejects a misplaced `__future__` import, which is exactly
    what slipped through in #813."""
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


@pytest.mark.parametrize("mod", _MODULES, ids=[m.rsplit(".", 1)[-1] for m in _MODULES])
def test_every_module_imports(mod):
    """Runs module-level code — where a bad decorator, a name missing at class-definition time,
    or a circular import appears. `compile()` sees none of those."""
    if mod in sys.modules:
        return
    importlib.import_module(mod)


def test_ast_parse_really_is_weaker():
    """Non-vacuity for this file's whole premise: demonstrate the gap rather than asserting it.

    If a future Python makes `ast.parse` strict here, this fails and the docstring above should be
    corrected rather than the test deleted."""
    import ast
    bad = "import logging\nfrom __future__ import annotations\n"
    ast.parse(bad)                       # accepted
    with pytest.raises(SyntaxError):
        compile(bad, "<bad>", "exec")    # refused


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
