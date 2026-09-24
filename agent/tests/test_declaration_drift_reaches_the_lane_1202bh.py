r"""#1202bh: `apis_used` drift is detected precisely and told to nobody who can fix it.

`reconcile_ui_page_apis_1199` names both halves of the mismatch, and its own comment says
the finding belongs to "the lane that owns it" — then the caller logs a warning and stops.
`frontend_scaffold` files no tasks at all.

This one earns an inbox more than most. From the detector's own message: `apis_used` is
read by **84 call sites, including the gates**, so a wrong declaration makes a gate check
an endpoint the page never touches, and pass. netflix-r30 shipped

    browse_by_languages_page: apis_used declares ['/api/profiles'],
                              but the shipped page reaches ['/api/titles']

Reporting, still not rewriting: #1202d made this report-only after auto-reconciliation
produced false rewrites on tiktok, googlemaps and instagram. A task writes nothing to
disk, so that decision stands — which the last test pins.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))


def _block():
    """Landmark-bounded (#943): the marker to the end of its own handler."""
    from multi_agent.runtime import scaffolder
    src = Path(scaffolder.__file__).read_text(encoding="utf-8")
    i = src.index("#1202bh")
    j = src.index('"the declaration-drift task (#1202bh)"', i)
    return src[i:j]


class DeclarationDriftReachesTheLaneTests(unittest.TestCase):
    def test_the_finding_is_filed_not_only_logged(self):
        b = _block()
        self.assertIn("create_task", b)
        self.assertIn('assignee="frontend"', b)

    def test_both_halves_of_the_mismatch_are_named(self):
        """A page name alone is not actionable; the declared and actual paths are."""
        b = _block()
        self.assertIn('r.get("was")', b)
        self.assertIn('r.get("now")', b)

    def test_it_says_why_this_one_matters(self):
        """The gates read this field — that is the whole reason it is P1."""
        b = _block()
        self.assertIn("84 call sites", b)
        self.assertIn('priority="P1"', b)

    def test_it_still_does_not_rewrite(self):
        """#1202d's decision must survive: a task is not an auto-reconciliation."""
        b = _block()
        for forbidden in ("write_text(", "register_ui_page(", "update_ui_page("):
            self.assertNotIn(forbidden, b,
                             f"the drift path writes again ({forbidden}) — #1202d found "
                             "that produced false rewrites on three environments")

    def test_a_failure_to_file_is_announced(self):
        from multi_agent.runtime import scaffolder
        src = Path(scaffolder.__file__).read_text(encoding="utf-8")
        i = src.index("#1202bh")
        j = src.index("except Exception as _e1202bh", i)
        k = src.index("(#1202bh)", j)
        self.assertIn("warn_once_1201", src[j:k],
                      "a silent except here would recreate the defect being fixed")


if __name__ == "__main__":
    unittest.main()
