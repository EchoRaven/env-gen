"""Role-ownership gate helpers for hub write sites.

Two idioms shared by every authorship gate in the runtime hubs:

* ``require_allowed_actor`` — ALLOWLIST: caller's identity must be in a
  named set. Used by schema_hub.register_table / registryhub.register_endpoint
  / mcp_registry.register_mcp_server / gate_registry.submit_*_review /
  story_hub.register_story / etc.
* ``require_runtime_actor`` — RUNTIME-ONLY: caller's identity must equal
  a single runtime name. Used by RunHub.record_probe.

Both gates preserve the empty-actor fallthrough — system / test / HTTP
paths that pass no agent identity are admitted without raising. Only
EXPLICIT non-allowed actors raise.
"""

from __future__ import annotations

from typing import Iterable, Optional


__all__ = [
    "require_allowed_actor",
    "require_runtime_actor",
]


def require_allowed_actor(
    method_name: str,
    agent: Optional[str],
    provider: Optional[str],
    allowed_set: Iterable[str],
    *,
    target_label: Optional[str] = None,
    error_extra: str = "",
) -> None:
    """Raise ``PermissionError`` if an explicit non-allowed actor wrote.

    ``actor_id = (agent or provider or "").strip().lower()``.
    Empty actor → return (system / test fallthrough).
    ``actor_id`` in ``allowed_set`` → return. Otherwise raise.
    """
    actor_id = (agent or provider or "").strip().lower()
    if not actor_id:
        return
    allowed = set(allowed_set)
    label = target_label or method_name
    if actor_id in allowed:
        return
    extra = (" " + error_extra) if error_extra else ""
    raise PermissionError(
        f"{method_name}: {label} is restricted to {sorted(allowed)}; "
        f"got actor={actor_id!r}.{extra}"
    )


def require_runtime_actor(
    method_name: str,
    agent: Optional[str],
    runtime_name: str,
    *,
    target_label: Optional[str] = None,
    error_extra: str = "",
) -> None:
    """Raise ``PermissionError`` if an explicit non-runtime actor wrote.

    Admits exactly one named actor (the lowercased ``runtime_name``).
    Empty actor → return; matching actor → return; otherwise raise.
    """
    actor_id = (agent or "").strip().lower()
    if not actor_id:
        return
    runtime_id = runtime_name.strip().lower()
    label = target_label or method_name
    if actor_id == runtime_id:
        return
    extra = (" " + error_extra) if error_extra else ""
    raise PermissionError(
        f"{method_name}: {label} is restricted to the {runtime_id!r} "
        f"runtime only; got actor={actor_id!r}.{extra}"
    )
