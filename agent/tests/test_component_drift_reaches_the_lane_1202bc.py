r"""#1202bc: the component-drift finding is computed, returned, and read by nobody.

`sync_ui_page_statuses` fills `out["component_drift"]` and warns, and its one caller
never touches the key. netflix-r31 reported 12 pages:

    COMPONENT DRIFT: ui_page `landing` declares 2 component(s) and the delivered page
    renders NONE of them (public_header, landing_hero)

The delivered LandingPage.jsx is 45 lines with no component tag and no `../components/`
import at all, so the finding is accurate rather than a naming mismatch. It is also not
the clobber loop wearing a different hat: r31 logged zero PROJECTION CLOBBER and zero
SCAFFOLD LOOP.

The frontend lane owns those pages and can fix this, which is what separates it from
#844 — so it gets a task, per #780.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))


def _block():
    """The wiring, landmark-bounded (#943): marker to the end of its own handler."""
    from multi_agent.runtime import scaffolder
    src = Path(scaffolder.__file__).read_text(encoding="utf-8")
    i = src.index("#1202bc")
    j = src.index('"the component-drift report (#1202bc)"', i)
    return src[i:j]


class ComponentDriftReachesTheLaneTests(unittest.TestCase):
    def test_the_returned_finding_is_now_read(self):
        self.assertIn('_pa.get("component_drift")', _block(),
                      "the key is still computed and ignored")

    def test_it_files_to_the_lane_that_owns_the_pages(self):
        b = _block()
        self.assertIn("create_task", b)
        self.assertIn('assignee="frontend"', b)

    def test_the_advice_is_the_actionable_one(self):
        """Naming the missing components is not enough — say where to put them."""
        b = _block()
        self.assertIn("src/components/", b)
        self.assertIn("import and render it", b)

    def test_it_ties_the_fix_to_surviving_the_projector(self):
        """#914/#1020 keeps a page built from ../components/; that is the same action."""
        self.assertIn("#914/#1020", _block())

    def test_a_failure_to_file_is_announced(self):
        """A silent except here would recreate the exact defect being fixed."""
        from multi_agent.runtime import scaffolder
        src = Path(scaffolder.__file__).read_text(encoding="utf-8")
        i = src.index("#1202bc")
        j = src.index("_pa.get(\"implemented\")", i)
        self.assertIn("warn_once_1201", src[i:j])


if __name__ == "__main__":
    unittest.main()
