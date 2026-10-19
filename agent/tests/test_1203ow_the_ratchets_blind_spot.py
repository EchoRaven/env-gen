r"""#1203ow: twelve ratchets could not see the subsystem whose failures block delivery most.

`agent/tests/` filters framework sources by FILENAME -- `"test" in p.name` or
`f.name.startswith("test_")` -- in twelve places. That drops ten files, and only seven of them
are tests (`multi_agent/bundled_tests/oauth_contract/*`). The other three are framework
modules whose names merely begin with `test`:

    runtime/test_user_runner.py       1853 lines   the browser walk
    runtime/test_user_squad.py        1931 lines   the test-user squad
    runtime/test_user_validation.py   1756 lines   test-user validation
    -------------------------------------------   5,540 lines = 5.1% of the runtime

That is the subsystem whose failures are the corpus's number-one and number-two terminal
blockers (`validation_ui_evidence_failed` 172 blocking holds, `deliverability_ui_flow_failed`
142). Every empty default it returned was invisible to #883's rule, every unbound name to
#940's, every log-only detector to #947's.

★ FOUND BY THE BLIND SPOT BITING. #1203ov's pre-registered criterion needs the sentence "no
login steps recorded", which the framework emits from `test_user_runner.py` -- and #1203oh's
emitter check reported NO EMITTER for a line the framework really prints, because its reader
used the same filename filter. Second time that checker's own reader was the bug.

★ WHAT THE BLIND SPOT ACTUALLY HID, after judging all six hits one at a time:
    REAL   test_user_squad.py  `missing_state = {}`   -> no `missing_write_path` goal spawned
    REAL   test_user_squad.py  `flow_findings = []`   -> the flow reads as covered
    SILENT test_user_runner.py `_affordance = False`  -> the VALUE is deliberate (see below)
    mine   test_user_squad.py  `ui = api = ""`        -> announces via `report["reason"]`
    mine   test_user_validation.py `_wfr_1203je = None` -> a guarded import, #802's own comment
    thin   test_user_validation.py `vals = []`        -> a display path
  My `_announces` approximation only knew logger/warn/raise keywords, so two of the six were
  my own false positives: reporting through the ARTIFACT is reporting. Three real, not six.

★ `_affordance = False` KEEPS ITS VALUE. It feeds `_landed_in_the_app_1126`, whose
`if not login_affordance: return True` is documented as conservative on purpose -- "a false
'auth broken' is worse than a missed one here" (#504, r81). #883 asks for the announcement,
not for the other side of the trade.

★ The other eleven ratchets' blind spot is REAL BUT MEASURED EMPTY today: #895's deep relative
imports, #1034's capped joins and #943's fixed-width windows all return 0 over the three
modules, so widening those filters is churn with no finding behind it (#647). The number is
recorded so the next person does not re-derive it.
"""
from __future__ import annotations

import ast
import importlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_RUNTIME = LLM / "multi_agent" / "runtime"
_MODULES = ("test_user_runner.py", "test_user_squad.py", "test_user_validation.py")

# the rule is #883's; this test must not grow a second copy of it (#1032)
_R883 = importlib.import_module("tests.test_an_empty_default_must_not_mean_clean_883") \
    if "tests.test_an_empty_default_must_not_mean_clean_883" in sys.modules \
    else importlib.import_module("test_an_empty_default_must_not_mean_clean_883")


class TheRatchetCanSeeTheModulesNow(unittest.TestCase):

    def test_the_three_modules_are_in_the_gate_list(self):
        for m in _MODULES:
            with self.subTest(module=m):
                self.assertIn(m, _R883._GATES)

    def test_the_scan_no_longer_skips_them_by_filename(self):
        """The reader's own behaviour, not its source: run the counter and assert the three
        modules are among the files it walked (they contribute to the denominator)."""
        counts, total = _R883._counts()
        self.assertGreaterEqual(total, 100, "the AST walk has drifted: total=%d" % total)
        # Visible now, so the residue is RECORDED rather than invisible: the walk is 0, and
        # the two remaining handlers are in #883's own `_BASELINE` with a reason each (one
        # reports through `report["reason"]`, two are a guarded import and a display path).
        # A NEW silent default in any of the three fails #883 itself.
        self.assertEqual(counts.get("test_user_runner.py", 0), 0,
                         "the affordance probe stopped announcing")
        for m in ("test_user_squad.py", "test_user_validation.py"):
            with self.subTest(module=m):
                self.assertEqual(counts.get(m, 0), _R883._BASELINE[m],
                                 "the reviewed residue in %s moved; re-read it rather than "
                                 "raising the baseline" % m)

    def test_real_tests_are_still_excluded(self):
        """The exclusion that IS needed must stay: a sentence only a bundled OAuth contract
        test contains must not count as framework source."""
        walked = []
        for f in sorted(_R883._ROOT.rglob("*.py")):
            if {"tests", "bundled_tests", "node_modules"} & set(f.parts):
                continue
            walked.append(f.name)
        self.assertNotIn("test_whatsapp.py", walked)
        self.assertNotIn("test_slack.py", walked)
        self.assertIn("test_user_squad.py", walked)


