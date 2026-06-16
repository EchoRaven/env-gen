"""Unit tests for the deterministic embedded-OAuth2-AS scaffold (Phase 3b).

The env IS the OAuth2 Authorization Server (zoom-style). Its three AS modules —
``jwt_manager.py`` (RSA keypair + RS256 sign + JWKS), ``oauth_store.py``
(psycopg3 store for users/clients/codes) and ``oauth_routes.py`` (authorize +
token + register + JWKS endpoints, PKCE S256) — are pure infrastructure: byte
identical for every generated env, zero business logic. So the runtime is the
SOLE owner of them, exactly like ``app/database/`` — closed-by-construction, no
LLM variance, always matching the tenancy spine in ``database_scaffold.py``.

This guards the projection: the emitter copies the locked templates into
``app/backend/`` and the contract markers the spine/main/store all agree on
(``app-oauth-key-1`` kid, ``app_sandbox_salt_2024`` password salt, ``sub`` ==
str(users.id)) are present and aligned with the database scaffold.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # .../agent
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from multi_agent.runtime.oauth_scaffold import (  # noqa: E402
    AS_MODULES,
    AS_CONTRACT_ENDPOINTS,
    write_oauth_as,
)


class WriteOAuthASTests(unittest.TestCase):
    def test_writes_three_as_modules_under_app_backend(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            result = write_oauth_as(out)

            be = out / "app" / "backend"
            for mod in ("jwt_manager.py", "oauth_store.py", "oauth_routes.py"):
                p = be / mod
                self.assertTrue(p.is_file(), f"missing {mod}")
            self.assertEqual(set(result["written"]), {
                str(be / "jwt_manager.py"),
                str(be / "oauth_store.py"),
                str(be / "oauth_routes.py"),
            })

    def test_emitted_modules_are_valid_python(self):
        # The templates ship as .py.tmpl so the test runner never imports them;
        # the emitter strips the suffix. Parse (not import) the emitted .py to
        # prove the projection produced syntactically valid modules.
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            write_oauth_as(out)
            be = out / "app" / "backend"
            for mod in ("jwt_manager.py", "oauth_store.py", "oauth_routes.py"):
                src = (be / mod).read_text(encoding="utf-8")
                compile(src, mod, "exec")  # raises SyntaxError on a bad emit

    def test_contract_markers_match_the_tenancy_spine(self):
        # Consistency-by-construction: the AS modules and database_scaffold's
        # spine must agree on the locked contract constants. If either side
        # drifts, the generated env can't mint/verify a token end-to-end.
        from multi_agent.runtime.database_scaffold import render_schema_sql

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            write_oauth_as(out)
            be = out / "app" / "backend"
            jwt_src = (be / "jwt_manager.py").read_text()
            store_src = (be / "oauth_store.py").read_text()
            routes_src = (be / "oauth_routes.py").read_text()
            spine = render_schema_sql({})

            # Signing key id is shared between the JWKS header and verifiers.
            self.assertIn("app-oauth-key-1", jwt_src)
            # Password salt must match between the store and (later) main.py.
            self.assertIn("app_sandbox_salt_2024", store_src)
            # The store reads exactly the spine's identity + oauth columns.
            self.assertIn("password_hash", store_src)
            self.assertIn("password_hash", spine)
            self.assertIn("WHERE email = %s AND tenant_id = %s", store_src)
            self.assertIn("UNIQUE (email, tenant_id)", spine)
            # PKCE S256 is enforced at /oauth/authorize and the column exists.
            self.assertIn("S256", routes_src)
            self.assertIn("code_challenge_method", spine)

    def test_register_provisions_tenant_before_user_insert(self):
        # 2026-06-13: ``users.tenant_id REFERENCES tenants(id)`` + only ``default``
        # seeded → a first-party register naming an unprovisioned tenant (e.g. a
        # verification chain's ``tenant_id="test_tenant"``) FK-violated and 409'd
        # ("could not register: insert ... violates foreign key"), blocking the
        # business_chain / milestone delivery forever. create_user must ensure the
        # tenant row exists before the user insert.
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            write_oauth_as(out)
            store_src = (out / "app" / "backend" / "oauth_store.py").read_text()
            self.assertIn("INSERT INTO tenants", store_src)
            self.assertIn("ON CONFLICT (id) DO NOTHING", store_src)
            # the tenant ensure must precede the users insert inside create_user
            tenant_at = store_src.find("INSERT INTO tenants")
            users_at = store_src.find("INSERT INTO users")
            self.assertTrue(0 < tenant_at < users_at,
                            "tenant provision must come before the users insert")

    def test_idempotent_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            write_oauth_as(out)
            write_oauth_as(out)  # must not raise on existing files
            be = out / "app" / "backend"
            self.assertTrue((be / "jwt_manager.py").is_file())

    def test_as_modules_manifest_is_the_three_infra_files(self):
        # AS_MODULES is the public manifest other layers key off (e.g. the
        # backend prompt's "do NOT author these" list).
        self.assertEqual(
            set(AS_MODULES),
            {"jwt_manager.py", "oauth_store.py", "oauth_routes.py"},
        )


class ASContractEndpointsTests(unittest.TestCase):
    """The AS contract surface registered into RegistryHub: well-formed, tagged
    auth|oauth (NOT business), and covering the routes oauth_routes.py mounts."""

    def test_endpoints_are_register_endpoint_shaped(self):
        for ep in AS_CONTRACT_ENDPOINTS:
            self.assertIn(ep["method"], {"GET", "POST", "PUT", "PATCH", "DELETE"})
            self.assertTrue(ep["path"].startswith("/"))
            self.assertIn(ep["kind"], {"auth", "oauth"})
            self.assertIn("auth_required", ep)

    def test_first_party_auth_endpoints_present(self):
        paths = {(e["method"], e["path"]) for e in AS_CONTRACT_ENDPOINTS}
        self.assertIn(("POST", "/auth/register"), paths)
        self.assertIn(("POST", "/auth/login"), paths)

    def test_oauth_protocol_endpoints_present(self):
        paths = {e["path"] for e in AS_CONTRACT_ENDPOINTS}
        for p in ("/oauth/authorize", "/oauth/token", "/oauth/register",
                  "/.well-known/jwks.json", "/.well-known/oauth-authorization-server"):
            self.assertIn(p, paths)

    def test_registered_routes_match_oauth_routes_template(self):
        # Drift gate: every /oauth/* + /.well-known/* route the runtime emits in
        # oauth_routes.py.tmpl must be registered (kind=oauth), and vice versa.
        from multi_agent.runtime.oauth_scaffold import render_oauth_module
        routes_src = render_oauth_module("oauth_routes.py")
        registered_oauth = {e["path"] for e in AS_CONTRACT_ENDPOINTS if e["kind"] == "oauth"}
        for path in registered_oauth:
            self.assertIn(path, routes_src,
                          f"registered oauth path {path} not found in oauth_routes.py template")


def _run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


class _CaptureHub:
    """Records register_table / register_endpoint calls for assertions."""

    def __init__(self):
        self.tables = []
        self.endpoints = []

    def register_table(self, **kw):
        self.tables.append(kw); return kw

    def register_endpoint(self, **kw):
        self.endpoints.append(kw); return kw


class _SeedStubOrchestrator:
    """Bind target for ``_seed_base_scaffold`` — holds a REAL CodeHub on
    output_dir so the test exercises the genuine commit-to-base path."""

    def __init__(self, output_dir):
        import logging
        from multi_agent.runtime.hubs.codehub.service import CodeHub

        class _Hubs:
            pass
        self.output_dir = Path(output_dir)
        self._logger = logging.getLogger("stub_seed")
        self.hubs = _Hubs()
        self.hubs.codehub = CodeHub(
            repo_root=self.output_dir, hub_dir=self.output_dir / ".hubs", eventhub=None,
        )


class _RegisterStubOrchestrator:
    def __init__(self):
        import logging

        class _Hubs:
            pass
        self._logger = logging.getLogger("stub_register")
        self.hubs = _Hubs()
        self.hubs.schema_hub = _CaptureHub()
        self.hubs.registryhub = _CaptureHub()


class SeedBaseScaffoldWiringTests(unittest.TestCase):
    def test_seed_emits_and_commits_the_three_modules_to_base(self):
        import shutil
        if not shutil.which("git"):
            self.skipTest("git not available")
        from multi_agent.orchestrator import Orchestrator
        with tempfile.TemporaryDirectory() as td:
            stub = _SeedStubOrchestrator(td)
            _run(Orchestrator._seed_base_scaffold(stub))
            be = Path(td) / "app" / "backend"
            for mod in ("jwt_manager.py", "oauth_store.py", "oauth_routes.py"):
                self.assertTrue((be / mod).is_file(), f"missing {mod}")
            # decisive: a worktree created after the seed inherits the modules.
            wt = stub.hubs.codehub.register_agent_worktree("backend")
            for mod in ("jwt_manager.py", "oauth_store.py", "oauth_routes.py"):
                self.assertTrue((wt / "app" / "backend" / mod).is_file(),
                                f"worktree missing inherited {mod}")


class RegisterContractSurfaceTests(unittest.TestCase):
    def test_registers_spine_tables_and_auth_oauth_endpoints(self):
        from multi_agent.orchestrator import Orchestrator
        from multi_agent.runtime.database_scaffold import SPINE_TABLE_RECORDS
        from multi_agent.runtime.oauth_scaffold import AS_CONTRACT_ENDPOINTS
        from multi_agent.runtime.control_plane import CONTROL_SURFACE_ENDPOINTS
        stub = _RegisterStubOrchestrator()
        Orchestrator._register_contract_surface(stub)

        reg_tables = {t["name"] for t in stub.hubs.schema_hub.tables}
        self.assertEqual(reg_tables, {r["name"] for r in SPINE_TABLE_RECORDS})
        # all spine tables registered by orchestrator, status=implemented
        for t in stub.hubs.schema_hub.tables:
            self.assertEqual(t["agent"], "orchestrator")
            self.assertEqual(t["status"], "implemented")

        # the COMPLETE fixed surface is registered: auth + oauth + infra control plane
        reg_eps = {(e["method"], e["path"]) for e in stub.hubs.registryhub.endpoints}
        expected = {(e["method"], e["path"]) for e in (*AS_CONTRACT_ENDPOINTS, *CONTROL_SURFACE_ENDPOINTS)}
        self.assertEqual(reg_eps, expected)
        # every fixed endpoint carries a kind tag so the frontend skips response_key.
        for e in stub.hubs.registryhub.endpoints:
            self.assertIn(e["kind"], {"auth", "oauth", "infra"})
            self.assertEqual(e["agent"], "orchestrator")
            self.assertEqual(e["status"], "implemented")


if __name__ == "__main__":
    unittest.main()
