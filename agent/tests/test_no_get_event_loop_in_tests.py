r"""Guard: no test may drive a coroutine through `asyncio.get_event_loop()`.

`asyncio.run()` closes its loop and leaves the thread with NO current event loop. Any later test
that calls `asyncio.get_event_loop().run_until_complete(...)` then dies with

    RuntimeError: There is no current event loop in thread 'MainThread'

The two forms coexisted for a long time and the suite passed — purely because collection order
happened to put every `asyncio.run` caller AFTER every `get_event_loop` caller. Adding
`test_bug_found_explicit_recipients_628.py` broke that by accident of its NAME: "bug_f" sorts
before "capture_stability", so four tests in a file nobody had touched started failing.

The suite already knew about the hazard and had patched the wrong side — three files carry
workarounds that "save + restore a usable current loop" so they do not poison later tests. That
protects the polluter's neighbours; it cannot protect against a new file appearing earlier in the
order. Removing the deprecated call is the fix that holds. (`get_event_loop()` is deprecated from
3.10 and this suite runs on 3.10.)

Use `asyncio.run(coro())`. A bare `asyncio.get_event_loop()` for inspection is still allowed —
what is banned is driving a coroutine with it.
"""
import pathlib
import glob
import os
import re

import pytest

_BANNED = re.compile(r"get_event_loop\(\)\s*\.\s*run_until_complete")


def _offenders():
    here = os.path.dirname(os.path.abspath(__file__))
    out = {}
    for path in sorted(glob.glob(os.path.join(here, "test_*.py"))):
        name = os.path.basename(path)
        if name == os.path.basename(__file__):
            continue
        src = pathlib.Path(path).read_text(encoding="utf-8")   # #1202eu: open().read() leaked one FD per file (1593 each)
        n = len(_BANNED.findall(src))
        if n:
            out[name] = n
    return out


def test_no_test_drives_a_coroutine_through_the_current_loop():
    offenders = _offenders()
    assert not offenders, (
        "get_event_loop().run_until_complete() found in " + repr(offenders) +
        " — use asyncio.run(...). The current form fails the moment any earlier-sorting test "
        "file calls asyncio.run(), because that leaves no current loop.")


def test_the_detector_matches_the_shape_it_claims():
    assert _BANNED.search("asyncio.get_event_loop().run_until_complete(f())")
    assert _BANNED.search("loop = asyncio.get_event_loop() . run_until_complete(f())")
    # inspection-only use stays legal
    assert not _BANNED.search("prev = asyncio.get_event_loop()")
    assert not _BANNED.search("asyncio.run(f())")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
