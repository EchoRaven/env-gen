"""is_business must exclude framework-owned control-surface/auth paths by PATH, not just
by the kind tag. A lane that DECLARES /api/v1/tenants (etc.) with no kind would otherwise
be REQUIRED for business_chain coverage — uncoverable by the verifier → permanent
stuck-abort (outlook M2 business_chain_api_coverage, 2026-06-29)."""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.lifecycle import is_business  # noqa: E402


def _ep(method, path, **md):
    return {"method": method, "path": path, "metadata": md}


def test_control_surface_excluded_even_without_kind_tag():
    # NO kind tag (the lane declared them as plain endpoints) — still NOT business.
    for p in ("/api/v1/tenants", "/api/v1/tenants/{tenant_id}", "/api/v1/reset",
              "/api/v1/admin/init-tenant", "/health"):
        assert is_business(_ep("GET", p)) is False, p


def test_auth_oauth_paths_excluded():
    for p in ("/auth/register", "/auth/login", "/api/auth/me", "/oauth/token"):
        assert is_business(_ep("POST", p)) is False, p


def test_real_business_endpoints_still_business():
    for p in ("/api/messages", "/api/messages/{id}", "/api/projects/{id}/tasks",
              "/api/notes", "/api/calendars", "/api/messages/search"):
        assert is_business(_ep("GET", p)) is True, p


def test_kind_tagged_fixed_still_excluded():
    assert is_business(_ep("POST", "/api/messages", kind="infra")) is False
    assert is_business(_ep("POST", "/api/messages", kind="spine")) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
