r"""#1203px: the two artifact writers failed silently, and their False is read by nobody.

`record_frontend_calls_without_backend_1202uv` and `record_route_params_ignored_1202uw` land
their detector's finding in a `logs/*.jsonl` ledger. Both ended in

    except Exception:
        return False

and `False` is ALSO what the guard above returns for "there was nothing to record". Both
call sites invoke them as a statement and read neither return, so the crash had no trace at
all -- and the ledger's absence carries the same ambiguity: no file means either "the
detector found nothing" or "the write threw", which is the pair #883 says must be
distinguishable.

This is the purest of the three silence tickets: for #1203pv and #1203pw the `[]` at least
flows into a gate decision, so a wrong answer has downstream effects. Here nothing reads
anything, so announcing is the ONLY way a failed write can ever surface.

The cost lands on a later reader rather than on the run: these ledgers are what an
investigation greps, and it is how #1203pd attributed `/@:username -> ProfileOwnPage` in
r189 and r191.
"""
import sys
import unittest
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[1]
for _p in (str(_AGENT), str(_AGENT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import message_format as MF  # noqa: E402
from multi_agent.runtime.scaffolder import (  # noqa: E402
    record_frontend_calls_without_backend_1202uv as REC_UV,
    record_route_params_ignored_1202uw as REC_UW,
)

_SITE_UV = "scaffolder.record_frontend_calls_without_backend_1202uv"
_SITE_UW = "scaffolder.record_route_params_ignored_1202uw"


class _Spy:
    def __init__(self):
        self.said = []

    def __call__(self, site, what, exc):
        self.said.append((site, what, exc))


class _Boom:
    """Truthy, so it passes the `if not out_dir` guard, and then explodes where the write is."""

    def __bool__(self):
        return True

    def __str__(self):
        raise RuntimeError("boom-1203px")

    def __fspath__(self):
        raise RuntimeError("boom-1203px")


class AFailedWriteIsAnnounced(unittest.TestCase):

    def setUp(self):
        for s in (_SITE_UV, _SITE_UW):
            MF._WARNED_1201.discard(s)
            self.addCleanup(MF._WARNED_1201.discard, s)
        self._orig = MF.warn_once_1201
        self.spy = _Spy()
        MF.warn_once_1201 = self.spy
        self.addCleanup(lambda: setattr(MF, "warn_once_1201", self._orig))

    def test_the_unserved_call_ledger_says_it_could_not_write(self):
        self.assertFalse(REC_UV(_Boom(), ["GET /api/x"]))
        self.assertIn(_SITE_UV, [s for s, _w, _e in self.spy.said], self.spy.said)

    def test_the_route_param_ledger_says_it_could_not_write(self):
        self.assertFalse(REC_UW(_Boom(), ["/@:username -> ProfileOwnPage"]))
        self.assertIn(_SITE_UW, [s for s, _w, _e in self.spy.said], self.spy.said)

    def test_the_message_says_the_evidence_is_absent(self):
        """#983: the point is that a later reader will find no file and must not read that
        as 'the detector found nothing'."""
        REC_UW(_Boom(), ["x"])
        what = next(w for s, w, _e in self.spy.said if s == _SITE_UW)
        self.assertIn("ledger", what.lower())

    def test_the_exception_is_carried(self):
        REC_UV(_Boom(), ["GET /api/x"])
        exc = next(e for s, _w, e in self.spy.said if s == _SITE_UV)
        self.assertIsInstance(exc, Exception)
        self.assertIn("boom-1203px", str(exc))


class NothingToRecordStaysQuiet(unittest.TestCase):
    """The guard above the handler returns False for an empty finding list, and that is an
    ordinary answer on almost every run -- announcing it would be #1041's storm."""

    def setUp(self):
        for s in (_SITE_UV, _SITE_UW):
            MF._WARNED_1201.discard(s)
            self.addCleanup(MF._WARNED_1201.discard, s)
        self._orig = MF.warn_once_1201
        self.spy = _Spy()
        MF.warn_once_1201 = self.spy
        self.addCleanup(lambda: setattr(MF, "warn_once_1201", self._orig))

    def test_no_findings_is_silent(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="px1203_")
        self.assertFalse(REC_UV(d, []))
        self.assertFalse(REC_UW(d, []))
        self.assertEqual(self.spy.said, [])

    def test_no_out_dir_is_silent(self):
        self.assertFalse(REC_UV(None, ["GET /api/x"]))
        self.assertFalse(REC_UW(None, ["x"]))
        self.assertEqual(self.spy.said, [])

    def test_a_real_write_succeeds_and_is_silent(self):
        import tempfile
        d = tempfile.mkdtemp(prefix="px1203b_")
        self.assertTrue(REC_UV(d, ["GET /api/x"]))
        self.assertTrue(REC_UW(d, ["/@:username -> ProfileOwnPage"]))
        self.assertEqual(self.spy.said, [])
        self.assertTrue((Path(d) / "logs").is_dir())


if __name__ == "__main__":
    unittest.main()
