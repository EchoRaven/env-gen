"""Static check: every tool name referenced in a v3 agent prompt's
structured ``{"tool": "..."}`` entries must resolve to a real
registered tool NAME.

Origin (2026-06-01 v3 re-pilot debugging chain):
  - GAP-6: orchestrator prompt called workhub_create_plan /
    workhub_create_task / workhub_claim_task / workhub_complete_task —
    none exist; the real tool is workhub_task(action=...)
  - GAP-8: knowledge prompt called workhub_get_block + registryhub_lookup —
    neither exists; the real tools are workhub_get_document +
    registryhub_get_endpoint
  - GAP-13: orchestrator prompt listed retrieve_context as a tool — it's
    a pipeline stage name, not a tool
  - GAP-14: orchestrator prompt listed team_spawn as a tool — it's a
    tool BUNDLE name, not a tool name

All four bugs were caught only after orchestrator startup attempted to
spawn agents and the LLM tried to call the non-existent tools. By that
point the pilot run had already burned ~7 minutes of wall time and the
truncation bug had compounded the failure mode.

This test runs at offline-suite collection time and catches the same
class of bug in zero seconds. Specifically:

1. Authoritative tool-NAME set is built from every ``NAME = "..."``
   declaration under ``tools/`` and ``multi_agent/agents/`` (currently
   ~246 entries).
2. For every v3 prompt under ``multi_agent/prompts/v3/*.j2``, scan
   the structured ``{"tool": "..."}`` dict-value entries. Split on
   ``/`` to handle the ``"name1 / name2"`` group form, strip
   parenthetical commentary like ``"write (spec files)"``.
3. For every extracted name, assert it's either in the registered
   set OR in the explicit ``_KNOWN_ALIASES`` whitelist (covers
   prose-style entries like ``"write"`` that don't have a
   matching NAME constant but ARE real built-in tools).

If a future PR adds a new bundle / renames a tool / drops a tool,
this test surfaces every broken prompt reference at the same instant.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from typing import Iterable, Set

THIS = Path(__file__).resolve()
AGENT_DIR = THIS.parent.parent
TOOLS_DIR = AGENT_DIR / "env_generator" / "llm_generator" / "tools"
AGENTS_DIR = AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "agents"
PROMPTS_V3 = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent" / "prompts" / "v3"
)


# Tool-shape strings that legitimately appear in prompts but have no
# NAME constant — built-in framework tools / aliases / verb-only refs.
# Keep this set MINIMAL and explain each entry: an unexplained entry
# becomes "if I add foo to this set, I'm hiding a bug".
_KNOWN_ALIASES = frozenset({
    # Built-in file-ops surfaced under prosaic names in prompts.
    "write",                 # the framework's write file tool
    "read",                  # the framework's read file tool
    "list",                  # the framework's list-dir tool
    "edit",                  # the framework's edit tool
    "apply_patch",           # registered separately (verified in NAME set)
    "spec files",            # the "(spec files)" parenthetical marker
    # Verb-only short forms for `send_message` / `broadcast` etc that
    # appear sometimes without a hub prefix.
    "send_message",
    "broadcast",
    "ask_agent",
    "check_inbox",
    "subscribe_messages",
    "unsubscribe_messages",
    "publish_message",
    "get_message_status",
    "acknowledge_message",
    "mark_processing",
    "list_agents",
    "get_pending_replies",
    "search_messages",
    "get_important_messages",
    # Lifecycle verbs.
    "finish",                # universal finish tool (registered, but verify)
    "wait",                  # NEVER use, but referenced as forbidden in avoid:
    "sleep",                 # NEVER use
    "poll",                  # NEVER use
    "commit",                # prose-only verb in `{"tool": "write / edit / commit (code)"}`
                             # entries — these list FORBIDDEN file-mutating verbs;
                             # `commit` here means `git commit`, not a tool NAME.
    # Reasoning / planning surface (some are pipeline-stages, some real tools).
    "plan",                  # plan tool (action=create/etc)
    "focus_hub",             # registered tool
    # Visual / image surfaces.
    "view_image",
    "list_reference_images",
    # Knowledge surface.
    "store_knowledge",
    "query_knowledge",
    "submit_learning",
    # Filesystem / repo verbs.
    "execute_bash",
    "lint",
    # Memory bank surface.
    "read_memory_bank",
    "update_memory_bank",
    # Workflow / progress.
    "complete_step",
    # Bug surface.
    "bug_create",
})


def _enumerate_registered_tool_names() -> Set[str]:
    """Build the authoritative tool-name set from every ``NAME = "..."``
    declaration under ``tools/`` and ``multi_agent/agents/``.

    Catches BOTH class-level (``NAME = "x"``) and instance-level
    (``self.NAME = "x"``) forms — the browser-tool subtree uses the
    latter pattern.
    """
    pat_class = re.compile(r'^\s*NAME\s*=\s*"([a-z_][a-z0-9_]+)"', re.MULTILINE)
    pat_inst = re.compile(r'\bself\.NAME\s*=\s*"([a-z_][a-z0-9_]+)"')
    names: Set[str] = set()
    for base in (TOOLS_DIR, AGENTS_DIR):
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except Exception:
                continue
            names.update(pat_class.findall(text))
            names.update(pat_inst.findall(text))
    return names


def _extract_tool_dict_values(prompt_text: str) -> Iterable[str]:
    """Yield each tool-name string from `{"tool": "..."}` dict entries.

    Handles three quirks:
      - `"name1 / name2"` group form → yields each name separately
      - `"name (commentary)"` → strips the parenthetical
      - "(retrieve_context)" or other purely-parenthetical forms → skipped
      - Non-identifier prose like `"broadcast-then-wait"` or
        `"'poll RegistryHub'"` → skipped (those are pattern descriptions
        in the `"tool"` slot, not actual tool names — yielding them
        creates false positives that obscure real bugs)
    """
    pat = re.compile(r'\{\s*"tool"\s*:\s*"([^"]+)"')
    ident_pat = re.compile(r'^[a-z_][a-z0-9_]*$')
    for m in pat.finditer(prompt_text):
        raw = m.group(1).strip()
        # Strip parenthetical / bracket commentary.
        without_parens = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]\s*', '', raw).strip()
        # Split on "/" for group forms.
        for piece in without_parens.split('/'):
            piece = piece.strip()
            if not piece:
                continue
            # Skip prose / pattern descriptions — only yield valid
            # Python identifiers (snake_case lowercase). This filters
            # out things like 'poll RegistryHub', broadcast-then-wait,
            # explicit poll, "tool name with [ANNOTATION]" etc.
            if not ident_pat.match(piece):
                continue
            yield piece


def _extract_peer_tool_refs(prompt_text: str) -> Iterable[str]:
    """Yield identifier-like tool refs from the `peers` / `hubs` blocks
    `tools:` value field (e.g. ``"tools": "registryhub_register_endpoint, registryhub_..."``).

    Filters to valid Python identifiers — skips prose / wildcards like
    `mcp_registry_*` or `(unused)`.
    """
    pat = re.compile(r'"tools"\s*:\s*"([^"]+)"')
    ident_pat = re.compile(r'^[a-z_][a-z0-9_]*$')
    for m in pat.finditer(prompt_text):
        for piece in m.group(1).split(','):
            piece = piece.strip()
            # Strip parenthetical / bracket commentary.
            piece = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]\s*', '', piece).strip()
            if not piece:
                continue
            if not ident_pat.match(piece):
                continue
            yield piece


class RegisteredToolNameSetIsNonEmpty(unittest.TestCase):
    """Sanity: the NAME enumeration finds the expected ~246+ tools."""

    def test_registered_tool_names_at_least_200(self) -> None:
        names = _enumerate_registered_tool_names()
        self.assertGreaterEqual(
            len(names), 200,
            msg=f"only enumerated {len(names)} tool NAMEs; expected >=200. "
                f"NAME enumeration regex may have drifted.",
        )

    def test_known_high_value_tools_present(self) -> None:
        """Sanity-check a few well-known tools to confirm the enumeration works."""
        names = _enumerate_registered_tool_names()
        for required in [
            "registryhub_register_endpoint", "registryhub_register_table",
            "workhub_task", "workhub_create_document",
            "design_get_status", "check_inbox",
        ]:
            self.assertIn(required, names,
                          msg=f"expected {required!r} in registered NAMEs")


class V3PromptsReferenceRealTools(unittest.TestCase):
    """Every tool name in a v3 prompt's `{"tool": "..."}` dict entries
    must resolve to a real registered tool NAME (or be an explicit
    _KNOWN_ALIASES whitelist entry)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registered = _enumerate_registered_tool_names()
        cls.allowed = cls.registered | _KNOWN_ALIASES
        cls.prompts = sorted(PROMPTS_V3.glob("*.j2"))
        if not cls.prompts:
            raise AssertionError(f"no v3 prompts found under {PROMPTS_V3}")

    def test_every_tool_dict_entry_resolves(self) -> None:
        """Scan each v3 prompt's `{"tool": "..."}` entries — every name
        must be in the registered set or _KNOWN_ALIASES."""
        unknown: dict = {}
        for prompt in self.prompts:
            text = prompt.read_text(encoding="utf-8")
            for name in _extract_tool_dict_values(text):
                if name not in self.allowed:
                    unknown.setdefault(prompt.name, []).append(name)
        self.assertEqual(
            unknown, {},
            msg=(
                f"v3 prompts reference {sum(len(v) for v in unknown.values())} "
                f"tool name(s) that are NOT registered AND NOT in "
                f"_KNOWN_ALIASES:\n"
                + "\n".join(
                    f"  {fname}: {sorted(set(names))}"
                    for fname, names in sorted(unknown.items())
                )
                + "\n\nFix either: (a) the prompt's tool name to match a "
                "registered NAME, OR (b) register the tool in tools/*.py "
                "and add to TOOL_BUNDLE_REGISTRY, OR (c) if it's a "
                "framework-built-in without a NAME constant, add it to "
                "_KNOWN_ALIASES in this file with a brief comment."
            ),
        )

    def test_every_hub_block_tools_field_resolves(self) -> None:
        """The peers / hubs blocks have a `"tools": "name1, name2, ..."`
        field. Scan those too — same registered/whitelist rule."""
        unknown: dict = {}
        for prompt in self.prompts:
            text = prompt.read_text(encoding="utf-8")
            for name in _extract_peer_tool_refs(text):
                # The `tools` field uses comma-separated tool names; an
                # entry like "(unused)" means "no tools" — skip.
                if name == "(unused)" or not name:
                    continue
                if name not in self.allowed:
                    unknown.setdefault(prompt.name, []).append(name)
        self.assertEqual(
            unknown, {},
            msg=(
                f"v3 prompts' hub/peer `tools` fields reference "
                f"{sum(len(v) for v in unknown.values())} tool name(s) "
                f"that are NOT registered AND NOT in _KNOWN_ALIASES:\n"
                + "\n".join(
                    f"  {fname}: {sorted(set(names))}"
                    for fname, names in sorted(unknown.items())
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()
