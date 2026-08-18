r"""#940: three NameError-shaped seams in one session, and nothing in the repo looks for them.

Every mistake I made today was at a boundary I introduced, never in a fix's logic:

    #930   `_head_sha`     used ~140 lines ABOVE its assignment
    #934   `shots_dir`     assigned only inside the `capture is None` branch
    #939   `fe`            the parameter is `frontend_dir`

The suite caught the first two — they sit on paths tests exercise. It could not catch the third:
no test drives the auth branch of `scaffold_pages_from_contract`, so 6351 passing tests said
nothing about a `NameError` on a line that executes **only when the defect it reports fires**.
That is the worst possible placement, and it is #910's own original mistake, repeated inside the
branch #910b added to report it.

The tool for this class exists everywhere else — pyflakes F821, ruff F821 — and this repo has
neither configured nor installed, and no egress to install one. So: a conservative AST scan,
written to MISS rather than to false-positive.

It found exactly one real thing on its first full run: `agents/runtime/messaging.py` used `Any`
in its `TYPE_CHECKING` block and never imported it. Harmless today (PEP 563 makes annotations
strings) and a live `NameError` the moment anything calls `get_type_hints` or the `__future__`
import goes away. Fixed rather than allowlisted.
"""
import ast
import builtins
import pathlib

import pytest


_EXTRA_BUILTINS = {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    # `__builtins__` is present in every module's globals at runtime but is not in dir(builtins).
    "__builtins__",
}
_BUILTINS = set(dir(builtins)) | _EXTRA_BUILTINS

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "env_generator"


def _bound_in(node):
    """Every name this scope binds. Over-approximates deliberately: a miss is a quiet pass, a
    false positive is a broken build for everyone."""
    out = set()

    def add_args(a):
        if not a:
            return
        for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs):
            out.add(x.arg)
        if a.vararg:
            out.add(a.vararg.arg)
        if a.kwarg:
            out.add(a.kwarg.arg)

    def targets(t):
        if isinstance(t, ast.Name):
            out.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                targets(e)
        elif isinstance(t, ast.Starred):
            targets(t.value)

    add_args(getattr(node, "args", None))
    for n in ast.walk(node):
        # ★ nested defs and lambdas bind their OWN params, and walking the outer body sees those
        # loads. Without this the scan reported 315 hits, ~all of them inner-function arguments.
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            add_args(n.args)
        if isinstance(n, ast.Assign):
            for t in n.targets:
                targets(t)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
            targets(n.target)
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            targets(n.target)
        elif isinstance(n, ast.withitem) and n.optional_vars is not None:
            targets(n.optional_vars)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                out.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
    return out


def _module_bindings(tree):
    """Module-scope names only — PRUNED at every function and class body.

    ★ The first version used `_bound_in(tree)`, which walks the whole module and therefore
    harvested every function's locals as if they were globals. `frontend_scaffold` has eight
    functions containing `fe = Path(frontend_dir)`, so `fe` read as a module global and the guard
    passed on the very seam it was written for (#939, planted back as a control). A guard nobody
    has watched fail is a guess.
    """
    out = set()
    stack = list(tree.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)                      # the name binds; the BODY does not escape
            continue
        if isinstance(n, ast.Assign):
            for t in n.targets:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name):
                        out.add(x.id)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
            for x in ast.walk(n.target):
                if isinstance(x, ast.Name):
                    out.add(x.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                out.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            for x in ast.walk(n.target):
                if isinstance(x, ast.Name):
                    out.add(x.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.withitem) and n.optional_vars is not None:
            for x in ast.walk(n.optional_vars):
                if isinstance(x, ast.Name):
                    out.add(x.id)
        for f in ("body", "orelse", "finalbody", "handlers", "items"):
            stack.extend(getattr(n, f, []) or [])
    return out


def unbound_loads(tree):
    """(line, name, function) for every Load of a name no enclosing scope binds."""
    module = _module_bindings(tree) | _BUILTINS
    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    hits = []
    for f in funcs:
        scope = module | _bound_in(f)
        for g in funcs:                      # closures: every enclosing function's bindings
            if g is not f and g.lineno <= f.lineno and (f.end_lineno or 0) <= (g.end_lineno or 0):
                scope |= _bound_in(g)
        for n in ast.walk(f):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in scope:
                hits.append((n.lineno, n.id, f.name))
    return hits


def _scan_repo():
    out = []
    for p in sorted(_ROOT.rglob("*.py")):
        if "test" in p.name:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for ln, name, fn in unbound_loads(tree):
            out.append(f"{p.relative_to(_ROOT)}:{ln} {name!r} in {fn}()")
    return out


# --------------------------------------------------------------------------- the guard

def test_no_unbound_names_in_the_package():
    """★ THE guard — the one that would have caught #939 when 6351 tests did not."""
    stray = _scan_repo()
    assert not stray, "possibly-unbound names:\n  " + "\n  ".join(stray)


def test_the_scanner_catches_the_three_seams_of_this_session():
    """★ Planted controls, one per shape. A guard nobody has seen fail is a guess."""
    cases = {
        "used before assignment in another branch": """
def f(flag):
    if flag:
        shots_dir = 1
    return shots_dir_typo
""",
        "wrong parameter name": """
def g(frontend_dir, comp):
    return helper(fe, comp)
""",
        "name from a sibling scope": """
def h():
    head = 1
def i():
    return head_sha
""",
    }
    for label, src in cases.items():
        assert unbound_loads(ast.parse(src)), f"missed: {label}"


def test_it_does_not_flag_the_ordinary(monkeypatch):
    """Non-false-positive cases, each of which the first draft got wrong."""
    ok = """
import os
from typing import Any
G = 1
def outer(a, *args, **kw):
    b = 2
    def inner(c):
        return a + b + c + G + os.sep
    for i in range(3):
        pass
    with open("x") as fh:
        pass
    try:
        pass
    except ValueError as exc:
        print(exc, i, fh)
    lam = lambda z: z + 1
    return [y for y in range(3)] + [lam(1)] + list(kw) + list(args)
class K:
    attr = 1
    def m(self):
        return self.attr
"""
    assert unbound_loads(ast.parse(ok)) == []


def test_a_global_declaration_is_respected():
    assert unbound_loads(ast.parse("def f():\n    global Z\n    return Z\n")) == []


def test_a_walrus_binds():
    assert unbound_loads(ast.parse("def f(xs):\n    if (n := len(xs)):\n        return n\n")) == []


def test_a_local_import_binds():
    assert unbound_loads(ast.parse("def f():\n    import json\n    return json.dumps({})\n")) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
