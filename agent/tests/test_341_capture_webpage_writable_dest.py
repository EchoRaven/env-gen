"""#341: capture_webpage defaulted into a route nobody may write.

`screenshots/` is declared read-only in ROUTING_TABLE --
`("screenshots/", "base", frozenset(), "reference screenshots -- read-only")`
-- because it holds the ground-truth references the visual gate diffs against.
Yet capture_webpage's default destination was `screenshots/<domain>.png`, and
its schema advertised exactly that, so agents also passed explicit
`screenshots/...` paths.

Result: `Write permission denied ... ['screenshots/login_current.png']` across
**23 distinct runs** (tiktok, instagram, googlemaps), attributed to the
frontend lane. FIX #110 exists precisely so the frontend can SEE its own render
before self-certifying UI fidelity, and it landed in a route nobody can write.

The route must stay read-only -- opening it would let a lane overwrite the
references the gate scores against. So the TOOL moves: it writes to
`design/captures/`, which is granted to backend / frontend / design_analyst.

An explicit `screenshots/...` path is redirected there rather than refused: the
agent is trying to do the right thing, the schema taught it the wrong directory,
and a hard failure costs a turn to rediscover. The result reports the redirect
so nothing is silent.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CAPTURE_DIR = "design/captures"


def _workspace(tmp):
    from multi_agent.runtime.path_routed_workspace import PathRoutedWorkspace
    return PathRoutedWorkspace(base_root=tmp, code_root=tmp / "code")


class TheDestinationIsWritable(unittest.TestCase):

    def test_frontend_may_write_the_new_capture_dir(self):
        with TemporaryDirectory() as tmp:
            ws = _workspace(Path(tmp))
            self.assertTrue(
                ws.is_write_allowed(f"{CAPTURE_DIR}/localhost_8080.png", "frontend"))

    def test_screenshots_route_stays_read_only(self):
        """It holds the visual gate's ground truth -- must NOT be opened up."""
        with TemporaryDirectory() as tmp:
            ws = _workspace(Path(tmp))
            for role in ("frontend", "backend", "orchestrator", "verifier"):
                self.assertFalse(
                    ws.is_write_allowed("screenshots/ref.png", role),
                    f"{role} must not be able to write the reference dir")


class TheToolNoLongerAimsAtAReadOnlyRoute(unittest.TestCase):

    def _src(self):
        from tools import image_search_tools
        return Path(image_search_tools.__file__).read_text()

    def test_default_destination_is_the_capture_dir(self):
        src = self._src()
        self.assertIn(f'_CAPTURE_DIR = "{CAPTURE_DIR}"', src)
        self.assertNotIn('resolve("screenshots")', src)

    def test_schema_advertises_the_writable_dir_as_the_default(self):
        """It may still MENTION screenshots/ -- as the read-only dir to avoid --
        but must not present it as the default.

        Asserted against the source: this tool builds its parameter schema
        inside a method (it has no class-level PARAMETERS like the hub tools),
        so there is no object to introspect.
        """
        src = self._src()
        self.assertIn(f"default: {CAPTURE_DIR}/", src)
        self.assertNotIn("default: screenshots", src)
        self.assertIn("read-only reference dir", src)

    def test_the_usage_example_no_longer_points_at_the_read_only_dir(self):
        self.assertNotIn('"screenshots/github.png"', self._src())


class ExplicitReadOnlyPathIsRedirected(unittest.TestCase):

    def _redirect(self, path):
        from tools.image_search_tools import _redirect_readonly_capture_path
        return _redirect_readonly_capture_path(path)

    def test_screenshots_path_is_moved_to_the_capture_dir(self):
        self.assertEqual(
            self._redirect("screenshots/login_current.png"),
            f"{CAPTURE_DIR}/login_current.png")

    def test_leading_slash_form_is_handled(self):
        self.assertEqual(
            self._redirect("/screenshots/x.png"), f"{CAPTURE_DIR}/x.png")

    def test_nested_path_keeps_only_its_basename(self):
        self.assertEqual(
            self._redirect("screenshots/a/b/c.png"), f"{CAPTURE_DIR}/c.png")

    def test_an_unrelated_path_is_untouched(self):
        for p in (f"{CAPTURE_DIR}/x.png", "design/x.png", "app/frontend/x.png"):
            self.assertEqual(self._redirect(p), p)

    def test_empty_path_is_untouched(self):
        self.assertEqual(self._redirect(""), "")


if __name__ == "__main__":
    unittest.main()
