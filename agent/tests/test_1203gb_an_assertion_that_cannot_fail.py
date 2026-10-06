"""#1203gb -- a ratchet against assertions that cannot fail.

Six tests in this suite asserted nothing while reporting as passes. Five of them were the same
shape: the author wanted to say "this call must not raise" or "for reference only", wrote it as
`assert <real check> or True`, and the `or True` made the whole line a no-op that LOOKS like a
check. Two of the five sat under test names that promised the thing they had stopped checking
(`test_a_free_port_is_not_reported_blocked` bound a socket and asserted nothing;
`test_..._classifier_not_called_on_pass` was a bare `assert True`).

This is the failure mode #1202hl and #943 are about, one level up: a green test that proves
nothing. It is invisible in a suite report -- 20291 passes look identical whether or not six of
them are empty -- so it needs a structural check, which is what this file is.

What to write instead, by intent:
  * "must not raise"      -> assert the type or value that comes back
  * "for reference only"  -> `pytest.skip(<why nothing here can fail>)`, so the suite says so
  * "superseded by the AST check below" -> delete the line; the real check already stands
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def _truthy_constant(node: ast.AST) -> bool:
    """A literal that `assert` can never reject: True, 1, a non-empty string."""
    return isinstance(node, ast.Constant) and bool(node.value) is True


def vacuous_asserts_1203gb(tree: ast.AST):
    """Every `assert` in `tree` whose outcome is fixed by its own syntax.

    Two shapes, both decidable without running anything:
      1. the test IS a truthy literal -- `assert True`, `assert 1`, `assert "note"`
      2. the test is an `or` chain with a truthy literal anywhere in it -- the chain
         short-circuits to that literal, so no operand's value can fail the line

    Deliberately NOT flagged: `assert f(x) == f(x)`. That shape reads as vacuous but is how this
    suite pins determinism (same input, same output, called twice), and it fails for real when a
    helper starts carrying state. An earlier sweep of mine flagged 16 of those and all 16 were
    legitimate -- the predicate, not the tests, was wrong.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        if _truthy_constant(test):
            found.append((node.lineno, "the assert's test is a truthy literal"))
        elif isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            if any(_truthy_constant(v) for v in test.values):
                found.append((node.lineno, "an `or <truthy literal>` makes the whole assert true"))
    return found


def test_no_test_in_the_suite_asserts_something_unfalsifiable():
    offenders = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for lineno, why in vacuous_asserts_1203gb(tree):
            offenders.append("%s:%d -- %s" % (path.relative_to(TESTS_DIR), lineno, why))
    assert not offenders, (
        "These assertions pass no matter what the code does. See this file's docstring for what "
        "to write instead:\n  " + "\n  ".join(offenders)
    )


# --- the ratchet's own power, pinned on the six lines it was built from -------------------------
# Each string below is a line that really shipped in this suite. If the predicate stops catching
# one, the counter-test goes red rather than the ratchet quietly going blind.

_THE_SIX_AS_SHIPPED = (
    'assert True',
    'assert o2._fwdeliver_stuck_count >= 3 or True',
    'assert isinstance(first, ast.Assign) or isinstance(first, ast.If) or True',
    'assert X.check_app_env_contract(r) == [] or True',
    'assert "_worst942" in src and "similarity_live" in src.split("_w")[0][-600:] or True',
    'assert 1',
)


def test_the_predicate_catches_each_shape_that_shipped():
    for src in _THE_SIX_AS_SHIPPED:
        assert vacuous_asserts_1203gb(ast.parse(src)), src


def test_the_predicate_leaves_real_assertions_alone():
    for src in (
        'assert x == y',
        'assert isinstance(n, int)',
        'assert a or b',                      # two real operands: either can be falsy
        'assert _pick(u, "a") == _pick(u, "a")',   # the determinism shape, deliberately allowed
        'assert x or ""',                     # falsy literal cannot rescue the line
        'assert x, "or True"',                # only in the message
    ):
        assert not vacuous_asserts_1203gb(ast.parse(src)), src
