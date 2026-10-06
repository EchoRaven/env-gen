"""#1203g5 — half of all lint calls re-lint bytes nothing has written, at ~992ms each.

`lint` is the most expensive tool by wall clock in the corpus: of 7214s of recorded tool time,
1156s is lint — 16.0%, over 1165 calls at 992ms each. Measured over r160–r164's agent logs with
every write attributed to its file: 1004 of 1978 lint calls (51%) re-lint a path nothing has
written since the previous lint, and 1003 of those 1004 returned a BYTE-IDENTICAL result. The
one exception is `app/backend/main.py`, written by a different agent between the two calls —
which a content hash handles correctly and a per-agent "unchanged?" flag would not.

1003 × 992ms is ~16.6 minutes across five runs, ~3.3 per run, against the 7200s per-milestone
wall cap that r159 died on with zero delivery.

#1191's dedup cannot help: it collapses a repeated RESULT in the context, and lint results have
a median length of 77 bytes — below its 1500-byte floor, whose reasoning ("a pointer costs about
as much as the body") is right for them. The cost is the subprocess, not the tokens.

Keyed on the content hash rather than mtime: a hash cannot lie about a rewrite that kept the
timestamp, and `lint`'s only parameter is `path`, so identical bytes have no other input.
"""
import sys
import time
from pathlib import Path

import pytest

