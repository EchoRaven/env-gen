"""#1202vn — the build-currency verdict was computed, logged, and never reached the lane.

`#1202ex` measures whether the running image was built from the source now on disk. Its own
docstring names the case it exists for: "googlemaps-r16 ... 12 chain steps died on a
projected create whose handler, run against the authored body, passes. Its image fingerprint
does not match its source. Nothing in the run said so, and the run spent its remaining budget
on the app."

tiktok-r136, live: the warning fired 36 times into the log while 43 gate snapshots carried a
`business_chain_failing` detail and NOT ONE mentioned it. The lane was handed
`GET /api/videos/feed -> 422` with no hint that the container might predate the fix — on a
run whose source orders that literal route ahead of the `{id}` route swallowing it.
"""
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import (
    _build_currency_caveat_1202vn as caveat,
)

_GATE = pathlib.Path(
    __file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/runtime/delivery_gate.py")
_VT = pathlib.Path(
    __file__).resolve().parents[1] / "env_generator/llm_generator/tools/validation_tools.py"


def _rec(verdict, detail="app/ has changed since the image was built (source a, built b)"):
    return {"last_result": {"build_currency_1202ex": {"verdict": verdict, "detail": detail}}}


def test_a_changed_image_is_named_in_the_blocker():
    out = caveat([_rec("changed")])
    assert "BUILD CURRENCY" in out
    assert "app/ has changed" in out
    assert "Rebuild and recreate" in out


def test_a_current_image_adds_nothing():
    assert caveat([_rec("current", "the running image was built from this exact source")]) == ""


def test_an_unknown_verdict_adds_nothing():
    """`unknown` means the probe could not answer — saying "may be stale" on that would be
    inventing a diagnosis, which is what #1202ex refuses to do."""
    assert caveat([_rec("unknown", "no compose file")]) == ""


def test_a_record_without_the_verdict_adds_nothing():
    assert caveat([{"last_result": {}}]) == ""
    assert caveat([{}]) == ""
    assert caveat([]) == ""


def test_one_changed_record_among_many_is_enough():
    """The verdict is a property of the RUN, not of one chain — it is stored per chain only
    because that is the record the gate reads."""
    assert "BUILD CURRENCY" in caveat([_rec("current"), _rec("changed"), _rec("current")])


def test_it_does_not_suppress_the_blocker():
    """#1202ex is explicit: "a `changed` reading does not make a failure fake -- it makes it
    unattributable". Blocking on an unattributable failure is right; hiding that it is
    unattributable is not. So this only APPENDS to the detail."""
    src = _GATE.read_text()
    block = src[src.index('"reason": "business_chain_failing", "authored": len(authored),'):]
    block = block[:block.index("# #510 GUARD")]
    assert "_build_currency_caveat_1202vn(authored)" in block
    # appended to the detail, not used to change the reason or skip the branch
    assert "+ _build_currency_caveat_1202vn(authored)" in block


def test_malformed_input_never_raises():
    assert caveat("not a list") == ""
    assert caveat([{"last_result": "junk"}]) == ""
    assert caveat([{"last_result": {"build_currency_1202ex": "junk"}}]) == ""


def test_the_verdict_is_carried_not_recomputed():
    """Recomputing costs 1.07s per gate tick, measured on r136 — over two minutes across
    that run's 127 snapshots. `run_chains` already returns it, so the sync point carries it
    into the durable record instead."""
    vt = _VT.read_text()
    block = vt[vt.index("registryhub.record_chain_result("):]
    block = block[:block.index("agent=")]
    assert 'report.get("build_currency_1202ex")' in block
    gate = _GATE.read_text()
    fn = gate[gate.index("def _build_currency_caveat_1202vn"):
              gate.index("def _first_broken_step_1202ox")]
    assert "build_currency_1202ex(" not in fn, "the gate must read the stored verdict"


def test_a_crash_reading_the_verdict_announces_itself(monkeypatch):
    """#1202ah: an empty string here is the pre-#1202vn behaviour, not a pass — but a reader
    comparing two blockers cannot tell "the image is current" from "the caveat could not be
    read"."""
    import env_generator.llm_generator.multi_agent.runtime.message_format as mf

    class _Boom(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")

    seen = []
    monkeypatch.setattr(mf, "warn_once_1201", lambda site, what, exc: seen.append(site))
    assert caveat([_Boom()]) == ""
    assert seen == ["_build_currency_caveat_1202vn"]
