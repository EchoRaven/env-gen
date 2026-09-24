"""Guard: FIX #192a — framework-injected cross-user isolation probe.

Empirical (2026-07-18): the last 5 SUCCESS archives carry ZERO denial (401/403)
steps in their authored chains — a pure 2xx happy-path sweep proves nothing
about ownership/tenancy (smoke_feed_77: a cross-user MUTATE returned 200 and
nothing gated it), and ENVGEN_ISOLATION_GATE can't be default-ON while its
precondition depends on an unvalidated verifier drive loop.

By-construction fix: when a chain (a) has NO denial step already, (b) registers
an authed user, and (c) POSTs a bare /api/<coll> saving an id var, normalize
appends the framework's own probe — intruder PUT /api/<coll>/${id} expect
[401,403,404] — targeting the standard item shape where the PROJECTED
owner-safe write handler serves by construction. Legit apps deny; a leaky app
2xxes and fails honestly (#78 fresh-intruder reverify guards probe artifacts).
"""

import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime.chain_executor import normalize_steps  # noqa: E402

_REGISTER = {"action": "register", "method": "POST", "path": "/auth/register",
             "body": {"email": "u_${rand}@example.com", "password": "x"},
             "expect": [201], "save": {"token": "access_token"}}
_CREATE = {"action": "create_video", "method": "POST", "path": "/api/videos",
           "body": {"title": "t"}, "auth": "token",
           "expect": [201], "save": {"video_id": "item.id"}}
_READ = {"action": "read_video", "method": "GET",
         "path": "/api/videos/${video_id}", "auth": "token", "expect": [200]}


def _probe_steps(steps):
    return [s for s in steps
            if str(s.get("action", "")).startswith("framework_isolation_probe")]


class IsolationProbeInjectionTests(unittest.TestCase):
    def test_probe_injected_for_authed_create_chain(self):
        out, _ = normalize_steps([dict(_REGISTER), dict(_CREATE), dict(_READ)])
        probes = _probe_steps(out)
        self.assertEqual(len(probes), 1)
        p = probes[0]
        self.assertEqual(p["method"], "PUT")
        self.assertEqual(p["path"], "/api/videos/${video_id}")
        self.assertEqual(sorted(p["expect"]), [401, 403, 404])
        self.assertEqual(p["auth"], "__chain_intruder_token")
        # the intruder identity is registered before the probe runs
        idx_reg = next(i for i, s in enumerate(out)
                       if "__chain_intruder_token" in (s.get("save") or {}))
        idx_probe = out.index(p)
        self.assertLess(idx_reg, idx_probe)

    def test_no_injection_when_denial_step_already_authored(self):
        denial = {"action": "cross_user_read", "method": "GET",
                  "path": "/api/videos/${video_id}", "auth": "token",
                  "expect": [403]}
        out, _ = normalize_steps(
            [dict(_REGISTER), dict(_CREATE), dict(denial)])
        self.assertEqual(_probe_steps(out), [])

    def test_no_injection_without_authed_create(self):
        out, _ = normalize_steps([
            {"action": "list", "method": "GET", "path": "/api/videos",
             "expect": [200]},
        ])
        self.assertEqual(_probe_steps(out), [])

    def test_idempotent_on_renormalize(self):
        out, _ = normalize_steps([dict(_REGISTER), dict(_CREATE), dict(_READ)])
        out2, _ = normalize_steps([dict(s) for s in out])
        self.assertEqual(len(_probe_steps(out2)), 1)

    def test_action_path_create_not_used_as_probe_target(self):
        # POST /api/videos/${id}/like is an ACTION (custom handler may serve it,
        # 422-before-ownership risk) — only a BARE collection create qualifies.
        act = {"action": "like", "method": "POST",
               "path": "/api/videos/${video_id}/like", "auth": "token",
               "expect": [200], "save": {"like_id": "item.id"}}
        out, _ = normalize_steps([dict(_REGISTER), dict(act)])
        self.assertEqual(_probe_steps(out), [])


if __name__ == "__main__":
    unittest.main()
