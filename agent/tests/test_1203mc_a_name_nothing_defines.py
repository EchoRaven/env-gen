r"""#1203mc: a name a scope references and nothing defines, and the try that hides it.

On 2026-10-15 I reached for a name that did not exist four times in one session -- `json` and
`os` in modules that never imported them, an invented `join_capped_1203ki`, and a missing
`import ast` in a test. Three sat inside `try: ... except Exception: <fallback>`, so the
NameError became a silent downgrade, and `py_compile` passed every time because compiling
does not resolve names.

`scripts/undefined_names.py` answers it with `symtable` -- the scopes CPython computes --
after an AST name-set version was bent twice and got WORSE (254 -> 605 candidates, top hit
`self`). The baseline it is held to here is ZERO across the whole tree; that is what makes it
a tripwire rather than a report.

What it found when it landed: a `Dict` annotation behind a `pytest.skip` that always fired
(the glob named `netflix-web-r*`, which matches nothing -- the corpus is `netflix-local-r*`),
an `Optional` annotation on the second line of a collect-ignored spike test, and one
vestigial `_ROOT` branch. Local annotations ARE evaluated at runtime unless the module has
`from __future__ import annotations`, which is why the first two were real.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import pathlib

import pytest

_AGENT = pathlib.Path(__file__).resolve().parents[1]
_TOOL = _AGENT.parent / "scripts" / "undefined_names.py"


def _load():
    spec = importlib.util.spec_from_file_location("_undef_1203mc", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tool():
    assert _TOOL.exists(), "scripts/undefined_names.py is gone"
    return _load()


KNOWN = '''
import re
X = 1
def good(a):
    try:
        import json
        return json.dumps({"a": a, "x": X}) + re.escape("y")
    except Exception:
        return ""
def bad(a):
    try:
        return json.dumps({"a": a})
    except Exception:
        return ""
def invented(b):
    try:
        return join_capped_1203ki(b)
    except Exception:
        return ""
def comprehension(xs):
    try:
        return [y for y in xs if y]
    except Exception:
        return []
class K:
    def m(self, xs):
        try:
            return [self.f(x) for x in xs]
        except Exception:
            return []
    def f(self, x):
        return x
def closure(a):
    def inner():
        try:
            return a + 1
        except Exception:
            return 0
    return inner()
'''


def test_the_two_known_answers_and_nothing_else(tmp_path, tool):
    """★ Validated on known answers before being pointed at the tree."""
    p = tmp_path / "known.py"
    p.write_text(KNOWN, encoding="utf-8")
    names = sorted(n for _s, _l, n in tool.scan(str(p)))
    assert names == ["join_capped_1203ki", "json"], names


def test_self_and_free_variables_are_not_candidates(tmp_path, tool):
    """The two bugs the detector itself had: `self` inside a comprehension in a method is
    FREE, and a closure's captured name is free too. `is_free()` means defined."""
    p = tmp_path / "scopes.py"
    p.write_text(KNOWN, encoding="utf-8")
    reported = {n for _s, _l, n in tool.scan(str(p))}
    assert "self" not in reported and "a" not in reported and "x" not in reported


def test_a_module_level_import_counts_as_defined(tmp_path, tool):
    p = tmp_path / "m.py"
    p.write_text("import json\ndef f():\n    try:\n        return json.dumps({})\n"
                 "    except Exception:\n        return ''\n", encoding="utf-8")
    assert tool.scan(str(p)) == []


def test_a_syntax_error_is_not_a_finding(tmp_path, tool):
    p = tmp_path / "broken.py"
    p.write_text("def f(:\n", encoding="utf-8")
    assert tool.scan(str(p)) == []