_AGENT = Path(__file__).resolve().parents[1]
for _p in (str(_AGENT), str(_AGENT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools._base import Workspace  # noqa: E402
from tools.code_tools import LintTool  # noqa: E402

_DIRTY = "import os\nimport sys\n"          # two unused imports -> real findings
_DIRTY2 = "import os\n"


@pytest.fixture
def lint(tmp_path):
    (tmp_path / "x.py").write_text(_DIRTY, encoding="utf-8")
    return LintTool(workspace=Workspace(tmp_path)), tmp_path


def test_the_same_bytes_are_not_linted_twice(lint):
    tool, root = lint
    first = tool.execute("x.py")
    t0 = time.time()
    second = tool.execute("x.py")
    hit_ms = (time.time() - t0) * 1000
    assert second.data == first.data
    assert hit_ms < 50, "a cache hit took %.0fms — it is not hitting" % hit_ms


def test_the_cache_hit_is_a_copy_not_the_stored_object(lint):
    """#1203g4 had just been fixed for this hazard one layer up: a caller that annotates the
    result must not be editing the cache, or every later hit serves the annotation as if lint
    had said it."""
    tool, root = lint
    first = tool.execute("x.py")
    second = tool.execute("x.py")
    assert second is not first
    if isinstance(second.data, dict):
        second.data["injected"] = 1
    third = tool.execute("x.py")
    assert "injected" not in (third.data or {})


def test_changed_bytes_are_relinted(lint):
    tool, root = lint
    before = tool.execute("x.py")
    (root / "x.py").write_text(_DIRTY2, encoding="utf-8")
    after = tool.execute("x.py")
    assert after.data != before.data, "a rewrite must not serve the stale verdict"


def test_reverting_the_bytes_hits_the_original_entry(lint):
    """Content-keyed, not sequence-keyed: going back to earlier bytes is a hit, which an
    mtime or a 'dirty since last lint' flag would both get wrong."""
    tool, root = lint
    first = tool.execute("x.py")
    (root / "x.py").write_text(_DIRTY2, encoding="utf-8")
    tool.execute("x.py")
    (root / "x.py").write_text(_DIRTY, encoding="utf-8")
    again = tool.execute("x.py")
    assert again.data == first.data


def test_a_rewrite_that_keeps_the_mtime_is_still_seen(lint):
    """Why the key is a hash: `os.utime` can put the timestamp back, and a mtime-keyed cache
    would then serve the previous file's verdict for different bytes."""
    import os
    tool, root = lint
    f = root / "x.py"
    st = f.stat()
    before = tool.execute("x.py")
    f.write_text(_DIRTY2, encoding="utf-8")
    os.utime(f, (st.st_atime, st.st_mtime))
    assert f.stat().st_mtime == st.st_mtime
    after = tool.execute("x.py")
    assert after.data != before.data, "mtime was restored and the stale verdict came back"


def test_two_files_do_not_share_a_verdict(tmp_path):
    (tmp_path / "a.py").write_text(_DIRTY, encoding="utf-8")
    (tmp_path / "b.py").write_text("x = 1\n", encoding="utf-8")
    tool = LintTool(workspace=Workspace(tmp_path))
    a = tool.execute("a.py")
    b = tool.execute("b.py")
    assert a.data != b.data


def test_identical_bytes_in_two_paths_share_correctly(tmp_path):
    """The key is the CONTENT, so the same bytes under another name is a legitimate hit — the
    verdict depends on nothing else (`lint`'s only parameter is `path`)."""
    (tmp_path / "a.py").write_text(_DIRTY, encoding="utf-8")
    (tmp_path / "copy.py").write_text(_DIRTY, encoding="utf-8")
    tool = LintTool(workspace=Workspace(tmp_path))
    a = tool.execute("a.py")
    c = tool.execute("copy.py")
    assert c.data == a.data


def test_a_missing_file_is_not_cached_as_a_verdict(tmp_path):
    """The not-found answer must not outlive the file's absence.

    NOT asserted via `success`: lint returns `success=False` whenever it FINDS issues, so a
    dirty file answers False too -- the first version of this test read that as the cached
    not-found error. What distinguishes them is the error message versus a real report."""
    tool = LintTool(workspace=Workspace(tmp_path))
    r = tool.execute("nope.py")
    assert "File not found" in str(r.error_message or "")
    (tmp_path / "nope.py").write_text(_DIRTY, encoding="utf-8")
    r2 = tool.execute("nope.py")
    assert "File not found" not in str(r2.error_message or ""), r2
    assert r2.data, "it must have actually linted the file that now exists"


def test_the_cache_is_bounded(tmp_path):
    tool = LintTool(workspace=Workspace(tmp_path))
    cap = tool._LINT_CACHE_MAX_1203G5
    for i in range(cap + 5):
        (tmp_path / "f.py").write_text("x = %d\n" % i, encoding="utf-8")
        tool.execute("f.py")
    assert len(tool._lint_cache_1203g5) <= cap


def test_an_unreadable_file_pays_the_lint_rather_than_guessing_a_key(lint, monkeypatch):
    """A key it cannot compute must disable the cache, never fall back to the path: serving one
    file's verdict for another's bytes is worse than paying the second lint."""
    tool, root = lint
    assert tool._lint_content_key_1203g5(root / "does_not_exist.py") is None
    monkeypatch.setattr(tool, "_lint_content_key_1203g5", lambda _p: None)
    a = tool.execute("x.py")
    (root / "x.py").write_text(_DIRTY2, encoding="utf-8")
    b = tool.execute("x.py")
    assert a.data != b.data, "with no key, every call must re-lint"


def test_json_and_unknown_extensions_also_cache(tmp_path):
    (tmp_path / "d.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "n.txt").write_text("hello", encoding="utf-8")
    tool = LintTool(workspace=Workspace(tmp_path))
    for name in ("d.json", "n.txt"):
        first = tool.execute(name)
        second = tool.execute(name)
        assert second.data == first.data
    assert len(tool._lint_cache_1203g5) >= 2


# ---------------------------------------------------------------- wiring, over the AST

def test_execute_consults_and_fills_the_cache():
    """A memo nobody reads, or nobody fills, is the #1178 shape. Both halves pinned."""
    import ast
    import inspect
    src = inspect.getsource(LintTool.execute)
    tree = ast.parse(src.lstrip())
    names = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "_lint_cache_get_1203g5" in names, sorted(names)
    assert "_lint_cache_put_1203g5" in names, sorted(names)


def test_the_key_is_a_hash_not_a_timestamp():
    import inspect
    src = inspect.getsource(LintTool._lint_content_key_1203g5)
    assert "sha256" in src
    for forbidden in ("st_mtime", "getmtime", "st_size", "time()"):
        assert forbidden not in src, forbidden
