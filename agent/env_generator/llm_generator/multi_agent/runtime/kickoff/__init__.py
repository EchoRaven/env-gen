"""Kickoff-meeting helpers (charter §8).

Pure-Python, hub-free helpers invoked by the future
`Orchestrator.run_kickoff` polling loop. Lives in its own sub-package
so orchestrator.py does not grow further (mirrors the
`runtime/observability/` precedent — the only other runtime
sub-package).

Each helper is a free function over already-loaded data — no hub
coupling, no I/O, no LLM. This module's __init__ re-exports the
public API so callers can write

    from multi_agent.runtime.kickoff import ready_set

without reaching into individual files.
"""

from .arbitration_table import (
    ARBITRATION_TABLE,
    arbitrate,
    resolve_conflict,
    tiebreak_by_alphabetical_agent_id,
)
from .facilitate import (
    FACILITATOR_ACTIONS,
    KICKOFF_MAX_ROUNDS,
    current_round,
    read_facilitator_decision,
    request_facilitation,
    request_revisions,
)
from .cross_check_suite import (
    api_vs_data_model,
    api_vs_frontend,
    run_cross_checks,
    test_strategy_coverage,
)
from .ready_set import ready_set
from .roadmap_validator import (
    ACCEPTANCE_PREDICATE_KINDS,
    validate_roadmap,
)
from .run_kickoff import (
    EXPECTED_SECTIONS,
    finalize_kickoff,
    start_kickoff,
    try_synthesize,
)

__all__ = [
    "ACCEPTANCE_PREDICATE_KINDS",
    "ARBITRATION_TABLE",
    "EXPECTED_SECTIONS",
    "FACILITATOR_ACTIONS",
    "KICKOFF_MAX_ROUNDS",
    "api_vs_data_model",
    "api_vs_frontend",
    "arbitrate",
    "current_round",
    "finalize_kickoff",
    "read_facilitator_decision",
    "ready_set",
    "request_facilitation",
    "request_revisions",
    "resolve_conflict",
    "run_cross_checks",
    "start_kickoff",
    "test_strategy_coverage",
    "tiebreak_by_alphabetical_agent_id",
    "try_synthesize",
    "validate_roadmap",
]
