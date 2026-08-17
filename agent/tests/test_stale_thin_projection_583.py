r"""#583: #221 re-projects an existing page only when it does NOT already carry the projector
marker — "so the lane's IN-PLACE refinement of the floor SURVIVES". But a page emitted BEFORE
`decompose_reference` landed carries the marker too, and the guard then freezes it: the design
later gains every component region, the pass re-runs, sees the marker, and skips.

netflix r142 `title_detail` shipped **61 lines with no `<ul>`/`<li>`/`<h2>`**, while rendering
the SAME screen with the 17 components it now has yields **83 lines WITH them** — both executed,
not inferred. Six other explanations were eliminated first (apis_used, the decomposition, #547a,
the #449 player misclassification, reference_spec.json, and "the components never reached the
design"); see HANDOFF §5.0r.

The marker alone is not evidence of refinement. This predicate adds the evidence.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _stale_thin_projection_583 as stale,
)

_PREAMBLE = ("const _url = (u) => u;\n"
             "const _imgOf = (r) => null;\n"
             "const _titleOf = (r) => '';\n")

_THIN = """// framework-projected page
import { useState } from 'react';
""" + _PREAMBLE + """export default function P() {
  return (<div data-projected="ref"><main><p>x</p></main></div>);
}
"""

_RICH = """// framework-projected page
import { useState } from 'react';
""" + _PREAMBLE + """export default function P() {
  return (<div data-projected="ref"><main>
    <h2>Episodes</h2>
    <ul><li key={i}>ep</li></ul>
    <img src="x" />
  </main></div>);
}
"""


def test_r142_shape_a_marked_thin_page_is_stale():
    assert stale(_THIN, _RICH) is True


def test_a_page_that_pulls_in_lane_components_is_protected():
    """The failure mode this guard exists to prevent: clobbering real lane work."""
    refined = _THIN.replace("import { useState } from 'react';",
                            "import { useState } from 'react';\n"
                            "import TopNav from '../components/TopNav.jsx';")
    assert stale(refined, _RICH) is False


def test_one_missing_kind_is_not_enough():
    """A single structural difference can be incidental; two whole categories cannot."""
    almost = _RICH.replace("<img src=\"x\" />", "").replace("<h2>Episodes</h2>", "")
    # `almost` still has <ul>/<li>; the fresh render adds only <h2> and <img> back
    one_kind = _RICH.replace("<img src=\"x\" />", "")
    assert stale(almost, one_kind) is False


def test_a_hand_rewritten_page_without_the_projector_preamble_is_protected():
    """The #221 regression test's shape: a marked page the lane refined in place down to a
    single div carries no projector helpers, so it must never be re-clobbered. This condition
    was added because that existing test caught the first draft of this predicate."""
    refined = '// framework-projected page\nexport default function P() {\n  return <div data-projected="ref">refined-by-lane</div>;\n}\n'
    assert stale(refined, _RICH) is False


def test_an_equally_rich_page_is_left_alone():
    assert stale(_RICH, _RICH) is False


def test_empty_inputs_never_trigger():
    assert stale("", _RICH) is False
    assert stale(_THIN, "") is False
    assert stale(None, None) is False


def test_the_call_site_still_requires_a_structured_candidate():
    """A screen-matched-but-unprojectable page must never be DOWNGRADED (the #221 guard)."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs
    src = inspect.getsource(fs.scaffold_pages_from_contract)
    i = src.index("_stale_thin_projection_583(_existing, _cand)")
    window = src[max(0, i - 400):i]
    assert "_cand_ok" in window, window
    assert "_STRUCTURED_MARKER in _cand" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
