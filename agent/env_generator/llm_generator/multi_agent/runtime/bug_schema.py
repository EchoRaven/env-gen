"""Canonical bug schema — single source of truth for field names,
state values, and severity constants.

PR 2 of the hub-responsibility-split plan
(``docs/hub_responsibility_split_plan.md``). The reviewer's
acceptance criterion for the bug-routing de-dup was: "no field
name appears in bug_tools.py that WorkHub doesn't either define or
read; the tool can't write a bug shape the hub doesn't understand."

Both the bug tools (``tools/bug_tools.py``, write side) and the
WorkHub bug methods (``hubs/workhub/service.py``, read side) import
the constants in this module. A parity test
(``tests/test_bug_schema_parity.py``) scans both files and fails
the build if either side writes or reads a field name not declared
here — pinning the schema so the two sides can never drift.

Sections:
  * ``KIND``                       — the task.metadata.kind marker.
  * ``VALID_STATES`` / ``OPEN_STATES`` / ``STATE_INITIAL`` —
    bug-lifecycle state values.
  * ``VALID_SEVERITIES`` /
    ``SEVERITY_RANK``              — severity vocabulary + sort key.
  * ``CREATE_METADATA_FIELDS``     — fields ``bug_tools.BugCreateTool``
    writes via ``workhub.create_task(**kwargs)`` on initial creation.
  * ``READ_FIELDS``                — fields WorkHub bug methods
    actually consult.
  * ``LIFECYCLE_PASSTHROUGH_FIELDS`` — fields written during state
    transitions and stored opaquely (not read by the hub but
    persisted on the task).
  * ``ALL_WRITABLE_METADATA_FIELDS`` — the closure: any field name a
    tool can legally write to the bug task's metadata.
"""

from __future__ import annotations

from typing import Dict, FrozenSet, Tuple


# ----- kind marker --------------------------------------------------

# Value of ``task["metadata"]["kind"]`` that distinguishes a bug task
# from a regular task / plan / design page.
KIND: str = "bug"


# ----- lifecycle states ---------------------------------------------

# Full lifecycle vocabulary.
VALID_STATES: FrozenSet[str] = frozenset({
    "open", "triaged", "assigned", "in_progress",
    "fix_proposed", "fix_verified", "closed", "escalated",
})
# "Still actionable" filter used by ``list_open_bugs``.
# ``fix_verified`` is intentionally NOT in this set — the convention
# is "a verified fix awaits close/escalate, not 'open' for new work".
OPEN_STATES: FrozenSet[str] = frozenset({
    "open", "triaged", "assigned", "in_progress", "fix_proposed",
})
# State a newly-created bug starts in.
STATE_INITIAL: str = "open"


# ----- severity -----------------------------------------------------

# Allowed values for ``task["metadata"]["severity"]``.
# Order matters — ``SEVERITY_RANK`` derives sort keys from this tuple
# so P0 < P1 < ... < P3.
VALID_SEVERITIES: Tuple[str, ...] = ("P0", "P1", "P2", "P3")
SEVERITY_RANK: Dict[str, int] = {sev: i for i, sev in enumerate(VALID_SEVERITIES)}


# ----- field-name schema --------------------------------------------

# Fields bug_tools writes through ``create_task(**kwargs)`` at the
# initial bug-creation moment. Each appears as ``<name>=...`` inside
# ``BugCreateTool._run``.
CREATE_METADATA_FIELDS: FrozenSet[str] = frozenset({
    "kind",
    "severity",
    "bug_state",
    "source",
    "parent_bug_id",
    "bug_artifacts",
    "triage_history",
})

# Fields WorkHub's bug read-side actually consults. Note: the read
# side ALSO consults the top-level task fields ``assignee`` and
# ``created_at`` — those are general task fields, not bug-specific
# metadata, and aren't governed by this schema (covered by the
# generic Task schema in WorkHub).
READ_FIELDS: FrozenSet[str] = frozenset({
    "kind",
    "bug_state",
    "severity",
    "bug_artifacts",
})

# Fields the lifecycle transition tools write through
# ``update_bug_state(**metadata_updates)`` / ``close_bug`` /
# ``escalate_bug`` and the hub stores as opaque metadata. These are
# legitimate writes that WorkHub doesn't directly query against, but
# the schema declares them so the parity scanner doesn't flag them
# as "unknown field name".
LIFECYCLE_PASSTHROUGH_FIELDS: FrozenSet[str] = frozenset({
    "triage_history",        # appended-to by update_bug_state
    "root_cause_hypothesis",  # written by BugTriageTool
    "fix_evidence",           # written by BugCloseTool
    "escalation_reason",      # written by BugEscalateTool
})

# The closure — every metadata field name a tool can legally write.
# Parity scanner enforces: every ``<name>=...`` keyword the tools
# pass to create_task / update_bug_state / close_bug / escalate_bug
# must be either a top-level task field or in this set.
ALL_WRITABLE_METADATA_FIELDS: FrozenSet[str] = (
    CREATE_METADATA_FIELDS
    | READ_FIELDS
    | LIFECYCLE_PASSTHROUGH_FIELDS
)


# ----- top-level task fields the bug tools write through (not metadata) ---

# Generic ``Task`` fields the bug tools also touch — these belong to
# WorkHub's generic task schema, not this bug schema. Listed for the
# scanner so it can recognize them as "not a metadata field; OK".
TOP_LEVEL_TASK_FIELDS: FrozenSet[str] = frozenset({
    "title", "description", "agent", "task_id",
    "assignee", "status", "priority", "depends_on", "plan_id",
})


__all__ = [
    "KIND",
    "VALID_STATES",
    "OPEN_STATES",
    "STATE_INITIAL",
    "VALID_SEVERITIES",
    "SEVERITY_RANK",
    "CREATE_METADATA_FIELDS",
    "READ_FIELDS",
    "LIFECYCLE_PASSTHROUGH_FIELDS",
    "ALL_WRITABLE_METADATA_FIELDS",
    "TOP_LEVEL_TASK_FIELDS",
]
