#!/usr/bin/env python
"""#1203pg: rank tests by how much of their assertion weight is SOURCE TEXT, not behaviour.

Why this exists. On 2026-10-19 four guards were mutation-tested in one batch and the ratio
predicted every outcome: `test_fwval_early_return_checklist_502.py` (a pure predicate, ratio
0.00) caught 4 of 4, while `test_redispatch_nags_without_cloning_794.py` (0.95),
`test_the_visual_defer_check_that_failed_open_888.py` (1.00) and
`test_the_kickoff_guard_that_failed_open_882.py` (1.00) missed 7 real defects between them.

The shape is always the same: an assertion written as `"<line of code>" in getsource(mod)` is
satisfied by the line EXISTING. A mutation that keeps the line and makes it unreachable -- or
inverts the branch around it -- reads identical to working code. A test that never calls the
thing it names cannot see a behaviour change at all.

Worst combination, and it is worth looking for by name: a guard that FAILS OPEN whose assertions
are all source text. Its entire subject is what happens on an error, and nothing drives the error.

#943: this reports a RATIO, never a verdict. A high ratio is a reason to write a
behaviour-preserving-text mutation, not evidence of a defect -- some properties (a comment that
must carry a correction, a default that must stay spelled a certain way) are honestly textual.

THE DETECTOR VALIDATES ITSELF, and that is not decoration. Its first version missed the
transitive step: `s = _src()` where `_src()` returns `inspect.getsource(...)` left `s` unmarked,
because `_src()` does not match the source-text pattern. It scored #794 at 0.05 against a hand
count of 18/19 and reported "only 7 tests are entirely source-text".

That headline figure then moved TWICE more as two further detector bugs were fixed, and every
move was toward fewer false positives: 7 (missed the transitive step) -> 105 (a FIXTURE read
counted as a source read) -> 64 (a text name spelled inside a STRING leaked and cascaded) ->
32 (source that is EVALUATED is driven, not read) -> 9 (names were matched WITHOUT SCOPE, so a
loop variable in one test poisoned another that reused the letter).

The sixth was the widest in SCOPE and the narrowest in yield, which is worth separating: only
`ast.Assert` was counted, so all 637 `unittest.TestCase` files -- 27% of this repo's tests --
scored (0, 0) and were dropped by the `min_asserts` filter. Ranked files went 1722 -> 2303, and
the 581 newly visible files produced exactly TWO candidates at ratio 1.00, both migration tests
whose subject really is the source text. A blind spot can be large and still be empty; finding
that out is the only way to know which.

Worth being precise about what that means. At the point the ranking was first used it was
over-reporting by roughly 3.5x -- and it still RANKED correctly: every file taken from the top
of it (#794 at 0.95, #882 and #888 at 1.00) turned out to hold real gaps, 17 of which were
closed and each confirmed by mutation. A noisy ORDER can still be a useful order. The absolute
count is not written down anywhere (#1202vs: each copy is a liability); run the tool.

`--check` therefore re-measures cases whose answers are known BY CONSTRUCTION, written in this
file. The first version anchored on two real files' hand-counted ratios instead, and those rotted
within the hour -- adding the behavioural tests that #1203pg's own finding called for moved 18/19
to 18/27 and 0/7 to 0/10, so the check failed on correct work. #1203oa: a parked measurement
rots. A synthetic case cannot. Run `--check` before trusting any ranking this prints.
"""
import argparse
import ast
import copy
import pathlib
import re
import sys

# A read counts as SOURCE text only when the same expression also names a source LOCATOR.
# Found by the constructed self-test below, which is the whole reason it exists: the first
# version matched `.read()` on its own, so `open("fixture.json").read()` -- a test reading its
# own DATA -- landed in the text bucket and inflated every ratio in the ranking.
_STRONG = re.compile(r"getsource|getdoc")
_READ = re.compile(r"read_text|\.read\(\)|open\(")
_SRC_LOCATOR = re.compile(r"getfile|__file__|inspect\.|\.py[\'\"]|_SRC\b|_PATH\b")


