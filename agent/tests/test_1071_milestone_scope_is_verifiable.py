"""#1071 — the milestone-scoped gate had never run, in a test or in a run.

`ENVGEN_MILESTONE_SCOPED_GATE` scopes the structural-task gate to THIS milestone's
declared endpoints on an intermediate milestone, "so it isn't blocked on
later-milestone surface" — the behaviour asked for directly ("each milestone
should only be judged on the pages it is meant to finish").

It is env-gated and default-off, which is a deliberate opt-in, not a bug. What was
a gap: across the 201 kept run logs it is enabled 0 times, and no test named it
either. A path that has never executed anywhere is indistinguishable from one that
does not work — the shape #1048 and #1062 both turned out to be.

Its inputs check out — `description_slice` is a real milestone-registry key and
the orchestrator's `_current_milestone` is the registry dict — so this pins the
decision itself, extracted as a pure function so it can be exercised without an
orchestrator:

  * OFF by default, and byte-identical (None) when off;
  * None on the FINAL milestone, whatever the flag says;
  * None when the slice names no endpoint — "never gates on an empty set";
  * verb-prefixed paths win over the bare /api fallback;
  * the result is deduped and sorted, so the scope is stable across ticks.
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

from multi_agent.orchestrator import _milestone_endpoint_scope_1071 as _scope  # noqa: E402

_M = {"description_slice": "Build GET /api/videos and POST /api/videos/{id}/like"}


class ItIsOffUnlessAskedFor(unittest.TestCase):

    def test_default_off_means_no_scope(self):
        self.assertIsNone(_scope(_M, is_final=False, enabled=False))

    def test_the_final_milestone_is_never_scoped(self):
        """The last milestone owns the whole app; scoping it would hide real gaps."""
        self.assertIsNone(_scope(_M, is_final=True, enabled=True))


class ItScopesToThisMilestonesEndpoints(unittest.TestCase):

    def test_verb_prefixed_paths_are_extracted(self):
        got = _scope(_M, is_final=False, enabled=True)
        self.assertEqual(got, {"endpoint_paths": ["/api/videos", "/api/videos/{id}/like"]})

    def test_bare_api_paths_are_the_fallback(self):
        m = {"description_slice": "the /api/titles list and /api/my-list"}
        self.assertEqual(_scope(m, is_final=False, enabled=True),
                         {"endpoint_paths": ["/api/my-list", "/api/titles"]})

    def test_verb_form_wins_over_the_bare_fallback(self):
        m = {"description_slice": "GET /api/a mentions /api/b in passing"}
        self.assertEqual(_scope(m, is_final=False, enabled=True),
                         {"endpoint_paths": ["/api/a"]})

    def test_a_path_param_keeps_its_closing_brace(self):
        """The punctuation trim must not eat `}` — it terminates a path param."""
        m = {"description_slice": "GET /api/videos/{id}, then DELETE /api/videos/{id}."}
        self.assertEqual(_scope(m, is_final=False, enabled=True),
                         {"endpoint_paths": ["/api/videos/{id}"]})

    def test_prose_punctuation_is_trimmed(self):
        """`\\S+` swallowed it, so `/api/b,` and `/api/b` counted as two endpoints
        and neither of the comma'd ones matched anything real."""
        m = {"description_slice": "GET /api/b, POST /api/a; then GET /api/c."}
        self.assertEqual(_scope(m, is_final=False, enabled=True),
                         {"endpoint_paths": ["/api/a", "/api/b", "/api/c"]})

    def test_paths_are_deduped_and_sorted(self):
        m = {"description_slice": "GET /api/b, POST /api/a, GET /api/b again"}
        self.assertEqual(_scope(m, is_final=False, enabled=True),
                         {"endpoint_paths": ["/api/a", "/api/b"]})


class AnEmptyScopeFallsBackToTheFullApp(unittest.TestCase):
    """"Empty parsed scope also falls back to full-app (never gates on an empty set)."""

    def test_a_slice_naming_no_endpoint(self):
        self.assertIsNone(_scope({"description_slice": "polish the landing page"},
                                 is_final=False, enabled=True))

    def test_a_missing_or_empty_milestone(self):
        for m in (None, {}, {"description_slice": ""}, {"description_slice": None}):
            self.assertIsNone(_scope(m, is_final=False, enabled=True), m)

    def test_a_non_dict_milestone_does_not_raise(self):
        self.assertIsNone(_scope("M1", is_final=False, enabled=True))


if __name__ == "__main__":
    unittest.main()
