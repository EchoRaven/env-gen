"""#1202cm — score the presentation, not the content.

The reference is a screenshot of the real product: real titles, real cover art, real
avatars. The implementation is seeded with its own. Those can never be the same images, so
asking for them is asking for something unreachable — the honest target is the same DESIGN
applied to whatever content is there.

Measured over 2888 recorded deviations: only one says outright that the imagery differs, so
the judge was already largely doing this. But 63 name a specific title ("implementation
lacks the large 'ALL AMERICAN' title artwork"), and that wording sends the fixing lane after
the words rather than after the treatment.

The line this must NOT cross is the other 55, which complain that a tile is a placeholder or
the page is a blank loading state. Those are presentation failures and must keep costing
marks. LOCAL-ONLY (agent/tests/ gitignored).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.visual_fidelity import design_premises_text  # noqa: E402

_RAW = (LLM / "multi_agent" / "runtime" / "visual_fidelity.py").read_text(encoding="utf-8")

# These prompts are built from adjacent string literals, so a sentence in the rendered text
# is split across `" ... "\n    " ... "` in the source. Assertions must match the SENTENCE,
# not the source layout — join the seams first.
VF = re.sub(r'"\s*\n\s*"', "", _RAW)


def test_the_judge_is_told_content_is_not_the_criterion():
    assert "CONTENT IS NOT THE CRITERION; ITS PRESENTATION IS" in VF


def test_the_judge_is_still_told_to_penalise_an_empty_state():
    """THE guard. 'Different content' must not become a licence to show none — 55 of the
    corpus deviations are placeholder/blank/loading complaints and they are correct."""
    i = VF.index("CONTENT IS NOT THE CRITERION")
    stanza = VF[i:VF.index("Assess each dimension", i)]
    assert "NOT licence for an empty state" in stanza
    for word in ("placeholder", "blank", "loading"):
        assert word in stanza, word


def test_the_judge_is_told_how_to_word_a_deviation():
    """The 63 title-naming deviations are the actual damage: they send the lane after the
    words instead of the treatment."""
    i = VF.index("CONTENT IS NOT THE CRITERION")
    stanza = VF[i:VF.index("Assess each dimension", i)]
    assert "never 'missing ALL AMERICAN'" in stanza


def test_the_overall_anchor_is_design_not_product_identity():
    """It used to read 'a user would take the implementation for the reference PRODUCT',
    which is an identity test — and identity is decided by content, the one thing that
    legitimately differs."""
    assert "for the reference product" not in VF, "the identity anchor is still there"
    assert "a designer would say the same design was applied here" in VF


def test_the_lane_is_given_the_same_rule_as_the_judge():
    """This block exists so the lane designs against the criteria it will be scored on. A
    rule reaching only one of the two puts them back out of step — the shape of most of what
    this session fixed."""
    t = design_premises_text()
    assert "Content is not the criterion" in t
    assert "placeholder tile" in t and "IS a deviation" in t


def test_the_lane_is_told_not_to_hard_code_the_reference_text():
    """The failure mode the wording change is meant to prevent on the OTHER side: a lane
    that reads 'missing ALL AMERICAN' and renders that string."""
    assert "Do not hard-code the reference's title text" in design_premises_text()


def test_the_dimension_rubrics_are_still_carried():
    """The rule is appended to the premises, not a replacement for them."""
    t = design_premises_text()
    for title in ("Component completeness", "Color", "Style character"):
        assert title in t, title
