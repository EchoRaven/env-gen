"""#362: a selector miss should answer the question, not just report failure.

`browser_fill` returns a bare `Fill failed: Page.fill: Timeout 5000ms exceeded`
and `browser_click` a bare `Click failed after 3 attempts`. The model has no way
to learn what IS on the page, so it guesses the next selector -- 52 identical
`browser_fill` failures on `input[name='username']` in r91's verifier alone,
plus 17 `browser_click`. Each costs a 5s timeout AND a full-context round.
Verbatim between attempts: "Let me try the fallback's typical selectors --
input#username, input#password, or by placeholder."

The page already knows the answer. Attaching the actual candidate elements to
the failure turns N blind retries into one informative failure.

Why this rather than a repeated-failure circuit breaker: I measured that first.
Keying on the FULL call (tool + exact args + error), only 22 triples repeat >=3
times across r91/r92/r93, and the single largest is

    12x  Backend  test_api GET http://localhost:8082/health -> Connection refused

which is a legitimate wait-for-boot poll. A generic breaker would have broken
that, and two of the other top offenders (deliver_project x35,
kickoff_declare_predicate x29) are already fixed by #361 and #335. Enriching the
error is the safe half of that idea.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _El:
    def __init__(self, attrs, tag="input"):
        self._a = attrs
        self._tag = tag

    async def get_attribute(self, name):
        return self._a.get(name)

    async def evaluate(self, _js):
        return self._tag


class _Page:
    def __init__(self, els=None, raises=False):
        self._els = els or []
        self._raises = raises

    async def query_selector_all(self, _sel):
        if self._raises:
            raise RuntimeError("page gone")
        return self._els


def _describe(page):
    from tools.browser.interaction import describe_interactive_candidates
    return asyncio.run(describe_interactive_candidates(page))


class TheCandidatesAreReported(unittest.TestCase):

    def test_name_and_id_are_surfaced(self):
        page = _Page([_El({"name": "email", "id": "login-email"}),
                      _El({"name": "password"})])
        out = _describe(page)
        self.assertIn("email", out)
        self.assertIn("login-email", out)
        self.assertIn("password", out)

    def test_placeholder_and_type_are_surfaced(self):
        page = _Page([_El({"placeholder": "Email or username", "type": "email"})])
        out = _describe(page)
        self.assertIn("Email or username", out)

    def test_an_element_with_no_useful_attributes_is_skipped(self):
        page = _Page([_El({}), _El({"name": "real"})])
        out = _describe(page)
        self.assertIn("real", out)

    def test_empty_page_returns_the_688_sentinel(self):
        """#688 split the two cases this used to conflate.

        `""` means "could not look" (the probe itself failed — see the
        ItNeverRaises cases below, which still return it). A page that the probe
        DID read and that offers nothing is a different fact the caller has to
        render differently, so it gets the `\x00empty-page` sentinel."""
        from tools.browser.interaction import _EMPTY_PAGE_688 as _S
        self.assertEqual(_describe(_Page([])), _S)


class ItNeverRaises(unittest.TestCase):
    """This runs on an ALREADY failing path -- it must not mask the real error."""

    def test_a_broken_page_returns_empty(self):
        self.assertEqual(_describe(_Page(raises=True)), "")

    def test_none_page_returns_empty(self):
        self.assertEqual(_describe(None), "")


class TheFailurePathsUseIt(unittest.TestCase):

    def _src(self):
        from tools.browser import interaction
        return Path(interaction.__file__).read_text()

    def test_fill_failure_attaches_candidates(self):
        src = self._src()
        idx = src.index("Fill failed:")
        self.assertIn("describe_interactive_candidates",
                      src[max(0, idx - 600):idx + 200])

    def test_click_failure_attaches_candidates(self):
        src = self._src()
        idx = src.index("Click failed after")
        self.assertIn("describe_interactive_candidates",
                      src[max(0, idx - 600):idx + 400])


if __name__ == "__main__":
    unittest.main()
