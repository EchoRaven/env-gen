#!/usr/bin/env python3
"""Two-level static sweeps — because a one-level sweep misses whatever hides behind a helper.

Three times in one session an enumeration came back clean and was wrong, always the same way:

    #980   looked for `subprocess.run` INSIDE `async def`. Missed `_run_compose`, a helper
           that calls it — and that helper later froze the loop for 300 seconds.
    #992   looked for shape heuristics inside `repair_*` bodies. Missed
           `_is_fabricated_fallback_literal`, the helper the repair delegates to.
    #397   same scan, same blind spot, found on the second attempt only because I already
           knew the answer.

A direct-call AST walk answers "does this function do X". The question that matters is almost
always "does this function CAUSE X", and those differ by exactly one level of indirection.

    python3 tools/sweep_indirect.py blocking-in-async
    python3 tools/sweep_indirect.py heuristic-classifiers
    python3 tools/sweep_indirect.py --selftest
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from typing import Dict, List, Set, Tuple

REPO = pathlib.Path(__file__).resolve().parents[1]
SCAN_ROOT = REPO / "agent" / "env_generator" / "llm_generator"

BLOCKING_LEAVES = {
    "subprocess.run", "subprocess.check_output", "subprocess.call",
    "time.sleep", "requests.get", "requests.post", "urlopen",
}
SHAPE_TESTS = ("isupper", "islower", "isalpha", "isdigit", "istitle")


def _modules(root: pathlib.Path):
    for p in sorted(root.rglob("*.py")):
        try:
            yield p, ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue


def _sync_fns_calling(root, leaves: Set[str]) -> Dict[str, Set[str]]:
    """Sync functions that reach a blocking leaf directly. These are the HELPERS a one-level
    sweep cannot see through."""
    out: Dict[str, Set[str]] = {}
    for p, tree in _modules(root):
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and ast.unparse(n.func) in leaves:
                    out.setdefault(fn.name, set()).add(p.name)
    return out


def blocking_in_async(root=SCAN_ROOT) -> List[Tuple[str, str, str, int]]:
    """Async functions that block the event loop, directly OR through a sync helper."""
    helpers = _sync_fns_calling(root, BLOCKING_LEAVES)
    hits = []
    for p, tree in _modules(root):
        rel = str(p).split("llm_generator/")[-1]
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                full = ast.unparse(n.func)
                leaf = full.split(".")[-1]
                if full in BLOCKING_LEAVES:
                    hits.append((rel, fn.name, full + " [direct]", n.lineno))
                elif leaf in helpers and leaf not in ("run", "sleep", "get", "post"):
                    hits.append((rel, fn.name, leaf + "() [via helper]", n.lineno))
    return hits


def heuristic_classifiers(root=SCAN_ROOT) -> List[Tuple[str, str]]:
    """Boolean-returning functions that decide on STRING SHAPE. #992 was one of these: a
    rewrite driven by `isupper() and len>=4 and isalpha()` blanked every button label."""
    out = []
    for p, tree in _modules(root):
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            body = ast.unparse(fn)
            if not any(f".{s}()" in body for s in SHAPE_TESTS):
                continue
            if not any(isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
                       and isinstance(n.value.value, bool) for n in ast.walk(fn)):
                continue
            out.append((p.name, fn.name))
    return out


def selftest() -> int:
    tmp = REPO / "tools" / "_sweep_selftest_pkg"
    tmp.mkdir(exist_ok=True)
    (tmp / "m.py").write_text(
        "import subprocess, time\n"
        "def _helper(cmd):\n"
        "    return subprocess.run(cmd, timeout=300)\n"
        "async def caller():\n"
        "    return _helper(['x'])\n"
        "async def direct():\n"
        "    return subprocess.run(['y'])\n"
        "def _shape(s):\n"
        "    if s.isupper():\n"
        "        return True\n"
        "    return False\n",
        encoding="utf-8")
    try:
        hits = blocking_in_async(tmp)
        kinds = {k for _, _, k, _ in hits}
        # the whole point: the INDIRECT one must be found, not just the direct one
        assert any("via helper" in k for k in kinds), f"indirect call missed: {hits}"
        assert any("direct" in k for k in kinds), f"direct call missed: {hits}"
        assert len(hits) == 2, hits
        cls = heuristic_classifiers(tmp)
        assert ("m.py", "_shape") in cls, cls
        print("selftest OK")
        return 0
    finally:
        (tmp / "m.py").unlink(missing_ok=True)
        tmp.rmdir()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sweep", nargs="?", choices=["blocking-in-async", "heuristic-classifiers"])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.sweep:
        ap.error("pick a sweep or --selftest")

    if a.sweep == "blocking-in-async":
        hits = blocking_in_async()
        direct = [h for h in hits if "direct" in h[2]]
        indirect = [h for h in hits if "helper" in h[2]]
        print(f"blocking calls inside async def: {len(hits)} "
              f"({len(direct)} direct, {len(indirect)} via a helper)\n")
        print("NOTE: helper hits include name collisions — `execute()`/`wait()` are everywhere.")
        print("      Read the callee before believing any single row.\n")
        seen = set()
        for f, fn, kind, ln in hits:
            k = (f, kind)
            if k in seen:
                continue
            seen.add(k)
            print(f"   {f}:{ln}  async {fn}() -> {kind}")
    else:
        cls = heuristic_classifiers()
        print(f"boolean classifiers deciding on string shape: {len(cls)}\n")
        print("Ask of each: does it drive a DESTRUCTIVE action, and can legitimate input")
        print("look like the bad case? #992 was a rewrite that blanked every button label.\n")
        for f, fn in sorted(cls):
            print(f"   {f}: {fn}()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
