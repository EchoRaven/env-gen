r"""#1203on: what "only routes projected with no actor" excludes, pinned.

`#1202kh` built the guard's public allow-list from the projector's own auth decision and said
so: "it holds only routes projected with no actor". A route the LANE implements in
`custom_routes.py` is not projected, so it never reaches that list even when the contract
declares `auth_required=false` — and the guard denies it with a 401 the lane cannot explain.

MEASURED across the 49 corpus runs that carry the mechanism: 351 contract-public `/api/`
endpoints, 295 listed, and — after applying the guard's OWN prefix exemptions (`/auth/`,
`/api/v1/`, `/oauth`, `/.well-known`, and the login|register|signup terminal segments under
`/api/auth/`) — **39 routes in 22 runs are declared public and denied anyway, 37 of them
implemented in the lane's custom_routes.py**. r133's backend wrote it four times: "tokenless
session 401 is caused by generated app/backend/main.py auth guard allow-list omitting GET
/api/auth/session despite RegistryHub auth_required=false".

★ DELIBERATELY NOT FIXED, and this file is the ratchet on that decision:
  * the modern era has nearly closed it — r185, r186, r188, r189, r190 and r191 deny ZERO,
    only r187 denies one, because the projector now builds most public business routes itself;
  * sourcing the list from `schema.auth_required` instead would open a HOLE rather than close
    a wall: a lane that declares `auth_required=false` by mistake would then be believed, and a
    wrongly-public /api/ route is worse than a wrongly-denied one. #1202w6 says a new wall gets
    a live run first; a new hole deserves more caution than that, not less.

So the numbers live at the code and here. If a modern run starts denying declared-public routes
again, `test_the_modern_era_is_still_clean` fails and the trade can be re-decided with numbers.
"""
import json
import re
import unittest
from pathlib import Path

ENTRY_SEGMENTS = ("login", "register", "signup")


def _guard_exempts(path):
    """The guard's own prefix rules, as the generated middleware applies them."""
    p = str(path or "").rstrip("/")
    if p.startswith(("/auth/", "/api/v1/", "/.well-known", "/oauth",
                     "/api/.well-known", "/api/oauth")):
        return True
    if p.startswith("/api/auth/") and p.rsplit("/", 1)[-1] in ENTRY_SEGMENTS:
        return True
    return False


def _denied_public_routes(run_dir):
    """(method, path, in_lane_file) for every contract-public /api/ route the guard denies.

    Returns None when the run predates `#1202kh` -- its main.py has no allow-list at all, so
    there is nothing to compare and counting it would inflate the number (my first pass did:
    it answered 542 because it folded 42 pre-mechanism runs in).
    """
    main = run_dir / "app" / "backend" / "main.py"
    eps_f = run_dir / "shared" / "hubs" / "registryhub_endpoints.json"
    if not main.is_file() or not eps_f.is_file():
        return None
    try:
        src = main.read_text(encoding="utf-8", errors="ignore")
        eps = json.load(open(eps_f, errors="ignore"))
    except Exception:
        return None
    if "_FW_PUBLIC_API_1202KH" not in src:
        return None
    custom = run_dir / "app" / "backend" / "custom_routes.py"
    lane_src = custom.read_text(encoding="utf-8", errors="ignore") if custom.is_file() else ""
    listed = set()
    for m in re.finditer(r"_FW_PUBLIC_API_1202KH\s*=\s*\[(.*?)\]", src, re.S):
        for mm in re.finditer(r"\(\s*['\"](\w+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", m.group(1)):
            listed.add((mm.group(1).upper(), mm.group(2).rstrip("/")))
    out = []
    for key, e in eps.items():
        if key == "_meta" or not isinstance(e, dict):
            continue
        schema = e.get("schema") or {}
        if not (isinstance(schema, dict) and schema.get("auth_required") is False):
            continue
        path = str(e.get("path") or "").rstrip("/")
        method = str(e.get("method") or "GET").upper()
        if not path.startswith("/api/") or _guard_exempts(path):
            continue
        if (method, path) in listed:
            continue
        out.append((method, path, path in lane_src))
    return out


class TheGuardsOwnExemptionsAreApplied(unittest.TestCase):
    """The count means nothing if the exemptions are not the guard's own."""

    def test_the_prefixes_the_guard_lets_through(self):
        for p in ("/auth/login", "/api/v1/tenants", "/oauth/token", "/.well-known/jwks.json",
                  "/api/oauth/token", "/api/.well-known/jwks.json"):
            with self.subTest(path=p):
                self.assertTrue(_guard_exempts(p))

    def test_the_entry_points_under_the_api_umbrella(self):
        for p in ("/api/auth/login", "/api/auth/register", "/api/auth/signup"):
            with self.subTest(path=p):
                self.assertTrue(_guard_exempts(p))

    def test_everything_else_under_api_auth_stays_guarded(self):
        """The guard's own comment: `/api/auth/me` and anything else stays guarded."""
        for p in ("/api/auth/me", "/api/auth/session", "/api/auth/logout"):
            with self.subTest(path=p):
                self.assertFalse(_guard_exempts(p))

    def test_a_business_route_is_not_exempt(self):
        for p in ("/api/videos/feed", "/api/comments", "/api/live"):
            with self.subTest(path=p):
                self.assertFalse(_guard_exempts(p))


