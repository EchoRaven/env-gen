r"""#1203fs: the framework registered an auth page with no APIs, then projected one that calls two.

`derive_frontend_pages_from_endpoints` (twice) and `_ensure_framework_auth_pages` register
`login_page` / `signup_page` with NO `apis_used`. The framework then projects
`_AUTH_PAGE_TEMPLATE` into those files, and that template calls the auth API -- verified by
calling the gate's own detector on the projected source, which returns True. The registry is
what `deliverability` reads, so the gate declines delivery on a contradiction the framework
created between its own registration and its own file:

    "N registered ui_page(s) declare `apis_used: []` while their own source calls an API:
     login_page (LoginPage.jsx); signup_page (SignupPage.jsx). Everything downstream then
     reasons from a registry that contradicts the code — #151 skips the page for having no
     `apis`, the consumer-wiring audit has nothing ..."

Measured from the gate's own prose, counting only records whose instance list is EXACTLY the two
framework-injected ids: 79 blocker records across 8 runs -- r137 42, r144 7, r152 6, r154 6,
r156 6, r147 5, r155 4, r134 3. Every one transient (the lane eventually enriches the
registration and it clears) and terminal in none, which is why the fix removes the contradiction
at its source instead of filing a P0 or adding an exemption: the framework declares what the
framework will emit, and the gate then has nothing to fire on.

Two things this must not do, both asserted below:
  * OVERSTATE. Declaring a path the projected file does not call would create the mirror defect
    in a check that already exists for it.
  * change the projection. `_project_page_component` picks the auth template from
    `_is_auth_page`, never from `apis_used`, so the emitted source must stay byte-identical.

And the paths are read OFF `_AUTH_PAGE_TEMPLATE` rather than spelled in three producers, so a
template change carries the declaration with it -- the drift is the defect.

LOCAL-ONLY (agent/tests/ gitignored).
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

from multi_agent.runtime import frontend_scaffold as FS  # noqa: E402
from multi_agent.runtime.deliverability import (  # noqa: E402
    _api_client_calls_1202vk as calls_an_api)
from multi_agent.runtime.kickoff.run_kickoff import (  # noqa: E402
    derive_frontend_pages_from_endpoints, _fw_auth_apis_1203fs)

AUTH_IDS = ("login_page", "signup_page")


class TheDeclarationComesOffTheTemplate(unittest.TestCase):
    def test_it_names_what_the_template_calls(self):
        self.assertEqual(FS.framework_auth_apis_used_1203fs(),
                         ["POST /auth/login", "POST /auth/register"])

    def test_an_ambiguous_template_declares_nothing_rather_than_guessing(self):
        """Two methods in the template means this function cannot say which endpoint takes
        which, and a wrong pair would be an OVERSTATED declaration -- the mirror defect. []
        restores today's behaviour (no `apis_used`), which is the honest answer."""
        real = FS._AUTH_PAGE_TEMPLATE
        try:
            FS._AUTH_PAGE_TEMPLATE = real + "\n  method: 'PATCH',\n"
            self.assertEqual(FS.framework_auth_apis_used_1203fs(), [])
            FS._AUTH_PAGE_TEMPLATE = "const x = 1;"      # no /auth path at all
            self.assertEqual(FS.framework_auth_apis_used_1203fs(), [])
        finally:
            FS._AUTH_PAGE_TEMPLATE = real

    def test_the_kickoff_side_reads_the_same_function(self):
        self.assertEqual(_fw_auth_apis_1203fs(), FS.framework_auth_apis_used_1203fs())


class EveryProducerDeclaresIt(unittest.TestCase):
    """Three producers, and the two in run_kickoff have byte-identical dict literals -- fixing
    one and leaving the other is the shape #1202lh paid for."""

    def test_the_kickoff_derivation(self):
        pages = {p["id"]: p for p in derive_frontend_pages_from_endpoints([])
                 if p.get("id") in AUTH_IDS}
        self.assertEqual(set(pages), set(AUTH_IDS), pages)
        for pid in AUTH_IDS:
            self.assertTrue(pages[pid].get("apis_used"), pid)

    def test_the_projection_side_injection(self):
        out = FS._ensure_framework_auth_pages(
            [{"name": "feed", "route": "/", "component": "ForYouFeedPage"}])
        auth = [p for p in out if p.get("id") in AUTH_IDS]
        self.assertEqual(len(auth), 2, auth)
        for p in auth:
            self.assertTrue(p.get("apis_used"), p)

    def test_both_run_kickoff_literals_were_edited(self):
        """The two producers are textually identical, so a `replace(..., 1)` would have left
        one behind and this assertion is what notices."""
        src = (LLM_DIR / "multi_agent" / "runtime" / "kickoff" / "run_kickoff.py").read_text(
            encoding="utf-8")
        self.assertEqual(src.count('"id": "login_page", "route": "/login"'), 2)
        self.assertEqual(src.count("_fwauth1203fs = _fw_auth_apis_1203fs()"), 2)


class TheGatesConditionCanNoLongerHold(unittest.TestCase):
    """The decisive join: the gate fires on (`apis_used == []`) AND (source calls an API). The
    second half is true by construction of the template -- so the first must be false."""

    def _projected(self, comp, pid, route):
        return FS._project_page_component(comp, {"route": route, "id": pid})

    def test_the_projected_source_really_calls_an_api(self):
        for comp, pid, route in (("LoginPage", "login_page", "/login"),
                                 ("SignupPage", "signup_page", "/signup")):
            self.assertTrue(calls_an_api(self._projected(comp, pid, route)),
                            "%s no longer trips the detector — re-measure before trusting "
                            "this patch" % comp)

    def test_and_the_registration_is_no_longer_empty(self):
        pages = {p["id"]: p for p in derive_frontend_pages_from_endpoints([])
                 if p.get("id") in AUTH_IDS}
        for pid in AUTH_IDS:
            self.assertNotEqual(pages[pid].get("apis_used") or [], [], pid)

    def test_nothing_is_overstated(self):
        """Every declared path must appear in the file the projector writes, or this patch has
        created the mirror defect (a page declaring an API it never calls)."""
        for comp, pid, route in (("LoginPage", "login_page", "/login"),
                                 ("SignupPage", "signup_page", "/signup")):
            src = self._projected(comp, pid, route)
            for entry in FS.framework_auth_apis_used_1203fs():
                path = entry.split()[-1]
                self.assertIn(path, src, "%s declares %s and does not call it" % (comp, path))

    def test_the_projection_is_byte_identical(self):
        """`_is_auth_page` picks the template, not `apis_used` -- so adding the declaration must
        not change one byte of what ships."""
        for comp, pid, route in (("LoginPage", "login_page", "/login"),
                                 ("SignupPage", "signup_page", "/signup")):
            bare = FS._project_page_component(comp, {"route": route, "id": pid})
            declared = FS._project_page_component(
                comp, {"route": route, "id": pid,
                       "apis_used": FS.framework_auth_apis_used_1203fs()})
            self.assertEqual(bare, declared, comp)


if __name__ == "__main__":
    unittest.main()
