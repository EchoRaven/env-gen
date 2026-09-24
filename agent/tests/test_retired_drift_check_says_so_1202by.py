"""#1202by — a retired check must not print zeros that read as a measurement.

`semantic_hub_drift` is vestigial: delivery_gate builds it as {"errors": [], "warnings": []}
and nothing ever fills the six count fields, so every `.get(key, 0)` fell through and the
report claimed `spec_pages=0, hub_pages=0` two lines above `hub counts: pages=30`. "Did not
run" looked exactly like "found nothing". The report is handed to lanes as remediation
context, so the contradiction costs lane turns. LOCAL-ONLY (agent/tests/ gitignored).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

GATE = LLM / "multi_agent" / "runtime" / "delivery_gate.py"


def _render(gate: dict):
    """Run just the drift stanza the way delivery_gate builds it."""
    lines = []
    semantic_drift = gate.get("semantic_hub_drift", {})
    if semantic_drift:
        _counts = [(k, semantic_drift[k]) for k in
                   ("spec_endpoints", "hub_endpoints", "spec_tables",
                    "hub_tables", "spec_pages", "hub_pages") if k in semantic_drift]
        if _counts:
            lines.append("- Semantic hub drift: "
                         + ", ".join(f"{k}={v}" for k, v in _counts))
        elif semantic_drift.get("errors") or semantic_drift.get("warnings"):
            lines.append("- Semantic hub drift (counts not measured):")
    return lines


def test_the_vestigial_shape_prints_no_counts():
    """The exact dict delivery_gate constructs today."""
    assert _render({"semantic_hub_drift": {"errors": [], "warnings": []}}) == []


def test_a_revived_check_still_reports_its_counts():
    """The stanza must keep working if the check is ever given real keys again."""
    out = _render({"semantic_hub_drift": {"spec_pages": 18, "hub_pages": 30}})
    assert out and "spec_pages=18" in out[0] and "hub_pages=30" in out[0]


def test_findings_without_counts_are_still_announced():
    out = _render({"semantic_hub_drift": {"errors": ["x"], "warnings": []}})
    assert out and "not measured" in out[0]


def test_the_gate_no_longer_defaults_the_counts_to_zero():
    """The defect in one line: six `.get(..., 0)` calls turned a retired check into a
    clean-looking measurement. #943: anchor on the stanza, not a byte window."""
    src = GATE.read_text(encoding="utf-8")
    i = src.index('semantic_drift = gate.get("semantic_hub_drift"')
    stanza = src[i:src.index("projection_errors = gate.get(", i)]
    assert "spec_endpoints', 0)" not in stanza and 'spec_endpoints", 0)' not in stanza
    assert "hub_pages', 0)" not in stanza and 'hub_pages", 0)' not in stanza


def test_the_check_is_still_declared_vestigial_where_it_is_built():
    """If someone revives the check, this test should fail and make them revisit the
    reporter above rather than silently reinstating the zeros."""
    src = GATE.read_text(encoding="utf-8")
    assert re.search(r'semantic_drift = \{"errors": \[\], "warnings": \[\]\}\s*#\s*vestigial',
                     src)
