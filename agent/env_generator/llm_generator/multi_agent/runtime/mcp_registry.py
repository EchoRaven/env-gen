"""MCPRegistry — Model Context Protocol server / tool / consumer
registry, lifted out of ``RegistryHub`` per the hub-responsibility-split
plan (``docs/hub_responsibility_split_plan.md``, PR 4, rank 4).

Plain-module pattern (per plan §6 Q4): not a Hub. The reviewer's
decision rule was "the MCP domain has one cohesive job (track which
servers/tools are wired up and which files consume them) — adding
the full Hub framework (stores ownership / ``_emit`` / snapshot /
subscriptions) would be over-structuring". Same shape as PR 3's
``GateRegistry``.

What lives here:
  * ``register_mcp_server`` / ``get_mcp_servers``
  * ``register_mcp_tool`` / ``get_mcp_tools``
  * ``register_mcp_consumer`` / ``get_mcp_consumers``
  * The ``_VALID_MCP_TRANSPORTS`` constant.

Data persistence: the JSON store backing this surface
(``registryhub_mcp_registry.json``) stays owned by RegistryHub for
backward-compatibility — the file path doesn't change so existing
snapshots load cleanly. MCPRegistry receives the store handle at
init and mutates it; RegistryHub no longer carries the methods.

Event emission: the events stay tagged ``source_hub='registryhub'`` for
downstream listener compatibility during the delegate window. After
Phase E retires the RegistryHub delegates, the events still carry the
same source tag so external bus consumers don't need to rebind.
"""

from __future__ import annotations

import time
from typing import Any, Dict, FrozenSet, List, Optional


