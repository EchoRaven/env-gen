r"""#1202zj: the launcher checked that the key EXISTS and never that it ANSWERS.

r141 cleared all six of `tiktok_designinput.sh`'s preflights — provider/model set, key
present, no concurrent run, design materials staged, 60G free, playwright installed — and then
died 82.7 s in, with **612 s of process wall clock**, on
`429 insufficient_quota: You have no credits remaining`. One HTTP call answers that in about
two seconds, and wall clock is the binding constraint on this pipeline (r139 died of it).

★ THE CLASSIFICATION IS THE WHOLE DESIGN, and getting it wrong in either direction costs more
than the check saves:

    refuse (1)      401/403, a 429 whose body names a quota/billing condition, 404 on the model
    inconclusive (2) timeout, DNS, reset, 5xx, unparseable body — and a BARE 429

A bare 429 is ordinary throttling and clears on its own. #1159 and #1174 paid for that
distinction twice: r15 spent 2h50m retrying a dead account, and r16 — which had $262 spent and
one failing gate left — was killed by a 57-SECOND quota blip on a live one. Refusing on a
network hiccup would trade a wasted run for a false refusal, which is worse: the run was
possible and nothing ran.
"""
import importlib.util
import json
import os
import sys
import urllib.error

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(_AGENT)
_SCRIPT = os.path.join(_ROOT, "scripts", "preflight_credential.py")
_LAUNCH = os.path.join(_ROOT, "scripts", "tiktok_designinput.sh")


