"""Fix #59 — cross-user probes must never test AS the prober (outlook run-44, live).

run-44 wedged business_chain 12+ cycles on 'GET /api/messages/<uuid> → 200'
(expect [404,403]) while a live 2-user curl proved the app CORRECTLY isolated
(owner 200 / intruder 404 / unauth 401). Two executor defects:

#59c AUTH-SAVE CLOBBER: the verifier's second register saved BOTH vars —
  save:{token_2:..., token:...} — overwriting user 1's token with user 2's, so
  the 'owner' create ran AS USER 2 and the token_2 probe read a row its own
  identity created → 200 'leak'. normalize_steps now drops a save key that
  RE-BINDS a token var an earlier auth step with a DIFFERENT email bound
  (same-email re-login rebind untouched).

#59b DENIAL RECOVERY IDENTITY: an unresolved ${x_id} on a denial step fell to
  list/create recovery WITH THE STEP'S OWN TOKEN — owner-scoped list is empty
  for the prober, so #32 create-recovery minted the PROBER's own row → probe
  reads it → 200 false leak. Recovery now uses a NON-prober token (the chain's
  primary actor); with no other token it skips recovery (literal 404s → the
  denial expectation tolerates it — vacuous, never a false leak).

LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.chain_executor as ce  # noqa: E402


def _isolated_mail_server():
    """Fake owner-scoped backend: users A/B via register; messages owned by
    creator; by-id GET 404s for non-owners. Returns (http, calls, state)."""
    state = {"next_user": 1, "msgs": {}}   # msg_id -> owner_token
    calls = []

    def http(method, url, token=None, body=None, **_kw):
        calls.append((method, url, token))
        if "/auth/register" in url and method == "POST":
            tok = f"tok_user{state['next_user']}"
            state["next_user"] += 1
            return {"status": 201, "body_text": json.dumps({"access_token": tok})}
        if url.endswith("/api/messages") and method == "POST":
            mid = f"m{len(state['msgs']) + 1}"
            state["msgs"][mid] = token
            return {"status": 201, "body_text": json.dumps({"item": {"id": mid}})}
        if url.endswith("/api/messages") and method == "GET":
            mine = [{"id": k} for k, o in state["msgs"].items() if o == token]
            return {"status": 200, "body_text": json.dumps({"items": mine})}
        if "/api/messages/" in url and method == "GET":
            mid = url.rsplit("/", 1)[-1]
            owner = state["msgs"].get(mid)
            if owner is None or owner != token:
                return {"status": 404, "body_text": '{"detail":"Not found"}'}
            return {"status": 200, "body_text": json.dumps({"item": {"id": mid}})}
        return {"status": 404, "body_text": "{}"}
    return http, calls, state


_RUN44_CHAIN = {"name": "mail_flow", "steps": [
    {"method": "POST", "path": "/auth/register", "auth": "token",
     "body": {"email": "owner@example.com", "password": "Pw1!", "name": "O"},
     "save": {"token": "access_token"}, "expect": [201, 200, 409]},
    # the run-44 poison: the second register ALSO saves into "token"
    {"method": "POST", "path": "/auth/register", "auth": "token_2",
     "body": {"email": "intruder@example.com", "password": "Pw1!", "name": "I"},
     "save": {"token_2": "access_token", "token": "access_token"},
     "expect": [201, 200, 409]},
    {"method": "POST", "path": "/api/messages", "auth": "token",
     "body": {"subject": "Test Subject ${rand}", "body": "b",
              "to_emails": ["r@test.com"]},
     "save": {"message_id": "item.id"}, "expect": [201, 200]},
    {"method": "GET", "path": "/api/messages/${var.message_id}", "auth": "token",
     "expect": [200]},
    {"method": "GET", "path": "/api/messages/${var.message_id}", "auth": "token_2",
     "expect": [404, 403]},
]}


def test_run44_chain_goes_green_on_an_isolated_app(monkeypatch):
    """The EXACT run-44 chain against a correctly-isolated fake app: with #59c
    the owner keeps its token, the probe reads the OWNER's row → 404 → green
    (was: 200 'leak' flagged every cycle)."""
    http, calls, state = _isolated_mail_server()
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", _RUN44_CHAIN)
    assert out["broken"] == [], out["broken"]
    # the message was created by USER 1 (the owner), not the clobbering user 2
    assert list(state["msgs"].values()) == ["tok_user1"]


def test_clobber_guard_drops_only_the_rebinding_key():
    steps, errors = ce.normalize_steps(_RUN44_CHAIN["steps"])
    assert not errors
    assert steps[1]["save"] == {"token_2": "access_token"}   # clobber dropped
    assert steps[0]["save"]["token"] == "access_token"       # first binder kept


def test_same_email_relogin_rebind_allowed():
    steps, _ = ce.normalize_steps([
        {"method": "POST", "path": "/auth/register", "auth": "token",
         "body": {"email": "a@x.com", "password": "p", "name": "A"},
         "save": {"token": "access_token"}, "expect": [201, 409]},
        {"method": "POST", "path": "/auth/login", "auth": "token",
         "body": {"email": "a@x.com", "password": "p"},
         "save": {"token": "access_token"}, "expect": [200]},
    ])
    assert steps[1]["save"] == {"token": "access_token"}     # same identity — kept


def test_denial_recovery_uses_non_prober_token(monkeypatch):
    """#59b: unresolved var on the denial step (no prior create captured) —
    recovery must list AS THE OWNER (finds the owner's row) and never create
    as the prober; the probe then 404s → green."""
    http, calls, state = _isolated_mail_server()
    state["msgs"]["m_seed"] = "tok_user1"       # owner-seeded row
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register", "auth": "token",
         "body": {"email": "o@x.com", "password": "p", "name": "O"},
         "save": {"token": "access_token"}, "expect": [201]},
        {"method": "POST", "path": "/auth/register", "auth": "token_2",
         "body": {"email": "i@x.com", "password": "p", "name": "I"},
         "save": {"token_2": "access_token"}, "expect": [201]},
        {"method": "GET", "path": "/api/messages/${message_id}", "auth": "token_2",
         "expect": [404, 403]},
    ]})
    assert out["broken"] == [], out["broken"]
    # recovery listed with the OWNER token, and no message was created at all
    assert ("GET", "http://x/api/messages", "tok_user1") in calls
    assert not any(m == "POST" and u.endswith("/api/messages") for m, u, _t in calls)


def test_denial_without_other_token_never_creates(monkeypatch):
    """No non-prober token exists → recovery is skipped entirely: no create as
    the prober; the literal placeholder 404s and the denial expectation
    tolerates it (vacuous pass, never a false leak)."""
    http, calls, state = _isolated_mail_server()
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register", "auth": "token_2",
         "body": {"email": "i@x.com", "password": "p", "name": "I"},
         "save": {"token_2": "access_token"}, "expect": [201]},
        {"method": "GET", "path": "/api/messages/${message_id}", "auth": "token_2",
         "expect": [404, 403]},
    ]})
    assert out["broken"] == [], out["broken"]
    assert not any(m == "POST" and u.endswith("/api/messages") for m, u, _t in calls)
    assert state["msgs"] == {}


def test_non_denial_recovery_unchanged(monkeypatch):
    """#32 regression: a NON-denial step still recovers with its own token
    (list → create) exactly as before."""
    http, calls, state = _isolated_mail_server()
    monkeypatch.setattr(ce, "_http", http)
    out = ce.execute_chain("http://x", {"name": "m", "steps": [
        {"method": "POST", "path": "/auth/register", "auth": "token",
         "body": {"email": "o@x.com", "password": "p", "name": "O"},
         "save": {"token": "access_token"}, "expect": [201]},
        {"method": "GET", "path": "/api/messages/${message_id}", "auth": "token",
         "expect": [200]},
    ]})
    assert out["broken"] == [], out["broken"]
    # empty list → create-recovery AS SELF fired (the #32 behaviour)
    assert any(m == "POST" and u.endswith("/api/messages") and t == "tok_user1"
               for m, u, t in calls)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
