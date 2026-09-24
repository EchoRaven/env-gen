r"""#1202tm: the unwired-page reporter returned [] when it could not look, and said nothing.

```python
try:
    return ui_page_delivery_blockers(Path(app_root) / "frontend" / "src", workhub)
except Exception:
    return []
```

This produces `deliverability_ui_page_unwired` — the most frequent blocker in the corpus. An
empty list means the gate sees ZERO unwired pages, so "could not look" and "nothing to find"
reach every reader as the same answer. And the check is deliberately NOT relaxed on a
functionally-validated app: its own docstring says api_smoke "never opens a frontend page, so
an unwired page (round 44's blank-screen-but-api_smoke-green class) must still block delivery".
A silent detector fault is exactly that blind spot, reopened.

★ THE RIGHT TREATMENT IS TEN LINES ABOVE IT, in the same function. `#1067` says of the
duplicate-route reporter: *"this run has no duplicate-route findings because the reporter
raised, not because there are none. Logged once per process."* One fact, two emitters, the
guard on one of them — and the same function even argues elsewhere against a "try/except-pass
— because that would skip the report silently".

THE VERDICT IS LEFT ALONE, exactly as `#1067` left it: turning a detector fault into a blocker
would wedge a run on the framework's own error, which is the opposite of what a gate is for.
Only the silence goes.

Found by narrowing 111 silent empty-collection returns to the ones inside the module that
PRODUCES blockers, then to the ones bypassing that module's own channels (`#790`/`#791`/`#792`
/`#1201`) — 23 → 2. The other is `_filters_708b`, which returns `{}` when a registry lookup
fails; that one only omits a filter hint from a report ("…and /api/titles takes kind, genre,
language"), so blindness costs a less helpful sentence, not a false verdict. Left alone, and
recorded here so it is not re-chased.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import io
import logging
import sys
import tempfile
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime import deliverability as dv  # noqa: E402
from multi_agent.runtime import frontend_audit as fa  # noqa: E402


@pytest.fixture
def seen():
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.WARNING)
    root = logging.getLogger()
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.WARNING)
    dv._WIRING_REPORT_FAILED_1202TM["said"] = False
    try:
        yield buf
    finally:
        root.removeHandler(handler)
        root.setLevel(old)
        dv._WIRING_REPORT_FAILED_1202TM["said"] = False


def _args():
    """The shapes production passes: `(hub_registry, app_root)`.

    My first version of this test passed a Path as `hub_registry`, so the function returned at
    its `workhub is None` guard and NEVER reached the line under test — both halves green and
    both meaningless. The fixture has to reach line 498 or this file proves nothing.
    """
    d = Path(tempfile.mkdtemp())
    (d / "frontend" / "src").mkdir(parents=True)
    hub = types.SimpleNamespace(
        workhub=types.SimpleNamespace(list_tasks=lambda: []),
        registryhub=types.SimpleNamespace(get_endpoints=lambda: {}, get_ui_pages=lambda: {}))
    return hub, d


def test_the_fixture_actually_reaches_the_reporter(monkeypatch):
    """Non-vacuity, pinned: if this stops being called, the tests below mean nothing."""
    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return []

    monkeypatch.setattr(fa, "ui_page_delivery_blockers", spy)
    hub, d = _args()
    dv._ui_page_wiring_blockers(hub, d)
    assert called["n"] == 1, "the fixture never reached the reporter — fix the fixture"


def test_the_healthy_path_is_silent(seen):
    hub, d = _args()
    dv._ui_page_wiring_blockers(hub, d)
    assert seen.getvalue().count("#1202tm") == 0


def test_a_blind_reporter_says_so(seen, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated reporter fault")

    monkeypatch.setattr(fa, "ui_page_delivery_blockers", boom)
    hub, d = _args()
    assert dv._ui_page_wiring_blockers(hub, d) == []
    out = seen.getvalue()
    assert "#1202tm" in out
    assert "not because every page is wired" in out, (
        "the message must name the CONSEQUENCE — an empty list is indistinguishable from a "
        "clean app without it")


def test_it_says_so_once_per_process(seen, monkeypatch):
    """#1067's cadence, matched: a per-tick warning would bury the run's log."""
    def boom(*a, **k):
        raise RuntimeError("simulated reporter fault")

    monkeypatch.setattr(fa, "ui_page_delivery_blockers", boom)
    hub, d = _args()
    for _ in range(3):
        dv._ui_page_wiring_blockers(hub, d)
    assert seen.getvalue().count("#1202tm") == 1


def test_the_verdict_is_unchanged_when_blind(monkeypatch):
    """Deliberate, and the same call #1067 made: a detector fault must not become a blocker,
    or the run wedges on the framework's own error."""
    def boom(*a, **k):
        raise RuntimeError("simulated reporter fault")

    monkeypatch.setattr(fa, "ui_page_delivery_blockers", boom)
    hub, d = _args()
    assert dv._ui_page_wiring_blockers(hub, d) == []


def test_the_sibling_report_still_exists():
    """This fix exists because #1067 was right. If #1067's report ever goes, this rationale
    goes with it and someone should notice."""
    src = (LLM_DIR / "multi_agent" / "runtime" / "deliverability.py").read_text(
        encoding="utf-8")
    assert "#1067 duplicate-route report SKIPPED" in src
    assert "not because there are none" in src
