"""PR 2 of the hub-responsibility-split plan (P1 de-dup).

Reviewer's acceptance criterion for the bug-routing de-dup:
  "no field name appears in bug_tools.py that WorkHub doesn't
   either define or read; the tool can't write a bug shape the
   hub doesn't understand."

The risk shape isn't predicate-divergence (PR 1) but
**field-name drift**: bug_tools could start writing
``bug_artifacts`` while WorkHub starts reading ``artifacts`` — both
test green individually, integration silently broken. So the parity
test scans both files at the AST/string level, not the behavior
level, and fails the build if either side writes/reads a field name
not declared in the canonical ``bug_schema`` module.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime import bug_schema  # noqa: E402

BUG_TOOLS_PATH = LLM_DIR / "tools" / "bug_tools.py"
WORKHUB_PATH = LLM_DIR / "multi_agent" / "runtime" / "hubs" / "workhub" / "service.py"


def _extract_create_task_kwargs(source: str) -> set:
    """Return the set of kwarg names passed to
    ``workhub.create_task(...)`` anywhere in the source."""
    tree = ast.parse(source)
    kwargs: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # match foo.create_task(...) and workhub.create_task(...)
        if not isinstance(func, ast.Attribute) or func.attr != "create_task":
            continue
        for kw in node.keywords:
            if kw.arg:
                kwargs.add(kw.arg)
    return kwargs


def _extract_update_bug_state_kwargs(source: str) -> set:
    """Return kwarg names passed to ``update_bug_state(...)`` calls."""
    tree = ast.parse(source)
    kwargs: set = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "update_bug_state":
            continue
        for kw in node.keywords:
            if kw.arg:
                kwargs.add(kw.arg)
    return kwargs


_META_RECV_RE = re.compile(r"\bmeta(?:data)?\b|['\"]metadata['\"]")


def _in_range(node, line_range):
    """Return True if a node's ``lineno`` falls within
    ``line_range`` (an (lo, hi) tuple inclusive). When
    ``line_range`` is None, accept all nodes."""
    if line_range is None:
        return True
    lo, hi = line_range
    lineno = getattr(node, "lineno", None)
    if lineno is None:
        return False
    return lo <= lineno <= hi


def _extract_metadata_get_keys(source: str, line_range=None) -> set:
    """Find every literal string used in metadata-style ``.get("X")``
    reads — the read side.

    PR 2.5-fix (reviewer 2026-05-28): the original regex required the
    receiver to be the literal identifier ``meta`` or ``metadata``,
    which made chained-expression reads invisible —
    ``(t.get("metadata") or {}).get("bug_state")`` silently went
    uncaught. We now walk the AST: for every ``.get(literal)`` call
    whose receiver textually references ``metadata`` or the bare
    ``meta`` identifier (per ``ast.unparse``), capture the literal.
    Catches the bare ``meta.get(...)``, the dict ``metadata.get(...)``
    form, AND the chained ``(t.get('metadata') or {}).get(...)``
    form.

    ``line_range`` is an optional (lo, hi) tuple to filter the
    parsed file down to a region (e.g. the bug-method block in
    service.py, which mid-file makes the bare-section text
    un-parseable on its own — we parse the FULL file and filter by
    line)."""
    keys: set = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return keys
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _in_range(node, line_range):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "get":
            continue
        try:
            recv_src = ast.unparse(func.value)
        except Exception:
            continue
        if not _META_RECV_RE.search(recv_src):
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
            keys.add(arg0.value)
    return keys


def _extract_metadata_setitem_keys(source: str, line_range=None) -> set:
    """Find ``meta[\"X\"] = ...`` / ``meta.setdefault(\"X\", ...)``
    style writes — the read side of WorkHub also DOES write metadata
    keys when applying lifecycle transitions. AST-based for the same
    reason as ``_extract_metadata_get_keys``."""
    keys: set = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return keys
    for node in ast.walk(tree):
        if not _in_range(node, line_range):
            continue
        if isinstance(node, ast.Subscript):
            try:
                recv_src = ast.unparse(node.value)
            except Exception:
                continue
            if not _META_RECV_RE.search(recv_src):
                continue
            slc = node.slice
            if isinstance(slc, ast.Constant) and isinstance(slc.value, str):
                keys.add(slc.value)
        elif isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "setdefault":
                continue
            try:
                recv_src = ast.unparse(func.value)
            except Exception:
                continue
            if not _META_RECV_RE.search(recv_src):
                continue
            if not node.args:
                continue
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                keys.add(arg0.value)
    return keys


def _extract_update_bug_state_literal_states(source: str) -> set:
    """Walk all ``*.update_bug_state(task_id, <STATE_LITERAL>, ...)``
    calls and capture the second positional arg when it's a string
    literal. Catches BOTH bug_tools' literals AND service.py's
    internal calls (``close_bug`` → "closed", ``escalate_bug`` →
    "escalated"). The original test only scanned bug_tools.py, so
    a typo'd literal in close_bug/escalate_bug would have been
    invisible — see reviewer's PR 2 scanner-gap finding."""
    used: set = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return used
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "update_bug_state":
            continue
        if len(node.args) < 2:
            continue
        second = node.args[1]
        if isinstance(second, ast.Constant) and isinstance(second.value, str):
            used.add(second.value)
    return used


def _bug_section_line_range(text: str) -> tuple:
    """Compute (lo, hi) line numbers of the bug-method block in
    service.py. The block starts at the ``_OPEN_BUG_STATES``
    constant declaration and ends at the first non-bug method
    that follows (``set_task_priority``).

    PR 2.5-fix-2 (2026-05-29, reviewer follow-up): the previous
    version silently fell back to ``(1, len(lines))`` when an
    anchor was missing, which would have scanned the WHOLE file
    and surfaced unrelated ``metadata.get`` reads as spurious
    "unknown field" failures (or in the partial-miss case, scanned
    too wide and red-lined the build). Now: raise ValueError on
    any anchor miss, which the calling test must explicitly
    accept (via the ``self.fail`` path) so an anchor rename is
    immediately surfaced rather than masked.

    Returns (lo, hi) inclusive. Raises ValueError if either
    anchor cannot be found — callers MUST handle this explicitly
    and treat it as "the heuristic broke, the test must be
    updated"."""
    lines = text.split("\n")
    lo = -1
    hi = -1
    for i, line in enumerate(lines, start=1):
        if lo < 0 and "_OPEN_BUG_STATES" in line:
            lo = i
        if lo > 0 and hi < 0 and "def set_task_priority" in line:
            hi = i - 1
            break
    if lo < 0:
        raise ValueError(
            "_bug_section_line_range: '_OPEN_BUG_STATES' anchor not "
            "found in service.py. The constant was renamed/removed. "
            "Update the anchor here AND in the helper docstring."
        )
    if hi < 0:
        raise ValueError(
            "_bug_section_line_range: 'def set_task_priority' anchor "
            "not found after the bug section. The method was renamed/"
            "moved/removed. Update the anchor."
        )
    return (lo, hi)


class BugToolsWritesOnlyDeclaredFields(unittest.TestCase):
    """Every kwarg the bug tools pass to ``workhub.create_task`` and
    ``workhub.update_bug_state`` must be either a generic top-level
    Task field OR a declared bug metadata field. If a future commit
    adds a new field name without adding it to bug_schema, this fails."""

    def test_bugcreatetool_kwargs_are_all_declared(self):
        text = BUG_TOOLS_PATH.read_text()
        kwargs = _extract_create_task_kwargs(text)
        allowed = (
            bug_schema.ALL_WRITABLE_METADATA_FIELDS
            | bug_schema.TOP_LEVEL_TASK_FIELDS
        )
        unknown = kwargs - allowed
        self.assertFalse(unknown,
                          f"bug_tools.create_task writes unknown field(s): "
                          f"{sorted(unknown)}. Add them to bug_schema "
                          f"(CREATE_METADATA_FIELDS / "
                          f"LIFECYCLE_PASSTHROUGH_FIELDS) — otherwise "
                          f"WorkHub won't recognize them.")

    def test_update_bug_state_kwargs_are_all_declared(self):
        text = BUG_TOOLS_PATH.read_text()
        kwargs = _extract_update_bug_state_kwargs(text)
        # update_bug_state has 4 named params (task_id, new_state,
        # agent, note, assignee, status) plus **metadata_updates.
        # All keyword names should be in the metadata schema OR one
        # of the function's own named parameters.
        known_params = {"task_id", "new_state", "agent", "note",
                        "assignee", "status"}
        allowed = (
            bug_schema.ALL_WRITABLE_METADATA_FIELDS | known_params
        )
        unknown = kwargs - allowed
        self.assertFalse(unknown,
                          f"bug_tools.update_bug_state writes unknown "
                          f"metadata-update field(s): {sorted(unknown)}. "
                          f"Add to bug_schema.LIFECYCLE_PASSTHROUGH_FIELDS.")


class WorkHubReadsOnlyDeclaredFields(unittest.TestCase):
    """Every metadata-style read in the WorkHub bug methods must
    correspond to a field bug_tools could legally have written.
    Otherwise the read side is consulting a field nobody on the
    write side declared, and the read silently sees default values
    in production — the exact drift this PR was supposed to make
    impossible."""

    def test_metadata_gets_in_workhub_match_writable_fields(self):
        text = WORKHUB_PATH.read_text()
        # Parse the full file (mid-file slicing produces
        # un-parseable fragments) and filter captured nodes by line
        # range. Section = _OPEN_BUG_STATES → set_task_priority.
        line_range = _bug_section_line_range(text)
        self.assertGreater(line_range[1], line_range[0],
                            "_bug_section_line_range failed — "
                            "section anchors moved; update the helper.")
        gets = _extract_metadata_get_keys(text, line_range=line_range)
        # PR 2.5-fix: the upgraded AST extractor now catches the
        # chained ``(t.get("metadata") or {}).get("bug_state")``
        # form in ``list_open_bugs``. The regex version silently
        # missed those reads. Pin that they're present now so the
        # parity guarantee actually holds.
        self.assertIn("bug_state", gets,
                       "scanner failed to catch ``bug_state`` read in "
                       "list_open_bugs — regression of the chained-.get "
                       "blind spot. Check _extract_metadata_get_keys.")
        self.assertIn("severity", gets,
                       "scanner failed to catch ``severity`` read in "
                       "list_open_bugs — same blind spot as bug_state.")
        allowed = bug_schema.READ_FIELDS | bug_schema.LIFECYCLE_PASSTHROUGH_FIELDS
        unknown = gets - allowed
        self.assertFalse(unknown,
                          f"WorkHub bug methods read field(s) not in the "
                          f"schema: {sorted(unknown)}. Either add to "
                          f"bug_schema.READ_FIELDS or stop reading them.")

    def test_metadata_writes_in_workhub_match_writable_fields(self):
        text = WORKHUB_PATH.read_text()
        line_range = _bug_section_line_range(text)
        writes = _extract_metadata_setitem_keys(text, line_range=line_range)
        allowed = bug_schema.ALL_WRITABLE_METADATA_FIELDS
        unknown = writes - allowed
        self.assertFalse(unknown,
                          f"WorkHub bug methods write metadata field(s) "
                          f"not in the schema: {sorted(unknown)}.")


class StatesAreDrawnFromSchema(unittest.TestCase):
    """State-value strings used in bug_tools AND in WorkHub's
    internal terminal-state writes (``close_bug`` → "closed",
    ``escalate_bug`` → "escalated") must be in
    ``bug_schema.VALID_STATES``. Catches the LLM-friendly-typo
    failure mode (``bug_update_state(new_state="resolved")`` when
    no such state exists), AND the previously-invisible "service.py
    typo'd a terminal state" mode the original test did not cover."""

    def test_states_in_bug_tools_are_all_valid(self):
        text = BUG_TOOLS_PATH.read_text()
        used = _extract_update_bug_state_literal_states(text)
        unknown = used - bug_schema.VALID_STATES
        self.assertFalse(unknown,
                          f"bug_tools transitions to unknown state(s): "
                          f"{sorted(unknown)} not in bug_schema.VALID_STATES "
                          f"({sorted(bug_schema.VALID_STATES)}). "
                          f"Either fix the typo or expand the schema.")

    def test_states_in_workhub_internal_calls_are_all_valid(self):
        """PR 2.5-fix: ``close_bug`` and ``escalate_bug`` call
        ``self.update_bug_state(task_id, "closed", ...)`` /
        ``"escalated"`` with the terminal state as a string
        literal. Before this test, a typo like ``"closd"`` would
        have green-lit because the scanner only walked bug_tools.py
        — service.py's internal calls weren't scanned at all."""
        text = WORKHUB_PATH.read_text()
        used = _extract_update_bug_state_literal_states(text)
        # The two known terminal states close_bug/escalate_bug
        # write — pin them as actually being detected by the
        # scanner. Without this assertion, a refactor that
        # rewrote those methods to bypass update_bug_state would
        # silently take the scan out of band.
        self.assertIn("closed", used,
                       "scanner did not catch ``closed`` literal in "
                       "service.py — close_bug write side is invisible "
                       "to the parity scanner.")
        self.assertIn("escalated", used,
                       "scanner did not catch ``escalated`` literal in "
                       "service.py — escalate_bug write side is invisible.")
        unknown = used - bug_schema.VALID_STATES
        self.assertFalse(unknown,
                          f"WorkHub internal calls write unknown state(s): "
                          f"{sorted(unknown)} not in "
                          f"bug_schema.VALID_STATES.")

    def test_workhub_open_states_subset_of_valid_states(self):
        """OPEN_STATES must be a subset of VALID_STATES, otherwise
        a list_open_bugs call could include states the hub claims
        aren't valid."""
        self.assertTrue(bug_schema.OPEN_STATES <= bug_schema.VALID_STATES)


class NegativeScannerCases(unittest.TestCase):
    """PR 2.5-fix (reviewer feedback): the scanner had no negative
    tests, so a regression that made the regex silently match
    nothing would still ship green. These tests construct synthetic
    bad source and assert the extractors actually surface the
    drift — turning the scanner from "we hope it works" into
    "we know it catches what it claims to catch"."""

    def test_metadata_get_extractor_catches_chained_form(self):
        """The pre-fix regex required ``meta`` / ``metadata`` to
        be a bare identifier — the chained ``(t.get('metadata') or
        {}).get('X')`` form (as in list_open_bugs) went silently
        uncaught. Pin that the AST walker now catches it."""
        src = """
def foo(t):
    return (t.get("metadata") or {}).get("rogue_field", "default")
"""
        keys = _extract_metadata_get_keys(src)
        self.assertIn("rogue_field", keys,
                       "AST walker failed to catch chained metadata "
                       "read — the original bug list_open_bugs has.")

    def test_metadata_get_extractor_catches_bare_form(self):
        src = """
def foo(meta):
    return meta.get("classic_field")
"""
        keys = _extract_metadata_get_keys(src)
        self.assertIn("classic_field", keys)

    def test_metadata_get_extractor_ignores_unrelated_get(self):
        """A ``.get("X")`` on a clearly-unrelated object (no
        meta/metadata in the receiver) must NOT be captured —
        otherwise the scanner would flood with false positives
        from every random dict lookup."""
        src = """
def foo(headers):
    return headers.get("Content-Type")
"""
        keys = _extract_metadata_get_keys(src)
        self.assertNotIn("Content-Type", keys)

    def test_state_extractor_catches_typo_in_close_bug_shape(self):
        """Construct a synthetic ``close_bug``-like call with a
        typo'd state, confirm the scanner flags it as not in
        VALID_STATES. Before the fix, this typo would have passed
        because service.py wasn't scanned."""
        src = """
def close_bug(self, task_id, agent):
    return self.update_bug_state(task_id, "closd", agent=agent)
"""
        used = _extract_update_bug_state_literal_states(src)
        self.assertIn("closd", used)
        unknown = used - bug_schema.VALID_STATES
        self.assertEqual(unknown, {"closd"},
                          "scanner did not detect the typo'd state — "
                          "the negative case is what gives the positive "
                          "assertions their meaning.")

    def test_kwargs_extractor_catches_rogue_field_name(self):
        """Synthetic ``create_task`` call with an undeclared kwarg —
        scanner must surface it so the build fails.

        PR 2.5-fix-2: tightened to an EQUALITY assertion on the
        unknown-set, not just subset/membership. The previous
        ``assertIn + assertFalse(<= allowed)`` would have been
        satisfied even by a superset-returning extractor that also
        captured every other kwarg; only the EQUALITY check pins
        the extractor to the exact bad key."""
        src = """
def make_bug(wh):
    return wh.create_task(
        title="t", description="d", agent="x",
        kind="bug",
        rogue_meta_field={"a": 1},
    )
"""
        kwargs = _extract_create_task_kwargs(src)
        self.assertEqual(
            kwargs,
            {"title", "description", "agent", "kind", "rogue_meta_field"},
            "kwargs extractor returned an unexpected set — neither a "
            "superset nor a subset is acceptable; the literal extraction "
            "must match the call's literal keyword names.",
        )
        allowed = (
            bug_schema.ALL_WRITABLE_METADATA_FIELDS
            | bug_schema.TOP_LEVEL_TASK_FIELDS
        )
        unknown = kwargs - allowed
        self.assertEqual(
            unknown, {"rogue_meta_field"},
            "expected exactly one unknown field; getting more would "
            "indicate the schema mistakenly excludes legitimate fields, "
            "fewer would mean the extractor missed the rogue.",
        )

    def test_chained_metadata_get_extractor_exact_set(self):
        """Tighten ``test_metadata_get_extractor_catches_chained_form``
        from membership to equality so a superset-returning extractor
        (which would falsely red-line the parity tests) is also
        rejected."""
        src = """
def foo(t):
    val = (t.get("metadata") or {}).get("rogue_field", "default")
    other = t.get("created_at")
    return val
"""
        keys = _extract_metadata_get_keys(src)
        self.assertEqual(
            keys, {"rogue_field"},
            f"chained metadata extractor must return exactly the "
            f"chained-receiver field — got {sorted(keys)}. Catching "
            f"``created_at`` (an unrelated read on a non-metadata "
            f"receiver) would falsely red-line the parity tests.",
        )


class ScannerKnownLimitations(unittest.TestCase):
    """PR 2.5-fix-2 (2026-05-29, reviewer follow-up): document the
    scanner's known false-negative patterns AS TESTS. The current
    codebase doesn't use these patterns, but if a future refactor
    introduces one, the maintainer should explicitly opt in (delete
    the test and acknowledge the gap) rather than silently land code
    the scanner can't see. Each test pins a known blind spot."""

    def test_kwargs_extractor_blind_to_dict_splat(self):
        """``wh.create_task(**{'rogue': 1})`` — ast.keywords with
        arg=None represent the splat; the extractor correctly skips
        them but that means the field name inside the dict is
        invisible. Acceptable trade-off (the codebase doesn't write
        bug create calls via splats and probably never should) but
        documented here so the limit is explicit."""
        src = """
def f(wh):
    return wh.create_task(**{"rogue_in_splat": 1, "title": "t"})
"""
        kwargs = _extract_create_task_kwargs(src)
        self.assertEqual(
            kwargs, set(),
            "splatted-dict create_task call yielded non-empty kwarg "
            "set; the extractor's expected behaviour is to skip "
            "splats. If this expectation changes, update the helper.",
        )

    def test_state_extractor_blind_to_name_second_arg(self):
        """``update_bug_state(tid, NEW_STATE_VAR, ...)`` where the
        second arg is an ``ast.Name`` instead of a string literal.
        Extractor skips non-Constant second args. If a future
        refactor moves state literals into module-level constants
        (e.g. ``STATE_CLOSED = 'closed'``), drift could ship
        invisible to this scanner — explicit limitation."""
        src = """
STATE_CLOSED = "closed"
def f(self, tid, agent):
    return self.update_bug_state(tid, STATE_CLOSED, agent=agent)
"""
        states = _extract_update_bug_state_literal_states(src)
        self.assertEqual(
            states, set(),
            "Name-typed second arg yielded a state; the extractor's "
            "expected behaviour is to skip non-Constant args. If you "
            "introduce module-level state constants, extend the "
            "extractor to resolve Names against module-level "
            "Assign nodes.",
        )


class BothSidesShareTheSameSchemaModule(unittest.TestCase):
    """The whole point of this PR: bug_tools.py and the WorkHub
    service.py must both import from ``bug_schema``. If one stops
    doing so, the parity scanner can't catch drift — pin the import."""

    def test_bug_tools_imports_bug_schema(self):
        text = BUG_TOOLS_PATH.read_text()
        self.assertIn("bug_schema", text,
                       "bug_tools.py must import bug_schema so it can "
                       "reference shared constants — otherwise the parity "
                       "guarantee disappears.")

    def test_workhub_imports_bug_schema(self):
        text = WORKHUB_PATH.read_text()
        self.assertIn("bug_schema", text,
                       "WorkHub service.py must import bug_schema. "
                       "Without it the parity guarantee disappears.")


class SchemaContainsAllExpectedConstants(unittest.TestCase):
    """A property check on the schema itself — pin the set of
    constants the rest of the test suite depends on."""

    def test_schema_has_required_constants(self):
        for name in (
            "KIND", "VALID_STATES", "OPEN_STATES", "STATE_INITIAL",
            "VALID_SEVERITIES", "SEVERITY_RANK",
            "CREATE_METADATA_FIELDS", "READ_FIELDS",
            "LIFECYCLE_PASSTHROUGH_FIELDS",
            "ALL_WRITABLE_METADATA_FIELDS",
            "TOP_LEVEL_TASK_FIELDS",
        ):
            self.assertTrue(hasattr(bug_schema, name),
                             f"bug_schema is missing {name!r}")

    def test_severity_rank_consistent_with_valid_severities(self):
        self.assertEqual(
            set(bug_schema.SEVERITY_RANK.keys()),
            set(bug_schema.VALID_SEVERITIES),
        )


if __name__ == "__main__":
    unittest.main()
