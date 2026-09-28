"""#1202wp: the reference-doc sections withheld from the analyst must survive the run.

`_docs_for_prompt_817` cuts the reference docs at a section boundary when they exceed the
12,000-char budget, and #811 already names the dropped sections -- into a log line, and run
logs are not kept.

What falls past that cut is not filler. The function's own docstring records what the
4000-char era dropped from r151's spec: the per-screen behaviour list ("clicking a poster
opens the title-detail modal"), the whole `## Data model (tables)` and `## Seed data`
sections, and the Wiring rule -- "EVERY nav link, button, icon and card must call a real
endpoint" -- which is precisely what `frontend_dead_controls` blocks releases over. So when
an analyst's spec turns out to be missing exactly those things, the run directory should be
able to say whether the analyst was ever shown them.

Currently low-frequency: measured across the four design-input domains, only instagram
(30,074 chars) exceeds the budget; tiktok (8,452), netflix (7,652) and google_maps (10,200)
do not. Fixed anyway -- a real defect does not stop being one for firing on one domain, and
the whole cost is one appended line at the moment of the cut.
"""
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.design_prep import (  # noqa: E402
    _DOCS_BUDGET_817,
    _docs_for_prompt_817,
)


def _doc(*sections):
    """A markdown doc whose sections each overflow a third of the budget."""
    pad = "x" * (_DOCS_BUDGET_817 // 2)
    return "\n".join("# %s\n%s" % (s, pad) for s in sections)


def _rows(tmp_path):
    p = tmp_path / "logs" / "docs_withheld_1202wp.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_a_doc_under_budget_writes_nothing(tmp_path):
    out = _docs_for_prompt_817("# Small\nhello", tmp_path)
    assert out == "# Small\nhello"
    assert not (tmp_path / "logs").exists(), "nothing was withheld, so there is nothing to say"


def test_the_withheld_sections_are_named(tmp_path):
    _docs_for_prompt_817(_doc("Overview", "Data model (tables)", "Seed data"), tmp_path)
    row = _rows(tmp_path)[0]
    assert row["withheld_count"] == 2, row
    assert row["withheld"] == ["# Data model (tables)", "# Seed data"], row


def test_the_sizes_explain_the_cut(tmp_path):
    text = _doc("A", "B", "C")
    kept = _docs_for_prompt_817(text, tmp_path)
    row = _rows(tmp_path)[0]
    assert row["total_chars"] == len(text)
    assert row["kept_chars"] == len(kept)
    assert row["budget"] == _DOCS_BUDGET_817


def test_an_unsectioned_tail_still_says_something(tmp_path):
    """A doc with no headings past the cut must not record an empty list as 'nothing lost'."""
    _docs_for_prompt_817("x" * (_DOCS_BUDGET_817 * 2), tmp_path)
    assert _rows(tmp_path)[0]["withheld"] == ["<unsectioned tail>"]


def test_without_an_output_dir_the_cut_still_happens(tmp_path):
    """Recording is best-effort; it must never change what the analyst receives."""
    text = _doc("A", "B")
    with_dir = _docs_for_prompt_817(text, tmp_path)
    without = _docs_for_prompt_817(text, None)
    assert with_dir == without and len(without) < len(text)


def test_the_count_survives_a_capped_roster(tmp_path):
    """#1034: a doc with many dropped sections keeps its true count."""
    text = _doc(*["S%d" % i for i in range(40)])
    _docs_for_prompt_817(text, tmp_path)
    row = _rows(tmp_path)[0]
    assert row["withheld_count"] > 30, row
    assert len(row["withheld"]) == 30


def test_the_recorder_is_called_from_the_cut():
    """★ A recorder nobody calls is the defect #1202wm was about."""
    import ast

    path = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                        "design_prep.py")
    with open(path, encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_docs_for_prompt_817"), None)
    assert fn is not None, "_docs_for_prompt_817 is gone"
    assert any(isinstance(c, ast.Call)
               and getattr(c.func, "id", "") == "_record_docs_withheld_1202wp"
               for c in ast.walk(fn)), "the cut happens and leaves no evidence"
