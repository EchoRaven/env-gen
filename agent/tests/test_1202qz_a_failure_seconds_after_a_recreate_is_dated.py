r"""#1202qz: a tool that judged the live app says how old the stack was.

tiktok-r129, to the second:

    20:47:58  compose `up -d` finished (both frontend and backend created)
    20:48:07  the backend logged "Application startup complete"
    20:48:12  the verifier wrote ui_smoke_fyp_feed_logged_out_502_failure.png
    20:48:27  it filed P1 "Frontend same-origin API proxy returns 502 for
              GET /api/videos/feed while backend API is healthy"
    20:48:56  the backend lane claimed the task

A triage-and-dispatch chain on a stack twenty-nine seconds old.

The note says ONLY how old the stack is, because that is the only part that was measured. Two
explanations for that 502 were tried and both falsified: nginx holding a stale upstream IP (both
containers are recreated together, so nginx re-resolves) and the backend still booting when the
screenshot was written (uvicorn was serving five seconds earlier). A tool that hands over a
verdict it cannot support is how #1202qp's 401 hint rewrote a contract.

Both producing paths carry it -- `browser_navigate` and `test_api` -- because a guard on one
branch of a harm with two is the shape this repo has paid for before (#934).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "env_generator" / "llm_generator")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from multi_agent.runtime import compose_mutex as CM  # noqa: E402
from tools import runtime_tools as RT  # noqa: E402


def _row(age_s: float) -> str:
    started = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return "abc123 " + started.isoformat().replace("+00:00", "Z")


# --- the age itself ----------------------------------------------------------------------

def test_the_age_is_the_youngest_container(monkeypatch):
    """A recreate replaces containers one at a time; what matters is the last one up."""
    monkeypatch.setattr(CM, "stack_identity_1202ne",
                        lambda cf, **kw: frozenset({_row(600), _row(20), _row(300)}))
    age = CM.stack_age_s_1202qz("/nowhere/docker-compose.yml")
    assert 15 <= age <= 40


def test_nanosecond_stamps_parse():
    """Docker emits RFC3339 with nine fractional digits; fromisoformat takes six."""
    stamp = "2026-09-18T01:47:58.351294081Z"
    assert CM.stack_age_s_1202qz.__doc__  # the helper exists
    # parsed through the real code path
    import types
    fake = types.SimpleNamespace()
    got = {}

    def _ident(cf, **kw):
        return frozenset({"abc " + stamp})
    orig = CM.stack_identity_1202ne
    CM.stack_identity_1202ne = _ident
    try:
        age = CM.stack_age_s_1202qz("/nowhere/docker-compose.yml")
    finally:
        CM.stack_identity_1202ne = orig
    assert age is not None and age > 0


def test_an_unreadable_stack_has_no_age(monkeypatch):
    monkeypatch.setattr(CM, "stack_identity_1202ne", lambda cf, **kw: None)
    assert CM.stack_age_s_1202qz("/nowhere/docker-compose.yml") is None


def test_a_stopped_stack_has_no_age(monkeypatch):
    monkeypatch.setattr(CM, "stack_identity_1202ne", lambda cf, **kw: frozenset())
    assert CM.stack_age_s_1202qz("/nowhere/docker-compose.yml") is None


# --- the note ----------------------------------------------------------------------------

class _Hubs:
    def __init__(self, base):
        self.base_dir = base


def _project(tmp_path):
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    return _Hubs(str(tmp_path))


def test_the_r129_age_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(CM, "stack_age_s_1202qz", lambda cf, **kw: 29.0)
    note = RT._young_stack_note_1202qz(_project(tmp_path))
    assert "29s ago" in note and "#1202qz" in note


def test_an_older_stack_gets_no_note(tmp_path, monkeypatch):
    monkeypatch.setattr(CM, "stack_age_s_1202qz",
                        lambda cf, **kw: RT._YOUNG_STACK_S_1202QZ + 1)
    assert RT._young_stack_note_1202qz(_project(tmp_path)) == ""


def test_the_note_names_no_cause(tmp_path, monkeypatch):
    """Both explanations tried for r129's 502 were falsified; the note must not pick one."""
    monkeypatch.setattr(CM, "stack_age_s_1202qz", lambda cf, **kw: 10.0)
    note = RT._young_stack_note_1202qz(_project(tmp_path)).lower()
    for invented in ("nginx", "upstream", "still booting", "not listening", "dns"):
        assert invented not in note


def test_no_hubs_no_note():
    assert RT._young_stack_note_1202qz(None) == ""


def test_a_project_without_compose_gets_no_note(tmp_path):
    assert RT._young_stack_note_1202qz(_Hubs(str(tmp_path))) == ""


# --- both producing paths carry it --------------------------------------------------------

def test_browser_navigate_attaches_it():
    src = (ROOT / "env_generator" / "llm_generator" / "tools" / "browser"
           / "core.py").read_text(encoding="utf-8")
    nav = src[src.index("class BrowserNavigateTool"):src.index("def _is_extension_error")]
    assert "_young_stack_note_1202qz" in nav
    assert "def set_agent" in nav, "without the agent binding the note can never be produced"


def test_test_api_attaches_it():
    src = (ROOT / "env_generator" / "llm_generator" / "tools"
           / "runtime_tools.py").read_text(encoding="utf-8")
    assert src.count("_young_stack_note_1202qz(self._hubs)") == 1
