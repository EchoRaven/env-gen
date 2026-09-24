"""#339: a gate suggestion may only name a tool that actually exists.

The delivery gate hands the agent remediation text with backticked call
examples. Several named things that are not tools at all:

  * `record_validation_result(...)` -- a HubRegistry METHOD
    (runtime/hub_registry.py), never a registered tool. Agents tried to call it
    35 times across r91/r92/r93 (3 + 12 + 20).
  * `update_endpoint(...)` / `update_table(...)` / `workhub.update_ui_page(...)`
    -- no such tools; the real ones are registryhub_register_endpoint /
    registryhub_register_table / registryhub_register_ui_page.

An instruction naming a nonexistent tool cannot be followed by any agent, in
any role, in any stage. It is a pure framework defect, and today it is only
discoverable by watching an agent waste turns on it live.

This is the first (narrow, zero-false-positive) rung of the build-time
tool-name assertion two independent trajectory audits converged on. It is
deliberately scoped to AGENT-FACING gate suggestions -- the strings appended to
`suggestions` -- and NOT to docstrings or maintainer comments, which
legitimately mention internal Python methods like `get_verification_chains()`.

A later rung can widen this to prompt templates and per-role reachability
(the tool must also be SURFACED to the addressed role); that one has ~113
existing violations and has to land as a report first.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for _p in (str(ROOT), str(LLM_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TOOLS_DIR = LLM_DIR / "tools"
GATE = LLM_DIR / "multi_agent" / "runtime" / "delivery_gate.py"

_CALL_RE = re.compile(r"`(?:([a-z_][a-z0-9_]*)\.)?([a-z_][a-z0-9_]{3,})\(")


def registered_tool_names() -> set:
    names = set()
    for p in TOOLS_DIR.rglob("*.py"):
        names |= set(re.findall(
            r'NAME(?:\s*:\s*str)?\s*=\s*["\']([a-z_][a-z0-9_]*)["\']',
            p.read_text(errors="ignore")))
    return names


def gate_suggestion_strings() -> list:
    """Every string literal appended to `suggestions` in delivery_gate.py."""
    out = []
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "suggestions"):
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.append(sub.value)
    return out


class TheHarnessSeesWhatItShould(unittest.TestCase):
    """If these break, the assertion below has gone blind."""

    def test_tool_registry_is_populated(self):
        self.assertGreater(len(registered_tool_names()), 200)

    def test_suggestions_are_extracted(self):
        self.assertGreater(len(gate_suggestion_strings()), 10)

    def test_a_known_real_tool_is_recognised(self):
        self.assertIn("codehub_record_check", registered_tool_names())


class EveryGateSuggestionNamesARealTool(unittest.TestCase):

    def test_no_phantom_tool_in_any_gate_suggestion(self):
        tools = registered_tool_names()
        phantoms = {}
        for text in gate_suggestion_strings():
            for obj, name in _CALL_RE.findall(text):
                if name not in tools:
                    phantoms.setdefault(
                        f"{obj + '.' if obj else ''}{name}", []).append(text[:90])
        self.assertEqual(
            phantoms, {},
            "delivery-gate suggestions name tools that do not exist:\n" +
            "\n".join(f"  {k} -> {v[0]!r}" for k, v in sorted(phantoms.items())))

    def test_the_known_phantoms_are_gone(self):
        blob = "\n".join(gate_suggestion_strings())
        for dead in ("record_validation_result(", "update_endpoint(",
                     "update_table(", "workhub.update_ui_page("):
            self.assertNotIn(dead, blob, f"{dead} is not a callable tool")

    def test_the_replacements_are_present_and_real(self):
        blob = "\n".join(gate_suggestion_strings())
        tools = registered_tool_names()
        for live in ("codehub_record_check", "registryhub_register_endpoint",
                     "registryhub_register_table", "registryhub_register_ui_page"):
            self.assertIn(live, blob)
            self.assertIn(live, tools)

    def test_validation_record_guidance_uses_the_colon_prefixed_name(self):
        blob = "\n".join(gate_suggestion_strings())
        self.assertIn("validation:api_smoke", blob)
        self.assertIn("validation:ui_flow:", blob)


if __name__ == "__main__":
    unittest.main()