class TheTwoGoalGeneratorsSayWhenTheyCouldNotLook(unittest.TestCase):
    """The REAL pair: `{}` / `[]` here means the squad spawns no goal for that gap."""

    def setUp(self):
        from multi_agent.runtime import message_format as MF
        MF._WARNED_1201.clear()
        self.MF = MF

    def tearDown(self):
        self.MF._WARNED_1201.clear()

    def _run_with(self, name):
        """Make one helper raise and return (warnings said, the call's result)."""
        from multi_agent.runtime import completeness_audit as CA
        from multi_agent.runtime import test_user_squad as TUS
        said = []
        orig_w = self.MF.warn_once_1201

        def spy(site, what, exc):
            said.append((site, what, exc))
            return orig_w(site, what, exc)

        orig_fn = getattr(CA, name)

        def boom(*a, **k):
            raise RuntimeError("boom")

        self.MF.warn_once_1201 = spy
        setattr(CA, name, boom)
        try:
            out = TUS._missing_write_goals(
                [{"method": "GET", "path": "/api/x", "status": "implemented"}],
                {"things": {"schema": {"columns": [{"name": "id"}]}}},
                {"flows": []}, [])
        finally:
            self.MF.warn_once_1201 = orig_w
            setattr(CA, name, orig_fn)
        return said, out

    def _one(self, said, marker):
        rows = [r for r in said if marker in str(r[0])]
        self.assertTrue(rows, "nothing said so: %r" % (said,))
        return rows[0]

    def test_a_crashed_write_path_inventory_is_announced(self):
        said, out = self._run_with("state_entities_missing_write")
        site, what, exc = self._one(said, "missing_state_1203ow")
        self.assertIsNotNone(out)
        # ★ mutation OW4: passing None here would make #1201 render "its precondition was
        # not met (no exception was raised)" -- a sentence that is false when something DID
        # raise. The cause clause only works if the real exception reaches it.
        self.assertIsInstance(exc, BaseException, "the cause is %r, not the exception" % exc)
        self.assertIn("boom", str(exc))

    def test_a_crashed_flow_check_is_announced(self):
        said, out = self._run_with("check_flow_no_write")
        site, what, exc = self._one(said, "flow_findings_1203ow")
        self.assertIsNotNone(out)
        self.assertIsInstance(exc, BaseException, "the cause is %r, not the exception" % exc)
        self.assertIn("boom", str(exc))

    def test_the_healthy_path_says_nothing(self):
        """★ Non-vacuity: the announcement must be the exception, not a heartbeat."""
        from multi_agent.runtime import test_user_squad as TUS
        said = []
        orig_w = self.MF.warn_once_1201
        self.MF.warn_once_1201 = lambda s, w, e: said.append(s)
        try:
            TUS._missing_write_goals([], {}, {}, [])
        finally:
            self.MF.warn_once_1201 = orig_w
        self.assertEqual([s for s in said if "1203ow" in str(s)], [], said)


class TheAffordanceProbeKeepsItsSideOfTheTrade(unittest.TestCase):
    """`#1203ow` adds the announcement and does NOT flip the conservative default."""

    def test_the_default_still_reads_as_landed(self):
        from multi_agent.runtime.test_user_runner import _landed_in_the_app_1126 as landed
        # a probe that could not look -> False -> "landed", which is #504's deliberate side
        self.assertTrue(landed("/", "/login", False))
        self.assertTrue(landed("/feed", "/login", False))
        # and a probe that DID see a login affordance on the entry page still fails
        self.assertFalse(landed("/", "/login", True))
        self.assertFalse(landed("/login", "/login", True))
        self.assertTrue(landed("/feed", "/login", True))

    def test_the_handler_announces_and_binds_its_exception(self):
        """Structural, by AST: the handler must name the exception and call the announcer --
        a bare `except Exception:` cannot report what it swallowed."""
        src = (_RUNTIME / "test_user_runner.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            if "_LOGIN_AFFORDANCE_JS" not in ast.unparse(node):
                continue
            for h in node.handlers:
                body = ast.unparse(h)
                if "_affordance = False" in body:
                    found.append((h.name, "warn_once_1201" in body))
        self.assertTrue(found, "the affordance handler is gone")
        for name, announces in found:
            self.assertIsNotNone(name, "the handler does not bind its exception")
            self.assertTrue(announces, "the handler still swallows in silence")


class TheOtherElevenRatchetsAreMeasuredEmpty(unittest.TestCase):
    """#647: their blind spot is real, and widening them today would find nothing. The
    numbers are frozen so the decision stays checkable."""

    def test_no_deep_relative_imports(self):
        for m in _MODULES:
            tree = ast.parse((_RUNTIME / m).read_text(encoding="utf-8"))
            deep = [n for n in ast.walk(tree)
                    if isinstance(n, ast.ImportFrom) and (n.level or 0) >= 3]
            with self.subTest(module=m):
                self.assertEqual(deep, [], "#895 would now fire in %s" % m)

    def test_no_capped_join_and_no_fixed_width_window(self):
        import re
        for m in _MODULES:
            src = (_RUNTIME / m).read_text(encoding="utf-8")
            with self.subTest(module=m):
                self.assertEqual(re.findall(r"join\([^)]*\[:\s*\d+\s*\]", src), [],
                                 "#1034 would now fire in %s" % m)
                self.assertEqual(
                    re.findall(r"\[\s*\w+\s*:\s*\w+\s*\+\s*\d{3,}\s*\]", src), [],
                    "#943 would now fire in %s" % m)


if __name__ == "__main__":
    unittest.main()
