"""Guard: FIX #188 — business_chain diagnostics must name the REAL failure.

Evidence (handoff 2026-07-18 §3-4, 225x across logs): `business_chain: GET
/api/auth/me → 200 ({"item":{...}})` marked FAILED reads as nonsense — the line
hides that the step was a pure-DENIAL probe (expect [401]) that got a success,
and a silent save-capture failure upstream surfaces only as a baffling
downstream 404/422 with a literal ${var} in the path. Three honesty fixes, all
diagnostic-only (ok/kind verdicts unchanged):
 1. broken lines carry the authored expectation ("expected [401]"), and a
    denial-probe-got-2xx is labelled as such;
 2. an OK step whose save:{var: path} captured NOTHING records save_failed on
    its entry (today: silent);
 3. a broken step that went out with an unresolved ${var} names the var and —
    when a prior step's save failed for it — the causal step.
"""

import json
import sys
import unittest
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR / "env_generator" / "llm_generator"))

from multi_agent.runtime import chain_executor as ce  # noqa: E402


class _FakeHttp:
    """Route (method, path-sans-query) → response; default 404 Not Found."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, token=None, body=None, **kw):
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        path = "/" + path.split("?", 1)[0]
        self.calls.append((method, path, token, body))
        resp = self.routes.get((method, path))
        if resp is None:
            return {"status": 404, "body_text": '{"detail":"Not Found"}', "error": None}
        return dict(resp)


class ChainDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self._orig_http = ce._http

    def tearDown(self):
        ce._http = self._orig_http

    def test_denial_probe_got_success_is_labelled(self):
        # Pure denial probe (expect [401]) got a 200 — the broken line must say
        # what was EXPECTED and that the denial did not happen, not read like
        # "a 200 failed".
        ce._http = _FakeHttp({
            ("GET", "/api/auth/me"): {
                "status": 200, "body_text": '{"item":{"id":6}}', "error": None},
        })
        res = ce.execute_chain("http://t", {
            "name": "denial", "steps": [
                {"action": "me_unauthed", "method": "GET", "path": "/api/auth/me",
                 "expect": [401]},
            ]})
        self.assertEqual(len(res["broken"]), 1)
        line = res["broken"][0]
        self.assertIn("expected [401]", line)
        self.assertIn("DENIAL-PROBE", line)

    def test_ok_step_with_failed_save_records_it(self):
        # register succeeds (201) but save:{token: access_token} finds nothing —
        # the entry must record the failed capture instead of staying silent.
        ce._http = _FakeHttp({
            ("POST", "/auth/register"): {
                "status": 201, "body_text": '{"item":{"id":1}}', "error": None},
        })
        res = ce.execute_chain("http://t", {
            "name": "reg", "steps": [
                {"action": "register", "method": "POST", "path": "/auth/register",
                 "body": {"email": "a@b.c", "password": "x"},
                 "expect": [201], "save": {"token": "access_token"}},
            ]})
        entry = res["steps"][0]
        self.assertTrue(entry["ok"])
        self.assertIn("save_failed", entry)
        self.assertIn("token", entry["save_failed"])
        self.assertIn("save", entry["note"].lower())

    def test_unresolved_var_broken_write_names_the_var_and_cause(self):
        # register OK but returns NO id/token (save fails, nothing captured) —
        # a WRITE goes out with the literal ${msg_id} (writes "fail honestly"
        # by design) and 422s. Its broken line must name ${msg_id} as
        # unresolved + carry the upstream save-failure hint, not a bare 422.
        ce._http = _FakeHttp({
            ("POST", "/auth/register"): {
                "status": 201, "body_text": '{"registered": true}', "error": None},
            ("POST", "/api/messages/${msg_id}/read"): {
                "status": 422,
                "body_text": json.dumps({"detail": [
                    {"loc": ["path", "message_id"], "msg": "int_parsing"}]}),
                "error": None},
        })
        res = ce.execute_chain("http://t", {
            "name": "flow", "steps": [
                {"action": "register", "method": "POST", "path": "/auth/register",
                 "body": {"email": "a@b.c", "password": "x"},
                 "expect": [201], "save": {"token": "access_token"}},
                {"action": "mark_read", "method": "POST",
                 "path": "/api/messages/${msg_id}/read", "auth": "token",
                 "expect": [200]},
            ]})
        broken = [s for s in res["steps"] if s["kind"] == "broken"]
        self.assertEqual(len(broken), 1)
        note = broken[0]["note"]
        self.assertIn("${msg_id}", note)
        self.assertIn("never captured", note)
        # the register's failed token save is surfaced as the causal hint
        joined = " ".join(res["broken"])
        self.assertIn("save failed", joined)

    def test_skipped_unsatisfiable_read_carries_save_failure_hint(self):
        # A GET starving on ${msg_id} is soft-SKIPPED (existing behavior) — but
        # when an upstream OK step's save failed for a var, the skip note must
        # point at that capture bug instead of only "no data to target".
        ce._http = _FakeHttp({
            ("POST", "/auth/register"): {
                "status": 201, "body_text": '{"registered": true}', "error": None},
        })
        res = ce.execute_chain("http://t", {
            "name": "flow", "steps": [
                {"action": "register", "method": "POST", "path": "/auth/register",
                 "body": {"email": "a@b.c", "password": "x"},
                 "expect": [201], "save": {"msg_id": "item.id"}},
                {"action": "read_msg", "method": "GET",
                 "path": "/api/messages/${msg_id}", "expect": [200]},
            ]})
        skipped = [s for s in res["steps"] if s["kind"] == "skipped"]
        self.assertEqual(len(skipped), 1)
        self.assertIn("${msg_id} save failed at step 'register'", skipped[0]["note"])

    def test_verdicts_unchanged_by_diagnostics(self):
        # A clean happy-path chain still passes with empty broken (diagnostics
        # must not alter verdict behavior).
        ce._http = _FakeHttp({
            ("POST", "/auth/register"): {
                "status": 201,
                "body_text": '{"item":{"id":1,"access_token":"tk"}}',
                "error": None},
            ("GET", "/api/auth/me"): {
                "status": 200, "body_text": '{"item":{"id":1}}', "error": None},
        })
        res = ce.execute_chain("http://t", {
            "name": "happy", "steps": [
                {"action": "register", "method": "POST", "path": "/auth/register",
                 "body": {"email": "a@b.c", "password": "x"},
                 "expect": [201], "save": {"token": "access_token"}},
                {"action": "me", "method": "GET", "path": "/api/auth/me",
                 "auth": "token", "expect": [200]},
            ]})
        self.assertEqual(res["broken"], [])
        self.assertNotIn("save_failed", res["steps"][0])


if __name__ == "__main__":
    unittest.main()
