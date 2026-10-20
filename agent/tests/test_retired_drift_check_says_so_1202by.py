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


from env_generator.llm_generator.multi_agent.runtime import (  # noqa: E402
    delivery_gate as dg)


def _render(gate: dict):
    """#1203qp: the REAL stanza, not a copy of it.

    This used to be a transcription documented as "run just the drift stanza the way
    delivery_gate builds it", and three of this file's tests drove the transcription while
    the other two read delivery_gate.py as text -- so no test here could see a change to the
    stanza itself. The copy was also partial: it stopped at the counts and left out the
    ERROR/WARN lines, which are now covered too."""
    return dg._semantic_drift_lines_1203qp(gate.get("semantic_hub_drift", {}))


def test_the_findings_are_rendered_too_1203qp():
    """The half the copy omitted, so nothing here ever drove it."""
    out = _render({"semantic_hub_drift": {"errors": ["e1"], "warnings": ["w1"]}})
    assert "- Semantic hub drift (counts not measured):" in out, out
    assert "  \u2022 ERROR: e1" in out, out
    assert "  \u2022 WARN: w1" in out, out


def test_nothing_renders_for_an_empty_or_unusable_drift_1203qp():
    for bad in ({}, None, [], "drift"):
        assert _render({"semantic_hub_drift": bad}) == [], bad
    assert _render({}) == []


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


def _gate_assignment_1203qp(name):
    """The AST node that assigns `<name> = ...` at any depth in delivery_gate, or None."""
    import ast
    import inspect
    from multi_agent.runtime import delivery_gate as _dg
    for n in ast.walk(ast.parse(inspect.getsource(_dg))):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name):
            return n
    return None


def _gate_extend_args_1203qp(func_name):
    """Every `*.extend(<arg>)` whose arg mentions `func_name`, as AST nodes."""
    import ast
    import inspect
    from multi_agent.runtime import delivery_gate as _dg
    out = []
    for n in ast.walk(ast.parse(inspect.getsource(_dg))):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "extend" and n.args
                and func_name in ast.dump(n.args[0])):
            out.append(n.args[0])
    return out


def test_the_stanza_reaches_the_report_whole_1203qp():
    """ARRIVAL. A call-site COUNT cannot see this: slicing the result to `[:0]` keeps the
    call and the name, and the section still vanishes from the report. So the ARGUMENT of
    the extend has to be the bare call, not something wrapping it."""
    import ast
    args = _gate_extend_args_1203qp("_semantic_drift_lines_1203qp")
    assert len(args) == 1, "%d extend site(s) pass the stanza" % len(args)
    assert isinstance(args[0], ast.Call), ast.dump(args[0])[:200]
    assert isinstance(args[0].func, ast.Name), ast.dump(args[0])[:200]
    assert args[0].func.id == "_semantic_drift_lines_1203qp"
