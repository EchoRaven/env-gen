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


# Tool-shape strings that legitimately appear in prompts but have no NAME constant.
#
# #1202tt: this set held 38 entries and exactly ONE of them was doing anything. 32 were
# also REGISTERED tool names, and an alias that duplicates a registered name does not
# merely sit there -- it TURNS THIS TEST OFF for that name. `send_message` was in here, so
# if it were renamed or dropped tomorrow every prompt calling it would still pass, which is
# GAP-6 exactly: the orchestrator prompt called workhub_create_task, no such tool existed,
# and it surfaced only after a pilot run had burned ~7 minutes spawning agents. The other 5
# were stale -- `commit`, `complete_step`, `list`, `poll`, `spec files` are referenced by no
# v3 prompt at all, and `complete_step` never even carried the explanation the old header
# demanded of every entry.
#
# So the header's rule ("keep this set MINIMAL ... an unexplained entry becomes 'if I add
# foo to this set, I'm hiding a bug'") was right and unenforced -- the same shape as
# #1202ts's exemption list. `test_no_alias_is_redundant_or_stale_1202tt` below now enforces
# it: an alias must be REFERENCED by a prompt and must NOT be a registered tool name.
_KNOWN_ALIASES = frozenset({
    "sleep",   # a forbidden-verb reference in an `avoid:` entry; no tool of this name exists
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


class KnownAliasesStayMinimal1202TT(unittest.TestCase):
    """#1202tt: the whitelist must not be able to grow back into a place to hide a bug.

    An alias earns its place only by being (a) referenced by some v3 prompt and (b) absent
    from the registered tool names. Anything else is one of the two failures this set had:

      REDUNDANT -- also a registered name, so the alias shadows the registry and the test
                   can no longer notice that tool being renamed or removed;
      STALE     -- no prompt refers to it, so it protects nothing and only adds noise.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.registered = _enumerate_registered_tool_names()
        cls.refs: Set[str] = set()
        for prompt in sorted(PROMPTS_V3.glob("*.j2")):
            text = prompt.read_text(encoding="utf-8", errors="replace")
            cls.refs |= set(_extract_tool_dict_values(text))
            cls.refs |= set(_extract_peer_tool_refs(text))

    def test_the_scan_sees_the_prompts(self) -> None:
        """Non-vacuity: empty refs would make every assertion below trivially true."""
        self.assertGreater(len(self.refs), 50, "prompt tool-ref extraction has drifted")
        self.assertGreater(len(self.registered), 200, "tool NAME enumeration has drifted")

    def test_no_alias_is_redundant(self) -> None:
        redundant = sorted(a for a in _KNOWN_ALIASES if a in self.registered)
        self.assertEqual(
            redundant, [],
            msg=("these aliases are also REGISTERED tool names, so listing them here turns "
                 "this test off for them -- the tool could be renamed or deleted and every "
                 "prompt calling it would still pass (GAP-6's exact shape). Delete them; the "
                 "registry already resolves them: %s" % redundant))

    def test_no_alias_is_stale(self) -> None:
        stale = sorted(a for a in _KNOWN_ALIASES
                       if a not in self.registered and a not in self.refs)
        self.assertEqual(
            stale, [],
            msg=("no v3 prompt references these and they are not tools, so they whitelist "
                 "nothing. An entry that protects nothing is where the next real gap gets "
                 "hidden: %s" % stale))

    def test_deleting_a_real_tool_is_now_caught(self) -> None:
        """★ The consequence, not the mechanism. For a tool that prompts actually call,
        simulate its NAME constant disappearing and check this suite would notice.

        Before #1202tt each of these sat in _KNOWN_ALIASES, so the whitelist answered for
        the registry and the deletion sailed through -- which is the whole failure GAP-6
        cost a pilot run to discover."""
        for victim in ("send_message", "check_inbox", "finish"):
            with self.subTest(tool=victim):
                self.assertIn(victim, self.registered, f"{victim} is no longer a tool")
                self.assertIn(victim, self.refs, f"no v3 prompt calls {victim} any more")
                pruned = (self.registered - {victim}) | _KNOWN_ALIASES
                self.assertTrue(
                    [n for n in self.refs if n not in pruned],
                    f"deleting {victim} would still pass unnoticed — something is "
                    f"answering for the registry again")


if __name__ == "__main__":
    unittest.main()
