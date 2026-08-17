r"""#816: the analyst was handed truncated — therefore invalid — JSON, on 7 of 20 screens.

The fourth evaporation point for the design-prep enrichment, after the call (#813), the join
(#815) and an empty reply. The skeleton was serialised whole and cut at 9000 characters:

    json.dumps(s, indent=1)[:9000]

Measured on r151:

    7 of 20 screens exceed 9000 chars    median overflow 2,733
    largest: new_and_popular at 13,563

★ A JSON object cut mid-structure is **not valid JSON**. So on a third of the screens the analyst
was asked to *"enrich THESE components by id"* from a malformed document — and every component
past the cut has an id it never saw. That is enough on its own to produce either a non-dict reply
(#813's branch) or an answer keyed on invented ids (#815's branch).

The fix is not a bigger cut — the 6000-token reply budget is the real constraint — it is to send
**only what the analyst needs**. Its job is to ADD `build_notes`/`typography`/`copy` per id; it
does not need crop paths, full colour dicts, geometry, or six-decimal regions echoed back.
Projecting to id/role/state/region/bg:

    largest screen  13,563 -> 5,450 chars      every screen fits, with room
    total           178,958 -> 61,386 (34%)    zero invalid JSON
    every skeleton id present in the prompt    <- the join key, on every screen

The residual cut is kept as a backstop but is no longer silent (#811).
"""
import json
import logging
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.design_prep import (
    _skeleton_for_prompt_816)


_GENERATED = pathlib.Path(__file__).resolve().parents[1] / "generated"


def _r151():
    f = _GENERATED / "netflix-web-r151" / "design" / "design_system.json"
    if not f.is_file():
        pytest.skip("r151 not present")
    return json.loads(f.read_text(encoding="utf-8"))


def test_the_corpus_screens_are_really_large():
    """Non-vacuity for the whole item: without this, a shrunken corpus would make the fix look
    unnecessary rather than done."""
    ds = _r151()
    full = [len(json.dumps(s, indent=1)) for s in ds["screens"]]
    assert max(full) > 9000, f"largest screen only {max(full)} chars"
    assert sum(1 for n in full if n > 9000) >= 5


def test_every_screen_now_fits_and_stays_valid_json():
    ds = _r151()
    for s in ds["screens"]:
        out = _skeleton_for_prompt_816(s)
        assert len(out) <= 9000, (s.get("name"), len(out))
        json.loads(out)                      # would raise on a mid-structure cut


def test_every_join_key_survives():
    """★ The point of the whole thing. `id` is what the merge joins on (#815); a component whose
    id never reaches the analyst cannot come back enriched."""
    ds = _r151()
    for s in ds["screens"]:
        sent = {c["id"] for c in json.loads(_skeleton_for_prompt_816(s))["components"]}
        assert sent == {c.get("id") for c in s["components"]}, s.get("name")


def test_the_bulk_is_dropped_but_the_context_is_kept():
    ds = _r151()
    comp = json.loads(_skeleton_for_prompt_816(ds["screens"][0]))["components"][0]
    assert "id" in comp and "role" in comp
    assert "crop" not in comp and "geometry" not in comp and "colors" not in comp


def test_empty_values_are_not_emitted():
    out = json.loads(_skeleton_for_prompt_816(
        {"name": "x", "components": [{"id": "a", "role": "", "region": [], "state": None}]}))
    assert out["components"][0] == {"id": "a"}


@pytest.mark.parametrize("screen", [
    {}, {"components": None}, {"components": ["nope", 3]},
    {"components": [{"id": "a", "region": ["x", "y"]}]},
])
def test_malformed_screens_never_raise(screen):
    """design-prep runs before any lane; a fault here costs the whole visual pipeline."""
    try:
        json.loads(_skeleton_for_prompt_816(screen))
    except (TypeError, ValueError):
        pytest.fail("the projection must always emit parseable JSON")


def test_a_residual_overflow_is_announced(caplog):
    """#811: the backstop stays, the silence does not."""
    huge = {"name": "huge", "components": [
        {"id": f"c{i}", "role": "x" * 400} for i in range(60)]}
    with caplog.at_level(logging.WARNING):
        out = _skeleton_for_prompt_816(huge)
    assert len(out) == 9000
    assert any("even COMPACTED" in r.getMessage() for r in caplog.records)


def test_a_normal_screen_is_silent(caplog):
    with caplog.at_level(logging.WARNING):
        _skeleton_for_prompt_816(_r151()["screens"][0])
    assert not [r for r in caplog.records if "COMPACTED" in r.getMessage()]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
