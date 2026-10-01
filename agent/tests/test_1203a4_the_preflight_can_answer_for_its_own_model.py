r"""#1203a4: the credential gate could not give a verdict for the model it guards.

`scripts/preflight_credential.py` is the gate my own notes say to run before starting a run —
"起 run 前跑 scripts/preflight_credential.py". It probed with `max_tokens: 1`.

MEASURED 2026-10-01, against a working key:
  1. `max_tokens` → HTTP 400 "Unsupported parameter: 'max_tokens' is not supported with this
     model. Use 'max_completion_tokens' instead" → fell through to rc=2 "inconclusive".
  2. `max_completion_tokens: 1` → HTTP 400 "Could not finish the message because max_tokens or
     model output limit was reached" — the model RAN and was billed, and the probe still said
     inconclusive, because a reasoning model spends tokens before it emits any.
  3. `max_completion_tokens: 16` → HTTP 200, rc=0.

★ WHY THIS WENT UNNOTICED FOR SO LONG. Every definitive verdict this gate produced was a
refusal — 401, or 429 with a billing phrase — and those are decided BEFORE parameter
validation. So the gate looked healthy for exactly as long as the credential was broken. The
day the credential started working, the gate stopped being able to say so. A guard that can
only confirm bad news is not a guard.

★ THE FIX ADDS NO FALLBACK THAT HIDES A FAILURE (the standing rule). The retry fires only on
HTTP 400 whose body carries `unsupported_parameter` AND names the next spelling, only once, and
the retry's own answer is judged by the unchanged verdict logic. Anthropic's API takes
`max_tokens`, so that branch never retries.
"""
import importlib.util
import io
import json
import os
import sys
import urllib.error

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(os.path.dirname(_AGENT), "scripts", "preflight_credential.py")


def _mod():
    spec = importlib.util.spec_from_file_location("preflight_1203a4", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _http_error(code, payload):
    return urllib.error.HTTPError(
        "https://x/v1/chat/completions", code, "err", {},
        io.BytesIO(json.dumps(payload).encode()))


_UNSUPPORTED = {"error": {"code": "unsupported_parameter", "param": "max_tokens",
                          "message": "Unsupported parameter: 'max_tokens' is not supported "
                                     "with this model. Use 'max_completion_tokens' instead."}}
_TRUNCATED = {"error": {"message": "Could not finish the message because max_tokens or model "
                                   "output limit was reached."}}
_QUOTA = {"error": {"code": "credit_balance_exhausted",
                    "message": "You have no credits remaining."}}


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run(monkeypatch, answers, provider="openai", model="gpt-5.5"):
    """`answers` is consumed one per HTTP call; each is an exception to raise or a response."""
    m = _mod()
    monkeypatch.setenv("ENVGEN_LLM_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("ENVGEN_MODEL", model)
    monkeypatch.setenv("ENVGEN_PROVIDER", provider)
    sent = []
    seq = list(answers)

    def fake_urlopen(req, timeout=None):
        sent.append(json.loads(req.data.decode()))
        nxt = seq.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr(m.urllib.request, "urlopen", fake_urlopen)
    rc, msg = m.probe()
    return rc, msg, sent


def test_a_working_credential_is_reported_as_working(monkeypatch):
    """Non-vacuity: if this cannot go green, nothing below means anything."""
    rc, msg, sent = _run(monkeypatch, [_Resp()])
    assert rc == 0, msg
    assert "answers" in msg


def test_the_parameter_name_is_retried_and_then_succeeds(monkeypatch):
    """★ The defect: a 400 about the cap's NAME is the probe's problem, not a verdict."""
    rc, msg, sent = _run(monkeypatch, [_http_error(400, _UNSUPPORTED), _Resp()])
    assert rc == 0, msg
    assert len(sent) == 2, sent
    assert "max_tokens" in sent[0] and "max_completion_tokens" not in sent[0]
    assert "max_completion_tokens" in sent[1] and "max_tokens" not in sent[1]


def test_the_cap_is_large_enough_for_a_reasoning_model(monkeypatch):
    """★ 1 token came back 400 "could not finish" — the model ran and was billed, and the gate
    still said inconclusive."""
    rc, msg, sent = _run(monkeypatch, [_Resp()])
    assert sent[0]["max_tokens"] > 1, sent[0]


def test_it_retries_at_most_once(monkeypatch):
    """A second unsupported-parameter 400 must end as a verdict, not another attempt."""
    rc, msg, sent = _run(monkeypatch, [_http_error(400, _UNSUPPORTED),
                                       _http_error(400, _UNSUPPORTED)])
    assert len(sent) == 2, sent
    assert rc == 2, msg


def test_a_truncation_400_is_not_retried_as_a_parameter_problem(monkeypatch):
    """It carries no `unsupported_parameter`, so it must not consume the second spelling."""
    rc, msg, sent = _run(monkeypatch, [_http_error(400, _TRUNCATED)])
    assert len(sent) == 1, sent
    assert rc == 2, msg


def test_a_rejected_credential_is_still_a_refusal(monkeypatch):
    """The verdict logic is untouched — and a 401 must never be retried into silence."""
    rc, msg, sent = _run(monkeypatch, [_http_error(401, {"error": {"message": "bad key"}})])
    assert rc == 1, msg
    assert len(sent) == 1, sent
    assert "rejected" in msg


def test_an_exhausted_balance_is_still_a_refusal(monkeypatch):
    """The condition that blocked every run for a day. It must stay a hard rc=1."""
    rc, msg, sent = _run(monkeypatch, [_http_error(429, _QUOTA)])
    assert rc == 1, msg
    assert "billing condition" in msg


def test_a_missing_model_is_still_a_refusal(monkeypatch):
    rc, msg, sent = _run(monkeypatch, [_http_error(404, {"error": {"message": "no model"}})])
    assert rc == 1, msg


def test_anthropic_never_retries_the_openai_spelling(monkeypatch):
    """Anthropic's API takes `max_tokens`; offering it `max_completion_tokens` would turn a
    clear answer into a second failure."""
    rc, msg, sent = _run(monkeypatch, [_http_error(400, _UNSUPPORTED)], provider="anthropic")
    assert len(sent) == 1, sent
    assert "max_tokens" in sent[0]
    assert rc == 2, msg


def test_the_body_is_read_once(monkeypatch):
    """`HTTPError.read()` does not rewind, so reading it in the retry check and again in the
    verdict would hand the verdict an EMPTY body — and an empty body means every refusal
    silently downgrades to "inconclusive"."""
    rc, msg, sent = _run(monkeypatch, [_http_error(429, _QUOTA)])
    assert "no credits remaining" in msg, (
        "the response body was consumed before the verdict could read it: %r" % msg)


def test_the_key_never_reaches_the_message(monkeypatch):
    """The standing rule: the key is never echoed. `_scrub` exists for this."""
    rc, msg, sent = _run(monkeypatch, [_http_error(
        401, {"error": {"message": "Incorrect API key provided: sk-test-not-a-real-key"}})])
    assert "sk-test-not-a-real-key" not in msg, msg