def test_the_tree_has_no_undefined_names(tool):
    """★ THE RATCHET. Zero across the whole tree is what makes this a tripwire.

    A hit here is the shape that cost four occurrences in one session: the name does not
    exist, and if the reference sits in a `try` nobody will ever see the NameError.
    """
    pats = [str(_AGENT / "env_generator" / "**" / "*.py"),
            str(_AGENT / "tests" / "**" / "*.py"),
            str(_AGENT.parent / "tests" / "**" / "*.py"),
            str(_AGENT.parent / "scripts" / "*.py")]
    files = [f for pat in pats for f in glob.glob(pat, recursive=True)
             if "__pycache__" not in f]
    assert len(files) > 1000, "the sweep stopped seeing the tree (%d files)" % len(files)
    hits = [(os.path.relpath(f, str(_AGENT)), line, scope, name)
            for f in files for scope, line, name in tool.scan(f)]
    assert hits == [], "names nothing defines:\n" + "\n".join(map(str, hits))


# --- #1203md/#1203me: star imports ---------------------------------------------------
# Without this the delivered `main.py` is unscannable: 205 of the 227 delivered ones do
# `from models import *`, and symtable cannot know what that defines, so every ORM class came
# back undefined — 1328 candidates, almost all `User`/`Post`. Resolving the sibling module
# turned that into 203, and the names that were left were real: `_sys` (#1203md) and a `user`
# a projected handler never took (#1203me).

STAR_MODELS = '''
from sqlalchemy import Column
class User: pass
class Post: pass
_private = 1
TABLE_COUNT = 2
'''

STAR_MAIN = '''
from models import *
def handler():
    try:
        return User(), Post(), TABLE_COUNT, Column
    except Exception:
        return None
def broken():
    try:
        return Widget()
    except Exception:
        return None
def also_broken():
    try:
        return _private
    except Exception:
        return None
'''


def _star_tree(tmp_path, main=STAR_MAIN, models=STAR_MODELS):
    (tmp_path / "models.py").write_text(models, encoding="utf-8")
    p = tmp_path / "main.py"
    p.write_text(main, encoding="utf-8")
    return p


def test_a_star_import_resolves_the_siblings_names(tmp_path, tool):
    """★ The two known answers again: an undefined name, and one `import *` does not export."""
    p = _star_tree(tmp_path)
    assert sorted(n for _s, _l, n in tool.scan(str(p))) == ["Widget", "_private"]


def test_the_siblings_own_imports_come_through(tmp_path, tool):
    """`Column` reaches main.py only because models.py imported it — `import *` re-exports."""
    p = _star_tree(tmp_path)
    assert "Column" not in {n for _s, _l, n in tool.scan(str(p))}


def test_an_all_list_is_honoured(tmp_path, tool):
    """With `__all__`, only those names are exported — `Post` is then undefined in main."""
    models = STAR_MODELS + '\n__all__ = ["User"]\n'
    p = _star_tree(tmp_path, models=models)
    reported = {n for _s, _l, n in tool.scan(str(p))}
    assert "Post" in reported and "User" not in reported


def test_a_missing_sibling_contributes_nothing(tmp_path, tool):
    """No models.py: the scan stays where it was rather than inventing bindings."""
    p = tmp_path / "main.py"
    p.write_text(STAR_MAIN, encoding="utf-8")
    reported = {n for _s, _l, n in tool.scan(str(p))}
    assert {"User", "Post", "Widget"} <= reported


# --- composition: the PROJECTED backend, end to end ----------------------------------
# #1203l9's rule: patches that land on one output need a test that renders that output
# once. Four did on 2026-10-15 (three of them covered here -- see the note below) — #1203md (an unbound `_sys` in the seed-shortfall report),
# #1203me (a `user` a projected handler never took), #1203mf (a bare `text(` in #803's
# label read) and #1203mg (unreachable statements after an action stub, reading an unbound
# `valid`). Each has its own tests; this one renders a backend that exercises all four
# shapes at once and requires the instrument to find nothing.

