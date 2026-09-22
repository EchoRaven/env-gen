r"""#778: the design system never asked what the words were.

`login` is the pipeline's single biggest obstacle — it fails the visual bar in **35 of 48** r99+
runs (73%) — and across those runs `copy` is the most frequent scoring floor (15 of 48, ahead of
`style`'s 12). r151's judge is explicit:

    Heading copy differs: 'Sign in' vs 'Enter your info to sign in' plus missing subheading
    Footer is missing Netflix House, Netflix Shop columns and the toll-free phone header
    copy 0.50   <- the floor, against layout 0.75 / color 0.85

**The words are in the reference image and the framework never asks for them.** `_SCREEN_PROMPT`
requests `build_notes` (geometry, padding, icons, borders), `typography` and `assets` per
component — and the component schema has exactly those slots. There is nowhere to put a string,
so the vision model describes instead of quoting:

    signin-heading      state='Enter your info to sign in' shown     <- quoted, 15%
    signin-subheading   state=muted secondary text                   <- described, 84%

Measured over 53 r99+ runs: **9152 text-bearing components, 1441 carry a quoted literal (15%),
7711 carry only a description (84%)** — `page-title: static`,
`language-filter-dropdown: collapsed, default value`. The 15% that do quote are burying the
string in prose, which is the tell that the slot was missing rather than the intent.

Three changes, and the third is the one this session has learned to check: a `copy` slot in the
function schema, a prompt clause demanding VERBATIM transcription, and **both fixed-key
projections** carrying it through. #767b, #768b and #771 were each a field added at one end and
silently dropped by a projection; this path has two.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import design_prep as dp


def _src() -> str:
    return inspect.getsource(dp)


# --- the slot exists -----------------------------------------------------------------------------

def test_the_component_schema_has_a_copy_slot():
    s = _src()
    assert '"copy": {"type": "string"}' in s


def test_the_existing_slots_are_untouched():
    s = _src()
    for keep in ('"build_notes": {"type": "string"}', '"typography": {"type": "object"}',
                 '"assets": {"type": "array"'):
        assert keep in s, keep


def test_build_notes_is_still_the_required_one():
    """#778 adds a slot; it must not make the model's existing obligation optional."""
    s = _src()
    assert '"required": ["id", "build_notes"]' in s


# --- the prompt asks for the words --------------------------------------------------------------

def test_the_prompt_demands_a_verbatim_transcription():
    s = _src()
    assert "transcribe it VERBATIM" in s
    assert "character for character" in s


def test_the_prompt_forbids_the_shape_that_dominates_today():
    """84% of components describe. The instruction has to name that failure, not just ask."""
    s = _src()
    assert "Do NOT describe it" in s
    assert "'muted secondary text', 'static'" in s


def test_the_prompt_says_why_it_matters():
    s = _src()
    assert "scored against the reference on COPY" in s
    assert "a description cannot be typed into JSX" in s


def test_it_allows_a_genuinely_textless_component():
    """An icon or a spacer must not be forced to invent a string."""
    s = _src()
    assert "Empty string only when the component genuinely renders no text" in s


# --- it survives BOTH projections -----------------------------------------------------------------

def test_the_skeleton_projection_carries_it():
    s = _src()
    i = s.index('"state": c.get("state") or ""')
    assert '"copy": ""' in s[i:s.index('"build_notes": ""', i)]


def test_the_merge_projection_carries_it():
    """What this guards is that `copy` survives the merge. The old form asserted the tuple's
    EXACT spelling, which is a proxy: it breaks the moment a key is legitimately added beside
    copy (#1202ri added `data_slots`) while the property it protects still holds. Parse the
    projection instead and look for the key."""
    import ast
    s = _src()
    tree = ast.parse(s)
    projections = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        it = node.iter
        if not isinstance(it, ast.Tuple):
            continue
        keys = [e.value for e in it.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if "role" in keys and "build_notes" in keys:
            projections.append(keys)
    assert projections, "the enrichment merge projection is gone"
    for keys in projections:
        assert "copy" in keys, "the merge drops `copy` again (#778)"
        assert "state" in keys and "typography" in keys


def test_the_projection_risk_is_recorded_where_it_bites():
    """The comment has to sit at the projection, not only in this file — that is where the next
    person adds a field."""
    s = _src()
    i = s.index('"state", "copy"')
    blk = s[max(0, i - 400):i]
    assert "767b" in blk and "771" in blk


# --- provenance ----------------------------------------------------------------------------------------

def test_the_measurement_is_recorded_in_the_schema_comment():
    s = _src()
    i = s.index('"copy": {"type": "string"}')
    blk = s[max(0, i - 700):i]
    assert "84% of 9152 text components" in blk
    assert "blocks 73% of runs" in blk


def test_the_15_percent_tell_is_recorded():
    s = _src()
    i = s.index('"copy": {"type": "string"}')
    blk = s[max(0, i - 700):i]
    assert "burying it" in blk and "the slot was missing" in blk


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
