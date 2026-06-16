"""Regression guard: every tool name referenced in a prompt template,
runtime hint, or workflow-policy gap message MUST exist as a real
registered tool. This is the class of bug the user keeps catching
("``workhub_complete_task`` mentioned, doesn't exist"; "gap message
says call ``workhub_register_ui_page``, no such tool"). One test, one fence.

The scan:
  1. Walk every tool class in ``tools/`` and collect its ``NAME = "..."``.
  2. Walk prompts (``multi_agent/prompts/``) and runtime sources
     (``multi_agent/runtime/``, ``multi_agent/agents/runtime/``,
     ``multi_agent/workflow_policies.py``) for tool-call style refs.
  3. Any reference with a hub-prefix (``registryhub_``, ``workhub_``,
     ``codehub_``, ``eventhub_``, ``runhub_``, ``design_``, ``bug_``,
     ``run_``) that isn't in the registry is a ghost — fail the test
     with the file:line that referenced it.

False positives:
  * Store-file names (``registryhub_endpoints.json``) — handled by requiring
    a ``(`` after the identifier in the source.
  * Jinja macros (``design_system_prompt``) — handled by the explicit
    ``KNOWN_MACROS`` allowlist below.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
TOOLS_DIR = LLM_DIR / "tools"
PROMPTS_DIR = LLM_DIR / "multi_agent" / "prompts"
RUNTIME_DIRS = [
    LLM_DIR / "multi_agent" / "runtime",
    LLM_DIR / "multi_agent" / "agents" / "runtime",
]
RUNTIME_FILES = [
    LLM_DIR / "multi_agent" / "workflow_policies.py",
]

HUB_PREFIXES = (
    "registryhub_", "workhub_", "codehub_", "eventhub_", "runhub_",
    "design_", "bug_", "run_",
)

# Jinja macro names + Python helpers that share the prefix shape but
# aren't tool calls. If you add a new macro/helper with a hub-prefix
# name, add it here.
KNOWN_MACROS: Set[str] = {
    "run_chains",  # chain_executor python fn (validation_runner), not a tool
    "debugger_system_prompt", "debugger_task_prompt",
    "design_system_prompt", "design_task_prompt", "design_specifics",
    "run_get", "run_list", "run_status", "run_start",  # these ARE tools
    "bug_close", "bug_create", "bug_escalate", "bug_list_assigned_to",
    "bug_list_open", "bug_triage", "bug_update_state",  # ARE tools
    "bug_found",  # EventHub event name (looks like a tool ref but it's an event)
    "design_get_status",  # IS a tool
    # Round-7b additions:
    "run_cross_checks",  # internal function in runtime/kickoff/run_kickoff.py — not an agent tool
    "workhub_get_meeting",  # appears only as negative instruction "do NOT poll workhub_get_meeting(...)" in backend/frontend kickoff_response prompts — guarding against an LLM-fabricated tool ref
}

# Method calls on hub objects that look like tool refs but aren't.
# Pattern ``hubs.workhub.update_ui_page`` looks like a tool name but
# it's a service method.
SERVICE_METHOD_PATTERNS = re.compile(
    r"\b(?:hubs?|registry|reg|self|loop|cls|obj|p|proc|asyncio)\.\w+(?:\.\w+)*\("
)
# Any ``self.foo(`` or ``loop.foo(`` style call — these are Python
# method invocations on Python objects, not tool calls.
DOTTED_CALL = re.compile(r"\b\w+\.\w+\s*\(")


def _collect_tool_names() -> Set[str]:
    """Read every ``NAME = "..."`` from tools/*.py."""
    pat = re.compile(r"""^\s*NAME\s*=\s*['"]([a-z_][a-z_0-9]+)['"]""", re.M)
    names: Set[str] = set()
    for py in TOOLS_DIR.rglob("*.py"):
        try:
            text = py.read_text()
        except Exception:
            continue
        names.update(pat.findall(text))
    return names


def _scan_for_refs() -> Dict[str, List[Tuple[Path, int, str]]]:
    """Return {name: [(file, lineno, line_text)]} for any hub-prefixed
    identifier followed by ``(`` in prompts + runtime sources."""
    # Match either `name(` in prose/comments or name( in Python source.
    # The ``\b`` keeps us from matching middle-of-word fragments.
    ref_pat = re.compile(r"\b([a-z_][a-z_0-9]+)\s*\(")
    refs: Dict[str, List[Tuple[Path, int, str]]] = {}
    targets: List[Path] = []
    for p in PROMPTS_DIR.rglob("*.j2"):
        targets.append(p)
    for d in RUNTIME_DIRS:
        for p in d.rglob("*.py"):
            targets.append(p)
    for p in RUNTIME_FILES:
        if p.exists():
            targets.append(p)
    for path in targets:
        try:
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                # Drop comments + docstrings approximately by skipping
                # the prefix up to the first non-comment payload. We
                # still scan them — tool names buried in comments are
                # still operator-facing if they ever surface as hints.
                # But skip lines that LOOK like a Python def to avoid
                # flagging function definitions.
                if line.lstrip().startswith(("def ", "async def ", "class ")):
                    continue
                # Skip any dotted call (``self.foo(``, ``loop.foo(``,
                # ``hubs.workhub.foo(``). These are Python attribute
                # accesses, not tool calls.
                stripped = DOTTED_CALL.sub("", line)
                for name in ref_pat.findall(stripped):
                    if not name.startswith(HUB_PREFIXES):
                        continue
                    if name in KNOWN_MACROS:
                        continue
                    refs.setdefault(name, []).append((path, lineno, line.strip()[:140]))
        except Exception:
            continue
    return refs


class NoGhostToolReferences(unittest.TestCase):
    """Every tool name referenced in a prompt or hint must be a real
    registered tool. Otherwise the agent reads the hint, tries to
    call it, the schema doesn't include it, and the pipeline stalls
    silently (the exact class of bug seen in the live Facebook smoke
    run with ``workhub_complete_task``)."""

    def test_no_ghost_tool_references_in_prompts_or_hints(self):
        real = _collect_tool_names()
        self.assertGreater(len(real), 100,
                            "Tool registry scan returned too few names — "
                            "scan logic broken?")
        refs = _scan_for_refs()
        ghosts: Dict[str, List[Tuple[Path, int, str]]] = {}
        for name, sites in refs.items():
            if name not in real:
                ghosts[name] = sites
        if ghosts:
            lines = ["", "=== Ghost tool-name references found ==="]
            lines.append("These names are referenced as tool calls in "
                          "prompts/runtime sources but are NOT in the "
                          "tool registry. Either fix the reference to "
                          "use a real tool name, or add the name to "
                          "KNOWN_MACROS if it's a known false positive.")
            for name in sorted(ghosts):
                lines.append(f"")
                lines.append(f"  ghost: {name}")
                for path, lineno, txt in ghosts[name][:3]:
                    rel = path.relative_to(ROOT) if path.is_absolute() else path
                    lines.append(f"    at  {rel}:{lineno}")
                    lines.append(f"        {txt}")
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
