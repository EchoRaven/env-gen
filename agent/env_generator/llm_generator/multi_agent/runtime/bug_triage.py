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

# Path-prefix heuristic for files not covered by RegistryHub registrations.
_FILE_PREFIX_OWNERS = (
    ("backend/", "backend"),
    ("frontend/", "frontend"),
    ("database/", "database"),
    ("migrations/", "database"),
    ("db/", "database"),
)


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
    fp = (file_path or "").lstrip("/")
    for prefix, owner in _FILE_PREFIX_OWNERS:
        if fp.startswith(prefix):
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
