"""Round 8f.2 — kickoff authoring: synthesize human-readable milestone
artifacts (MILESTONE_M{n}.md / ROADMAP.md / BRIEFING_M{n}_{agent}.md)
from a finalized kickoff synthesis_result.

Pure-Python module. Zero I/O, zero LLM, zero hub coupling. The caller
(typically the kickoff driver in ``orchestrator.py``) is responsible
for filesystem writes / codehub commits / etc. This shape keeps the
authoring testable without a real LLM run + lets the driver decide
where the artifacts land per project (CI repo vs ephemeral workspace).

Why a module rather than an orchestrator LLM turn?

  * Determinism: every kickoff with the same synthesis_result produces
    byte-identical docs. Regressions are diff-visible.
  * Cost: no extra LLM call after finalize_kickoff. The synthesis_result
    already carries every fact the docs need; an LLM turn would just
    re-narrate it (with hallucination risk).
  * Audit: docs/MILESTONE_M{n}.md is the human-readable mirror of the
    machine-readable contract + task_tree + predicates. They MUST stay
    in sync; a pure function makes that a code-review concern rather
    than a vibes concern.

The user's earlier ask (round 8f planning):
  > "orchestrator 还得根据会议写 milestone 或者 roadmap 之类的文件,
  >  规划整个 workflow 重申各个 agent 当前 milestone 职责"

This module produces:

  * **MILESTONE_M{n}.md** — the canonical per-milestone spec mirror.
    Audience: a human reader who wants to know "what is M{n}".
  * **ROADMAP.md** — cumulative project plan. Each new milestone
    appends a section; prior milestones are preserved verbatim.
  * **BRIEFING_M{n}_{agent}.md** — per-agent "marching orders" for
    the milestone. Audience: the agent's lane lead reading it before
    they execute. Carries only the slice of the synthesis that lane
    needs to act on.

API surface (the driver calls only these):

    author_all(
        synthesis: SynthesisResult,
        project_name: Optional[str] = None,
        prior_roadmap_md: Optional[str] = None,
        attendees: Optional[Iterable[str]] = None,
    ) -> AuthoringOutputs

    where AuthoringOutputs = {
        "milestone":  str,                  # MILESTONE_M{n}.md content
        "roadmap":    str,                  # ROADMAP.md content (full)
        "briefings":  Dict[str, str],       # agent_id -> BRIEFING_*.md
        "paths":      Dict[str, str],       # logical key -> suggested path
    }

The ``paths`` map names the conventional location for each file under
``docs/`` — the caller can override but the convention is::

    paths["milestone"]     = "docs/milestones/MILESTONE_M{n}.md"
    paths["roadmap"]       = "docs/ROADMAP.md"
    paths["briefings"]["backend"] = "docs/briefings/BRIEFING_M{n}_backend.md"
    ...
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

__all__ = [
    "AuthoringOutputs",
    "author_all",
    "build_milestone_doc",
    "build_briefing_doc",
    "append_milestone_to_roadmap",
    "BRIEFING_ATTENDEES",
]


# Default attendee set the briefings cover. Mirrors EXPECTED_SECTIONS in
# run_kickoff.py — kept as a local constant so authoring stays decoupled
# (zero import from the rest of kickoff).
BRIEFING_ATTENDEES = ("backend", "frontend", "verifier")


# Outputs are a plain dict at the API boundary (avoid TypedDict so this
# module can be imported in older runtimes without typing_extensions).
AuthoringOutputs = Dict[str, Any]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def author_all(
    synthesis: Mapping[str, Any],
    *,
    project_name: Optional[str] = None,
    prior_roadmap_md: Optional[str] = None,
    attendees: Optional[Iterable[str]] = None,
    now: Optional[datetime] = None,
) -> AuthoringOutputs:
    """Synthesize all three artifact families from a finalized kickoff.

    Args:
        synthesis: A ready synthesis_result (the dict returned by
            ``run_kickoff.try_synthesize`` with status="ready", or the
            equivalent shape produced post-finalize). Must carry at
            minimum ``milestone_index``, ``contract``, ``task_tree``,
            and ``predicates``. ``roadmap`` is preferred when present.
        project_name: Human-readable project name for the doc headers.
            Defaults to "Project" when omitted.
        prior_roadmap_md: Existing ROADMAP.md text (if any) — new
            milestone is appended; prior content preserved verbatim.
        attendees: Per-agent briefings to author. Defaults to
            :data:`BRIEFING_ATTENDEES`.
        now: Optional override for the timestamp embedded in the docs.
            Defaults to ``datetime.now(timezone.utc)``. Allows
            deterministic tests.

    Returns:
        AuthoringOutputs dict with ``milestone``, ``roadmap``,
        ``briefings``, and ``paths``.
    """
    if not isinstance(synthesis, Mapping):
        raise ValueError("synthesis MUST be a Mapping (synthesis_result shape)")
    milestone_index = _require_milestone_index(synthesis)
    project = (project_name or "Project").strip() or "Project"
    stamp = now or datetime.now(timezone.utc)
    attendees_list = list(attendees or BRIEFING_ATTENDEES)

    milestone_md = build_milestone_doc(
        synthesis, project_name=project, now=stamp,
    )
    roadmap_md = append_milestone_to_roadmap(
        prior_roadmap_md or "", synthesis,
        project_name=project, now=stamp,
    )
    briefings: Dict[str, str] = {
        agent_id: build_briefing_doc(
            synthesis, agent_id,
            project_name=project, now=stamp,
        )
        for agent_id in attendees_list
    }
    paths = _suggested_paths(milestone_index, attendees_list)
    return {
        "milestone": milestone_md,
        "roadmap": roadmap_md,
        "briefings": briefings,
        "paths": paths,
    }


def build_milestone_doc(
    synthesis: Mapping[str, Any],
    *,
    project_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """Generate the canonical MILESTONE_M{n}.md content."""
    milestone_index = _require_milestone_index(synthesis)
    project = (project_name or "Project").strip() or "Project"
    stamp = now or datetime.now(timezone.utc)
    contract = synthesis.get("contract") or {}
    task_tree = list(synthesis.get("task_tree") or [])
    predicates = list(synthesis.get("predicates") or [])
    roadmap_block = synthesis.get("roadmap") or {}
    feature_inventory = roadmap_block.get("feature_inventory") or {}
    done_def = list(roadmap_block.get("done_def") or [])

    lines: List[str] = []
    lines.append(f"# Milestone M{milestone_index} — {project}")
    lines.append("")
    lines.append(f"_Authored {_fmt_stamp(stamp)} by the kickoff driver_")
    lines.append("")
    lines.append("> This file is the human-readable mirror of the machine-readable")
    lines.append("> kickoff contract. Source of truth: the meeting page decisions +")
    lines.append("> `synthesis_result`. Regenerated on every kickoff finalize.")
    lines.append("")

    # --- Contract ---
    lines.append("## Contract")
    lines.append("")
    endpoints = list(contract.get("endpoints") or [])
    if endpoints:
        lines.append("### API endpoints")
        lines.append("")
        lines.append("| Method | Path | Auth | Response key |")
        lines.append("|---|---|---|---|")
        for ep in endpoints:
            if not isinstance(ep, Mapping):
                continue
            method = str(ep.get("method") or "?").upper()
            path = str(ep.get("path") or "?")
            auth_required = ep.get("auth_required")
            auth_str = "✓" if auth_required else "—"
            rkey = str(ep.get("response_key") or "—")
            lines.append(f"| `{method}` | `{path}` | {auth_str} | `{rkey}` |")
        lines.append("")
    else:
        lines.append("_No endpoints declared._")
        lines.append("")

    data_model = contract.get("data_model") or {}
    tables = list(data_model.get("tables") or []) if isinstance(data_model, Mapping) else []
    if tables:
        lines.append("### Data model")
        lines.append("")
        for t in tables:
            if not isinstance(t, Mapping):
                continue
            tname = str(t.get("name") or "?")
            cols = list(t.get("columns") or [])
            lines.append(f"- **`{tname}`**")
            for c in cols:
                if not isinstance(c, Mapping):
                    continue
                cname = str(c.get("name") or "?")
                ctype = str(c.get("type") or "?")
                lines.append(f"  - `{cname}`: `{ctype}`")
        lines.append("")

    auth = contract.get("auth") or {}
    if isinstance(auth, Mapping) and auth:
        lines.append("### Auth")
        lines.append("")
        for k, v in auth.items():
            lines.append(f"- **{k}**: `{v}`")
        lines.append("")

    # --- Feature inventory ---
    if isinstance(feature_inventory, Mapping) and feature_inventory:
        lines.append("## Feature inventory")
        lines.append("")
        entities = list(feature_inventory.get("entities") or [])
        flows = list(feature_inventory.get("flows") or [])
        if entities:
            lines.append("**Entities**: " + ", ".join(f"`{e}`" for e in entities))
            lines.append("")
        if flows:
            lines.append("**Flows**: " + ", ".join(f"`{f}`" for f in flows))
            lines.append("")
        if not entities and not flows:
            # Non-canonical shape (per-feature dict) — render verbatim.
            for k, v in feature_inventory.items():
                lines.append(f"- **{k}**: {_inline(v)}")
            lines.append("")

    # --- Task tree ---
    if task_tree:
        lines.append("## Task tree")
        lines.append("")
        lines.append("| ID | Owner | Kind | Summary |")
        lines.append("|---|---|---|---|")
        for t in task_tree:
            if not isinstance(t, Mapping):
                continue
            tid = str(t.get("id") or "?")
            owner = str(t.get("owner") or "?")
            kind = str(t.get("kind") or "?")
            summary = str(t.get("summary") or t.get("title") or "")
            lines.append(f"| `{tid}` | `{owner}` | `{kind}` | {summary} |")
        lines.append("")

    # --- Acceptance predicates ---
    if predicates:
        lines.append("## Acceptance predicates")
        lines.append("")
        for p in predicates:
            if not isinstance(p, Mapping):
                continue
            pid = str(p.get("id") or "?")
            flow = str(p.get("flow") or "?")
            form = p.get("form") or {}
            kind = str(form.get("kind") if isinstance(form, Mapping) else "?")
            lines.append(f"- **`{pid}`** (`{kind}`) — flow `{flow}`")
        lines.append("")

    # --- Definition of done ---
    if done_def:
        lines.append("## Definition of done")
        lines.append("")
        for d in done_def:
            lines.append(f"- {d}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_briefing_doc(
    synthesis: Mapping[str, Any],
    agent_id: str,
    *,
    project_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """Per-agent marching orders for the milestone. Only the slice of
    the synthesis the agent owns gets included — keeps each briefing
    short and on-task.

    The slice rules (mirror the round 8e.1 ownership split):

      backend  → endpoints + data_model + auth + tasks owned by backend
      frontend → screens/pages + user_flows + tasks owned by frontend
      verifier → predicates + tasks owned by verifier

    Falls back gracefully: if an agent owns nothing in the synthesis,
    the briefing renders a "no work assigned this milestone" stub so
    the file still lands (audit trail of who-saw-what).
    """
    milestone_index = _require_milestone_index(synthesis)
    project = (project_name or "Project").strip() or "Project"
    stamp = now or datetime.now(timezone.utc)
    agent = str(agent_id).strip()
    if not agent:
        raise ValueError("agent_id MUST be a non-empty string")

    contract = synthesis.get("contract") or {}
    task_tree = list(synthesis.get("task_tree") or [])
    predicates = list(synthesis.get("predicates") or [])
    roadmap = synthesis.get("roadmap") or {}
    frontend_drafts = roadmap.get("contract") or contract

    owned_tasks = [
        t for t in task_tree
        if isinstance(t, Mapping) and str(t.get("owner") or "").strip() == agent
    ]

    lines: List[str] = []
    lines.append(f"# M{milestone_index} Briefing — {agent} — {project}")
    lines.append("")
    lines.append(f"_Authored {_fmt_stamp(stamp)} by the kickoff driver_")
    lines.append("")
    lines.append(f"This is your slice of the M{milestone_index} contract. The full")
    lines.append(f"milestone spec lives at `docs/milestones/MILESTONE_M{milestone_index}.md`.")
    lines.append("")

    if agent == "backend":
        _append_backend_briefing(lines, contract)
    elif agent == "frontend":
        _append_frontend_briefing(lines, contract, frontend_drafts, roadmap)
    elif agent == "verifier":
        _append_verifier_briefing(lines, predicates)
    else:
        # Unknown agent — render a generic "your slice" stub.
        lines.append(f"## Slice for `{agent}`")
        lines.append("")
        lines.append(f"No specialized briefing template for agent `{agent}`.")
        lines.append("Refer to the full milestone spec for context.")
        lines.append("")

    # --- Tasks owned by this agent ---
    lines.append("## Your tasks")
    lines.append("")
    if owned_tasks:
        lines.append("| ID | Kind | Summary |")
        lines.append("|---|---|---|")
        for t in owned_tasks:
            tid = str(t.get("id") or "?")
            kind = str(t.get("kind") or "?")
            summary = str(t.get("summary") or t.get("title") or "")
            lines.append(f"| `{tid}` | `{kind}` | {summary} |")
        lines.append("")
    else:
        lines.append(f"_No tasks in the M{milestone_index} task_tree are owned by `{agent}`._")
        lines.append(f"_(If this is a mistake, surface a comment on the meeting page.)_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def append_milestone_to_roadmap(
    prior_roadmap_md: str,
    synthesis: Mapping[str, Any],
    *,
    project_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """Append the new milestone section to ROADMAP.md.

    The function is idempotent in the common case: if the prior ROADMAP
    already contains a section for this milestone (header line ``## M{n}``),
    that section is REPLACED rather than duplicated, so a re-finalize
    overwrites cleanly. Other milestones are preserved verbatim.
    """
    milestone_index = _require_milestone_index(synthesis)
    project = (project_name or "Project").strip() or "Project"
    stamp = now or datetime.now(timezone.utc)
    new_section = _build_roadmap_section(synthesis, project, stamp, milestone_index)

    if not prior_roadmap_md.strip():
        # Fresh roadmap — write the canonical header + this milestone.
        header_lines = [
            f"# Roadmap — {project}",
            "",
            "_Cumulative milestone plan. Each kickoff finalize appends or",
            "rewrites the corresponding `## M{n}` section here._",
            "",
        ]
        return "\n".join(header_lines) + new_section + "\n"

    # Replace existing M{n} section in-place (if present); else append.
    section_header = f"## M{milestone_index}"
    out_lines: List[str] = []
    in_target = False
    skipping = False
    inserted = False
    for line in prior_roadmap_md.splitlines():
        if line.startswith(section_header) and not in_target:
            # Replace the prior block. Emit the new section content,
            # then skip until the next `## M*` header (or EOF).
            in_target = True
            skipping = True
            inserted = True
            out_lines.append(new_section.rstrip())
            continue
        if skipping:
            # Stop skipping when we hit another `## M*` header.
            if line.startswith("## M") and not line.startswith(section_header):
                skipping = False
                in_target = False
                out_lines.append(line)
                continue
            # Otherwise keep skipping.
            continue
        out_lines.append(line)
    if not inserted:
        # Append a fresh section.
        if out_lines and out_lines[-1].strip():
            out_lines.append("")
        out_lines.append(new_section.rstrip())
    out = "\n".join(out_lines)
    if not out.endswith("\n"):
        out += "\n"
    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _require_milestone_index(synthesis: Mapping[str, Any]) -> int:
    raw = synthesis.get("milestone_index")
    if not isinstance(raw, int) or raw < 0:
        raise ValueError(
            "synthesis MUST carry a non-negative int 'milestone_index' "
            f"(got {raw!r})"
        )
    return raw


def _fmt_stamp(stamp: datetime) -> str:
    """ISO 8601 timestamp with explicit UTC marker.

    Round 8h adversarial-review follow-up: the prior impl had the
    ternary inverted — it appended ``"Z"`` only when ``tzinfo`` was
    None (a naive datetime), and dropped it for UTC-aware
    datetimes. The function is always called with
    ``datetime.now(timezone.utc)``-style values from ``author_all``,
    so the ``"Z"`` branch never fired and emitted output read as
    ``"2026-06-03T12:30:45+00:00"`` instead of the conventional
    ``"2026-06-03T12:30:45Z"``. Both are valid ISO 8601 but the
    ``Z`` form is what the existing test assertions implicitly expect
    via substring matching, and it's what downstream markdown
    consumers prefer.

    Behavior now: UTC-aware → ``...Z``. Other-tz-aware →
    ``...+HH:MM`` (full ISO offset). Naive → bare ISO with no
    suffix (no fake ``"Z"`` lie).
    """
    base = stamp.replace(microsecond=0).isoformat()
    if stamp.tzinfo is None:
        return base
    if stamp.utcoffset() == timedelta(0):
        # Replace explicit "+00:00" tail (Python's UTC isoformat) with the
        # conventional "Z" abbreviation.
        if base.endswith("+00:00"):
            return base[: -len("+00:00")] + "Z"
        return base + "Z"
    return base


def _inline(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return ", ".join(f"{k}: {_inline(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_inline(v) for v in value)
    return str(value)


def _suggested_paths(milestone_index: int, attendees: Iterable[str]) -> Dict[str, Any]:
    return {
        "milestone": f"docs/milestones/MILESTONE_M{milestone_index}.md",
        "roadmap": "docs/ROADMAP.md",
        "briefings": {
            agent_id: f"docs/briefings/BRIEFING_M{milestone_index}_{agent_id}.md"
            for agent_id in attendees
        },
    }


def _build_roadmap_section(
    synthesis: Mapping[str, Any],
    project: str,
    stamp: datetime,
    milestone_index: int,
) -> str:
    contract = synthesis.get("contract") or {}
    task_tree = list(synthesis.get("task_tree") or [])
    predicates = list(synthesis.get("predicates") or [])
    endpoints = list(contract.get("endpoints") or [])
    data_model = contract.get("data_model") or {}
    tables = list(data_model.get("tables") or []) if isinstance(data_model, Mapping) else []
    lines: List[str] = []
    lines.append(f"## M{milestone_index}")
    lines.append("")
    lines.append(f"_Finalized {_fmt_stamp(stamp)} — see `docs/milestones/MILESTONE_M{milestone_index}.md` for the full spec._")
    lines.append("")
    lines.append(f"- **Endpoints**: {len(endpoints)}")
    lines.append(f"- **Tables**: {len(tables)}")
    lines.append(f"- **Tasks**: {len(task_tree)}")
    lines.append(f"- **Acceptance predicates**: {len(predicates)}")
    return "\n".join(lines) + "\n"


def _append_backend_briefing(
    lines: List[str], contract: Mapping[str, Any],
) -> None:
    endpoints = list(contract.get("endpoints") or [])
    tables = []
    data_model = contract.get("data_model") or {}
    if isinstance(data_model, Mapping):
        tables = list(data_model.get("tables") or [])
    lines.append("## API endpoints to implement")
    lines.append("")
    if endpoints:
        for ep in endpoints:
            if not isinstance(ep, Mapping):
                continue
            method = str(ep.get("method") or "?").upper()
            path = str(ep.get("path") or "?")
            auth = "auth required" if ep.get("auth_required") else "open"
            lines.append(f"- `{method} {path}` ({auth})")
    else:
        lines.append("_No endpoints declared._")
    lines.append("")
    lines.append("## Tables to implement")
    lines.append("")
    if tables:
        for t in tables:
            if not isinstance(t, Mapping):
                continue
            lines.append(f"- `{t.get('name', '?')}`")
    else:
        lines.append("_No tables declared._")
    lines.append("")


def _append_frontend_briefing(
    lines: List[str],
    contract: Mapping[str, Any],
    drafts_contract: Mapping[str, Any],
    roadmap: Mapping[str, Any],
) -> None:
    # Pull user_flows and screens from the roadmap snapshot if available
    # (the synthesizer doesn't carry them in `contract`).
    fe_block = (roadmap.get("frontend") if isinstance(roadmap, Mapping) else None) or {}
    user_flows = list(fe_block.get("user_flows") or [])
    screens = list(fe_block.get("screens") or []) or list(fe_block.get("ui_pages") or [])
    lines.append("## Screens to implement")
    lines.append("")
    if screens:
        for s in screens:
            if isinstance(s, Mapping):
                sid = str(s.get("id") or "?")
                path = str(s.get("path") or s.get("route") or "?")
                lines.append(f"- `{sid}` (route `{path}`)")
    else:
        lines.append("_No screens declared in the kickoff snapshot. Refer to the full milestone spec for screen breakdown._")
    lines.append("")
    lines.append("## Critical user flows")
    lines.append("")
    if user_flows:
        for f in user_flows:
            if isinstance(f, Mapping):
                fid = str(f.get("id") or "?")
                crit = "critical" if f.get("critical") else "normal"
                lines.append(f"- `{fid}` ({crit})")
    else:
        lines.append("_No user_flows declared. Acceptance predicates may still constrain expected behavior — see your tasks below._")
    lines.append("")


def _append_verifier_briefing(
    lines: List[str], predicates: List[Mapping[str, Any]],
) -> None:
    lines.append("## Acceptance predicates to validate")
    lines.append("")
    if predicates:
        for p in predicates:
            if not isinstance(p, Mapping):
                continue
            pid = str(p.get("id") or "?")
            flow = str(p.get("flow") or "?")
            form = p.get("form") or {}
            kind = str(form.get("kind") if isinstance(form, Mapping) else "?")
            lines.append(f"- **`{pid}`** (`{kind}`) — covers flow `{flow}`")
    else:
        lines.append("_No predicates declared. Surface this on the meeting page if a critical_flow lacks coverage._")
    lines.append("")
