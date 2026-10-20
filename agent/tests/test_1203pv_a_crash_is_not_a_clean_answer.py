r"""#1203pv: two detectors returned "nothing wrong" when they had crashed.

`route_params_ignored_1202uw` and `frontend_calls_without_backend_1202uv` both end in

    except Exception:
        return []

and `[]` from either is byte-identical to a clean answer -- "no route ignores its parameter",
"every frontend call is served". #883's rule is that "I could not look" and "I looked and
found nothing" must be different answers.

WHY THESE TWO, out of the twelve silent swallows in detector-ish functions. The framework
already applies this disposition at 29 of these 41 handlers -- 27 through one of its six
swallow-announcing helpers and 2 by logging directly (`warn_once_1201`,
`_scan_truncated_791`, `_swallowed_790`, `_swallowed_1152`, `_gate_absent_792`,
`_log_hub_swallow_once`) -- #701's wording is "keep the behaviour, end the silence".
`warn_once_1201` is used TWICE in scaffolder.py already (`persist_backfilled_apis_1202ub`,
`isolation_scoped_tables`), so this is the same rule missing at a sibling in the same file,
not a new policy.

And `route_params_ignored_1202uw` is LIVE: #1203pd found `/@:username -> ProfileOwnPage` in
both r189 and r191 -- every `/@someone` URL shows the viewer their own profile. A fault there
hands the gate a clean answer about a check that never ran.

★ The counts behind "twelve" took three tries. Scanning for unannounced swallows gave 30,
then 18, then 12 as each new announcement helper was discovered by sampling. The fix was to
enumerate the vocabulary from the code instead of guessing it -- the same mistake recorded for
the detector-channel classifier, which knew only `create_task` and logs and so reported all 18
`*_blockers` as log-only.
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
    frontend_calls_without_backend_1202uv as UV,
    route_params_ignored_1202uw as UW,
)

_SITE_UW = "scaffolder.route_params_ignored_1202uw"
_SITE_UV = "scaffolder.frontend_calls_without_backend_1202uv"


class _Boom:
    """`str()` raises, so the detector faults inside its own try -- no monkeypatching, and
    the fault lands exactly where a real one would."""

    def __str__(self):
        raise RuntimeError("boom-1203pv")


class _Spy:
    def __init__(self):
        self.said = []

    def __call__(self, site, what, exc):
        self.said.append((site, what, exc))


class ACrashIsNotACleanAnswer(unittest.TestCase):

    def setUp(self):
        for s in (_SITE_UW, _SITE_UV):
            MF._WARNED_1201.discard(s)
            self.addCleanup(MF._WARNED_1201.discard, s)
        self._orig = MF.warn_once_1201
        self.spy = _Spy()
        MF.warn_once_1201 = self.spy

        def _restore():
            MF.warn_once_1201 = self._orig
        self.addCleanup(_restore)

    def test_the_route_param_detector_says_it_crashed(self):
        """★ THE TICKET on the live one: #1203pd's finding rides this detector."""
        self.assertEqual(UW(_Boom()), [])
        sites = [s for s, _w, _e in self.spy.said]
        self.assertIn(_SITE_UW, sites, self.spy.said)

    def test_the_route_param_warning_names_the_consequence(self):
        """#983: a line that fires while saying nothing is not an announcement. The reader
        has to learn that the clean answer is about a check that did not run."""
        UW(_Boom())
        what = next(w for s, w, _e in self.spy.said if s == _SITE_UW)
        self.assertIn("did not", what.lower())

    def test_the_route_param_warning_carries_the_exception(self):
        """`exc=None` is reserved for "a precondition was absent" (#1203os). This is a real
        exception and must arrive as one, or the cause clause says the wrong thing."""
        UW(_Boom())
        exc = next(e for s, _w, e in self.spy.said if s == _SITE_UW)
        self.assertIsInstance(exc, Exception)
        self.assertIn("boom-1203pv", str(exc))

    def test_the_unserved_call_detector_says_it_crashed(self):
        self.assertEqual(UV(_Boom(), [{"method": "GET", "path": "/api/x"}]), [])
        sites = [s for s, _w, _e in self.spy.said]
        self.assertIn(_SITE_UV, sites, self.spy.said)

    def test_it_still_returns_an_empty_list_rather_than_raising(self):
        """The swallow itself is right: a scan fault must never crash the scaffolder. This
        is "end the silence", not "start raising"."""
        self.assertEqual(UW(_Boom()), [])
        self.assertEqual(UV(_Boom(), [{"method": "GET", "path": "/api/x"}]), [])


class TheQuietPathsStayQuiet(unittest.TestCase):
    """The announcement must fire on a FAULT, never on a legitimately empty answer -- or it
    becomes noise on every run and nobody reads it (#1041)."""

    def setUp(self):
        for s in (_SITE_UW, _SITE_UV):
            MF._WARNED_1201.discard(s)
            self.addCleanup(MF._WARNED_1201.discard, s)
        self._orig = MF.warn_once_1201
        self.spy = _Spy()
        MF.warn_once_1201 = self.spy

        def _restore():
            MF.warn_once_1201 = self._orig
        self.addCleanup(_restore)

    def test_a_missing_App_jsx_is_silent(self):
        """`route_params_ignored_1202uw` returns [] by its own `if not app.is_file()` check,
        which is an answer and not a fault."""
        import tempfile
        d = tempfile.mkdtemp(prefix="pv1203_")
        self.assertEqual(UW(d), [])
        self.assertEqual(self.spy.said, [])

    def test_a_missing_service_module_is_silent(self):
        """Same for the other: "the frontend lane has not written api.js yet" is handled by
        `if not svc` above the handler."""
        import tempfile
        d = tempfile.mkdtemp(prefix="pv1203b_")
        self.assertEqual(UV(d, [{"method": "GET", "path": "/api/x"}]), [])
        self.assertEqual(self.spy.said, [])

    def test_an_empty_contract_is_silent(self):
        """`if not have: return []` -- #1202tn's rule, an answer about the registry."""
        import tempfile
        d = tempfile.mkdtemp(prefix="pv1203c_")
        self.assertEqual(UV(d, []), [])
        self.assertEqual(self.spy.said, [])


if __name__ == "__main__":
    unittest.main()
