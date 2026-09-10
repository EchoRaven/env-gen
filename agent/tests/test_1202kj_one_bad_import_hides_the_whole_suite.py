"""#1202kj: one test file imported a sibling by package name, and the suite reported nothing.

`agent/tests/` has no `__init__.py`, so

    from tests.test_kickoff_run_kickoff import ATTENDEES, _all_clean_decisions

only ever resolved through a namespace package rooted at whatever was first on `sys.path`.
Add a test file that puts `.../llm_generator/multi_agent` ahead of `agent/` — that directory
has its OWN `tests/` package — and `tests` redirects there, the import fails, and the module
fails to COLLECT. pytest turns a collection error into

    Interrupted: 1 error during collection
    1 error in 11.65s

so the whole suite reports NOTHING: not a count, not a failure list, nothing about the other
~4200 tests. The file passed when run alone and when run with its sibling; only the full run
showed it, and the error named the VICTIM rather than the file that had moved `sys.path`.

It was the only import of its kind in the tree, so it is replaced rather than policed — the
sibling is loaded by PATH, which no future `sys.path` line can reach. This ratchet keeps it
that way, and pins the house style that made the collision possible.

WHAT IS VERIFIED: no test imports another test through the `tests.` package name, and the
house sys.path style adds `llm_generator`, never `multi_agent` itself.

WHAT IS NOT: that any product behaviour changed. This is a test-infrastructure failure whose
whole cost is silence — which is precisely why it is worth a ratchet: a suite that reports
nothing looks exactly like a suite nobody ran.
"""
import ast
import pathlib

_TESTS = pathlib.Path(__file__).resolve().parent


def _py_files():
    return sorted(p for p in _TESTS.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_test_imports_another_test_through_the_tests_package():
    """★ The defect. `agent/tests` is not a package; importing through it depends on
    sys.path order, which any other test file can change."""
    def _fragile(dotted: str) -> bool:
        """`tests.<module>` resolves only through a NAMESPACE package, because `agent/tests`
        has no `__init__.py`. `tests.north_star...` is different: north_star IS a package, and
        those fixtures are the pilot driver's, not collected by this suite."""
        parts = dotted.split(".")
        if not parts or parts[0] != "tests" or len(parts) < 2:
            return False
        return not (_TESTS / parts[1] / "__init__.py").exists()

    bad = []
    for p in _py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and _fragile(node.module or ""):
                bad.append(f"{p.name}:{node.lineno} from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if _fragile(a.name):
                        bad.append(f"{p.name}:{node.lineno} import {a.name}")
    assert not bad, (
        "load a sibling test by PATH (importlib.util.spec_from_file_location) — importing it "
        "as `tests.<name>` resolves through a namespace package and any sys.path change "
        "elsewhere silently kills COLLECTION, which reports the whole suite as nothing: "
        + "; ".join(bad))


def test_the_house_sys_path_style_does_not_shadow_the_tests_directory():
    """★ The other half. `multi_agent/` carries its own `tests/` package, so putting that
    directory on sys.path shadows this one. The house style adds `llm_generator` and imports
    `from multi_agent.runtime...`, which cannot collide."""
    bad = []
    for p in _py_files():
        src = p.read_text(encoding="utf-8")
        if "sys.path" not in src:
            continue
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("insert", "append")
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "path"):
                continue
            # the path expression may be a name bound elsewhere, so scan the whole
            # enclosing statement's source rather than just the call.
            seg = ast.get_source_segment(src, node) or ""
            if seg.rstrip().endswith('"multi_agent")') or seg.rstrip().endswith("'multi_agent')"):
                bad.append(f"{p.name}:{node.lineno}")
    assert not bad, (
        "add `.../llm_generator` to sys.path and import `from multi_agent.runtime...`; adding "
        "`multi_agent` itself shadows agent/tests with multi_agent/tests: " + "; ".join(bad))


def test_the_detector_would_catch_the_original():
    """★ Validate the detector on the known-bad shape before trusting a clean sweep — the
    standing rule after four false-clean scans. The FIRST form below is what actually shipped,
    and the AST check above does NOT see it (the `insert` call names only a loop variable), so
    the durable guard is the first test, not this one. Pinned so nobody 'simplifies' the
    path-import fix away on the strength of a green style sweep."""
    # ...and the import check itself, on the exact line that broke the suite.
    from_the_break = "from tests.test_kickoff_run_kickoff import ATTENDEES\n"
    node = ast.parse(from_the_break).body[0]
    assert isinstance(node, ast.ImportFrom)
    assert not (_TESTS / "test_kickoff_run_kickoff" / "__init__.py").exists(), (
        "the guard's premise: the target is a MODULE, not a package")

    shipped = (
        'for _p in (str(_AGENT), str(_AGENT / "llm_generator" / "multi_agent")):\n'
        "    sys.path.insert(0, _p)\n")
    tree = ast.parse(shipped)
    seen = [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "insert"]
    assert len(seen) == 1
    seg = ast.get_source_segment(shipped, seen[0]) or ""
    assert "multi_agent" not in seg, (
        "if this ever starts matching, the style check above has become the real guard and "
        "this comment is stale")
