"""#1202nj: a capture that missed says where the field actually is.

tiktok-r125 M2. The verifier's follow chains saved the new user from `/auth/register` with
`item.id`; the response carries it at `user.id`. Every run said

    SUBSTITUTED ${userB} save failed at step 'signup_user_b' (response lacked the save path)
    — the ladder sent an UNRELATED id — fix that capture, not this endpoint.

and nothing about what the response did contain. Between 07:08 and 07:29 the verifier registered
v2, v4 and v5 of the chain with `item.id` and `id`, while `messages_follow_isolation_flow`, which
saved `user.id`, passed on every run. Delivery of v1.1.0 was held the whole time.

Two emitters again: #1202hb fixed the starving-GET sentence (its docstring quotes this very
SUBSTITUTED line from r102), and the #592 SUBSTITUTED branch kept its fixed wording.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.chain_executor import (  # noqa: E402
    _save_miss_reason_1202gu, execute_chain)

REGISTER = {"access_token": "tok", "token_type": "bearer",
            "user": {"id": 67, "email": "a@x.com", "username": "a"}}


def test_the_reason_names_the_path_that_holds_the_field():
    why = _save_miss_reason_1202gu(REGISTER, "item.id")
    assert "`item.id`" in why and "`user.id`" in why, why


def test_without_a_same_named_field_it_lists_the_keys_where_the_walk_stopped():
    why = _save_miss_reason_1202gu(REGISTER, "item.uid")
    assert "access_token" in why and "user" in why, why


def test_an_empty_collection_keeps_its_own_verdict():
    why = _save_miss_reason_1202gu({"items": []}, "items.0.id")
    assert "EMPTY" in why and "has `" not in why, why


def test_a_path_that_exists_elsewhere_under_a_list_is_found():
    why = _save_miss_reason_1202gu({"items": [{"video": {"id": 3}}]}, "items.0.id")
    assert "`items.0.video.id`" in why, why


class _App(BaseHTTPRequestHandler):
    next_id = [60]

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        if self.path == "/auth/register":
            _App.next_id[0] += 1
            return self._send(201, {"access_token": "tok%d" % _App.next_id[0],
                                    "user": {"id": _App.next_id[0]}})
        return self._send(400, {"detail": "cannot follow yourself"})

    do_DELETE = do_POST

    def do_GET(self):
        self._send(200, {"items": [{"id": 61}, {"id": 62}]})


def test_r125_the_failing_follow_step_names_user_id():
    srv = HTTPServer(("127.0.0.1", 0), _App)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        chain = {"name": "follow_v2", "steps": [
            {"action": "signup_user_a", "method": "POST", "path": "/auth/register",
             "body": {"email": "a_${rand}@x.com", "password": "pw123456!"},
             "expect": [200, 201], "save": {"tokenA": "item.access_token", "userA": "item.id",
                                            "token": "access_token"}},
            {"action": "signup_user_b", "method": "POST", "path": "/auth/register",
             "body": {"email": "b_${rand}@x.com", "password": "pw123456!"},
             "expect": [200, 201], "save": {"userB": "item.id"}},
            {"action": "a_follows_b", "method": "POST", "path": "/api/users/${userB}/follow",
             "auth": "tokenA", "body": {}, "expect": [200, 201]},
        ]}
        res = execute_chain("http://127.0.0.1:%d" % srv.server_port, chain)
    finally:
        srv.shutdown()
    follow = [b for b in res.get("broken") or [] if "/follow" in b]
    assert follow and "SUBSTITUTED" in follow[0], res.get("broken")
    assert "`user.id`" in follow[0], follow[0]
