r"""#1202tl: `is_business` answers TRUE when blind, and said nothing about it.

```python
try:
    from .kickoff.contract import is_control_surface_path
    if is_control_surface_path(p):
        return False
except Exception:
    pass
return True            # ← blind ⇒ "yes, a business endpoint"
```

Its own docstring says what that costs: a control-surface path mis-classified as business
"gets REQUIRED — for implementation AND for business_chain COVERAGE — even though it is served
by the control plane and the verifier can never chain it. **outlook M2 wedged on exactly this:
business_chain_api_coverage listed the spine endpoints as uncovered → 7 stuck cycles → abort**."

So the failure mode is not hypothetical, it is the one this function was written to prevent —
and the `except Exception: pass` re-creates it silently. Simulated by breaking the helper:
`/api/v1/tenants`, `/api/v1/reset` and `/api/v1/admin/init-tenant` all flip to business at once.

THE ANSWER IS DELIBERATELY UNCHANGED. The path net only ever REMOVES from the business set, so
failing open is the safer direction, and `#1202gd`'s lesson is that the damage came from the
SILENCE — a dead exemption path that ran as a "zero behaviour change" green light across a
whole corpus — not from the default. What changes is that the silence ends.

`#1201`'s channel exists for exactly this: *"treat this as the mechanism being OFF, not as a
transient."* Found by enumerating predicate functions whose error path is silent or permissive
— ten in the package, and this is the one that gates delivery, through
`all_business_endpoints_implemented`.

The other nine were checked and cleared, which is worth recording so they are not re-chased:
`_is_process_alive` returns True on `PermissionError` because the process genuinely EXISTS and
is merely unsignalable, and `_is_dark_hex` defaults an unparseable colour to "dark", which
gates nothing.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import lifecycle  # noqa: E402
from multi_agent.runtime import message_format as mf  # noqa: E402
from multi_agent.runtime.kickoff import contract as kc  # noqa: E402

_SITE = "lifecycle.is_business.control_surface"
_CONTROL = ("/api/v1/tenants", "/api/v1/reset", "/api/v1/admin/init-tenant")


@pytest.fixture
def warnings_seen(monkeypatch):
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.WARNING)
    root = logging.getLogger()
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.WARNING)
    mf._WARNED_1201.discard(_SITE)
    try:
        yield buf
    finally:
        root.removeHandler(handler)
        root.setLevel(old)
        mf._WARNED_1201.discard(_SITE)


def _blind(monkeypatch):
    def boom(*a, **k):
        raise ImportError("simulated: the exemption path is dead")
    monkeypatch.setattr(kc, "is_control_surface_path", boom)


def test_the_healthy_path_is_silent(warnings_seen):
    """A warning on the working path would be noise, and #1201's channel is how an auditor
    finds mechanisms that are actually off."""
    for p in _CONTROL + ("/api/videos", "/health"):
        lifecycle.is_business({"path": p})
    assert warnings_seen.getvalue().count("#1201") == 0


def test_the_healthy_path_still_exempts_the_control_surface():
    """Non-vacuity: the thing being protected must actually work."""
    for p in _CONTROL:
        assert lifecycle.is_business({"path": p}) is False
    assert lifecycle.is_business({"path": "/api/videos"}) is True


def test_a_blind_guard_says_so(warnings_seen, monkeypatch):
    _blind(monkeypatch)
    lifecycle.is_business({"path": "/api/v1/tenants"})
    out = warnings_seen.getvalue()
    assert "#1201" in out
    assert "control-surface exemption" in out
    assert "BUSINESS endpoint" in out, "the message must name the CONSEQUENCE, not the error"


def test_it_says_so_once_not_per_endpoint(warnings_seen, monkeypatch):
    """#1201 is once-per-site by design; a per-call warning would bury the run's log."""
    _blind(monkeypatch)
    for p in _CONTROL:
        lifecycle.is_business({"path": p})
    assert warnings_seen.getvalue().count("#1201") == 1


def test_the_answer_is_unchanged_when_blind(monkeypatch):
    """Deliberate: the path net only ever REMOVES, so failing open is the safer direction.
    This pins that the fix is about visibility, not about flipping the default."""
    _blind(monkeypatch)
    for p in _CONTROL:
        assert lifecycle.is_business({"path": p}) is True


def test_the_handler_is_not_a_bare_pass_any_more():
    """The rule: a guard around a DECISION must not be silent."""
    src = (LLM_DIR / "multi_agent" / "runtime" / "lifecycle.py").read_text(encoding="utf-8")
    body = src[src.index("def is_business("):]
    body = body[:body.index("\ndef ", 1)]
    assert "warn_once_1201" in body
    assert "except Exception:\n        pass" not in body
