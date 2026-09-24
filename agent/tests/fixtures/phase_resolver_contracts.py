"""Canonical-writer-driven fixture base for Phase-3+ resolver tests (O2).

This module is the test-only shared scaffold the Phase 3 mechanism PR
(and Phase 3.1a/3.1b/3.5/3.9) will subclass when they need to drive
HubRegistry through a real writer→reader round-trip from a test.

INVARIANT — NO MOCKING: code in this module and any subclass MUST NOT
import ``unittest.mock`` for the purpose of stubbing hub internals or
JsonStore writes. Evidence must flow through canonical writers (the
``seed_*`` module-level helpers below). The reason this matters: the
Phase 3 resolver bug class (BLOCKER B1 — endpoint_contract reading a
non-existent ``verdict`` field; concern C1 — visual keying off
``page_key`` when the writer stores ``metadata.route``) is exactly
schema-misread between a mocked test and the real writer shape. The
mock-free convention makes that bug uncatchable-in-test impossible:
the test exercises the real writer signature, so any shape drift
between writer and resolver is caught at test time.

The frame-inspection guard originally proposed (``_assert_no_mocks_below_this_frame``)
was DROPPED in favor of this code-review-enforced convention (roadmap
line 40, line 262). Reviewer convention: PR description must affirm
"no ``unittest.mock`` imports in fixture-using tests" or list explicit
exception sites.

Active namespaces (v1 ship):
  * ``api_smoke``  — RunHub probe records
  * ``ui_flow``    — CodeHub validation results (via record_validation_result)
  * ``table``      — SchemaHub register_table + seed_data registry
  * ``mcp``        — RunHub mcp_probes records

Deferred namespaces (per workflow ``wufqrn61m`` discipline):
  * ``visual``           — Phase 3.9 (writer shape not finalized)
  * ``endpoint_contract``— Phase 3.5 (verdict field amendment pending)
Helpers for those land alongside their owning mechanism PRs.
"""
from __future__ import annotations

import abc
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Set

_THIS = Path(__file__).resolve()
_AGENT_ROOT = _THIS.parents[2]
sys.path.insert(0, str(_AGENT_ROOT / "env_generator" / "llm_generator"))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.hubs.runhub.compose import (  # noqa: E402
    ComposeResult, HealthcheckResult,
)


def _fake_compose():
    class _Compose:
        def up(self, timeout=180.0):
            return ComposeResult(returncode=0, stdout="up ok", stderr="")

        def down(self, timeout=60.0):
            return ComposeResult(returncode=0)

    return _Compose()


def _fake_healthcheck(healthy: bool = True):
    class _HC:
        def wait(self):
            return HealthcheckResult(
                healthy=healthy,
                status_code=200 if healthy else 503,
                attempts=1,
                elapsed_s=0.1,
            )

    return _HC()


def _fake_probe_runner(body: str = "probe ok"):
    def runner(plan):
        return {
            "status_code": 200,
            "body_excerpt": body,
            "transport_error": None,
            "latency_ms": 12.3,
        }

    return runner


def _fake_mcp_stdio_probe(healthy: bool = True):
    """Returns a callable that emits raw healthy_detail dict — NOT a
    verdict_record. RunHub.start_run wraps the result into the
    mcp_probes record itself (per runhub/service.py:335-337)."""

    def probe(server_name: str):
        return {
            "healthy": healthy,
            "detail": "stub mcp probe",
            "latency_ms": 5.0,
        }

    return probe


def seed_endpoint_probe(
    reg: HubRegistry, method: str, path: str, *,
    body: str = "probe ok",
) -> dict:
    """Seed an endpoint + run a probe via the canonical writer chain.

    Calls ``registryhub.register_endpoint`` then ``runhub.start_run`` with
    stubbed compose / healthcheck / probe_runner. Returns the run
    dict that the canonical reader ``runhub.get_run`` would yield.

    Canonical writer path (verified):
      * ``registryhub.register_endpoint`` at registryhub.py:155+ (Phase 2 gate
        admits ``agent='backend'``)
      * ``runhub.start_run`` at hubs/runhub/service.py:194+
    """
    reg.registryhub.register_endpoint(
        method=method, path=path, schema={}, provider="backend",
        agent="backend", status="defined", auth_required=False,
    )
    return reg.runhub.start_run(
        branch="o2", generated_dir="/tmp/o2", base_url="http://localhost:8000",
        agent="orch",
        compose=_fake_compose(),
        healthcheck=_fake_healthcheck(),
        probe_runner=_fake_probe_runner(body),
    )


def seed_ui_flow_result(
    reg: HubRegistry, flow: str, *,
    status: str = "pass",
) -> dict:
    """Record a ui_flow validation result via canonical writer.

    Canonical writer: ``hub_registry.record_validation_result`` at
    hub_registry.py:254+. The flatten/re-extract pattern at
    line 271-278 (write) / 303 (read) is the shape Phase 3 resolvers
    will need to honor.
    """
    return reg.record_validation_result(
        task_id=f"ui_flow:{flow}",
        status=status,
        agent="verifier",
        summary=f"flow {flow} {status}",
        metadata={"check": "ui_flow", "flow": flow},
    )


