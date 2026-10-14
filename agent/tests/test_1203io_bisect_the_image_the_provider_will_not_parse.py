"""#1203io — #1203if's successful retry is a proof; bisect to use it.

When `#1203if` drops every inline image and the retry SUCCEEDS, the images were the cause:
the same conversation was refused with them and accepted without. WHICH image is the fact six
separate eliminations could not get —

  * the provider's 400 is 193 characters and carries `'param': None`, naming no part;
  * every reference PNG loads on its own (33 in r184, 11 in r183);
  * so do all 4415 entries of the shared compression cache;
  * the same images replayed through the framework's own compress+fit were ACCEPTED;
  * so were they beside a 90k system prompt and 13 tools;
  * and the condenser had been DECLINED at every step before the first 400.

A bisect is the only thing that can produce it. Each probe re-sends the proven-good payload
with one HALF of the images restored, so it differs from that payload by exactly the images
under test: ceil(log2(n)) + 1 calls — 5 for r184's 11 images — against a conversation that was
losing EVERY call (49 across four phases in r184).

Diagnosis only: the recovered response is never replaced, so a bisect that fails or raises
changes nothing the caller sees.
"""
import os
import sys

import pytest

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

from utils.llm import (  # noqa: E402
    _image_part_index_1203io as index,
    _keep_only_image_parts_1203io as keep_only,
)

IMG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
TXT = {"type": "text", "text": "hi"}


def _msgs(n_images=3):
    return [{"role": "system", "content": "s"},
            {"role": "user", "content": [TXT] + [dict(IMG) for _ in range(n_images)]},
            {"role": "user", "content": [dict(IMG), TXT]}]


def test_the_index_is_in_wire_order():
    got = index(_msgs(2))
    assert got == [(1, 1), (1, 2), (2, 0)], got


def test_keeping_a_subset_replaces_only_the_others():
    m = _msgs(2)
    out = keep_only(m, [(1, 1)])
    parts = out[1]["content"]
    assert parts[1]["type"] == "image_url", "the kept image was dropped"
    assert parts[2]["type"] == "text" and "#1203io" in parts[2]["text"]
    assert out[2]["content"][0]["type"] == "text", "an image in another message survived"


def test_positions_are_preserved_so_each_probe_differs_only_by_the_images():
    """A probe that also shifted the parts would not be testing the same conversation."""
    m = _msgs(3)
    out = keep_only(m, [(2, 0)])
    assert [len(x["content"]) if isinstance(x["content"], list) else 0
            for x in out] == [0, 4, 2]


def test_the_callers_payload_is_never_mutated():
    """The recovered response was built from it, and the original exception may still be
    re-raised, so it has to stay intact."""
    import json
    m = _msgs(3)
    before = json.dumps(m)
    keep_only(m, [(1, 1)])
    index(m)
    assert json.dumps(m) == before


def test_keeping_everything_is_a_no_op_on_the_images():
    m = _msgs(2)
    out = keep_only(m, index(m))
    assert [p["type"] for p in out[1]["content"]] == ["text", "image_url", "image_url"]


@pytest.mark.parametrize("bad", [None, "str", 42, [{"role": "u"}], [None]])
def test_hostile_payloads_do_not_raise(bad):
    assert index(bad) == []
    keep_only(bad, [(0, 0)])          # must not raise


