r"""#1202bk: skills cite paths from a different repository as if a lane could open them.

`multi-tenancy-pattern` and `env-oauth-blueprint` say so — "reference examples from the
product these envs ship into ... Treat them as shape, not literal". `new-env-bootstrap`
(17 references) and `ui-bootstrap` (11) said nothing, and they present the paths in
lookup tables that read as instructions:

    | Tenant picker drop-in | `src/envs/paypal/paypal_ui/src/TenantPicker.jsx` |

A lane's workspace holds app/, design/, shared/ and its worktree — checked against
netflix-local-r32, which has no `src/` at all. So a lane following that table opens
nothing, learns nothing from the failure, and the skill never told it why.

The note has to come BEFORE the first reference to do any work, which is what the second
test checks — my first attempt placed it correctly and my first VERIFICATION said
otherwise, because the note itself contains `src/envs/` and matched ahead of the real one.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
_SKILLS = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
           / "bundled_skills")
_NOTE = "do NOT exist in your workspace"
_CITING = ("new-env-bootstrap", "ui-bootstrap")


def _lines(name):
    return (_SKILLS / name / "SKILL.md").read_text(encoding="utf-8").splitlines()


class CrossRepoPathsAreLabelledTests(unittest.TestCase):
    def test_every_skill_citing_cross_repo_paths_says_so(self):
        for name in _CITING:
            self.assertTrue(any(_NOTE in ln for ln in _lines(name)),
                            f"{name} cites src/envs/ paths with no note that they are "
                            "not in the lane's workspace")

    def test_the_note_precedes_the_first_reference(self):
        """A disclaimer after the table is a disclaimer nobody reads in time."""
        for name in _CITING:
            lines = _lines(name)
            note = next(i for i, ln in enumerate(lines) if _NOTE in ln)
            first = next(i for i, ln in enumerate(lines)
                         if "src/envs/" in ln and _NOTE not in ln)
            self.assertLess(note, first, f"{name}: the note comes after the first path")

    def test_the_note_says_what_the_workspace_does_hold(self):
        """'Not here' is half an answer; the lane still needs to know where to look."""
        for name in _CITING:
            body = "\n".join(_lines(name))
            self.assertIn("app/", body)
            self.assertIn("worktree", body)

    def test_the_skills_that_already_had_a_note_are_untouched(self):
        for name in ("multi-tenancy-pattern", "env-oauth-blueprint"):
            body = "\n".join(_lines(name))
            self.assertIn("reference examples", body)


if __name__ == "__main__":
    unittest.main()
