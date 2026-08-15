r"""#772: "kept in sync via grep" is not a mechanism. Make the drift fail the suite.

#764's root cause was a classification duplicated by hand: `repair_dead_nav_links`' docstring
said *"Classification mirrors ``dead_nav_link_remediation``"*, #690 taught one copy and not the
other, and nothing could notice — the two live in different modules and no test crossed them.
The damage was real: `/watch/` and `/title/` rewritten to `/tenants` in four components.

So the CLASS was swept: 20 places in the tree declare that they are kept identical to something
else. Most are prose references to a line number and cannot be pinned. One is security-critical
and says exactly how it is maintained:

    tools/image_search_tools.py:29
    # SSRF guard — kept in sync with tools/web_tools.py::_ssrf_check via grep.
    # Duplicated rather than imported to avoid cross-module coupling for a
    # small, security-critical helper.

**They are currently identical** — compared as normalised ASTs, not by eye, and the duplication
is a defensible choice for a small guard. What was missing is any way to KNOW that tomorrow. A
grep is a thing someone has to remember; this is a thing that fails.

If the two are deliberately changed apart later, this test should be deleted along with the
comment that claims they are in sync — not weakened.
"""
import ast
import difflib
import pathlib

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
PAIR = [
    (ROOT / "tools" / "web_tools.py", "_ssrf_check"),
    (ROOT / "tools" / "image_search_tools.py", "_ssrf_check"),
]


def _normalised(path: pathlib.Path, name: str) -> str:
    """The function's AST, unparsed, with the docstring stripped — so comments, blank lines and
    docstring wording differ freely while the LOGIC is compared."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            node.body = [b for b in node.body
                         if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant)
                                 and isinstance(b.value.value, str))]
            return ast.unparse(node)
    raise AssertionError(f"{name} not found in {path.name}")


def test_the_two_ssrf_guards_are_identical():
    a = _normalised(*PAIR[0])
    b = _normalised(*PAIR[1])
    if a != b:
        diff = "\n".join(difflib.unified_diff(
            a.split("\n"), b.split("\n"), PAIR[0][0].name, PAIR[1][0].name, lineterm="", n=2))
        raise AssertionError(
            "the two SSRF guards have DRIFTED. One request path now validates differently from "
            "the other, and the comment in image_search_tools still claims they are in sync.\n"
            + diff)


def test_both_still_exist_where_the_comment_says():
    """Non-vacuity: if either is renamed or removed, this must fail rather than pass silently."""
    for path, name in PAIR:
        assert _normalised(path, name)


def test_the_comment_that_claims_the_invariant_is_still_there():
    """The test and the claim have to live or die together — a comment promising a grep-kept
    invariant, with no grep and no test, is how #764 happened."""
    src = (ROOT / "tools" / "image_search_tools.py").read_text(encoding="utf-8")
    assert "kept in sync with tools/web_tools.py::_ssrf_check" in src


@pytest.mark.parametrize("blocked", [
    "http://127.0.0.1/x", "http://169.254.169.254/latest/meta-data/",
    "file:///etc/passwd", "http://10.0.0.1/", "not a url",
])
def test_both_guards_agree_on_the_cases_that_matter(blocked):
    """Behavioural, not just structural: identical ASTs could still be two copies of a broken
    guard, so the security cases are asserted directly on both."""
    import importlib
    import sys
    sys.path.insert(0, str(ROOT))
    try:
        wt = importlib.import_module("tools.web_tools")
        it = importlib.import_module("tools.image_search_tools")
    finally:
        sys.path.pop(0)
    assert wt._ssrf_check(blocked) is not None, blocked
    assert it._ssrf_check(blocked) is not None, blocked


def test_both_give_the_SAME_answer_on_a_normal_url():
    """The other direction — a guard that blocks everything would pass every test above.

    Asserted as AGREEMENT, not as "allowed": this box has no DNS egress, so a public hostname
    fails resolution and both guards correctly reject it. My first version asserted `is None`
    and failed on the sandbox rather than on the code — an environment assumption dressed as an
    invariant. Agreement is the property this file exists to protect anyway."""
    import importlib
    import sys
    sys.path.insert(0, str(ROOT))
    try:
        wt = importlib.import_module("tools.web_tools")
        it = importlib.import_module("tools.image_search_tools")
    finally:
        sys.path.pop(0)
    for url in ("https://example.com/a.png", "http://cdn.example.org/x.jpg"):
        assert wt._ssrf_check(url) == it._ssrf_check(url), url


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
