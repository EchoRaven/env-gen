"""#1202gb -- the server already diagnosed the opaque 400; carry the diagnosis out.

The generated app maps every SQLAlchemy DataError to 400 {"detail": "invalid field value"}
— deliberately, since a real API does not leak SQL to callers — and logs the real cause
next to it: "DataError on GET /api/videos -> 400: orig=...". The chain sees only the
response, so the step fails with a message naming no field, no value, no table.

tiktok-r97 measured the cost: once #1202ga removed the auth wall the requests reached the
handlers and hit this on /api/videos, /api/explore and /api/messages at once. The lane
reverse-engineered the cause from the bare string (the seed stores TikTok counters as
"25.5M"/"251.3K" in TEXT columns, so a raw ::bigint blows up) and wrote it into a docstring
— work the server had already done and thrown away.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.runtime import chain_executor as CE  # noqa: E402

LOGS = (
    "backend-1  | INFO:     172.18.0.1:1 - \"GET /api/health HTTP/1.1\" 200\n"
    "backend-1  | ERROR:app.integrity:DataError on GET /api/videos -> 400: "
    "orig=invalid input syntax for type bigint: \"25.5M\"\n"
    "backend-1  | ERROR:app.integrity:DataError on GET /api/explore -> 400: "
    "orig=invalid input syntax for type bigint: \"251.3K\"\n"
)


def _seed(monkeypatch, logs=LOGS):
    CE._integrity_detail_1202gb.__defaults__[-1].clear()   # the per-project cache
    monkeypatch.setattr(CE, "_integrity_detail_1202gb",
                        CE._integrity_detail_1202gb)       # keep the real function
    return logs


def _call(monkeypatch, tmp_path, method, path, note, logs=LOGS):
    proj = tmp_path / "proj"
    (proj / "docker").mkdir(parents=True, exist_ok=True)
    (proj / "docker" / "docker-compose.yml").write_text("services: {}\n")
    CE._integrity_detail_1202gb.__defaults__[-1].clear()
    import multi_agent.runtime.validation_runner as VR
    monkeypatch.setattr(VR, "_backend_logs_tail", lambda *a, **k: logs)
    return CE._integrity_detail_1202gb(proj, method, path, note)


def test_the_logged_cause_reaches_the_step(monkeypatch, tmp_path):
    got = _call(monkeypatch, tmp_path, "GET", "/api/videos",
                '400 {"detail":"invalid field value"}')
    assert "25.5M" in got and "bigint" in got, got


def test_the_line_matching_THIS_path_is_chosen(monkeypatch, tmp_path):
    got = _call(monkeypatch, tmp_path, "GET", "/api/explore",
                '400 {"detail":"invalid field value"}')
    assert "251.3K" in got, f"picked another path's line: {got}"


def test_silent_for_any_other_failure(monkeypatch, tmp_path):
    """It must not staple database logs onto unrelated failures."""
    assert _call(monkeypatch, tmp_path, "GET", "/api/videos", "404 not found") == ""
    assert _call(monkeypatch, tmp_path, "POST", "/api/videos", "500 boom") == ""


def test_silent_when_the_logs_say_nothing_about_it(monkeypatch, tmp_path):
    assert _call(monkeypatch, tmp_path, "GET", "/api/videos",
                 '400 {"detail":"invalid field value"}',
                 logs="backend-1  | INFO: started\n") == ""


def test_missing_compose_is_not_a_crash(monkeypatch, tmp_path):
    CE._integrity_detail_1202gb.__defaults__[-1].clear()
    assert CE._integrity_detail_1202gb(tmp_path / "nope", "GET", "/api/videos",
                                       '400 {"detail":"invalid field value"}') == ""


def test_the_detail_is_capped(monkeypatch, tmp_path):
    huge = "backend-1 | ERROR:app.integrity:DataError on GET /api/videos -> 400: " + "x" * 5000
    got = _call(monkeypatch, tmp_path, "GET", "/api/videos",
                '400 {"detail":"invalid field value"}', logs=huge + "\n")
    assert 0 < len(got) <= 400


def test_it_is_wired_to_the_failing_step(monkeypatch):
    """A detector nobody calls is #1202's most expensive recurring defect."""
    import inspect
    src = inspect.getsource(CE)
    i = src.index('entry["sent_body"] = _sent_body_1202ew')
    window = src[i:src.index("recorded.append(entry)", i)]
    assert "_integrity_detail_1202gb" in window, "computed but never attached"
    assert "server_detail" in window