_COMPOSITION_ENDPOINTS = [
    {"method": "GET", "path": "/api/titles/{id}", "metadata": {"response_key": "item"}},
    {"method": "POST", "path": "/api/posts", "metadata": {"response_key": "item"},
     "auth_required": True},
    {"method": "POST", "path": "/api/posts/{id}/repost", "metadata": {},
     "auth_required": True},
    {"method": "GET", "path": "/api/posts", "metadata": {"response_key": "items"}},
]

_COMPOSITION_TABLES = {
    # titles + genres + the link table give #803 its label read
    "titles": {"columns": [{"name": "id", "type": "serial primary key"},
                           {"name": "name", "type": "text"}]},
    "genres": {"columns": [{"name": "id", "type": "serial primary key"},
                           {"name": "name", "type": "text"}]},
    "title_genres": {"columns": [{"name": "id", "type": "serial primary key"},
                                 {"name": "title_id", "type": "integer references titles(id)"},
                                 {"name": "genre_id", "type": "integer references genres(id)"}]},
    "users": {"columns": [{"name": "id", "type": "serial primary key"},
                          {"name": "email", "type": "text"}]},
    "posts": {"columns": [{"name": "id", "type": "serial primary key"},
                          {"name": "user_id", "type": "integer references users(id)"},
                          {"name": "body", "type": "text"}]},
}


def test_a_freshly_projected_backend_has_no_undefined_names(tmp_path, tool):
    """★ The forward state for #1203md/me/mf/mg at once, on the real rendered output."""
    from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
        write_backend_skeleton)

    (tmp_path / "app" / "backend").mkdir(parents=True)
    write_backend_skeleton(tmp_path, _COMPOSITION_ENDPOINTS, _COMPOSITION_TABLES)
    files = [f for f in (tmp_path / "app" / "backend").rglob("*.py")
             if "__pycache__" not in str(f)]
    assert len(files) >= 3, "the skeleton rendered almost nothing (%d files)" % len(files)
    hits = [(f.name, line, scope, name)
            for f in files for scope, line, name in tool.scan(str(f))]
    assert hits == [], "the projected backend reads names nothing binds:\n" + "\n".join(
        map(str, hits))


def test_the_composition_actually_exercises_all_four_shapes(tmp_path):
    """A clean scan is only evidence if the four shapes are present to be scanned."""
    from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import (
        write_backend_skeleton)

    (tmp_path / "app" / "backend").mkdir(parents=True)
    write_backend_skeleton(tmp_path, _COMPOSITION_ENDPOINTS, _COMPOSITION_TABLES)
    main = (tmp_path / "app" / "backend" / "main.py").read_text(encoding="utf-8")
    seed = (tmp_path / "app" / "backend" / "seed_data.py").read_text(encoding="utf-8")
    assert "_verify_seed_counts_1202r" in seed, "#1203md's function is not in the render"
    assert "_labels = {}" in main, "#1203mf's label read is not in the render"
    assert "action endpoint not implemented" in main, "#1203mg's stub is not in the render"
    assert "_fw_upsert_on_conflict" in main, "the conflict path is not in the render"
    # ★ WHAT THIS COMPOSITION DOES NOT COVER, and why, because a clean scan that silently
    # misses a shape is worse than no claim. #1203me needs the conflict path in a handler
    # that does NOT bind `user`, i.e. a PUBLIC owner-scoped write — and that combination is
    # nearly unreachable from tables alone: #566u enables the upsert exactly for the
    # owner-FK-plus-subject-FK shape, and #1202vt/#598 read that same shape as per-user
    # private and project an actor onto it, overriding an explicit `auth_required: False`
    # (the render says so out loud: "SHAPE OVERRODE AN EXPLICIT PUBLIC"). It takes MATERIALS
    # declaring the entity public to get there, which `write_backend_skeleton` does not take
    # here — and that is why #1203me shows in only 3 delivered runs. Mutation confirmed the
    # gap rather than my reading it: reverting #1203me came back MISSED here while its own
    # test (`test_1203me_…`, the invariant over both values of `auth`) CAUGHT it 3/3.