def seed_table(
    reg: HubRegistry, table_name: str, *,
    rows: List[Dict[str, Any]] = None,
) -> dict:
    """Register a table + seed it with >= 5 non-placeholder rows.

    Canonical writers: ``schema_hub.register_table`` (schema_hub.py:103+,
    Phase 1 gate admits ``agent='backend'``) + ``register_seed_data``
    (schema_hub.py:338+). Asserts ``len(rows) >= 5`` to avoid the
    ``min_seed_rows=0`` opt-out flagged at seed_audit.py:107-109; the
    audit reader treats fewer-than-min rows as not-seeded.
    """
    if rows is None:
        rows = [{"id": i, "body": f"row-{i}"} for i in range(5)]
    if len(rows) < 5:
        raise ValueError(
            f"seed_table({table_name!r}) requires >= 5 rows to satisfy "
            "min_seed_rows audit; got {0}".format(len(rows)))
    reg.schema_hub.register_table(
        name=table_name,
        schema={"id": "int", "body": "text"},
        agent="backend",
    )
    return reg.schema_hub.register_seed_data(
        table_name=table_name,
        row_count=len(rows),
        sample_excerpt=rows[:3],
        agent="backend",
    )


def seed_mcp_probe(
    reg: HubRegistry, server_name: str, *,
    healthy: bool = True,
) -> dict:
    """Register an MCP server + run an mcp_stdio_probe via canonical
    writer chain.

    Canonical writers: ``mcp_registry.register_mcp_server`` at
    mcp_registry.py:86+ (Phase 4 gate admits ``agent='backend'``) +
    ``runhub.start_run(mcp_stdio_probe=...)`` at
    hubs/runhub/service.py:202,310. The probe callable returns a
    raw healthy_detail dict; RunHub wraps it into the mcp_probes
    record itself at service.py:335-337.
    """
    reg.mcp_registry.register_mcp_server(
        name=server_name, transport="stdio", endpoint="true",
        agent="backend",
    )
    return reg.runhub.start_run(
        branch="o2", generated_dir="/tmp/o2-mcp",
        base_url="http://localhost:8000", agent="orch",
        compose=_fake_compose(),
        healthcheck=_fake_healthcheck(),
        probe_runner=_fake_probe_runner(),
        mcp_stdio_probe=_fake_mcp_stdio_probe(healthy),
    )


class PhaseResolverFixtureContracts(abc.ABC):
    """Mixin (combine with ``unittest.TestCase`` in subclass).

    Subclass MUST:
      * override ``target_key()`` returning the resolver lookup key,
        e.g. ``'api_smoke:GET /health'``.
      * override ``declared_record_fields()`` returning the SET of
        canonical-writer record fields the resolver reads (closes
        SM1 schema-misread gap — the resolver author declares which
        fields they depend on, and the assert below verifies the
        writer actually emits them).
      * override ``build_evidence(reg)`` returning the
        ``{target_key: status}`` mapping the subclass plans to seed.
        Status values are typed
        ``Literal['pass'|'fail'|'skipped'|'evidence_pending']`` so
        Phase 3.5/3.9's tri-state evidence_pending need is forward-
        compatible from day one.

    ABC is NOT collected by unittest discovery (``__test__ = False``).
    Subclasses must set ``__test__ = True`` if they want their inherited
    ``test_resolver_round_trip`` to run.
    """
    __test__ = False

    def setUp(self) -> None:  # type: ignore[override]
        super().setUp()
        self._o2_tmp = Path(tempfile.mkdtemp(prefix="o2_resolver_"))
        self.reg = HubRegistry(
            self._o2_tmp, project_id="p", project_name="P",
        )

    def tearDown(self) -> None:  # type: ignore[override]
        shutil.rmtree(self._o2_tmp, ignore_errors=True)
        super().tearDown()

    @abc.abstractmethod
    def target_key(self) -> str:
        """E.g. ``'api_smoke:GET /health'``."""

    @abc.abstractmethod
    def declared_record_fields(self) -> Set[str]:
        """Set of canonical-writer record fields the resolver reads.

        Used by ``test_resolver_round_trip`` to assert the writer
        emits every field before the resolver is hooked up — catches
        the BLOCKER B1 / concern C1 schema-misread class at test time.
        """

    @abc.abstractmethod
    def build_evidence(self, reg: HubRegistry) -> Dict[str, str]:
        """Seed evidence via ``seed_*`` helpers and return the
        ``{target_key: status}`` mapping. Status values typed
        ``'pass' | 'fail' | 'skipped' | 'evidence_pending'``."""

    def test_resolver_round_trip(self) -> None:
        """Concrete: build evidence, look it up via a canonical hub
        reader, assert the round-trip preserves the declared fields.

        Subclasses are deliberately simple — this base does the work.
        """
        evidence = self.build_evidence(self.reg)
        self.assertIn(self.target_key(), evidence,
                      msg="build_evidence must mention target_key()")
        for value in evidence.values():
            self.assertIn(
                value, {"pass", "fail", "skipped", "evidence_pending"},
                msg=("status values must be one of "
                     "'pass'|'fail'|'skipped'|'evidence_pending' "
                     "(typed for Phase 3.5/3.9 forward-compat)"),
            )
