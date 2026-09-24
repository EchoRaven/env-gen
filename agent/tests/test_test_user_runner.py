"""Browser test-user engine: structured report + feedback formatting + graceful
failure. (The live browser run is integration-tested against a running app; here we
cover the pure pieces so they never regress.) LOCAL-ONLY."""
import sys, asyncio, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; LLM = ROOT/"env_generator"/"llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path: sys.path.insert(0, str(_p))
from multi_agent.runtime.test_user_runner import (  # noqa
    run_browser_test_user, format_feedback, judge_against_references,
    _drive_auth_form, _fill_visible_inputs)


# --- fakes modelling a real browser form (no playwright/chromium needed) ---
class _FakeInput:
    def __init__(self, typ="text", name="", placeholder=""):
        self.typ, self.name, self.placeholder, self.value = typ, name, placeholder, ""
    async def get_attribute(self, a):
        return {"type": self.typ, "name": self.name, "placeholder": self.placeholder}.get(a)
    async def input_value(self):
        return self.value
    async def fill(self, v):
        self.value = v


class _FakeBtn:
    def __init__(self, page):
        self.page = page
    async def count(self):
        return 1
    async def is_visible(self):
        return True
    async def click(self, timeout=None):
        self.page.advance()


class _FakeLoc:
    def __init__(self, items):
        self._items = items
    @property
    def first(self):
        return self._items[0]
    async def all(self):
        return self._items
    async def count(self):
        return len(self._items)


class _StagedLogin:
    """email -> Next -> password -> Sign in -> token (the Microsoft/Google flow)."""
    def __init__(self, single_step=False):
        self.step, self.token, self.single = 0, None, single_step
        self.email = _FakeInput("email", "email", "Email")
        self.pw = _FakeInput("password", "password", "Password")
    def locator(self, sel):
        if "input" in sel:
            if self.single:
                vis = [self.email, self.pw] if self.step == 0 else []
            else:
                vis = [self.email] if self.step == 0 else ([self.pw] if self.step == 1 else [])
            return _FakeLoc(vis)
        return _FakeLoc([_FakeBtn(self)])
    async def evaluate(self, js):
        return self.token
    async def wait_for_timeout(self, ms):
        return None
    def advance(self):
        if self.single:
            if self.email.value and self.pw.value:
                self.token, self.step = "tok-1", 1
            return
        if self.step == 0 and self.email.value:
            self.step = 1
        elif self.step == 1 and self.pw.value:
            self.token, self.step = "tok-1", 2


_CREDS = {"email": "t@example.com", "password": "Probe123!x", "name": "Test User"}


def test_drive_auth_form_handles_multi_step_login():
    page = _StagedLogin(single_step=False)
    token = asyncio.run(_drive_auth_form(page, _CREDS))
    assert token == "tok-1" and page.step == 2  # advanced through email -> password


def test_drive_auth_form_handles_single_step_login():
    page = _StagedLogin(single_step=True)
    token = asyncio.run(_drive_auth_form(page, _CREDS))
    assert token == "tok-1"


def test_fill_visible_inputs_does_not_clobber_filled_fields():
    page = _StagedLogin(single_step=True)
    page.email.value = "already@set.com"
    asyncio.run(_fill_visible_inputs(page, _CREDS))
    assert page.email.value == "already@set.com"  # left as-is
    assert page.pw.value == _CREDS["password"]     # empty one got filled





def _make_png(path: Path) -> None:
    # 1x1 transparent PNG — enough to be a real file map_reference_screens accepts.
    import base64
    path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))


