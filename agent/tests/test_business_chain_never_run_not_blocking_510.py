"""#510 (netflix r84, 2026-08-05) — a NEVER-RUN ('registered') verification chain must NOT
block delivery like a chain that RAN and broke.

GROUND TRUTH: r84 exited main()=1 (no release) on ['verification_checklist_not_ready',
'business_chain_failing']. The chain registry at exit: 11 PASSING + 1 coverage + 5 REGISTERED
(the verifier RE-AUTHORED 5 comprehensive business chains at the deliver tail — auth_roundtrip,
catalog_browse, my_list_crud, rating, tenant_admin — that never ran). Those 5 unrun chains kept
business_chain_failing FOREVER → the milestone gate never cleared → the #139 final-gate DRIFT
WAIVER (which needs a cleared milestone) never fired → main()=1, though 11 chains PASSED and
covered the surface. A never-run chain is INDETERMINATE, not a failure.

FIX #510 (business_chain_blockers): exclude never-run ('registered', no last_result) chains from
`not_passing` — only a chain that RAN and broke (or status 'failing') blocks — with a ≥1-passing
guard so an all-unrun set can't ship unverified. Coverage still enforced.

These tests lock: (1) the r84 case (passing + never-run → NOT blocked), (2) a ran-and-broke chain
still blocks, (3) a status='failing' chain still blocks, (4) all-never-run blocks (guard),
(5) passing-only still delivers, (6) no authored chain → business_chain_missing (unchanged)."""
import re

from env_generator.llm_generator.multi_agent.runtime.delivery_gate import business_chain_blockers


class _FakeRH:
    def __init__(self, endpoints, chains):
        self._eps, self._chains = endpoints, chains

    def get_endpoints(self):
        return dict(self._eps)

    def get_verification_chains(self):
        return dict(self._chains)

    def endpoint_id(self, m, p):
        p = re.sub(r"\{[^}]+\}", "{x}", p)
        return f"{(m or 'GET').upper()} {p.rstrip('/') or '/'}"

    def register_verification_chain(self, *a, **k):
        return None

    def update_verification_chain(self, *a, **k):
        return None


class _FakeHubs:
    def __init__(self, rh):
        self.registryhub = rh


_ENDPOINTS = {"e1": {"method": "GET", "path": "/api/titles"}}


def _chain(name, status, ran=None):
    """ran=None → never ran (no last_result). ran='ok'|'broken' → ran with a result."""
    rec = {"name": name, "steps": [{"method": "GET", "path": "/api/titles"}],
           "status": status}
    if ran is not None:
        rec["last_result"] = {"broken": (ran == "broken")}
    return rec


def _blockers(chains):
    return business_chain_blockers(_FakeHubs(_FakeRH(_ENDPOINTS, chains)))


# ---- the r84 case: PASSING chain(s) + NEVER-RUN re-authored chains → NOT blocked ----
def test_r84_passing_plus_never_run_not_blocked():
    chains = {
        "title_flow": _chain("title_flow", "passing", ran="ok"),
        "reauthored_1": _chain("reauthored_1", "registered"),   # never ran
        "reauthored_2": _chain("reauthored_2", "registered"),   # never ran
    }
    b = _blockers(chains)
    assert b.get("reason") != "business_chain_failing", b


# ---- a chain that RAN and BROKE still blocks (no false-pass) ----
def test_ran_and_broke_still_blocks():
    chains = {
        "title_flow": _chain("title_flow", "passing", ran="ok"),
        "broken_flow": _chain("broken_flow", "failing", ran="broken"),
    }
    assert _blockers(chains).get("reason") == "business_chain_failing"


def test_status_failing_still_blocks():
    chains = {
        "title_flow": _chain("title_flow", "passing", ran="ok"),
        "failing_flow": _chain("failing_flow", "failing", ran="ok"),  # ran, status failing
    }
    assert _blockers(chains).get("reason") == "business_chain_failing"


# ---- ALL never-run (no passing) → blocked by the ≥1-passing guard ----
def test_all_never_run_blocked_by_guard():
    chains = {
        "a": _chain("a", "registered"),
        "b": _chain("b", "registered"),
    }
    assert _blockers(chains).get("reason") == "business_chain_failing"


# ---- passing-only still delivers (byte-identical happy path) ----
def test_passing_only_not_blocked():
    chains = {"title_flow": _chain("title_flow", "passing", ran="ok")}
    b = _blockers(chains)
    assert b.get("reason") != "business_chain_failing", b


# ---- no authored chain at all → business_chain_missing (unchanged) ----
def test_no_authored_chain_missing():
    assert _blockers({}).get("reason") == "business_chain_missing"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
