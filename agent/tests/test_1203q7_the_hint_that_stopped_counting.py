"""#1203q7: the #1135 hint argues from a COUNT and stops counting at three.

`_chain_broken_detail_798` tells the verifier which PASSING chains already exercise the
endpoint its broken step failed on -- "the endpoint works, so compare THEIR step inputs
against yours". The persuasive force of that sentence is the number: #1135's own docstring
argues the case as "`titles_page` broke on `POST /api/titles/1/rating` with THREE passing
chains over it". The code then rendered `", ".join(sorted(_sib)[:3])`, so a reader could
never see a number larger than three.

MEASURED over the corpus (104 run trees, the production `_passing_endpoint_index_1135` /
`_canon_endpoint_1135` / `_step_is_actionable_1202gx` driving the real records): 775
actionable broken steps, 284 of them carry at least one passing sibling, and **137 of those
284 (48.2%) sit above the cap** -- across 16 runs, 36 distinct endpoints and 4 products.
100 of the 137 are NOT on an `/auth/` endpoint (`GET /api/feed` 12, `GET /api/me` 11,
`GET /api/transit-stops/{}` 10, and `POST /api/titles/{}/rating` -- #1135's own motivating
endpoint -- 3). The worst reads "three chains pass" where **48** do:

    googlemaps-r16  POST /auth/register   48 passing siblings, 3 named
    tiktok-web-r90  POST /auth/register   25 passing siblings, 3 named

Worse on googlemaps (48) than on tiktok (25): the same "cap sized to tiktok's scale" shape
as #1203q3/q5/q6.

#811 declares its cut TWENTY LINES BELOW this one, in the same function, citing #680 ("no
silent caps") -- and `join_capped` is already imported at module scope and used at ten call
sites in this file. The precedent was half-copied, the #1139/#1148 shape.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import remediation_dispatcher as rd  # noqa: E402


def _step(method, path, ok, **kw):
    d = {"method": method, "path": path, "ok": ok}
    d.update(kw)
    return d


def _orch(chains):
    class _RH:
        def get_verification_chains(self):
            return chains
    class _Hubs:
        registryhub = _RH()
    class _Orch:
        hubs = _Hubs()
    return _Orch()


def _register_chains(n_passing):
    """One failing step on POST /auth/register, with `n_passing` passing siblings on it.

    Shaped after googlemaps-r16, where 48 chains pass the endpoint one chain broke on.
    """
    chains = {
        "_meta": {"version": 1},
        "broken_one": {"status": "failing", "last_result": {"steps": [
            _step("POST", "/auth/register", False, status=409, action="register viewer",
                  note='{"detail":"email already registered"}')]}},
    }
    for i in range(n_passing):
        chains["flow_%02d" % i] = {"status": "passing", "last_result": {"steps": [
            _step("POST", "/auth/register", True, status=201)]}}
    return chains


def _hint(chains, prefix="broken_one"):
    hits = [l for l in rd._chain_broken_detail_798(_orch(chains)) if l.startswith(prefix)]
    assert hits, "the builder emitted no line for %s" % prefix
    return hits[0]


class TheReaderCanRecoverTheCount(unittest.TestCase):
    """The number is the evidence, so the number has to survive the cap."""

    def test_a_cut_sibling_list_says_how_many_more_passed(self):
        line = _hint(_register_chains(48))
        self.assertIn("#1135", line)
        self.assertIn("more not shown", line)

    def test_shown_plus_declared_equals_the_chains_that_really_pass(self):
        """Not a hardcoded remainder: shown + declared must equal the real sibling count."""
        for n_passing in (4, 7, 25, 48):
            with self.subTest(n_passing=n_passing):
                line = _hint(_register_chains(n_passing))
                named = set(re.findall(r"flow_\d\d", line.split("ALREADY PASS")[0]))
                m = re.search(r"\+(\d+) more not shown", line)
                self.assertIsNotNone(m, line)
                self.assertEqual(len(named) + int(m.group(1)), n_passing,
                                 "a reader cannot recover %d from %r" % (n_passing, line))

    def test_the_names_it_does_show_are_real_siblings(self):
        chains = _register_chains(48)
        line = _hint(chains)
        for name in re.findall(r"flow_\d\d", line.split("ALREADY PASS")[0]):
            self.assertEqual(chains[name]["status"], "passing")
        self.assertNotIn("broken_one,", line.split("ALREADY PASS")[0])


class ItDeclaresNothingWhenNothingIsCut(unittest.TestCase):
    """#647: no wider than the evidence. #1135's own motivating case has exactly three."""

    def test_the_netflix_r2_case_of_three_reads_exactly_as_before(self):
        chains = _register_chains(3)
        line = _hint(chains)
        self.assertIn("flow_00, flow_01, flow_02 ALREADY PASS", line)
        self.assertNotIn("more not shown", line)

    def test_one_sibling_is_not_decorated(self):
        line = _hint(_register_chains(1))
        self.assertIn("flow_00 ALREADY PASS", line)
        self.assertNotIn("more not shown", line)

    def test_no_sibling_still_means_no_hint_at_all(self):
        line = _hint(_register_chains(0))
        self.assertNotIn("#1135", line)


class TheRestOfTheLineIsUntouched(unittest.TestCase):
    """#798 / #1202wx payload must still ride along with the hint."""

    def test_the_apps_own_words_and_the_status_survive(self):
        line = _hint(_register_chains(48))
        self.assertIn("POST /auth/register", line)
        self.assertIn("returned 409", line)
        self.assertIn("email already registered", line)
        self.assertIn("compare THEIR step inputs", line)


class OneOwnerForTheCut(unittest.TestCase):
    """#1032: the declaration belongs to `join_capped`, not to a second spelling."""

    def test_the_hint_is_built_with_the_shared_helper(self):
        """STRUCTURAL, not textual.

        The first version of this test read the function's source text and asserted
        `'", ".join(sorted(_sib)' not in it -- and the #1203q7 comment I had just written
        QUOTED the old expression, so the assertion failed on my own prose. Same shape as
        #1203ph. A check that scans source must read the tree, not the characters.
        """
        import ast
        src = Path(rd.__file__).read_text(encoding="utf-8")
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "_chain_broken_detail_798")
        mods = [n for n in ast.walk(fn)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_sib_txt" for t in n.targets)
                and isinstance(n.value, ast.BinOp) and isinstance(n.value.op, ast.Mod)]
        self.assertEqual(len(mods), 1, "expected exactly one `_sib_txt = ... % (...)`")
        args = mods[0].value.right
        self.assertIsInstance(args, ast.Tuple)
        first = args.elts[0]
        self.assertIsInstance(first, ast.Call,
                              "the sibling names must be rendered by a call, not a bare join")
        self.assertEqual(getattr(first.func, "id", None), "join_capped",
                         "the cut belongs to join_capped (#1032: one owner for the rule)")
        self.assertNotIsInstance(
            first.args[0], ast.Subscript,
            "slicing before the helper sees the list hides the remainder (#1203pl)")


if __name__ == "__main__":
    unittest.main()
