"""#1202bv — a --resume INHERITS the design_system.json it already paid an analyst for.

design-prep is the most expensive PREFIX of a run. Before this fix a resume re-ran it
unconditionally: `write_skeleton_design_system` overwrote the enriched doc with a bare
skeleton and the design_analyst was respawned — so a resume did not merely re-derive the
doc, it DESTROYED the old one first. (r17: three resumes, $299, no delivery; $635 total
against $400 for a fresh run.)

Reuse is allowed only when BOTH hold: the doc passes `design_system_is_enriched` (the same
predicate the normal path uses), and the recorded fingerprint matches the design input
resolved now. LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.design_prep import (  # noqa: E402
    design_prep_reusable_1202bv, record_design_prep_input_1202bv,
    design_system_is_enriched)

RESOLVED = {"references": ["/refs/home.png", "/refs/detail.png"], "docs": ["/refs/spec.md"]}
ENRICHED = {"design_system": {"palette": {"bg": "#141414"}, "type_scale": {"h1": "32px"}},
            "screens": [{"name": "home", "components": [{"name": "hero",
                                                         "build_notes": "measured 32px"}]}]}
HOLLOW = {"design_system": {"palette": {"bg": "#141414"}}, "screens": [{"name": "home"}]}


def _lay(tmp_path, doc):
    d = tmp_path / "design"
    d.mkdir(parents=True, exist_ok=True)
    (d / "design_system.json").write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_known_answer_the_two_sample_docs_are_what_the_test_claims():
    """Guard the fixtures themselves: if `enriched` ever stopped judging these two apart,
    every other assertion here would pass for the wrong reason."""
    assert design_system_is_enriched(ENRICHED) is True
    assert design_system_is_enriched(HOLLOW) is False


def test_no_doc_on_disk_is_not_reusable(tmp_path):
    assert design_prep_reusable_1202bv(tmp_path, "/refs", RESOLVED) is False


def test_hollow_doc_is_not_reusable_even_with_a_matching_fingerprint(tmp_path):
    _lay(tmp_path, HOLLOW)
    record_design_prep_input_1202bv(tmp_path, "/refs", RESOLVED)
    assert design_prep_reusable_1202bv(tmp_path, "/refs", RESOLVED) is False


def test_enriched_doc_without_a_fingerprint_is_not_reusable(tmp_path):
    """A doc written before this fix records nothing about what it was measured from;
    inheriting it would be guessing."""
    _lay(tmp_path, ENRICHED)
    assert design_prep_reusable_1202bv(tmp_path, "/refs", RESOLVED) is False


def test_enriched_doc_with_a_matching_fingerprint_is_reusable(tmp_path):
    _lay(tmp_path, ENRICHED)
    record_design_prep_input_1202bv(tmp_path, "/refs", RESOLVED)
    assert design_prep_reusable_1202bv(tmp_path, "/refs", RESOLVED) is True


def test_reference_order_does_not_force_a_needless_rerun(tmp_path):
    _lay(tmp_path, ENRICHED)
    record_design_prep_input_1202bv(tmp_path, "/refs", RESOLVED)
    shuffled = {"references": list(reversed(RESOLVED["references"])), "docs": RESOLVED["docs"]}
    assert design_prep_reusable_1202bv(tmp_path, "/refs", shuffled) is True


def test_a_changed_design_input_is_not_reusable(tmp_path):
    """The failure this guards: resuming with different references must not inherit a doc
    measured from the old ones."""
    _lay(tmp_path, ENRICHED)
    record_design_prep_input_1202bv(tmp_path, "/refs", RESOLVED)
    other = {"references": ["/refs2/other.png"], "docs": []}
    assert design_prep_reusable_1202bv(tmp_path, "/refs2", other) is False


def test_a_dropped_reference_is_not_reusable(tmp_path):
    _lay(tmp_path, ENRICHED)
    record_design_prep_input_1202bv(tmp_path, "/refs", RESOLVED)
    fewer = {"references": RESOLVED["references"][:1], "docs": RESOLVED["docs"]}
    assert design_prep_reusable_1202bv(tmp_path, "/refs", fewer) is False


def test_orchestrator_gates_the_skeleton_write_behind_the_resume_check():
    """#943: landmark anchors, never a fixed byte window. The skeleton overwrite and the
    analyst spawn must both sit on the ELSE side of the #1202bv guard — if either escapes
    it, a resume destroys the doc again and the reuse above is dead code."""
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    guard = src.index("if getattr(self, \"_resume\", False) and design_prep_reusable_1202bv(")
    region = src[guard:src.index("# Validate the agent's output", guard)]
    assert "else:" in region
    body = region[region.index("else:"):]
    assert "write_skeleton_design_system(resolved, self.output_dir)" in body
    assert "await self._spawn_design_analyst(resolved)" in body
    assert "record_design_prep_input_1202bv(" in body


def test_orchestrator_records_resume_for_the_design_prep_phase():
    """design-prep runs in a method that cannot see the `resume` parameter; without this
    the guard silently reads False forever and the fix never fires."""
    src = (LLM / "multi_agent" / "orchestrator.py").read_text(encoding="utf-8")
    assert "self._resume = bool(resume)" in src
