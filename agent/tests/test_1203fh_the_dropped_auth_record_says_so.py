r"""#1203fh: the framework drops every lane ui_page on /login|/signup, and said so to nobody.

`_ensure_framework_auth_pages` exists for a good reason -- the lane ships a dead/unwired login
or omits /signup, and the test-user walkthrough then cannot register, so the framework forces
its own wired form onto both routes and DISCARDS any lane-declared page there. The drop is
right. What was missing is that nothing downstream learned of it:

  * 38 runs across r57-r159 register such a record -- login_modal/LoginModalPage (r58, r105,
    r128, r132, r135, r140, r148, r158, r159 ...), NetflixLoginPage (netflix r8/r11/r22/r37),
    login_route/LoginRoute (r78, r82), LoginScreenPage (r130), plain Login/Signup (r57, r76);
  * `registryhub_ui_pages` keeps the record intact afterwards, still claiming `route=/login`,
    because #1202d found auto-reconciliation of lane declarations produces false rewrites;
  * so the only channel left was trial: r159's lane re-pointed /login and /signup at its own
    LoginModalPage/SignupModalPage at 07:34 while App.jsx still carried
    `@framework-managed-routes`, the 07:37 projection wrote it back, and only at 07:40 -- four
    App.jsx edits later -- did it reach the marker's documented escape hatch.

Two halves, two places, which is the #1203fg division applied deliberately:
  * the RULE ("those two routes stay framework-owned, wrap LoginPage instead") is constant in
    every run, so it ships in App.jsx's own header, where the agent about to edit the routes is
    already reading. Constant and unconditional on purpose: a header that varied per run would
    make the projection non-idempotent and cause spurious rewrites of a lane-owned file.
  * WHICH records were dropped is computed, so it goes to the run log via the scaffolder.

r159 is also the positive result worth keeping: once the lane owned the router it routed
/login at a surface that renders the framework's own `<LoginPage mode=... />` inside the feed
-- the modal design AND the auth guarantee, which is why the header names that shape.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_scaffold import (  # noqa: E402
    _ensure_framework_auth_pages, _render_routed_app, scaffold_pages_from_contract)

KEY = "auth_routes_taken_1203fh"


def _strip_comments(src: str) -> str:
    """#1202w3 / #1203fe: a comment is not output. Every positional or presence assertion
    about SOURCE below runs on the code, so the paragraph above cannot vouch for itself."""
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


class TheDropIsReported(unittest.TestCase):
    def test_lane_auth_record_lands_in_the_out_list(self):
        dropped: list = []
        out = _ensure_framework_auth_pages(
            [{"name": "login_modal", "route": "/login",
              "path": "app/frontend/src/pages/LoginModalPage.jsx"},
             {"name": "signup_modal", "route": "/signup",
              "path": "app/frontend/src/pages/SignupModalPage.jsx"},
             {"name": "for_you_feed", "route": "/", "component": "ForYouFeedPage"}],
            dropped)
        # r159's exact pair, verbatim from generated/tiktok-web-r159/shared/hubs.
        self.assertEqual(len(dropped), 2, dropped)
        joined = " | ".join(dropped)
        self.assertIn("login_modal @ /login", joined)
        self.assertIn("LoginModalPage.jsx", joined)
        self.assertIn("signup_modal @ /signup", joined)
        # the drop itself is unchanged: framework auth wins both routes, the rest survives
        self.assertEqual([p["route"] for p in out][:2], ["/login", "/signup"])
        self.assertEqual([p.get("component") for p in out][:2], ["LoginPage", "SignupPage"])
        self.assertIn("/", [p.get("route") for p in out])

    def test_no_lane_auth_record_reports_nothing(self):
        """Negative control: the announcement must not fire on the common case."""
        dropped: list = []
        _ensure_framework_auth_pages(
            [{"name": "for_you_feed", "route": "/", "component": "ForYouFeedPage"}], dropped)
        self.assertEqual(dropped, [])

    def test_out_list_is_optional(self):
        """The signature stays append-only -- test_frontend_auth_page_projection calls it
        positionally with one argument and must keep working (#782)."""
        out = _ensure_framework_auth_pages([{"route": "/login", "component": "MyBrokenLogin"}])
        self.assertEqual([p["route"] for p in out][:2], ["/login", "/signup"])


class TheProjectorSurfacesIt(unittest.TestCase):
    """End-to-end through the real caller, not the helper (#1203f6's lesson: a helper that
    reports to a return value nobody reads has reported nothing)."""

    def _tree(self) -> Path:
        d = Path(tempfile.mkdtemp())
        (d / "src" / "pages").mkdir(parents=True)
        (d / "src" / "App.jsx").write_text(
            "// @framework-managed-routes\n"
            "export default function App(){return null}\n", encoding="utf-8")
        return d

    def test_scaffold_returns_the_dropped_records(self):
        rep = scaffold_pages_from_contract(self._tree(), [
            {"name": "login_modal", "route": "/login",
             "path": "app/frontend/src/pages/LoginModalPage.jsx"},
            {"name": "for_you_feed", "route": "/", "component": "ForYouFeedPage"},
        ])
        self.assertNotIn("error", rep, rep)
        self.assertEqual(len(rep.get(KEY) or []), 1, rep.get(KEY))
        self.assertIn("login_modal @ /login", (rep.get(KEY) or [""])[0])

    def test_key_is_present_and_empty_when_nothing_was_dropped(self):
        """Absent vs empty matters: the consumer below reads `or []`, and a key that only
        appears on the bad path cannot be distinguished from a projection that never ran."""
        rep = scaffold_pages_from_contract(self._tree(), [
            {"name": "for_you_feed", "route": "/", "component": "ForYouFeedPage"}])
        self.assertIn(KEY, rep)
        self.assertEqual(rep[KEY], [])


class TheRuleShipsWhereTheEditorReads(unittest.TestCase):
    def test_header_names_both_routes_and_the_remedy(self):
        app = _render_routed_app([("LoginPage", "/login"), ("ForYouFeedPage", "/")])
        head = app.split("import {", 1)[0]
        self.assertIn("/login", head)
        self.assertIn("/signup", head)
        self.assertIn("LoginPage", head)          # names what to wrap
        self.assertIn("framework-owned", head)
        # the escape hatch it already documented is still there -- this adds, never replaces
        self.assertIn("marker line above", head)

    def test_the_addition_is_comment_only(self):
        """A rule written into a .jsx file must not become code: every added header line is a
        `//` comment, so Rollup sees exactly what it saw before."""
        app = _render_routed_app([("LoginPage", "/login")])
        head = app.split("import {", 1)[0]
        for line in head.splitlines():
            if line.strip():
                self.assertTrue(line.lstrip().startswith("//"), line)

    def test_header_is_identical_across_renders(self):
        """Unconditional on purpose: the same contract must render byte-identical App.jsx, or
        the projection rewrites a lane-owned file on every tick for no reason."""
        a = _render_routed_app([("LoginPage", "/login"), ("ForYouFeedPage", "/")])
        b = _render_routed_app([("LoginPage", "/login"), ("ForYouFeedPage", "/")])
        self.assertEqual(a, b)


class TheComputedHalfReachesARecipient(unittest.TestCase):
    """#1203f6: by CALL SITE and by dataflow, not "the key's name appears in the file" --
    that scope passed while the announcement was deleted, because another repair in the same
    module read a key of the same name."""

    def test_scaffolder_reads_the_key_off_this_projectors_result(self):
        src = _strip_comments((RUNTIME / "scaffolder.py").read_text(encoding="utf-8"))
        tree = ast.parse(src)
        found = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # the variable this projector's result was assigned to, in THIS function
            targets = set()
            for node in ast.walk(fn):
                if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                        and getattr(node.value.func, "id", "") == "scaffold_pages_from_contract"):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            targets.add(t.id)
            if not targets:
                continue
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id in targets
                        and node.args and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == KEY):
                    found.append(fn.name)
        self.assertTrue(found, "nothing reads %s off scaffold_pages_from_contract's result" % KEY)

    def test_the_names_are_in_the_warning_not_only_the_count(self):
        """#1202ds: a check that logs only its own name leaves the reader auditing blind. The
        dropped records themselves must be interpolated, and a truncated list must say how
        much it cut (#1034) -- which is what join_capped is for.

        Asserted over the AST, not a byte window: #943's ratchet is right that a window
        breaks when a comment grows, and the first version of this test both tripped that
        ratchet AND anchored on the ticket -- which also appears inside the warning's own
        message -- putting the join_capped call, emitted earlier, outside the window."""
        tree = ast.parse((RUNTIME / "scaffolder.py").read_text(encoding="utf-8"))
        warnings = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "warning"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "_logger"):
                continue
            if (node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.startswith("#1203fh")):
                warnings.append(node)
        self.assertEqual(len(warnings), 1, "expected exactly one #1203fh warning")
        call = warnings[0]
        rendered = {ast.dump(a) for a in call.args[1:]}
        # the count AND the names, each as its own interpolated argument
        self.assertTrue(
            any("'len'" in d and "_authtaken1203fh" in d for d in rendered),
            "the warning does not interpolate how many records were dropped")
        self.assertTrue(any("_shown1203fh" in d for d in rendered),
                        "the warning does not interpolate WHICH records were dropped")
        # ... and the VALUE that reaches it went through join_capped, so a truncated list
        # says how much it cut (#1034) instead of silently showing the first few.
        #
        # Tied to the assignment of that exact variable, not to an import anywhere in the
        # enclosing function: the first version asked whether `join_capped` was imported in
        # the function containing the warning, and that function already imports it for
        # #1202bh -- so replacing this call with a bare `", ".join(...[:4])` left the test
        # GREEN. Same wrong scope #1203f6 was written about, found the same way (by mutating).
        fn = next(f for f in ast.walk(tree)
                  if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and any(n is call for n in ast.walk(f)))
        aliases = {a.asname or a.name
                   for imp in ast.walk(fn) if isinstance(imp, ast.ImportFrom)
                   for a in imp.names if a.name == "join_capped"}
        self.assertTrue(aliases, "join_capped is not imported where the warning is built")
        capped = [n for n in ast.walk(fn)
                  if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "_shown1203fh"
                          for t in n.targets)
                  and isinstance(n.value, ast.Call)
                  and isinstance(n.value.func, ast.Name) and n.value.func.id in aliases]
        self.assertTrue(capped,
                        "what the warning prints is not produced by join_capped")


if __name__ == "__main__":
    unittest.main()
