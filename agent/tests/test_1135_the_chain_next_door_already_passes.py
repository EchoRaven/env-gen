"""#1135: the registry knew another chain already passes that endpoint, and never said so.

#798 made the `business_chain_failing` task name the broken step instead of saying "read the
broken step". It still leaves the verifier with one fact — "my step got a 4xx" — which reads
equally as "the app is broken" and "my inputs are wrong". The registry holds the discriminator.

netflix-local-r2 had 3 failing chains and 2 of them had PASSING siblings on the exact endpoint
their broken step failed on:

    continue-watching_page  broke on POST /api/continue-watching
        → continue_watching_page_basic PASSES on it
    titles_page             broke on POST /api/titles/1/rating
        → rating_profile_state_transition, ..._v2, api_business_chain_no_path_vars_v4 PASS

`continue-watching_page` is the one that aborted the run. Its broken step posted another
user's `profile_id` and the app answered `{"detail":"profile_id does not belong to the
caller"}` — correct tenant isolation, a mis-authored chain. The verifier held that blocker for
79 minutes.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.remediation_dispatcher import (  # noqa: E402
    _canon_endpoint_1135, _passing_endpoint_index_1135,
)
from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402


def _step(method, path, ok, **kw):
    d = {"method": method, "path": path, "ok": ok}
    d.update(kw)
    return d


# the r2 registry, reduced to what the builder reads
R2_CHAINS = {
    "_meta": {"version": 1},
    "continue-watching_page": {
        "status": "failing",
        "last_result": {"steps": [
            _step("POST", "/api/continue-watching", False, status=400,
                  action="create continue-watching",
                  note='{"detail":"profile_id does not belong to the caller"}'),
        ]},
    },
    "continue_watching_page_basic": {
        "status": "passing",
        "last_result": {"steps": [
            _step("POST", "/api/continue-watching", True, status=201),
            _step("GET", "/api/continue-watching", True, status=200),
        ]},
    },
    "titles_page": {
        "status": "failing",
        "last_result": {"steps": [
            _step("POST", "/api/titles/1/rating", False, status=422, action="rate a title"),
        ]},
    },
    "rating_profile_state_transition": {
        "status": "passing",
        "last_result": {"steps": [_step("POST", "/api/titles/7/rating", True, status=201)]},
    },
}


class _Hubs:
    def __init__(self, chains):
        class _RH:
            def get_verification_chains(self_inner):
                return chains
        self.registryhub = _RH()


class _Orch:
    def __init__(self, chains):
        self.hubs = _Hubs(chains)


class TheDiscriminatorIsNamed(unittest.TestCase):

    def test_the_run_ending_chain_is_told_its_sibling_passes(self):
        lines = rd._chain_broken_detail_798(_Orch(R2_CHAINS))
        hit = [l for l in lines if l.startswith("continue-watching_page")]
        self.assertTrue(hit, lines)
        self.assertIn("#1135", hit[0])
        self.assertIn("continue_watching_page_basic", hit[0])
        self.assertIn("compare THEIR step inputs", hit[0])

    def test_a_different_row_of_the_same_endpoint_still_matches(self):
        """/api/titles/1/rating and /api/titles/7/rating are one endpoint."""
        hit = [l for l in rd._chain_broken_detail_798(_Orch(R2_CHAINS))
               if l.startswith("titles_page")]
        self.assertTrue(hit)
        self.assertIn("rating_profile_state_transition", hit[0])

    def test_the_original_798_payload_is_still_there(self):
        hit = [l for l in rd._chain_broken_detail_798(_Orch(R2_CHAINS))
               if l.startswith("continue-watching_page")][0]
        self.assertIn("POST /api/continue-watching", hit)
        self.assertIn("returned 400", hit)
        self.assertIn("profile_id does not belong", hit)


class ItStaysQuietWhenItHasNothingToSay(unittest.TestCase):

    def test_no_passing_sibling_means_no_hint(self):
        chains = {
            "lonely": {"status": "failing", "last_result": {"steps": [
                _step("POST", "/oauth/register", False, status=500)]}},
        }
        line = rd._chain_broken_detail_798(_Orch(chains))[0]
        self.assertNotIn("#1135", line)

    def test_a_chain_is_never_its_own_sibling(self):
        chains = {
            "self": {"status": "failing", "last_result": {"steps": [
                _step("GET", "/api/x", True, status=200),
                _step("POST", "/api/x", False, status=400)]}},
        }
        line = rd._chain_broken_detail_798(_Orch(chains))[0]
        self.assertNotIn("#1135", line)

    def test_only_PASSING_chains_count_as_evidence(self):
        chains = {
            "a": {"status": "failing", "last_result": {"steps": [
                _step("POST", "/api/x", False, status=400)]}},
            "b": {"status": "failing", "last_result": {"steps": [
                _step("POST", "/api/x", True, status=201)]}},
        }
        line = [l for l in rd._chain_broken_detail_798(_Orch(chains))
                if l.startswith("a ")][0]
        self.assertNotIn("#1135", line)


class TheCanonicaliser(unittest.TestCase):

    def test_ids_collapse_the_way_the_endpoint_registry_spells_them(self):
        self.assertEqual(_canon_endpoint_1135("post", "/api/titles/12/rating"),
                         "POST /api/titles/{}/rating")
        self.assertEqual(_canon_endpoint_1135("GET", "/api/v1/tenants/{tenant_id}"),
                         "GET /api/v1/tenants/{}")

    def test_it_does_not_collapse_real_words(self):
        self.assertEqual(_canon_endpoint_1135("GET", "/api/continue-watching"),
                         "GET /api/continue-watching")

    def test_query_strings_and_slashes_do_not_split_an_endpoint(self):
        self.assertEqual(_canon_endpoint_1135("GET", "/api/titles?limit=5"),
                         _canon_endpoint_1135("GET", "/api/titles/"))

    def test_junk_does_not_raise(self):
        for m, p in ((None, None), ("", ""), (5, 7)):
            self.assertTrue(_canon_endpoint_1135(m, p))

    def test_the_index_ignores_meta_and_malformed_records(self):
        self.assertEqual(_passing_endpoint_index_1135({"_meta": {"x": 1}, "bad": "nope"}), {})


if __name__ == "__main__":
    unittest.main()
