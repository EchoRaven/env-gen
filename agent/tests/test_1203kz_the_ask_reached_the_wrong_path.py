"""#1203kz: the verbatim-copy ask reached the path that does not run.

`copy` is the per-component text transcribed from the reference screenshot. Three parts of the
framework depend on it:

  * `visual_fidelity`'s judged dimensions include `{"key": "copy", "title": "UI copy & labels"}`;
  * #797 builds the repair round a block from it -- "REFERENCE COPY (verbatim -- render these
    strings character for character; do not paraphrase, translate or substitute a synonym)";
  * #778 measured why it exists: 9152 text components across the corpus, 84% of whose notes
    DESCRIBED the text rather than quoting it, "which is why `ui_copy` keeps scoring as a floor".

And the ask for it lived only inside `_SCREEN_PROMPT`, which belongs to the single-shot
per-screen enrichment -- a FALLBACK. The agent that actually writes design/design_system.json is
the spawned design_analyst, and `build_design_analyst_briefing` named neither `copy` nor
`data_slots`.

MEASURED across every run on disk: components with a non-empty `copy` are 4640 of 21159 before
r100 (26 runs, when the single-shot path was in use), then 0 of 1725 in r100-149 and 0 of 1341
across the 39 modern runs -- zero for 89 consecutive runs, while #797's block rendered nothing
and said nothing.

BOTH HALVES: `copy` is asked for together with the #1202ri chrome-vs-data rule, because asking
for one without the other is the harm #1202ri was written for -- "a profile header transcribed
as copy shipped the operator's own real handle into four generated runs" -- and `data_slots` is
where that data must go instead, which material_prep then scrubs for identity values.
"""
import ast
import inspect
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import design_prep as DP  # noqa: E402


def test_the_briefing_asks_the_agent_that_writes_the_doc():
    brief = DP.build_design_analyst_briefing("/tmp/nowhere", {"references": ["a/login.png"]})
    # the ask itself
    assert "transcribe it VERBATIM" in brief, brief
    assert "character for character" in brief, brief
    # NON-VACUITY: the briefing still does its original job
    assert "design/design_system.json" in brief and "decompose_reference" in brief, brief


def test_both_halves_are_asked_for_or_neither():
    """#1202ri: `copy` without the chrome-vs-data rule is the defect that rule exists for."""
    brief = DP.build_design_analyst_briefing("/tmp/nowhere", {})
    assert "data_slots" in brief, brief
    assert "CHROME TEXT ONLY" in brief, brief
    # the named harm, so a reader cannot drop the half that prevents it
    assert "real handle" in brief, brief
    # and the single-shot path still carries exactly the same wording
    assert "transcribe it VERBATIM" in DP._SCREEN_PROMPT
    assert "CHROME TEXT ONLY" in DP._SCREEN_PROMPT


def test_the_rule_has_one_owner():
    """#1032: the two prompts must share the text, not each hold a copy that can drift."""
    src = Path(inspect.getfile(DP)).read_text(encoding="utf-8")
    tree = ast.parse(src)
    lits = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "transcribe it VERBATIM" in n.value]
    assert len(lits) == 1, ("the ask appears as %d separate literals" % len(lits))
    # and both consumers reference the constant by name
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_COPY_RULE_1203KZ" in names


def _doc(comps):
    return {"design_system": {"palette": {"bg": "#000"}},
            "screens": [{"name": "home", "components": comps}], "assets": []}


def test_the_completion_pass_counts_and_names_the_empty_case(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="Orchestrator"):
        DP.complete_design_system(_doc([{"id": "a", "copy": ""},
                                        {"id": "b"}]), {}, tmp_path)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "0 carrying verbatim copy" in said, said
    assert "NOT ONE of 2 components" in said, said
    assert "1203kz" in said, said


def test_a_doc_that_carries_copy_is_not_scolded(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="Orchestrator"):
        DP.complete_design_system(_doc([{"id": "a", "copy": "Log in"},
                                        {"id": "b", "copy": ""}]), {}, tmp_path)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "1 carrying verbatim copy" in said, said
    assert "NOT ONE" not in said, said


def test_the_counter_agrees_with_a_real_corpus_document(tmp_path, caplog):
    """Driven with real components rather than my fixtures. Deliberately asserts AGREEMENT,
    not the corpus's current zero: an assertion that the corpus still has none would go red
    the day the briefing starts working, which is the wrong direction for a test to fail in.
    The zero belongs in the commit message and the ledger. Skipped when the corpus is absent.
    """
    import pytest
    comps = None
    for p in sorted((ROOT.parent / "generated").glob("*/design/design_system.json")):
        m = re.search(r"r(\d+)$", p.parent.parent.name)
        if not m or int(m.group(1)) < 150:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        got = [c for s in (d.get("screens") or []) for c in (s.get("components") or [])
               if isinstance(c, dict)]
        if got:
            comps = got
            break
    if not comps:
        pytest.skip("no corpus design document with components on this disk")
    expect = sum(1 for c in comps if str(c.get("copy") or "").strip())
    with caplog.at_level(logging.INFO, logger="Orchestrator"):
        DP.complete_design_system(_doc([dict(c) for c in comps]), {}, tmp_path)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "%d carrying verbatim copy" % expect in said, (expect, said)
    assert ("NOT ONE of %d components" % len(comps) in said) == (expect == 0), said
