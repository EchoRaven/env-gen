r"""#1203n5: #363 binds a negative probe by collapsing the LAST segment, and a nested action
route puts the probe's bogus id one segment in.

#363's rule: a purely-negative probe uses an id that must not exist, so bind it to the
registered TEMPLATE rather than refusing the chain "for the property that makes it a probe".
Its collapse is "minimal on purpose: one segment" -- the FINAL one. That is right for a flat
by-id probe and cannot work for a nested action route:

    /api/users/absent_creator_{}/follow   --last-->  /api/users/absent_creator_{}/{x}

which matches nothing, while `/api/users/{username}/follow` sits registered (POST and DELETE,
both `implemented`, in r190). So the chain is refused with "these steps reference endpoints
NOT registered in RegistryHub" -- the message r190's verifier hit a dozen times while trying
to write "follow a user who does not exist -> 404".

MEASURED over the 37 run logs that carry such a rejection AND still have their endpoint
registry: 94 rejected items are bound by the final-segment collapse (#363's population) and
**84 can only be bound by collapsing a NON-final segment** --
`/api/videos/not-real/comments` (r116), `/api/videos/missing-{}/comments` (r170),
`/api/videos/video-{}-absent/comments` (r133), `/api/users/therock/videos` (r120). 73 match
no template under any collapse and stay rejected.

HONEST CAVEAT, recorded because the method bit me elsewhere today: a further 42 rejected
items DO match the final registry, which is the timeline rather than this rule -- the
rejection happened before the endpoint was registered. The counts above are upper bounds.

The acceptance guard is unchanged: the collapsed path must match a REGISTERED template, and
only a purely-negative step (`expect` ⊆ {401,403,404,410}) is collapsed at all.
"""
import unittest

from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    collapse_candidates_1203n5 as candidates,
    collapse_last_literal_segment as collapse_last,
    is_negative_probe_step,
)


class TheNestedProbeReachesItsTemplate(unittest.TestCase):
    def test_r190s_follow_probe(self):
        self.assertIn("/api/users/{x}/follow",
                      list(candidates("/api/users/absent_creator_{}/follow")))

    def test_the_corpus_shapes(self):
        for path, want in (
            ("/api/videos/not-real/comments", "/api/videos/{x}/comments"),
            ("/api/videos/missing-{}/comments", "/api/videos/{x}/comments"),
            ("/api/videos/video-{}-absent/comments", "/api/videos/{x}/comments"),
            ("/api/users/therock/videos", "/api/users/{x}/videos"),
        ):
            with self.subTest(path=path):
                self.assertIn(want, list(candidates(path)))

    def test_the_old_last_segment_form_comes_FIRST(self):
        """A path #363 already accepted must take the same decision by the same route."""
        p = "/api/users/nobody"
        self.assertEqual(next(iter(candidates(p))), collapse_last(p))

    def test_a_flat_probe_still_yields_its_template(self):
        self.assertIn("/api/users/{x}", list(candidates("/api/users/nobody")))

    def test_every_segment_is_offered_once(self):
        got = list(candidates("/a/b/c"))
        self.assertEqual(got, ["/a/b/{x}", "/a/{x}/c", "/{x}/b/c"])


class ItRefusesToGuessWhereThereIsNothingToCollapse(unittest.TestCase):
    def test_a_single_segment_path(self):
        self.assertEqual(list(candidates("/health")), [])

    def test_a_relative_path(self):
        self.assertEqual(list(candidates("api/users/x")), [])

    def test_empty_and_none(self):
        self.assertEqual(list(candidates("")), [])
        self.assertEqual(list(candidates(None)), [])


class OnlyAPurelyNegativeStepIsCollapsedAtAll(unittest.TestCase):
    """#363's gate, unchanged by this ticket -- asserted so widening the collapse cannot be
    read as widening who gets it."""

    def test_a_404_only_step_qualifies(self):
        self.assertTrue(is_negative_probe_step({"expect": [404]}))

    def test_401_403_410_qualify(self):
        for code in (401, 403, 410):
            with self.subTest(code=code):
                self.assertTrue(is_negative_probe_step({"expect": [code]}))

    def test_a_step_that_also_wants_success_does_not(self):
        self.assertFalse(is_negative_probe_step({"expect": [200, 404]}))
        self.assertFalse(is_negative_probe_step({"expect": [201, 401, 404]}))

    def test_no_expectation_does_not(self):
        self.assertFalse(is_negative_probe_step({}))
        self.assertFalse(is_negative_probe_step({"expect": []}))


class TheRegistryUsesEveryCandidate(unittest.TestCase):
    def _probe_branch(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import registryhub
        tree = ast.parse(inspect.getsource(registryhub))
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and "collapse_candidates_1203n5" in ast.dump(node.iter):
                return node
        return None

    def test_the_acceptance_loops_over_the_candidates(self):
        self.assertIsNotNone(self._probe_branch(),
                             "the registry still collapses only the final segment")

    def test_it_still_requires_a_registered_template(self):
        node = self._probe_branch()
        import ast
        dump = ast.dump(node)
        self.assertIn("registered_ids", dump,
                      "a collapsed path must still have to match a registered template")

    def test_it_returns_false_when_no_candidate_matches(self):
        import ast
        node = self._probe_branch()
        tail = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        self.assertTrue(tail, "the loop must still be able to refuse")


if __name__ == "__main__":
    unittest.main()