def _mod():
    spec = importlib.util.spec_from_file_location("preflight_credential_1202zj", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _env(monkeypatch, **over):
    base = {"ENVGEN_PROVIDER": "openai", "ENVGEN_LLM_KEY": "sk-testtesttesttest",
            "ENVGEN_MODEL": "gpt-5.5", "ENVGEN_API_BASE": "https://example.invalid/v1",
            "ENVGEN_PREFLIGHT": "1"}
    base.update(over)
    for k in ("ENVGEN_PROVIDER", "ENVGEN_LLM_KEY", "ENVGEN_MODEL", "ENVGEN_API_BASE",
              "ENVGEN_PREFLIGHT", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in base.items():
        if v is not None:
            monkeypatch.setenv(k, v)


def _http(monkeypatch, m, code, body):
    def _raise(*a, **k):
        raise urllib.error.HTTPError("u", code, "m", {},
                                     __import__("io").BytesIO(body.encode()))
    monkeypatch.setattr(m.urllib.request, "urlopen", _raise)


def _ok(monkeypatch, m, status=200):
    class _R:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    r = _R(); r.status = status
    monkeypatch.setattr(m.urllib.request, "urlopen", lambda *a, **k: r)


_QUOTA_BODY = json.dumps({"error": {"message": "You have no credits remaining.",
                                    "type": "insufficient_quota",
                                    "code": "credit_balance_exhausted"}})


# ── refuse ────────────────────────────────────────────────────────────────────────

def test_the_exact_body_that_killed_r141_is_refused(monkeypatch):
    m = _mod(); _env(monkeypatch); _http(monkeypatch, m, 429, _QUOTA_BODY)
    code, msg = m.probe()
    assert code == 1, msg
    assert "billing condition" in msg


def test_a_rejected_key_is_refused(monkeypatch):
    m = _mod(); _env(monkeypatch)
    for status in (401, 403):
        _http(monkeypatch, m, status, '{"error":{"message":"Incorrect API key"}}')
        assert m.probe()[0] == 1, status


def test_a_model_that_does_not_exist_is_refused(monkeypatch):
    """A run would fail on its first call, so it is not worth starting."""
    m = _mod(); _env(monkeypatch)
    _http(monkeypatch, m, 404, '{"error":{"message":"model not found"}}')
    assert m.probe()[0] == 1


# ── inconclusive: NOT a refusal ───────────────────────────────────────────────────

def test_a_bare_429_is_not_a_refusal(monkeypatch):
    """★ Ordinary throttling clears on its own. #1174: r16 had $262 spent and was killed by a
    57-second quota blip on an account that was fine."""
    m = _mod(); _env(monkeypatch)
    _http(monkeypatch, m, 429, '{"error":{"message":"Rate limit reached for requests"}}')
    code, msg = m.probe()
    assert code == 2, msg
    assert "throttling" in msg


def test_a_server_error_is_not_a_refusal(monkeypatch):
    m = _mod(); _env(monkeypatch)
    _http(monkeypatch, m, 503, "upstream unavailable")
    assert m.probe()[0] == 2


def test_a_network_failure_is_not_a_refusal(monkeypatch):
    """A DNS blip must not stop a launch — the run's own retry logic is built for it."""
    m = _mod(); _env(monkeypatch)
    def _boom(*a, **k):
        raise urllib.error.URLError("Temporary failure in name resolution")
    monkeypatch.setattr(m.urllib.request, "urlopen", _boom)
    assert m.probe()[0] == 2


def test_a_missing_key_is_inconclusive_not_a_refusal(monkeypatch):
    """The launcher's own key check already refuses on absence; this must not double-refuse
    on a DIFFERENT reading of the same environment."""
    m = _mod(); _env(monkeypatch, ENVGEN_LLM_KEY=None)
    assert m.probe()[0] == 2


# ── pass ──────────────────────────────────────────────────────────────────────────

def test_an_answering_credential_passes(monkeypatch):
    m = _mod(); _env(monkeypatch); _ok(monkeypatch, m)
    code, msg = m.probe()
    assert code == 0 and "answers" in msg


def test_an_unprobeable_provider_passes(monkeypatch):
    """google/metagen/local are not probed here; refusing them would block launches this
    check knows nothing about."""
    m = _mod(); _env(monkeypatch, ENVGEN_PROVIDER="google")
    assert m.probe()[0] == 0


def test_anthropic_uses_its_own_header_and_path(monkeypatch):
    m = _mod(); _env(monkeypatch, ENVGEN_PROVIDER="anthropic", ENVGEN_API_BASE=None)
    seen = {}
    class _R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    def _cap(req, *a, **k):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.headers.items()}
        return _R()
    monkeypatch.setattr(m.urllib.request, "urlopen", _cap)
    assert m.probe()[0] == 0
    assert seen["url"].endswith("/messages"), seen["url"]
    assert "x-api-key" in seen["headers"], seen["headers"]


# ── the key never leaves ──────────────────────────────────────────────────────────

def test_the_key_is_never_in_the_message(monkeypatch):
    """★ The user's standing rule: the key is never echoed, logged or committed. A provider
    that quotes the key back in its error body must not become a printed key."""
    m = _mod(); _env(monkeypatch)
    _http(monkeypatch, m, 401,
          '{"error":{"message":"Incorrect API key provided: sk-abcdef123456789."}}')
    code, msg = m.probe()
    assert code == 1
    assert "sk-abcdef123456789" not in msg, msg
    assert "sk-***" in msg, msg


def test_the_body_is_truncated(monkeypatch):
    m = _mod(); _env(monkeypatch)
    _http(monkeypatch, m, 500, "x" * 5000)
    assert len(m.probe()[1]) < 500


# ── the switch and the wiring ─────────────────────────────────────────────────────

def test_the_switch_skips_without_calling_out(monkeypatch):
    m = _mod(); _env(monkeypatch, ENVGEN_PREFLIGHT="0")
    def _never(*a, **k):
        raise AssertionError("the switch did not prevent the call")
    monkeypatch.setattr(m.urllib.request, "urlopen", _never)
    assert m.main() == 0


def test_main_returns_the_probe_code(monkeypatch, capsys):
    m = _mod(); _env(monkeypatch); _http(monkeypatch, m, 429, _QUOTA_BODY)
    assert m.main() == 1
    assert "REFUSED" in capsys.readouterr().out


def test_the_launcher_refuses_only_on_a_definitive_refusal():
    """★ Testing the caller, not just the helper. The launcher must exit on 1 and CONTINUE on
    2 — treating an inconclusive probe as a refusal would block launches on a network blip."""
    src = open(_LAUNCH, encoding="utf-8").read()
    assert "preflight_credential.py" in src, "the launcher does not run the preflight"
    # #943: the section is delimited by the launcher's OWN `# --- … ---` markers, not by a
    # byte count. A window sized in bytes stops covering the code the moment a comment above
    # it grows, and this ratchet has caught me doing it more than once.
    i = src.index("preflight_credential.py")
    nxt = src.find("\n# ---", i)
    window = src[i:nxt if nxt != -1 else len(src)]
    assert 'PF_RC=$?' in window, window
    assert '[ "$PF_RC" = "1" ]' in window, (
        "the launcher does not gate on exit code 1 exactly — a `-ne 0` test would refuse on "
        "an inconclusive probe")
    assert "exit 1" in window


def test_the_launcher_checks_python_before_using_it():
    """The preflight is now the FIRST use of $PYTHON, so a caller without it got a bare
    `python: command not found` instead of the sentence it needs."""
    src = open(_LAUNCH, encoding="utf-8").read()
    py = src.index('command -v "$PYTHON"')
    pf = src.index("preflight_credential.py")
    assert py < pf, "the PYTHON check must come before the first use of it"
    assert "REFUSED: PYTHON=" in src


def test_the_preflight_runs_before_the_slow_ones():
    """Two seconds of HTTP must not sit behind a playwright install."""
    src = open(_LAUNCH, encoding="utf-8").read()
    assert src.index("preflight_credential.py") < src.index("playwright install")
