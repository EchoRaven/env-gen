"""Pure-function `ready_set` helper for the kickoff polling loop.

WHY
---
The kickoff meeting (charter §5, plan §Step 4) dispatches per-agent
tasks whose dependencies have all been satisfied. The orchestrator's
run_kickoff loop polls the task tree on every tick and asks "which
tasks are ready to be claimed right now?". That predicate is pure —
it depends only on the task list shape, not on WorkHub state, the
event bus, or any LLM. Charter §8 explicitly demands that this
predicate live SEPARATE from the polling loop so orchestrator.py
does not grow further.

This module is the home of that predicate. It is intentionally
unaware of WorkHub: callers (orchestrator, tests, future agents)
pass in an already-loaded list of task dicts. WorkHub has its own
inline `claim_task` dep-resolution rule that uses the `'completed'`
terminology; this helper uses the kickoff-side terminology
(`'done'` for deps, `'pending'`/`'ready'` for self) so the two
surfaces stay decoupled. If a future caller wants to bridge them,
they normalise at the boundary — this module is the contract.

CONTRACT (data shape)
---------------------
A "task" is a Mapping with these required fields:

    {
        "id":         str,              # non-empty, globally unique within the input list
        "depends_on": list[str],        # 0+ task ids; each MUST appear as another task's "id"
        "status":     str,              # one of: "pending", "ready", "in_progress", "done",
                                        #         "failed", "cancelled" — the kickoff terminology
    }

Extra fields are allowed and ignored (forward-compatible with
WorkHub-shaped rows).

INVARIANT (what `ready_set` promises)
--------------------------------------
Return the ordered list of task ids `t.id` such that:

  (1) t.status in {"pending", "ready"}, AND
  (2) every dep_id in t.depends_on resolves to some task d in the
      input where d.status == "done".

The output preserves the input order of the matching tasks (so the
caller's deterministic seeding is honoured).

ERRORS (structured, raised — closed-by-construction)
----------------------------------------------------
Pure-function but raises `ValueError` for malformed input that cannot
be silently coerced. No phantom defaults, no fallback identities:

  * `ValueError("duplicate task id: <id>")` — input contains two tasks
    with the same id (the helper cannot disambiguate a dep reference).
  * `ValueError("orphan dependency: <task_id> -> <missing_dep_id>")` —
    a `depends_on` entry references a task id that does not appear
    anywhere in the input list.
  * `ValueError("dependency cycle detected: <a> -> <b> -> ... -> <a>")` —
    the dependency graph is not a DAG.
  * `ValueError("missing required field <field> on task <repr>")` — a
    task dict is missing `id`, `depends_on`, or `status`, or any of
    them is the wrong shape (id not str, depends_on not list, etc).

Pure: no I/O, no global state, no LLM, deterministic.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping


# Statuses recognised by the kickoff polling loop. Kept module-level so
# tests and callers can introspect (but NOT extend by mutation — the
# helper does not accept an override kwarg; the kickoff terminology is
# fixed by the charter).
_READY_STATUSES = frozenset({"pending", "ready"})
_DEP_SATISFIED_STATUSES = frozenset({"done"})


def ready_set(tasks: Iterable[Mapping[str, Any]]) -> List[str]:
    """Return the task ids whose deps are all satisfied and whose own status is ready.

    See module docstring for the full data-shape contract, invariant,
    and error catalogue. Returns a fresh list (caller may mutate).
    Output order = input order of matching tasks (deterministic).

    Empty input -> empty output (the only legal "no work" case).
    """

    # ---- Phase 1: validate shape and index by id (catches duplicates, missing fields). ----
    by_id: dict[str, Mapping[str, Any]] = {}
    ordered_ids: List[str] = []

    for task in tasks:
        if not isinstance(task, Mapping):
            raise ValueError(
                f"task must be a mapping; got {type(task).__name__}: {task!r}"
            )

        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"missing required field id on task {task!r}")

        depends_on = task.get("depends_on")
        if not isinstance(depends_on, list) or not all(
            isinstance(d, str) and d for d in depends_on
        ):
            raise ValueError(
                f"missing required field depends_on on task {task!r} "
                f"(must be a list of non-empty str ids)"
            )

        status = task.get("status")
        if not isinstance(status, str) or not status:
            raise ValueError(f"missing required field status on task {task!r}")

        if task_id in by_id:
            raise ValueError(f"duplicate task id: {task_id}")

        by_id[task_id] = task
        ordered_ids.append(task_id)

    # ---- Phase 2: orphan-dep detection. Every dep must resolve in the index. ----
    for task_id in ordered_ids:
        for dep_id in by_id[task_id]["depends_on"]:
            if dep_id not in by_id:
                raise ValueError(
                    f"orphan dependency: {task_id} -> {dep_id}"
                )

    # ---- Phase 3: cycle detection (DFS, three-colour). ----
    # WHITE = unvisited, GREY = on the current DFS stack, BLACK = fully explored.
    WHITE, GREY, BLACK = 0, 1, 2
    colour: dict[str, int] = {tid: WHITE for tid in ordered_ids}

    def _dfs(start: str) -> None:
        # Iterative DFS so deep dep chains don't blow Python's recursion limit.
        # Invariant: every node on `stack` is GREY and also on `path` in the
        # same order — push together, pop together.
        if colour[start] != WHITE:
            return
        colour[start] = GREY
        path: List[str] = [start]
        stack: List[tuple[str, int]] = [(start, 0)]
        while stack:
            node, child_idx = stack[-1]
            deps = by_id[node]["depends_on"]
            if child_idx < len(deps):
                stack[-1] = (node, child_idx + 1)
                next_node = deps[child_idx]
                if colour[next_node] == GREY:
                    # back-edge -> cycle. Slice `path` from the cycle's
                    # entry point and append the back-target for readability.
                    cycle_start = path.index(next_node)
                    cycle = path[cycle_start:] + [next_node]
                    raise ValueError(
                        f"dependency cycle detected: {' -> '.join(cycle)}"
                    )
                if colour[next_node] == WHITE:
                    colour[next_node] = GREY
                    path.append(next_node)
                    stack.append((next_node, 0))
                # BLACK -> already fully explored; skip.
            else:
                colour[node] = BLACK
                path.pop()
                stack.pop()

    for tid in ordered_ids:
        if colour[tid] == WHITE:
            _dfs(tid)

    # ---- Phase 4: select ready tasks. Deterministic = input order. ----
    out: List[str] = []
    for tid in ordered_ids:
        task = by_id[tid]
        if task["status"] not in _READY_STATUSES:
            continue
        if all(
            by_id[dep_id]["status"] in _DEP_SATISFIED_STATUSES
            for dep_id in task["depends_on"]
        ):
            out.append(tid)
    return out
