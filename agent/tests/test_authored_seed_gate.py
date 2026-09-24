"""Authored-seed deliverability gate — not waived by functional validation (run-33,
2026-07-02).

The registration-based seed checks are relaxed once api_smoke passes, so run-33 shipped
"SUCCESS" with app/backend/seed_data.json still `{}` — the bland framework-fallback seed —
while the spec's bar is domain-realistic populated screens. compute_deliverability now
blocks (non-waivable) when seed_data.json is absent/empty/invalid; clears the moment a
non-empty valid JSON lands. The remediation dispatch + deliver guard (#39) then drive the
lane to author it (run-31 proved it can). ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.deliverability import compute_deliverability  # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402


def _blockers(tmp_path, seed_content=None):
    app = tmp_path / "app"
    (app / "backend").mkdir(parents=True, exist_ok=True)
    if seed_content is not None:
        (app / "backend" / "seed_data.json").write_text(seed_content, encoding="utf-8")
    hr = HubRegistry(tmp_path / "hubs")
    rep = compute_deliverability(hr, app, session_start_ts=0.0)
    return [b for b in (rep.blockers or []) if "authored seed missing" in b]


def test_empty_placeholder_json_blocks(tmp_path):
    assert _blockers(tmp_path, "{}")            # the run-33 state


def test_absent_json_blocks(tmp_path):
    assert _blockers(tmp_path, None)


def test_invalid_json_blocks(tmp_path):
    assert _blockers(tmp_path, "{not json")


def test_empty_lists_still_block(tmp_path):
    assert _blockers(tmp_path, json.dumps({"users": [], "messages": []}))


def test_authored_rows_clear_the_blocker(tmp_path):
    seed = json.dumps({"users": [{"email": "demo@example.com", "name": "Demo"}],
                       "messages": [{"user_id": 1, "subject": "Quarterly sync notes"}]})
    assert _blockers(tmp_path, seed) == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
