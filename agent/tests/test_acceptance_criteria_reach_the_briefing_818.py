r"""#818: the acceptance criteria were cut mid-sentence at 1,500 chars — in 150 of 150 runs.

#817 fixed the reference DOC truncation on the design-prep path. The same doc is read again by
`reference_materials`, which renders a briefing from the extracted `reference_spec.json`. Five
sections, five caps. Measured over every corpus spec:

    section      cap    overflowing runs   median   max
    screens     1500          0/150           206     206
    endpoints   2000          0/150           395     395
    entities    2000          0/150           100     100
    mcp_tools    800          0/150             0       0
    acceptance  1500        150/150         2,156   3,202

★ Exactly one section is mis-sized, and it is **the machine-checkable criteria the run is judged
against** — cut mid-sentence, in every run in the corpus. The other four caps were never close to
binding, which is why this survived: four correct numbers next to one wrong one reads as a
considered scheme.

4,000 clears the observed maximum with ~25% margin. Past that the cut lands on an **item**
boundary and states how many criteria were dropped and where to read them (#811) — a criterion
sliced in half is worse than one omitted, because it still looks like an instruction.
"""
import json
import logging
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime.reference_materials import (
    _ACCEPTANCE_BUDGET_818, _acceptance_line_818)


_GENERATED = pathlib.Path(__file__).resolve().parents[1] / "generated"


def _specs():
    out = []
    if not _GENERATED.is_dir():
        return out
    for r in sorted(_GENERATED.iterdir()):
        f = r / "design" / "reference_spec.json"
        if f.is_file():
            try:
                out.append((r.name, json.loads(f.read_text(encoding="utf-8"))))
            except Exception:
                pass
    return out


_SPECS = _specs()


def test_the_corpus_really_overflowed_the_old_cap():
    """Non-vacuity: without this, a shrunken corpus makes the fix look unnecessary."""
    if not _SPECS:
        pytest.skip("no corpus")
    lens = [len(" | ".join(map(str, s.get("acceptance") or []))) for _, s in _SPECS]
    assert max(lens) > 1500
    assert sum(1 for n in lens if n > 1500) > len(lens) * 0.9, "it overflowed nearly everywhere"


def test_no_corpus_spec_is_truncated_now(caplog):
    if not _SPECS:
        pytest.skip("no corpus")
    with caplog.at_level(logging.WARNING):
        for name, s in _SPECS:
            out = _acceptance_line_818(s.get("acceptance") or [])
            assert "… and" not in out, name
    assert not caplog.records


def test_an_oversized_list_cuts_on_an_item_boundary():
    items = [f"criterion number {i} " + "y" * 120 for i in range(60)]
    out = _acceptance_line_818(items)
    assert not out.endswith("y"), "a criterion sliced in half still looks like an instruction"
    assert out.rstrip().endswith("design/reference_spec.json")


def test_it_says_how_many_were_dropped(caplog):
    items = [f"criterion {i} " + "y" * 120 for i in range(60)]
    with caplog.at_level(logging.WARNING):
        out = _acceptance_line_818(items)
    assert "more acceptance criterion(s)" in out
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "acceptance criteria dropped" in msg and "of 60" in msg


def test_a_short_list_is_untouched_and_silent(caplog):
    with caplog.at_level(logging.WARNING):
        assert _acceptance_line_818(["a", "b"]) == "a | b"
    assert not caplog.records


@pytest.mark.parametrize("bad", [None, [], [None, 3]])
def test_malformed_input_never_raises(bad):
    _acceptance_line_818(bad)


def test_the_budget_clears_the_observed_maximum():
    """A budget below what the corpus actually produces is not a budget — that was the bug."""
    if not _SPECS:
        pytest.skip("no corpus")
    worst = max(len(" | ".join(map(str, s.get("acceptance") or []))) for _, s in _SPECS)
    assert _ACCEPTANCE_BUDGET_818 > worst


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