def test_judge_against_references_attaches_verdicts_and_flags_mismatch():
    d = Path(tempfile.mkdtemp())
    (d / "outlook_inbox.png").touch(); _make_png(d / "outlook_inbox.png")
    (d / "outlook_calendar.png").touch(); _make_png(d / "outlook_calendar.png")
    shot_inbox = d / "shot_inbox.png"; _make_png(shot_inbox)
    shot_cal = d / "shot_calendar.png"; _make_png(shot_cal)
    rep = {"ran": True, "summary": "", "steps": [],
           "pages": [
               {"name": "inbox", "route": "/inbox", "ok": True, "blank": False,
                "console_errors": [], "shot": str(shot_inbox)},
               {"name": "calendar", "route": "/calendar", "ok": True, "blank": False,
                "console_errors": [], "shot": str(shot_cal)}],
           "shots": {"inbox": str(shot_inbox), "calendar": str(shot_cal)}}

    async def fake_judge(llm, screen, shot):
        sim = 0.40 if "inbox" in screen["route"] else 0.90
        return {"similarity": sim, "dimensions": {},
                "deviations": ["missing folder rail"] if sim < 0.65 else [],
                "summary": "off" if sim < 0.65 else "good"}

    refs = [str(d / "outlook_inbox.png"), str(d / "outlook_calendar.png")]
    out = asyncio.run(judge_against_references(rep, refs, llm=None,
                                               judge_fn=fake_judge, min_similarity=0.65))
    inbox = [p for p in out["pages"] if p["route"] == "/inbox"][0]
    cal = [p for p in out["pages"] if p["route"] == "/calendar"][0]
    assert inbox["visual"]["similarity"] == 0.40 and inbox["visual"]["passed"] is False
    assert cal["visual"]["similarity"] == 0.90 and cal["visual"]["passed"] is True
    # only the failing page is rolled up as a mismatch
    assert out["visual_mismatches"] == ["inbox"]


def test_judge_against_references_no_refs_is_noop():
    rep = {"ran": True, "pages": [{"name": "x", "route": "/x", "shot": None}], "shots": {}}
    out = asyncio.run(judge_against_references(rep, [], llm=None, judge_fn=None))
    assert out is rep and out.get("visual_mismatches", []) == []


def test_format_feedback_renders_visual_mismatch():
    rep = {"ran": True, "summary": "auth_ok=True; pages=1", "steps": [],
           "pages": [{"name": "inbox", "route": "/inbox", "blank": False, "console_errors": [],
                      "visual": {"similarity": 0.40, "passed": False,
                                 "deviations": ["missing folder rail", "wrong theme"]}}],
           "visual_mismatches": ["inbox"]}
    msg = format_feedback(rep)
    assert "/inbox" in msg and "0.40" in msg
    assert "missing folder rail" in msg and "reference" in msg.lower()


def test_format_feedback_surfaces_failures_and_blank_pages():
    rep = {"ran": True, "summary": "auth_ok=False; pages=2",
           "steps": [{"step": "auth flow stores a token + navigates", "ok": False,
                      "note": "submit did nothing: token=False"}],
           "pages": [{"route": "/inbox", "blank": True, "console_errors": []},
                     {"route": "/calendar", "blank": False, "console_errors": ["TypeError: x is undefined"]}]}
    msg = format_feedback(rep)
    assert "FAIL" in msg and "submit did nothing" in msg
    assert "/inbox" in msg and "BLANK" in msg
    assert "/calendar" in msg and "console errors" in msg


def test_format_feedback_not_run():
    assert "could not run" in format_feedback({"ran": False, "summary": "playwright unavailable: x"})


def test_runner_graceful_when_app_unreachable():
    # connection refused -> ran False/structured, never raises into the loop
    out = Path(tempfile.mkdtemp())
    rep = asyncio.run(run_browser_test_user("http://127.0.0.1:59999",
          [{"name": "p", "route": "/x", "auth": False}], out, register=False,
          chrome_path="/home/haibotong/.cache/ms-playwright/chromium-1140/chrome-linux/chrome"))
    assert isinstance(rep, dict) and "summary" in rep  # no exception


if __name__ == "__main__":
    import pytest; raise SystemExit(pytest.main([__file__, "-q"]))
