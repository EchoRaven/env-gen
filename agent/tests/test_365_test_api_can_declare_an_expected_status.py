"""#365: test_api cannot say what it expects, so a correct probe reads as a failure.

`test_api(method, url, body, headers)` has no way to declare an expected
status, and any non-2xx is returned as a FAILED tool call. But the gates
demand negative tests: `auth_enforced_401` requires a business endpoint to
refuse an unauthenticated request, and `business_chain_isolation`'s remediation
text says "a SECOND user (or an unauthenticated request) ... MUST be refused
(expect 401/403)".

So the framework tells the agent to prove an endpoint 401s, and then records
the proof as a tool failure. Measured across r91/r92/r93: 282 of 508 test_api
calls (56%) are reported failures, 154 of them 401s.

This is the same shape as #363 -- the framework not letting an agent express a
negative expectation -- and the fix is the same: let the call declare it, and
treat a matching status as SUCCESS.

Deliberately NOT done here: auto-attaching a framework-minted token. I measured
that first. Of the 154 401s, 65 ALREADY passed an Authorization header and were
refused anyway (a token problem, not a missing-token problem, and one that
needs a live run to diagnose), and the tool's own DESCRIPTION already documents
the login-then-header flow. Auto-auth would fix neither of those and would make
the unauthenticated probe the gates require impossible to write.
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


def _matches(status, expect):
    from tools.runtime_tools import status_meets_expectation
    return status_meets_expectation(status, expect)


class AnExpectedStatusIsSatisfied(unittest.TestCase):

    def test_a_single_int(self):
        self.assertTrue(_matches(401, 401))

    def test_a_list(self):
        self.assertTrue(_matches(403, [401, 403]))

    def test_a_string_is_accepted(self):
        """LLM-authored args arrive stringified (see #335)."""
        self.assertTrue(_matches(404, "404"))

    def test_a_list_of_strings(self):
        self.assertTrue(_matches(401, ["401", "403"]))


class AMismatchIsStillAFailure(unittest.TestCase):

    def test_wrong_status(self):
        self.assertFalse(_matches(200, 401))

    def test_not_in_the_list(self):
        self.assertFalse(_matches(500, [401, 403]))


class NoExpectationKeepsTodaysBehaviour(unittest.TestCase):
    """Every existing call must behave exactly as before."""

    def test_none_never_matches(self):
        self.assertFalse(_matches(200, None))
        self.assertFalse(_matches(401, None))

    def test_empty_list_never_matches(self):
        self.assertFalse(_matches(401, []))

    def test_garbage_expectation_never_matches(self):
        self.assertFalse(_matches(401, "not-a-status"))
        self.assertFalse(_matches(401, {"a": 1}))


class TheToolExposesIt(unittest.TestCase):

    def _src(self):
        from tools import runtime_tools
        return Path(runtime_tools.__file__).read_text()

    def test_expect_is_in_the_signature(self):
        src = self._src()
        i = src.index('NAME = "test_api"')
        self.assertIn("expect", src[i:i + 4000])

    def test_the_description_tells_the_agent_about_it(self):
        src = self._src()
        i = src.index('NAME = "test_api"')
        block = src[i:i + 1600]
        self.assertIn("expect", block)

    def test_the_documented_auth_flow_is_still_there(self):
        """It was already correct -- 65 of the 401s passed a header and were
        refused anyway, so the docs are not the defect."""
        src = self._src()
        i = src.index('NAME = "test_api"')
        self.assertIn("Authorization", src[i:i + 1600])


if __name__ == "__main__":
    unittest.main()
