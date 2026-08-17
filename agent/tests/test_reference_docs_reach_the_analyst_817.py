r"""#817: the reference spec was cut at 4000 chars, dropping its actionable half, on 151/151 runs.

#816 fixed a truncation that produced INVALID JSON. Sweeping the same pattern found four other
prompt-bound truncations; three are honestly-named prose previews. The fourth was not:

    parts.append({"type": "text", "text": "REFERENCE DOCS:\n" + docs_text[:4000]})

Every run in the corpus stages a `spec.md`, and every one of them is **5,690 bytes** — 42% over the
cut. What fell past it:

  * the per-screen behaviour list — *"clicking a poster opens the title-detail modal"*,
    *"+ toggles My List"*, *"thumbs set the rating"*;
  * the whole `## Data model (tables)` and `## Seed data` sections;
  * the **Wiring rule** — *"EVERY nav link, button, icon and card must call a real endpoint ...
    no dead links, no inert placeholders, no fabricated data"*.

★ That last one is precisely what `frontend_dead_controls` blocks releases over, and the analyst
writing every component's `build_notes` never read it. 4000 was not a considered budget for a
5,690-char spec.

12,000 fits real specs with margin against the 6000-token reply. Past that the cut lands on a
markdown heading rather than mid-sentence, and names the sections it dropped (#811).
"""
import logging
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.design_prep import (
    _DOCS_BUDGET_817, _docs_for_prompt_817)


_SPEC = (pathlib.Path(__file__).resolve().parents[1]
         / "generated/netflix-web-r151/design/references/spec.md")


def test_the_real_spec_now_arrives_whole(caplog):
    if not _SPEC.is_file():
        pytest.skip("r151 spec not present")
    spec = _SPEC.read_text(encoding="utf-8", errors="ignore")
    assert len(spec) > 4000, "non-vacuity: the old cut really did bite this file"
    with caplog.at_level(logging.WARNING):
        out = _docs_for_prompt_817(spec)
    assert out == spec
    assert not caplog.records, "a doc within budget must be silent"


def test_the_parts_that_used_to_be_dropped_are_present():
    """★ Named individually, because 'the tail' understates what the tail was."""
    if not _SPEC.is_file():
        pytest.skip("r151 spec not present")
    out = _docs_for_prompt_817(_SPEC.read_text(encoding="utf-8", errors="ignore"))
    for marker in ("Wiring rule", "## Data model", "## Seed data", "toggles My List"):
        assert marker in out, marker


def test_an_oversized_doc_cuts_on_a_heading():
    big = "".join(f"## Section {i}\n" + "x" * 900 + "\n" for i in range(20))
    out = _docs_for_prompt_817(big)
    assert len(out) <= _DOCS_BUDGET_817
    assert out.rstrip().endswith("x"), "the kept text must end at a section, not mid-heading"
    assert "## Section" in out


def test_an_oversized_doc_names_what_it_dropped(caplog):
    big = "".join(f"## Section {i}\n" + "x" * 900 + "\n" for i in range(20))
    with caplog.at_level(logging.WARNING):
        _docs_for_prompt_817(big)
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "over the 12000 budget" in msg
    assert "will NOT see" in msg and "## Section 19" in msg


def test_an_unsectioned_overflow_still_says_something(caplog):
    with caplog.at_level(logging.WARNING):
        out = _docs_for_prompt_817("y" * 20000)
    assert len(out) == _DOCS_BUDGET_817
    assert "unsectioned tail" in " ".join(r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("bad", ["", None, 0])
def test_empty_input_is_not_an_error(bad):
    assert _docs_for_prompt_817(bad) in ("", "0")


def test_the_budget_is_not_smaller_than_the_corpus_spec():
    """A budget below the size of the doc every run stages is not a budget, it is the old bug."""
    if not _SPEC.is_file():
        pytest.skip("r151 spec not present")
    assert _DOCS_BUDGET_817 > _SPEC.stat().st_size


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
