"""A keyless stand-in for the metagen sidecar, to exercise the launch path below the key check.

`run_netflix.sh` only calls `start_sidecar` (and therefore only demands MG_KEY) when nothing
healthy already answers on the port:

    if sidecar_healthy; then say "sidecar already up on :$PORT" ; else start_sidecar ; fi

So serving `/health` + `/v1/chat/completions` here lets the ENTIRE segment after the key check run
unattended: smoke test, playwright preflight, DESCRIPTION load, engine startup, provider wiring,
the first model calls, and the round loop's handling of replies. None of that has ever been
executed on this host — every dry run to date stopped AT the key.

This does not generate an app and must never be mistaken for a run: replies are canned. What it
buys is (a) plumbing defects found before a real key is spent on them, and (b) `stub_calls.jsonl`,
a transcript of what the engine actually asks for — model, params, system prompt, response shape.

Usage:  python tools/stub_llm_server.py --port 8900 --log /tmp/stub_calls.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_LOCK = threading.Lock()
_N = {"calls": 0}
_LOG: pathlib.Path | None = None


def _reply_text(messages: list, req: dict) -> str:
    """A reply shaped like what the prompt seems to demand, so the engine gets as deep as possible.

    The point is not to be useful — it is to avoid failing for a boring reason (a parse error on
    call #1) before the plumbing under test has had a chance to break.
    """
    last = ""
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "user":
            last = str(m.get("content") or "")
            break
    low = last.lower()
    if "reply with exactly: pong" in low:
        return "pong"  # the launcher's smoke test greps for this
    if req.get("response_format") or '"json"' in low or "json object" in low or "return json" in low:
        return '{"status": "stub", "items": [], "notes": "stub_llm_server reply"}'
    return "```python\n# stub_llm_server reply — no model was called\npass\n```"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep stdout for our own lines only
        return

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            self._send(200, {"ok": True, "stub": True, "calls": _N["calls"]})
        elif self.path.rstrip("/") == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": "stub", "object": "model"}]})
        else:
            self._send(404, {"error": {"message": f"no route {self.path}"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except Exception:
            req = {}
        msgs = req.get("messages") or []
        with _LOCK:
            _N["calls"] += 1
            idx = _N["calls"]
            if _LOG is not None:
                rec = {
                    "n": idx,
                    "path": self.path,
                    "model": req.get("model"),
                    "max_tokens": req.get("max_tokens") or req.get("max_completion_tokens"),
                    "temperature": req.get("temperature"),
                    "stream": bool(req.get("stream")),
                    "response_format": req.get("response_format"),
                    "tools": [((t.get("function") or {}).get("name")) for t in (req.get("tools") or [])],
                    "n_messages": len(msgs),
                    "roles": [m.get("role") for m in msgs if isinstance(m, dict)],
                    "chars": sum(len(str((m or {}).get("content") or "")) for m in msgs),
                    "first_user_head": next(
                        (str(m.get("content"))[:400] for m in msgs
                         if isinstance(m, dict) and m.get("role") == "user"), ""),
                    "system_head": next(
                        (str(m.get("content"))[:400] for m in msgs
                         if isinstance(m, dict) and m.get("role") == "system"), ""),
                }
                with _LOG.open("a") as fh:
                    fh.write(json.dumps(rec) + "\n")
        text = _reply_text(msgs, req)
        print(f"[stub] call {idx}: model={req.get('model')} msgs={len(msgs)} "
              f"stream={bool(req.get('stream'))} -> {len(text)}ch", flush=True)
        if req.get("stream"):
            # The engine may ask for SSE; answering with a non-stream body would look like a
            # protocol bug that is mine, not the engine's.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            chunk = {"id": f"stub-{idx}", "object": "chat.completion.chunk", "created": 0,
                     "model": req.get("model") or "stub",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": text},
                                  "finish_reason": None}]}
            done = {"id": f"stub-{idx}", "object": "chat.completion.chunk", "created": 0,
                    "model": req.get("model") or "stub",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            for ev in (chunk, done):
                self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self._send(200, {
            "id": f"stub-{idx}", "object": "chat.completion", "created": 0,
            "model": req.get("model") or "stub",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })


def main() -> None:
    global _LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8900)
    ap.add_argument("--log", default="")
    ns = ap.parse_args()
    if ns.log:
        _LOG = pathlib.Path(ns.log)
        _LOG.parent.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", ns.port), Handler)
    print(f"[stub] serving :{ns.port}  health=/health  log={ns.log or '(none)'}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