def _is_text_expr(expr):
    if _STRONG.search(expr):
        return True
    return bool(_READ.search(expr)) and bool(_SRC_LOCATOR.search(expr))

# Cases whose answer is known BY CONSTRUCTION. Each is (source, expected_text, expected_total).
# The three-hop case is the bug the first version had, kept as a permanent regression case.
_SELF_TEST = (
    ("three hops from getsource to the asserted name", """
import inspect
def _src():
    return inspect.getsource(object)
def test_a():
    s = _src()
    blk = s[0:40]
    assert "x" in blk
""", 1, 1),
    ("a behavioural assert is not text", """
def test_b():
    assert add(1, 1) == 2
    assert add(2, 2) == 4
""", 0, 2),
    ("a mixed file is scored as mixed", """
import inspect
def test_c():
    assert "def add" in inspect.getsource(add)
    assert add(1, 1) == 2
""", 1, 2),
    ("reading a FIXTURE is data, not source", """
def test_d():
    rows = open("fixture.json").read()
    assert len(rows) > 0
""", 0, 1),
    ("a unittest assertion is counted at all", """
import unittest
class T(unittest.TestCase):
    def test_a(self):
        self.assertEqual(add(1, 1), 2)
        self.assertIn("x", render())
""", 0, 2),
    ("a unittest assertion ON SOURCE is counted as source", """
import inspect, unittest
class T(unittest.TestCase):
    def test_a(self):
        src = inspect.getsource(add)
        self.assertIn("def add", src)
""", 1, 1),
    ("an assertion MESSAGE is not the thing asserted", """
import inspect, unittest
class T(unittest.TestCase):
    def test_a(self):
        self.assertEqual(add(1, 1), 2, "we used to read this with getsource")
""", 0, 1),
    ("a STRING that spells a source pattern is not source", """
def test_i():
    msg = "we read it with inspect.getsource in the old version"
    assert msg.startswith("we read")
""", 0, 1),
    ("a name is scoped to the function that binds it", """
import inspect
def test_a():
    src = inspect.getsource(object)
    i = src.index("x")
    assert "def" in src[i:]
def test_b():
    out = reasons([dict(EP, id="n%d" % i) for i in range(3)])
    assert len(out) == 3
""", 1, 2),
    ("source that is EVALUATED is driven, not read", """
import inspect
def test_h():
    g = inspect.getsource(guard)
    assert bool(eval(g, {}, {"x": 1})) is True
""", 0, 1),
    ("a text name spelled inside a STRING does not leak", """
import inspect
def test_g():
    src = inspect.getsource(object)
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)]
    wh = _WH([{"title": "the logged-out page calls an auth-required endpoint"}])
    assert len(wh.created) == 1
""", 0, 1),
    ("getdoc counts, and so does a name derived from it", """
import inspect
def test_e():
    d = inspect.getdoc(add)
    assert "blocks delivery" in d
""", 1, 1),
)

# A property of two real files that does NOT rot as tests are added: a detector that marks
# everything, or nothing, fails these whatever the counts have grown to.
_SHAPE = {
    "test_fwval_early_return_checklist_502.py": "pure",   # a pure predicate: no text asserts
    "test_redispatch_nags_without_cloning_794.py": "mixed",  # both kinds, since #1203pg
}

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TEST_DIRS = ("agent/tests", "tests")


def _returns_text(node):
    """A function whose own `return` reads source text."""
    return any(isinstance(b, ast.Return) and b.value is not None
               and _is_text_expr(_code_text(b.value)) for b in ast.walk(node))


def _propagate(scope, names):
    """Grow `names` over the assignments in ONE scope, to a fixed point."""
    names = set(names)
    for _ in range(8):                      # bounded: the graph is tiny and must not spin
        before = len(names)
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign) and node.value is not None:
                if _mentions(node.value, names):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
        if len(names) == before:
            break
    return names


