r"""#1203fw: the framework served `register`; 69 lanes hand-rolled `signup`.

`FRAMEWORK_AUTH_SURFACE_PREFIXES_1202vl` names `/auth/` and `/api/auth/` as the framework's own
auth surface -- the business-auth middleware exempts them for that reason, and `is_business`
excludes them. The framework served exactly two spellings on it. Measured over the corpus, by
registered path and by hand-written handler in `custom_routes.py`:

    /auth/register      184 registered   10 hand-written
    /auth/login         184 registered   16 hand-written
    /auth/signup         35 registered   38 hand-written   <- served by nobody
    /api/auth/signup     29 registered   31 hand-written   <- served by nobody

So 69 lanes wrote their own registration handler -- password hashing, tenant resolution, token
minting -- for a surface the framework claims. Each hand-roll can reintroduce a bug this handler
has already fixed, and r163 filed exactly that: "POST /api/auth/signup ignores X-Tenant-Id and
creates user in default tenant" -- the very tenant resolution the login handler carries a
comment about.

One alias closes both rows. The skeleton mounts this router BARE and again with
`prefix="/api"`:

    app.include_router(_as_router)
    app.include_router(_as_router, prefix="/api")

so `/api/auth/signup` follows from `/auth/signup` for free. That mount is also why
`/api/auth/register` (6 registered) and `/api/auth/login` (13) were already served -- checking
it corrected my first premise, which was that the framework claimed `/api/auth/` and served
nothing there.

LOCAL-ONLY (agent/tests/ gitignored).
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.oauth_scaffold import render_oauth_module  # noqa: E402

SRC = render_oauth_module("oauth_routes.py")
SKELETON = (LLM_DIR / "multi_agent" / "runtime" / "backend_skeleton.py").read_text(
    encoding="utf-8")


def _routes_of(fn_name: str) -> set:
    """Every path decorating one handler in the rendered module."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == fn_name):
            continue
        out = set()
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and dec.args
                    and isinstance(dec.args[0], ast.Constant)):
                out.add(dec.args[0].value)
        return out
    raise AssertionError("%s is not in the rendered AS module" % fn_name)


class SignupIsServed(unittest.TestCase):
    def test_register_also_answers_signup(self):
        self.assertEqual(_routes_of("auth_register"),
                         {"/auth/register", "/auth/signup"})

    def test_it_is_the_same_handler_not_a_second_copy(self):
        """#906: one criterion, one function. A second signup implementation would drift from
        register on the next fix to either -- which is the whole defect being removed here."""
        self.assertEqual(SRC.count("async def auth_register"), 1)

    def test_both_keep_register_s_created_status(self):
        tree = ast.parse(SRC)
        for node in ast.walk(tree):
            if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "auth_register"):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                codes = [k.value.value for k in dec.keywords
                         if k.arg == "status_code" and isinstance(k.value, ast.Constant)]
                self.assertEqual(codes, [201], ast.unparse(dec))

    def test_login_is_untouched(self):
        """Additive: this patch adds a path to register and must not alter login's."""
        self.assertEqual(_routes_of("auth_login"), {"/auth/login"})

    def test_the_rendered_module_still_parses(self):
        ast.parse(SRC)


class ThePrefixMountGivesTheApiSpelling(unittest.TestCase):
    """The reason one alias covers two corpus rows, asserted rather than assumed -- the first
    version of this patch's premise was wrong about it."""

    def test_the_skeleton_mounts_the_as_router_twice(self):
        self.assertIn("app.include_router(_as_router)", SKELETON)
        self.assertRegex(SKELETON,
                         r"app\.include_router\(\s*_as_router,\s*prefix=[\"']/api[\"']")

    def test_so_every_served_auth_path_has_an_api_twin(self):
        """Not a code assertion about FastAPI -- a statement of what the two mounts mean, kept
        beside the mount check so the pair cannot drift apart silently."""
        served = {p for p in _routes_of("auth_register") | _routes_of("auth_login")}
        self.assertTrue(all(p.startswith("/auth/") for p in served), served)
        self.assertIn("/auth/signup", served)


class TheCorpusShapeIsWhatWasMeasured(unittest.TestCase):
    def test_the_measurement_is_recorded_beside_the_alias(self):
        """#647/#1202tr: a constant added without its measurement is an unchecked claim. The
        numbers that justify this alias live in the template, next to it."""
        # Anchor on the DECORATOR, not the first mention of the path -- the first mention is
        # inside the comment itself, so `find("/auth/signup")` stopped the window before the
        # numbers it was meant to contain. That was this test's first failure, not the patch's.
        i = SRC.index('@router.post("/auth/signup"')
        head = SRC[:i]
        for token in ("184 registered", "38 hand-written", "31 hand-written"):
            self.assertIn(token, head, token)

    def test_no_internal_ticket_reaches_the_shipped_app(self):
        """The provenance scrubber strips ticket numbers from what ships; this asserts the
        template's own comment is the only place they live -- `render_oauth_module` is verbatim,
        so the scrub happens later in `write_oauth_as`."""
        self.assertIn("#1203fw", SRC)          # present pre-scrub, by design
        from multi_agent.runtime.provenance_scrub import scrub_provenance_1202mi
        scrubbed = scrub_provenance_1202mi(SRC, "oauth_routes.py")
        self.assertNotIn("#1203fw", scrubbed)
        # and the route itself survives the scrub
        self.assertIn('"/auth/signup"', scrubbed)

    def test_no_bare_run_id_reaches_the_shipped_app(self):
        """The RULE, aimed at the form that actually leaks. Measured against the scrubber:

            "tiktok-r163"      -> "an earlier run"     (handled)
            "netflix-local-r44"-> "an earlier run"     (handled)
            "#1203fw"          -> ""                   (handled)
            "r163"             -> "r163"               LEAKS
            "r126"             -> "r126"               LEAKS

        So a QUALIFIED run name in a template comment is safe provenance and a BARE `rNNN` is a
        builder's run id rendered into the delivered app -- the class #1202te fixed for the
        generated JS. My first draft of this patch wrote a bare `r163`, which is what this test
        caught; and my first draft of the TEST then replaced two safe `tiktok-r126` mentions for
        no reason, which measuring the scrubber showed was an overreach, since reverted."""
        import re
        from multi_agent.runtime.provenance_scrub import scrub_provenance_1202mi
        scrubbed = scrub_provenance_1202mi(SRC, "oauth_routes.py")
        leaks = re.findall(r"(?<![\w-])r\d{2,4}\b", scrubbed)
        self.assertEqual(leaks, [], "bare run ids ship in the generated AS module: %s" % leaks)

    def test_the_qualified_form_is_what_the_scrubber_handles(self):
        """A positive control for the rule above: if the scrubber ever stops handling the
        qualified form, the template's own `tiktok-r126` notes start leaking and this says so."""
        from multi_agent.runtime.provenance_scrub import scrub_provenance_1202mi
        self.assertNotIn("tiktok-r", scrub_provenance_1202mi(SRC, "oauth_routes.py"))
        self.assertIn("tiktok-r126", SRC)      # present pre-scrub, as useful provenance


if __name__ == "__main__":
    unittest.main()
