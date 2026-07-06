"""Pure-Python validator for milestone kickoff artifacts (charter §5).

WHY
---
The kickoff meeting MUST produce a small set of structurally well-formed
artifacts before any implementation task is dispatched (charter §5):

  1. Contract delta            — API endpoints + data model + auth
  2. Task tree                 — WorkHub tasks with owner + depends_on + kind
  3. Acceptance predicates     — machine-checkable, per critical flow
  4. Definition of Done        — non-empty list
  5. (M1 only) Global feature inventory — entities + flows for the whole project

If any of these are malformed before build, the contract-drift bug class
re-enters by the back door. This validator is the closed-by-construction
gate: a pure function over already-loaded artifacts that produces a
``ValidationResult`` aggregate. It runs BEFORE ``close_meeting`` so a
malformed kickoff cannot ship.

Pure-function contract (matches charter §8 + plan §Phase-C step 2):
  - No I/O (no file reads, no hub calls, no LLM)
  - No raises on bad shape — return a finding instead
  - Raises ValueError ONLY for caller misuse (e.g. milestone_index < 1,
    or roadmap is not a Mapping). No phantom defaults, per charter
    "no fallback, no back-compat" discipline.
  - Deterministic output order (input artifact order preserved within
    each section)
  - LLM-free; the kickoff orchestrator will call this between collecting
    drafts and writing the milestone page.

ARTIFACT SHAPES (the contract this validator enforces)
------------------------------------------------------
The roadmap mapping passed to :func:`validate_roadmap` is the snapshot
produced by the orchestrator's synthesis step. Charter §5 names the
sections; the shapes below are what this module accepts. New shapes
should add a new check, never silently extend an existing one.

``roadmap`` (Mapping[str, Any])::

    {
      "milestone_index": int,            # MUST match the milestone_index arg
      "contract": {
        "endpoints":  [Endpoint, ...],   # MUST be non-empty for any milestone
        "data_model": {"tables": [Table, ...]},   # MUST be non-empty
        "auth":       {"model": str, "required": bool},  # required keys
      },
      "task_tree":            [Task, ...],   # MUST be non-empty
      "acceptance_predicates":[Predicate, ...],  # MUST be non-empty
      "done_def":             [str, ...],    # MUST be non-empty
      # M1 only:
      "feature_inventory":    {
        "entities": [str, ...],          # MUST be non-empty for M1
        "flows":    [str, ...],          # MUST be non-empty for M1
      },
    }

Where each sub-shape MUST satisfy::

    Endpoint  = {"method": str, "path": str, "response_key": str, "auth_required": bool}
    Table     = {"name": str, "columns": [{"name": str, "type": str}, ...]}
    Task      = {"id": str, "owner": str, "depends_on": [str, ...], "kind": str, "status": str}
    Predicate = {"id": str, "flow": str, "form": {"kind": str, ...}}
                # form.kind MUST be one of {"api_smoke", "ui_flow",
                # "sql_check", "predicate_dsl"} — the v1 machine-checkable
                # vocabulary. New kinds add a new entry.

Output shape (``ValidationResult``)::

    {
      "ok": bool,                        # True iff every finding.severity == "info"
      "milestone_index": int,            # echoed for the caller
      "findings": [Finding, ...],        # input order preserved within section
    }
    Finding = {
      "section": str,                    # "contract" | "task_tree" | ...
      "id":      str,                    # stable identifier within section
      "severity":str,                    # "error" | "warning" | "info"
      "message": str,                    # human-readable, short
    }

Closed-by-construction: only ``severity == "error"`` flips ``ok`` to False;
``warning`` is surfaced for orchestrator audit but does not block kickoff
close. ``info`` rows are pure echoes (e.g. "task_tree: 7 tasks accepted")
useful for the live_monitor progress bar.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

__all__ = [
    "Finding",
    "ValidationResult",
    "validate_roadmap",
    "ACCEPTANCE_PREDICATE_KINDS",
    "VALID_TASK_STATUSES",
]


# Type aliases (PEP 484 — keep simple to avoid python-version coupling).
Finding = Dict[str, Any]
ValidationResult = Dict[str, Any]


# v1 machine-checkable predicate vocabulary. New kinds add a new entry —
# never expand silently (charter §C — closed-by-construction).
ACCEPTANCE_PREDICATE_KINDS: Set[str] = {
    "api_smoke",
    "ui_flow",
    "sql_check",
    "predicate_dsl",
}


# Closed task-status vocabulary (charter §5 + workhub schema). A task whose
# status string is outside this set MUST surface as an error finding — silent
# acceptance would let downstream pollers misread the lifecycle. New states
# add a new entry; never expand silently.
VALID_TASK_STATUSES: Set[str] = {
    "pending",
    "ready",
    "claimed",
    "done",
    "blocked",
    "failed",
    "cancelled",
}


# ---------------------------------------------------------------------------
# Helpers — small, pure, each enforcing one shape rule.
# ---------------------------------------------------------------------------


def _finding(section: str, fid: str, severity: str, message: str) -> Finding:
    """Build a finding dict with stable key order."""
    return {
        "section": section,
        "id": fid,
        "severity": severity,
        "message": message,
    }


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _check_contract(contract: Any, milestone_index: int = 1) -> List[Finding]:
    """Validate the ``contract`` block: endpoints + data_model + auth."""
    findings: List[Finding] = []
    if not isinstance(contract, Mapping):
        findings.append(_finding(
            "contract", "contract_shape", "error",
            "contract MUST be a mapping with keys "
            "{endpoints, data_model, auth}",
        ))
        return findings

    # --- endpoints ---------------------------------------------------------
    endpoints = contract.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) == 0:
        findings.append(_finding(
            "contract", "endpoints_missing", "error",
            "contract.endpoints MUST be a non-empty list",
        ))
    else:
        required = ("method", "path", "response_key", "auth_required")
        for idx, ep in enumerate(endpoints):
            ep_id = f"endpoint[{idx}]"
            if not isinstance(ep, Mapping):
                findings.append(_finding(
                    "contract", ep_id, "error",
                    "endpoint MUST be a mapping",
                ))
                continue
            for key in required:
                if key not in ep:
                    findings.append(_finding(
                        "contract", f"{ep_id}.{key}", "error",
                        f"endpoint MUST have '{key}'",
                    ))
                    continue
            # Field-type checks (only if all keys present)
            if all(k in ep for k in required):
                if not _is_nonempty_str(ep["method"]):
                    findings.append(_finding(
                        "contract", f"{ep_id}.method", "error",
                        "endpoint.method MUST be a non-empty string",
                    ))
                if not _is_nonempty_str(ep["path"]):
                    findings.append(_finding(
                        "contract", f"{ep_id}.path", "error",
                        "endpoint.path MUST be a non-empty string",
                    ))
                if not _is_nonempty_str(ep["response_key"]):
                    findings.append(_finding(
                        "contract", f"{ep_id}.response_key", "error",
                        "endpoint.response_key MUST be a non-empty string",
                    ))
                if not isinstance(ep["auth_required"], bool):
                    findings.append(_finding(
                        "contract", f"{ep_id}.auth_required", "error",
                        "endpoint.auth_required MUST be a bool",
                    ))

            # --- response.tables (cross_check_suite alignment) -------------
            # The canonical KickoffEndpoint (see contract.py) carries an
            # optional ``response`` sub-mapping; when present, its
            # ``tables`` list MUST be a list of non-empty strings —
            # cross_check_suite.api_vs_data_model reads them verbatim.
            # Absent ``response`` is OK (vacuously aligned); a malformed
            # ``response.tables`` MUST NOT slip through silently.
            if isinstance(ep, Mapping) and "response" in ep:
                response = ep["response"]
                if not isinstance(response, Mapping):
                    findings.append(_finding(
                        "contract", f"{ep_id}.response", "error",
                        "endpoint.response MUST be a mapping when present",
                    ))
                elif "tables" in response:
                    tables = response["tables"]
                    if not isinstance(tables, list):
                        findings.append(_finding(
                            "contract", f"{ep_id}.response.tables", "error",
                            "endpoint.response.tables MUST be a list of "
                            "non-empty strings",
                        ))
                    else:
                        for t_idx, name in enumerate(tables):
                            if not _is_nonempty_str(name):
                                findings.append(_finding(
                                    "contract",
                                    f"{ep_id}.response.tables[{t_idx}]",
                                    "error",
                                    "endpoint.response.tables entries MUST "
                                    "be non-empty strings",
                                ))

    # --- data_model --------------------------------------------------------
    data_model = contract.get("data_model")
    if not isinstance(data_model, Mapping):
        findings.append(_finding(
            "contract", "data_model_shape", "error",
            "contract.data_model MUST be a mapping with key 'tables'",
        ))
    else:
        tables = data_model.get("tables")
        if not isinstance(tables, list) or len(tables) == 0:
            # FIX #96 (instagram run-14 M2, live): the contract is CUMULATIVE — a
            # vertical slice at milestone 2+ routinely adds endpoints on the tables
            # M1 already registered, so an EMPTY tables list there is legitimate.
            # The unconditional error made kickoff synthesis validation_failed →
            # run abort right after M1 delivered (and right after the #95 retry
            # had successfully recovered the missing sections). Milestone 1 (the
            # walking skeleton) still hard-requires tables.
            findings.append(_finding(
                "contract", "data_model.tables_missing",
                "error" if int(milestone_index or 1) <= 1 else "warning",
                "contract.data_model.tables MUST be a non-empty list"
                if int(milestone_index or 1) <= 1 else
                "contract.data_model.tables is empty — OK for a milestone 2+ "
                "slice on the cumulative contract (M1 registered the tables)",
            ))
        else:
            for idx, tbl in enumerate(tables):
                t_id = f"table[{idx}]"
                if not isinstance(tbl, Mapping):
                    findings.append(_finding(
                        "contract", t_id, "error",
                        "table MUST be a mapping",
                    ))
                    continue
                if not _is_nonempty_str(tbl.get("name")):
                    findings.append(_finding(
                        "contract", f"{t_id}.name", "error",
                        "table.name MUST be a non-empty string",
                    ))
                cols = tbl.get("columns")
                if not isinstance(cols, list) or len(cols) == 0:
                    findings.append(_finding(
                        "contract", f"{t_id}.columns", "error",
                        "table.columns MUST be a non-empty list",
                    ))
                    continue
                for c_idx, col in enumerate(cols):
                    c_id = f"{t_id}.col[{c_idx}]"
                    if not isinstance(col, Mapping):
                        findings.append(_finding(
                            "contract", c_id, "error",
                            "column MUST be a mapping",
                        ))
                        continue
                    if not _is_nonempty_str(col.get("name")):
                        findings.append(_finding(
                            "contract", f"{c_id}.name", "error",
                            "column.name MUST be a non-empty string",
                        ))
                    if not _is_nonempty_str(col.get("type")):
                        findings.append(_finding(
                            "contract", f"{c_id}.type", "error",
                            "column.type MUST be a non-empty string",
                        ))

    # --- auth --------------------------------------------------------------
    auth = contract.get("auth")
    if not isinstance(auth, Mapping):
        findings.append(_finding(
            "contract", "auth_shape", "error",
            "contract.auth MUST be a mapping with keys {model, required}",
        ))
    else:
        if not _is_nonempty_str(auth.get("model")):
            findings.append(_finding(
                "contract", "auth.model", "error",
                "contract.auth.model MUST be a non-empty string "
                "(e.g. 'jwt', 'session', 'none')",
            ))
        if not isinstance(auth.get("required"), bool):
            findings.append(_finding(
                "contract", "auth.required", "error",
                "contract.auth.required MUST be a bool",
            ))

    return findings


def _check_task_tree(task_tree: Any) -> List[Finding]:
    """Validate the ``task_tree`` block.

    Rules:
      - non-empty list
      - every task has id + owner + depends_on + kind + status (all non-empty strings,
        depends_on is a list of strings)
      - task ids are unique
      - every depends_on entry refers to an id that exists in the tree
      - no dependency cycles (DFS with grey/black markers)
    """
    findings: List[Finding] = []
    if not isinstance(task_tree, list) or len(task_tree) == 0:
        findings.append(_finding(
            "task_tree", "task_tree_missing", "error",
            "task_tree MUST be a non-empty list",
        ))
        return findings

    required = ("id", "owner", "depends_on", "kind", "status")
    ids_seen: List[str] = []
    by_id: Dict[str, Mapping[str, Any]] = {}

    for idx, task in enumerate(task_tree):
        t_id = f"task[{idx}]"
        if not isinstance(task, Mapping):
            findings.append(_finding(
                "task_tree", t_id, "error",
                "task MUST be a mapping",
            ))
            continue
        for key in required:
            if key not in task:
                findings.append(_finding(
                    "task_tree", f"{t_id}.{key}", "error",
                    f"task MUST have '{key}'",
                ))

        tid = task.get("id")
        if _is_nonempty_str(tid):
            if tid in by_id:
                findings.append(_finding(
                    "task_tree", f"duplicate_id:{tid}", "error",
                    "task ids MUST be unique within the tree",
                ))
            else:
                ids_seen.append(tid)
                by_id[tid] = task
        else:
            if "id" in task:
                findings.append(_finding(
                    "task_tree", f"{t_id}.id", "error",
                    "task.id MUST be a non-empty string",
                ))

        owner = task.get("owner")
        if "owner" in task and not _is_nonempty_str(owner):
            findings.append(_finding(
                "task_tree", f"{t_id}.owner", "error",
                "task.owner MUST be a non-empty string",
            ))
        kind = task.get("kind")
        if "kind" in task and not _is_nonempty_str(kind):
            findings.append(_finding(
                "task_tree", f"{t_id}.kind", "error",
                "task.kind MUST be a non-empty string",
            ))
        status = task.get("status")
        if "status" in task:
            if not _is_nonempty_str(status):
                findings.append(_finding(
                    "task_tree", f"{t_id}.status", "error",
                    "task.status MUST be a non-empty string",
                ))
            elif status not in VALID_TASK_STATUSES:
                # Vocabulary check (closed-by-construction): silent
                # acceptance of unknown statuses lets the polling loop
                # misread the lifecycle. New states add a new entry to
                # VALID_TASK_STATUSES — never expand silently.
                findings.append(_finding(
                    "task_tree", f"{t_id}.status", "error",
                    f"unsupported task status {status!r}; "
                    f"v1 vocabulary = {sorted(VALID_TASK_STATUSES)}",
                ))

        deps = task.get("depends_on")
        if "depends_on" in task:
            if not isinstance(deps, list):
                findings.append(_finding(
                    "task_tree", f"{t_id}.depends_on", "error",
                    "task.depends_on MUST be a list (use [] for none)",
                ))
            else:
                for d_idx, dep in enumerate(deps):
                    if not _is_nonempty_str(dep):
                        findings.append(_finding(
                            "task_tree",
                            f"{t_id}.depends_on[{d_idx}]",
                            "error",
                            "task.depends_on entries MUST be non-empty strings",
                        ))

    # --- referential integrity ---------------------------------------------
    valid_ids: Set[str] = set(ids_seen)
    for idx, task in enumerate(task_tree):
        if not isinstance(task, Mapping):
            continue
        tid = task.get("id") if _is_nonempty_str(task.get("id")) else f"task[{idx}]"
        deps = task.get("depends_on")
        if not isinstance(deps, list):
            continue
        for dep in deps:
            if not _is_nonempty_str(dep):
                continue
            if dep not in valid_ids:
                findings.append(_finding(
                    "task_tree", f"{tid}.unknown_dep:{dep}", "error",
                    f"task.depends_on references unknown task id "
                    f"'{dep}' (not in task_tree)",
                ))

    # --- cycle detection (iterative DFS, grey/black markers) --------------
    # Iterative form (mirrors ready_set._dfs at runtime/kickoff/ready_set.py
    # line 137) so chains of 1000+ tasks don't blow Python's recursion limit.
    # Difference from ready_set: this validator COLLECTS cycle findings and
    # dedupes by sorted-node-tuple signature instead of raising on the
    # first back-edge — every distinct cycle MUST surface as exactly one
    # error finding.
    WHITE, GREY, BLACK = 0, 1, 2
    color: Dict[str, int] = {tid: WHITE for tid in valid_ids}
    cycle_reported: Set[Tuple[str, ...]] = set()

    def _dfs(start: str) -> None:
        # Invariant: every node on ``dfs_stack`` is GREY and also on
        # ``path`` in the same order — push together, pop together.
        if color.get(start, BLACK) != WHITE:
            return
        color[start] = GREY
        path: List[str] = [start]
        # Each stack frame is (node, next_child_index_to_visit).
        dfs_stack: List[Tuple[str, int]] = [(start, 0)]
        while dfs_stack:
            node, child_idx = dfs_stack[-1]
            task = by_id.get(node, {})
            deps = task.get("depends_on", []) or []
            # Advance to the next dep whose shape is admissible AND that
            # actually exists in the colour map. Shape-invalid deps and
            # unknown-id deps have already been flagged upstream.
            next_dep: Optional[str] = None
            while child_idx < len(deps):
                candidate = deps[child_idx]
                child_idx += 1
                if not _is_nonempty_str(candidate) or candidate not in color:
                    continue
                next_dep = candidate
                break
            dfs_stack[-1] = (node, child_idx)

            if next_dep is None:
                # All children visited — mark BLACK and pop.
                color[node] = BLACK
                path.pop()
                dfs_stack.pop()
                continue

            if color[next_dep] == GREY:
                # Back-edge → cycle. Slice ``path`` from the cycle's entry
                # point and append the back-target for readability.
                try:
                    cycle_start = path.index(next_dep)
                    cycle = tuple(path[cycle_start:] + [next_dep])
                except ValueError:
                    # path.index miss shouldn't happen given the GREY
                    # invariant, but stay defensive — record a minimal
                    # cycle slice rather than re-raise (closed-by-
                    # construction: never propagate to caller).
                    cycle = (next_dep, node, next_dep)
                key = tuple(sorted(cycle))
                if key not in cycle_reported:
                    cycle_reported.add(key)
                    findings.append(_finding(
                        "task_tree", f"cycle:{'->'.join(cycle)}", "error",
                        "task_tree MUST be acyclic; depends_on cycle detected",
                    ))
                # Do NOT recurse into a GREY node — that's the cycle.
            elif color[next_dep] == WHITE:
                color[next_dep] = GREY
                path.append(next_dep)
                dfs_stack.append((next_dep, 0))
            # BLACK → already fully explored; skip.

    for node in ids_seen:
        if color.get(node, BLACK) == WHITE:
            _dfs(node)

    if not findings:
        findings.append(_finding(
            "task_tree", "task_tree_ok", "info",
            f"task_tree accepted ({len(ids_seen)} tasks)",
        ))
    return findings


def _check_acceptance_predicates(predicates: Any) -> List[Finding]:
    """Validate acceptance predicates list (charter §5 item 3)."""
    findings: List[Finding] = []
    if not isinstance(predicates, list) or len(predicates) == 0:
        findings.append(_finding(
            "acceptance_predicates", "predicates_missing", "error",
            "acceptance_predicates MUST be a non-empty list "
            "(verifier writes machine-checkable predicates at kickoff)",
        ))
        return findings
    for idx, pred in enumerate(predicates):
        p_id = f"predicate[{idx}]"
        if not isinstance(pred, Mapping):
            findings.append(_finding(
                "acceptance_predicates", p_id, "error",
                "acceptance_predicate MUST be a mapping",
            ))
            continue
        if not _is_nonempty_str(pred.get("id")):
            findings.append(_finding(
                "acceptance_predicates", f"{p_id}.id", "error",
                "predicate.id MUST be a non-empty string",
            ))
        if not _is_nonempty_str(pred.get("flow")):
            findings.append(_finding(
                "acceptance_predicates", f"{p_id}.flow", "error",
                "predicate.flow MUST be a non-empty string "
                "(name of the user flow being asserted)",
            ))
        form = pred.get("form")
        if not isinstance(form, Mapping):
            findings.append(_finding(
                "acceptance_predicates", f"{p_id}.form", "error",
                "predicate.form MUST be a mapping with key 'kind'",
            ))
            continue
        kind = form.get("kind")
        if not _is_nonempty_str(kind):
            findings.append(_finding(
                "acceptance_predicates", f"{p_id}.form.kind", "error",
                "predicate.form.kind MUST be a non-empty string",
            ))
        elif kind not in ACCEPTANCE_PREDICATE_KINDS:
            findings.append(_finding(
                "acceptance_predicates", f"{p_id}.form.kind", "error",
                f"unsupported predicate kind '{kind}'; "
                f"v1 vocabulary = {sorted(ACCEPTANCE_PREDICATE_KINDS)}",
            ))
    return findings


def _check_done_def(done_def: Any) -> List[Finding]:
    """Validate Definition of Done (charter §5 item 4)."""
    findings: List[Finding] = []
    if not isinstance(done_def, list) or len(done_def) == 0:
        findings.append(_finding(
            "done_def", "done_def_missing", "error",
            "done_def MUST be a non-empty list of done-criteria strings",
        ))
        return findings
    for idx, item in enumerate(done_def):
        if not _is_nonempty_str(item):
            findings.append(_finding(
                "done_def", f"done_def[{idx}]", "error",
                "done_def entries MUST be non-empty strings",
            ))
    return findings


def _check_feature_inventory_m1(inventory: Any) -> List[Finding]:
    """Validate global feature inventory (M1 only — charter §5 item 5)."""
    findings: List[Finding] = []
    if not isinstance(inventory, Mapping):
        findings.append(_finding(
            "feature_inventory", "feature_inventory_missing", "error",
            "M1 kickoff MUST emit feature_inventory "
            "{'entities': [...], 'flows': [...]} "
            "(global plan at M1, charter §3)",
        ))
        return findings
    entities = inventory.get("entities")
    flows = inventory.get("flows")
    if not isinstance(entities, list) or len(entities) == 0:
        findings.append(_finding(
            "feature_inventory", "entities_missing", "error",
            "feature_inventory.entities MUST be a non-empty list "
            "(full entity inventory at M1)",
        ))
    else:
        for idx, name in enumerate(entities):
            if not _is_nonempty_str(name):
                findings.append(_finding(
                    "feature_inventory", f"entities[{idx}]", "error",
                    "feature_inventory.entities entries MUST be non-empty strings",
                ))
    if not isinstance(flows, list) or len(flows) == 0:
        findings.append(_finding(
            "feature_inventory", "flows_missing", "error",
            "feature_inventory.flows MUST be a non-empty list "
            "(full flow inventory at M1)",
        ))
    else:
        for idx, name in enumerate(flows):
            if not _is_nonempty_str(name):
                findings.append(_finding(
                    "feature_inventory", f"flows[{idx}]", "error",
                    "feature_inventory.flows entries MUST be non-empty strings",
                ))
    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_roadmap(
    roadmap: Mapping[str, Any],
    milestone_index: int,
) -> ValidationResult:
    """Validate the kickoff-meeting roadmap snapshot for one milestone.

    Pure function. Takes already-loaded artifacts; never touches a hub,
    the filesystem, or an LLM. Caller (the future
    ``Orchestrator.run_kickoff``) MUST pass both args explicitly — no
    phantom defaults (charter "no fallback, no back-compat").

    Args:
        roadmap: the synthesized milestone snapshot. See the module
            docstring for the required shape.
        milestone_index: 1-based milestone counter. ``1`` is the
            walking-skeleton; ``2..N`` are vertical feature slices.
            ``feature_inventory`` is required ONLY for milestone 1.

    Returns:
        ``ValidationResult`` aggregate::

            {
              "ok":               bool,   # True iff no error-severity findings
              "milestone_index":  int,
              "findings":         [Finding, ...],
            }

        Findings keep input order within each section. ``ok=True`` iff
        every finding has ``severity in {"info", "warning"}``.

    Raises:
        ValueError: if ``roadmap`` is not a Mapping, or
            ``milestone_index`` is not an int >= 1. These are caller
            misuse — not data-shape problems.
    """
    if not isinstance(milestone_index, int) or milestone_index < 1:
        raise ValueError(
            "milestone_index MUST be an int >= 1 "
            "(M1 is the walking skeleton, M2+ are vertical slices); "
            f"got {milestone_index!r}"
        )
    if not isinstance(roadmap, Mapping):
        raise ValueError(
            "roadmap MUST be a Mapping (already-loaded snapshot); "
            f"got {type(roadmap).__name__}"
        )

    findings: List[Finding] = []

    # Cross-check the milestone_index echo if present.
    echoed = roadmap.get("milestone_index")
    if echoed is not None and echoed != milestone_index:
        findings.append(_finding(
            "milestone_index", "milestone_index_mismatch", "error",
            f"roadmap.milestone_index={echoed!r} does not match arg "
            f"{milestone_index!r}",
        ))

    findings.extend(_check_contract(roadmap.get("contract"), milestone_index))
    findings.extend(_check_task_tree(roadmap.get("task_tree")))
    findings.extend(_check_acceptance_predicates(
        roadmap.get("acceptance_predicates")
    ))
    findings.extend(_check_done_def(roadmap.get("done_def")))

    if milestone_index == 1:
        findings.extend(_check_feature_inventory_m1(
            roadmap.get("feature_inventory")
        ))

    ok = all(f["severity"] != "error" for f in findings)
    return {
        "ok": ok,
        "milestone_index": milestone_index,
        "findings": findings,
    }
