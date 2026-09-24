"""step_pipeline.helpers artifact-sync empty-actor cleanup
(Phase 4.6.1 prep — Step A spin-off from workflow wnjpij4xw DEFER).

When the artifact-sync helper records a `record_check` per file
touched by a step, it previously fell back to `agent_id="unknown"`
when `self.agent_id` was unbound. That literal is non-empty and
would be rejected by any future Phase 4.6.1 `record_check`
allowlist gate.

Phase 4.6.1 itself stays DEFERRED (workflow wnjpij4xw — see
docs/phase_4_6_expansion_design_notes.md). This Step A spin-off
unblocks Blocker 1 of the two stated DEFER reasons; Blocker 2
(plumb `checks_authorized` data-driven allowed_set through
open_pull_request) lands separately.

This test locks the empty-actor default so a future PR doesn't
re-introduce the "unknown" phantom.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
AGENT_DIR = THIS_DIR.parent
HELPERS_PY = (
    AGENT_DIR / "env_generator" / "llm_generator" / "multi_agent"
    / "agents" / "runtime" / "step_pipeline" / "helpers.py"
)


class ArtifactSyncFallsBackToEmptyActor(unittest.TestCase):
    """The artifact-sync record_check callsite must default to ``""``
    (empty-actor fallthrough), not the literal ``"unknown"`` phantom."""

    def setUp(self) -> None:
        self.src = HELPERS_PY.read_text(encoding="utf-8")

    def _artifact_sync_block(self) -> str:
        """Return a window of text centered on the `codehub.record_check`
        call in the artifact-sync helper. Scopes assertions so the
        independent `record_agent_status` getattr earlier in the file
        (positional id, not caller-actor; legitimately uses 'unknown')
        isn't false-flagged."""
        lines = self.src.splitlines()
        target_idx = None
        for i, line in enumerate(lines):
            if "codehub.record_check(" in line:
                target_idx = i
                break
        if target_idx is None:
            raise AssertionError(
                "codehub.record_check call not found in helpers.py"
            )
        # Take a window of 20 lines before and 20 after — wide enough
        # to capture the getattr fallback above and the agent= kwarg
        # at the call site below.
        start = max(0, target_idx - 20)
        end = min(len(lines), target_idx + 20)
        return "\n".join(lines[start:end])

    def test_artifact_sync_getattr_fallback_is_empty_string(self) -> None:
        """The `getattr(self, 'agent_id', <FALLBACK>)` call in the
        artifact-sync block must use `''` as the fallback."""
        block = self._artifact_sync_block()
        broken = re.search(
            r'getattr\(\s*self,\s*["\']agent_id["\']\s*,\s*["\']unknown["\']\s*\)',
            block,
        )
        self.assertIsNone(
            broken,
            msg=(
                "artifact-sync helper still falls back to agent_id='unknown' "
                "phantom — flip to empty-string for Phase 4.6.1 gate "
                "compatibility. The 'unknown' literal is non-empty and "
                "bypasses empty-actor fallthrough."
            ),
        )
        good = re.search(
            r'getattr\(\s*self,\s*["\']agent_id["\']\s*,\s*["\']{2}\s*\)',
            block,
        )
        self.assertIsNotNone(
            good,
            msg=(
                "expected `getattr(self, 'agent_id', '')` in artifact-sync "
                "block"
            ),
        )

    def test_evidence_payload_preserves_unknown_for_audit_trail(self) -> None:
        """The flip only changes the gate-facing `agent=` kwarg — the
        evidence dict still records `agent_id or 'unknown'` so the
        audit trail stays readable when agent_id was unbound."""
        block = self._artifact_sync_block()
        evidence_pattern = re.search(
            r'"agent":\s*agent_id\s+or\s+["\']unknown["\']',
            block,
        )
        self.assertIsNotNone(
            evidence_pattern,
            msg=(
                "evidence payload should preserve `agent_id or 'unknown'` "
                "so the audit trail still shows when agent_id was unbound; "
                "only the gate-facing `agent=` kwarg flips to empty."
            ),
        )

    def test_record_check_call_uses_agent_id_kwarg(self) -> None:
        """The `agent=` kwarg passed to codehub.record_check in the
        artifact-sync block must be the bare `agent_id` local."""
        block = self._artifact_sync_block()
        # In the artifact-sync block, the record_check call ends with
        # `agent=agent_id,` on its own line.
        self.assertRegex(
            block,
            r"agent\s*=\s*agent_id\s*,",
            msg=(
                "record_check call in artifact-sync block should pass "
                "`agent=agent_id` (the post-flip empty-fallback local)"
            ),
        )
        # And the literal `agent="unknown"` must NOT appear as a kwarg.
        self.assertNotRegex(
            block,
            r"agent\s*=\s*[\"']unknown[\"']",
            msg=(
                "record_check call must not pass `agent=\"unknown\"` "
                "literal — phase gates reject non-allowlisted strings"
            ),
        )


if __name__ == "__main__":
    unittest.main()
