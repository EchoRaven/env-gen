#!/usr/bin/env python3
"""Names a scope references but nothing defines — the NameError a `try` turns into silence.

#1203mc. On 2026-10-15 I reached for a name that did not exist FOUR times in one session:
`json.dumps` in a module that never imported json, `os.path` likewise, an invented
`join_capped_1203ki`, and a missing `import ast` in a test. The first three sat inside
`try: ... except Exception: <fallback>`, so the NameError became a silent downgrade and
`py_compile` passed every time — compilation does not resolve names.

WHY `symtable` AND NOT AN AST NAME SET. I wrote the AST version first and bent it twice;
the candidate count went 254 -> 605 and the single most common "undefined name" was `self`.
A top hit of `self` is the detector being wrong, not the tree. Scope in Python is not a set
of strings: a name can be bound by a comprehension, a lambda, an enclosing function (free),
a `global` declaration, a walrus, an except-as, or a nested def's own name. `symtable`
computes the scopes CPython computes, so none of that has to be re-derived — and the one
filter that still matters is that `is_free()` means BOUND IN AN ENCLOSING SCOPE, i.e.
defined. Treating free names as candidates is what produced the 79 `self` hits.

Validated against a fixture with two known answers before being pointed at anything: it
reports exactly the unimported `json` and the invented name, and nothing from a sibling
function that imports json properly or from a comprehension variable.

MEASURED when it landed: 0 candidates across 267 framework modules, and 3 in 2319 test and
script files -- a vestigial `_ROOT` branch guarded by `"_ROOT" in globals()` (harmless), a
`Dict` annotation behind an early `pytest.skip` that always fired (a latent NameError, fixed
with the tripwire that hid it), and an `Optional` annotation on the second line of a
collect-ignored spike test (fixed). Local annotations are EVALUATED at runtime unless the
module has `from __future__ import annotations`, which is why those two were real.

Usage:
    scripts/undefined_names.py <file.py> [more.py ...]
    scripts/undefined_names.py $(git ls-files '*.py')
Exit code is 1 when anything was reported.
"""
import builtins
import io
import symtable
import sys

_BUILTINS = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__class__", "__spec__", "__loader__",
    "__package__", "__builtins__", "__debug__", "__annotations__", "__dict__",
}


def _walk(table, out, module_globals):
    for sym in table.get_symbols():
        if not sym.is_referenced():
            continue
        # is_free(): bound in an ENCLOSING function scope. Defined, not a candidate.
        #
        # TWO OF THESE ARE REDUNDANT TODAY, and mutation said so rather than my reading it:
        # dropping `is_imported()` and dropping the `is_referenced()` guard above both came
        # back MISSED. Probed rather than assumed -- `symtable` marks a function-level
        # `import json` as BOTH imported and local, and a module-level one lands in
        # `module_globals`, so `is_local()` already covers it; an unreferenced symbol is
        # either assigned, a parameter, or imported, all of which are covered too. They are
        # kept because they state the intent and survive a future reordering of this test,
        # NOT because they are load-bearing -- a reader must not take their presence for
        # logic that fires.
        if (sym.is_assigned() or sym.is_imported() or sym.is_parameter()
                or sym.is_local() or sym.is_free()):
            continue
        name = sym.get_name()
        if name in module_globals or name in _BUILTINS:
            continue
        out.append((table.get_name(), table.get_lineno(), name))
    for child in table.get_children():
        _walk(child, out, module_globals)


def _star_import_names(path, src):
    """Top-level public names of every sibling module this one does `from X import *` on.

    #1203md: without this the delivered `main.py` is unscannable. 205 of the 227 delivered
    ones do `from models import *`, and symtable cannot know what that defines -- so every
    ORM class came back as undefined (1328 candidates, almost all `User`/`Post`). Resolving
    the sibling module turns that into signal: the one name in that noise which was NOT a
    model class was `_sys`, and it was a real NameError the delivered app swallowed.

    Only SIBLING modules are read, by their own top-level bindings, and only names that do
    not start with `_` (what `import *` actually exports absent `__all__`). An `__all__` list
    of plain strings is honoured when present. Any fault contributes nothing, which leaves
    the scan where it was rather than hiding a name.
    """
    import ast as _ast
    import os as _os
    out = set()
    try:
        tree = _ast.parse(src)
    except Exception:
        return out
    here = _os.path.dirname(_os.path.abspath(str(path)))
    for node in _ast.walk(tree):
        if not (isinstance(node, _ast.ImportFrom) and node.module
                and any(a.name == "*" for a in node.names)):
            continue
        sib = _os.path.join(here, node.module.replace(".", _os.sep) + ".py")
        if not _os.path.isfile(sib):
            continue
        try:
            sibsrc = io.open(sib, encoding="utf-8", errors="replace").read()
            sibtree = _ast.parse(sibsrc)
        except Exception:
            continue
        declared = None
        for n in sibtree.body:
            if isinstance(n, _ast.Assign) and any(
                    isinstance(t, _ast.Name) and t.id == "__all__" for t in n.targets):
                if isinstance(n.value, (_ast.List, _ast.Tuple)):
                    declared = {e.value for e in n.value.elts
                                if isinstance(e, _ast.Constant) and isinstance(e.value, str)}
        if declared is not None:
            out |= declared
            continue
        for n in sibtree.body:
            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                out.add(n.name)
            elif isinstance(n, _ast.Assign):
                out |= {t.id for t in n.targets if isinstance(t, _ast.Name)}
            elif isinstance(n, _ast.AnnAssign) and isinstance(n.target, _ast.Name):
                out.add(n.target.id)
            elif isinstance(n, (_ast.Import, _ast.ImportFrom)):
                for a in n.names:
                    if a.name != "*":
                        out.add((a.asname or a.name).split(".")[0])
    return {n for n in out if not n.startswith("_")}


def scan(path):
    """``[(scope_name, scope_lineno, undefined_name), ...]``; never raises on a syntax error."""
    try:
        src = io.open(path, encoding="utf-8", errors="replace").read()
        top = symtable.symtable(src, str(path), "exec")
    except Exception:
        return []
    module_globals = {s.get_name() for s in top.get_symbols()
                      if s.is_assigned() or s.is_imported() or s.is_namespace()}
    module_globals |= _star_import_names(path, src)       # #1203md
    out = []
    for child in top.get_children():
        _walk(child, out, module_globals)
    return out


def main(argv):
    found = 0
    for path in argv[1:]:
        for scope, line, name in scan(path):
            found += 1
            print("%s:%s  in %s()  -> %s" % (path, line, scope, name))
    if not found:
        print("no undefined-name candidates in %d file(s)" % (len(argv) - 1))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
