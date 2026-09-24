"""Fix #57 — empty/invalid brace path params must never crash the backend
(outlook run-43, live 2026-07-02).

The lane registered ``DELETE /api/messages/{}``; the route projector emitted it
verbatim: ``def _projected_delete_api_messages_7(: str, ...)`` → SyntaxError →
the backend container CRASH-LOOPED (Exited 1) → every framework-validation
cycle failed on ``backend_port: could not resolve backend published port``.
Two layers: registryhub.register_endpoint REJECTS a non-identifier brace param
with the fix in the message (stops garbage entering the contract);
route_projector._sanitize_path_params rewrites any bad ``{...}`` already in a
hub store to a positional ``{param_N}`` so the emitted handler is always valid
Python. LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.hub_registry import HubRegistry  # noqa: E402
from multi_agent.runtime.route_projector import (  # noqa: E402
    _generate_handler, _sanitize_path_params)


# ------------------------------------------------------------- registration
def _rh(tmp_path):
    return HubRegistry(tmp_path / "hubs").registryhub


def test_empty_brace_param_rejected_with_actionable_message(tmp_path):
    with pytest.raises(ValueError) as ei:
        _rh(tmp_path).register_endpoint("DELETE", "/api/messages/{}", agent="backend")
    assert "NAMED identifier" in str(ei.value)
    assert "/api/messages/{}" in str(ei.value)


def test_non_identifier_brace_params_rejected(tmp_path):
    rh = _rh(tmp_path)
    for bad in ("/api/x/{2id}", "/api/x/{a-b}", "/api/x/{ }"):
        with pytest.raises(ValueError):
            rh.register_endpoint("GET", bad, agent="backend")


def test_named_params_still_register(tmp_path):
    rh = _rh(tmp_path)
    out = rh.register_endpoint("DELETE", "/api/messages/{messageId}", agent="backend")
    assert out
    out2 = rh.register_endpoint("GET", "/api/events/{event_id}/rsvp", agent="backend")
    assert out2


# ---------------------------------------------------------------- projector
def test_sanitize_rewrites_only_invalid_brace_params():
    assert _sanitize_path_params("/api/messages/{}") == "/api/messages/{param_4}"
    assert _sanitize_path_params("/api/x/{2id}/y/{ok_id}") == "/api/x/{param_4}/y/{ok_id}"
    assert _sanitize_path_params("/api/messages/{messageId}") == "/api/messages/{messageId}"
    assert _sanitize_path_params("") == ""


def test_generated_handler_for_bad_param_is_valid_python():
    block = _generate_handler("DELETE", "/api/messages/{}", auth=True,
                              models={}, idx=7)
    assert "(: str" not in block
    assert "{param_" in block
    compile(block, "projected.py", "exec")     # the run-43 crash was a SyntaxError here


def test_generated_handler_for_named_param_unchanged():
    block = _generate_handler("DELETE", "/api/messages/{messageId}", auth=True,
                              models={}, idx=7)
    assert "{messageId}" in block
    compile(block, "projected.py", "exec")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
