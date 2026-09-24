"""#152 — a HARD-unusable app never escape-releases (googlemaps run-4).

run-4 shipped a UI nobody can use: SearchResultsList used a bare fetch() with no auth
token → every /api/ call 401'd → bc_auth bounced every core page to /login. The browser
test-user CAUGHT it (auth_ok=False, blank home/search) and deferred — but the bounded
escape (squad_release_decision: cap 3 attempts / 900s) fired after 7 attempts / 9614s and
delivered "a possibly-unusable UI, loudly". A release nobody can log into is worthless;
holding to a FAIL-FAST STUCK is more honest than shipping a dead app.

browser_gate_decision hardens the escape: HARD-unusable (auth_ok False, or a login-wall
hollow_frontend) NEVER releases — keep deferring. SOFT-unusable (auth works, only some
pages blank/console-error) keeps the existing bounded escape so a minor defect never
deadlocks. ENVGEN_TESTUSER_HARD_GATE=0 restores the old always-escape (safety valve).
LOCAL-ONLY (agent/tests/ gitignored).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.test_user_runner import browser_gate_decision  # noqa: E402


def test_auth_broken_never_escapes():
    # squad would release (cap hit), but a login-broken app must keep deferring
    r = {"ran": True, "auth_ok": False, "hollow_frontend": False, "blank_pages": ["home"]}
    assert browser_gate_decision(r, "release") == "defer"
    assert browser_gate_decision(r, "defer") == "defer"


def test_hollow_frontend_never_escapes():
    r = {"ran": True, "auth_ok": True, "hollow_frontend": True, "auth_redirect_pages": ["home", "search"]}
    assert browser_gate_decision(r, "release") == "defer"


def test_soft_unusable_keeps_bounded_escape():
    # auth works, only a secondary page blank — the bounded escape still applies
    r = {"ran": True, "auth_ok": True, "hollow_frontend": False, "blank_pages": ["departures"]}
    assert browser_gate_decision(r, "release") == "release"
    assert browser_gate_decision(r, "defer") == "defer"


def test_hard_gate_env_override_restores_escape(monkeypatch):
    monkeypatch.setenv("ENVGEN_TESTUSER_HARD_GATE", "0")
    r = {"ran": True, "auth_ok": False, "hollow_frontend": True}
    assert browser_gate_decision(r, "release") == "release"  # old behavior when disabled


def test_run4_shape_holds(monkeypatch):
    # the exact run-4 signature: auth_ok False + core pages blank, squad wants release
    monkeypatch.delenv("ENVGEN_TESTUSER_HARD_GATE", raising=False)
    r = {"ran": True, "auth_ok": False, "hollow_frontend": False,
         "blank_pages": ["home_map", "search_results"]}
    assert browser_gate_decision(r, "release") == "defer", \
        "run-4's dead UI must NOT escape-release"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
