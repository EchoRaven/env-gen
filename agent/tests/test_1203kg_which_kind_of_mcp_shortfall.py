"""#1203kg: an MCP tool count judged against a registry that had moved on.

#616 made the "no mcp_server/ yet" branch say that absence can be a timing verdict. The
branch three lines below it, which compares COUNTS, said nothing of the kind — it reports
`N tool(s) for M endpoint(s)` and leaves the reader to read a gap.

Measured over the modern era's final test-user reports: 17 of 36 read INCOMPLETE, and in 14
of them the delivered `mcp_server/<env>/main.py` is NEWER than the report (by 6 to 106
minutes) with a final tool count that MEETS what the report demanded — r169 reported 9 tools
for 23 endpoints and ships 23. In 16 of the 17, business endpoints were still being registered
AFTER the report was written.

Three are real and must stay distinguishable: r180 ships 6 tools for 32 endpoints behind a
server file 92 minutes older than its own report; r156 and r152 have no server file at all.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_validation import (  # noqa: E402
    mcp_shortfall_cause_1203kg as CAUSE)

_NOW = time.time()


def _ep(path, at):
    return {"path": path, "method": "GET", "_updated_at": at}


def test_an_endpoint_registered_after_the_server_explains_the_shortfall_1203kg():
    stale, why = CAUSE(_NOW - 600, [_ep("/api/a", _NOW - 900), _ep("/api/b", _NOW)])
    assert stale is True, why
    assert "registered AFTER this server file was written" in why, why
    assert "/api/b" in why, "name the endpoints, or the claim cannot be checked"
    assert "/api/a" not in why, "an endpoint OLDER than the server is not an excuse"
    assert "Re-check the tree" in why, why


def test_a_server_newer_than_every_endpoint_is_a_real_gap_1203kg():
    """r180's shape: nothing explains it away, so the sentence must not soften."""
    stale, why = CAUSE(_NOW, [_ep("/api/a", _NOW - 10), _ep("/api/b", _NOW - 5)])
    assert stale is False, why
    assert "real gap in the projection" in why, why
    assert "Re-check" not in why, "a real gap must not be dressed as a timing artifact"


def test_the_count_of_late_endpoints_is_the_one_reported_1203kg():
    eps = [_ep("/api/%d" % i, _NOW + i) for i in range(5)] + [_ep("/api/old", _NOW - 999)]
    stale, why = CAUSE(_NOW - 1, eps)
    assert stale is True and why.lstrip().startswith("— but 5 of those"), why
    assert "…" in why, "#1034: a cut list must say it was cut"


def test_no_server_mtime_says_nothing_rather_than_guessing_1203kg():
    for bad in (None, 0, "", "x", -1):
        stale, why = CAUSE(bad, [_ep("/api/a", _NOW)])
        assert stale is False and why == "", (bad, why)


def test_junk_endpoints_cannot_break_it_1203kg():
    stale, why = CAUSE(_NOW - 10, [None, 7, "x", {}, {"path": "/p"},
                                   {"path": "/q", "_updated_at": "nope"},
                                   _ep("/api/late", _NOW)])
    assert stale is True and "/api/late" in why, why


def test_the_verdict_itself_is_not_touched_1203kg():
    """#616's rule, and the reason this is a note and not a flip: the probe must not claim a
    surface it did not see. `complete` is the count comparison and nothing else.

    The first version compared the POSITION of the two statements, and a mutation that ADDED
    a second assignment slipped past it — the original was still earlier, so "first index of
    each" was satisfied while the cause now decided the verdict. The invariant is ownership,
    not order: ONE assignment, and the cause function nowhere inside its value.
    """
    import ast
    src = (LLM / "multi_agent" / "runtime" / "test_user_validation.py").read_text("utf-8")
    tree = ast.parse(src)
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, ast.FunctionDef) and f.name == "_mcp_test_user")
    assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
               and any(ast.unparse(t) in ('out["complete"]', "out['complete']")
                       for t in n.targets)]
    assert len(assigns) == 1, (
        "#1203kg: `complete` must have exactly one owner (#1032) — found %d assignments: %s"
        % (len(assigns), [ast.unparse(a) for a in assigns]))
    value = ast.unparse(assigns[0].value)
    assert "mcp_shortfall_cause_1203kg" not in value, (
        "#1203kg explains the shortfall; it must not decide it — the probe may not claim a "
        "surface it did not see (#616's own rule for the sibling branch): " + value)
    assert "tools" in value and "business_eps" in value, value


def test_it_does_not_reach_for_a_module_the_file_lacks_1203kg():
    """The call site uses `Path.stat()`, not `os.path.getmtime`.

    This module imports no `os`, and a NameError inside `_mcp_test_user` is swallowed by its
    own `except Exception`, which would REPLACE the real note with "mcp check error" — a
    silent degradation (#1201) that reads as a probe fault rather than a missing import.

    Asked of the AST, not the text. The first version of this test grepped the source for
    "os.path.getmtime" and failed on the COMMENT that explains why the code avoids it —
    source text holds both code and talk about code, and grep cannot tell them apart
    (the same trap, mirrored, as the assertions that are satisfied BY their own comment).
    """
    import ast
    src = (LLM / "multi_agent" / "runtime" / "test_user_validation.py").read_text("utf-8")
    tree = ast.parse(src)
    imported = {n.names[0].name.split(".")[0]
                for n in ast.walk(tree) if isinstance(n, ast.Import)}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree)
                 if isinstance(n, ast.ImportFrom) and n.module}
    used = {n.value.id for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    assert "os" not in (used - imported), (
        "`os` is used but never imported — a NameError the enclosing except would hide")
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, ast.FunctionDef) and f.name == "_mcp_test_user")
    names = {ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not any(n.startswith("os.") for n in names), sorted(names)
