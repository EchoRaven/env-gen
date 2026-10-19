r"""#1203ou: the decision not to clobber the lane's login page said itself 92 times.

`#1197` keeps an existing auth page when it is the lane's own AND wired AND drivable, and
logs the decision. The scaffolder runs per tick, so the decision is re-announced every pass.
MEASURED on the modern run logs, counting DISTINCT RAW lines (the normalised count hides it):

    r190  212 lines /  5 distinct   (the top one 92 times, byte for byte)
    r183  208 lines / 17 distinct
    r185  110 lines / 14 distinct
    r191   88 lines /  9 distinct
    ------------------------------------------------
    1,115 lines across the r183+ logs, for about 45 decisions

#1202ad's rule, and the third instance of the same shape after #1203i3 (`#150`, 132-207 lines
per agent -> 2-4) and #1203ot (`#1202vz resolved`, 797 identical lines in r190).

★ THE STATE IS THE PAIR OF LINE COUNTS, not a constant: r190 shows SignupPage kept at 15
lines 79 times and then at 14 lines 22 times. The lane editing its own page inside one run is
news; the same page at the same size again is the heartbeat.

★ AND `_body = None` STAYS OUTSIDE THE ANNOUNCEMENT. That assignment IS the decision -- it is
how the write loop is told to skip this page -- and #1197's own line says what it is for: "r26
clobbered this page 87 times". A memo that can move a decision is worse than the repetition it
removes, so the structural placement is asserted here by AST, not by reading the text.

★ The sibling `#914` line ("LANE PAGE WITH OWN COMPONENTS ... KEEPING the lane's page") is
deliberately left alone: it is 57 lines for 54 DISTINCT raw lines in r190 -- a per-page
measurement, not a heartbeat. It only looked like one when a forward window captured the
trailing marker instead of the sentence.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import logging
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs  # noqa: E402
from env_generator.llm_generator.multi_agent.runtime import message_format as MF  # noqa: E402

# The SCENARIO (a lane auth page that is wired and drivable, in a real-shaped tree) belongs to
# #1197's own test and stays in one place -- #1032. Duplicating ~80 lines of JSX here would
# drift from the branch it is supposed to exercise.
_SIB = importlib.import_module("tests.test_the_auth_branch_defers_to_a_live_lane_login_1197") \
    if "tests.test_the_auth_branch_defers_to_a_live_lane_login_1197" in sys.modules \
    else importlib.import_module("test_the_auth_branch_defers_to_a_live_lane_login_1197")

_CORPUS = ROOT.parent / "generated"
_LOGGER = "env_generator.llm_generator.multi_agent.runtime.frontend_scaffold"


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.said = []

    def emit(self, record):
        self.said.append(record.getMessage())


class ThePassesStopRepeatingTheDecision(unittest.TestCase):

    def setUp(self):
        MF._STATE_SAID_1202AD.clear()
        self.cap = _Capture()
        self.lg = logging.getLogger(fs.__name__)
        self.lg.addHandler(self.cap)
        self._lvl = self.lg.level
        self.lg.setLevel(logging.INFO)
        import os
        os.environ.pop("ENVGEN_DEFER_TO_LANE_PAGE", None)

    def tearDown(self):
        self.lg.removeHandler(self.cap)
        self.lg.setLevel(self._lvl)
        MF._STATE_SAID_1202AD.clear()

    def _kept(self):
        return [m for m in self.cap.said if "KEEPING the lane's auth page" in m]

    def _scaffold_twice(self, page_src=None):
        fe = _SIB._tree(page_src if page_src is not None else _SIB._LANE_PAGE)
        target = fe / "src" / "pages" / "LoginPage.jsx"
        orig = fs._load_design_for_projection
        fs._load_design_for_projection = lambda _fd: None
        try:
            for _ in range(3):
                fs.scaffold_pages_from_contract(fe, [_SIB._LOGIN_PAGE])
        finally:
            fs._load_design_for_projection = orig
        return target.read_text(encoding="utf-8") if target.exists() else None

    def test_three_passes_say_the_decision_once(self):
        left = self._scaffold_twice()
        self.assertEqual(len(self._kept()), 1, self._kept())
        self.assertIsNotNone(left)

    def test_the_decision_itself_still_holds_on_the_silent_passes(self):
        """★ The one that matters: the lane's page must survive the passes whose log line was
        suppressed. If the memo ever moved `_body = None` under it, the page would be
        clobbered on pass 2 and 3 while the log stayed quiet -- r26's 87 clobbers, with the
        evidence removed."""
        left = self._scaffold_twice()
        self.assertIsNotNone(left, "the lane's page was deleted")
        self.assertNotIn("isRegister", left,
                         "the framework's projection replaced the lane's page on a pass whose "
                         "announcement was deduped")
        self.assertEqual(left.strip(), _SIB._LANE_PAGE.strip())

    def test_a_page_the_lane_edits_is_announced_again(self):
        """★ Mutation OU3 found this missing. r190 shows SignupPage kept at 15 lines 79 times
        and then at 14 lines 22 times -- the lane editing its own page inside one run, which
        a constant state would swallow."""
        fe = _SIB._tree(_SIB._LANE_PAGE)
        target = fe / "src" / "pages" / "LoginPage.jsx"
        orig = fs._load_design_for_projection
        fs._load_design_for_projection = lambda _fd: None
        try:
            fs.scaffold_pages_from_contract(fe, [_SIB._LOGIN_PAGE])
            # the lane edits its page: same behaviour, one more line
            target.write_text("// the lane's own note\n" + _SIB._LANE_PAGE, encoding="utf-8")
            fs.scaffold_pages_from_contract(fe, [_SIB._LOGIN_PAGE])
        finally:
            fs._load_design_for_projection = orig
        said = self._kept()
        self.assertEqual(len(said), 2, said)
        self.assertNotEqual(said[0], said[1], said)

    def test_two_auth_pages_do_not_silence_each_other(self):
        """★ Mutation OU4: with the component out of the site key, the second page's decision
        would never be announced."""
        fe = _SIB._tree(_SIB._LANE_PAGE)
        (fe / "src" / "pages" / "SignupPage.jsx").write_text(
            _SIB._LANE_PAGE.replace("LoginPage", "SignupPage"), encoding="utf-8")
        signup = dict(_SIB._LOGIN_PAGE, name="signup", route="/signup",
                      component="SignupPage")
        orig = fs._load_design_for_projection
        fs._load_design_for_projection = lambda _fd: None
        try:
            fs.scaffold_pages_from_contract(fe, [_SIB._LOGIN_PAGE, signup])
        finally:
            fs._load_design_for_projection = orig
        said = self._kept()
        self.assertEqual(len(said), 2, said)
        self.assertTrue(any("LoginPage" in m for m in said), said)
        self.assertTrue(any("SignupPage" in m for m in said), said)

    def test_a_memo_failure_never_silences_the_decision_log(self):
        orig = MF.state_changed_1202ad

        def boom(*a, **k):
            raise RuntimeError("memo down")

        MF.state_changed_1202ad = boom
        try:
            self._scaffold_twice()
        finally:
            MF.state_changed_1202ad = orig
        self.assertEqual(len(self._kept()), 3, self._kept())


class TheDecisionIsNotInsideTheAnnouncement(unittest.TestCase):
    """Structural, by AST: the placement IS the property."""

    def _branch(self):
        src = inspect.getsource(fs)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                try:
                    txt = ast.unparse(node)
                except Exception:
                    continue
                if "_say1203ou" in txt and "KEEPING the lane's auth page" in txt:
                    # the innermost `if _say1203ou:` that carries the log call
                    if isinstance(node.test, ast.Name) and node.test.id == "_say1203ou":
                        return node
        return None

    def test_the_announcement_is_guarded(self):
        self.assertIsNotNone(self._branch(), "no `if _say1203ou:` guards the #1197 line")

    def test_body_none_is_not_inside_the_guard(self):
        node = self._branch()
        self.assertIsNotNone(node)
        inside = ast.unparse(node)
        self.assertNotIn("_body = None", inside,
                         "the decision moved under the memo: a suppressed log would now "
                         "also suppress `_body = None` and the lane's page gets clobbered")

    def test_body_none_still_follows_the_guard(self):
        """...and it is still there at all, as a SIBLING of the guard.

        ★ The first version read `src[i:i+2000]` and #943's ratchet turned it red -- the
        third fixed-width source window this project has caught me writing. The property is
        structural, so it is read structurally: find the block that CONTAINS the guard and
        look at the statements after it."""
        # ★ ONE parse: a node from a different `ast.parse` is a different object, so
        # `st is node` can never match across two trees -- the first version of this check
        # looked for the holder in a freshly parsed tree and found nothing.
        tree = ast.parse(inspect.getsource(fs))
        node = holder = None
        for parent in ast.walk(tree):
            for field in ("body", "orelse", "finalbody"):
                block = getattr(parent, field, None)
                if not isinstance(block, list):
                    continue
                for st in block:
                    if (isinstance(st, ast.If) and isinstance(st.test, ast.Name)
                            and st.test.id == "_say1203ou"):
                        node, holder = st, block
                        break
                if node is not None:
                    break
            if node is not None:
                break
        self.assertIsNotNone(node, "no `if _say1203ou:` found in a readable block")
        after = holder[holder.index(node) + 1:]
        self.assertTrue(
            any(isinstance(st, ast.Assign)
                and any(getattr(t, "id", None) == "_body" for t in st.targets)
                and isinstance(st.value, ast.Constant) and st.value.value is None
                for st in after),
            "`_body = None` no longer follows the guard as its sibling: %s"
            % [type(st).__name__ for st in after[:4]])


class WhatTheCorpusSays(unittest.TestCase):
    _MEASURED = {"gm_tiktok_r190.log": (212, 5), "gm_tiktok_r183.log": (208, 17),
                 "gm_tiktok_r185.log": (110, 14), "gm_tiktok_r191.log": (88, 9)}

    def setUp(self):
        if not (_CORPUS.parent / "gm_tiktok_r190.log").is_file():
            self.skipTest("the run logs are not beside this checkout")

    def test_the_decision_repeated_itself_in_every_modern_log(self):
        checked = 0
        for name, (n, d) in sorted(self._MEASURED.items()):
            f = _CORPUS.parent / name
            if not f.is_file():
                continue
            checked += 1
            lines = [l for l in f.read_text(encoding="utf-8", errors="replace").splitlines()
                     if "#1197 KEEPING" in l]
            bodies = {l.split("#1197", 1)[1].strip() for l in lines}
            self.assertEqual((len(lines), len(bodies)), (n, d),
                             "%s: %d/%d, measured %d/%d" % (name, len(lines), len(bodies), n, d))
        self.assertEqual(checked, len(self._MEASURED),
                         "only %d of %d logs read" % (checked, len(self._MEASURED)))

    def test_the_sibling_914_line_is_a_measurement_not_a_heartbeat(self):
        """The #647 half: #914 is left unguarded because its lines are nearly all distinct.
        Counted on RAW lines -- a forward window on its trailing marker is what made it look
        like a heartbeat in the first place."""
        f = _CORPUS.parent / "gm_tiktok_r190.log"
        lines = [l for l in f.read_text(encoding="utf-8", errors="replace").splitlines()
                 if "LANE PAGE WITH OWN COMPONENTS" in l]
        bodies = {l.split("LANE PAGE WITH OWN COMPONENTS", 1)[1].strip() for l in lines}
        self.assertGreater(len(lines), 40, len(lines))
        self.assertGreater(len(bodies) / max(len(lines), 1), 0.9,
                           "#914 now repeats itself (%d lines, %d distinct); size a guard and "
                           "copy the #1203ou pattern" % (len(lines), len(bodies)))


if __name__ == "__main__":
    unittest.main()
