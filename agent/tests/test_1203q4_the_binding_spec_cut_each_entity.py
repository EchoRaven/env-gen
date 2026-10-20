r"""#1203q4: the binding spec showed ten fields of an entity and did not say there were more.

`reference_materials.spec_summary_for_requirements` builds the block headed "REFERENCE SPEC
(compiled from the user's reference materials -- binding)", and its docstring says it exists
so "the lanes design against the compiled spec from the first turn" -- precisely so they need
not go and read design/reference_spec.json. Then each entity's fields were sliced at 10 with
nothing saying so, which makes a partial data model look like the whole one.

MEASURED over the 102 reference_spec.json docs (1119 entities): 99 of them (97%) carry at
least one entity past 10 fields, and 316 fields in total are never shown to a lane. As with
#1203q3 the damage is worst away from tiktok -- googlemaps `places` has 22 fields (12 hidden),
`place` 18, `route_legs` 16, while tiktok's fattest is `videos` at 13.

★ FOUND BY FOLLOWING #1203q3's OWN DOCSTRING, which says it "mirrors
reference_materials.spec_summary_for_requirements" -- the #1139/#1148 instrument: when a rule
is applied at one site, look at the sibling the comment points to.

★ THE FOUR CHARACTER CAPS IN THAT FUNCTION ARE DELIBERATELY UNTOUCHED. Measured across the
same 102 docs, not one is ever reached (screens 1500, endpoints 2000, entities 2000,
mcp_tools 800 -- zero exceedances). A cap that never bites needs no declaration, and moving a
prompt bound is a live-run decision (#1202w6). Guarding that restraint is a test below.
"""
import sys
import unittest
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[1]
for _p in (str(_AGENT), str(_AGENT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime.reference_materials import (  # noqa: E402
    spec_summary_for_requirements as SUMMARY,
)


def _spec(n_fields, name="thing", extra=None):
    s = {"entities": [{"name": name, "fields": ["f%d" % i for i in range(n_fields)]}]}
    if extra:
        s.update(extra)
    return s


def _entities_line(spec):
    for line in SUMMARY(spec).split("\n"):
        if line.startswith("Entities:"):
            return line
    return ""


class TheCutIsDeclared(unittest.TestCase):

    def test_googlemaps_places_shape_says_how_many_it_hid(self):
        """★ THE TICKET at the worst real figure: 22 fields, 10 shown."""
        line = _entities_line(_spec(22))
        self.assertIn("+12 more", line, line)

    def test_the_count_is_the_REMAINDER_not_the_total(self):
        """Declaring the total (22) or the shown count (10) would both be wrong; the reader
        needs to know what is ABSENT -- #1203pl's and #1203pa's defect."""
        line = _entities_line(_spec(13))
        self.assertIn("+3 more", line)
        self.assertNotIn("+13 more", line)
        self.assertNotIn("+10 more", line)

    def test_exactly_ten_claims_no_cut(self):
        """#983: a clause that fires while naming nothing."""
        line = _entities_line(_spec(10))
        self.assertNotIn("more", line)

    def test_a_short_entity_claims_no_cut(self):
        self.assertNotIn("more", _entities_line(_spec(3)))

    def test_the_first_ten_are_still_shown(self):
        line = _entities_line(_spec(22))
        for i in range(10):
            self.assertIn("f%d" % i, line)
        self.assertNotIn("f10,", line)

    def test_each_entity_declares_its_own_cut(self):
        spec = {"entities": [
            {"name": "a", "fields": ["x%d" % i for i in range(12)]},
            {"name": "b", "fields": ["y%d" % i for i in range(4)]},
            {"name": "c", "fields": ["z%d" % i for i in range(15)]},
        ]}
        line = _entities_line(spec)
        self.assertIn("+2 more", line)
        self.assertIn("+5 more", line)
        self.assertEqual(line.count("more"), 2, line)


class TheUnbittenCapsAreLeftAlone(unittest.TestCase):
    """#647: measured across the same 102 docs, none of the four character caps is ever
    reached, so none of them is declared. Pinning that keeps a later reader from 'fixing'
    a cap that does not bite -- and from quietly moving a prompt bound (#1202w6)."""

    def test_the_character_caps_are_still_present_and_unchanged(self):
        import inspect
        src = inspect.getsource(SUMMARY)
        for lim in ("[:1500]", "[:2000]", "[:800]"):
            self.assertIn(lim, src, "a character bound on the binding block moved")

    def test_a_long_entity_list_is_still_bounded(self):
        spec = {"entities": [{"name": "e%03d" % i, "fields": ["a", "b"]}
                             for i in range(400)]}
        line = _entities_line(spec)
        self.assertLessEqual(len(line.split(": ", 1)[1]), 2000, len(line))


class ItStillBehaves(unittest.TestCase):

    def test_no_entities_means_no_line(self):
        self.assertEqual(_entities_line({"screens": [{"name": "s"}]}), "")

    def test_an_entity_with_no_fields_does_not_raise(self):
        line = _entities_line({"entities": [{"name": "bare"}]})
        self.assertIn("bare[]", line)

    def test_a_junk_entity_is_skipped(self):
        line = _entities_line({"entities": ["nonsense", {"name": "ok", "fields": ["a"]}]})
        self.assertIn("ok[a]", line)


if __name__ == "__main__":
    unittest.main()
