r"""#1203mu: a resume was handed a different brief, and re-contracted a half-built app.

The checkpoint records `description` -- the brief the first attempt ran on -- and `--resume`
takes whatever the command line passes and never compares the two.

MEASURED on tiktok-web-r190, 2026-10-16. The first attempt ran on a 1024-char inline brief
and delivered M1 (tag 1.0.0) and M2 (tag 1.1.0). Its resume was launched from a 2798-char
DESCRIPTION.txt for the same product -- same --design-input, same model, same 11 reference
images. The description is hashed into #1202ca's fingerprint (`req_sha` ad60fec6.. vs
54e91c7c..), so the reuse missed and the reference spec was recompiled into a different
contract:

    screens  12 -> 11   (signup_modal gone)
    endpoints 24 -> 21  with near-zero spelling overlap:
        GET /api/videos/feed         -> GET /api/videos
        POST /auth/signup            -> POST /auth/register
        /api/users/:username/follow  -> /api/users/{id}/follow
        GET /api/creators/suggested  -> GET /api/suggested-creators
    entities 12 -> 11   user/video/comment -> users/videos/comments

M1 and M2 implement the OLD names. Every gate after the recompile measures the delivered app
against the new spelling, so work that exists reads as missing endpoints -- and M3's lane was
already being told to build `/api/suggested-creators` beside M2's `/api/creators/suggested`.

#1202eo already warns at this exact moment and then recompiles anyway; its prose named
--design-input ("the wrong DESIGN was passed", which is what googlemaps-r16 was), and on r190
that was the one input that had NOT changed. Both halves are fixed here: the guard refuses
before the compile, and the warning names the input that actually diverged.
"""
import ast
import inspect
import unittest
from pathlib import Path

# The same file the orchestrator imports as the top-level `checkpoint` module (#895); the
# tests reach it by package path, which is the root that is on sys.path here.
from env_generator.llm_generator.checkpoint import (
    rebrief_verdict_1203mu as verdict,
    REBRIEF_OPT_IN_1203MU,
)

R190_OLD = ("TikTok web clone (desktop web, dark theme, brand red #FE2C55). Auth: login "
            "modal (QR / phone-email / social) + signup.")
R190_NEW = ("Build a pixel-faithful, fully-functional TikTok desktop-web clone -- a "
            "short-form vertical video feed. Match every reference screenshot exactly.")
DELIVERED = {"milestone:1:M1-auth-foryou-readonly@1.0.0": "complete",
             "milestone:2:M2-explore-and-engagement@1.1.0": "complete",
             "milestone:3:M3-suggested-creators-and-follows@1.2.0": "planning"}


class TheSameBriefSaysNothing(unittest.TestCase):
    def test_identical_brief_is_silent(self):
        self.assertEqual(verdict(R190_OLD, R190_OLD, DELIVERED), ("", ""))

    def test_identical_brief_is_silent_even_with_no_phases(self):
        self.assertEqual(verdict(R190_OLD, R190_OLD, {}), ("", ""))


class ADeliveredMilestoneMakesItARefusal(unittest.TestCase):
    def test_r190_shape_refuses(self):
        sev, msg = verdict(R190_OLD, R190_NEW, DELIVERED)
        self.assertEqual(sev, "refuse")

    def test_the_refusal_names_both_briefs_and_where_they_diverge(self):
        _, msg = verdict(R190_OLD, R190_NEW, DELIVERED)
        self.assertIn(str(len(R190_OLD)), msg)
        self.assertIn(str(len(R190_NEW)), msg)
        self.assertIn("offset 0", msg)  # the two r190 briefs differ from the first character

    def test_the_refusal_names_the_milestones_that_are_already_built(self):
        _, msg = verdict(R190_OLD, R190_NEW, DELIVERED)
        self.assertIn("milestone:1:M1-auth-foryou-readonly@1.0.0", msg)
        self.assertIn("milestone:2:M2-explore-and-engagement@1.1.0", msg)
        self.assertNotIn("milestone:3", msg)   # planning, not delivered against

    def test_the_refusal_says_where_the_stored_brief_lives_and_how_to_override(self):
        _, msg = verdict(R190_OLD, R190_NEW, DELIVERED,
                         checkpoint_path="/x/generated/tiktok-web-r190/.checkpoint")
        self.assertIn("/x/generated/tiktok-web-r190/.checkpoint", msg)
        self.assertIn(REBRIEF_OPT_IN_1203MU, msg)

    def test_a_later_divergence_reports_its_own_offset(self):
        a = "same prefix. then A tail."
        b = "same prefix. then B tail."
        _, msg = verdict(a, b, DELIVERED)
        self.assertIn("offset %d" % a.index("A"), msg)


