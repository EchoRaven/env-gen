r"""#1203c7: the MCP probe counted the framework's own docstring as a tool.

    tools = len(re.findall(r"@\w+\.tool\b", src)) or len(re.findall(r"\basync def tool_\w+", src))
    out["complete"] = tools >= len(business_eps) and tools > 0

`mcp_scaffold._SKELETON_HEADER` opens every generated server with "One @mcp.tool per backend
endpoint", so the regex matched the DOCUMENTATION of the decorator before any decorator.

MEASURED, and total: over all 119 delivered `mcp_server/*/main.py`, the regex exceeds an AST
count of `@<obj>.tool` decorators by EXACTLY 1 — 119 of 119. r146 live: 4 real tools at lines
116/127/138/148, reported as 5, the fifth match on line 4.

★ A FALSE GREEN AT THE ONLY BOUNDARY THAT MATTERS. `complete` is `tools >= expected`, so the
phantom flips it whenever the real count is exactly `expected - 1`. 38 of 198 persisted reports
sit on that boundary with `complete: True`, and in TEN the verdict is PASS with `broken` and
`missing` both empty — the MCP surface was the only thing between PARTIAL and PASS.

★ The second regex branch (`async def tool_*`) is dropped: it was doubly dead — unreachable
because the first branch always matched the docstring, and 0 of 119 servers contain the pattern
at all. `test_the_counter_is_tied_to_what_the_scaffolder_emits` is what keeps that safe: if the
generator ever stops emitting a `.tool` decorator, it goes red before the count silently does.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.test_user_validation as TUV  # noqa: E402


def _count(src):
    fn = getattr(TUV, "_count_mcp_tools_1203c7", None)
    assert fn is not None, "_count_mcp_tools_1203c7 is not defined"
    return fn(src)


def _header():
    """★ THE POSITIVE CONTROL IS THE FRAMEWORK'S OWN TEXT, not a header I retyped — a fixture I
    write myself proves only that I can reproduce the bug I already understand."""
    from multi_agent.runtime import mcp_scaffold as MS
    h = getattr(MS, "_SKELETON_HEADER", None)
    assert h, "_SKELETON_HEADER is gone — this test's whole premise was that header"
    return h


def test_the_scaffolders_own_header_holds_no_tools():
    """★ The defect in one assertion: the header ALONE used to count as a tool."""
    h = _header()
    assert "@mcp.tool" in h, "the header no longer mentions the decorator; see the next test"
    n, _how = _count(h + "\nimport os\n")
    assert n == 0, "the docstring is still being counted: %d" % n


def test_r146s_four_tools_read_as_four():
    """r146's exact shape: the real header plus four decorated handlers."""
    src = _header() + """
import os
mcp = object()

@mcp.tool()
async def get_search(q=None): return ""

@mcp.tool()
async def get_videos_feed(cursor=None): return ""

@mcp.tool()
async def post_videos_feed(body=None): return ""

@mcp.tool()
async def get_videos_by_videoId(videoId=None): return ""
"""
    n, how = _count(src)
    assert n == 4, n
    assert "4" in how, how


def test_a_bare_decorator_counts():
    """`@mcp.tool` with no call parens is the same registration."""
    n, _ = _count("@mcp.tool\nasync def f(): return 1\n")
    assert n == 1, n


def test_any_object_counts():
    """Scope is unchanged from `@\\w+\\.tool`: the attribute name is what matters."""
    n, _ = _count("@app.tool()\nasync def f(): return 1\n")
    assert n == 1, n


def test_a_comment_is_not_a_tool():
    """The general form of the defect — the word appearing in prose anywhere."""
    n, _ = _count("# register one @mcp.tool per endpoint\nasync def f(): return 1\n")
    assert n == 0, n


def test_an_unrelated_decorator_is_not_a_tool():
    n, _ = _count("@mcp.resource()\nasync def f(): return 1\n")
    assert n == 0, n


def test_a_file_that_does_not_parse_says_so():
    """★ NOT a masking fallback: a server that cannot be imported exposes no tools, and the
    note names the generation defect rather than reporting a decorator count for broken code."""
    n, how = _count("def f(:\n  pass\n")
    assert n == 0
    assert "does NOT parse" in how, how


def test_the_note_says_how_it_counted():
    """#1034: a count whose method is invisible cannot be checked by its reader."""
    _n, how = _count(_header() + "\n@mcp.tool()\nasync def f(): return 1\n")
    assert "AST" in how, how


def test_the_counter_is_tied_to_what_the_scaffolder_emits():
    """★ The guard on dropping the `async def tool_*` branch. It was unreachable (0 of 119
    delivered servers contain the pattern, and the first branch always matched the docstring
    anyway) — but "harmless today" stops being true the moment the producer changes. If the
    scaffolder ever emits a registration this counter cannot see, this goes red first."""
    import re
    from multi_agent.runtime import mcp_scaffold as MS
    import inspect
    src = inspect.getsource(MS)
    assert re.search(r"@\{?\w+\}?\.tool", src), \
        "the scaffolder no longer emits a `.tool` decorator — _count_mcp_tools_1203c7 must " \
        "be taught the new registration shape before this is relaxed"


# ── the verdict boundary ──────────────────────────────────────────────────────────────

def _probe(monkeypatch, tmp_path, src, n_endpoints):
    srv = tmp_path / "mcp_server" / "app"
    srv.mkdir(parents=True)
    (srv / "main.py").write_text(src, encoding="utf-8")
    eps = [{"path": "/api/e%d" % i, "method": "GET"} for i in range(n_endpoints)]
    return TUV._mcp_test_user(tmp_path, eps)



def test_one_short_is_not_complete(monkeypatch, tmp_path):
    """★ The flip: 4 real tools for 5 endpoints used to read 5 >= 5 -> complete."""
    src = _header() + "\n" + "".join(
        "@mcp.tool()\nasync def f%d(): return 1\n\n" % i for i in range(4))
    out = _probe(monkeypatch, tmp_path, src, 5)
    assert out["tools_found"] == 4, out
    assert out["complete"] is False, out
    assert "INCOMPLETE" in out["note"], out


def test_an_exact_match_is_complete(monkeypatch, tmp_path):
    """The other direction must not regress: a genuinely complete surface stays complete."""
    src = _header() + "\n" + "".join(
        "@mcp.tool()\nasync def f%d(): return 1\n\n" % i for i in range(5))
    out = _probe(monkeypatch, tmp_path, src, 5)
    assert out["tools_found"] == 5 and out["complete"] is True, out


def test_the_report_records_the_method(monkeypatch, tmp_path):
    src = _header() + "\n@mcp.tool()\nasync def f(): return 1\n"
    out = _probe(monkeypatch, tmp_path, src, 1)
    assert "counted_by_1203c7" in out, sorted(out)
    assert "AST" in out["counted_by_1203c7"], out


def test_a_missing_server_is_untouched(monkeypatch, tmp_path):
    """#616's timing verdict must survive — this patch only changes how tools are counted."""
    out = TUV._mcp_test_user(tmp_path, [{"path": "/api/x"}])
    assert out["server_found"] is False
    assert "AT THIS MOMENT" in out["note"], out
