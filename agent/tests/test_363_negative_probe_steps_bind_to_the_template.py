"""#363: a deliberate not-found probe is rejected for using a not-found id.

`register_verification_chain` refuses any step whose path does not resolve to a
registered endpoint. `_chain_eid` collapses `${var}` substitutions and LITERAL
NUMERIC segments (FIX #137, so the verifier binding a real seed id still matches
the registered `{id}` template) -- but nothing else.

So a cross-user / not-found probe is rejected for the exact property that makes
it a probe. Verified against the runs: every rejected step of this shape carries
an explicitly negative expectation.

    path=/api/videos/nonexistent-video-id-zzz    expect=[404]
    path=/api/videos/does_not_exist_${rand}      expect=[404]
    path=/api/sounds/does_not_exist_xyz          expect=[404]

40 chain registrations were rejected across r91/r92/r93. This matters because
`business_chain_isolation`'s own remediation text DEMANDS exactly this test:
"a SECOND user (or an unauthenticated request) reading another user's resource
MUST be refused (expect 401/403)". The verifier was told to write a probe the
registry then refused to accept.

Fix, deliberately narrow: only when a step expects NOTHING BUT not-found /
denied codes, retry its endpoint id with the final literal segment collapsed to
a path param. It still has to match a REGISTERED template -- a genuinely wrong
path is still rejected. `/api/videos/xyz/save` with expect [200,201,401,404] is
NOT a pure negative probe and keeps the old strict treatment.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _is_neg(step):
    from multi_agent.runtime.registryhub import is_negative_probe_step
    return is_negative_probe_step(step)


def _collapse(path):
    from multi_agent.runtime.registryhub import collapse_last_literal_segment
    return collapse_last_literal_segment(path)


class ANegativeProbeIsRecognised(unittest.TestCase):

    def test_a_404_only_step(self):
        self.assertTrue(_is_neg({"expect": [404]}))

    def test_denied_codes_count(self):
        self.assertTrue(_is_neg({"expect": [401]}))
        self.assertTrue(_is_neg({"expect": [403]}))
        self.assertTrue(_is_neg({"expect": [401, 403, 404]}))


class AMixedExpectationIsNotAProbe(unittest.TestCase):
    """`/api/videos/xyz/save` expects [200,201,401,404] -- it wants success too."""

    def test_success_in_the_set_disqualifies_it(self):
        self.assertFalse(_is_neg({"expect": [200, 201, 401, 404]}))

    def test_a_plain_success_step_is_not_a_probe(self):
        self.assertFalse(_is_neg({"expect": [200]}))

    def test_no_expectation_is_not_a_probe(self):
        self.assertFalse(_is_neg({}))
        self.assertFalse(_is_neg({"expect": []}))

    def test_a_500_expectation_is_not_a_not_found_probe(self):
        self.assertFalse(_is_neg({"expect": [500]}))


class TheCollapseIsMinimal(unittest.TestCase):

    def test_the_last_segment_becomes_a_param(self):
        self.assertEqual(_collapse("/api/videos/nonexistent-video-id-zzz"),
                         "/api/videos/{x}")

    def test_only_the_last_segment_moves(self):
        self.assertEqual(_collapse("/api/users/alice/follow"),
                         "/api/users/alice/{x}")

    def test_a_single_segment_path_is_left_alone(self):
        self.assertEqual(_collapse("/api"), "/api")

    def test_root_is_left_alone(self):
        self.assertEqual(_collapse("/"), "/")

    def test_a_trailing_slash_does_not_produce_an_empty_param(self):
        self.assertEqual(_collapse("/api/videos/"), "/api/{x}")


class TheStrictBehaviourSurvives(unittest.TestCase):
    """A genuinely unregistered path must still be refused."""

    def test_collapsing_does_not_invent_a_route(self):
        # the helper only rewrites; matching against the registry is the caller's
        # job, so a nonsense path still yields a nonsense (unmatchable) template
        self.assertEqual(_collapse("/totally/made/up"), "/totally/made/{x}")


if __name__ == "__main__":
    unittest.main()
