"""#1203g6 — grep read every byte of every seed video, line by line, in Python.

`grep` is the third most expensive tool in the corpus by wall clock: 857s of 7214s. Its
per-call cost varies a thousandfold — r164's backend averaged 16ms over 16 calls, r153's
backend 9722ms over 6, and one call in r148 took 28.2 seconds. The loop opened every file
matching `include` (default `*`) in text mode with `errors='replace'` and iterated its lines.

Measured on the trees it searches: tiktok-r153's `app/` is 412.1 MB across 205 files, of which
411.5 MB — 99.9% — is BINARY: 35 seed `.mp4` files totalling 406.8 MB (largest 30.6 MB) plus 68
jpg/jpeg/woff2. The text is 0.5 MB in 97 files. r152 is identical; googlemaps-r16 is 140.3 MB of
binary across 805 files.

Measured end to end on those trees, before vs after: r153 110.30s -> 0.008s, googlemaps-r16
4.86s -> 0.023s.

And the old behaviour was not merely slow, it was WRONG under the result cap: on r152 with
pattern `api`, 16 of the 32 matched "files" were a .woff2 and fifteen .mp4s, and both versions
stopped at MAX_RESULTS — so binary noise displaced real text matches. With the skip: 18 files,
zero binary.

The test is the NUL sniff GNU grep itself uses, and the count of skipped files is REPORTED with
the results: a tool that quietly searched fewer files than asked would be the masked-failure
shape this project forbids.
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
from tools.code_tools import GrepTool, _binary_note_1203g6  # noqa: E402


def _out(result):
    d = result.data if isinstance(result.data, dict) else {}
    return str(d.get("output") or d.get("info") or ""), d


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "a.py").write_text("needle here\nsecond line\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("nothing\n", encoding="utf-8")
    with open(tmp_path / "clip.mp4", "wb") as fh:
        fh.write(b"\0needle\0" * 200000)        # ~1.6 MB, contains the pattern in bytes
    return GrepTool(workspace=Workspace(tmp_path)), tmp_path


def test_a_binary_file_is_not_searched(tree):
    tool, root = tree
    out, d = _out(tool.execute("needle"))
    assert "a.py:1: needle here" in out
    assert "clip.mp4" not in out, "the pattern inside video bytes was reported as a match"


def test_the_skip_is_reported_not_silent(tree):
    """The user's standing rule: no fallback that masks what did not happen. A lane concluding
    'the string is nowhere' has to know which files were never read."""
    tool, _ = tree
    out, _ = _out(tool.execute("needle"))
    assert "1 binary file(s) skipped" in out


def test_the_skip_is_reported_on_a_zero_match_search_too(tree):
    tool, _ = tree
    out, d = _out(tool.execute("zzz_no_such_string"))
    assert d.get("matches") == 0
    assert "binary file(s) skipped" in out


def test_nothing_is_said_when_nothing_was_skipped(tmp_path):
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")
    tool = GrepTool(workspace=Workspace(tmp_path))
    out, _ = _out(tool.execute("needle"))
    assert "skipped" not in out


@pytest.mark.parametrize("n,expect", [
    (0, ""), (None, ""), (-1, ""), ("", ""), ("junk", ""),
    (1, ", 1 binary file(s) skipped"), (35, ", 35 binary file(s) skipped"),
])
def test_the_note_helper_is_total_and_quiet_at_zero(n, expect):
    assert _binary_note_1203g6(n) == expect


def test_a_text_file_with_a_high_byte_is_still_searched(tmp_path):
    """The test is a NUL byte, not 'is it ASCII'. UTF-8 source with CJK or emoji must still be
    read — excluding it would silently narrow every search in this corpus."""
    (tmp_path / "zh.py").write_text("# 中文注释 needle 🎬\n", encoding="utf-8")
    tool = GrepTool(workspace=Workspace(tmp_path))
    out, _ = _out(tool.execute("needle"))
    assert "zh.py:1:" in out
    assert "skipped" not in out


def test_a_nul_after_the_first_4kb_is_still_searched(tmp_path):
    """The sniff reads 4 KiB, exactly like GNU grep. A file whose only NUL is past that is
    treated as text -- stated here so the boundary is a decision, not an accident."""
    body = ("x = 1  # needle\n" + "p = 2\n" * 2000).encode("utf-8")
    assert len(body) > 4096
    with open(tmp_path / "late.py", "wb") as fh:
        fh.write(body + b"\0tail")
    tool = GrepTool(workspace=Workspace(tmp_path))
    out, _ = _out(tool.execute("needle"))
    assert "late.py:1:" in out


def test_an_explicit_binary_path_is_still_honoured(tmp_path):
    """Grepping a binary BY NAME is a deliberate act; the skip must not make it impossible.
    The result may be empty, but the call must not error."""
    with open(tmp_path / "clip.mp4", "wb") as fh:
        fh.write(b"\0needle\0" * 10)
    tool = GrepTool(workspace=Workspace(tmp_path))
    r = tool.execute("needle", path="clip.mp4")
    assert r.success, r.error_message


def test_it_is_fast_with_a_large_binary_present(tmp_path):
    """The measured cost was 110s on a tree that is 99.9% video. Here: a 20 MB binary must not
    be read, so the search stays in milliseconds."""
    (tmp_path / "a.py").write_text("needle\n", encoding="utf-8")
    with open(tmp_path / "big.bin", "wb") as fh:
        fh.write(b"\0" * (20 * 1024 * 1024))
    tool = GrepTool(workspace=Workspace(tmp_path))
    t0 = time.time()
    out, _ = _out(tool.execute("needle"))
    ms = (time.time() - t0) * 1000
    assert "a.py:1:" in out
    assert ms < 500, "took %.0fms — the binary is being read" % ms


# ----------------------------------------------------------------- structure, over the AST

def test_the_sniff_runs_before_the_text_read():
    """Order is the whole point: sniffing after opening in text mode would save nothing."""
    import ast
    import inspect
    src = inspect.getsource(GrepTool.execute)
    i = src.index('open(file_path, \'rb\')')
    j = src.index("open(file_path, 'r', encoding='utf-8'")
    assert i < j, "the binary sniff must come before the line-by-line read"
    tree = ast.parse(src.lstrip())
    consts = {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, int)}
    assert 4096 in consts, "the sniff window is no longer 4 KiB"


def test_the_skipped_count_reaches_both_return_paths():
    """A counter that only one exit reports would leave the no-match answer silent — which is
    the exit a lane reads when it concludes the string is nowhere."""
    import inspect
    src = inspect.getsource(GrepTool.execute)
    assert src.count("_binary_note_1203g6(") >= 2, src.count("_binary_note_1203g6(")
