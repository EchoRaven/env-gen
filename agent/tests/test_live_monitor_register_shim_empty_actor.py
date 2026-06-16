"""Live monitor HTTP shim empty-actor cleanup — register_endpoint /
register_table / register_consumer.

The Phase 4.5/4.6 callsite-cleanup (Step A `138cb475`) established that
HTTP shims in `live_monitor_server.py` should default `agent=""` so the
phase gates' empty-actor fallthrough kicks in, instead of `"ui_user"`
which is a phantom principal nobody is granted.

For the registryhub register-* shims this was a LIVE BUG at phase>=2.0:
  - register_endpoint Phase 2 gate {backend} REJECTS "ui_user" →
    every UI-triggered register_endpoint call breaks.
  - register_table Phase 1 gate {backend, database_worker} REJECTS
    "ui_user" → every UI-triggered register_table call breaks.

This test locks the empty-actor default so future PRs don't
accidentally re-introduce the "ui_user" phantom (a grep+rewrite
discipline check, complementing the runtime gate).
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
LIVE_MONITOR = (
    AGENT_DIR / "env_generator" / "llm_generator" / "live_monitor_server.py"
)


def _extract_call_block(fname: str, src: str) -> str:
    """Return the body of the named `def <fname>(...): ... return ...`
    block as a single string (best-effort)."""
    pat = re.compile(
        rf"def\s+{re.escape(fname)}\s*\([^)]*\)\s*->\s*dict\s*:(.*?)(?=\n\ndef\s|\nclass\s|\Z)",
        re.DOTALL,
    )
    m = pat.search(src)
    if not m:
        raise AssertionError(f"function {fname!r} not found in live_monitor_server.py")
    return m.group(1)


class RegisterEndpointShimDefaultsEmptyActor(unittest.TestCase):
    """The register_endpoint HTTP shim must default `agent=""` so the
    Phase 2 `{backend}`-only gate's empty-actor fallthrough applies."""

    def setUp(self) -> None:
        self.src = LIVE_MONITOR.read_text(encoding="utf-8")

    def test_register_endpoint_shim_no_ui_user_default(self) -> None:
        block = _extract_call_block("registryhub_register_endpoint_call", self.src)
        # Match the broken default pattern specifically — the comment
        # text mentions "ui_user" in explanation, so a naive `in`
        # check would false-positive.
        broken = re.search(
            r'agent\s*=\s*body\.get\(["\']agent["\']\)\s*or\s*["\']ui_user["\']',
            block,
        )
        self.assertIsNone(
            broken,
            msg=(
                "registryhub_register_endpoint_call must not default agent to "
                "'ui_user' — Phase 2 gate {backend} rejects it. Use "
                "`agent=body.get('agent') or ''` for empty-actor fallthrough."
            ),
        )

    def test_register_endpoint_shim_uses_empty_actor_fallthrough(self) -> None:
        block = _extract_call_block("registryhub_register_endpoint_call", self.src)
        self.assertRegex(
            block,
            r'agent\s*=\s*body\.get\(["\']agent["\']\)\s*or\s*["\']{2}',
            msg=(
                "registryhub_register_endpoint_call must use the "
                "`agent=body.get('agent') or ''` pattern."
            ),
        )

    def test_register_table_shim_no_ui_user_default(self) -> None:
        block = _extract_call_block("registryhub_register_table_call", self.src)
        # Match the broken default pattern specifically — the comment
        # text mentions "ui_user" in explanation, so a naive `in`
        # check would false-positive.
        broken = re.search(
            r'agent\s*=\s*body\.get\(["\']agent["\']\)\s*or\s*["\']ui_user["\']',
            block,
        )
        self.assertIsNone(
            broken,
            msg=(
                "registryhub_register_table_call must not default agent to "
                "'ui_user' — Phase 1 gate {backend, database_worker} "
                "rejects it. Use empty-actor fallthrough."
            ),
        )

    def test_register_table_shim_uses_empty_actor_fallthrough(self) -> None:
        block = _extract_call_block("registryhub_register_table_call", self.src)
        self.assertRegex(
            block,
            r'agent\s*=\s*body\.get\(["\']agent["\']\)\s*or\s*["\']{2}',
        )

    def test_register_consumer_shim_no_ui_user_default(self) -> None:
        """register_consumer is currently ungated but the misnomer is
        cleaned up alongside the gated siblings for consistency."""
        block = _extract_call_block("registryhub_register_consumer_call", self.src)
        # Match the broken default pattern specifically — the comment
        # text mentions "ui_user" in explanation, so a naive `in`
        # check would false-positive.
        broken = re.search(
            r'agent\s*=\s*body\.get\(["\']agent["\']\)\s*or\s*["\']ui_user["\']',
            block,
        )
        self.assertIsNone(
            broken,
            msg=(
                "registryhub_register_consumer_call still defaults to "
                "'ui_user' phantom — flip to empty-actor fallthrough "
                "for consistency with register_endpoint / register_table."
            ),
        )


class GateActuallyFiresOnLegacyUIUser(unittest.TestCase):
    """End-to-end: passing the literal `agent='ui_user'` from the
    request body MUST trigger the registryhub register_endpoint
    PermissionError. The shim default fix doesn't whitelist the phantom —
    it only avoids forcing it as the default. If a UI request explicitly
    carries `agent: 'ui_user'`, the gate still rejects."""

    def test_explicit_ui_user_rejected_by_register_endpoint(self) -> None:
        import shutil
        import tempfile
        sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))
        from multi_agent.runtime.hub_registry import HubRegistry

        tmp = Path(tempfile.mkdtemp(prefix="ui_user_gate_"))
        try:
            reg = HubRegistry(tmp, project_id="p", project_name="P")
            with self.assertRaises(PermissionError) as ctx:
                reg.registryhub.register_endpoint(
                    method="GET", path="/x", schema={},
                    agent="ui_user",
                )
            self.assertIn("registryhub.register_endpoint", str(ctx.exception))
            self.assertIn("backend", str(ctx.exception))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
