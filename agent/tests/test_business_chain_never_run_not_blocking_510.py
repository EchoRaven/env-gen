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


_BROKEN_STEP = "GET /api/titles \u2192 500 (expected 200)"


def _chain(name, status, ran=None):
    """ran=None → never ran (no last_result). ran='ok'|'broken' → ran with a result.

    #1203rl: `broken` is a LIST of broken-step descriptions, which is what production
    writes -- 3134 of 3134 `last_result["broken"]` values in the corpus chain registries are
    lists, and none is a bool. This helper used to build `{"broken": (ran == "broken")}`, a
    BOOL, and every assertion in this file still passed because the paths under test only ask
    it for truthiness.

    What the wrong shape cost: the blocker's detail is built with
    `_first_broken_step_1202ox(...)`, which ITERATES the list to name which step broke -- the
    one actionable sentence in the message. Handed a bool it raises TypeError, the
    `warn_once_1201` guard swallows it, and the detail silently loses the step name. So this
    file drove the gate for months without ever exercising that path. #1046's shape: a stub's
    return value drifted from production's, and nothing says so.
    """
    rec = {"name": name, "steps": [{"method": "GET", "path": "/api/titles"}],
           "status": status}
    if ran is not None:
        rec["last_result"] = {"broken": [_BROKEN_STEP] if ran == "broken" else []}
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


def test_the_blocker_names_which_step_broke():
    """#1203rl: the detail is the only part a lane can act on, and this file never reached it.

    `_first_broken_step_1202ox` iterates `last_result["broken"]` to quote the failing step.
    With the old bool fixture it raised TypeError, `warn_once_1201` swallowed it, and the
    blocker still read as a pass of this test file -- a message that says N chains have not
    passed and cannot say which step, in the gate that blocks more corpus runs than any other
    (business_chain_failing: 76 runs).
    """
    chains = {
        "title_flow": _chain("title_flow", "passing", ran="ok"),
        "broken_flow": _chain("broken_flow", "failing", ran="broken"),
    }
    b = _blockers(chains)
    assert b.get("reason") == "business_chain_failing", b
    assert "broken_flow" in str(b.get("detail") or ""), b
    assert _BROKEN_STEP in str(b.get("detail") or ""), (
        "the detail must quote the broken step, not just count the chains: %r"
        % (b.get("detail"),))


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


# ---- the >=1-passing guard's `not broken` clause: a DEFENSIVE case ----
def test_a_passing_status_over_broken_steps_does_not_satisfy_the_guard():
    """A chain still LABELLED passing while its last run recorded broken steps must block.

    #1203rl. This is NOT a test of the >=1-passing guard's `not broken` clause, though that is
    what it looks like. Mutation LF deletes that clause and stays MISSED, and the reason is
    reachability, not a missing assertion: `not_passing` is evaluated FIRST and admits any
    chain whose last run recorded broken steps, whatever its status, so by the time the guard
    runs there is no such chain left to distinguish. An earlier layer already handled it.

    Also measured: the pairing never occurs in the corpus (0 of 100 chain registries; the
    observed states are all self-consistent). So the clause is unreachable AND the input is
    synthetic -- it is kept because what it asserts is still the right answer, and it pins
    which branch delivers it.
    """
    chains = {"stale_label": _chain("stale_label", "passing", ran="broken")}
    b = _blockers(chains)
    assert b.get("reason") == "business_chain_failing", (
        "a chain whose status says passing while its last run recorded broken steps must not "
        "count as the one passing chain the guard demands: %r" % (b,))


# ---- no authored chain at all → business_chain_missing (unchanged) ----
def test_no_authored_chain_missing():
    assert _blockers({}).get("reason") == "business_chain_missing"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