def _text_names(tree, scope=None):
    """Names holding source TEXT, resolved PER SCOPE.

    Scope is the fourth thing this detector got wrong, and the subtlest. The propagation used to
    run over the whole module and keyed on the NAME, so a short identifier in one test function
    poisoned a different function that happened to reuse it. In
    `test_1203g3_the_reason_was_computed_and_dropped.py` one test does `i = src.index(...)` --
    `i` genuinely holds a source offset -- and another does
    `out = reasons([dict(_EP, id="impl.endpoint.%d" % i) for i in range(5)])`, where `i` is a
    COMPREHENSION variable. That marked `out`, and every assertion in the file is about `out`,
    which is the return value of the function under test. 0.90 for a fully behavioural file.
    """
    module_names = {n.name for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and _returns_text(n)}
    # module-level assignments are visible everywhere
    top = ast.Module(body=[s for s in tree.body if isinstance(s, ast.Assign)], type_ignores=[])
    module_names = _propagate(top, module_names)
    if scope is None:
        return module_names
    return _propagate(scope, module_names)


class _BlankStrings(ast.NodeTransformer):
    """Replace every string constant with `""`, so a literal cannot look like code."""

    def visit_Constant(self, node):          # noqa: N802 — ast's own naming
        if isinstance(node.value, str):
            return ast.copy_location(ast.Constant(value=""), node)
        return node


def _code_text(node):
    """`ast.unparse(node)` with string CONTENTS blanked.

    The third detector bug lived here. `_is_text_expr` ran a regex over the raw unparse, so a
    docstring or message that happened to spell `getsource` counted as code -- the same mistake
    #1203ph fixed in `test_1202eu`'s scanner, two hours earlier, in this same session.
    """
    try:
        return ast.unparse(_BlankStrings().visit(copy.deepcopy(node)))
    except Exception:
        return ast.unparse(node)


def _names_in(node):
    """The identifiers an expression actually REFERENCES.

    The second half of the third bug, and the worse half: matching a text name as a WORD
    against the unparsed text meant a common identifier leaked through string contents. In
    `test_1202z0` the chain ran `src` -> `tree` -> `fn` -> `calls` (all genuinely source-derived),
    and then `wh = _WH([{"title": "... calls an auth-required endpoint ..."}])` picked up `calls`
    FROM INSIDE A STRING, which marked `wh`, which marked `d = wh.created[0]["description"]`.
    Every one of that file's 18 assertions was then counted as source text, when the file is one
    of the most behavioural in the directory -- it builds a fake WorkHub and asserts on the task
    it created. Comparing `ast.Name` ids cannot do that.
    """
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(n.name)
    return out


def _executes_source(node):
    """Does this expression EXECUTE extracted source rather than read it?

    `test_1202kn` is why this exists: it lifts the shipped guard expression out of the
    orchestrator with `getsource` and then `eval`s it against fake gate objects. Every name in
    sight is source-derived, so the file ranks 1.00 -- yet its mutations came back 2 of 2
    CAUGHT, because evaluating the guard IS driving it. Reading source and running source are
    opposite things and must not score the same.
    """
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") in ("eval", "exec"):
            return True
    return False


def _mentions(node, names):
    """Does this expression read source text, or a name that holds some?"""
    if _executes_source(node):
        return False
    if _is_text_expr(_code_text(node)):
        return True
    return bool(_names_in(node) & names)


_ASSERT_METHOD = re.compile(r"^assert[A-Z]")


def _assertions(scope):
    """Every assertion in `scope`, as (node, expression-to-classify) pairs.

    BOTH styles. Counting only `ast.Assert` was the sixth detector bug and the widest one:
    637 of this repo's 2363 test files are `unittest.TestCase` subclasses that assert through
    `self.assertEqual(...)` / `self.assertIn(...)`, so 27% of the suite scored (0, 0) and was
    dropped by the `total >= min_asserts` filter -- never ranked at all. Same shape as #1203ow,
    where twelve ratchets filtered by FILE NAME and so could not see the three modules holding
    the top blockers: a filter keyed on spelling rather than on role.

    For a method call the expression to classify is the ARGUMENTS minus any string literal,
    which is the assertion's message -- prose about the check, not part of it.
    """
    out = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Assert):
            out.append((node, node.test))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and _ASSERT_METHOD.match(node.func.attr or "")):
            args = [a for a in node.args
                    if not (isinstance(a, ast.Constant) and isinstance(a.value, str))]
            probe = args or list(node.args)
            out.append((node, ast.Tuple(elts=probe, ctx=ast.Load()) if probe
                        else ast.Constant(value=True)))
    return out


