"""FIX #281 — a chain step against a FORM-encoded endpoint can never pass (tiktok r66, 2026-07-23 live).

`validation_runner._http` ALWAYS sends `Content-Type: application/json`. The framework's OWN
scaffolded `oauth_routes.py` declares `POST /oauth/authorize` with `email: str = Form(...)` /
`password: str = Form(...)` / `client_id: str = Form(...)` — which is the CORRECT OAuth2 shape,
not a lane defect. FastAPI then reports every Form field as missing FROM THE BODY, so the step
gets `400 {"error":"invalid_request","errors":[{"type":"missing","loc":["body","email"],...}]}`
no matter what the verifier authors — the chain-step schema has no way to express encoding.

Live cost (r66): business_chain wedged on that ONE step through all 6 validation attempts →
`deliverability_no_successful_run` → DELIVERY-GATE NO-CONVERGENCE ABORT at 76min. The verifier
was dispatched to "fix" a defect it had no power to fix — reproduced by hand against the live
container: the same request re-sent form-encoded returns 401 + the real consent page, proving
the endpoint works and only the ENCODING was wrong.

Fix: detect the JSON-vs-Form mismatch by SIGNATURE (the response calls fields missing from the
body that we demonstrably DID send) and retry that step ONCE form-encoded. Deterministic and
env-agnostic: it cannot misfire on a genuine missing-field error, because a field we never sent
is not evidence of an encoding mismatch. ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import multi_agent.runtime.validation_runner as vr  # noqa: E402

# The VERBATIM r66 response body (live capture, localhost:3001).
R66_400 = (
    '{"error":"invalid_request","detail":"missing or malformed request parameters",'
    '"errors":[{"type":"missing","loc":["body","email"],"msg":"Field required","input":null},'
    '{"type":"missing","loc":["body","password"],"msg":"Field required","input":null},'
    '{"type":"missing","loc":["body","client_id"],"msg":"Field required","input":null}]}'
)

SENT = {
    "response_type": "code", "client_id": "mcp_k0G5dGO_YeRzbZ8H2MPv9A",
    "redirect_uri": "http://localhost:9999/callback", "scope": "openid",
    "email": "probe@example.com", "password": "password123",
}


def test_r66_signature_warrants_a_form_retry():
    """The live wedge: every 'missing' field WAS sent → encoding mismatch."""
    assert vr._form_retry_warranted(SENT, 400, R66_400) is True


def test_genuine_missing_field_does_not_warrant_a_form_retry():
    """A field we never sent is a REAL validation error — must not be masked by a retry."""
    body = {"title": "x"}  # 'email' genuinely absent from what we sent
    assert vr._form_retry_warranted(body, 400, R66_400) is False


def test_422_form_signature_also_warrants_retry():
    """FastAPI returns 422 for the same mismatch when the app keeps the default handler."""
    r = ('{"detail":[{"type":"missing","loc":["body","username"],"msg":"Field required"}]}')
    assert vr._form_retry_warranted({"username": "u"}, 422, r) is True


def test_non_4xx_and_empty_body_never_retry():
    assert vr._form_retry_warranted(SENT, 200, R66_400) is False
    assert vr._form_retry_warranted(SENT, 500, R66_400) is False
    assert vr._form_retry_warranted(None, 400, R66_400) is False
    assert vr._form_retry_warranted({}, 400, R66_400) is False


def test_query_loc_is_not_a_body_encoding_mismatch():
    """loc=['query',...] means a missing QUERY param — re-encoding the body cannot help."""
    r = '{"detail":[{"type":"missing","loc":["query","client_id"],"msg":"Field required"}]}'
    assert vr._form_retry_warranted({"client_id": "c"}, 400, r) is False


def test_http_form_flag_sends_urlencoded(monkeypatch):
    """_http(form=True) must send urlencoded bytes + the form content-type."""
    seen = {}

    class _Resp:
        status = 200

        def read(self, _n=None):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        seen["ctype"] = req.get_header("Content-type")
        seen["data"] = req.data
        return _Resp()

    monkeypatch.setattr(vr.urllib.request, "urlopen", _fake_urlopen)
    vr._http("POST", "http://x/oauth/authorize", body={"a": "1", "b": "x y"}, form=True)

    assert seen["ctype"] == "application/x-www-form-urlencoded"
    assert seen["data"] == b"a=1&b=x+y"


def test_http_defaults_to_json(monkeypatch):
    """Unchanged default: JSON encoding for every existing caller."""
    seen = {}

    class _Resp:
        status = 200

        def read(self, _n=None):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        seen["ctype"] = req.get_header("Content-type")
        seen["data"] = req.data
        return _Resp()

    monkeypatch.setattr(vr.urllib.request, "urlopen", _fake_urlopen)
    vr._http("POST", "http://x/api/videos", body={"a": 1})

    assert seen["ctype"] == "application/json"
    assert seen["data"] == b'{"a": 1}'