def test_a_bisect_over_the_index_converges(monkeypatch):
    """★ The algorithm itself, driven offline: with a known culprit, halving the candidate
    list must land on exactly it in ceil(log2(n)) probes."""
    import math
    for n in (2, 3, 5, 8, 11):
        for culprit in range(n):
            idx = [(1, k) for k in range(n)]
            lo, probes = list(idx), 0
            while len(lo) > 1 and probes < 12:
                half = lo[:max(1, len(lo) // 2)]
                probes += 1
                # the probe fails iff the culprit is among the restored half
                if (1, culprit) in half:
                    lo = half
                else:
                    lo = lo[len(half):]
            assert lo == [(1, culprit)], (n, culprit, lo)
            assert probes <= math.ceil(math.log2(n)) + 1, (n, culprit, probes)


def test_the_bisect_never_replaces_the_recovered_response():
    """★ THE GUARD. This is a diagnosis; if it ever assigned to `response` a failing probe
    could overwrite a good answer. Pinned over the AST of the enclosing block."""
    import ast
    import pathlib
    src = pathlib.Path(_AGENT, "utils/llm.py").read_text(encoding="utf-8")
    start = src.index("#1203io: THE RETRY SUCCEEDING IS A PROOF")
    end = src.index("latency = (datetime.now() - start_time)", start)
    block = src[start:end]
    code = "\n".join(l for l in block.splitlines() if not l.strip().startswith("#"))
    assert "response" not in code.split("_idx1203io")[0] or "response =" not in code, (
        "the bisect assigns to `response`; a failing probe could overwrite the recovery")
    assert "_calls1203io < 12" in code, "the probe loop is uncapped"
    assert "_is_unchanged_payload_400_1203i8(_e1203io)" in code, (
        "a DIFFERENT error must stop the bisect rather than be read as a culprit signal")


# ---------------------------------------------------------------- forensics
from utils.llm import _image_part_forensics_1203io as forensics  # noqa: E402


def _one(url):
    return [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}]


def test_a_truncated_base64_is_named_as_such():
    """★ The question the bisect exists to enable. Planting a truncated base64 into r184's
    real screenshots and sending them to the real endpoint reproduces `image_parse_error`
    while every file on disk is valid — so "was this part's base64 cut?" is the next
    question, and it must be answered without logging the payload."""
    import base64
    good = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 400).decode()
    out = forensics(_one("data:image/png;base64," + good[: len(good) // 3] + "QUJD"), (0, 0))
    assert "b64_len=" in out
    assert "b64_tail=" in out
    # it is cut mid-image: either it fails to decode, or decodes but will not open
    assert "decodes=NO" in out or "opens=NO" in out, out


def test_a_valid_image_reports_clean():
    import base64
    import io as _io
    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGB", (4, 3), (1, 2, 3)).save(buf, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    out = forensics(_one(url), (0, 0))
    assert "decodes=yes" in out and "opens=yes size=4x3" in out, out


def test_it_never_logs_the_payload():
    """★ A forensics line that dumps 700KB of base64 is unusable and may leak. Measurements
    only — and the tail is bounded to a few characters."""
    import base64
    big = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"y" * 5000).decode()
    out = forensics(_one("data:image/png;base64," + big), (0, 0))
    assert len(out) < 300, len(out)
    assert big[:64] not in out, "the payload itself is in the log line"


@pytest.mark.parametrize("bad", [
    [], [{"role": "user"}], [{"role": "user", "content": []}],
    [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
])
def test_forensics_never_raises(bad):
    assert isinstance(forensics(bad, (0, 0)), str)


def test_a_url_that_is_not_a_data_uri_says_so():
    out = forensics(_one("https://example.com/a.png"), (0, 0))
    assert "no data URI" in out


def test_the_bisect_actually_calls_the_forensics():
    """★ THE GUARD M3 needed. Replacing the forensics call with `""` left all 20 other
    tests green, because they exercise the helper and never its caller — the same hole
    #1203ii was written about ("evidence in a key nothing reads"). Pinned on the AST so the
    bisect cannot name a part and then stay silent about what is wrong with it."""
    import ast
    import pathlib
    src = pathlib.Path(_AGENT, "utils/llm.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_image_part_forensics_1203io"]
    assert calls, (
        "the bisect localises an image part and never says what is measurably wrong with "
        "it — the one question it exists to enable")
    # and it must be fed the SAME payload the bisect ran over, not a rebuilt one
    seg = " ".join(ast.get_source_segment(src, c) or "" for c in calls)
    assert "request_params" in seg, (
        "the forensics is not reading the payload that was actually sent")


def test_the_bisect_runs_once_per_process_and_says_when_it_skips():
    """★ THE COST GUARD, found by auditing my own patch for amplification.

    Each bisect costs ceil(log2(n)) + 1 extra image-bearing calls. Cheap against ONE
    poisoned conversation; ruinous per occurrence — tiktok-web-r117 logged 1024
    `image_parse_error`s, which unguarded would be ~4-5k extra calls. That is a 4x
    amplification, the same shape as the 9x re-send #1203i8 exists to remove, and I built it
    in while fixing that.

    The diagnostic lands on the FIRST bisect (it names the part and dumps the forensics six
    eliminations could not get); later occurrences repeat it at full price. So: once per
    process, and the skip is LOGGED — a silent skip is exactly what this session kept
    finding wrong elsewhere.
    """
    import ast
    import pathlib
    import utils.llm as _l

    assert hasattr(_l, "_IO_BISECTED_1203io"), "the once-per-process latch is gone"
    assert _l._IO_BISECTED_1203io.get("done") in (True, False)

    src = pathlib.Path(_AGENT, "utils/llm.py").read_text(encoding="utf-8")
    start = src.index("#1203io: THE RETRY SUCCEEDING IS A PROOF")
    end = src.index("latency = (datetime.now() - start_time)", start)
    block = src[start:end]
    code = "\n".join(l for l in block.splitlines() if not l.strip().startswith("#"))

    assert '_IO_BISECTED_1203io.get("done")' in code, (
        "the latch is never consulted, so every occurrence pays for a bisect")
    assert '_IO_BISECTED_1203io["done"] = True' in code, (
        "the latch is never set, so it can never skip")
    assert "bisect SKIPPED" in block, (
        "the skip is silent — say it, the way #1203if says what it dropped")
    # the skip must not disturb the recovered response
    assert "_SkipBisect1203io" in code
    tree = ast.parse(src)
    assert any(isinstance(n, ast.ClassDef) and n.name == "_SkipBisect1203io"
               for n in ast.walk(tree)), "the sentinel exception is not defined"
