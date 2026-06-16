"""Kickoff conflict-arbitration table — deterministic, LLM-free.

Per ``docs/plan_kickoff_refactor.md`` Step 3 ("orchestrator
synthesizes"), once the kickoff cross-check suite reports a conflict
between two agents' drafts, the orchestrator MUST resolve it without
calling out to an LLM. Non-determinism here would re-introduce the
exact stall the kickoff refactor exists to kill — agents looping
on "who's right". The plan pins the resolution as a fixed authority
table:

    | Conflict                       | Authority                        |
    | ------------------------------ | -------------------------------- |
    | api shape vs frontend usage    | backend wins (frontend revises)  |
    | api shape vs data model        | backend wins (both sides)        |
    | test strategy coverage gap     | verifier always revises own      |
    | tiebreak (no rule applies)     | alphabetical agent_id            |

    Round 8e.1 dropped the legacy "ui pages vs user flows" row — after
    design+frontend merged, both ui_pages and user_flows live in
    frontend's section so the conflict is intra-section (the LLM's
    job to keep coherent) rather than cross-section arbitration.

This module ships that table verbatim plus the two-function contract
the task spec pinned (``resolve_conflict`` + ``tiebreak_by_alphabetical_agent_id``)
and a thin aggregator (``arbitrate``) that wraps the single-conflict
resolver in the same ``{ok: bool, items: [...]}`` shape the sibling
kickoff helpers return — so ``run_kickoff`` can wire the four helpers
together with one uniform short-circuit pattern.

Contract: ALL functions in this module are pure (no I/O, no LLM, no
hub coupling), deterministic (same inputs → same outputs, no time /
randomness / dict-iteration-order dependence), and total over the
documented input shape. Missing required fields raise
``ValueError`` — no phantom defaults, per the charter no-fallback
discipline.

Check-result data shape (the ONE shape this module commits to):

    {
        "id": "<conflict_id>",          # required, non-empty str
        "kind": "<check_kind>",         # required; one of ARBITRATION_TABLE keys
                                        # OR any other str (falls through to tiebreak)
        "agents": ["<agent_a>", "<agent_b>"],   # required; non-empty list of >=1 str
        # ...arbitrary extra fields are preserved + ignored
    }

The three pinned ``kind`` values (after round 8e.1 dropped
``ui_pages_vs_user_flows``):
``api_vs_frontend`` / ``api_vs_data_model`` / ``test_strategy_coverage``.
Anything else routes through ``tiebreak_by_alphabetical_agent_id(agents)``.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

# ARBITRATION_TABLE: {check_kind: (authority_agent, reviser_agent)}.
#
# The four entries are the four rows of plan §Step-3 verbatim. The
# tuple semantics are (authority, reviser) — i.e. "authority wins,
# reviser must update its draft to match". For the api_vs_data_model
# row the plan says "both sides revise" — backend remains authority
# but the reviser is also backend because backend's data_model draft
# is the canonical source for entity shape, so the api draft (also
# backend-owned) is what bends. For test_strategy_coverage the plan
# says "verifier always revises own" — verifier is both authority and
# reviser because the coverage gap is in its OWN draft and no other
# agent can author tests.
ARBITRATION_TABLE: Dict[str, Tuple[str, str]] = {
    "api_vs_frontend": ("backend", "frontend"),
    "api_vs_data_model": ("backend", "backend"),
    # Round 8e.1: ui_pages_vs_user_flows removed — design merged into
    # frontend; both fields are intra-section now (no arbitration).
    "test_strategy_coverage": ("verifier", "verifier"),
}


def tiebreak_by_alphabetical_agent_id(agents: Iterable[str]) -> str:
    """Pick the lexicographically-first agent_id as the reviser.

    The deterministic fallback when ``check_result['kind']`` does not
    match any row in ``ARBITRATION_TABLE``. Per plan §Step-3 the
    tiebreak rule is "alphabetical agent_id" — we treat the
    lexicographically-FIRST id as the loser (reviser) so two runs
    against the same conflict always elect the same side, with no
    dict-iteration-order or set-ordering dependence.

    Args:
        agents: iterable of agent_id strings (typically the
            ``agents`` list off a check_result). Must be non-empty
            and contain only non-empty strings.

    Returns:
        The alphabetically-first agent_id (the reviser).

    Raises:
        ValueError: if ``agents`` is empty or contains an
            empty / non-string element. No phantom defaults.
    """
    items = list(agents)
    if not items:
        raise ValueError(
            "tiebreak_by_alphabetical_agent_id: agents iterable is empty; "
            "caller must inject at least one agent_id (no phantom default)."
        )
    for ix, a in enumerate(items):
        if not isinstance(a, str) or not a:
            raise ValueError(
                f"tiebreak_by_alphabetical_agent_id: agents[{ix}] is empty "
                f"or non-string ({a!r}); caller must inject non-empty "
                "agent_ids (no phantom default)."
            )
    return sorted(items)[0]


def resolve_conflict(check_result: Mapping[str, Any]) -> str:
    """Return the reviser agent_id for a single cross-check conflict.

    Deterministic lookup against ``ARBITRATION_TABLE`` by
    ``check_result['kind']``. If the kind is registered, returns the
    pinned reviser; otherwise falls back to
    ``tiebreak_by_alphabetical_agent_id(check_result['agents'])``.

    Why pure + deterministic: the kickoff polling loop calls this
    inside its synthesis step. Any non-determinism here would let
    two agents flip-flop their drafts forever (the exact stall the
    kickoff refactor exists to kill). Same inputs → same output,
    always.

    Args:
        check_result: a Mapping matching the data shape documented in
            the module docstring. Required fields: ``id`` (non-empty
            str), ``kind`` (str), ``agents`` (non-empty list of
            non-empty str). Extra fields are ignored.

    Returns:
        The agent_id (str) that must revise its draft.

    Raises:
        ValueError: if any required field is missing or empty.
            No phantom defaults — caller MUST inject identity.
    """
    if not isinstance(check_result, Mapping):
        raise ValueError(
            "resolve_conflict: check_result must be a Mapping; got "
            f"{type(check_result).__name__}."
        )
    cid = check_result.get("id")
    if not isinstance(cid, str) or not cid:
        raise ValueError(
            "resolve_conflict: check_result['id'] missing or empty; "
            "caller must inject a stable conflict_id (no phantom default)."
        )
    kind = check_result.get("kind")
    if not isinstance(kind, str) or not kind:
        raise ValueError(
            f"resolve_conflict: check_result['kind'] missing or empty for "
            f"conflict {cid!r}; caller must inject the check_kind "
            "(no phantom default)."
        )
    agents = check_result.get("agents")
    if not isinstance(agents, (list, tuple)) or not agents:
        raise ValueError(
            f"resolve_conflict: check_result['agents'] missing or empty "
            f"for conflict {cid!r}; caller must inject at least one "
            "agent_id (no phantom default)."
        )
    if kind in ARBITRATION_TABLE:
        _, reviser = ARBITRATION_TABLE[kind]
        return reviser
    return tiebreak_by_alphabetical_agent_id(agents)


def arbitrate(conflicts: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Aggregate ``resolve_conflict`` over a batch of conflicts.

    Wraps the per-conflict resolver in the same ``{ok, items}`` shape
    the sibling kickoff helpers (``run_cross_checks``,
    ``validate_roadmap``) return, so ``run_kickoff`` can chain them
    uniformly: call helper, short-circuit on ``ok=False``.

    Determinism contract: input order of ``conflicts`` is preserved
    in ``items`` 1:1. ``ok`` is True iff every conflict resolved via
    the pinned ``ARBITRATION_TABLE`` (no tiebreak fallback used) —
    a tiebreak signals that the cross-check produced a ``kind``
    outside the v1 vocabulary, which the orchestrator should surface
    as a deferral, not silently accept.

    Args:
        conflicts: iterable of check_result Mappings (see module
            docstring for shape).

    Returns:
        ``{ok: bool, items: [{conflict_id, kind, reviser, source}, ...]}``
        where ``source`` ∈ {``"arbitration_table"``, ``"tiebreak"``}.

    Raises:
        ValueError: if any single conflict fails ``resolve_conflict``
            field validation. (Field-validation failures are caller
            bugs; tiebreak fallback is NOT a failure — it's a
            ``source="tiebreak"`` item with ``ok=False`` at the
            aggregate level.)
    """
    items: List[Dict[str, Any]] = []
    aggregate_ok = True
    for conflict in conflicts:
        reviser = resolve_conflict(conflict)  # raises on missing fields
        kind = conflict["kind"]  # safe — resolve_conflict validated
        source = "arbitration_table" if kind in ARBITRATION_TABLE else "tiebreak"
        if source == "tiebreak":
            aggregate_ok = False
        items.append(
            {
                "conflict_id": conflict["id"],
                "kind": kind,
                "reviser": reviser,
                "source": source,
            }
        )
    return {"ok": aggregate_ok, "items": items}
