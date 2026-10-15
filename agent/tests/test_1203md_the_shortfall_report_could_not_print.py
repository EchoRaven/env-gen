r"""#1203md: the seed-shortfall report raised NameError and the try swallowed it.

`_verify_seed_counts_1202r` exists because a per-row SAVEPOINT (#218) drops a bad row
silently, so a seeded table can hold fewer rows than the seed declares. Its own comment
measures that across 13 delivered stacks (r26 `continue_watching 8->1`, r30 `genres 10->0`,
…) and says the framework's older audit "has never run".

Neither did its one output line. `_sys` was never bound in that function — the only
`import sys as _sys` in the projected file sits inside `_seed_dbg` — so the moment `short`
was non-empty, `_sys.stderr.write` raised NameError and `except Exception: pass` ate it.
py_compile cannot catch that: compiling does not resolve names.

MEASURED: 110 of the 110 delivered `seed_data.py` carrying the function have the unbound
name (modern runs 38 of 38), and the message text appears in NO run log and no run `logs/`
— never emitted once. r161's backend lane grepped for `SEED SHORTFALL` and got nothing.
"""
from __future__ import annotations

import ast
import importlib.util
import io
import pathlib
import re
import sys
import tempfile
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.runtime.backend_skeleton import render_seed_data

_TOOL = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "undefined_names.py"

TABLES = {
    "users": {"columns": [{"name": "id", "type": "serial primary key"},
                          {"name": "email", "type": "text"}]},
    "posts": {"columns": [{"name": "id", "type": "serial primary key"},
                          {"name": "user_id", "type": "integer references users(id)"},
                          {"name": "body", "type": "text"}]},
}


@pytest.fixture(scope="module")
def rendered():
    return render_seed_data(TABLES)


def _fn_source(src, name):
    tree = ast.parse(src)
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(src, n)
    raise AssertionError("%s is not in the projected module" % name)


def test_the_projected_module_has_no_undefined_names(rendered, tmp_path):
    """The OUTPUT, scanned by the instrument — not the template's text."""
    spec = importlib.util.spec_from_file_location("_undef_md", _TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    p = tmp_path / "seed_data.py"
    p.write_text(rendered, encoding="utf-8")
    assert tool.scan(str(p)) == []


def test_the_function_binds_sys_in_its_own_scope(rendered):
    src = _fn_source(rendered, "_verify_seed_counts_1202r")
    tree = ast.parse(textwrap.dedent(src))
    imported = {(a.asname or a.name) for n in ast.walk(tree)
                if isinstance(n, ast.Import) for a in n.names}
    assert "_sys" in imported, "the report still reaches for a name this scope does not bind"


def test_the_shortfall_actually_prints(rendered, capsys, monkeypatch):
    """★ The load-bearing one: run the projected function and read stderr.

    An AST assertion would pass on an import that sits after the use, or inside the wrong
    branch. This executes the function with a db that reports FEWER rows than declared and
    requires the sentence to come out.
    """
    src = rendered
    ns: dict = {}

    class _Q:
        def __init__(self, n):
            self._n = n

        def count(self):
            return self._n

    class _DB:
        def query(self, cls):
            return _Q(1)          # one row landed...

    class _Models:
        pass

    for cls_name in ("User", "Post"):
        setattr(_Models, cls_name, type(cls_name, (), {}))

    ns["models"] = _Models
    ns["_ORDER"] = ["users", "posts"]
    ns["_CLASS"] = {"users": "User", "posts": "Post"}
    exec(compile(_fn_source(src, "_verify_seed_counts_1202r"), "<proj>", "exec"), ns)

    data = {"users": [{}, {}, {}], "posts": [{}, {}]}      # ...three and two declared
    ns["_verify_seed_counts_1202r"](_DB(), data)

    err = capsys.readouterr().err
    assert "SEED SHORTFALL (#1202r)" in err, (
        "the shortfall report is still silent; stderr was %r" % err)
    assert "users 3->1" in err and "posts 2->1" in err, err


def test_a_healthy_seed_says_nothing(rendered, capsys):
    """The other direction: no shortfall, no noise."""
    ns: dict = {}

    class _Q:
        def count(self):
            return 5

    class _DB:
        def query(self, cls):
            return _Q()

    class _Models:
        pass
    for cls_name in ("User", "Post"):
        setattr(_Models, cls_name, type(cls_name, (), {}))
    ns["models"] = _Models
    ns["_ORDER"] = ["users", "posts"]
    ns["_CLASS"] = {"users": "User", "posts": "Post"}
    exec(compile(_fn_source(rendered, "_verify_seed_counts_1202r"), "<proj>", "exec"), ns)
    ns["_verify_seed_counts_1202r"](_DB(), {"users": [{}], "posts": [{}]})
    assert "SEED SHORTFALL" not in capsys.readouterr().err


def test_it_still_never_raises(rendered):
    """#1202r's own promise: reports, never raises. A db that explodes must not propagate."""
    ns: dict = {}

    class _DB:
        def query(self, cls):
            raise RuntimeError("db gone")

    class _Models:
        pass
    setattr(_Models, "User", type("User", (), {}))
    ns["models"] = _Models
    ns["_ORDER"] = ["users"]
    ns["_CLASS"] = {"users": "User"}
    exec(compile(_fn_source(rendered, "_verify_seed_counts_1202r"), "<proj>", "exec"), ns)
    ns["_verify_seed_counts_1202r"](_DB(), {"users": [{}, {}]})      # must not raise
