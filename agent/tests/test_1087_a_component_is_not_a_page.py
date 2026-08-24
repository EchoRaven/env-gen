"""#1087 — every registered ui_component also got a page stub projected for it.

gmrun4's stores, verbatim: all 14 ui_components are ALSO present in the ui_pages store, each
with `component=''` and `route=''`. The page projector iterates `list_ui_pages()`, sees
`category_chips`, derives `CategoryChips` from the name and writes an 8-line stub —

    // framework-generated page (frontend_page_projector) — edits are overwritten
    export default function CategoryChips() { … }

— into `src/pages/CategoryChips.jsx`, while the REAL `src/components/CategoryChips.jsx` sits
next to it. Nothing imports the stub, so the coverage audit calls it a dead artifact and asks
the lane to remove or wire it; removing it is futile because the projector writes it again
next cycle. That is #201's wall ("a FRAMEWORK stub is regenerated every cycle — the lane
CANNOT edit it, so the remedy is non-actionable") on the frontend side.

Measured across 166 hub stores:

    ui_page records                                    1051
    ★ also registered as a ui_component                 243   (23.1%)
        of those, route is blank -> projected orphan     235
        of those, a real '/' route -> a genuine page       8

and of the 249 framework-projected orphan files left in the corpus, 178 are exactly this.

The rule keys on the more specific declaration: a name registered as a ui_component is a
component, so no page stub is projected for its blank-route page twin. The 8 records that
carry a real route are pages that happen to share a name and are untouched — as is every
route-less record that is NOT also a component, which #905/#906 measured to be mostly real
pages (643 of them) and which this must not touch.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.frontend_scaffold import drop_component_page_twins_1087  # noqa: E402
from multi_agent.runtime.registryhub import RegistryHub  # noqa: E402


class TheFilter(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rh_1087_"))
        self.rh = RegistryHub(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _names(self, pages):
        return [p.get("name") for p in drop_component_page_twins_1087(pages, self.rh)]

    def test_gmrun4s_shape_is_dropped(self):
        self.rh.register_ui_component(name="category_chips", component="CategoryChips",
                                      agent="frontend")
        pages = [{"name": "category_chips", "component": "", "route": ""},
                 {"name": "search", "component": "SearchPage", "route": "/search"}]
        self.assertEqual(self._names(pages), ["search"])

    def test_a_routed_twin_is_a_real_page_and_stays(self):
        """8 of the 243 carry a real route — a page that happens to share a component's name."""
        self.rh.register_ui_component(name="profile", component="Profile", agent="frontend")
        pages = [{"name": "profile", "component": "ProfilePage", "route": "/profile"}]
        self.assertEqual(self._names(pages), ["profile"])

    def test_a_route_less_page_that_is_NOT_a_component_stays(self):
        """#905/#906: 643 route-less records are real pages under src/pages/. Untouched."""
        pages = [{"name": "settings", "component": "SettingsPage", "route": ""}]
        self.assertEqual(self._names(pages), ["settings"])

    def test_nothing_is_dropped_when_no_components_are_registered(self):
        pages = [{"name": "a", "route": ""}, {"name": "b", "route": "/b"}]
        self.assertEqual(self._names(pages), ["a", "b"])


class ItNeverBreaksTheCaller(unittest.TestCase):
    """This runs inside the projection path — a fault here must not cost the app its pages."""

    def test_a_broken_registry_returns_the_pages_unchanged(self):
        class _Boom:
            def list_ui_components(self):
                raise RuntimeError("hub down")
        pages = [{"name": "a", "route": ""}]
        self.assertEqual(drop_component_page_twins_1087(pages, _Boom()), pages)

    def test_no_registry_returns_the_pages_unchanged(self):
        pages = [{"name": "a", "route": ""}]
        self.assertEqual(drop_component_page_twins_1087(pages, None), pages)

    def test_junk_entries_are_passed_through(self):
        pages = [None, "nonsense", {"name": "a", "route": "/a"}]
        self.assertEqual(drop_component_page_twins_1087(pages, None), pages)


class TheProjectionPathUsesIt(unittest.TestCase):

    def test_the_scaffolder_filters_before_projecting(self):
        from multi_agent.runtime import scaffolder
        src = Path(scaffolder.__file__).read_text(encoding="utf-8")
        i = src.index("scaffold_pages_from_contract(fe, ui_pages)")
        self.assertIn("drop_component_page_twins_1087", src[:i],
                      "components are still projected as pages")


if __name__ == "__main__":
    unittest.main()
