"""#1202wm: a method shaped like a mechanism must be called by something that is not a test.

`SystemMetrics` was constructed by the orchestrator on every run and never used. Six methods
-- record_token_usage, record_operation_time, record_retry and their getters -- had zero
production references, and its three stores appear in 0 of the corpus's 176 run directories.

That is worse than absent. Looking for where per-tool wall clock was kept, I found a store
that persists exactly the right shape (count / total / min / max per operation) and spent an
hour before noticing nothing ever wrote to it. A facility that looks available and is empty
costs a reader more than no facility.

The earlier dead-mechanism sweeps looked at module-level functions, so a dead METHOD slipped
through every one of them. This is that sweep, at method level, with the one criterion that
matters: references from `tests/` do not count. A recorder whose only caller is the test
proving it records is still dead.

Scope is deliberately narrow -- names that announce a mechanism (record_/check_/guard_/
detect_/ensure_/verify_/enforce_/audit_). A broad "unused method" rule would fire on API
surface, thin delegates and mixin hooks, and would be turned off within a week.
"""
import ast
import glob
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.join(_AGENT, "env_generator", "llm_generator")

sys.path.insert(0, _ROOT)

_MECHANISM = ("record_", "check_", "guard_", "detect_", "ensure_", "verify_",
              "enforce_", "audit_")


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def _names_used(paths):
    used = set()
    for f in paths:
        try:
            tree = ast.parse(_read(f))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                used.add(node.value)          # getattr("name") and tool registries
    return used


def _production_files():
    out = glob.glob(os.path.join(_ROOT, "**", "*.py"), recursive=True)
    for extra in ("tools", "utils"):
        out += glob.glob(os.path.join(_AGENT, extra, "**", "*.py"), recursive=True)
    return out


def _definition_files():
    """Where a mechanism may be DEFINED -- the same tree its uses are counted over.

    This scanned `env_generator/llm_generator` only while counting uses across `tools/` and
    `utils/` too, so a dead mechanism defined in either of those was invisible to it by
    construction. That is the partial-coverage flaw this sweep exists to catch, in the sweep
    itself; #1202wr came from the same mistake in a different sweep. Widened: 7 more
    mechanism methods come into scope, 0 of them dead today.
    """
    return _production_files()


def _mechanism_methods():
    """`{name: (file, lineno, class)}` for uniquely-named mechanism-shaped methods."""
    seen = {}
    dupes = set()
    for f in _definition_files():
        try:
            tree = ast.parse(_read(f))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for body in node.body:
                if not isinstance(body, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                name = body.name
                if name.startswith("__"):
                    continue
                if not any(name.lstrip("_").startswith(p) for p in _MECHANISM):
                    continue
                if name in seen:
                    dupes.add(name)          # an override pair proves nothing either way
                seen[name] = (f, body.lineno, node.name)
    return {k: v for k, v in seen.items() if k not in dupes}


def test_the_sweep_sees_mechanisms():
    """A ratchet over an empty scan is vacuous."""
    found = _mechanism_methods()
    assert len(found) >= 20, "the method scan found almost nothing: %d" % len(found)


def test_no_mechanism_method_is_called_only_by_its_test():
    used = _names_used(_production_files())
    dead = sorted(
        "%s.%s (%s:%d)" % (cls, name, os.path.basename(f), line)
        for name, (f, line, cls) in _mechanism_methods().items()
        if name not in used
    )
    assert not dead, (
        "these announce a mechanism and nothing in production calls them. Wire it, or "
        "remove it -- an empty facility that looks available costs a reader more than no "
        "facility (#1202wm). Dead: %r" % (dead,))