class TheDecisionIsRecordedWhereItIsMade(unittest.TestCase):
    def test_the_comment_carries_the_measurement(self):
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import backend_scaffold as BS
        src = inspect.getsource(BS)
        self.assertIn("#1203on", src)
        for fragment in ("37 OF THE 39", "custom_routes.py", "WOULD OPEN A HOLE"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, src)

    def test_the_allow_list_is_still_sourced_from_the_projector(self):
        """The ratchet half: this ticket deliberately did NOT change where the list comes
        from, so a future patch that sources it from `auth_required` has to come past here."""
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import backend_scaffold as BS
        src = inspect.getsource(BS)
        i = src.index("_FW_PUBLIC_API_1202KH")
        window = src[max(0, i - 4000):i]
        self.assertIn("only routes projected with no actor", window)


class WhatTheCorpusSays(unittest.TestCase):
    _MODERN = ("tiktok-web-r185", "tiktok-web-r186", "tiktok-web-r188", "tiktok-web-r189",
               "tiktok-web-r190", "tiktok-web-r191")

    @classmethod
    def setUpClass(cls):
        cls.corpus = Path(__file__).resolve().parents[2] / "generated"
        if not cls.corpus.is_dir():
            raise unittest.SkipTest("no generated/ corpus on this machine")

    def test_the_measured_runs_still_show_it(self):
        """r133 is the run whose lane said it four times."""
        got = _denied_public_routes(self.corpus / "tiktok-web-r133")
        if got is None:
            self.skipTest("r133 is not on this disk")
        self.assertEqual(len(got), 3, got)
        self.assertIn(("GET", "/api/auth/session"), [(m, p) for m, p, _ in got])
        self.assertTrue(all(lane for _, _, lane in got),
                        "r133's denied routes are the lane's own, which is the point")

    def test_the_modern_era_is_still_clean(self):
        """★ The ratchet. If this fails, the projector stopped covering public business routes
        and the trade-off recorded at the code has to be re-decided -- with the new numbers.

        ★ IT MUST FAIL RATHER THAN SKIP WHEN IT LOOKS AT NOTHING. Mutation ON4 emptied the
        loop and this test SKIPPED -- and a skip passes the suite, so the ratchet would have
        been silently inert. The run set is asserted before the verdict."""
        present = [r for r in self._MODERN if (self.corpus / r).is_dir()]
        if not present:
            self.skipTest("no modern run on this disk")
        offenders = {}
        checked = []
        for run in present:
            got = _denied_public_routes(self.corpus / run)
            if got is None:
                continue
            checked.append(run)
            if got:
                offenders[run] = got
        self.assertEqual(sorted(checked), sorted(present),
                         "the scan returned None for %s, so it looked at fewer runs than are "
                         "on this disk" % sorted(set(present) - set(checked)))
        self.assertEqual(offenders, {},
                         "a modern run denies a contract-public route again: %s" % offenders)

    def test_the_gap_is_dominated_by_lane_written_routes(self):
        """37 of 39 -- the mechanism, as an EXACT corpus assertion.

        ★ A floor (`>= 0.9`) is not falsifiable by lowering it, which mutation ON5 showed. The
        recorded pair is asserted instead, so a change in either direction has to be read."""
        total = lane = runs = 0
        for d in sorted(self.corpus.glob("*/app/backend")):
            got = _denied_public_routes(d.parent.parent)
            if not got:
                continue
            runs += 1
            total += len(got)
            lane += sum(1 for _, _, in_lane in got if in_lane)
        if not total:
            self.skipTest("no denied public route on this disk")
        self.assertEqual((runs, total, lane), (22, 39, 37),
                         "measured (runs, denied, lane-written) = %s; the code's comment "
                         "records (22, 39, 37)" % ((runs, total, lane),))

    def test_a_run_without_the_mechanism_is_excluded(self):
        """★ Mutation ON1 folded pre-#1202kh runs back in -- which is how my first pass
        answered 542 instead of 39 -- and nothing noticed. r107's main.py has no allow-list at
        all, so there is nothing to compare and it must come back as None."""
        d = self.corpus / "tiktok-web-r107"
        if not (d / "app" / "backend" / "main.py").is_file():
            self.skipTest("r107 is not on this disk")
        self.assertNotIn("_FW_PUBLIC_API_1202KH",
                         (d / "app" / "backend" / "main.py").read_text(
                             encoding="utf-8", errors="ignore"))
        self.assertIsNone(_denied_public_routes(d),
                          "a run that predates the mechanism was counted")


if __name__ == "__main__":
    unittest.main()
