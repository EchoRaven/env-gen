"""#234 (r24/r25, live): a deleted playwright browser binary silently blinded every
runtime UI gate for two whole runs (102 launch failures in r25 alone) because a
walk that cannot run reports ran=False and infra never blocks. The heal: detect
the permanent missing-executable signature, `playwright install` once per
process, retry."""
import types

from env_generator.llm_generator.tools.browser import _bootstrap as bb


def setup_function(_fn):
    bb.reset_for_tests()


def test_signature_detection():
    assert bb.is_missing_executable(
        "BrowserType.launch: Executable doesn't exist at /x/chrome-headless-shell")
    assert not bb.is_missing_executable("net::ERR_CONNECTION_REFUSED")
    assert not bb.is_missing_executable(RuntimeError("timeout 30000ms exceeded"))


def test_non_matching_error_never_spawns_install(monkeypatch):
    calls = []
    monkeypatch.setattr(bb.subprocess, "run",
                        lambda *a, **k: calls.append(a) or types.SimpleNamespace(returncode=0))
    assert bb.heal_missing_browser(RuntimeError("page crashed")) is False
    assert not calls


def test_matching_error_installs_once_per_process(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(bb.subprocess, "run", fake_run)
    err = "BrowserType.launch: Executable doesn't exist at /x"
    assert bb.heal_missing_browser(err) is True          # first: installs, retry-worthy
    assert bb.heal_missing_browser(err) is False         # once-guard: no second install
    assert len(calls) == 1
    assert "playwright" in calls[0] and "install" in calls[0]
    assert "chromium" in calls[0] and "chromium-headless-shell" in calls[0]


def test_failed_install_reports_not_retry_worthy(monkeypatch):
    monkeypatch.setattr(
        bb.subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    assert bb.heal_missing_browser("Executable doesn't exist at /x") is False


def test_install_exception_never_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(bb.subprocess, "run", boom)
    assert bb.heal_missing_browser("Executable doesn't exist at /x") is False
