"""Roster-consistency invariant — closed-by-construction.

Every reference to an agent id in load-bearing code (runtime hub gate
literals, prompt routing, tool default identities, named constants
holding allowlists) MUST resolve to either a live resident lane in
``agents_config.yaml`` or a documented spawn identity.

Original scope (gates + attendees + subscriptions) caught the hub
layer in the 2026-06-02 review, but the SAME class of bug then
re-surfaced in prompts and tool descriptions because those layers
were excluded. v2 of this invariant scans:

* runtime hubs: ``allowed_set={...}`` literals + named-constant
  allowlists (``allowed_set=_FOO_ALLOWED`` resolved via simple
  AST-free reach), ``attendees=[...]`` defaults, ``runtime_name="..."``.
* prompts: ``notify=[...]`` finish-kwarg lists, ``to_agent="..."``
  send_message targets, ``assignee="..."`` task assignments, ``{"id":
  "<agent>"`` peer entries in the v3 peers table.
* tools: ``getattr(self, "_agent_id", None) or "<agent>"`` phantom
  defaults — caller must inject the agent identity, not the tool.

If a roster reduction (or rename) lands without propagating to one
of these layers, this test fires — before the prompt routes the LLM
to a dead lane and the run stalls waiting for a phantom response.

History:
* 2026-06-02 review #1: caught hub-layer gate residue
  (architect_reviewer / visual_reviewer / database in allowed_set).
  v1 invariant landed; passed; the review's #2 caught that v1 missed
  prompts + tools — the same bug shape was still live one layer up.
* This file is v2: prompts + tools + named-constant resolution.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import yaml

_THIS = Path(__file__).resolve()
_AGENT_ROOT = _THIS.parent.parent
sys.path.insert(0, str(_AGENT_ROOT / "env_generator" / "llm_generator"))

CONFIG_YAML = (
    _AGENT_ROOT
    / "env_generator"
    / "llm_generator"
    / "multi_agent"
    / "agents"
    / "agents_config.yaml"
)
LLM_DIR = _AGENT_ROOT / "env_generator" / "llm_generator"
RUNTIME_DIR = LLM_DIR / "multi_agent" / "runtime"
PROMPTS_DIR = LLM_DIR / "multi_agent" / "prompts" / "v3"
TOOLS_DIR = LLM_DIR / "tools"


def _live_resident_lanes() -> set[str]:
    """The set of agent ids registered as resident lanes in YAML."""
    cfg = yaml.safe_load(CONFIG_YAML.read_text())
    return set((cfg.get("resident_lanes") or {}).keys())


def _live_profiles() -> set[str]:
    """All profiles in YAML (incl. ephemeral workers like database_worker)."""
    cfg = yaml.safe_load(CONFIG_YAML.read_text())
    return set((cfg.get("profiles") or {}).keys())


def _spawn_identities() -> set[str]:
    """Spawn-type identities a profile may legitimately claim at
    runtime when spawned via ``define_team_agent`` — they aren't
    resident lanes but ARE valid gate principals.

    Round-4 (reviewer NEW residue #3 / status #5): the original
    hardcoded ``{"database_worker"}`` could rot. The set is now
    derived from ``agents_config.yaml`` as ``profiles - resident_lanes``
    (the ephemeral worker profiles) PLUS any explicit spawn-only
    aliases documented in the YAML. Keeps in sync with roster changes.
    """
    cfg = yaml.safe_load(CONFIG_YAML.read_text())
    profiles = set((cfg.get("profiles") or {}).keys())
    resident = set((cfg.get("resident_lanes") or {}).keys())
    ephemeral = profiles - resident
    # database_worker is a spawn ALIAS — backend spawns the database
    # profile and the spawn identifies as 'database_worker' in gate
    # calls. agents_config.yaml has no separate profile for this name
    # (it's the database profile rebadged at spawn time per the
    # schema_hub gate's allowed_set). Pin explicitly until a YAML
    # 'spawn_aliases' section is added.
    spawn_aliases = {"database_worker"}
    return ephemeral | spawn_aliases


def _known_runtimes() -> set[str]:
    """Runtime / service identities that aren't agents but ARE valid
    gate principals (e.g. 'runhub' authoring probe records). Derived
    entirely from the runtime/ directory layout — adding/renaming a hub
    folder updates this set automatically.

    Round-4 (reviewer NEW residue #3): no more hardcoded literal
    supplement; everything comes from disk.
    """
    out: set[str] = set()
    hubs_dir = RUNTIME_DIR / "hubs"
    if hubs_dir.is_dir():
        out.update(
            p.name for p in hubs_dir.iterdir()
            if p.is_dir() and (p / "service.py").exists()
        )
    # Runtime hubs that live as top-level files in runtime/ (not under
    # hubs/). Discriminate by checking the file actually contains a
    # ``class XxxHub`` or ``class XxxRegistry`` definition — derived,
    # not hardcoded.
    hub_class_re = re.compile(
        r'^class\s+([A-Z][A-Za-z]*?(?:Hub|Registry))\b', re.MULTILINE
    )
    for py in RUNTIME_DIR.glob("*.py"):
        if py.stem.startswith("_"):
            continue
        try:
            src = py.read_text()
        except UnicodeDecodeError:
            continue
        if hub_class_re.search(src):
            out.add(py.stem)
    return out


# ============================================================================
# Scope helpers
# ============================================================================

def _hub_source_files() -> list[Path]:
    """All runtime/* and runtime/hubs/*/service.py."""
    out: list[Path] = []
    out.extend(sorted(RUNTIME_DIR.glob("*.py")))
    out.extend(sorted(RUNTIME_DIR.glob("hubs/*/service.py")))
    return out


def _prompt_files() -> list[Path]:
    """All v3/*.j2 prompt templates + shared macro files + any other
    template directories that v3 templates ``{% from %}``-import from.

    Round-4 expansion (per reviewer round-3 NEW residue #2): the scanner
    previously globbed only ``v3/*.j2``, missing ``agents/shared/*.j2``
    macros that all v3 prompts import — any routing literal authored
    inside a shared macro was unguarded. The Jinja-import follower
    (regex-based, not real parser) handles the general case so a future
    cross-directory macro added under any prompt subdirectory gets
    picked up automatically.

    Round-5 historical note: v2/orchestrator_agent.j2 used to be imported
    by v3/orchestrator. It was inlined + the v2/ directory deleted in
    round 4. The follower below still survives any future re-introduction
    of cross-directory imports.
    """
    PROMPTS_ROOT = PROMPTS_DIR.parent
    out: list[Path] = []
    out.extend(sorted(p for p in PROMPTS_DIR.glob("*.j2") if p.is_file()))
    # shared/ macros (single dir today; expand to rglob if more added)
    shared = PROMPTS_ROOT / "agents" / "shared"
    if shared.is_dir():
        out.extend(sorted(p for p in shared.glob("*.j2") if p.is_file()))
    # Any v2/ file v3 imports from. Resolve via {% from "<path>" %} scan.
    from_re = re.compile(r'{%\s*from\s+["\']([^"\']+\.j2)["\']')
    imported: set[Path] = set()
    for v3 in out:
        try:
            for m in from_re.finditer(v3.read_text()):
                rel = m.group(1)
                if rel.startswith("v2/") or rel.startswith("agents/"):
                    p = (PROMPTS_ROOT / rel).resolve()
                    if p.exists() and p not in out:
                        imported.add(p)
        except UnicodeDecodeError:
            continue
    out.extend(sorted(imported))
    return out


def _tool_files() -> list[Path]:
    """All tools/*.py and tools/*/*.py."""
    return sorted(TOOLS_DIR.rglob("*.py"))


# ============================================================================
# Literal extractors
# ============================================================================

def _extract_set_literals(source: str, key: str) -> list[tuple[int, list[str]]]:
    """Pull every ``<key>={"a","b",...}`` literal."""
    pattern = re.compile(
        rf'\b{re.escape(key)}\s*=\s*\{{\s*([^{{}}]*?)\s*\}}', re.DOTALL,
    )
    out: list[tuple[int, list[str]]] = []
    for m in pattern.finditer(source):
        body = m.group(1)
        if ":" in body and not re.search(r'["\']\s*,\s*["\']', body):
            continue  # dict literal, not a string set
        items = re.findall(r'["\']([a-z_][a-z_0-9]*)["\']', body)
        if items:
            line = source[: m.start()].count("\n") + 1
            out.append((line, items))
    return out


def _extract_list_literals(source: str, key: str) -> list[tuple[int, list[str]]]:
    """Pull every ``<key>=["a","b",...]`` literal. Captures multi-line lists."""
    pattern = re.compile(
        rf'\b{re.escape(key)}\s*=\s*\[\s*([^\[\]]*?)\s*\]', re.DOTALL,
    )
    out: list[tuple[int, list[str]]] = []
    for m in pattern.finditer(source):
        items = re.findall(r'["\']([a-z_][a-z_0-9]*)["\']', m.group(1))
        if items:
            line = source[: m.start()].count("\n") + 1
            out.append((line, items))
    return out


def _extract_kwarg_strings(source: str, key: str) -> list[tuple[int, str]]:
    """Pull every ``<key>="literal_string"`` kwarg."""
    pattern = re.compile(rf'\b{re.escape(key)}\s*=\s*["\']([a-z_][a-z_0-9]*)["\']')
    out: list[tuple[int, str]] = []
    for m in pattern.finditer(source):
        line = source[: m.start()].count("\n") + 1
        out.append((line, m.group(1)))
    return out


def _resolve_named_constants(source: str) -> dict[str, list[str]]:
    """For ``X = frozenset({...})`` / ``X = {...}`` definitions at module
    scope, return X → [items]. Lets the allowed_set scanner follow names
    like ``allowed_set=_REGISTER_STORY_ALLOWED``."""
    out: dict[str, list[str]] = {}
    pattern = re.compile(
        r'^(_?[A-Z][A-Z_0-9]*)\s*=\s*(?:frozenset)?\s*\(?\s*\{\s*([^{}]*?)\s*\}\s*\)?',
        re.MULTILINE | re.DOTALL,
    )
    for m in pattern.finditer(source):
        body = m.group(2)
        if ":" in body and not re.search(r'["\']\s*,\s*["\']', body):
            continue
        items = re.findall(r'["\']([a-z_][a-z_0-9]*)["\']', body)
        if items:
            out[m.group(1)] = items
    return out


# Round-5 (reviewer REFUTED #2): the round-4 split between
# _extract_set_literals (only matches `{` immediately after `=`) and
# _extract_allowed_set_names (only matches UPPERCASE names) left a
# silent-skip hole — `allowed_set=frozenset({...})`,
# `allowed_set=set([...])`, and `allowed_set=lowercase_var` all evaded
# both. Today no live code uses those shapes, but the class wasn't
# closed. This unified enumerator returns EVERY `allowed_set=` site
# with its classification; unclassifiable RHS is FAIL-LOUD by design.
def _enumerate_allowed_set_sites(source: str) -> list[tuple[int, str, str, list[str] | None]]:
    """For every ``allowed_set=<rhs>`` in source, return
    ``(line, raw_rhs_excerpt, classification, resolved_items_or_None)``.

    Classifications:
      - "brace_literal"     : ``{"a", "b", ...}`` directly after =
      - "frozenset_literal" : ``frozenset({"a", "b", ...})`` or
                              ``frozenset(["a","b",...])`` directly after =
      - "set_literal"       : ``set(["a","b",...])`` directly after =
      - "uppercase_const"   : ``_FOO_ALLOWED`` style name (resolved via pool by caller)
      - "lowercase_var"     : lowercase identifier — UNCLASSIFIABLE (fail-loud)
      - "unclassifiable"    : something else (fail-loud)
    Items list is ``None`` for uppercase_const (caller resolves) and
    fail-loud categories.
    """
    # Capture the RHS up to the line terminator OR comma at depth 0.
    # We use a simple bracket-balanced scan so frozenset({...}) reads
    # all its parens cleanly.
    pat = re.compile(r'\ballowed_set\s*=\s*')
    out: list[tuple[int, str, str, list[str] | None]] = []
    for m in pat.finditer(source):
        start = m.end()
        line = source[: m.start()].count("\n") + 1
        # Scan forward, tracking bracket depth, stopping at a comma/
        # newline at depth 0.
        i = start
        depth = 0
        n = len(source)
        while i < n:
            c = source[i]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and c in ",\n":
                break
            i += 1
        rhs = source[start:i].strip()
        # Classify.
        if rhs.startswith("{"):
            items = re.findall(r'["\']([a-z_][a-z_0-9]*)["\']', rhs)
            out.append((line, rhs[:80], "brace_literal", items))
        elif rhs.startswith("frozenset("):
            items = re.findall(r'["\']([a-z_][a-z_0-9]*)["\']', rhs)
            out.append((line, rhs[:80], "frozenset_literal", items))
        elif rhs.startswith("set(") and not rhs.startswith("set()"):
            items = re.findall(r'["\']([a-z_][a-z_0-9]*)["\']', rhs)
            out.append((line, rhs[:80], "set_literal", items))
        elif re.match(r"_?[A-Z][A-Z_0-9]*$", rhs):
            out.append((line, rhs[:80], "uppercase_const", None))
        elif re.match(r"_?[a-z][a-z_0-9]*$", rhs):
            out.append((line, rhs[:80], "lowercase_var", None))
        else:
            out.append((line, rhs[:80], "unclassifiable", None))
    return out


def _extract_allowed_set_names(source: str) -> list[tuple[int, str]]:
    """Pull every ``allowed_set=<NAMED_CONSTANT>`` reference (uppercase
    name only — kept for backward compatibility with the legacy
    `test_every_allowed_set_named_constant_references_live_agents`
    test. The round-5 unified enumerator
    `_enumerate_allowed_set_sites` is the source of truth for
    coverage; this is a narrow projection of it."""
    return [
        (line, rhs)
        for (line, rhs, kind, _items) in _enumerate_allowed_set_sites(source)
        if kind == "uppercase_const"
    ]


# ============================================================================
# Test classes
# ============================================================================

class GateAllowlistsReferenceLiveAgents(unittest.TestCase):
    """Hub gates: allowed_set literals + named constants + attendees."""

    def setUp(self) -> None:
        self.live = _live_resident_lanes() | _spawn_identities()

    def test_every_allowed_set_literal_references_live_agents(self) -> None:
        violations: list[str] = []
        for path in _hub_source_files():
            src = path.read_text()
            for line, ids in _extract_set_literals(src, "allowed_set"):
                dead = [i for i in ids if i not in self.live]
                if dead:
                    rel = path.relative_to(_AGENT_ROOT)
                    violations.append(
                        f"  {rel}:{line} allowed_set literal references dead id(s) {dead}"
                    )
        if violations:
            self.fail(
                f"Gate allowed_set literals reference dead agents. Live: "
                f"{sorted(self.live)}\n\n" + "\n".join(violations)
            )

    def test_every_allowed_set_named_constant_references_live_agents(self) -> None:
        """``allowed_set=_REGISTER_STORY_ALLOWED`` style — resolve the
        constant and assert its members are all live.

        Round-4 (reviewer NEW residue #4 / status #4): the previous
        version SILENTLY passed when the constant couldn't be resolved
        (union expressions, ``set([...])``, cross-module imports). That
        is the same "假绿" pattern that bit the round-2 invariant.
        Round-4 hardens this: a referenced constant that isn't resolved
        in the source file AND isn't found as a cross-module re-export
        FAILS the test with an explicit "unresolved" message. Resolver
        coverage stays narrow on purpose — the failure forces the
        author to either inline the literal or extend the resolver.
        """
        violations: list[str] = []
        unresolved: list[str] = []
        # Build a cross-module pool: every hub file's named constants.
        # Lets `allowed_set=_FOO_ALLOWED` defined in module A and
        # imported into module B both resolve.
        pool: dict[str, list[str]] = {}
        for path in _hub_source_files():
            src = path.read_text()
            for k, v in _resolve_named_constants(src).items():
                pool.setdefault(k, v)
        for path in _hub_source_files():
            src = path.read_text()
            for line, name in _extract_allowed_set_names(src):
                if name not in pool:
                    rel = path.relative_to(_AGENT_ROOT)
                    unresolved.append(
                        f"  {rel}:{line} allowed_set={name} — constant "
                        f"not resolvable as a plain string-set at module "
                        f"scope anywhere in runtime/. Either (a) make it "
                        f"a flat ``X = frozenset({{...}})`` / ``X = {{...}}``, "
                        f"or (b) extend _resolve_named_constants to "
                        f"handle the construct, or (c) inline the literal."
                    )
                    continue
                dead = [i for i in pool[name] if i not in self.live]
                if dead:
                    rel = path.relative_to(_AGENT_ROOT)
                    violations.append(
                        f"  {rel}:{line} allowed_set={name} resolves to "
                        f"{pool[name]}, dead members: {dead}"
                    )
        msgs = []
        if violations:
            msgs.append(
                f"Gate allowed_set named constants reference dead agents. "
                f"Live: {sorted(self.live)}\n" + "\n".join(violations)
            )
        if unresolved:
            msgs.append(
                "Unresolved named-constant references (fail-loud to "
                "prevent silent coverage gaps):\n" + "\n".join(unresolved)
            )
        if msgs:
            self.fail("\n\n".join(msgs))

    def test_unified_allowed_set_classifier_covers_all_shapes(self) -> None:
        """Round-5 (reviewer REFUTED #2): unified scanner across every
        ``allowed_set=`` RHS — classify each, fail-loud on shapes the
        scanner doesn't know. Catches the silent-skip class:

        * ``allowed_set=frozenset({...})`` and ``frozenset([...])`` inline
        * ``allowed_set=set([...])`` inline
        * ``allowed_set=lowercase_var`` (Python style says module
          constants are UPPER but a regression could land lowercase)
        * Any expression that isn't a literal / known name shape

        Today (round 5) every live site is brace_literal or
        uppercase_const — both ARE covered by the round-4 tests above.
        This unified test is the round-5 belt-and-suspenders: if a
        future PR introduces a frozenset-inline / set-literal /
        lowercase-var site that contains a dead agent, the scanner
        now red-fires instead of silently passing.
        """
        # Build the cross-module constant pool (same as the named-const test).
        pool: dict[str, list[str]] = {}
        for path in _hub_source_files():
            src = path.read_text()
            for k, v in _resolve_named_constants(src).items():
                pool.setdefault(k, v)

        violations: list[str] = []
        unclassifiable: list[str] = []
        for path in _hub_source_files():
            src = path.read_text()
            rel = path.relative_to(_AGENT_ROOT)
            for line, rhs, kind, items in _enumerate_allowed_set_sites(src):
                if kind in ("brace_literal", "frozenset_literal", "set_literal"):
                    dead = [i for i in (items or []) if i not in self.live]
                    if dead:
                        violations.append(
                            f"  {rel}:{line} ({kind}) allowed_set={rhs} "
                            f"contains dead id(s) {dead}"
                        )
                elif kind == "uppercase_const":
                    name = rhs
                    if name in pool:
                        dead = [i for i in pool[name] if i not in self.live]
                        if dead:
                            violations.append(
                                f"  {rel}:{line} allowed_set={name} resolves "
                                f"to {pool[name]}, dead members: {dead}"
                            )
                    # else: uppercase but unresolved → handled by the
                    # legacy fail-loud test above
                elif kind in ("lowercase_var", "unclassifiable"):
                    unclassifiable.append(
                        f"  {rel}:{line} ({kind}) allowed_set={rhs} — "
                        f"scanner cannot classify this RHS shape. "
                        f"Either (a) inline a brace literal, "
                        f"(b) move to an UPPERCASE module constant, or "
                        f"(c) extend _enumerate_allowed_set_sites to "
                        f"handle the new shape with a self-check probe."
                    )

        msgs = []
        if violations:
            msgs.append(
                "Gate allowed_set sites (all shapes) reference dead "
                f"agents. Live: {sorted(self.live)}\n" + "\n".join(violations)
            )
        if unclassifiable:
            msgs.append(
                "Unclassifiable allowed_set RHS shapes (fail-loud to "
                "close the round-3 silent-skip class):\n"
                + "\n".join(unclassifiable)
            )
        if msgs:
            self.fail("\n\n".join(msgs))

    def test_unified_classifier_via_probe(self) -> None:
        """Locks the round-5 classifier against future regression. A
        synthetic source containing each of the 5 RHS shapes must
        classify correctly — if a regex regression breaks one of them,
        this test surfaces it before a real dead reference does."""
        probe = """
allowed_set={"a", "b"}
allowed_set=frozenset({"c", "d"})
allowed_set=frozenset(["e", "f"])
allowed_set=set(["g", "h"])
allowed_set=_UPPER_CONST
allowed_set=lower_var
allowed_set=foo.bar(baz)
"""
        sites = _enumerate_allowed_set_sites(probe)
        kinds = [k for _l, _r, k, _i in sites]
        self.assertEqual(
            kinds,
            [
                "brace_literal",
                "frozenset_literal",
                "frozenset_literal",
                "set_literal",
                "uppercase_const",
                "lowercase_var",
                "unclassifiable",
            ],
            f"classifier regression — got {kinds}",
        )
        # Spot-check item extraction on the literal forms.
        items_by_kind = {k: i for _l, _r, k, i in sites if i is not None}
        self.assertEqual(items_by_kind["brace_literal"], ["a", "b"])
        self.assertEqual(items_by_kind["frozenset_literal"], ["e", "f"])
        self.assertEqual(items_by_kind["set_literal"], ["g", "h"])

    def test_every_runtime_actor_references_live_agent(self) -> None:
        admissible = self.live | _known_runtimes()
        violations: list[str] = []
        for path in _hub_source_files():
            src = path.read_text()
            for line, name in _extract_kwarg_strings(src, "runtime_name"):
                if name not in admissible:
                    rel = path.relative_to(_AGENT_ROOT)
                    violations.append(
                        f"  {rel}:{line} runtime_name={name!r} not in live agents "
                        f"or known runtimes"
                    )
        if violations:
            self.fail(
                "require_runtime_actor calls reference unknown runtime:\n\n"
                + "\n".join(violations)
            )

    def test_no_dead_attendees_in_gate_creators(self) -> None:
        violations: list[str] = []
        for path in _hub_source_files():
            src = path.read_text()
            for line, ids in _extract_list_literals(src, "attendees"):
                dead = [i for i in ids if i not in self.live]
                if dead:
                    rel = path.relative_to(_AGENT_ROOT)
                    violations.append(
                        f"  {rel}:{line} attendees={ids} contains dead id(s) {dead}"
                    )
        if violations:
            self.fail(
                "Attendee defaults reference removed agents:\n\n"
                + "\n".join(violations)
            )


class PromptRoutingReferencesLiveAgents(unittest.TestCase):
    """v3 prompt templates: notify lists + send_message targets + task
    assignees + peers entries must all reference live agents.

    SCOPE CAVEATS (documented for round-4 NEW residue #4, intentional):
    * Only LITERAL routing tokens are validated. A variable-routed
      target like ``notify=[<parent_id>]`` or ``to_agent=<var>`` (e.g.
      analysis_worker_agent.j2's runtime-substituted parent_id) yields
      no string literal — the scanner cannot validate it because the
      target is resolved at spawn time, not at render time. If a future
      regression introduces ``notify=[some_dead_var]`` where ``some_dead_var``
      resolves to a removed lane, this scanner will NOT catch it.
      Mitigation: keep the variable name explicit in the prompt and
      ensure the spawn-time substitution comes from the live roster.
    * Round-4 widens the notify-bracket char cap and adds an explicit
      check for nested brackets, which used to silently abort a match.
    """

    # Documented runtime-substituted placeholders used in ephemeral
    # worker prompts (analysis_worker / review_worker / worker). At spawn
    # time the agent_spawn_service rewrites these into the actual parent
    # agent_id. They are NOT phantoms; document and allowlist them.
    _TEMPLATE_PLACEHOLDERS = {
        "parent",                  # the dynamic spawn parent (orchestrator / lead / etc.)
        "parent_id",               # same as parent — used in finish(notify=[...])
        "peer_workers",            # other workers spawned in the same fan-out
        "other_review_workers",    # peers of a review_worker in a multi-reviewer round
    }

    def setUp(self) -> None:
        self.live = _live_resident_lanes() | _spawn_identities()
        # Allow ``human_user`` (a legitimate target in narratives) +
        # documented spawn-parent template placeholders.
        self.allow_extra = {"human_user"} | self._TEMPLATE_PLACEHOLDERS

    def _admissible(self) -> set[str]:
        return self.live | self.allow_extra

    def test_finish_notify_lists_reference_live_agents(self) -> None:
        """``finish(notify=['a','b',...])`` in v3 prompts.

        Round-4 fix (reviewer NEW residue #1): the previous pattern
        ``notify=[([^\\[\\]]{0,400})]`` had two silent blind spots:
        (a) the 400-char cap silently skipped longer notify lists,
            (b) nested brackets ``notify=[[...]]`` aborted the match.
        The fix uses a balanced match (single-bracket nesting acceptable
        by greedy widening) and a probe-test that locks the behavior so
        a future regression of the regex itself fires immediately.
        """
        violations: list[str] = []
        # Balanced-ish match: notify=[ <inner> ] where <inner> may
        # contain ONE level of nested brackets (rare in current prompts
        # but the round-3 review flagged the risk). Outer bracket pair
        # is captured greedily over up to 4000 chars (10x the old cap;
        # generous safety margin — the longest current notify is ~120
        # chars). If a prompt ever needs more than 4000 chars of notify
        # content something else has already gone wrong.
        pattern = re.compile(
            r"notify\s*=\s*\[((?:[^\[\]]|\[[^\[\]]*\]){0,4000})\]",
            re.DOTALL,
        )
        for path in _prompt_files():
            src = path.read_text()
            for m in pattern.finditer(src):
                items = re.findall(r"['\"]([a-z_][a-z_0-9]*)['\"]", m.group(1))
                dead = [i for i in items if i not in self._admissible()]
                if dead:
                    line = src[: m.start()].count("\n") + 1
                    rel = path.relative_to(_AGENT_ROOT)
                    violations.append(
                        f"  {rel}:{line} notify={items} contains dead id(s) {dead}"
                    )
        if violations:
            self.fail(
                f"v3 prompts route finish(notify=...) to dead agents. Live: "
                f"{sorted(self._admissible())}\n\n" + "\n".join(violations)
            )

    def test_notify_scanner_handles_long_and_nested_via_probe(self) -> None:
        """Probe-self-check: scanner must catch dead agents inside (a) a
        long notify list and (b) a nested-bracket notify. Locks
        round-4's bracket-balance + cap-widening fixes."""
        live = self._admissible()
        # (a) Long list — 600 chars of literal-spaced filler agent ids
        # all live, then a dead one at the end. Must be detected.
        long_inner = ", ".join([f"'orchestrator'"] * 30 + ["'dead_phantom'"])
        probe_long = f"notify=[{long_inner}]"
        # (b) Nested — notify=[['orchestrator', 'dead_phantom']]
        probe_nested = "notify=[['orchestrator', 'dead_phantom']]"
        pat = re.compile(
            r"notify\s*=\s*\[((?:[^\[\]]|\[[^\[\]]*\]){0,4000})\]",
            re.DOTALL,
        )
        for label, src in (("long", probe_long), ("nested", probe_nested)):
            hits = list(pat.finditer(src))
            self.assertGreaterEqual(
                len(hits), 1,
                f"scanner failed to match the {label}-form notify list",
            )
            items = re.findall(r"['\"]([a-z_][a-z_0-9]*)['\"]", hits[0].group(1))
            dead = [i for i in items if i not in live]
            self.assertIn(
                "dead_phantom", dead,
                f"scanner matched the {label} form but didn't surface "
                f"the dead_phantom inside",
            )

    def test_send_message_to_agent_targets_live(self) -> None:
        """``send_message(to_agent='<x>', ...)`` in v3 prompts."""
        violations: list[str] = []
        pattern = re.compile(r"to_agent\s*=\s*['\"]([a-z_][a-z_0-9]*)['\"]")
        for path in _prompt_files():
            src = path.read_text()
            for m in pattern.finditer(src):
                tgt = m.group(1)
                if tgt not in self._admissible():
                    line = src[: m.start()].count("\n") + 1
                    rel = path.relative_to(_AGENT_ROOT)
                    violations.append(
                        f"  {rel}:{line} send_message(to_agent={tgt!r}) — dead"
                    )
        if violations:
            self.fail(
                f"v3 prompts dispatch send_message to dead agents. Live: "
                f"{sorted(self._admissible())}\n\n" + "\n".join(violations)
            )

    def test_task_assignees_live(self) -> None:
        """``workhub_task(..., assignee='<x>', ...)`` in v3 prompts."""
        violations: list[str] = []
        pattern = re.compile(r"assignee\s*=\s*['\"]([a-z_][a-z_0-9]*)['\"]")
        for path in _prompt_files():
            src = path.read_text()
            for m in pattern.finditer(src):
                tgt = m.group(1)
                if tgt not in self._admissible():
                    line = src[: m.start()].count("\n") + 1
                    rel = path.relative_to(_AGENT_ROOT)
                    violations.append(
                        f"  {rel}:{line} assignee={tgt!r} — dead"
                    )
        if violations:
            self.fail(
                f"v3 prompts assign tasks to dead agents. Live: "
                f"{sorted(self._admissible())}\n\n" + "\n".join(violations)
            )

    def test_peer_entries_reference_live_agents(self) -> None:
        """``{"id": "<agent>", "role": "..."`` peer entries in
        agent_prompt_v3 ``peers=[...]`` tables.

        Round-4 tightening: the previous regex matched any
        ``{"id": "..."`` literal, which false-positive'd on stage-id
        examples in `plan(stages=[{"id": "requirements", ...}])`
        prose. The peers convention is co-occurrence of ``"role":``;
        require it to scope the match.
        """
        violations: list[str] = []
        # Peer entry pattern: ``{"id": "<x>", ... "role": ...}`` —
        # within ~600 chars of the id, demand a ``"role"`` key. Stage
        # examples use ``"name"`` + ``"description"`` instead.
        pattern = re.compile(
            r'\{\s*"id"\s*:\s*"([a-z_][a-z_0-9]*)"[^}]{0,600}?"role"\s*:',
            re.DOTALL,
        )
        for path in _prompt_files():
            src = path.read_text()
            for m in pattern.finditer(src):
                ident = m.group(1)
                # `runhub` is a runtime, not an agent — allow it as a
                # peer entry (peers tables also list hubs/services for
                # narrative context).
                if ident not in self._admissible() and ident not in _known_runtimes():
                    line = src[: m.start()].count("\n") + 1
                    rel = path.relative_to(_AGENT_ROOT)
                    violations.append(
                        f"  {rel}:{line} peers entry id={ident!r} — dead"
                    )
        if violations:
            self.fail(
                f"v3 prompts list dead agents as peers. Live: "
                f"{sorted(self._admissible() | _known_runtimes())}\n\n"
                + "\n".join(violations)
            )


class ToolDefaultsAvoidPhantomActors(unittest.TestCase):
    """Tools must NOT default ``_agent_id`` to a hard-coded actor name.
    Per cleanup discipline (2026-06-02), caller injects the identity;
    tool gets ``""`` and the gate handles the empty-actor fallthrough.

    Round-4 (review 2026-06-02): the original PATTERN matched only the
    `getattr(self, "_agent_id", None) or "x"` form. Reviewer's probe
    proved this scanner was 0-hit across 64 tool files because the
    DOMINANT live form is the bare-attribute `self._agent_id or "x"`.
    Round-4 adds BARE_PATTERN + an explicit empirical probe sub-test
    that injects a synthetic phantom and asserts the scanner red-fires —
    so a future regression of the regex itself surfaces immediately.
    """

    # Form 1: getattr(self, "_agent_id", None) or "<phantom>"
    GETATTR_PATTERN = re.compile(
        r'getattr\s*\(\s*self\s*,\s*["\']_agent_id["\']\s*,'
        r'\s*(?:None|""|\'\')?\s*\)\s*or\s*["\']([a-z_][a-z_0-9]*)["\']'
    )

    # Form 2: bare attribute — `self._agent_id or "<phantom>"`. This is
    # the dominant form in the live codebase per the round-3 review
    # probe. Match BOTH the simple lhs (`self._agent_id`) and a
    # `(... self._agent_id)` parenthesized expression terminating with
    # the attribute, both followed by `or "literal"`.
    BARE_PATTERN = re.compile(
        r'self\._agent_id\s*or\s*["\']([a-z_][a-z_0-9]*)["\']'
    )

    # Phantom-sentinel literals worth flagging even though they aren't
    # agent ids — per cleanup discipline #1 ("drop legacy defaults that
    # point to phantom IDs"), strings like "unknown" / "system" used as
    # fallback identity are the same code smell.
    _ALSO_PHANTOM_SENTINELS = frozenset({"unknown", "system", "anonymous"})

    def _scan(self, src: str, path: Path) -> list[str]:
        violations: list[str] = []
        for pat, form in ((self.GETATTR_PATTERN, "getattr"),
                          (self.BARE_PATTERN, "bare")):
            for m in pat.finditer(src):
                line = src[: m.start()].count("\n") + 1
                rel = path.relative_to(_AGENT_ROOT)
                violations.append(
                    f"  {rel}:{line} ({form}) `_agent_id ... or "
                    f"{m.group(1)!r}` — phantom default. Drop the `or`, "
                    f"let the gate handle empty actor."
                )
        return violations

    def test_no_phantom_agent_id_default(self) -> None:
        violations: list[str] = []
        for path in _tool_files():
            try:
                src = path.read_text()
            except UnicodeDecodeError:
                continue
            violations.extend(self._scan(src, path))
        if violations:
            self.fail(
                "Tools default _agent_id to a hard-coded actor:\n\n"
                + "\n".join(violations)
            )

    def test_scanner_catches_bare_attribute_form_via_probe(self) -> None:
        """Empirical self-check: a synthetic phantom in BARE form must
        red-fire the BARE_PATTERN. Catches regex regressions where the
        scanner silently goes 0-hit (round-3 incident)."""
        probe_src = (
            "def foo(self):\n"
            "    return self._agent_id or \"dead_phantom\"\n"
        )
        from pathlib import Path as _P
        hits = list(self.BARE_PATTERN.finditer(probe_src))
        self.assertGreaterEqual(
            len(hits), 1,
            "BARE_PATTERN failed to match the canonical phantom form "
            "`self._agent_id or \"<phantom>\"`. Regex regression — fix "
            "the pattern before merging.",
        )
        self.assertEqual(
            hits[0].group(1), "dead_phantom",
            f"BARE_PATTERN matched but captured {hits[0].group(1)!r}, "
            f"expected 'dead_phantom'.",
        )

    def test_scanner_catches_getattr_form_via_probe(self) -> None:
        """Same as above for the getattr form — locks both patterns."""
        probe_src = (
            "def foo(self):\n"
            "    return getattr(self, \"_agent_id\", None) or \"dead_phantom\"\n"
        )
        hits = list(self.GETATTR_PATTERN.finditer(probe_src))
        self.assertGreaterEqual(
            len(hits), 1,
            "GETATTR_PATTERN failed to match the canonical "
            "`getattr(self, \"_agent_id\", None) or \"<phantom>\"` form.",
        )
        self.assertEqual(hits[0].group(1), "dead_phantom")


class ResidentWorkflowReferencesLiveAgents(unittest.TestCase):
    def test_resident_workflow_targets_are_resident_lanes(self) -> None:
        cfg = yaml.safe_load(CONFIG_YAML.read_text())
        live = set((cfg.get("resident_lanes") or {}).keys())
        workflow = cfg.get("resident_workflow") or {}
        violations: list[str] = []
        for source, conf in workflow.items():
            if source not in live:
                violations.append(f"  source lane {source!r} not in resident_lanes")
            for target in (conf or {}).get("notifies") or []:
                if target not in live:
                    violations.append(
                        f"  {source!r} notifies {target!r} which is not a resident lane"
                    )
        if violations:
            self.fail(
                "resident_workflow edges reference dead lanes:\n\n"
                + "\n".join(violations)
            )


class AgentSubscriptionsReferenceLiveAgents(unittest.TestCase):
    def test_subscription_keys_are_resident_lanes(self) -> None:
        from multi_agent.runtime.agent_subscriptions import DEFAULT_SUBSCRIPTIONS

        live = _live_resident_lanes()
        dead = [k for k in DEFAULT_SUBSCRIPTIONS if k not in live]
        self.assertFalse(
            dead,
            f"DEFAULT_SUBSCRIPTIONS references {dead} which aren't resident "
            f"lanes. Live: {sorted(live)}",
        )


if __name__ == "__main__":
    unittest.main()
