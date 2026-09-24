"""#348: parallel_execute injected "" for an OPTIONAL field, guaranteeing rejection.

The tool documents agent_type as optional -- parallel.py:25 verbatim:

    "agent_type: Optional runtime worker label; if omitted, the runtime must
     infer a valid profile from the definition"

and ALL THREE of its worked examples omit it (0 occurrences of "agent_type" in
the example block). The child-task validator agrees: a non-required field that
is missing or None short-circuits to OK (contracts.py: `if key not in payload
or payload.get(key) is None: ... return None`).

But the builder injected an EMPTY STRING:

    parallel.py:236   "agent_type": agent_def.get("agent_type", "")

which sails past the None check and lands on `non_empty and not value.strip()`
-> "contract error at 'agent_definition.agent_type': must be non-empty".

So following the tool's own documentation was a guaranteed failure. Live:
10 such contract errors across the corpus, and in the tiktok runs every child
of the affected calls was rejected (SeedDataTeam, GitOpsTeam,
FrontendPageRescue, SeedAuthor -- "0/N succeeded").

The fix is one token: absent stays absent, so the runtime can infer as
documented.
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


class TheBuilderNoLongerInjectsAnEmptyString(unittest.TestCase):

    def _src(self):
        from tools.team_tools_parts import parallel
        return Path(parallel.__file__).read_text()

    def test_no_empty_string_default_for_agent_type(self):
        self.assertNotIn('"agent_type": agent_def.get("agent_type", "")', self._src())

    def test_absent_agent_type_stays_absent_or_none(self):
        src = self._src()
        self.assertIn('agent_def.get("agent_type") or None', src)

    def test_the_documented_contract_is_unchanged(self):
        """The docs promised optional; the code now matches the docs."""
        src = self._src()
        self.assertIn("if omitted, the runtime must infer", src)


class TheValidatorAcceptsWhatTheDocsPromise(unittest.TestCase):
    """Pins the asymmetry that caused this: missing/None is fine, "" is not."""

    def _check(self, payload):
        """Drive the REAL validator method on the mixin that owns it."""
        import inspect

        from multi_agent.team_runtime.parallel_runtime import contracts
        cls = next(o for _n, o in inspect.getmembers(contracts, inspect.isclass)
                   if hasattr(o, "_validate_string_field"))
        return cls._validate_string_field(
            payload, "agent_type", required=False, non_empty=True,
            prefix="agent_definition")

    def test_missing_is_accepted(self):
        self.assertIsNone(self._check({}))

    def test_none_is_accepted(self):
        self.assertIsNone(self._check({"agent_type": None}))

    def test_empty_string_is_rejected(self):
        self.assertIsNotNone(self._check({"agent_type": ""}))

    def test_a_real_label_is_accepted(self):
        self.assertIsNone(self._check({"agent_type": "backend"}))


class TheWorkedExamplesWouldNowPass(unittest.TestCase):

    def test_examples_still_omit_agent_type(self):
        """If an example ever starts passing it explicitly, this guard should be
        revisited rather than silently drifting."""
        from tools.team_tools_parts import parallel
        src = Path(parallel.__file__).read_text()
        example_block = src[src.index("parallel_execute("):src.index("parallel_execute(") + 2200]
        self.assertNotIn('"agent_type"', example_block)


if __name__ == "__main__":
    unittest.main()
