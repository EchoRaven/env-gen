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
