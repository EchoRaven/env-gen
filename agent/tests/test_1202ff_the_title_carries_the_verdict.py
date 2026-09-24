"""#1202ff: the empty-state task's TITLE must say what its body concluded.

#661 already distinguishes the two causes correctly in the description: with no
under-seeded table it says "this is probably NOT a seeding problem ... a read-path
bug ... Only add seed rows if you first confirm the backing table is genuinely
empty." The title was the literal "seed the missing rows" either way, so on that
branch it says the opposite of its own body.

That branch is the common one. Across every recent run with live row counts the
only tables ending at 0 are oauth_clients and oauth_authorization_codes --
infrastructure that is meant to be empty -- while 1-10 screens per run are flagged
empty_state. `workhub_list_tasks` returns titles and is the most-called tool in
the corpus, so a lane triaging its queue sees the title first.
"""
import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

VF = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent" / "runtime"
      / "visual_fidelity.py").read_text(encoding="utf-8")


def _block():
    i = VF.index("_title_1202ff = (")
    return VF[i:VF.index("description=", i)]


class TestTitleCarriesTheVerdict(unittest.TestCase):

    def test_the_title_is_no_longer_a_single_literal(self):
        self.assertNotIn(
            'title="Visual gate: screen(s) render an EMPTY state — seed the missing rows"',
            VF, "the unconditional title is what said the opposite of the body")

    def test_it_branches_on_the_same_fact_the_body_branches_on(self):
        """`_thin` is the audit's under-seeded list -- the body's own discriminator."""
        self.assertIn("if _thin else", _block())

    def test_the_seeding_title_survives_for_the_seeding_case(self):
        self.assertIn("seed the missing rows", _block())

    def test_the_other_title_names_the_read_path(self):
        other = _block()
        self.assertIn("read-path", other)
        self.assertIn("POPULATED", other)
        self.assertIn("NOT seeding", other)

    def test_the_title_is_what_create_task_receives(self):
        """A computed title nothing passes is the written-but-never-wired shape."""
        # Landmark-anchored (#943): the call it must reach is create_task, not a byte count.
        i = VF.index("_title_1202ff = (")
        after = VF[i:VF.index("description=", i)]
        self.assertTrue(re.search(r"title=_title_1202ff", after),
                        "create_task must be handed the computed title")

    def test_body_and_title_cannot_disagree_on_the_seeding_branch(self):
        """Both halves must read the same fact, or this regresses to r45's shape."""
        i = VF.index("_diag = (\"NOTE: the seed audit flags NO table")
        self.assertLess(i, VF.index("_title_1202ff = ("),
                        "the body's verdict is computed before the title that reports it")


if __name__ == "__main__":
    unittest.main()
