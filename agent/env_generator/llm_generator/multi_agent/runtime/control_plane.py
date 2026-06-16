"""The fixed tenant/health control-plane contract (deterministic).

Every generated env carries the same control surface (mandated by the backend
prompt's <server_template> + success criteria): a healthcheck, the tenant
control endpoints the test harness drives, and a factory/scoped reset. These are
FIXED — the same method+path in every env — so the orchestrator registers them
in RegistryHub under actor='orchestrator', tagged ``kind='infra'``.

Why register them rather than exempt them (the old ``_INFRA`` path-prefix hack):
consistency-by-construction. With the auth/oauth surface (oauth_scaffold) and the
spine tables (database_scaffold) also registered, the RegistryHub contract is
COMPLETE — a frontend call to ``/api/v1/reset`` or ``/auth/login`` matches a real
registration, so the delivery gate's "frontend calls an unregistered endpoint"
check needs no hardcoded exemption list. ``kind='infra'`` tells the frontend's
response_key-keyed api.js generator to SKIP them (they are not business
endpoints; the harness — not the UI service layer — drives them).
"""

from __future__ import annotations

from typing import Any, Dict, List


CONTROL_SURFACE_ENDPOINTS: List[Dict[str, Any]] = [
    {"method": "GET", "path": "/health", "kind": "infra", "auth_required": False,
     "summary": "Liveness probe → {status: healthy}."},
    {"method": "POST", "path": "/api/v1/admin/init-tenant", "kind": "infra", "auth_required": False,
     "summary": "Idempotently create a tenant (X-Tenant-Id header); harness-driven."},
    {"method": "POST", "path": "/api/v1/reset", "kind": "infra", "auth_required": False,
     "summary": "Reset: scoped (X-Tenant-Id → that tenant's business rows) or factory (no header)."},
    {"method": "GET", "path": "/api/v1/tenants", "kind": "infra", "auth_required": False,
     "summary": "List tenants → {items: [{id}]}."},
    {"method": "POST", "path": "/api/v1/tenants", "kind": "infra", "auth_required": False,
     "summary": "Create a tenant → {id}."},
    {"method": "DELETE", "path": "/api/v1/tenants/{tenant_id}", "kind": "infra", "auth_required": False,
     "summary": "Delete a tenant (refuse 'default'); ON DELETE CASCADE wipes its rows."},
]


__all__ = ["CONTROL_SURFACE_ENDPOINTS"]
