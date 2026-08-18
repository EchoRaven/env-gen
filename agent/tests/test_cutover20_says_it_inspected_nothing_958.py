r"""#958: the Cutover-20 visual-review gate can never fire.

`_visual_summary` reads `gate_registry.list_critical_visual_reviews()`, which filters the ui_pages
store for `kind == "visual_review"` and `metadata.critical is True`. Across the corpus:

    ui_pages records          2405
    kind == "ui_page"         2405
    kind == "visual_review"      0   in 0 runs

Both blockers keyed on it are `> 0` tests on a value that is structurally 0, so Cutover 20 has
never blocked anything, and its all-zero line reads as "reviews done" rather than "none exist".

★ Not repaired: making it fire requires deciding WHO creates a visual_review page and WHEN — a
workflow design question, not a fix. Announced, in the disposition of #956 and #957.
"""
import json
import logging
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime import deliverability as dl


def test_the_summary_is_zero_when_nothing_is_registered():
    class Gate:
        def list_critical_visual_reviews(self):
            return []

    class Hub:
        gate_registry = Gate()

    assert dl._visual_summary(Hub()) == {"critical_total": 0, "approved": 0,
                                         "pending": 0, "needs_revision": 0}


def test_it_counts_real_records_when_they_exist():
    """★ Non-vacuity: the summary is not hardcoded — it would work if anything registered."""
    class Gate:
        def list_critical_visual_reviews(self):
            return [{"status": "approved"}, {"status": "pending"},
                    {"status": "needs_revision"}]

    class Hub:
        gate_registry = Gate()

    assert dl._visual_summary(Hub()) == {"critical_total": 3, "approved": 1,
                                         "pending": 1, "needs_revision": 1}


def test_the_dead_state_is_announced_once():
    """A line that fires every tick stops being read (#845)."""
    dl._SAID_958.clear()
    import ast
    import inspect
    src = inspect.getsource(dl.compute_deliverability)
    assert "_SAID_958" in src and "#958" in src
    tree = ast.parse(src.strip())
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.If)
              and "_SAID_958" in ast.unparse(n.test)]
    assert guards, "the announcement must be one-shot"


def test_the_corpus_premise_holds():
    """★ If a visual_review page ever gets created, this ticket's premise is wrong and the test
    must say so rather than rot into a stale claim."""
    gen = pathlib.Path(__file__).resolve().parents[1] / "generated"
    files = list(gen.glob("*/shared/hubs/registryhub_ui_pages.json"))
    if not files:
        pytest.skip("no runs on this box")
    vr = 0
    for f in files:
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        vr += sum(1 for k, v in d.items()
                  if k != "_meta" and isinstance(v, dict) and v.get("kind") == "visual_review")
    assert vr == 0, f"{vr} visual_review page(s) now exist — Cutover 20 may be live; revisit #958"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
