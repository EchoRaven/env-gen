"""#1126b: the post-login check had a SECOND copy, and #1126 only reached the first.

`test_user_runner` asks whether the login landed somewhere that requires auth (#1126).
`test_user_validation` runs its own auth flow — the one whose record reaches
`test_user_reports/*.json` as `ui_flows` — and its check was weaker still:

    moved = not page.url.rstrip("/").endswith(route)
    ok = bool(token) or moved        # OR: a stored token passes, wherever it landed

netflix-local-r3 shipped `window.location.href = '/'` with `/` routed to `<LandingPage/>` —
the signed-out page, `Sign In` still in its header. This function recorded
`{flow: signup, ok: True, token_stored: True, navigated: True}` and `ui_flows.passed = True`,
while the run's own ui_flow checks failed with "/genres returned 200 but rendered login".
Three runs in a row (r1, r2, r3) shipped that redirect and #1126 fired ZERO times in r3,
because the flow that runs here is not the one it was applied to. #665: the copy drifts.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

VALIDATION = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
              / "test_user_validation.py")


class TheSecondCopyNowAsksWhereItLanded(unittest.TestCase):

    def setUp(self):
        self.src = VALIDATION.read_text(encoding="utf-8")

    def test_it_calls_the_landing_predicate(self):
        self.assertIn("_landed_in_the_app_1126", self.src)
        self.assertIn("_LOGIN_AFFORDANCE_JS", self.src)

    def test_it_reuses_rather_than_restates_the_rule(self):
        """A third copy is how this defect happened in the first place."""
        self.assertIn("from .test_user_runner import", self.src)
        self.assertNotIn("def _landed_in_the_app_1126", self.src,
                         "the predicate must live in ONE place")

    def test_the_or_semantics_are_untouched(self):
        """#1126b withdraws a false success; it does not tighten token-or-moved."""
        self.assertIn("ok = bool(token) or moved", self.src)

    def test_the_probe_failing_cannot_fail_a_good_login(self):
        i = self.src.index("#1126b")
        block = self.src[i:self.src.index("if ok:\n                        _note = \"\"", i)]
        self.assertIn("except Exception:", block)
        self.assertIn("pass", block)


class ThePredicateItBorrowsStillBehaves(unittest.TestCase):
    """Borrowed logic must keep the conservatism #1126 was built with."""

    def test_the_r3_shape_is_rejected(self):
        from multi_agent.runtime.test_user_runner import _landed_in_the_app_1126 as landed
        self.assertFalse(landed("/", "/login", login_affordance=True))

    def test_a_real_destination_still_passes(self):
        from multi_agent.runtime.test_user_runner import _landed_in_the_app_1126 as landed
        self.assertTrue(landed("/profiles", "/login", login_affordance=True))

    def test_no_affordance_means_no_complaint(self):
        from multi_agent.runtime.test_user_runner import _landed_in_the_app_1126 as landed
        self.assertTrue(landed("/", "/login", login_affordance=False))


if __name__ == "__main__":
    unittest.main()
