"""#1137: the framework's own auth template sent every logged-in user back to the front door.

`window.location.href = '/'` in `LoginPage.jsx` is not a lane bug. Both auth templates in
`frontend_scaffold.py` emit those exact bytes, and netflix r1, r2 and r3 shipped them
identically (`LoginPage.jsx:26-27`). For a product whose `/` is a signed-OUT marketing page —
which this same scaffold routes for media apps — a correct login returns the user to the page
they started on, `Sign In` still in the header.

It cost the delivery gate: r3's `validation_ui_evidence_failed` blocked 91 of 96 evaluations
and was the only failing check in its last three, the walk reporting "/genres returned 200 but
rendered login". The pages were fine; the session never got anywhere.

#1126/#1126b make the walk SEE it. This stops emitting it.
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

from multi_agent.runtime.frontend_scaffold import _post_auth_dest_1137  # noqa: E402

SCAFFOLD = (ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
            / "frontend_scaffold.py")


class TheDestinationRule(unittest.TestCase):

    def test_the_first_real_nav_route_wins(self):
        self.assertEqual(
            _post_auth_dest_1137([("Browse", "/browse"), ("Movies", "/movies")]), "/browse")

    def test_the_signed_out_root_is_never_the_destination(self):
        """That is the whole defect."""
        self.assertEqual(
            _post_auth_dest_1137([("Home", "/"), ("Browse", "/browse")]), "/browse")

    def test_auth_routes_are_never_the_destination(self):
        """Landing back on /login after logging in is the same bug wearing a hat."""
        self.assertEqual(
            _post_auth_dest_1137([("Sign in", "/login"), ("Sign up", "/signup"),
                                  ("Feed", "/feed")]), "/feed")

    def test_no_nav_routes_keeps_todays_behaviour(self):
        """Never WORSE than what it replaces."""
        for empty in ([], None, [("", "")], [("x", "   ")]):
            self.assertEqual(_post_auth_dest_1137(empty), "/")

    def test_malformed_input_does_not_raise(self):
        for bad in ("not a list", [("only-one",)], [None], 42):
            try:
                self.assertEqual(_post_auth_dest_1137(bad), "/")
            except Exception as exc:  # pragma: no cover
                self.fail(f"raised on {bad!r}: {exc}")


class EveryEmissionPathFillsIt(unittest.TestCase):
    """An unfilled placeholder would ship `location.href = '__AUTHDEST__'` — a hard break."""

    def setUp(self):
        self.src = SCAFFOLD.read_text(encoding="utf-8")

    def test_both_templates_use_the_placeholder(self):
        self.assertEqual(self.src.count("window.location.href = '__AUTHDEST__';"), 2)
        self.assertNotIn("      window.location.href = '/';\n    } catch (err)", self.src)

    def test_every_template_use_is_matched_by_a_fill(self):
        fills = self.src.count('.replace("__AUTHDEST__", _post_auth_dest_1137(nav_routes))')
        self.assertEqual(fills, 3, "three emitters render these templates; all must fill")

    def test_the_placeholder_never_reaches_a_generated_file(self):
        """count(placeholder) == 2 template uses + 3 fills, nothing stray."""
        self.assertEqual(self.src.count("__AUTHDEST__"), 5)


if __name__ == "__main__":
    unittest.main()
