"""#1202of: the delivery gate must not dispatch a lane for a chain that could not reach the app.

#1202od stopped a connection reset being recorded as a broken endpoint and gave such a chain the
status `environment_blocked` (as #272 gives `framework_blocked` to a projected-handler crash).
The GATE is the reader that dispatches, and it knew neither status by name: anything not
`passing`/`framework_blocked` landed in `not_passing` and came back as `business_chain_failing`,
so an unreachable stack still sent a lane after a socket. That is the "fixed one reader, not the
other" shape (#1202ij). Delivery still blocks — nothing was verified — under its own reason.
"""
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
        p = re.sub(r"\$\{[^}]+\}|\{[^}]+\}", "{x}", p)
        return f"{(m or 'GET').upper()} {p.rstrip('/') or '/'}"

    def register_verification_chain(self, *a, **k):
        return None

    def update_verification_chain(self, *a, **k):
        return None


class _FakeHubs:
    def __init__(self, rh):
        self.registryhub = rh


_EPS = {"e1": {"method": "GET", "path": "/api/videos"},
        "e2": {"method": "POST", "path": "/api/videos"}}
_STEPS = [{"method": "POST", "path": "/api/videos", "expect": [201]},
          {"method": "GET", "path": "/api/videos", "expect": [200]}]


def _chain(status, **extra):
    last = {"broken": [], "steps": _STEPS}
    last.update(extra)
    return {"name": "feed_flow", "status": status, "steps": _STEPS, "last_result": last}


def _gate(chains):
    return business_chain_blockers(_FakeHubs(_FakeRH(_EPS, chains)))


def test_r124_an_unreachable_app_blocks_delivery_without_blaming_a_lane():
    out = _gate({"feed_flow": _chain(
        "environment_blocked",
        environment_1202od=["POST /api/videos → None (ConnectionResetError: [Errno 104])"])})
    assert out.get("reason") == "business_chain_environment_blocked"
    assert "UNREACHABLE" in out["detail"] and "no lane edit" in out["detail"]
    assert "ConnectionResetError" in " ".join(out["unreachable"])


def test_a_real_failure_alongside_it_still_blames_the_lane():
    chains = {"feed_flow": _chain("environment_blocked",
                                  environment_1202od=["POST /api/videos → None (reset)"]),
              "other_flow": {"name": "other_flow", "status": "failing", "steps": _STEPS,
                             "last_result": {"broken": ["GET /api/videos → 500"],
                                             "steps": _STEPS}}}
    out = _gate(chains)
    assert out.get("reason") == "business_chain_failing"
    assert "other_flow" in out["chains"] and "feed_flow" not in out["chains"]


def test_a_passing_chain_still_satisfies_the_gate():
    assert _gate({"feed_flow": _chain("passing")}) == {}
