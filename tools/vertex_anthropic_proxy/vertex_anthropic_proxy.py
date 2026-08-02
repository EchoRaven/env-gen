#!/usr/bin/env python3
"""Anthropic-native → FB Vertex gateway proxy (cert-mTLS + cache_control passthrough).

WHY
---
The engine's native Anthropic client (``AnthropicClient`` in ``agent/utils/llm.py``,
which wraps ``anthropic.AsyncAnthropic``) POSTs to ``{api_base}/v1/messages``. The
internal Claude path on this host is the Vertex gateway, which (a) authenticates with the
fb x509 CERT (mTLS), not a bearer key, and (b) exposes ``…:rawPredict`` /
``…:streamRawPredict`` rather than ``/v1/messages``. The stock SDK can do neither.

This proxy bridges the two WITHOUT an OpenAI translation layer — which matters because the
OpenAI-compat wrapper silently drops ``cache_control`` for opus (proven inert). Here the
Anthropic body (``system`` blocks with ``cache_control``, ``tools``, ``messages``) is
forwarded verbatim, so prompt caching WORKS. Verified live on claude-opus-4-7:
call 1 ``cache_creation_input_tokens=34303`` / ``cache_read=0``; call 2 ``cache_read=34303``.

USE
---
    python vertex_anthropic_proxy.py --port 8790          # start it
    # then run the engine against it (a dummy key satisfies the SDK; the proxy ignores it):
    #   --provider anthropic \
    #   --api-base http://127.0.0.1:8790 \
    #   --model claude-opus-4-7
    #   (ANTHROPIC_API_KEY=dummy)

Config via env (all have sane defaults for this host):
    VERTEX_GATEWAY_BASE  default https://vertex.ai-gateway.fbinfra.net/v1
    VERTEX_PROJECT       default devai-mea-egeit
    VERTEX_LOCATION      default global   (us-east5/europe-west1 return 501; only global works)
    FB_X509              default /var/facebook/credentials/haibotong/x509/haibotong.pem
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

GATEWAY = os.getenv("VERTEX_GATEWAY_BASE", "https://vertex.ai-gateway.fbinfra.net/v1")
PROJECT = os.getenv("VERTEX_PROJECT", "devai-mea-egeit")
LOCATION = os.getenv("VERTEX_LOCATION", "global")
CERT = os.getenv("FB_X509", "/var/facebook/credentials/haibotong/x509/haibotong.pem")
# FB internal CA — needed to VERIFY the gateway's server cert (httpx's default certifi
# bundle does not trust it). Same bundle git uses (/etc/gitconfig http.sslcainfo).
CA = os.getenv("FB_CA", "/etc/pki/tls/certs/fb_certs.pem")
VERTEX_ANTHROPIC_VERSION = "vertex-2023-10-16"
UPSTREAM_TIMEOUT = float(os.getenv("VERTEX_PROXY_TIMEOUT", "600"))


def _build_ssl_context() -> ssl.SSLContext:
    """FB CA (server verify) + our x509 client chain (mTLS). httpx's own
    ``cert=``/``verify=cafile`` combo fails to present the client cert on TLS1.3 here
    (server → 'certificate required'); building the context explicitly is what works."""
    ctx = ssl.create_default_context(cafile=CA)
    ctx.load_cert_chain(CERT)
    return ctx


# Shared client, REBUILT when the mTLS cert file changes on disk (#413). fb x509 certs
# rotate every few days; a client that load_cert_chain'd the OLD cert at startup serves
# 'SSLV3_ALERT_CERTIFICATE_EXPIRED' 502s until the PROCESS is restarted — this silently
# killed a whole generation run (r10, 2026-08-02): the proxy's /health stayed 200 the
# entire time (health never touches the upstream mTLS), so the launcher reused the stale
# proxy. Reloading on realpath+mtime change makes the proxy self-heal across rotations.
# httpx.Client is safe for concurrent use by the threaded server.
import threading as _threading

_CLIENT = None
_CLIENT_KEY = None  # (realpath, mtime) the current _CLIENT was built for
_CLIENT_LOCK = _threading.Lock()


def _cert_key():
    """(realpath, mtime) of the mTLS cert, or None if unreadable. Tracking the resolved
    path AND mtime catches both a file rewrite and a symlink retarget (the fb cert path
    is an autofs symlink)."""
    try:
        rp = os.path.realpath(CERT)
        return (rp, os.path.getmtime(rp))
    except OSError:
        return None


def _client() -> httpx.Client:
    """The shared httpx client, rebuilt when the cert file changes (#413). Returns the
    existing client unchanged when the cert is unreadable (transient) or unchanged."""
    global _CLIENT, _CLIENT_KEY
    key = _cert_key()
    if _CLIENT is not None and (key is None or key == _CLIENT_KEY):
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None or (key is not None and key != _CLIENT_KEY):
            _old = _CLIENT
            _CLIENT = httpx.Client(verify=_build_ssl_context(), timeout=UPSTREAM_TIMEOUT)
            _CLIENT_KEY = key
            if _old is not None:
                try:
                    _old.close()
                except Exception:  # noqa: BLE001
                    pass
    return _CLIENT


def _upstream_url(model: str, stream: bool) -> str:
    verb = "streamRawPredict" if stream else "rawPredict"
    return (f"{GATEWAY}/projects/{PROJECT}/locations/{LOCATION}"
            f"/publishers/anthropic/models/{model}:{verb}")


def translate_body(body: dict, stream: bool):
    """Anthropic /v1/messages body → Vertex rawPredict body.

    Vertex takes the model in the URL and REJECTS a top-level ``model``; it also requires
    ``anthropic_version``. Everything else (``system`` w/ cache_control, ``tools``,
    ``messages``, ``max_tokens``, ``temperature``, ``stop_sequences``) is forwarded
    unchanged so caching + tool-calling behave exactly as anthropic-native.

    ``stream`` MUST be kept in the body for ``:streamRawPredict`` (the gateway emits proper
    Anthropic SSE only then); without it, ``:streamRawPredict`` returns one JSON blob the
    SDK's stream parser can't read. For ``:rawPredict`` it is dropped. Returns
    ``(model, translated_body)``; model is None when absent (caller 400s)."""
    b = dict(body)
    model = b.pop("model", None)
    b["anthropic_version"] = VERTEX_ANTHROPIC_VERSION
    if stream:
        b["stream"] = True
    else:
        b.pop("stream", None)
    return model, b


class _Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj) -> None:
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # trivial health check
        if self.path.rstrip("/").endswith("/health"):
            self._json(200, {"ok": True, "gateway": GATEWAY, "location": LOCATION})
        else:
            self._json(404, {"error": "GET only supports /health"})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/v1/messages"):
            self._json(404, {"error": "only POST /v1/messages is proxied"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:  # noqa: BLE001
            self._json(400, {"error": f"bad request body: {e}"})
            return

        stream = bool(body.get("stream"))
        model, tbody = translate_body(body, stream)
        if not model:
            self._json(400, {"error": "missing 'model' in request body"})
            return
        url = _upstream_url(model, stream)

        try:
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                with _client().stream("POST", url, json=tbody) as r:
                    for chunk in r.iter_raw():
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
            else:
                r = _client().post(url, json=tbody)
                self.send_response(r.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(r.content)))
                self.end_headers()
                self.wfile.write(r.content)
        except Exception as e:  # noqa: BLE001
            self._json(502, {"error": f"upstream call failed: {e}"})

    def log_message(self, *_a):  # keep the console quiet
        return


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"vertex-anthropic proxy on http://{args.host}:{args.port} -> {GATEWAY} "
          f"(project={PROJECT}, location={LOCATION}, cert={CERT})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
