r"""#1203pw: the wiring pre-check returned "every page is wired" when it had crashed.

`_frontend_wiring_blockers` gates the visual judge so it never scores a pre-wiring app.
api_smoke probes the BACKEND only, so it goes green while frontend routes are still unwired;
those routes fall through App.jsx's `*` catch-all and render a redirect/404 -- a NON-blank
page, so the capture_transient refund misses it -- and, in its own docstring's words, "the
judge scores the projected UI at ~0.00".

Its handler was `except Exception: return []`, and `[]` is also what "all wired" looks like.
Two costs follow, both stated by the code around it:

  * the judge scores a catch-all route and attributes ~0.00 to the app -- #769's shape one
    layer up, a harness failure producing a verdict-looking zero;
  * an ATTEMPT is spent, because the caller only skips `self.attempts + 1` when this returns
    rows.

The `[]` is kept -- "an audit hiccup must never wedge the judge shut" is correct, and this is
#701's disposition: keep the behaviour, end the silence. 29 of the 41 swallows in
detector-shaped functions already announce, 27 of them through one of the framework's six
swallow-announcing helpers.
"""
import sys
import unittest
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[1]
for _p in (str(_AGENT), str(_AGENT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import message_format as MF  # noqa: E402
from multi_agent.runtime import visual_fidelity as VF  # noqa: E402

_SITE = "visual_fidelity._frontend_wiring_blockers"


class _Hubs:
    def __init__(self, workhub):
        self.workhub = workhub


class _Orch:
    def __init__(self, out, workhub=object()):
        self.output_dir = out
        self.hubs = _Hubs(workhub)


class _Gate:
    """Only what the method reads off `self`."""

    def __init__(self, orch):
        self._orch = orch


def _call(orch):
    return VF.VisualFidelityGate._frontend_wiring_blockers(_Gate(orch))


class _Spy:
    def __init__(self):
        self.said = []

    def __call__(self, site, what, exc):
        self.said.append((site, what, exc))


class _Boom:
    def __fspath__(self):
        raise RuntimeError("boom-1203pw")

    def __str__(self):
        raise RuntimeError("boom-1203pw")


class AFaultIsNotAWiredApp(unittest.TestCase):

    def setUp(self):
        MF._WARNED_1201.discard(_SITE)
        self.addCleanup(MF._WARNED_1201.discard, _SITE)
        self._orig = MF.warn_once_1201
        self.spy = _Spy()
        MF.warn_once_1201 = self.spy
        self.addCleanup(lambda: setattr(MF, "warn_once_1201", self._orig))

    def test_a_fault_is_announced(self):
        """★ THE TICKET. `[]` still comes back, but it is no longer the only trace."""
        self.assertEqual(_call(_Orch(_Boom())), [])
        self.assertIn(_SITE, [s for s, _w, _e in self.spy.said], self.spy.said)

    def test_the_warning_names_BOTH_consequences(self):
        """#983: the reader has to learn why a clean answer here is expensive -- the judge
        cannot tell wired from unwired, and an attempt is spent either way."""
        _call(_Orch(_Boom()))
        what = next(w for s, w, _e in self.spy.said if s == _SITE)
        self.assertIn("attempt", what.lower())
        self.assertIn("wired", what.lower())

    def test_the_real_exception_is_carried(self):
        """#1203os: `exc=None` means "a precondition was absent". This is a crash."""
        _call(_Orch(_Boom()))
        exc = next(e for s, _w, e in self.spy.said if s == _SITE)
        self.assertIsInstance(exc, Exception)
        self.assertIn("boom-1203pw", str(exc))

    def test_it_still_returns_empty_rather_than_raising(self):
        """Keeping the judge open is the whole reason the swallow exists."""
        self.assertEqual(_call(_Orch(_Boom())), [])


class TheLegitimateEmptyAnswersStayQuiet(unittest.TestCase):
    """An announcement that fired on every normal run would be #1041's storm, and the two
    guarded early returns above the handler are ordinary answers, not faults."""

    def setUp(self):
        MF._WARNED_1201.discard(_SITE)
        self.addCleanup(MF._WARNED_1201.discard, _SITE)
        self._orig = MF.warn_once_1201
        self.spy = _Spy()
        MF.warn_once_1201 = self.spy
        self.addCleanup(lambda: setattr(MF, "warn_once_1201", self._orig))

    def test_no_output_dir_is_silent(self):
        self.assertEqual(_call(_Orch(None)), [])
        self.assertEqual(self.spy.said, [])

    def test_no_workhub_is_silent(self):
        import tempfile
        self.assertEqual(_call(_Orch(tempfile.mkdtemp(prefix="pw1203_"), workhub=None)), [])
        self.assertEqual(self.spy.said, [])


if __name__ == "__main__":
    unittest.main()
