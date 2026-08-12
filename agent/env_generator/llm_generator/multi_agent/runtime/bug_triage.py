"""Owning-agent resolution helpers for the Bug Triage Orchestrator (Cutover 10).

Pure functions over HubRegistry — given a bug's evidence (endpoint, table, file
paths), return the agent that owns the affected contract. The Bug Triage
Orchestrator agent uses these to decide who gets the remediation task.

Resolution priority (when multiple artifacts are present):
  1. affected_endpoint -> RegistryHub provider
  2. affected_table    -> RegistryHub provider
  3. affected_files[0] -> file-path heuristic (backend/frontend/database)
"""

from __future__ import annotations

from typing import Optional

# #626 — MATCH A PATH SEGMENT, NOT A PREFIX ANCHORED AT POSITION 0.
# This was a tuple of ``startswith`` prefixes ("backend/", "frontend/", …). Every generated
# project nests its code under ``app/``, so ``app/frontend/src/pages/TitleDetailPage.jsx`` does
# not start with "frontend/" and the resolver returned None for a path that names its owner
# plainly. Measured over 40 runs: of the 69 P0 bugs left UNASSIGNED, 55 carry usable
# ``affected_files`` and the prefix rule routed **0** of them; segment matching routes **44**
# (33 frontend, 11 backend).
#
# An unassigned bug is nobody's job by construction — those 69 sat a median of 46 minutes and
# the run ended with them still open, in runs that released. Segment equality (not substring)
# so a file named ``BackendStatus.jsx`` cannot masquerade as the backend lane, and first-match
# so ``app/frontend/src/db/x.js`` belongs to the frontend, not the database.
_LANE_BY_PATH_SEGMENT = {
    "backend": "backend",
    "frontend": "frontend",
    "database": "database",
    "migrations": "database",
    "db": "database",
}


def _registryhub_endpoints(registry) -> dict:
    """Return RegistryHub endpoint dict, tolerating either list_endpoints or get_endpoints."""
    registryhub = registry.registryhub
    if hasattr(registryhub, "list_endpoints"):
        return registryhub.list_endpoints() or {}
    if hasattr(registryhub, "get_endpoints"):
        return registryhub.get_endpoints() or {}
    return {}


def find_owning_agent_for_endpoint(registry, method: str, path: str) -> Optional[str]:
    method = (method or "").upper()
    for ep in _registryhub_endpoints(registry).values():
        if (ep.get("method") or "").upper() == method and ep.get("path") == path:
            owner = ep.get("provider") or None
            return owner or None
    return None


def find_owning_agent_for_table(registry, table_name: str) -> Optional[str]:
    schema_hub = getattr(registry, "schema_hub", None)
    if schema_hub is None:
        return None
    table = schema_hub.get_table(table_name)
    if table:
        return table.get("provider") or None
    tables = schema_hub.list_tables() or {}
    table = tables.get(table_name)
    if table:
        return table.get("provider") or None
    return None


def find_owning_agent_for_file(file_path: str) -> Optional[str]:
    """#626: the owning lane is whichever lane NAMES a segment of the path, wherever it sits."""
    for segment in (file_path or "").replace("\\", "/").split("/"):
        owner = _LANE_BY_PATH_SEGMENT.get(segment.strip().lower())
        if owner:
            return owner
    return None


def resolve_owning_agent(registry, artifacts: dict) -> Optional[str]:
    """Given a bug's `bug_artifacts` payload, return the owning agent, or None."""
    artifacts = artifacts or {}

    endpoint = artifacts.get("affected_endpoint")
    if endpoint and " " in endpoint:
        method, _, path = endpoint.partition(" ")
        owner = find_owning_agent_for_endpoint(registry, method, path)
        if owner:
            return owner

    table = artifacts.get("affected_table")
    if table:
        owner = find_owning_agent_for_table(registry, table)
        if owner:
            return owner

    for path in (artifacts.get("affected_files") or []):
        owner = find_owning_agent_for_file(path)
        if owner:
            return owner

    return None


__all__ = [
    "find_owning_agent_for_endpoint",
    "find_owning_agent_for_table",
    "find_owning_agent_for_file",
    "resolve_owning_agent",
]
