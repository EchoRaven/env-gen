r"""#1202bb: don't discard a kickoff section over a key name the framework has resolved.

hub_tools' own comment measured it: **145 of the ~171 rejections in the r1-r175 corpus
are `['api_endpoints']`**. #1037 improved the message so it names the substitution —

    decision for section 'backend' carried only NON-CONTRACT keys ['api_endpoints']
    — You used a near-miss key name: `api_endpoints` -> `endpoints`.

— and then still threw the section away. netflix-r31 shows what that costs: the backend
lane's response was rejected four times inside one second, the correct spelling in hand
every time, and its section was replaced by a deterministic derive.

The rename is only safe where it cannot be wrong, and `deprecated_endpoints` matching the
same suffix rule is why: these tests pin the ambiguous and partial cases as still rejected.
"""
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.kickoff.section_substance import (  # noqa: E402
    near_miss_contract_keys_1037)


def _accepts(content, section="backend"):
    """Replicate the guard's decision on a candidate rename. Mirrors hub_tools."""
    from multi_agent.runtime.kickoff.section_substance import non_contract_keys
    wrong = non_contract_keys(content, section)
    if not wrong:
        return True, content
    near = near_miss_contract_keys_1037(wrong, section)
    tgts = list(near.values())
    if (isinstance(content, dict) and near and len(near) == len(wrong)
            and len(set(tgts)) == len(tgts)
            and not any(t in content for t in tgts)):
        out = dict(content)
        for k, t in near.items():
            out[t] = out.pop(k)
        return True, out
    return False, content


class NearMissAcceptanceTests(unittest.TestCase):
    def test_the_corpus_case_is_accepted_and_renamed(self):
        ok, out = _accepts({"api_endpoints": [{"path": "/api/titles"}]})
        self.assertTrue(ok, "the 85% case is still discarded")
        self.assertIn("endpoints", out)
        self.assertNotIn("api_endpoints", out)

    def test_the_mapping_is_what_the_framework_already_states(self):
        """The rename must be the framework's own published substitution, not a guess."""
        self.assertEqual(
            near_miss_contract_keys_1037(["api_endpoints"], "backend").get("api_endpoints"),
            "endpoints")

    def test_a_section_that_already_has_the_real_key_is_untouched(self):
        """Measured, not assumed: with `endpoints` present there is nothing to reject —
        non_contract_keys returns [] — so no rename happens and the content is unchanged.
        The guard's occupied-target check is belt-and-braces behind that."""
        content = {"api_endpoints": [1], "endpoints": [2]}
        ok, out = _accepts(dict(content))
        self.assertTrue(ok)
        self.assertEqual(out, content, "a section carrying a valid key was rewritten")

    def test_two_near_misses_onto_one_key_are_refused(self):
        """Ambiguous: one of them would silently win."""
        ok, _ = _accepts({"api_endpoints": [1], "deprecated_endpoints": [2]})
        self.assertFalse(ok)

    def test_a_key_with_no_near_miss_is_still_refused(self):
        ok, _ = _accepts({"auth_model": "jwt"})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