class MCPRegistry:
    """Owns MCP server / tool / consumer state via the
    ``registryhub_mcp_registry.json`` store. See module docstring for
    scope rationale."""

    # ------------------------------------------------------------------
    # Validation constants — kept here (not on RegistryHub) because their
    # only readers are the methods below. RegistryHub no longer needs them
    # once PR 4 lands.
    # ------------------------------------------------------------------
    _VALID_MCP_TRANSPORTS: FrozenSet[str] = frozenset({
        "stdio", "http", "sse", "websocket",
    })

    def __init__(
        self,
        *,
        registry_store: Any,
        eventhub: Any = None,
    ) -> None:
        """``registry_store`` is the JsonStore that RegistryHub previously
        held as ``self._mcp_registry``. ``eventhub`` is the same handle
        RegistryHub uses for emission; events stay tagged
        ``source_hub='registryhub'`` for downstream listener
        compatibility."""
        self._store = registry_store
        self._eventhub = eventhub

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _emit(
        self,
        event_type: str,
        payload: dict,
        recipients: Optional[List[str]] = None,
        priority: str = "normal",
    ) -> None:
        if self._eventhub:
            # Phase 4.1c: source_hub="registryhub" cross-hub authorship —
            # mcp_registry publishes under registryhub vocab. caller=
            # "mcp_registry" is admitted via the registryhub sentinel
            # allowlist in PHASE_4_1C_PUBLISH_SENTINELS.
            self._eventhub.publish_event(
                "registryhub", event_type, payload,
                recipients=recipients or [], priority=priority,
                caller="mcp_registry",
            )

    def _store_value(self) -> Dict[str, dict]:
        return self._store.value() or {}

    # ==================================================================
    # MCP server registry
    # ==================================================================
    def register_mcp_server(
        self,
        name: str,
        transport: str,
        endpoint: str,
        provider: str = "",
        agent: str = "",
        status: str = "defined",
    ) -> dict:
        if not isinstance(name, str) or not name.strip():
            return {"error": "server name must be non-empty"}
        if transport not in self._VALID_MCP_TRANSPORTS:
            return {"error": (
                f"transport must be one of "
                f"{sorted(self._VALID_MCP_TRANSPORTS)}"
            )}
        # Ownership: backend lane owns MCP server registration; the
        # orchestrator also registers it when the MCP server is a
        # deterministic projection of the registered endpoints (Phase 3c —
        # consistency-by-construction, mirrors registryhub.register_endpoint's
        # {backend, orchestrator} allowed_set). Consumer rows remain open by
        # design (register_mcp_consumer wrapper admits non-frontend lanes).
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="register_mcp_server",
            agent=agent,
            provider=provider,
            allowed_set={"backend", "orchestrator"},
            target_label="mcp_registry.register_mcp_server",
            error_extra=(
                "backend lane or orchestrator owns MCP server registration."
            ),
        )
        key = f"mcp:server:{name}"
        now = time.time()
        record = {
            "kind": "server",
            "name": name, "transport": transport, "endpoint": endpoint,
            "provider": provider, "status": status,
            "_updated_by": agent, "_updated_at": now,
        }
        self._store.update(
            lambda m: m.set(key, record, agent),
            change_info={"agent": agent},
        )
        self._emit("mcp_server_registered", record, recipients=[])
        return record

    def get_mcp_servers(self) -> Dict[str, dict]:
        return {
            v["name"]: v
            for v in self._store_value().values()
            if v.get("kind") == "server"
        }

    # ==================================================================
    # MCP tool registry
    # ==================================================================
    def register_mcp_tool(
        self,
        server_name: str,
        tool_name: str,
        schema: dict = None,
        provider: str = "",
        agent: str = "",
        status: str = "defined",
    ) -> dict:
        if server_name not in self.get_mcp_servers():
            return {"error": (
                f"mcp server not registered: {server_name!r} "
                f"(call register_mcp_server first)"
            )}
        if not isinstance(tool_name, str) or not tool_name.strip():
            return {"error": "tool_name must be non-empty"}
        # Ownership: backend lane owns MCP tool registration; the orchestrator
        # also registers tools projected 1:1 from the registered endpoints
        # (Phase 3c). Consumer rows stay open by design.
        from ._role_gate import require_allowed_actor
        require_allowed_actor(
            method_name="register_mcp_tool",
            agent=agent,
            provider=provider,
            allowed_set={"backend", "orchestrator"},
            target_label="mcp_registry.register_mcp_tool",
            error_extra=(
                "backend lane or orchestrator owns MCP tool registration."
            ),
        )
        key = f"mcp:tool:{server_name}:{tool_name}"
        now = time.time()
        record = {
            "kind": "tool",
            "server_name": server_name, "tool_name": tool_name,
            "schema": schema or {}, "provider": provider, "status": status,
            "_updated_by": agent, "_updated_at": now,
        }
        self._store.update(
            lambda m: m.set(key, record, agent),
            change_info={"agent": agent},
        )
        self._emit("mcp_tool_registered", record, recipients=[])
        return record

    def get_mcp_tools(self, server_name: str = None) -> Dict[str, dict]:
        out = {}
        for k, v in self._store_value().items():
            if v.get("kind") != "tool":
                continue
            if server_name is not None and v.get("server_name") != server_name:
                continue
            out[k] = v
        return out

    # ==================================================================
    # MCP consumer registry (which file uses which MCP tool)
    # ==================================================================
    def register_mcp_consumer(
        self,
        server_name: str,
        tool_name: str,
        file_path: str,
        agent: str = "",
    ) -> dict:
        tool_key = f"mcp:tool:{server_name}:{tool_name}"
        if tool_key not in self._store_value():
            return {"error": (
                f"mcp tool not registered: {server_name}/{tool_name}"
            )}
        key = f"mcp:consumer:{server_name}:{tool_name}:{file_path}:{agent}"
        now = time.time()
        record = {
            "kind": "consumer",
            "server_name": server_name, "tool_name": tool_name,
            "file_path": file_path, "agent": agent,
            "_updated_by": agent, "_updated_at": now,
        }
        self._store.update(
            lambda m: m.set(key, record, agent),
            change_info={"agent": agent},
        )
        return record

    def get_mcp_consumers(
        self,
        server_name: str = None,
        tool_name: str = None,
    ) -> List[dict]:
        out = []
        for v in self._store_value().values():
            if v.get("kind") != "consumer":
                continue
            if server_name is not None and v.get("server_name") != server_name:
                continue
            if tool_name is not None and v.get("tool_name") != tool_name:
                continue
            out.append(v)
        return out


__all__ = ["MCPRegistry"]
