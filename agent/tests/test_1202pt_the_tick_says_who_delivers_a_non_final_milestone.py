"""#1202pt: before the final milestone the coordination tick must not tell the orchestrator
to call deliver_project (which is not offered), and must say the gate's repair tasks are live."""
import ast
from pathlib import Path
from types import SimpleNamespace

from env_generator.llm_generator.multi_agent import orchestrator as orch


def test_a_non_final_milestone_says_the_framework_delivers():
    line = orch._tick_delivery_line_1202pt(SimpleNamespace(_is_final_milestone=False))
    assert "deliver_project()" not in line.replace("deliver_project is not", "")
    assert "do not cancel" in line


def test_the_final_milestone_and_an_unstamped_lane_keep_the_old_instruction():
    for lane in (SimpleNamespace(_is_final_milestone=True), SimpleNamespace()):
        assert orch._tick_delivery_line_1202pt(lane).startswith(
            "If validation has passed and deliverables are ready, call deliver_project().")


def test_the_tick_instruction_uses_it():
    tree = ast.parse(Path(orch.__file__).read_text(encoding="utf-8"))
    hits = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value == "instruction" for k in n.keys)
            and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_tick_delivery_line_1202pt"
                    for c in ast.walk(n))]
    assert hits, "the resident_coordination_tick instruction no longer calls the helper"
    src = Path(orch.__file__).read_text(encoding="utf-8")
    assert src.count("If validation has passed and deliverables are ready, call deliver_project().") == 1