def ratio(path):
    """``(text_asserts, total_asserts)`` for one test file, or None if it will not parse."""
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return None
    return _count(tree)


def _count(tree):
    module_names = _text_names(tree)
    scopes = [n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    owner = {}
    for s in scopes:
        for node, _ in _assertions(s):
            cur = owner.get(id(node))
            if cur is None or s.lineno > cur.lineno:
                owner[id(node)] = s
    cache = {}
    total = text = 0
    for node, probe in _assertions(tree):
        total += 1
        s = owner.get(id(node))
        if s is None:
            names = module_names
        else:
            if id(s) not in cache:
                cache[id(s)] = _text_names(tree, s)
            names = cache[id(s)]
        if _mentions(probe, names):
            text += 1
    return text, total


def _rows(min_asserts):
    out = []
    for d in _TEST_DIRS:
        for p in sorted((_ROOT / d).glob("test_*.py")):
            r = ratio(p)
            if not r:
                continue
            text, total = r
            if total >= min_asserts:
                out.append((text / total, text, total, p))
    out.sort(key=lambda r: (-r[0], -r[2]))
    return out


def _ratio_of_source(text):
    """`ratio()` against a source string, for the self-test."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(text)
        tmp = fh.name
    try:
        return ratio(pathlib.Path(tmp))
    finally:
        pathlib.Path(tmp).unlink()


def check():
    """Validate the detector. Returns the failures; empty means it holds."""
    bad = []
    for label, text, want_text, want_total in _SELF_TEST:
        got = _ratio_of_source(text)
        if got != (want_text, want_total):
            bad.append("%s: expected %d/%d by construction, detector says %s"
                       % (label, want_text, want_total, got))
    for name, shape in _SHAPE.items():
        hits = [p for d in _TEST_DIRS for p in (_ROOT / d).glob(name)]
        if not hits:
            bad.append("%s: not found -- re-anchor this check or drop it" % name)
            continue
        got = ratio(hits[0])
        if not got or got[1] == 0:
            bad.append("%s: no assertions found" % name)
            continue
        text, total = got
        if shape == "pure" and text != 0:
            bad.append("%s: a pure predicate test should have 0 text asserts, got %d/%d"
                       % (name, text, total))
        if shape == "mixed" and not 0 < text < total:
            bad.append("%s: expected BOTH kinds of assert, got %d/%d" % (name, text, total))
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--min-asserts", type=int, default=4)
    ap.add_argument("--min-ratio", type=float, default=1.0)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--check", action="store_true",
                    help="only re-measure the hand-counted files; exit 1 if either moved")
    args = ap.parse_args(argv)

    bad = check()
    for line in bad:
        print("DETECTOR FAILED: %s" % line)
    if args.check:
        if not bad:
            print("detector holds: %d constructed case(s) + %d real-file shape(s)"
                  % (len(_SELF_TEST), len(_SHAPE)))
        return 1 if bad else 0
    if bad:
        print("\nrefusing to rank: a detector that cannot reproduce a hand count is not evidence.")
        return 1

    rows = _rows(args.min_asserts)
    hi = [r for r in rows if r[0] >= args.min_ratio]
    print("%d test(s) with >=%d asserts; %d at ratio >=%.2f"
          % (len(rows), args.min_asserts, len(hi), args.min_ratio))
    print()
    for r, text, total, p in hi[:args.limit]:
        print("  %.2f  %2d/%2d  %s" % (r, text, total, p.relative_to(_ROOT)))
    if len(hi) > args.limit:
        print("  ... and %d more not shown (#1034)" % (len(hi) - args.limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