class NothingDeliveredYetIsOnlyANotice(unittest.TestCase):
    def test_no_milestone_complete_continues(self):
        sev, msg = verdict(R190_OLD, R190_NEW,
                           {"milestone:1:M1@1.0.0": "planning"})
        self.assertEqual(sev, "notice")
        self.assertIn("No milestone is complete", msg)

    def test_a_complete_NON_milestone_phase_is_not_delivered_work(self):
        """`agent_workflow: complete` is not a tag anyone shipped against."""
        sev, _ = verdict(R190_OLD, R190_NEW, {"agent_workflow": "complete"})
        self.assertEqual(sev, "notice")

    def test_the_notice_still_states_the_consequence(self):
        _, msg = verdict(R190_OLD, R190_NEW, {})
        self.assertIn("DIFFERENT CONTRACT", msg)


class WhitespaceCountsBecauseTheFingerprintHashesIt(unittest.TestCase):
    def test_a_trailing_newline_is_a_different_brief(self):
        """#1202ca hashes the text; `$(cat FILE)` vs an inline literal is exactly this."""
        sev, _ = verdict(R190_OLD, R190_OLD + "\n", DELIVERED)
        self.assertEqual(sev, "refuse")

    def test_the_offset_points_past_the_shorter_brief(self):
        _, msg = verdict(R190_OLD, R190_OLD + "\n", DELIVERED)
        self.assertIn("offset %d" % len(R190_OLD), msg)


class AnUncomparableCheckpointIsNotAPass(unittest.TestCase):
    def test_no_stored_description_says_it_could_not_tell(self):
        """#883: having nothing to compare is not a verdict of 'same'."""
        sev, msg = verdict("", R190_NEW, DELIVERED)
        self.assertEqual(sev, "notice")
        self.assertIn("could NOT be checked", msg)

    def test_an_empty_passed_brief_is_also_reported(self):
        sev, _ = verdict(R190_OLD, "", DELIVERED)
        self.assertEqual(sev, "refuse")


class TheOptInIsTheOnlyWayPast(unittest.TestCase):
    def test_opt_in_downgrades_to_notice(self):
        sev, msg = verdict(R190_OLD, R190_NEW, DELIVERED, allow_rebrief=True)
        self.assertEqual(sev, "notice")

    def test_opt_in_still_states_what_it_is_letting_through(self):
        _, msg = verdict(R190_OLD, R190_NEW, DELIVERED, allow_rebrief=True)
        self.assertIn("DIFFERENT CONTRACT", msg)
        self.assertIn("already COMPLETE", msg)
        self.assertIn("Proceeding because", msg)


def _resume_block_1203mu():
    """The orchestrator statements that run when `resume` is true, as AST."""
    from env_generator.llm_generator.multi_agent import orchestrator as orch
    src = inspect.getsource(orch)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("info", "error"):
            for a in node.args:
                if isinstance(a, (ast.Constant, ast.JoinedStr)):
                    txt = a.value if isinstance(a, ast.Constant) else "".join(
                        v.value for v in a.values if isinstance(v, ast.Constant))
                    if isinstance(txt, str) and "Resuming from checkpoint" in txt:
                        return tree
    raise AssertionError("the resume announcement is gone — find where resume lives now")


class TheGuardIsWiredIntoTheResumePath(unittest.TestCase):
    def test_the_orchestrator_calls_the_verdict(self):
        tree = _resume_block_1203mu()
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "rebrief_verdict_1203mu"]
        self.assertEqual(len(calls), 1, "expected exactly one call site in the orchestrator")

    def test_it_is_handed_the_brief_this_launch_passed(self):
        tree = _resume_block_1203mu()
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "rebrief_verdict_1203mu")
        self.assertIn("goal", [getattr(a, "id", "") for a in call.args],
                      "the verdict must compare against the brief this launch passed")

    def test_a_refusal_raises(self):
        """A warning that is only logged is what #1202eo already was."""
        tree = _resume_block_1203mu()
        raises = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                cmp_src = ast.dump(node.test)
                if "_sev_1203mu" in cmp_src and "refuse" in cmp_src:
                    raises = [n for n in ast.walk(node) if isinstance(n, ast.Raise)]
        self.assertTrue(raises, "nothing raises when the verdict is 'refuse'")


class TheRecompileWarningNamesTheInputThatDiverged(unittest.TestCase):
    """#1203j2: a false sentence in the framework is its own defect.

    Asserted on the LITERAL inside the logger call, not on the file text — the docstring and
    the comments above it quote the old wording on purpose, and a text search would be fed by
    them (#1203l5's mirror trap).
    """

    def _warning_text(self):
        from env_generator.llm_generator.multi_agent.runtime import reference_materials as rm
        tree = ast.parse(inspect.getsource(rm))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "warning":
                for a in node.args:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                            and "#1202eo" in a.value:
                        return a.value
        raise AssertionError("#1202eo's warning literal is gone")

    def test_it_names_the_description_as_a_possible_cause(self):
        self.assertIn("--description", self._warning_text())

    def test_it_still_names_the_design_input(self):
        self.assertIn("--design-input", self._warning_text())

    def test_it_no_longer_blames_the_design_alone(self):
        self.assertNotIn("usually means the wrong DESIGN was passed", self._warning_text())

    def test_it_points_at_the_guard_that_can_refuse(self):
        self.assertIn("#1203mu", self._warning_text())


if __name__ == "__main__":
    unittest.main()
